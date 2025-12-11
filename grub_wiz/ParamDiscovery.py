#!/usr/bin/env python3
"""
Discovers which GRUB parameters are supported on this system by parsing
the installed GRUB documentation (info pages).

Results are cached in ~/.config/grub-wiz/system-params.yaml for performance.
"""

import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Set, Tuple
from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False

# Discovery status states
STATE_NO_INFO = "NO_INFO"              # info command not found or GRUB docs not installed
STATE_CANNOT_PARSE = "CANNOT_PARSE_INFO"  # info ran but parsing failed
STATE_OK = "OK"                        # Successfully discovered parameters

# Cache refresh interval (1 week in seconds)
WEEK_IN_SECONDS = 7 * 24 * 60 * 60


class ParamDiscovery:
    """Discovers and caches system-supported GRUB parameters"""

    def __init__(self, config_dir: Path = None):
        """
        Args:
            config_dir: Directory for cached results. Defaults to ~/.config/grub-wiz/
        """
        if config_dir is None:
            config_dir = Path.home() / '.config' / 'grub-wiz'

        self.config_dir = Path(config_dir)
        self.cache_file = self.config_dir / 'system-params.yaml'

    def discover_params(self) -> tuple[Set[str], str]:
        """
        Parse 'info grub' to discover system-supported GRUB parameters.

        Returns:
            Tuple of (parameter_set, status_state)
            - parameter_set: Set of parameter names
            - status_state: One of STATE_NO_INFO, STATE_CANNOT_PARSE, STATE_OK
        """
        params = set()

        try:
            # Get the "Simple configuration" section from GRUB info pages
            result = subprocess.run(
                ['info', '-f', 'grub', '-n', 'Simple configuration', '--output=-'],
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )

            if result.returncode != 0:
                print(f"Warning: info command failed (return code {result.returncode})")
                print("GRUB documentation may not be installed.")
                return params, STATE_NO_INFO

            # Parse output for GRUB parameter references
            # Common patterns in info pages:
            # 'GRUB_TIMEOUT'
            # `GRUB_DEFAULT'
            # GRUB_CMDLINE_LINUX

            # Pattern 1: Quoted parameters 'GRUB_*' or `GRUB_*'
            for match in re.finditer(r"[`']?(GRUB_[A-Z_0-9]+)[`']?", result.stdout):
                param = match.group(1)
                # Sanity check: reasonable length (avoid false positives)
                if 10 <= len(param) <= 40:
                    params.add(param)

            # Filter out likely false positives (rare but possible)
            # Real parameters don't have multiple underscores in a row
            params = {p for p in params if '__' not in p}

            # Determine status based on parsing results
            if len(params) > 0:
                return params, STATE_OK
            else:
                # Info ran but we couldn't parse any parameters
                print("Warning: Could not parse any parameters from info output")
                return params, STATE_CANNOT_PARSE

        except subprocess.TimeoutExpired:
            print("Warning: info command timed out")
            return params, STATE_NO_INFO
        except FileNotFoundError:
            print("Warning: 'info' command not found on system")
            return params, STATE_NO_INFO
        except Exception as e:
            print(f"Warning: Unexpected error during parameter discovery: {e}")
            return params, STATE_CANNOT_PARSE

    def save_params(self, params: Set[str], state: str) -> None:
        """
        Save discovered parameters and status to YAML cache file.

        Args:
            params: Set of parameter names
            state: Discovery state (STATE_NO_INFO, STATE_CANNOT_PARSE, or STATE_OK)
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Convert set to sorted list for readable YAML
        params_list = sorted(params)
        current_time = int(time.time())

        data = {
            'discovered_params': params_list,
            'status': {
                'state': state,
                'unixtime': current_time
            },
            'source': 'info grub',
            'note': 'Parameters not in this list will be hard-hidden by default'
        }

        with open(self.cache_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f)

    def load_cached_data(self) -> Optional[dict]:
        """
        Load cached discovery data including params and status.

        Returns:
            Dictionary with 'params', 'state', and 'timestamp', or None if cache doesn't exist
        """
        if not self.cache_file.exists():
            return None

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = yaml.load(f)

            if not data:
                return None

            # Extract status info
            status = data.get('status', {})
            state = status.get('state', STATE_NO_INFO)
            timestamp = status.get('unixtime', 0)

            # Extract params
            params = set(data.get('discovered_params', []))

            return {
                'params': params,
                'state': state,
                'timestamp': timestamp
            }
        except Exception as e:
            print(f"Warning: Failed to load cache file: {e}")
            return None

    def should_regenerate(self, cached_data: Optional[dict]) -> bool:
        """
        Determine if discovery should be re-run based on cached status.

        Logic:
        - If NO_INFO: Retry to see if info/docs are now installed
        - If CANNOT_PARSE or OK: Only retry if > 1 week old

        Args:
            cached_data: Cached discovery data from load_cached_data()

        Returns:
            True if discovery should be re-run
        """
        if cached_data is None:
            return True  # No cache exists, must run

        state = cached_data['state']
        timestamp = cached_data['timestamp']
        age_seconds = int(time.time()) - timestamp

        if state == STATE_NO_INFO:
            # Always retry - maybe docs were installed
            return True

        if state in (STATE_CANNOT_PARSE, STATE_OK):
            # Retry if > 1 week old
            return age_seconds > WEEK_IN_SECONDS

        # Unknown state, play it safe and regenerate
        return True

    def get_system_params(self, force_regenerate: bool = False) -> Set[str]:
        """
        Get system-supported parameters, using cache if available.

        Args:
            force_regenerate: If True, ignore cache and re-discover

        Returns:
            Set of parameter names supported on this system
        """
        # Load cached data
        cached_data = self.load_cached_data()

        # Check if we should use cache
        if not force_regenerate and cached_data is not None:
            if not self.should_regenerate(cached_data):
                # Cache is valid, use it
                return cached_data['params']

        # Need to run discovery
        print("Discovering GRUB parameters from system documentation...")
        params, new_state = self.discover_params()

        if params:
            print(f"Found {len(params)} parameters (state: {new_state})")
        else:
            print(f"Warning: No parameters discovered (state: {new_state})")
            if new_state == STATE_NO_INFO:
                print("GRUB documentation may not be installed:")
                print("  Ubuntu/Debian: sudo apt install grub-doc")
                print("  Fedora/RHEL:   sudo dnf install grub2-common")

        # Don't replace OK with non-OK
        if cached_data and cached_data['state'] == STATE_OK and new_state != STATE_OK:
            print(f"Keeping previous OK status (current attempt: {new_state})")
            # Return cached params but update timestamp
            self.save_params(cached_data['params'], STATE_OK)
            return cached_data['params']

        # Save new results
        self.save_params(params, new_state)
        return params


def main():
    """CLI entry point for standalone testing"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Discover GRUB parameters supported on this system'
    )
    parser.add_argument(
        '--regenerate', '-r',
        action='store_true',
        help='Force regeneration, ignore cached results'
    )
    parser.add_argument(
        '--config-dir',
        type=Path,
        help='Config directory (default: ~/.config/grub-wiz/)'
    )
    parser.add_argument(
        '--compare',
        type=str,
        help='Compare against comma-separated list of expected params'
    )

    args = parser.parse_args()

    # Run discovery
    discovery = ParamDiscovery(config_dir=args.config_dir)
    params = discovery.get_system_params(force_regenerate=args.regenerate)

    # Load and display status
    cached_data = discovery.load_cached_data()

    print(f"\n{'='*60}")
    print(f"Discovered Parameters ({len(params)} total):")
    print(f"{'='*60}")

    if cached_data:
        print(f"Status: {cached_data['state']}")
        age_days = (int(time.time()) - cached_data['timestamp']) / (24 * 60 * 60)
        print(f"Cache age: {age_days:.1f} days")
        print()

    for param in sorted(params):
        print(f"  {param}")

    print(f"\nCache location: {discovery.cache_file}")

    # Optional comparison
    if args.compare:
        expected = {p.strip() for p in args.compare.split(',')}
        missing = expected - params
        extra = params - expected

        print(f"\n{'='*60}")
        print("Comparison Results:")
        print(f"{'='*60}")

        if missing:
            print(f"\nMissing (expected but not found): {len(missing)}")
            for p in sorted(missing):
                print(f"  - {p}")

        if extra:
            print(f"\nExtra (found but not expected): {len(extra)}")
            for p in sorted(extra):
                print(f"  + {p}")

        if not missing and not extra:
            print("\n✓ Perfect match!")


if __name__ == '__main__':
    main()
