#!/usr/bin/env python3
import re
from typing import List, Dict, Optional, Any, Union

# --- Internal State Markers (for clarity) ---
STATE_COMMENTED = "#comment"
STATE_ABSENT = "#absent"
ACTION_ZAP = "#zap"

class GrubFile:
    """
    Manages reading, modifying, and writing the /etc/default/grub configuration file.

    It preserves unmanaged lines and correctly handles comment detection (ignoring
    # inside quotes) and the 'Zap' (remove/reset to default) action.
    """

    def __init__(self, file_path: str, supported_params: List[str]):
        """
        Initializes the parser and reads the file immediately.
        """
        self.file_path = file_path
        self.supported_params = supported_params
        self.original_lines: List[str] = []
        # Structure: {PARAM: {'line_num': int/None, 'original_value': str, 'new_value': str/None}}
        self.param_data: Dict[str, Dict[str, Any]] = {}

        self._initialize_param_data()
        self.read_file()

    def _initialize_param_data(self):
        """Pre-fills the data structure with all supported params set to ABSENT."""
        for param in self.supported_params:
            self.param_data[param] = {
                'line_num': None,
                'original_value': STATE_ABSENT,
                'new_value': None
            }

    # --- Core Parsing Methods ---

    def _clean_value(self, line: str) -> str:
        """
        Extracts the parameter value from a line, correctly clipping any unquoted comments.

        Example: 'GRUB_TIMEOUT=5 # 10 seconds default' -> '5'
        Example: 'GRUB_CMDLINE="has #hash" #comment' -> '"has #hash"'
        """
        # Find the assignment part (everything after the first '=')
        try:
            _, assignment_part = line.split('=', 1)
        except ValueError:
            # Should not happen for valid lines, but good for robustness
            return ""

        value_part = assignment_part.strip()
        
        # Look for the first UNQUOTED '#' to find the comment start
        in_single_quotes = False
        in_double_quotes = False
        comment_index = len(value_part)

        for i, char in enumerate(value_part):
            if char == "'" and not in_double_quotes:
                in_single_quotes = not in_single_quotes
            elif char == '"' and not in_single_quotes:
                in_double_quotes = not in_double_quotes
            elif char == '#' and not in_single_quotes and not in_double_quotes:
                comment_index = i
                break

        # Clip the string at the comment index and strip trailing whitespace
        cleaned_value = value_part[:comment_index].rstrip()

        # Remove surrounding quotes if present (simplifies TUI interaction, but keep quotes for cmdline params)
        if cleaned_value.startswith('"') and cleaned_value.endswith('"'):
             # We should generally keep the quotes if the user provides them, but for
             # basic values like GRUB_TIMEOUT=5, we strip them if they were quoted.
             # For simplicity, we just return the cleaned value as is.
             return cleaned_value 
        
        return cleaned_value


    def read_file(self):
        """Reads the GRUB file and populates the internal data structures."""
        try:
            with open(self.file_path, 'r') as f:
                self.original_lines = f.readlines()
        except FileNotFoundError:
            print(f"Warning: File not found at {self.file_path}. Starting with empty configuration.")
            self.original_lines = []
            return

        for i, line in enumerate(self.original_lines):
            line = line.strip()

            if not line:
                continue

            # Check for commented line
            if line.startswith('#'):
                # Check if it's a supported parameter that is commented out
                for param in self.supported_params:
                    # Look for the parameter name followed by '='
                    if re.match(rf"#{param}\s*=", line):
                        self.param_data[param]['line_num'] = i
                        self.param_data[param]['original_value'] = STATE_COMMENTED
                        break
                continue

            # Check for active line
            for param in self.supported_params:
                # Look for the parameter name at the start of the line, followed by '='
                if line.startswith(f"{param}="):
                    self.param_data[param]['line_num'] = i
                    # Extract the value, handling comments correctly
                    self.param_data[param]['original_value'] = self._clean_value(line)
                    break

    # --- TUI Interaction Methods ---

    def get_current_state(self, param: str) -> str:
        """Returns the current effective value or state for a TUI display."""
        if param not in self.param_data:
            raise ValueError(f"Unsupported parameter: {param}")

        # If a new value is set, display that (even if it's ACTION_ZAP)
        if self.param_data[param]['new_value'] is not None:
            return self.param_data[param]['new_value']

        # Otherwise, display the original value/state
        return self.param_data[param]['original_value']

    def set_new_value(self, param: str, value: str):
        """Sets a new, legal value (via Cycle/Edit)."""
        if param not in self.param_data:
            raise ValueError(f"Unsupported parameter: {param}")
        # Note: We trust the TUI to pass a clean, legal value (including necessary quotes)
        self.param_data[param]['new_value'] = value

    def zap_parameter(self, param: str):
        """Sets the parameter for removal (via Zap/Reset to Default)."""
        if param not in self.param_data:
            raise ValueError(f"Unsupported parameter: {param}")
        self.param_data[param]['new_value'] = ACTION_ZAP

    # --- File Writing Method ---

    def write_file(self, output_path: Optional[str] = None):
        """Writes the modified configuration to a new file."""
        output_path = output_path or self.file_path
        new_lines: List[str] = []
        processed_lines: set[int] = set()
        
        # 1. Process existing lines
        for i, original_line in enumerate(self.original_lines):
            line_added = False
            for param, data in self.param_data.items():
                if data['line_num'] == i:
                    processed_lines.add(i)
                    
                    new_value = data['new_value']
                    
                    if new_value is not None:
                        # User made a change (Legal Value or Zap)
                        if new_value == ACTION_ZAP:
                            # Zap action: Skip the line (i.e., remove it)
                            line_added = True 
                            break # Go to next line in original_lines
                        else:
                            # Legal Value: Replace the line with the new value
                            new_lines.append(f"{param}={new_value}\n")
                            line_added = True
                            break
                    else:
                        # new_value is None: No change, keep the original line
                        new_lines.append(original_line)
                        line_added = True
                        break
            
            # If the line was not a supported parameter, keep it
            if not line_added:
                 new_lines.append(original_line)

        # 2. Append new parameters (that were absent in the original file)
        # Note: We append them at the very end of the existing content.
        
        # A simple separator for appended content
        appended_content_added = False
        
        for param, data in self.param_data.items():
            if data['original_value'] == STATE_ABSENT:
                new_value = data['new_value']
                
                if new_value is not None and new_value != ACTION_ZAP:
                    # Found a parameter that was ABSENT but is now set to a Legal Value
                    
                    if not appended_content_added:
                        new_lines.append("\n#---# NOTE: New parameters added by 'grub-wiz' below\n")
                        appended_content_added = True
                        
                    # Add your custom guidance text here if desired
                    new_lines.append(f"{param}={new_value}\n")

        # 3. Write the new content to the file
        with open(output_path, 'w') as f:
            f.writelines(new_lines)
            
        print(f"Configuration successfully written to {output_path}")

# Example Usage (assuming a file named 'grub_test.cfg' exists)
# ----------------------------------------------------------------------
# supported = ["GRUB_TIMEOUT", "GRUB_DEFAULT", "GRUB_CMDLINE_LINUX_DEFAULT", "GRUB_THEME"]
# grub_file = GrubFile('./grub_test.cfg', supported)

# # 1. Example modification
# grub_file.set_new_value("GRUB_TIMEOUT", "5") # Change value

# # 2. Example Zap (Removal)
# grub_file.zap_parameter("GRUB_DEFAULT") # Remove parameter

# # 3. Example Addition (If GRUB_THEME was absent)
# grub_file.set_new_value("GRUB_THEME", "/boot/grub/themes/kubuntu")

# # Write the changes (use a temporary path for testing!)
# # grub_file.write_file('./grub_output.cfg')
