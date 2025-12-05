#!/usr/bin/env python3 

import os
import sys
import re
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union, List

GRUB_DEFAULT_PATH = Path("/etc/default/grub")

GRUB_CONFIG_DIR = Path.home() / ".config" / "grub-pal" # The backup folder

# Regex pattern for identifying backup files: YYYYMMDD-HHMMSS-{CHECKSUM}.{TAG}.bak
# We use the regex to ensure we only process valid files.
BACKUP_FILENAME_PATTERN = re.compile(
    r"(\d{8}-\d{6})-([0-9a-fA-F]{8})\.([a-zA-Z0-9_-]+)\.bak$"
)

class BackupMgr:
    """
    Manages backups for the /etc/default/grub configuration file.
    Backups are stored in ~/.config/grub-buddy/ with a structured filename.
    """
    
    def __init__(self, target_path: Path = GRUB_DEFAULT_PATH, config_dir: Path = GRUB_CONFIG_DIR):
        """
        Initializes the backup manager with target file and config directory.
        """
        self.target_path = target_path
        self.config_dir = config_dir
        
        # Ensure the config directory exists upon instantiation
        self._ensure_config_dir()


    def _ensure_config_dir(self):
        """
        Ensures the backup directory exists. Creates it if necessary.
        """
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            # The 'cd' functionality is implicitly handled by using self.config_dir in other methods.
        except Exception as e:
            # Handle potential permissions issues if the user's home directory is locked, 
            # though this should generally not happen for ~/.config
            print(f"Error: Could not ensure backup directory {self.config_dir} exists: {e}", file=sys.stderr)
            sys.exit(1)


    def calc_checksum(self, source: Union[Path, str]) -> str:
        """
        Calculates an 8-character hex checksum (first 8 chars of SHA256) 
        from file contents or a provided string.
        """
        content = b''
        
        if isinstance(source, Path):
            if not source.exists():
                return "" # Return empty string if path does not exist
            try:
                # Need to read as binary to avoid encoding issues with readlines
                content = source.read_bytes()
            except Exception as e:
                print(f"Error reading file {source} for checksum: {e}", file=sys.stderr)
                return ""
        elif isinstance(source, str):
            content = source.encode('utf-8')
        else:
            raise TypeError("Source must be a Path or a string.")

        # Calculate SHA-256 and return the first 8 hex characters (uppercase)
        return hashlib.sha256(content).hexdigest()[:8].upper()


    def get_backups(self) -> Dict[str, Path]:
        """
        Returns a dictionary mapping the 8-char checksum to the full Path object 
        of all valid backup files in the config directory.
        """
        backups: Dict[str, Path] = {}
        
        for file_path in self.config_dir.iterdir():
            match = BACKUP_FILENAME_PATTERN.search(file_path.name)
            
            if match:
                # Group 2 is the 8-hex-digit checksum
                checksum = match.group(2).upper()
                backups[checksum] = file_path

        return backups


    def create_backup(self, tag: str, file_to_backup: Optional[Path] = None, checksum: Optional[str] = None) -> Optional[Path]:
        """
        Creates a new backup file for the target path.
        
        Args:
            tag: A short, descriptive tag (alphanumeric/hyphen/underscore).
            file_to_backup: The path to the file to backup (defaults to self.target_path).
            checksum: Pre-calculated checksum (optional).
            
        Returns:
            The Path object of the created backup file, or None on failure/skip.
        """
        target = file_to_backup if file_to_backup is not None else self.target_path

        if not target.exists():
            print(f"Error: Target file {target} does not exist. Skipping backup.", file=sys.stderr)
            return None
        
        current_checksum = checksum if checksum else self.calc_checksum(target)
        if not current_checksum:
            return None # Checksum calculation failed

        # Check if a file with this checksum already exists in the backup directory
        # This handles the "if not there, skip" logic for identical files.
        existing_backups = self.get_backups()
        if current_checksum in existing_backups:
            print(f"Info: File is identical to existing backup: {existing_backups[current_checksum].name}. Skipping new backup.")
            return existing_backups[current_checksum]
        
        # Format the date/time string
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        
        # Construct the new filename
        new_filename = f"{timestamp}-{current_checksum}.{tag}.bak"
        new_backup_path = self.config_dir / new_filename

        try:
            # Copy the file to the backup location
            shutil.copy2(target, new_backup_path)
            print(f"Success: Created new backup: {new_backup_path.name}")
            return new_backup_path
        except Exception as e:
            print(f"Error creating backup file {new_filename}: {e}", file=sys.stderr)
            return None
    
    def delete_backup(self, backup_file: Path) -> bool:
        """ Delete the given backup file."""
        pass


    def restore_backup(self, backup_file: Path, dest_path: Optional[Path] = None) -> bool:
        """
        Restores a backup file to the /etc/default/grub location. REQUIRES ROOT.
        
        Args:
            backup_file: The Path object of the backup file to restore.
            dest_path: The destination path (defaults to /etc/default/grub).
            
        Returns:
            True on successful restore, False otherwise.
        """
        destination = dest_path if dest_path is not None else self.target_path
        
        if os.geteuid() != 0:
            print(f"Error: Root permissions required to write to {destination}.", file=sys.stderr)
            return False

        if not backup_file.exists():
            print(f"Error: Backup file {backup_file} not found.", file=sys.stderr)
            return False

        try:
            # Copy the backup file over the destination file
            shutil.copy2(backup_file, destination)
            print(f"Success: Restored {backup_file.name} to {destination}")
            return True
        except Exception as e:
            print(f"Error restoring backup to {destination}: {e}", file=sys.stderr)
            return False

