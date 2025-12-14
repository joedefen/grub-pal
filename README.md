>  **Note: This is version 1.0.x - please report issues at https://github.com/joedefen/grub-wiz/issues**

## GrubWiz: The Helpful GRUB Bootloader Assistant

GrubWiz is a safe, simple, and reliable Text User Interface (TUI) utility for managing the most common GRUB bootloader configuration tasks on Linux systems.

#### Why Use GrubWiz?

Dealing with `/etc/default/grub` and running `update-grub` manually is tedious and prone to typos. Other visual configurators often make overly aggressive changes that break the boot process.

GrubWiz solves this by focusing on core functionality and system safety:
  * ✅ Safety First: Always creates a timestamped backup of your current GRUB configuration before applying any changes.
  * 💻 Curses Interface: Lightning-fast, lightweight TUI works across all environments (local, SSH, minimal installs) without requiring a desktop environment.
  * ⚙️ Targeted Configuration: Focuses on the most essential and common configuration tasks, minimizing risk.

#### Core Features

GrubWiz makes complex, manual configuration steps as easy as a few keystrokes in a clean interface:
* **Safer editing:**
  * Only valid parameter names are offered.
  * For parameters with a fix set values or typical values, you can select from the choices preventing typos.
  * When you need to edit parameters, they are checked against a "regex" for validity preventing very wrong entries
  * In its "review" screen, cross-parameter and sensibility checks are done and issues are presented with a chance to fix them immediately.

* **Handles "Unknown" Parameters**
  * In the case a parameter is not supported, you can manually add it to `/etc/default/grub` and the supported and unsupported parameters will be combined.
  * Before committing, `grub-script-check` is run to catch syntax errors on the combination grub file.

* **Backup / Restore**
  * When loading and before saving, if the contents is different that other saved backups, you are prompted to name a new backup.
  * In the restore screen, you can restore backups, delete backups, retag backups, and view backup contents.

#### Installation and Running

* `grub-wiz` is available on PyPI and installed via: `pipx install grub-wiz`
* Typically, just run `grub-wiz` w/o arguments
* **Note**: `grub-wiz` makes itself root using `sudo` and will prompt for password if needed.
* **Getting Help**:
  * In the app: Press `?` to view navigation keys and other key assignments
  * From terminal: Run `grub-wiz --help` to see command-line options
---
#### How to Use grub-wiz
##### EDIT SCREEN
Running `grub-wiz` brings a screen similar to:
```
 EDIT  [g]uide=Off [w]rite [R]estore ?:help [q]uit  𝚫=0
 [s]how 18 ✘-params          ⮜–⮞ [e]dit x:mark
──────────────────────────────────────────────────────────────────────
 [Boot Timeout]
>  TIMEOUT·················  2

 [Menu Entries]
   DEFAULT·················  0
   SAVEDEFAULT·············  false
   DISABLE_OS_PROBER·······  false
   DISABLE_RECOVERY········  false

 [Kernel Arguments]
   CMDLINE_LINUX···········  ""
   CMDLINE_LINUX_DEFAULT···  "quiet splash"

 [Visual Appearance]
   BACKGROUND··············
   THEME···················

 [Security & Advanced]
```
NOTES:
* `grub-wiz` supports more parameters than shown; you can see them all with the `s` key. The parameters that are suppressed will be marked with an `✘` (and called x-params).
* In the header, `⮜–⮞` indicates you can cycle through a list of values with the right/left arrow keys.
* Also, `[e]dit` indicates you can type `e` to free-style edit the parameter; in that case, your change will be checked with a regular expression and you must make it match.
* When you have finished your changes, then type `w` to write the parameter after you **review** them.
* For editing the `CMDLINE` parameters, see "Essential Linux Kernel Parameters (GRUB Arguments)" in the Appendix.

##### REVIEW SCREEN
The next step in updating the `grub` configuration is the REVIEW screen:
```
 REVIEW  [g]uide=Off [w]rite [R]estore ESC:back ?:help [q]uit  𝚫=1
                             ⮜–⮞ [e]dit
──────────────────────────────────────────────────────────────────────
>  TIMEOUT·················  22003
                        was  2
                          *  over 60s seems ill advised
   DISABLE_OS_PROBER·······  false
                          *  perhaps set "true" since no multi-boot d▶
```
NOTES:
* The review screen shows parameters that you have changed and parameters that have warnings.
* On this screen, you may edit parameter values just as on the EDIT screen if the parameter is shown.
* Warnings are be dismissed by fixing the values or by suppressing the warning (with the `x` key).
* If you mark/suppress warnings (or parameters), they remain suppressed in future sessions until unmarked.
* Lines on this screen and others that end with `▶` are truncated. To see the rest of the text, visit that line.
* When done with your review, type `w` again to finally write the `grub` file; if successful, you will be given the choice to reboot or shutdown or return to `grub-wiz`.

