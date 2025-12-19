#!/usr/bin/env python3
""" TBD"""
# pylint: disable=line-too-long,invalid-name,broad-exception-caught
import os
import sys
import shutil
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union

from .UserConfigDir import UserConfigDir

# --- Constants ---

GRUB_DEFAULT_PATH = Path("/etc/default/grub")
USER_CONFIG = UserConfigDir.get_singleton("grub-wiz")
GRUB_CONFIG_DIR = USER_CONFIG.config_dir

# Regex pattern for identifying backup files: YYYYMMDD-HHMMSS-{CHECKSUM}.{TAG}.bak
BACKUP_FILENAME_PATTERN = re.compile(
    r"(\d{8}-\d{6})-([0-9a-fA-F]{8})\.([a-zA-Z0-9_-]+)\.bak$"
)

# --- Class Implementation ---

class BackupMgr:
    """
    Manages backups for the /etc/default/grub configuration file.
    Backups are stored in the real user's ~/.config/grub-wiz/ location.
    """

    def __init__(self, target_path: Path = GRUB_DEFAULT_PATH, user_config=None):
        self.target_path = target_path

        # Use provided user_config or get singleton
        self.user_config = user_config if user_config else USER_CONFIG
        self.config_dir = self.user_config.config_dir

    # --- calc_checksum, get_backups, and restore_backup remain the same ---
    # (Leaving these out for brevity in the response, but they are included in the full file block)

    def calc_checksum(self, source: Union[Path, str]) -> str:
        """ TBD """
        content = b''

        if isinstance(source, Path):
            if not source.exists():
                return ""
            try:
                content = source.read_bytes()
            except Exception:
                # print(f"Error reading file {source} for checksum: {e}", file=sys.stderr)
                return ""
        elif isinstance(source, str):
            content = source.encode('utf-8')
        else:
            raise TypeError("Source must be a Path or a string.")

        return hashlib.sha256(content).hexdigest()[:8].upper()


    def get_backups(self) -> Dict[str, Path]:
        """ TBD """
        backups: Dict[str, Path] = {}
        for file_path in self.config_dir.iterdir():
            match = BACKUP_FILENAME_PATTERN.search(file_path.name)
            if match:
                checksum = match.group(2).upper()
                backups[checksum] = file_path
        return backups

    def restore_backup(self, backup_file: Path, dest_path: Optional[Path] = None) -> bool:
        """ TBD """
        destination = dest_path if dest_path is not None else self.target_path

        if os.geteuid() != 0:
            print(f"Error: Root permissions required to write to {destination}.", file=sys.stderr)
            return False

        if not backup_file.exists():
            print(f"Error: Backup file {backup_file} not found.", file=sys.stderr)
            return False

        try:
            shutil.copy2(backup_file, destination)
            os.chmod(destination, 0o644)

            print(f"Success: Restored {backup_file.name} to {destination}")
            return True
        except Exception as e:
            print(f"Error restoring backup to {destination}: {e}", file=sys.stderr)
            return False
    # -----------------------------------------------------------------------


    def create_backup(self, tag: str, file_to_backup: Optional[Path] = None, checksum: Optional[str] = None) -> Optional[Path]:
        """
        Creates a new backup file for the target path and sets ownership to the real user.
        """
        target = file_to_backup if file_to_backup is not None else self.target_path

        if not target.exists():
            print(f"Error: Target file {target} does not exist. Skipping backup.", file=sys.stderr)
            return None

        current_checksum = checksum if checksum else self.calc_checksum(target)
        if not current_checksum:
            return None

        existing_backups = self.get_backups()
        if current_checksum in existing_backups:
            print(f"Info: File is identical to existing backup: {existing_backups[current_checksum].name}. Skipping new backup.")
            return existing_backups[current_checksum]

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        new_filename = f"{timestamp}-{current_checksum}.{tag}.bak"
        new_backup_path = self.config_dir / new_filename

        try:
            # Copy the file to the backup location (done as root)
            shutil.copy2(target, new_backup_path)

            # Set ownership to real user
            self.user_config.give_to_user(new_backup_path, mode=0o644)
            existing_backups = self.get_backups()

            print(f"Success: Created new backup: {new_backup_path.name}")
            return new_backup_path
        except Exception as e:
            print(f"Error creating backup file {new_filename}: {e}", file=sys.stderr)
            return None
