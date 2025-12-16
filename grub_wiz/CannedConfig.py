#!/usr/bin/env
"""
"""
from importlib.resources import files
from ruamel.yaml import YAML

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
        'hide': False,  # deprecated
    }
    def __init__(self):
        # 1. Get a Traversable object for the 'grub_wiz' package directory
        resource_path = files('grub_wiz') / 'canned_config.yaml'

        # 2. Open the file resource for reading
        # We use resource_path.read_text() to get the content as a string
        yaml_string = resource_path.read_text()
        self.data = yaml.load(yaml_string)

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