##### GUIDANCE LEVELS
Typing `g` on the EDIT and REVIEW screens cycles through its possible values, None, Enums, and Full.  Full guidance for the `TIMEOUT` parameter would look like:
```
>  DISABLE_OS_PROBER·······  false
                          *  perhaps set "true" since no multi-boot d▶
     Setting to 'true' prevents GRUB from automatically scanning other
          partitions for installed operating systems (like Windows,
          other Linux distros) and adding them to the boot menu.
     : ⮜–⮞ :
       ⯀ false: Search for and automatically add other operating
          systems to the menu.
       🞏 true: Do not search for other operating systems.
```

#### RESTORE SCREEN
When you enter the restore screen by typing `R` from the EDIT or REVIEW screen, it looks something like:
```
 RESTORE [d]elete [t]ag [r]estore [v]iew ESC:back ?:help [q]uit
──────────────────────────────────────────────────────────────────────
>● 20251211-211603-13C6E037.with-prober.bak
   20251210-170809-F68D6B8C.custom.bak
   20251210-003216-BC58FF3D.orig.bak
```
**NOTE**: the leading `●` indicates it is the backup for the current session.

**Backup and restore features**:
 - backups of `/etc/default/grub` are stored in `~/.config/grub-wiz`
 - backups are named `YYYYMMDD-HHMMSS-{8-hex-digit-checksum}.{tag}.bak`; you supply the tag.
 - if there are no backup files, on startup `grub-wiz` automatically creates one with tag='orig'
 - if there are backup files and none match the current `/etc/default/grub`, `grub-wiz` prompts you for a tag for its backup (you may decline).
 - tags must be word/phase-like strings with only [-_A-Za-z0-9] characters (spaces will be converted to "-" characters)
 - the `[R]estore` menu item brings up the RESTORE screen which lists backups; you can delete, restore, and view backups
 - if a backup is restored, `grub-wiz` re-initializes using restored grub file and returns to main screen

#### Parameter Discovery
Because GRUB can vary per system, `grub-wiz` uses `info -f grub -n "Simple Configuration"` to discover which parameters are actually supported. Parameters not found on your system are automatically removed by `grub-wiz` from its screens. Notes:
- We recommend installing GRUB documentation for best results:
    - Ubuntu/Debian: `sudo apt install grub-doc`
    - Fedora/RHEL: `sudo dnf install grub2-common`
- If `info` provides inaccurate results, you can disable discovery:
    - `grub-wiz --discovery=disable` (use "enable" or "show" for other actions)

## Appendix: Additional Details

#### Running grub-wiz at recovery time

To leverage user-installed, `grub-wiz` even in minimal recovery environment of grub recovery mode:
1. Remount the root filesystem as Read-Write: `mount -o remount,rw /`
2. Execute grub-wiz using its full path: `/home/{username}/.local/bin/grub-wiz`
3. Make changes as needed, and "write" them to update the boot instructions.

---

#### Essential Linux Kernel Parameters (GRUB Arguments)

These are the arguments that get passed directly to the Linux kernel during the boot process.
Parameter	Purpose & When to Use It	Example Use Case

* **quiet**
  * Boot Output Control: Suppresses most kernel startup messages, making the boot process appear cleaner and faster (often used with splash).
  * Default setting on most consumer distributions.
* **splash**
  * Visual Boot: Tells the kernel to display a graphical boot screen (e.g., the Ubuntu or Fedora logo) instead of raw text output.
  * Default setting for an aesthetic desktop experience.
* **nomodeset**
  * Graphics Troubleshooting: Crucial for fixing black screens or corrupted graphics.
  * It forces the kernel to skip loading video drivers and use basic VESA graphics initially, often allowing you to boot into the desktop to install proper proprietary drivers.	Use when the system freezes or shows a black screen after kernel loading.
* **init=/bin/bash**
  * Emergency Shell: Replaces the standard /sbin/init or /usr/lib/systemd/systemd process with a simple Bash shell, giving you immediate root access to the system for repair.
  * Use when you forget your root password or the system fails to boot into runlevels.
