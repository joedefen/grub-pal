#!/usr/bin/env python3
"""
Handles updating /etc/default/grub and running grub-install
"""
# pylint: disable=line-too-long,invalid-name,broad-exception-caught

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Tuple, List
from .DistroVars import DistroVars

class GrubWriter:
    """
    A class for safely writing and updating GRUB configuration files.

    This class caches the system's GRUB update command on initialization,
    avoiding repeated lookups during the session.
    """

    def __init__(self, distro_vars: DistroVars):
        """
        Initialize the GrubWriter.

        Args:
            distro_vars: DistroVars instance containing distribution-specific paths and commands
        """
        self.distro_vars = distro_vars
        self.etc_grub = self.distro_vars.etc_grub

        # Cache the grub update command and config file path at initialization
        self.update_grub = distro_vars.update_grub
        self.grub_cfg = distro_vars.grub_cfg

    def run_grub_update(self) -> Tuple[bool, str]:
        """
        Executes the appropriate GRUB update command found on the system.
        This step is MANDATORY after modifying /etc/default/grub.

        Returns:
            A tuple (success: bool, message: str)
        """
        if os.geteuid() != 0:
            return False, "ERROR: root required to run GRUB update command"

        if not self.update_grub:
            return False, "ERROR: cannot find GRUB update cmd"

        # Build the command array
        command_to_run: List[str] = [self.update_grub]

        if self.update_grub.endswith('-mkconfig') and self.grub_cfg:
            # If using grub-mkconfig or grub2-mkconfig,
            # we must provide the output flag and path
            command_to_run.extend(["-o", str(self.grub_cfg)])

        print(f"+  {' '.join(command_to_run)}")
        try:
            # Execute the command
            result = subprocess.run( command_to_run, capture_output=True,
                text=True, check=False)

            # Check for success
            if result.returncode != 0:
                error_output = result.stdout.strip() + "\n" + result.stderr.strip()
                return False, (
                    f"GRUB Update Failed: Command {' '.join(command_to_run)} returned an error (Exit code {result.returncode}).\n"
                    f"---------------------------------------------------\n"
                    f"{error_output}"
                )

            print(f"OK: GRUB config rebuilt: Output:\n{result.stdout.strip()}")
            return True, 'OK'

        except Exception as e:
            return False, f"An unexpected error occurred during GRUB update execution: {e}"

    # def commit_validated_grub_config(self, contents: str) -> Tuple[bool, str]:
    def commit_validated_grub_config(self, temp_path: Path) -> Tuple[bool, str]:
        """
        Safely commits new GRUB configuration contents to the target file.

        The process is:
        1. Write contents to a secure temporary file.
        2. If validation succeeds, copy the temporary file over the target_path.
        3. Explicitly set permissions to 644 (rw-r--r--) for security and readability.
        4. If validation fails, delete the temporary file and return the error.

        NOTE: The caller should call run_grub_update() immediately after this method
        if commit is successful.

        Args:
            contents: The new content of the /etc/default/grub file as a string.

        Returns:
            A tuple (success: bool, message: str)
            - If success is True, message is a confirmation.
            - If success is False, message contains the error and grub-script-check output.
        """
        # 1. Check for root permissions
        if os.geteuid() != 0:
            return False, f"Permission Error: Root access is required to modify {self.etc_grub} and run validation/update tools."


        try:
            # --- Step 2: Commit/Copy the Validated File ---
            print(f'+ cp {str(temp_path)!r} {str(self.etc_grub)!r}')
            shutil.copy2(temp_path, self.etc_grub)

            # --- Step 3: Explicitly set permissions to 644 (rw-r--r--) ---
            # This guarantees the standard permissions for /etc/default/grub
            # The octal '0o644' means: owner (6=rw-), group (4=r--), others (4=r--)
            os.chmod(self.etc_grub, 0o644)

            return True, f"OK: replaced {self.etc_grub!r}"

        except PermissionError:
            return False, f"Permission Error: Cannot write to {self.etc_grub} or execute GRUB utilities."

        except Exception as e:
            return False, f"An unexpected error occurred during commit: {e}"

        finally:
            # --- Step 4: Clean up the temporary file ---
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    print(f"Warning: Failed to rm temp file {temp_path}: {e}",
                          file=sys.stderr)
