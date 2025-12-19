>  **Note: This is version 0.8.y - please report issues at https://github.com/joedefen/grub-wiz/issues**

## GrubWiz: Safe GRUB Configuration Made Simple

`grub-wiz` is a terminal-based editor that helps you manage /etc/default/grub safely and efficiently, replacing error-prone manual editing with guided configuration.

**The Problem It Solves.** Editing GRUB configurations manually is risky—typos can break your bootloader, and GUI tools often make overly aggressive changes. `grub-wiz` provides a middle ground: the power of direct editing with the safety of validation and guidance.

* **Safety by Design**
  -   Parameter validation via regex and cross-checks
  -   Safe defaults and guided choices for common settings
  -   Backups offered when configuration is unique

* **Key Features**
  -   *Smart editing*: Preset choices for common values, regex validation for free-form entries
  -   *Context-aware warnings*: Cross-parameter validation and sensible defaults
  -   *Full backup system*: Tagged, timestamped backups with easy restore and comparison
  -   *Lightweight TUI*: Works everywhere—local, SSH, or minimal environments
  -   *Respects existing config*: Unknown parameters are preserved with minimal validation

* **How It Works**
  -   Edit with guidance: Choose from presets or edit with validation
  -   Review with checks: See warnings and fix issues before writing
  -   Write safely: validation → update-grub → backup
  -   Restore if needed: version history with diff comparison

`grub-wiz` focuses on the 95% of common GRUB configuration tasks, making them safe and simple while preserving your existing customizations.

#### Installation and Running is Easy

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
 EDIT  [g]uide=Off [w]rite-grub     ?:help [q]uit  𝚫=0
 [s]how-all-params(22-inact)  ⮜–⮞ [e]dit x:deact
─────────────────────────────────────────────────────────────────────────────────────────────
 [Boot Timeout]
>  TIMEOUT·················  5                                                               
   TIMEOUT_STYLE···········  menu
   RECORDFAIL_TIMEOUT······  2

 [Kernel Arguments]
   CMDLINE_LINUX···········  ""
   CMDLINE_LINUX_DEFAULT···  ""

 [Visual Appearance]
   DISTRIBUTOR·············  'Kubuntu'
```
NOTES:
* `grub-wiz` is only showing "active" parameters (the uncommented ones in the grub file); to add parameters, see them all with the `s` key. The parameters that are inactive will be marked with an `✘`.
* In the header, `⮜–⮞` indicates you can cycle through a list of values with the right/left arrow keys.
* Also, `[e]dit` indicates you can type `e` to free-style edit the parameter; in that case, your change will be checked with a regular expression and you must make it conform.
* When you done editing, then type `w` to write the parameter after you **review** them.
* For editing the `CMDLINE` parameters, see "Essential Linux Kernel Parameters (GRUB Arguments)" in the Appendix.

##### REVIEW SCREEN AND WRINTING/UPDATING GRUB
The next step in updating the `grub` configuration is the REVIEW screen:
```
 REVIEW  [g]uide=Off [w]rite-grub     ESC:back ?:help [q]uit  𝚫=3
                              [e]dit [u]ndo
──────────────────────────────────────────────────────────────────────────────────
   RECORDFAIL_TIMEOUT······  200
              └──────── was  2
                └───      *  over 120s seems ill advised
>  CMDLINE_LINUX···········  "splash"                                             
              └──────── was  ""
                └───    ***  "splash" belongs only in CMDLINE_LINUX_DEFAULT
   CMDLINE_LINUX_DEFAULT···  ""
   DISTRIBUTOR·············  'Kubuntu My Love'
              └──────── was  'Kubuntu'
```
NOTES:
* The review screen shows parameters that you have changed and parameters that have warnings.
* On this screen, you may edit parameter values just as on the EDIT screen if the parameter is shown.
* Warnings are be dismissed by fixing the values or by inhibiting the warning (with the `x` key).
* If you inhibit warnings, they remain suppressed in future sessions until allowed.
* Lines on this screen and others that end with `▶` are truncated. To see the rest of the text, visit that line.
* When done with your review, type `w` again to finally write the `grub` file; if successful, you will be given the choice to reboot or shutdown or return to `grub-wiz`.

##### GUIDANCE LEVELS AND EXTENDED MENU
* *Extended Menu*: Typing `m` (i.e., more keys) adds the second line showing the keys for the RestoreScreen (to manage backups) and the "WarningsScreen" to configure (i.e., inhibit and allow) warnings selectively.
* *Guidance Levels*: Typing `g` on the EDIT and REVIEW screens cycles through its possible values, None, Enums, and Full.  Full guidance for the `DISABLE_OS_PROBER` parameter is shown below.
```
 REVIEW  [g]uide=Full [w]rite-grub     ESC:back ?:help [q]uit  𝚫=3
 [R]estoreScreen  [W]arningsScreen  [f]ancy=Off
                             ⮜–⮞ undo
