>  **This project is very early in development ... come back later.**

💻 GrubPal: The Friendly GRUB Bootloader Assistant

A safe, simple, and reliable Text User Interface (TUI) utility for managing the most common GRUB bootloader configuration tasks on Linux systems.

GrubPal provides the ease-of-use of a graphical configurator without the dependency bloat or the reputation for complex, destructive changes. It operates strictly on configuration files, making safe backups before every change.
🚀 Why Use GrubPal?

Dealing with /etc/default/grub and running update-grub manually is tedious and prone to typos. Other visual configurators often make overly aggressive changes that break the boot process.

GrubPal solves this by focusing on core functionality and system safety:

    ✅ Safety First: Always creates a timestamped backup of your current GRUB configuration before applying any changes.

    💻 Curses Interface: Lightning-fast, lightweight TUI works across all environments (local, SSH, minimal installs) without requiring a desktop environment.

    ⚙️ Targeted Configuration: Focuses only on the most essential and common configuration tasks, minimizing risk.

✨ Core Features

GrubPal makes complex, manual configuration steps as easy as a few keystrokes in a clean interface:
1. Boot Entry Management

    Reorder Entries: Easily move boot entries up or down the list to change the default boot option or preferred order.

    Set Default: Select the specific entry that should boot automatically.

2. Boot Parameters Editor

    Simple Parameter Toggles: Visually add, remove, or modify common kernel parameters (e.g., nomodeset, quiet, splash).

    Custom Arguments: Add any custom arguments you need for specific hardware or debugging.

3. Timeout Control

    Set Timeout: Quickly adjust the display duration of the GRUB menu (in seconds) via a simple numeric input.

    Hide Menu: Option to set the timeout to zero for fast, non-interactive booting.

4. Configuration Safety & Deployment

    Automatic Backup: A compressed, timestamped backup is made before any file write. Recovery is straightforward.

    Preview Changes: Review the final $GRUB_CONFIG_FILE content before it is written and update-grub is executed.

    Configuration Validation: Basic checks to ensure the output configuration is syntactically correct before deployment.

🛠️ Installation (Hypothetical)

* `grub-pal` is available on PyPI and installed via `pipx install grub-pal.
* `grub-pal` makes itself root using `sudo` and will prompt for password.

👨‍💻 Development Status

    Foundation: Built upon the robust console-window curses foundation.

    Current State: Initial feature development and safety implementation.

    Contributions: Contributions are welcome! See the CONTRIBUTING.md for guidelines.
