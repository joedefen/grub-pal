#!/usr/bin/env
"""
{parameter-name}:
  section: {TUI grouping}
  type: {cycle | input | boolean | special_list} # Controls Curses interaction
  default: {default value from GRUB docs}
  enums: # list of values for 'type: cycle' or 'type: special_list'
    - value: meaning
  regex: {regex} # Optional, for 'type: input' validation
  specials: # Optional, for 'type: special_list' population
    - {special_key} # e.g., "get-res-list", "get-disk-uuid"
  brief: {text} # < 60 char description
  full: {text} # < 400 char detailed explanation
"""

YAML_STRING = r"""
GRUB_TIMEOUT:
  brief: Time (in seconds) to wait before booting the default entry.
  default: '5'
  enums: []
  full: The timeout for the GRUB menu display. Set to 0 for instant boot, or -1 to
    wait indefinitely until a key is pressed.
  regex: ^-?\d+$
  section: Timeout & Menu
  specials: []
  type: input
GRUB_TIMEOUT_STYLE:
  brief: How the timeout is displayed.
  default: menu
  enums:
  - meaning: Show the full menu during the timeout period.
    value: menu
  - meaning: Show a countdown display instead of the menu.
    value: countdown
  - meaning: Menu is hidden until a key is pressed.
    value: hidden
  full: Determines if the full menu, a countdown, or nothing is displayed during the
    timeout.
  regex: ^(menu|countdown|hidden)$
  section: Timeout & Menu
  specials: []
  type: cycle
"""
LEFT_BEHIND_STRING = r"""
GRUB_BACKGROUND:
  brief: Path to a background image file (PNG, JPG, TGA).
  default: ''
  enums: []
  full: Specifies a full path (e.g., /boot/grub/splash.png) to a custom image for
    the GRUB menu background.
  regex: ^(\/|\w).*$
  section: Appearance
  specials: []
  type: input
GRUB_CMDLINE_LINUX:
  brief: Arguments passed to all kernel entries, including recovery.
  default: ''
  enums: []
  full: Kernel parameters applied to all entries, including recovery. Use this for
    necessary hardware options that must *always* be present.
  regex: .*
  section: Kernel Arguments
  specials: []
  type: input
GRUB_CMDLINE_LINUX_DEFAULT:
  brief: Arguments passed to the kernel when booting (normal mode).
  default: quiet splash
  enums:
  - meaning: Disable kernel mode setting (often for broken graphics drivers).
    value: nomodeset
  - meaning: Force text-only console.
    value: text
  - meaning: Show systemd startup messages.
    value: systemd.show_status=1
  full: The most important line for common kernel options like 'quiet', 'splash',
    'nomodeset', etc. Ensure arguments are space-separated.
  regex: .+
  section: Kernel Arguments
  specials: []
  type: input
GRUB_DEFAULT:
  brief: Which boot entry to select by default.
  default: '0'
  enums:
  - meaning: Boot the first entry in the menu (usually the latest kernel).
    value: '0'
  - meaning: Boot the entry selected in the previous session.
    value: saved
  - meaning: Specify a menu entry title (complex, use 'e' edit).
    value: gnulinux-advanced-*-*
  full: Sets the default menu entry to boot. '0' is the first entry, 'saved' remembers
    the last successful boot.
  regex: (\d+|saved|gnulinux-advanced-\S+-\S+)
  section: Boot Selection
  specials: []
  type: cycle
GRUB_DISABLE_LINUX_UUID:
  brief: Force GRUB to use device names instead of UUIDs for mounting filesystems.
  default: 'false'
  enums:
  - meaning: Use device names (e.g., /dev/sda1) instead of UUIDs in boot entries.
    value: 'true'
  - meaning: Use Universally Unique Identifiers (UUIDs) for device paths.
    value: 'false'
  full: UUIDs are generally safer, but if you have a non-standard setup (like certain
    RAID/LVM) or are debugging, disabling UUIDs might be necessary.
  regex: ^(true|false)$
  section: Kernel Arguments
  specials: []
  type: boolean
GRUB_DISABLE_OS_PROBER:
  brief: Toggle scanning for other OSes (os-prober).
  default: 'false'
  enums:
  - meaning: Do NOT search for other operating systems (Windows, other Linux installs).
    value: 'true'
  - meaning: Search for other operating systems.
    value: 'false'
  full: If set to 'true', GRUB will not automatically add entries for other operating
    systems found on separate partitions.
  regex: ^(true|false)$
  section: Scanning
  specials: []
  type: boolean
GRUB_DISTRIBUTOR:
  brief: Label used to identify your OS in the menu entries.
  default: $(lsb_release -i -s 2> /dev/null || echo Debian)
  enums: []
  full: The string used in the menu entry titles to denote the operating system (e.g.,
    'Ubuntu', 'Debian').
  regex: .*
  section: Metadata
  specials: []
  type: input
GRUB_ENABLE_CRYPTODISK:
  brief: Enable support for booting from encrypted disks.
  default: n
  enums:
  - meaning: Enable support for encrypted disks (LUKS/dm-crypt) in the GRUB environment.
    value: y
  - meaning: Do not include support for encrypted disks.
    value: n
  full: If your system's root partition is encrypted (LUKS), you must enable this
    parameter and run update-grub for the boot process to work correctly.
  regex: ^(y|n)$
  section: Security
  specials: []
  type: boolean
GRUB_GFXMODE:
  brief: The resolution for the graphical GRUB menu.
  default: auto
  enums:
  - meaning: Automatically determine best resolution.
    value: auto
  full: The pixel resolution for the menu display, e.g., '1024x768'. 'auto' is the
    safest choice. List is populated via 'get-res-list'.
  regex: ^\d+x\d+x\d+$|^\d+x\d+$|^auto$
  section: Appearance
  specials:
  - get-res-list
  type: special_list
GRUB_RECORDFAIL_TIMEOUT:
  brief: Timeout (in seconds) used after a boot failure or crash.
  default: '30'
  enums: []
  full: If a previous boot failed (e.g., failed shutdown, kernel panic), GRUB will
    wait this long to give the user a chance to recover. Setting this to 0 or a low
    number can speed up boot after a known failure condition.
  regex: ^\d+$
  section: Timeout & Menu
  specials: []
  type: input
GRUB_TERMINAL_INPUT:
  brief: Sets the input device for the GRUB menu.
  default: console
  enums:
  - meaning: Use standard text input.
    value: console
  - meaning: Enable serial console input (requires GRUB_SERIAL_COMMAND).
    value: serial
  full: Typically set to 'console'. Change to 'serial' if you are managing the system
    remotely via a serial connection.
  regex: ^(console|serial)$
  section: Appearance
  specials: []
  type: cycle
GRUB_THEME:
  brief: Path to the directory containing a GRUB theme (optional).
  default: ''
  enums: []
  full: Specifies the full path to a directory containing a GRUB theme for a more
    polished graphical look. If unset, it uses the basic look defined by GRUB_GFXMODE.
  regex: ^(\/|\w).*$
  section: Appearance
  specials: []
  type: input
"""

import yaml

class WiredConfig:
    """ TBD"""
    def __init__(self):
        self.data = yaml.safe_load(YAML_STRING)
        
    def dump(self):
      """ Dump the wired/initial configuration"""
      string = yaml.dump(self.data, default_flow_style=False)
      print(string)

def main():
    """ TBD """
    string = yaml.dump(config_data, default_flow_style=False)
    print(string)

if __name__ == '__main__':
    main()