──────────────────────────────────────────────────────────────────────────────
>  DISABLE_OS_PROBER·······  false                                            
              └──────── was  ∎
                └───      *  perhaps set "true" since no multi-boot detected?
    ╭Setting to 'true' prevents GRUB from automatically scanning other
    │     partitions for installed operating systems (like Windows, other
    │     Linux distros) and adding them to the boot menu.
    │: ⮜–⮞ :
    │  ⯀ false: Search for and automatically add other operating systems to
    │     the menu.
    ╰  🞏 true: Do not search for other operating systems.
```

##### RESTORE SCREEN
When you enter the restore screen by typing `R` from the EDIT or REVIEW screen, it looks something like:
```
 RESTORE [r]estore [d]el [t]ag [v]iew [c]mp [b]aseline    ESC:back ?:help [q]uit
───────────────────────────────────────────────────────────────────────────────────
>●     20251217-162837-60FED5D3.custom-junk.bak                                    
       20251217-085729-92C840D0.my-default.bak
       20251215-185721-3F645E7C.custom.bak
   CMP 20251215-185242-A7206478.orig.bak
```

*Backup and restore features*:
 - the leading `●` indicates it is the backup for the current session.
 - backups of `/etc/default/grub` are stored in `~/.config/grub-wiz`
 - backups are named `YYYYMMDD-HHMMSS-{8-hex-digit-checksum}.{tag}.bak`; you supply the tag.
 - if there are no backup files, on startup `grub-wiz` automatically creates one with tag='orig'
 - if there are backup files and none match the current `/etc/default/grub`, `grub-wiz` prompts you for a tag for its backup (you may decline).
 - tags must be word/phase-like strings with only [-_A-Za-z0-9] characters (spaces will be converted to "-" characters)
 - if a backup is restored, `grub-wiz` re-initializes using restored grub file and returns to main screen
 - the `[v]iew` action bring up the VIEW screen to peruse the selected `.bak` file.
 - the `[c]mp` action compares the selected `.bak` to the `CMP` (or baseline) `.bak`, and you can set the `baseline` with the `[b]aseline` action. And example the COMPARE screen is below.  As you can see, it just show the parameter values difference, not different comments or blank lines or whatnot.
```
COMPARE   ESC:back
< 20251217-085729-92C840D0.my-default.bak [#lines=44]
> 20251215-185242-A7206478.orig.bak [#lines=39]
───────────────────────────────────────────────────────────────────────────────────

< GRUB_RECORDFAIL_TIMEOUT=2
>

< GRUB_TIMEOUT=2
> GRUB_TIMEOUT=0

< GRUB_TIMEOUT_STYLE=menu
> GRUB_TIMEOUT_STYLE=hidden

```
##### WARNINGS CONFIGURATION SCREEN
Finally, we show the Warnings Configuration Screen.  Here is a short snippet:
```
 WARNINGS-CONFIG   x:inhibit-warning   /   ESC=back quit
───────────────────────────────────────────────────────────────────────────────────
 [ ]   ** BACKGROUND: path does not seem to exist
>[ ]  *** CMDLINE_LINUX: "quiet" belongs only in CMDLINE_LINUX_DEFAULT             
 [ ]  ***                "splash" belongs only in CMDLINE_LINUX_DEFAULT
 [X]   **                has spaces and thus must be quoted
 [ ]  ***                no "rd.luks.uuid=" but LUKS seems active
 [ ]  ***                no "rd.lvm.vg=" but LVM seems active
 [ ]   ** CMDLINE_LINUX_DEFAULT: has spaces and thus must be quoted
           ...
```
Every possible warning (currently about 50) is shown on the Warning Configuration Screen. You can inhibit and allow warnings as you please. More often, you probably will inhibit/allow warnings on the Review Screen as they arise and you wish to dismiss it.

---
#### Parameter Discovery and Excluded Parameters
Because GRUB can vary per system, `grub-wiz` uses `info -f grub -n "Simple Configuration"` to discover which parameters are actually supported. Parameters not found on your system are automatically removed by `grub-wiz` from its screens so that you do not add it from the confusion. Notes:
- We recommend installing GRUB documentation for best results:
    - Ubuntu/Debian: `sudo apt install grub-doc`
    - Fedora/RHEL: `sudo dnf install grub2-common`
- If `info` provides inaccurate results, you can disable discovery:
    - `grub-wiz --discovery=disable` (use "enable" or "show" for other actions)


`grub-wiz` focuses on common configuration tasks. You may have specialized needs such as:

- **Xen virtualization**: GRUB_CMDLINE_XEN, GRUB_CMDLINE_XEN_DEFAULT
- **Debug output**: GRUB_ENABLE_BLSCFG, GRUB_DEBUG
- **Early initrd**: GRUB_EARLY_INITRD_LINUX*

If so, add these manually to `/etc/default/grub`; then, `grub-wiz` will recognize and preserve them (but with limited validation and no cross-checks).

#### Custom Parameter Configuration (Advanced)

For advanced users who need to modify parameter definitions:

1. grub-wiz creates `~/.config/grub-wiz/canned_config.yaml` as a template
2. Copy it to `~/.config/grub-wiz/custom_config.yaml`
3. Edit as needed (add params, modify validation regex, change guidance, etc.)
4. Restart `grub-wiz` - it will use your custom config if valid

**Notes:**
- Invalid YAML or schema errors fall back to packaged config with a warning
- Use `grub-wiz --validate-custom-config` to test your changes
- Consider submitting useful additions as GitHub issues/PRs!

---
---
---

## Appendix: Additional Topics

#### GRUB File Parsing and Rewriting Rules

When `grub-wiz` reads and writes `/etc/default/grub`, it follows specific rules to ensure compatibility and safety. Understanding these rules helps you avoid patterns that could cause issues.

##### ✅ Supported Patterns

**Standard Parameter Assignments**
```bash
GRUB_TIMEOUT=5
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
GRUB_DEFAULT=0
```
These are read, managed, and written back correctly.

**Backslash Continuation Lines**
```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash \
nvidia-drm.modeset=1 \
acpi_backlight=vendor \
intel_pstate=disable"
```
- Continuation lines are automatically joined during reading
- Written back as a single line: `GRUB_CMDLINE_LINUX_DEFAULT="quiet splash nvidia-drm.modeset=1 acpi_backlight=vendor intel_pstate=disable"`
- **Requirements**:
  - Value must be double-quoted (not single quotes or unquoted)
  - Each line except the last must end with `\` immediately before the newline
  - Works with both commented and uncommented parameters

**Commented Parameters**
```bash
# This parameter is disabled
#GRUB_DISABLE_RECOVERY=true
```
- Tracked with special internal value (shown as `∎` in param data)
- Can be uncommented and given a value through the UI
- Commented continuations are also supported (each line must start with `#`)

##### ⛔ Blacklisted Patterns (Passthrough Only)

`grub-wiz` detects but **does not manage** parameters using shell variable expansion. These patterns require shell interpretation and are preserved exactly as written but excluded from the UI:

**Variable Self-Reference**
```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
GRUB_CMDLINE_LINUX_DEFAULT="${GRUB_CMDLINE_LINUX_DEFAULT} extra_option"
```
- **Both lines** are blacklisted and passed through unchanged
- The parameter `GRUB_CMDLINE_LINUX_DEFAULT` will not appear in the UI

**Variable Cross-Reference**
```bash
GRUB_TIMEOUT=5
GRUB_FOO="timeout is $GRUB_TIMEOUT seconds"
```
- Only `GRUB_FOO` is blacklisted (uses expansion, can't predict final value)
- `GRUB_TIMEOUT` remains editable in the UI
- Changes to `GRUB_TIMEOUT` through `grub-wiz` will be picked up by `GRUB_FOO` when the file is sourced
- `GRUB_FOO` is written back exactly as found

**Why Blacklist Variable Expansion?**
- Parameters using `$VAR` or `${VAR}` require shell evaluation at runtime
- `grub-wiz` cannot reliably predict or validate their final expanded values
- Attempting to manage these could corrupt complex scripting logic
- Referenced parameters (like `GRUB_TIMEOUT` above) remain fully editable - changes propagate when the file is sourced by GRUB

##### 📝 Best Practices for Manual Editing

**DO:**
- ✅ Use double quotes for values with spaces or special characters
- ✅ Use continuation lines (with `\`) for very long parameter values
- ✅ Add comments above parameters for documentation
- ✅ Keep it simple - one assignment per parameter

**DON'T:**
- ❌ Use variable expansion (`$VAR` or `${VAR}`) if you want `grub-wiz` to manage the parameter
- ❌ Mix quoted and unquoted values in continuation lines
- ❌ Put `#` comments in the middle of continuation sequences
- ❌ Use single quotes with backslash continuations (shell doesn't expand `\` in single quotes)

##### 🔍 How to Check if a Parameter is Blacklisted

If a parameter you expect to see doesn't appear in `grub-wiz`:
1. Check `/etc/default/grub` for variable expansion (`$` or `${...}`)
2. Simplify to a direct assignment: `GRUB_PARAM="value"` instead of `GRUB_PARAM="${OTHER} value"`
3. Restart `grub-wiz` - the parameter should now appear

##### 📌 Parameter Discovery

Parameters that don't exist on your system (per `info grub`) are also excluded from the UI but preserved in the file. See **Parameter Discovery and Excluded Parameters** section for details.

---

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

## Future Feature Considerations

#### Sparse Override Feature
* Effort: Medium-high
* Value: High - best UX This is the most powerful and user-friendly:

###### ~/.config/grub-wiz/custom_config.yaml
```
##########     NOTE: this is FOR DISCUSSION (NOT IMPLEMENTED)  ################
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

###### Implementation notes for Sparse Override Feature:
* Schema version check - ignore custom_config if version mismatches (safe)
* killed_params vs WizHider - different purposes:
* WizHider: Runtime user preferences (hide/unhide in UI)
* killed_params: Admin decision "never expose this parameter"
* Merge strategy: canned → apply overrides → add user_params
* Updates safe: Changes to canned_config automatically flow through (unless overridden)