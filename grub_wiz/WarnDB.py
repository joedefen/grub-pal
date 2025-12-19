#!/usr/bin/env python3
"""
TBD
"""
# pylint: disable=too-many-instance-attributes

from pathlib import Path
from typing import Set, Dict, Any, Optional
from ruamel.yaml import YAML, YAMLError


from .UserConfigDir import UserConfigDir

yaml = YAML()
yaml.default_flow_style = False


class WarnDB:
    """
    Manages the persistent storage and state for the warnings database.
    Stores all warning info with severity levels and tracks which warnings
    are suppressed (inhibited).
    """

    def __init__(self, param_cfg, filename: str = 'warn-db.yaml'):
        """
        Initializes the class, creates the config directory if necessary,
        and performs the initial read/refresh.

        Args:
            user_config: UserConfigDir instance (uses singleton if not provided)
            filename: Name of the YAML file to store warning database
        """
        self.user_config = UserConfigDir.get_singleton("grub-wiz")
        self.config_dir: Path = self.user_config.config_dir
        self.yaml_path: Path = self.config_dir / filename
        self.param_cfg = param_cfg # has out-of-box state

        self.inhibits: Set[str] = set()   # Suppressed/inhibited warnings (keys)
        self.all_info: Dict[str, int] = {}  # All warning info: key -> severity (1-4)
        self.dirty_count: int = 0
        self.last_read_time: Optional[float] = None
        self.audited: bool = False  # Track if audit_info() has been called

        # Suck up the file on startup (initial refresh)
        # Note: config_dir is already created by UserConfigDir
        self.refresh()

    def refresh(self):
        """
            Reads the warning database from the YAML file.
            If file doesn't exist, starts with empty state (normal on first run).
        """
        self.last_read_time = None
        self.dirty_count = 0 # Assume file state is clean

        # File not existing is normal on first run - start fresh
        if not self.yaml_path.exists():
            self.inhibits.clear()
            return True

        try:
            with self.yaml_path.open('r') as f:
                data: Dict[str, Any] = yaml.load(f) or {}

            # Safely cast list data to sets
            self.inhibits = set(data.get('warns', []))

            # Record file modification time
            self.last_read_time = self.yaml_path.stat().st_mtime
            return True

        except (IOError, YAMLError) as e:
            # Only warn on actual errors (not missing file)
            print(f"Warning: Failed to read {self.yaml_path.name}: {e}")
            self.inhibits.clear()
            return True

    def write_if_dirty(self) -> bool:
        """Writes the current hidden state to disk if the dirty count is > 0."""
        if self.dirty_count == 0:
            return False

        data = {
            'warns': sorted(list(self.inhibits))
        }

        try:
            # 1. Write the file
            with self.yaml_path.open('w') as f:
                yaml.dump(data, f)

            # 2. Set ownership and permissions (crucial when running as root)
            self.user_config.give_to_user(self.yaml_path, mode=0o600)

            # 3. Update state
            self.dirty_count = 0
            self.last_read_time = self.yaml_path.stat().st_mtime
            return True

        except OSError as e:
            print(f"Error writing or setting permissions on {self.yaml_path.name}: {e}")
            return False

    def inhibit(self, composite_id: str, hide: bool):
        """Hides a warning by composite ID (e.g., 'GRUB_DEFAULT.3')."""
        hidden = self.is_inhibit(composite_id)
        if hide and not hidden:
            self.inhibits.add(composite_id)
            self.dirty_count += 1
        elif not hide and hidden:
            self.inhibits.remove(composite_id)
            self.dirty_count += 1

    def is_inhibit(self, composite_id: str) -> bool:
        """Checks if a warning should be suppressed."""
        return composite_id in self.inhibits

    def audit_info(self, all_warn_info: dict):
        """
        Update the warning database with current validation info.
        Should only be called once per instantiation.

        Args:
            all_warn_info: Dict mapping warning keys to severity levels (1-4)

        Actions:
        - Updates all_info with current warnings and severities
        - Removes orphaned keys from suppressed warnings list
        - Updates severity if changed
        """
        if self.audited:
            return  # Already audited this session

        self.audited = True

        # Update all_info with new data (write with sorted keys so looks good)
        self.all_info = {k: all_warn_info[k] for k in sorted(all_warn_info)}

        # Purge orphaned suppressed warnings
        orphans = []
        for key in self.inhibits:
            if key not in all_warn_info:
                orphans.append(key)

        for key in orphans:
            self.inhibits.discard(key)
            self.dirty_count += 1

    def is_dirty(self) -> bool:
        """Indicates if there are unsaved changes."""
        return self.dirty_count > 0

    def get_last_read_time(self) -> Optional[float]:
        """Returns the last file modification time when the file was read."""
        return self.last_read_time
