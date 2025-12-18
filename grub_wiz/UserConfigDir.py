#!/usr/bin/env python3
"""
Singleton class for managing user configuration directory and file ownership.
Handles the common case of scripts running as root but needing to store files
in the real user's home directory.
"""
# pylint: disable=broad-exception-caught,invalid-name

import os
import sys
import pwd
from pathlib import Path
from typing import Optional


class UserConfigDir:
    """
    Singleton class for managing user configuration directory.
    Handles detection of real user (even when running via sudo) and
    provides utilities for setting correct file ownership.
    """
    singleton = None
    _instance: Optional['UserConfigDir'] = None

    def __new__(cls, app_name: str = "grub-wiz"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, app_name: str = "grub-wiz"):
        # Only initialize once (singleton pattern)
        if UserConfigDir.singleton:
            raise RuntimeError("Use UserConfigDir.get_singleton(), not constructor")
        UserConfigDir.singleton = self

        self.app_name = app_name
        self._detect_user()
        self._ensure_config_dir()
    
    @staticmethod
    def get_singleton(app_name: str = 'grub-wiz'):
        """ Get or create the UserConfigDir singleton instance.
        Args: app_name: Application name for config directory
        Returns: UserConfigDir singleton instance
        """
        if not UserConfigDir.singleton:
            UserConfigDir.singleton = UserConfigDir(app_name)
        return UserConfigDir.singleton

    def _detect_user(self):
        """
        Identifies the real user who initiated the script, regardless of sudo.
        Prioritizes os.getlogin() over SUDO_USER for reliability.
        """
        real_username = None

        # Try to get the login name of the terminal owner (most reliable)
        try:
            real_username = os.getlogin()
        except OSError:
            # Fallback to SUDO_USER if getlogin fails
            real_username = os.environ.get('SUDO_USER')

        if real_username:
            try:
                # Get user info structure based on the determined username
                user_info = pwd.getpwnam(real_username)

                self.home = Path(user_info.pw_dir)
                self.uid = user_info.pw_uid
                self.gid = user_info.pw_gid
                self.config_dir = self.home / ".config" / self.app_name
                return
            except KeyError:
                # User lookup failed (e.g., deleted account or bad SUDO_USER)
                pass

        # Default to current effective user's information (fallback)
        self.home = Path.home()
        self.uid = os.geteuid()
        self.gid = os.getegid()
        self.config_dir = self.home / ".config" / self.app_name

    def _ensure_config_dir(self):
        """
        Ensures the config directory exists and is owned by the real user.
        """
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Set ownership to real user if running as root
            if os.geteuid() == 0:
                os.chown(self.config_dir, self.uid, self.gid)
                # Set directory permissions: rwx for owner, rx for group/others
                os.chmod(self.config_dir, 0o755)

        except Exception as e:
            print(f"Error: Could not create config directory {self.config_dir}: {e}",
                  file=sys.stderr)
            sys.exit(1)

    def give_to_user(self, filepath: Path, mode: int = 0o644):
        """
        Sets ownership and permissions on a file to match the real user.

        Args:
            filepath: Path to the file
            mode: Unix file permissions (default: 0o644 = rw-r--r--)

        Only changes ownership if running as root.
        """
        if not filepath.exists():
            print(f"Warning: Cannot set ownership on non-existent file: {filepath}",
                  file=sys.stderr)
            return

        try:
            # Set permissions
            os.chmod(filepath, mode)

            # Set ownership (only when running as root)
            if os.geteuid() == 0:
                os.chown(filepath, self.uid, self.gid)

        except Exception as e:
            print(f"Warning: Could not set ownership/permissions on {filepath}: {e}",
                  file=sys.stderr)

    def get_user_info(self) -> dict:
        """
        Returns dictionary with user information for backward compatibility.

        Returns:
            {'home': Path, 'uid': int, 'gid': int, 'config_dir': Path}
        """
        return {
            'home': self.home,
            'uid': self.uid,
            'gid': self.gid,
            'config_dir': self.config_dir
        }
