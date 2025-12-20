#!/usr/bin/env python3
import os
import shutil
import sys

class DistroVars:
    def __init__(self, yaml_data):
        vars_cfg = yaml_data.get('_distro_vars_', {})
        
        # 1. Resolve Components
        self.grub_cfg = self._find_first_path(vars_cfg.get('grub_cfg', []))
        self.etc_grub = self._find_first_path(vars_cfg.get('etc_grub', []))
        self.update_grub = self._find_binary(vars_cfg.get('update_grub', []))

        # 2. Check and Prompt if needed
        self._check_and_confirm()

    def _find_first_path(self, paths):
        for path in paths:
            if os.path.exists(path):
                return path
        return None

    def _find_binary(self, commands):
        for cmd in commands:
            resolved = shutil.which(cmd)
            if resolved:
                return resolved
        return None

    def _check_and_confirm(self):
        missing = []
        # etc_grub is critical - we can't edit anything without it
        if not self.etc_grub:
            print("\033[91mCRITICAL ERROR: /etc/default/grub not found.\033[0m")
            sys.exit(1)

        # These are "non-fatal" but limit the tool's power
        if not self.grub_cfg: missing.append("grub.cfg (Needed for DEFAULT choice list)")
        if not self.update_grub: missing.append("Update command (Needed to apply changes)")

        if missing:
            print("\033[93mWARNING: Some components were not found:\033[0m")
            for item in missing:
                print(f"  - {item}")
            
            print("\ngrub-wiz can continue in \033[1m'Cripple Mode'\033[0m (Manual save only).")
            choice = input("Continue anyway? [y/N]: ").strip().lower()
            
            if choice != 'y':
                print("Aborting.")
                sys.exit(0)
            
            # Set a flag so the UI knows to disable certain buttons
            self.is_crippled = True
        else:
            self.is_crippled = False

def main():
    # Example YAML structure
    sample_yaml = {
        '_distro_vars_': {
            'grub_cfg': ['/boot/grub/grub.cfg', '/boot/grub2/grub.cfg'],
            'update_grub': ['grub-mkconfig', 'update-grub'],
            'etc_grub': ['/etc/default/grub']
        }
    }

    env = DistroVars(sample_yaml)
    print(f"\nProceeding with is_crippled={env.is_crippled}")

if __name__ == "__main__":
    main()
