#!/usr/bin/env
"""
"""
from importlib.resources import files
from ruamel.yaml import YAML
from .UserConfigDir import UserConfigDir

yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False

EXPERT_EDIT = '>>EXPERT_EDIT<<', # not a regex (SPECIAL MEANING)
class CannedConfig:
    """ TBD"""
    default_cfg = {  # config schema for a single parameter
        'default': '',  # usually string, can be integer
        'edit_re': EXPERT_EDIT,
        'enums': {},  # key: enum name, value enum description
        'guidance': '',  # often lengthy, may have embedded newlines
    }
    def OLD__init__(self):
        # 1. Get a Traversable object for the 'grub_wiz' package directory
        resource_path = files('grub_wiz') / 'canned_config.yaml'

        # 2. Open the file resource for reading
        # We use resource_path.read_text() to get the content as a string
        yaml_string = resource_path.read_text()
        self.data = yaml.load(yaml_string)
    # In CannedConfig.__init__()

    def __init__(self):
        # 1. Load packaged canned_config
        resource_path = files('grub_wiz') / 'canned_config.yaml'
        self.data = yaml.load(resource_path.read_text())
        self.using_path = resource_path

        config_dir = UserConfigDir.get_singleton().config_dir
        
        # 2. Dump reference copy to config dir
        ref_path = config_dir / 'canned_config.yaml'
        if not ref_path.exists():
            ref_path.write_text(resource_path.read_text())
        
        # 3. Try to load user's custom config
        custom_path = config_dir / 'custom_config.yaml'
        if custom_path.exists():
            try:
                custom_data = yaml.load(custom_path.read_text())
                err =  self.validate_schema(custom_data)
                if err is None:
                    self.data = custom_data  # Or merge if you prefer
                    self.using_path = custom_path
                else:
                    print(f"WARNING: {custom_path} invalid ({err}), using canned config")
            except Exception as e:
                print(f"WARNING: Cannot yaml.load {custom_path}: {e}")

    def validate_schema(self, data):
        """Validate custom config has correct structure"""
        if not isinstance(data, dict):
            return False
        keys_set = set(self.default_cfg.keys())
        
        for section_name, params in data.items():
            if not isinstance(params, dict):
                return f'Section ({section_name!r} value not dict)'
            for param_name, cfg in params.items():
                if not param_name.startswith('GRUB_'):
                    return f'Param ({param_name!r} is not GRUB_*)'
                # Check required fields exist
                if not all(k in cfg for k in keys_set):
                    return f'Param ({param_name!r} dict missing keys'
                # Check no extra fields (strict)
                if set(cfg.keys()) - keys_set:
                    return f'Param ({param_name!r} dict extra keys'
        return None

    def dump(self):
      """ Dump the wired/initial configuration"""
      string = yaml.dump(self.data)
      print(string)

def main():
    """ TBD """
    cfg = CannedConfig()
    cfg.dump()

if __name__ == '__main__':
    main()