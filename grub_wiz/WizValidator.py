#!/usr/bin/env python3
""" TBD """

import os
import subprocess
import json
from types import SimpleNamespace
from typing import Tuple, Optional
from copy import deepcopy
# pylint: disable=line-too-long,invalid-name,too-many-locals
# pylint: disable=too-many-branches,too-many-statements


class WizValidator:
    """ TBD """
    def __init__(self, param_cfg):
        # Cache for the disk probe results
        self._disk_layout_cache: Optional[SimpleNamespace] = None
        self.param_cfg = param_cfg
        # ... other initializations ...

    def probe_disk_layout(self) -> SimpleNamespace:
        """
        Performs a quick heuristic scan using lsblk to determine key disk layout flags.
        The result is cached to ensure the subprocess is run only once.

        Returns:
            SimpleNamespace(has_another_os: bool, is_luks_active: bool, is_lvm_active: bool)
        """
        # 1. Check Cache
        if self._disk_layout_cache is not None:
            return self._disk_layout_cache

        # 2. Set Initial State
        result = SimpleNamespace(
            has_another_os=False,
            is_luks_active=False,
            is_lvm_active=False
        )

        # lsblk is fast and outputs in JSON format
        cmd = ['lsblk', '-o', 'FSTYPE,PARTTYPE', '-J']

        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )

            if process.returncode != 0:
                # If lsblk fails (e.g., permissions), return the default 'False' result
                self._disk_layout_cache = result
                return result

            data = json.loads(process.stdout)

            # 3. Scan Partitions
            for device in data.get('blockdevices', []):
                if 'children' in device:
                    for partition in device['children']:
                        fstype = partition.get('FSTYPE', '').lower()
                        parttype = partition.get('PARTTYPE', '').lower()

                        # --- A. Other OS Detection (Windows/Other) ---
                        if fstype in ('ntfs', 'vfat', 'fat32', 'exfat'):
                            result.has_another_os = True

                        # Windows Recovery Partition GUID
                        if 'de94bba4-06d9-4d40-a16a-bfd50179d6ac' in parttype:
                            result.has_another_os = True

                        # --- B. LUKS/LVM Detection (Requires Special Kernel Args) ---

                        # LUKS Check
                        if fstype in ('crypto_luks', 'crypto_luks2'):
                            result.is_luks_active = True

                        # LVM Check (FSTYPE or PARTTYPE)
                        if fstype == 'lvm2_member' or \
                           'e6d6d379-f507-44c2-a23c-238f2a3df928' in parttype:
                            result.is_lvm_active = True

                        # Optimization: If all flags are True, we can stop early
                        if result.has_another_os and result.is_luks_active and result.is_lvm_active:
                            break

        except (FileNotFoundError, json.JSONDecodeError):
            # If lsblk is missing or JSON output is bad, the default 'False' result will be cached.
            pass

        # 4. Cache and Return
        self._disk_layout_cache = result
        return result

    def get_full_path_and_check_existence(self, path: str) -> Tuple[bool, str]:
        """
        Resolves a GRUB path, checks for existence in common locations,
        and returns a tuple: (exists: bool, resolved_path: str).
        """
        base_dirs = [
            '/boot/grub',      # Common for Debian/Ubuntu
            '/boot/grub2',     # Common for Fedora/CentOS/openSUSE
            '/usr/share/grub', # Fallback for some assets
            '/'                # The root filesystem, for paths starting with simple components
        ]

        if not path:
            return False, ''

        # 1. Strip surrounding quotes
        resolved_path = path.strip().strip('"').strip("'")

        # 2. Simplified $prefix expansion
        if resolved_path.startswith('$prefix'):
            resolved_path = resolved_path.replace('$prefix', base_dirs[0])

        # 3. Handle Absolute Path Check
        if os.path.isabs(resolved_path):
            # If it's absolute, check it directly
            if os.path.exists(resolved_path):
                return True, resolved_path
            return False, resolved_path # Doesn't exist, but this is the path

        # 4. Handle Relative Path Check (Try Multiple Base Directories)
        for base_dir in base_dirs:
            # Construct the full path using the base directory
            full_path = os.path.join(base_dir, resolved_path)

            # Check for existence (can be file or directory)
            if os.path.exists(full_path):
                return True, full_path

        # If we reach here, the file was not found in any common base directory.
        # Return False and the most commonly expected full path (using the primary base dir)
        fallback_path = os.path.join(base_dirs[0], resolved_path)
        return False, fallback_path


    def make_warns(self, vals: dict):
        """
        Arguments:
            * vals: param_name -> current value
            * param_dict: param_name -> param configuration
        Returns:
            * warnings dict:
                key: param
                value: list of (severity, message)
        """

        def unquote(value):
            if value.startswith("'"):
                return value[1:].rstrip("'")
            if value.startswith('"'):
                return value[1:].rstrip('"')
            return value
        def quotes(param): # all forms of simple value in grub config
            return (param, f'"{param}"', f"'{param}'")
        def sh(param): # "ShortHand": reduce GRUB_TIMEOUT to TIMEOUT
            return param[5:]
        def hey(param, severity, message):
            nonlocal warns, stars
            if not warns[param]:
                warns[param] = []
            warns[param].append((stars[severity], message))

        stars = [''] + '* ** *** ****'.split()
        warns = {}
        layout = self.probe_disk_layout()

        # if _DEFAULT is saved, then _SAVEDDEFAULT must be true
        p1, p2 = 'GRUB_DEFAULT', 'GRUB_SAVEDDEFAULT'
        if vals[p1] in quotes('saved'):
            if vals[p2] not in quotes('true'):
                hey(p2, 4, f'must be "true" since {sh(p1)} is "saved"')

        # --- Critical Check 2: DEFAULT=hidden & HIDDEN_TIMEOUT ---
        p1, p2 = 'GRUB_DEFAULT', 'GRUB_HIDDEN_TIMEOUT'
        # The grub documentation implies that "0" or "unset" means no timeout, which is the main issue.
        # We check if DEFAULT is hidden AND the HIDDEN_TIMEOUT is effectively zero/missing.
        if vals.get(p1) in quotes('hidden'):
            # Check if p2 is '0', '0.0', missing, or None (allowing for quoted forms)
            is_zero_or_missing = (
                vals.get(p2) is None or
                vals.get(p2) in quotes('0') or
                vals.get(p2) in quotes('0.0')
            )

            if is_zero_or_missing:
                hey(p2, 4, f'should be positive int when {sh(p1)} is "hidden"')

        # --- Best Practice Check 1: TIMEOUT=0 & TIMEOUT_STYLE=hidden ---
        p1, p2 = 'GRUB_TIMEOUT', 'GRUB_TIMEOUT_STYLE'
        # Check if TIMEOUT is 0 (or equivalent) AND the style is 'hidden'
        is_zero_timeout = (
            vals.get(p1) in quotes('0') or
            vals.get(p1) in quotes('0.0')
        )
        if is_zero_timeout and vals.get(p2) in quotes('hidden'):
            # critical because it leads to an unrecoverable state
            hey(p1, 4 , f'should be positive int when {sh(p2)}="hidden"')


        # --- Critical Check 3: TIMEOUT is > 0 but TIMEOUT_STYLE is NOT menu ---
        p1, p2 = 'GRUB_TIMEOUT', 'GRUB_TIMEOUT_STYLE'

        timeout_val = unquote(vals.get(p1, '0'))
        timeout_style = vals.get(p2)

        # Check if TIMEOUT is a positive number
        try:
            is_positive_timeout = float(timeout_val) > 0
        except ValueError:
            # If it's not a number (e.g., 'infinity'), skip this check.
            is_positive_timeout = False

        # Check if the style is not explicitly set to 'menu'
        is_not_menu = timeout_style not in quotes('menu')

        if is_positive_timeout and is_not_menu:
            # If the user sets a timeout > 0, they expect to see the menu.
            # If the style is not 'menu', they may miss it or not see it at all.
            hey(p2, 4, f'should be "menu" when {sh(p1)} > 0')


        # --- Best Practice Check 2: 'quiet' only in GRUB_CMDLINE_LINUX_DEFAULT ---
        p1, p2 = 'GRUB_CMDLINE_LINUX_DEFAULT', 'GRUB_CMDLINE_LINUX'
        if 'quiet' in vals[p2]:
            # Having 'quiet' in _LINUX prevents seeing text even in recovery/single user mode
            hey(p2, 3, f'"quiet" belongs only in {sh(p1)}')
        if 'splash' in vals[p2]:
            # Having 'splash' in _LINUX prevents seeing text even in recovery/single user mode
            hey(p2, 3, f'"splash" belongs only in {sh(p1)}')

        if layout.is_luks_active and 'rd.luks.uuid=' not in vals[p2]:
            hey(p2, 3, 'no "rd.luks.uuid=" but LUKS seems active')
        if layout.is_lvm_active and 'rd.lvm.vg=' not in vals[p2]:
            hey(p2, 3, 'no "rd.lvm.vg=" but LVM seems active')

        # --- Advanced Check 1: SAVEDEFAULT=true but DEFAULT is numeric ---
        # The GRUB documentation discourages this because a numeric default can change
        # if the menu entries are reordered.
        p1, p2 = 'GRUB_SAVEDDEFAULT', 'GRUB_DEFAULT'
        if vals[p1] in quotes('true'):
            default_value = vals.get(p2, '0') # Default to '0' if missing
            # A simple check for numeric (excluding "saved", "menuentry title", etc.)
            if unquote(default_value).isdigit():
                hey(p2, 1, f'avoid numeric when {sh(p1)}="true"')

        # --- Common Mistake Check 1: Unquoted values in CMDLINEs ---
        # The main issue is checking if a value that *needs* quotes is unquoted.
        # We assume any value containing spaces needs to be quoted.
        for p in ['GRUB_CMDLINE_LINUX', 'GRUB_CMDLINE_LINUX_DEFAULT']:
            value = vals.get(p)
            # If the value contains a space...
            if value is not None and ' ' in value:
                # ... and it is not quoted in single or double quotes
                # The 'quotes()' helper returns raw, "...", and '...' forms.
                # If the value is not in any of the quoted forms generated by passing the raw value,
                # we issue a warning. (A more robust check would look at the raw config input.)
                if value not in quotes(unquote(value)):
                    hey(p, 2, 'has spaces and thus must be quoted')

        # --- Common Mistake Check 2: GRUB_BACKGROUND path doesn't exist ---
        for p1 in ['GRUB_BACKGROUND', 'GRUB_THEME']:
            exists, _ =  self.get_full_path_and_check_existence(vals[p1])
            if not exists:
                hey(p1, 2, 'path does not seem to exist')


        # --- Common Mistake Check 4: GFXMODE set but not a known safe value ---
        p1 = 'GRUB_GFXMODE'
        # Define the set of known safe/default values
        # TODO: get from the config
        safe_modes = {
            '640x480',
            '800x600',
            '1024x768',
            'auto',
            'keep' # 'keep' means keep the resolution set by the BIOS/firmware
        }

        value = vals.get(p1)

        if value:
            # 1. Strip quotes and normalize the value
            # Since GFXMODE can take multiple comma-separated values (e.g., "1024x768,auto"),
            # we need to check each one.
            modes = [m.strip().lower() for m in unquote(value).split(',')]

            unsafe_modes = [m for m in modes if m not in safe_modes]

            if unsafe_modes:
                hey(p1, 1, 'perhaps unsupported; stick to common values')

        # --- Common Mistake Check 5: Missing GRUB_DISTRIBUTOR ---
        p1 = 'GRUB_DISTRIBUTOR'
        if not vals[p1]:
            # If the value is completely missing or empty
            hey(p1, 2, 'should be distro name (it is missing/empty)')


        # --- Best Practice Check 4: OS-PROBER Disabled on Dual-Boot System ---
        p1 = 'GRUB_DISABLE_OS_PROBER'
        is_prober_disabled = vals.get(p1) in quotes('true')
        has_other_os = layout.has_another_os

        if is_prober_disabled and has_other_os:
            hey(p1, 2, 'suggest setting "false" since multi-boot detected')

        if not is_prober_disabled and not has_other_os:
            hey(p1, 1, 'perhaps set "true" since no multi-boot detected?')

        # for parameters with fixed list of possible values, ensure one of them
        for param_name, cfg in self.param_cfg.items():
            enums = cfg.get('enums', None)
            checks = cfg.get('checks', None)

            # Only validate enums if no regex/range checks defined
            has_enums = isinstance(enums, dict) and len(enums) > 0
            has_no_checks = not checks or (isinstance(checks, (list, dict)) and len(checks) == 0)

            if has_enums and has_no_checks and param_name in vals:
                value = str(unquote(vals[param_name]))
                found = any(value == unquote(str(k)) for k in enums.keys())

                if not found:
                    hey(param_name, 3, 'value not in list of allowed values')

        return warns

    @staticmethod
    def demo(defaults, param_dict):
        """ TBD """
        def dump(title):
            nonlocal warnings
            print(f'\n{title})')
            for param, pairs in warnings.items():
                for pair in pairs:
                    print(f'{param:>20} {pair[0]:>4} {pair[1]}')

        validator = WizValidator(param_dict)

        vals = deepcopy(defaults)
        # change vals
        warnings = validator.make_warns(vals)
        dump('demo1')

        vals = deepcopy(defaults)
        # change vals
        warnings = validator.make_warns(vals)
        dump('demo2')
