#!/usr/bin/env python3
"""
Handles updating /etc/default/grub and running grub-install
"""
# pylint: disable=line-too-long,invalid-name,broad-exception-caught

import os
import sys
import shutil
import subprocess
import glob
from pathlib import Path
from typing import Tuple, List, Dict
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
            # Execute the command - output streams directly to terminal
            result = subprocess.run(command_to_run, check=False)

            # Check for success
            if result.returncode != 0:
                return False, (
                    f"GRUB Update Failed: Command returned exit code {result.returncode}"
                )

            print("OK: GRUB config rebuilt")
            return True, 'OK'

        except Exception as e:
            return False, f"An unexpected error occurred during GRUB update execution: {e}"

    def should_rebuild_initramfs(self, diffs: dict) -> Tuple[bool, str, str]:
        """
        Determines if initramfs rebuild is needed based on parameter changes.

        Checks if changes to GRUB_CMDLINE_LINUX, GRUB_CMDLINE_LINUX_DEFAULT,
        or GRUB_CMDLINE_LINUX_RECOVERY contain keywords that affect early boot
        (GPU drivers, KMS, module loading, etc.).

        Args:
            diffs: Dictionary of parameter changes {param_name: (old_value, new_value)}

        Returns:
            Tuple of (needs_rebuild: bool, trigger_keyword: str, category: str)
            - needs_rebuild: True if initramfs rebuild is recommended
            - trigger_keyword: The specific keyword that triggered the recommendation
            - category: The category of the trigger (e.g., 'gpu_drivers', 'kernel_mode_setting')
        """
        # Parameters that affect early boot
        initramfs_params = {
            'GRUB_CMDLINE_LINUX',
            'GRUB_CMDLINE_LINUX_DEFAULT',
            'GRUB_CMDLINE_LINUX_RECOVERY',
        }

        # Flatten all trigger keywords from distro_vars
        triggers = self.distro_vars.initramfs_triggers
        if not triggers:
            return False, '', ''

        for param_name, (old_val, new_val) in diffs.items():
            if param_name not in initramfs_params:
                continue

            # Combine old and new values to check for any trigger keywords
            combined_cmdline = f"{old_val} {new_val}".lower()

            # Check each category of triggers
            for category, keywords in triggers.items():
                for keyword in keywords:
                    if keyword.lower() in combined_cmdline:
                        return True, keyword, category

        return False, '', ''

    def check_initramfs_space(self) -> Dict[str, any]:
        """
        Check if there's enough disk space in /boot to rebuild initramfs.

        Calculates space needed based on existing initramfs file sizes.
        Initramfs rebuild creates new files before deleting old ones,
        so we need approximately 2x the current size + safety margin.

        Returns:
            Dictionary with:
            - 'boot_path': Path to boot directory
            - 'free_mb': Free space in MB
            - 'needed_mb': Estimated space needed for rebuild in MB
            - 'existing_size_mb': Current size of all initramfs files in MB
            - 'existing_files': List of initramfs file paths found
            - 'is_sufficient': True if enough space available
            - 'is_critical': True if space is critically low
            - 'message': Human-readable status message
        """
        # Determine boot partition path from grub_cfg location
        boot_path = Path('/boot')
        if self.grub_cfg:
            grub_cfg_path = Path(self.grub_cfg)
            # grub.cfg is usually in /boot/grub or /boot/grub2
            # Find the /boot ancestor
            for parent in grub_cfg_path.parents:
                if parent.name == 'boot':
                    boot_path = parent
                    break

        try:
            # Find all initramfs/initrd files in /boot
            # Different distros use different naming conventions
            patterns = [
                str(boot_path / 'initrd.img-*'),
                str(boot_path / 'initrd-*'),
                str(boot_path / 'initramfs-*'),
                str(boot_path / 'initramfs.img-*'),
            ]

            existing_files = []
            for pattern in patterns:
                existing_files.extend(glob.glob(pattern))

            # Calculate total size of existing initramfs files
            total_size_bytes = 0
            for filepath in existing_files:
                try:
                    total_size_bytes += os.path.getsize(filepath)
                except OSError:
                    pass  # Skip files we can't stat

            existing_size_mb = total_size_bytes / (1024 * 1024)

            # Calculate space needed:
            # - 2x existing size (new files created before old ones deleted)
            # - +50MB safety margin for temp files and overhead
            safety_margin_mb = 50
            needed_mb = (existing_size_mb * 2) + safety_margin_mb

            # Check available space
            stat = os.statvfs(boot_path)
            free_bytes = stat.f_bavail * stat.f_frsize
            free_mb = free_bytes / (1024 * 1024)

            is_sufficient = free_mb >= needed_mb
            # Critical if we don't even have 1x the size (will likely fail mid-rebuild)
            is_critical = free_mb < existing_size_mb

            # Generate message
            if is_critical:
                message = (
                    f"CRITICAL: Only {free_mb:.0f}MB free in {boot_path}, "
                    f"but need ~{needed_mb:.0f}MB for rebuild.\n"
                    f"  Existing initramfs files: {existing_size_mb:.0f}MB\n"
                    f"  Rebuild creates new files before deleting old ones.\n"
                    f"  FREE UP SPACE or system may become unbootable!"
                )
            elif not is_sufficient:
                message = (
                    f"WARNING: Only {free_mb:.0f}MB free in {boot_path}, "
                    f"recommend {needed_mb:.0f}MB.\n"
                    f"  May work, but cutting it close. Consider freeing space first."
                )
            else:
                surplus_mb = free_mb - needed_mb
                message = (
                    f"OK: {free_mb:.0f}MB free in {boot_path} "
                    f"(need ~{needed_mb:.0f}MB, surplus: {surplus_mb:.0f}MB)"
                )

            return {
                'boot_path': str(boot_path),
                'free_mb': free_mb,
                'needed_mb': needed_mb,
                'existing_size_mb': existing_size_mb,
                'existing_files': existing_files,
                'is_sufficient': is_sufficient,
                'is_critical': is_critical,
                'message': message,
            }

        except Exception as e:
            # If we can't check space, return safe defaults (assume it's risky)
            return {
                'boot_path': str(boot_path),
                'free_mb': -1,
                'needed_mb': -1,
                'existing_size_mb': -1,
                'existing_files': [],
                'is_sufficient': False,
                'is_critical': False,
                'message': f"Unable to check disk space: {e}",
            }

    def run_initramfs_update(self) -> Tuple[bool, str]:
        """
        Executes the appropriate initramfs update command for this distribution.

        Returns:
            A tuple (success: bool, message: str)
        """
        if os.geteuid() != 0:
            return False, "ERROR: root required to rebuild initramfs"

        initramfs_cmd = self.distro_vars.update_initramfs
        if not initramfs_cmd:
            return False, "WARNING: No initramfs update command found on this system"

        # Determine command name (basename) to choose proper arguments
        cmd_name = os.path.basename(initramfs_cmd)

        # Build command with distribution-specific arguments
        if cmd_name == 'update-initramfs':
            # Debian/Ubuntu: update all kernels
            command_to_run = [initramfs_cmd, '-u', '-k', 'all']
        elif cmd_name == 'dracut':
            # RHEL/Fedora/SUSE: regenerate all kernels, force overwrite
            command_to_run = [initramfs_cmd, '--regenerate-all', '--force']
        elif cmd_name == 'mkinitcpio':
            # Arch: process all presets
            command_to_run = [initramfs_cmd, '-P']
        elif cmd_name == 'mkinitfs':
            # Alpine: regenerate for current kernel
            command_to_run = [initramfs_cmd]
        elif cmd_name == 'genkernel':
            # Gentoo: regenerate initramfs
            command_to_run = [initramfs_cmd, '--install', 'initramfs']
        else:
            # Unknown command, try with no arguments
            command_to_run = [initramfs_cmd]

        print(f"+  {' '.join(command_to_run)}")
        try:
            # Execute the command - output streams directly to terminal
            result = subprocess.run(command_to_run, check=False)

            # Check for success
            if result.returncode != 0:
                return False, (
                    f"Initramfs rebuild failed: {' '.join(command_to_run)} "
                    f"returned exit code {result.returncode}"
                )

            print("OK: Initramfs rebuilt")
            return True, 'OK'

        except Exception as e:
            return False, f"Unexpected error during initramfs rebuild: {e}"

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
