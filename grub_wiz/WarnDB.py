#!/usr/bin/env python3
"""
TBD
"""

from pathlib import Path
from typing import Set, Dict, Any, Optional
from ruamel.yaml import YAML, YAMLError


from .UserConfigDir import get_user_config_dir

yaml = YAML()
yaml.default_flow_style = False


class WarnDB:
    """
    Manages the persistent storage and state for the warnings database.
    Stores all warning info with severity levels and tracks which warnings
    are suppressed (inhibited).
    """

    def __init__(self, param_cfg,
                 user_config=None, filename: str = 'hidden-items.yaml'):
        """
        Initializes the class, creates the config directory if necessary,
        and performs the initial read/refresh.

        Args:
            user_config: UserConfigDir instance (uses singleton if not provided)
            filename: Name of the YAML file to store hidden items
        """
        self.user_config = user_config if user_config else get_user_config_dir("grub-wiz")
        self.config_dir: Path = self.user_config.config_dir
        self.yaml_path: Path = self.config_dir / filename
        self.param_cfg = param_cfg # has out-of-box state

        # self.params: Set[str] = set()  # hidden params (excluded from everything)
        self.warns: Set[str] = set()   # Suppressed/inhibited warnings (keys)
        self.all_info: Dict[str, int] = {}  # All warning info: key -> severity (1-4)
        self.dirty_count: int = 0
        self.last_read_time: Optional[float] = None
        self.audited: bool = False  # Track if audit_info() has been called

        # Suck up the file on startup (initial refresh)
        # Note: config_dir is already created by UserConfigDir
        self.refresh()

    def init_hides(self):
        """ Initialize warns database (no longer used for params). """
        # No initialization needed - warns are populated dynamically
        return True

    def refresh(self):
        """
            Reads the hidden items from the YAML file,
            clearing the current state on failure.
        """
        # self.params.clear()
        self.warns.clear()
        self.last_read_time = None
        self.dirty_count = 0 # Assume file state is clean

        if not self.yaml_path.exists():
            return self.init_hides()

        try:
            with self.yaml_path.open('r') as f:
                data: Dict[str, Any] = yaml.load(f) or {}

            # Safely cast list data to sets
            # self.params.update(set(data.get('params', [])))
            self.warns.update(set(data.get('warns', [])))

            # Record file modification time
            self.last_read_time = self.yaml_path.stat().st_mtime
            return True

        except (IOError, YAMLError) as e:
            # Any failure leads to empty sets, allowing the application to continue.
            print(f"Warning: Failed to read hidden-items.yaml: {e}")
            return self.init_hides()

    def write_if_dirty(self) -> bool:
        """Writes the current hidden state to disk if the dirty count is > 0."""
        if self.dirty_count == 0:
            return False

        data = {
            # 'params': sorted(list(self.params)),
            'warns': sorted(list(self.warns))
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
            print(f"Error writing or setting permissions on hidden-items.yaml: {e}")
            return False

#   def hide_param(self, name: str):
#       """Hides a parameter by name (e.g., 'GRUB_DEFAULT')."""
#       if name not in self.params:
#           self.params.add(name)
#           self.dirty_count += 1


#   def unhide_param(self, name: str):
#       """Unhides a parameter by name."""
#       if name in self.params:
#           self.params.remove(name)
#           self.dirty_count += 1

    def hide_warn(self, composite_id: str):
        """Hides a warning by composite ID (e.g., 'GRUB_DEFAULT.3')."""
        if composite_id not in self.warns:
            self.warns.add(composite_id)
            self.dirty_count += 1

    def unhide_warn(self, composite_id: str):
        """Unhides a warning by composite ID."""
        if composite_id in self.warns:
            self.warns.remove(composite_id)
            self.dirty_count += 1

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

        # Update all_info with new data
        self.all_info = all_warn_info.copy()

        # Purge orphaned suppressed warnings
        orphans = []
        for key in self.warns:
            if key not in all_warn_info:
                orphans.append(key)

        for key in orphans:
            self.warns.discard(key)
            self.dirty_count += 1

#   def is_hidden_param(self, name: str) -> bool:
#       """Checks if a parameter should be hidden."""
#       return name in self.params

    def is_hidden_warn(self, composite_id: str) -> bool:
        """Checks if a warning should be suppressed."""
        return composite_id in self.warns

    def is_dirty(self) -> bool:
        """Indicates if there are unsaved changes."""
        return self.dirty_count > 0

    def get_last_read_time(self) -> Optional[float]:
        """Returns the last file modification time when the file was read."""
        return self.last_read_time