* **ro** or **rw**
  * Root Filesystem Mode: ro mounts the root filesystem as Read-Only initially (standard for safety, as the initramfs will remount it rw later). rw forces it to mount Read-Write immediately.
  * `ro` is the safer, common default. Change to rw only if explicitly needed for early-boot modifications.
* **single** or **1**
  * Single-User Mode (Rescue): Boots the system to a minimal state, usually without networking or graphical interfaces, often requiring the root password.
  * This is ideal for system maintenance.	Use for maintenance or recovery, especially when networking or services are causing issues.
* **systemd.unit=multi-user.target**
  * Bypass Graphical Login: Forces the system to boot to a command-line terminal login instead of the graphical desktop (skipping graphical.target).
  * Use when GUI problems prevent login or you want a server-like environment.
* **noapic** or **acpi=off**
  * Hardware Compatibility (Legacy): Disables the Advanced Programmable Interrupt Controller (noapic) or the Advanced Configuration and Power Interface (acpi=off).
  * These are extreme measures for very old or extremely non-compliant hardware that hangs during boot.	Use as a last resort when the kernel hangs while initializing hardware components.
* **rhgb**
  * Red Hat Graphical Boot: Similar to splash, but specifically used by Red Hat/Fedora systems to control their graphical boot experience.
  * Used primarily on RHEL, CentOS, or Fedora distributions.


The authoritative source for all kernel command-line parameters is the official Linux kernel documentation. Since parameters can change between major kernel versions, this is always the best place to check for advanced or very specific options:

Official Linux Kernel Documentation (Current): Search for the `kernel-parameters.rst` document in the official kernel git repository. A common link to this documentation is the `kernel-command-line(7)` manual page, which is linked to the online documentation.

---

#### SUPPRESSING PARAMETERS AND WARNINGS

This feature addresses the core tension between offering comprehensive configuration and avoiding user annoyance.
* **Suppression of "Noise"**: Users who are confident in their configuration (like your preference for empty CMDLINE variables) can permanently hide low-severity warnings or warnings they deem incorrect. This prevents alert fatigue.
* **Reduced Clutter**: By default, we suppress uncommon or advanced parameters. This significantly cleans up the interface for 90% of users while keeping the full power accessible via the [S]how toggle.

**Parameter Coverage**. grub-wiz manages ~27 GRUB parameters covering 99% of home and server use cases:
* Boot timeout & menu configuration
* Kernel command-line arguments
* Visual appearance (themes, backgrounds, resolution)
* Security (encryption, UUIDs)
* Advanced features (serial console, recovery mode, etc.)

Automatic System Detection On first run, grub-wiz attempts to discover which parameters your system supports by parsing GRUB documentation:
* ✅ If info grub is available: Parameters not supported on your system are automatically suppressed.
* ⚠️ If GRUB docs aren't installed: All ~27 parameters remain visible (you can manually hide unused ones)
To improve detection accuracy, install GRUB documentation:
```
sudo apt install grub-doc # Ubuntu/Debian
sudo dnf install grub2-common # Fedora/RHEL
```

---

## Future Considerations

#### Sparse Override Feature
* Effort: Medium-high
* Value: High - best UX This is the most powerful and user-friendly:

###### ~/.config/grub-wiz/custom_config.yaml
```
schema_version: "1.0"  # Must match canned_config

# Permanently exclude parameters (stricter than WizHider)
killed_params:
  - GRUB_BADRAM        # Never show, even in "show all"
  - GRUB_INIT_TUNE     # Don't care about beeps

# Override specific parameter configs
overrides:
  GRUB_TIMEOUT:
    # Only override what you want - rest inherited from canned
    enums:
      0: no wait
      3: short (my preference)
      10: normal (my preference)
      30: long (my preference)

  GRUB_GFXMODE:
    hide: False  # Make visible by default (was True in canned)

  GRUB_CMDLINE_LINUX:
    guidance: "Custom help text for my specific use case..."

# Add custom parameters
user_params:
  GRUB_MY_CUSTOM_FLAG:
    default: '""'
    edit_re: ^".*"$
    guidance: "My organization's custom kernel parameter"
    hide: False
```

###### Implementation notes:
* Schema version check - ignore custom_config if version mismatches (safe)
* killed_params vs WizHider - different purposes:
* WizHider: Runtime user preferences (hide/unhide in UI)
* killed_params: Admin decision "never expose this parameter"
* Merge strategy: canned → apply overrides → add user_params
* Updates safe: Changes to canned_config automatically flow through (unless overridden)