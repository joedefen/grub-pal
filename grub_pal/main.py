#!/usr/bin/env python3

from .WiredConfig import WiredConfig

class GrubPal:
    """ TBD """
    def __init__(self):
      self.params = WiredConfig().data

def main():
    """ TBD """
    pal = GrubPal()
    print(f'{len(pal.params)=}')
    print(f'{type(pal.params['GRUB_TIMEOUT'])=}')

if __name__ == '__main__':
    main()
