#!/usr/bin/env python3
"""
DEFAULT HIDES:
    GRUB_HIDDEN_TIMEOUT (deprecated/confusing)
    GRUB_RECORDFAIL_TIMEOUT (Ubuntu-specific)
    GRUB_DISABLE_SUBMENU (rarely changed)
    GRUB_DISTRIBUTOR (cosmetic)
    GRUB_GFXMODE (advanced)
    GRUB_GFXPAYLOAD_LINUX (very advanced)
    GRUB_VIDEO_BACKEND (troubleshooting only)
    GRUB_INIT_TUNE (novelty)
    GRUB_ENABLE_CRYPTODISK (specialized)
    GRUB_TERMINAL_INPUT (advanced)
    GRUB_DISABLE_LINUX_UUID (rare)
    GRUB_CMDLINE_LINUX_RECOVERY (edge case)
    GRUB_DISABLE_LINUX_PARTUUID (rare)
    GRUB_TERMINAL_OUTPUT (server/serial)
    GRUB_SERIAL_COMMAND (server/serial)
    GRUB_PRELOAD_MODULES (server/troubleshooting)
    GRUB_BADRAM (rare hardware issue)
"""

from ruamel.yaml import YAML
from pathlib import Path
from typing import Set, Dict, Any, Optional

from .UserConfigDir import get_user_config_dir

yaml = YAML()
yaml.default_flow_style = False


class WizHider:
    """
    Manages the persistent storage and state for hidden parameters and suppressed warnings.
    Supports both hard-hiding (excluded from everything) and soft-hiding (hidden from UI
    but still validated and written to config).
    """

    def __init__(self, user_config=None, filename: str = 'hidden-items.yaml'):
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

        self.hard_params: Set[str] = set()  # Hard-hidden params (excluded from everything)
        self.soft_params: Set[str] = set()  # Soft-hidden params (hidden from UI only)
        self.warns: Set[str] = set()        # Suppressed warnings (e.g., 'GRUB_DEFAULT.3')
        self.dirty_count: int = 0
        self.last_read_time: Optional[float] = None

        # Suck up the file on startup (initial refresh)
        # Note: config_dir is already created by UserConfigDir
        self.refresh()

    def refresh(self):
        """Reads the hidden items from the YAML file, clearing the current state on failure."""
        self.hard_params.clear()
        self.soft_params.clear()
        self.warns.clear()
        self.last_read_time = None
        self.dirty_count = 0 # Assume file state is clean
        
        if not self.yaml_path.exists():
            return
            
        try:
            with self.yaml_path.open('r') as f:
                data: Dict[str, Any] = yaml.load(f) or {}
                
            # Safely cast list data to sets
            self.hard_params.update(set(data.get('hard_params', [])))
            self.soft_params.update(set(data.get('soft_params', [])))
            self.warns.update(set(data.get('warns', [])))
            
            # Record file modification time
            self.last_read_time = self.yaml_path.stat().st_mtime
            
        except (IOError, yaml.YAMLError) as e:
            # Any failure leads to empty sets, allowing the application to continue.
            print(f"Warning: Failed to read hidden-items.yaml: {e}")

    def write_if_dirty(self) -> bool:
        """Writes the current hidden state to disk if the dirty count is > 0."""
        if self.dirty_count == 0:
            return False

        data = {
            'hard_params': sorted(list(self.hard_params)),
            'soft_params': sorted(list(self.soft_params)),
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

    def hide_hard_param(self, name: str):
        """Hides a parameter by name (e.g., 'GRUB_DEFAULT')."""
        if name in self.soft_params:
            self.soft_params.remove(name)
            self.dirty_count += 1
        if name not in self.hard_params:
            self.hard_params.add(name)
            self.dirty_count += 1

    def hide_soft_param(self, name: str):
        """Hides a parameter by name (e.g., 'GRUB_DEFAULT')."""
        if name in self.hard_params:
            self.hard_params.remove(name)
            self.dirty_count += 1
        if name not in self.soft_params:
            self.soft_params.add(name)
            self.dirty_count += 1

    def unhide_param(self, name: str):
        """Unhides a parameter by name (removes from both hard and soft)."""
        if name in self.hard_params:
            self.hard_params.remove(name)
            self.dirty_count += 1
        if name in self.soft_params:
            self.soft_params.remove(name)
            self.dirty_count += 1

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
            
    def is_hidden_param(self, name: str) -> bool:
        """Checks if a parameter should be hidden."""
        return name in self.soft_params or name in self.hard_params

    def is_hidden_soft_param(self, name: str) -> bool:
        """Checks if a parameter should be hidden."""
        return name in self.soft_params

    def is_hidden_hard_param(self, name: str) -> bool:
        """Checks if a parameter should be hidden."""
        return name in self.hard_params

    def is_hidden_warn(self, composite_id: str) -> bool:
        """Checks if a warning should be suppressed."""
        return composite_id in self.warns

    def is_dirty(self) -> bool:
        """Indicates if there are unsaved changes."""
        return self.dirty_count > 0

    def get_last_read_time(self) -> Optional[float]:
        """Returns the last file modification time when the file was read."""
        return self.last_read_time