# --- Example Usage (Requires a mock environment to run without root) ---

if __name__ == '__main__':
    # --- MOCKING: Setup a temporary environment for testing without root ---
    print("--- Backup Manager Demonstration (Using Mock Paths) ---")
    mock_config_dir = Path("./mock_grub_config")
    mock_target_path = Path("./mock_grub_default")
    
    # Clean up and setup mock files/directories
    if mock_config_dir.exists(): shutil.rmtree(mock_config_dir)
    mock_target_path.write_text("GRUB_TIMEOUT=5\nGRUB_DEFAULT=0\n")
    
    # Initialize Manager with mock paths
    mgr = BackupMgr(target_path=mock_target_path, config_dir=mock_config_dir)
    
    print(f"Config Directory: {mgr.config_dir}")

    # 1. Calculate Checksum
    checksum_orig = mgr.calc_checksum(mock_target_path)
    print(f"\n1. Initial Checksum: {checksum_orig}")

    # 2. Create 'orig' Backup
    orig_backup = mgr.create_backup("orig")
    print(f"2. Original Backup created: {orig_backup.name if orig_backup else 'Failed'}")
    
    # 3. Create 'orig' Backup again (should skip)
    print("\n3. Attempting to create identical backup (should skip):")
    skipped_backup = mgr.create_backup("orig", checksum=checksum_orig)
    print(f"   Skipped/Found existing backup: {skipped_backup.name if skipped_backup else 'Failed'}")

    # 4. Modify the file and create a 'custom' backup
    print("\n4. Modifying file and creating 'custom' backup.")
    mock_target_path.write_text("GRUB_TIMEOUT=2\nGRUB_DEFAULT=saved\n")
    checksum_custom = mgr.calc_checksum(mock_target_path)
    print(f"   New Checksum: {checksum_custom}")
    custom_backup = mgr.create_backup("custom", checksum=checksum_custom)
    
    # 5. List Backups
    print("\n5. Listing all available backups (by checksum):")
    all_backups = mgr.get_backups()
    for cs, path in all_backups.items():
        print(f"   [{cs}] -> {path.name}")
        
    # 6. Restore a Backup (Mocking root permission check for demo)
    print("\n6. Attempting to restore the 'orig' backup (requires root in real app).")
    # For this demo, we'll manually copy since we aren't root:
    print(f"   (Restoring {orig_backup.name} over {mock_target_path})")
    shutil.copy2(orig_backup, mock_target_path) 
    
    # Verify restore
    restored_content = mock_target_path.read_text()
    print(f"   Content after mock restore:\n{restored_content.strip()}")
    
    # --- MOCKING: Cleanup ---
    if mock_config_dir.exists(): shutil.rmtree(mock_config_dir)
    if mock_target_path.exists(): mock_target_path.unlink()
    print("\n--- Demo Cleanup Complete ---")
