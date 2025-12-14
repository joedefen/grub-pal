#!/usr/bin/env python3
"""
    grub-wiz: the help grub file editor assistant
"""
# pylint: disable=invalid-name,broad-exception-caught
# pylint: disable=too-many-locals,too-few-public-methods,too-many-branches
# pylint: disable=too-many-nested-blocks,too-many-statements
# pylint: disable=too-many-public-methods,line-too-long
# pylint: disable=too-many-instance-attributes


import sys
import os
import time
import textwrap
import traceback
import re
import curses as cs
from argparse import ArgumentParser
from types import SimpleNamespace
from typing import Any #, Tuple #, Opt
from console_window import OptionSpinner, ConsoleWindow, ConsoleWindowOpts
from .CannedConfig import CannedConfig
from .GrubParser import GrubParser
from .GrubCfgParser import get_top_level_grub_entries
from .BackupMgr import BackupMgr, GRUB_DEFAULT_PATH
from .WizHider import WizHider
from .GrubWriter import GrubWriter
from .WizValidator import WizValidator
from .ParamDiscovery import ParamDiscovery

HOME_ST, REVIEW_ST, RESTORE_ST, VIEW_ST, HELP_ST = 0, 1, 2, 3, 4  # screen numbers
SCREENS = ('HOME', 'REVIEW', 'RESTORE', 'VIEW', 'HELP') # screen names

class Tab:
    """ TBD """
    def __init__(self, cols, param_wid):
        """           g
        >----left----|a |---right ---|
         |<---lwid-->|p |<---rwid--->|
         la          lz ra           rz

        :param self: provides access to the "tab" positions
        :param cols: columns in window
        :param param_wid: max wid of all param names
        """
        self.cols = cols
        self.la = 1
        self.lz = 1 + param_wid + 4
        self.lwid = self.lz - self.la
        self.gap = 2
        self.ra = self.lz + 2
        self.rz = self.cols
        self.rwid = self.rz - self.ra
        self.wid = self.rz - self.la

class ScreenStack:
    """ TBD """
    def __init__(self, win: ConsoleWindow , spins_obj: object, screens: tuple):
        self.win = win
        self.obj = spins_obj
        self.screens = screens
        self.stack = []
        self.curr = None
        self.push(HOME_ST, 0)

    def push(self, screen, prev_pos):
        """TBD"""
        if self.curr:
            self.curr.pick_pos = self.win.pick_pos
            self.curr.scroll_pos = self.win.scroll_pos
            self.curr.prev_pos = prev_pos
            self.stack.append(self.curr)
        self.curr = SimpleNamespace(num=screen,
                  name=self.screens[screen], pick_pos=-1,
                                scroll_pos=-1, prev_pos=-1)
        self.win.pick_pos = self.win.scroll_pos = 0
        return 0

    def pop(self):
        """ TBD """
        if self.stack:
            self.curr = self.stack.pop()
            self.win.pick_pos = self.curr.pick_pos
            self.win.scroll_pos = self.curr.scroll_pos
            return self.curr.prev_pos
        return None

    def is_curr(self, screens):
        """TBD"""
        def test_one(screen):
            if isinstance(screen, int):
                return screen == self.curr.num
            return str(screen) == self.curr.name
        if isinstance(screens, (tuple, list)):
            for screen in screens:
                if test_one(screen):
                    return True
            return False
        return test_one(screen=screens)

    def act_in(self, action, screens= None):
        """ TBD """
        val =  getattr(self.obj, action)
        setattr(self.obj, action, False)
        return val and (screens is None or self.is_curr(screens))


class Clue:
    """
    A semi-formal object that enforces fixed required fields (cat, ident)
    and accepts arbitrary keyword arguments.
    """
    def __init__(self, cat: str, ident: str='', group_cnt=1, **kwargs: Any):
        """
        Initializes the Clue object.

        :param cat: The required fixed cat (e.g., 'param', 'warn').
        # :param context: A required fixed field providing context.
        :param kwargs: Arbitrary optional fields (e.g., var1='foo', var2='bar').
        """
        # 1. Rigorous Fixed Field Assignment (Validation)
        # Ensure the fixed fields are not empty/invalid if needed
        if not cat:
            raise ValueError("The 'cat' field is required and cannot be empty.")
        # if not ident:
             # raise ValueError("The 'ident' field is required and cannot be empty.")

        self.cat = cat
        self.ident = ident
        # self.keys = keys
        self.group_cnt = group_cnt

        # 2. Forgiving Variable Field Assignment
        # Iterate over the arbitrary keyword arguments (kwargs)
        # and assign them directly as attributes to the instance.
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        # A helpful representation similar to SimpleNamespace
        attrs = [f"{k}={v!r}" for k, v in self.__dict__.items()]
        return f"Clue({', '.join(attrs)})"

class GrubWiz:
    """ TBD """
    singleton = None
    def __init__(self):
        GrubWiz.singleton = self
        self.win = None # place 1st
        self.spinner = None
        self.spins = None
        self.sections = None
        self.param_cfg = None
        self.positions = None
        self.seen_positions = None
        self.hidden_stats = None
        self.prev_pos = None
        self.defined_param_names = None # all of them
        self.param_names = None
        self.param_values = None
        self.param_defaults = None
        self.prev_values = None
        self.parsed = None
        self.param_name_wid = 0
        self.menu_entries = None
        self.backup_mgr = BackupMgr()
        self.hider = None
        self.grub_writer = GrubWriter()
        self.param_discovery = ParamDiscovery()
        self.wiz_validator = None
        self.backups = None
        self.ordered_backup_pairs = None
        self.must_reviews = None
        self.clues = None
        self.next_prompt_seconds = [3.0]
        self.ss = None
        self.is_other_os = None # don't know yet
        self.show_hidden_params = False
        self.show_hidden_warns = False
        self.grub_checksum = ''
        self.bak_lines = None # the currently viewed .bak file
        self.bak_path = None
        self._reinit()

    def _reinit(self):
        """ Call to initialize or re-initialize with new /etc/default/grub """
        self.param_cfg = {}
        self.positions = []
        self.param_values, self.prev_values = {}, {}
        self.param_defaults = {}
        self.must_reviews = None
        self.ss = None
        self.sections = CannedConfig().data

        names = []
        for idx, (section, params) in enumerate(self.sections.items()):
            for name in params.keys():
                names.append(name)
        absent_param_names = set(self.param_discovery.get_absent(names))
        self.defined_param_names = names

        for idx, (section, params) in enumerate(self.sections.items()):
            if idx > 0: # blank line before sections except 1st
                self.positions.append( SimpleNamespace(
                    param_name=None, section_name=' '))
            self.positions.append( SimpleNamespace(
                param_name=None, section_name=section))
            for param_name, payload in params.items():
                if param_name in absent_param_names:
                    continue
                self.param_cfg[param_name] = payload
                self.positions.append(SimpleNamespace(
                    param_name=param_name, section_name=None))
                self.param_defaults[param_name
                            ] = self.param_cfg[param_name]['default']
        self.param_names = list(self.param_cfg.keys())
        if self.wiz_validator is None:
            self.wiz_validator = WizValidator(self.param_cfg)

        self.parsed = GrubParser(params=self.param_names)
        self.parsed.get_etc_default_grub()
        self.prev_pos = -1024  # to detect direction

        name_wid = 0
        for param_name in self.param_names:
            name_wid = max(name_wid, len(param_name))
            value = self.parsed.vals.get(param_name, None)
            if value is None:
                value = self.param_cfg[param_name]['default']
            self.param_values[param_name] = value
        self.param_name_wid = name_wid - len('GRUB_')
        self.prev_values.update(self.param_values)

        self.menu_entries = get_top_level_grub_entries()
        try:
            self.param_cfg['GRUB_DEFAULT']['enums'].update(self.menu_entries)
        except Exception:
            pass
        self.hider = WizHider(param_cfg=self.param_cfg)

    def get_tab(self):
        """ get the tab positions of the print cols """
        return Tab(self.win.cols, self.param_name_wid)

    def setup_win(self):
        """TBD """
        spinner = self.spinner = OptionSpinner()
        self.spins = self.spinner.default_obj
        spinner.add_key('help_mode', '? - enter help screen', category='action')
        spinner.add_key('undo', 'u - revert value', category='action')
        spinner.add_key('cycle_next', 'c,=>,SP - next cycle value',
                        category='action', keys=[ord('c'), cs.KEY_RIGHT, ord(' ')])
        spinner.add_key('cycle_prev', '<=,BS - prev cycle value',
                        category='action', keys=[ord('C'), cs.KEY_LEFT, cs.KEY_BACKSPACE])
        spinner.add_key('edit', 'e - edit value', category='action')
        spinner.add_key('expert_edit', 'E - expert edit (minimal validation)', category='action',
                            keys=[ord('E')])
        spinner.add_key('guide', 'g - guidance level', vals=['Off', 'Enums', "Full"])
        spinner.add_key('hide', 'x - mark/unmark X-params/warnings', category='action')
        spinner.add_key('show_hidden', 's - show/hide the X-params/warnings', category='action')
        spinner.add_key('enter_restore', 'R - enter restore screen', category='action')
        spinner.add_key('restore', 'r - restore selected backup [in restore screen]', category='action')
        spinner.add_key('delete', 'd - delete selected backup [in restore screen]', category='action')
        spinner.add_key('tag', 't - tag/retag a backup file [in restore screen]', category='action')
        spinner.add_key('view', 'v - view a backup file [in restore screen]', category='action')
        spinner.add_key('write', 'w,ENTER - write params and run "grub-update"',
                        category='action', keys=[ord('w'), 10, 13])
        spinner.add_key('escape', 'ESC - back to prev screen',
                        category="action", keys=[27,])
        spinner.add_key('quit', 'q,ctl-c - quit the app', category='action', keys={0x3, ord('q')})
        spinner.add_key('fancy_headers', '_ - cycle fancy headers (Off/Underline/Reverse)',
                        vals=['Underline', 'Reverse', 'Off'], keys=[ord('_')])


        win_opts = ConsoleWindowOpts()
        win_opts.head_line = True
        win_opts.keys = spinner.keys
        win_opts.ctrl_c_terminates = False
        win_opts.return_if_pos_change = True
        win_opts.single_cell_scroll_indicator = True
        win_opts.dialog_abort = True
        self.win = ConsoleWindow(win_opts)

        self.ss = ScreenStack(self.win, self.spins, SCREENS)

    def _get_enums_regex(self):
        """ TBD"""
        enums, regex, param_name = None, None, None
        pos = self.win.pick_pos
        if self.ss.is_curr(HOME_ST):
            if self.seen_positions and 0 <= pos < len(self.seen_positions):
                param_name = self.seen_positions[pos].param_name
        elif self.ss.is_curr(REVIEW_ST):
            if self.clues and 0 <= pos < len(self.clues):
                clue = self.clues[pos]
                if clue.cat == 'param':
                    param_name = clue.ident
        if not param_name:
            return '', {}, {}, ''

        cfg = self.param_cfg[param_name]
        enums = cfg.get('enums', None)
        regex = cfg.get('edit_re', None)
        return param_name, cfg, enums, regex

    def add_restore_head(self):
        """ TBD """
        header = 'RESTORE [d]elete [t]ag [r]estore [v]iew ESC:back ?:help [q]uit'
        self.add_fancy_header(header)

    def add_restore_body(self):
        """ TBD """
        for pair in self.ordered_backup_pairs:
            prefix = '●' if pair[0] == self.grub_checksum else ' '
            self.win.add_body(f'{prefix} {pair[1].name}')

    def add_view_head(self):
        """ TBD """
        header = f'VIEW  {self.bak_path.name!r}  ESC:back ?:help [q]uit'
        self.add_fancy_header(header)

    def add_view_body(self):
        """ TBD """
        wid = self.win.cols - 7 # 4 num + SP before + 2SP after
        for idx, line in enumerate(self.bak_lines):
            self.win.add_body(f'{idx:>4}', attr=cs.A_BOLD)
            self.win.add_body(f'  {line[:wid]}', resume=True)
            line = line[wid:]
            while line:
                self.win.add_body(f'{' ':>6}{line[:wid]}')
                line = line[wid:]

    def add_review_head(self):
        """ Construct the review screen header
            Presumes the body was created and self.clues[]
            is populated.
        """
        self.add_common_head1('REVIEW')

        # if any warn is hidden on this screen, then show
        header, cnt = '', self.hidden_stats.warn
        if cnt:
            header = 's:hide' if self.show_hidden_warns else '[s]how'
            header += f' {cnt} ✘-warns'
        header = f'{header:<24}'
        self.add_common_head2(header)
        self.ensure_visible_group()

    def truncate_line(self, line):
        """ TBD """
        wid = self.win.cols-1
        if len(line) > wid:
            line = line[:wid-1] + '▶'
        return line

    def add_wrapped_body_line(self, line, indent, is_current):
        """ TBD """
        if not is_current:
            self.win.add_body(self.truncate_line(line))
            return 1

        wid = self.win.cols
        wrapped = textwrap.fill(line, width=wid-1,
                    subsequent_indent=' '*indent)
        wraps = wrapped.split('\n')
        for wrap in wraps:
            self.win.add_body(wrap)
        return len(wraps) # lines added

    def is_warn_hidden(self, param_name, hey):
        """ TBD """
        if not self.show_hidden_warns:
            warn_key = f'{param_name} {hey[1]}'
            return self.hider.is_hidden_warn(warn_key)
        return False


    def add_review_body(self):
        """ TBD """
        def add_review_item(param_name, value, old_value=None, heys=None):
            nonlocal reviews
            if param_name not in reviews:
                reviews[param_name] = SimpleNamespace(
                    value=value,
                    old_value=old_value,
                    heys=[] if heys is None else heys
                )
            return reviews[param_name]

        reviews = {}
        self.hidden_stats = SimpleNamespace(param=0, warn=0)
        diffs = self.get_diffs()
        warns, all_warn_keys = self.wiz_validator.make_warns(self.param_values)
        self.hider.purge_orphan_keys(all_warn_keys) # TODO: just run this once?
        if self.must_reviews is None:
            self.must_reviews = set()
        for param_name in list(diffs.keys()):
            self.must_reviews.add(param_name)
        for param_name, heys in warns.items():
            for hey in heys:
#               if self.is_warn_hidden(param_name, hey):
#                   continue
                words = re.findall(r'\b[_A-Z]+\b', hey[1])
                for word in words:
                    other_name = word
                    if f'GRUB_{word}'in self.param_values:
                        other_name = f'GRUB_{word}'
                    elif word not in self.param_values:
                        continue
                    if other_name not in self.must_reviews:
                        self.must_reviews.append(other_name)
                if param_name not in self.must_reviews:
                    self.must_reviews.add(param_name)

        for param_name in self.param_names:
            if param_name not in self.must_reviews:
                continue
            if param_name in diffs:
                old_value, new_value = diffs[param_name]
                item = add_review_item(param_name, new_value, old_value)
            else:
                value = self.param_values[param_name]
                item = add_review_item(param_name, value)
            heys = warns.get(param_name, None)
            if heys:
                item.heys += heys

        self.clues = []
        picked = self.win.pick_pos

        for param_name, ns in reviews.items():
            clue_idx = len(self.clues)
            param_pos = pos = len(self.clues)
#           keys, indent = [], 30
            tab = self.get_tab()
            is_current = bool(pos==picked)
            param_lines = self.body_param_lines(param_name, is_current)
            self.clues.append(Clue('param', param_name))
            for line in param_lines:
                self.win.add_body(line)
            pos += len(param_lines)

            changed = bool(ns.old_value is not None
                           and str(ns.value) != str(ns.old_value))
            if changed:
                pos += 1
                self.win.add_body(f'{"was":>{tab.lwid}}  {ns.old_value}')
                self.clues.append(Clue('nop'))

            for hey in ns.heys:
                warn_key = f'{param_name} {hey[1]}'
                is_hidden = self.hider.is_hidden_warn(warn_key)
                self.hidden_stats.warn += int(is_hidden)

                if not is_hidden or self.show_hidden_warns:
                    mark = '✘' if is_hidden else ' '
                    sub_text = f'{mark} {hey[0]:>4}'
                    line = f'{sub_text:>{tab.lwid}}  {hey[1]}'
                    cnt = self.add_wrapped_body_line(line,
                                        tab.lwid+2, pos==picked)
                    self.clues.append(Clue('warn', warn_key, cnt))
                    pos += cnt
            self.clues[clue_idx].group_cnt = pos - param_pos

            if is_current:
                emits = self.drop_down_lines(param_name)
                pos += len(emits)
                for emit in emits:
                    self.win.add_body(emit)

    def get_diffs(self):
        """ get the key/value pairs with differences"""
        diffs = {}
        for key, value in self.prev_values.items():
            new_value = self.param_values[key]
            if str(value) != str(new_value):
                diffs[key] = (value, new_value)
        return diffs

    def add_fancy_header(self, line):
        """
        Parses header line and adds it with fancy formatting if enabled.
        Modes: 'Off' (normal), 'Underline' (underlined keys), 'Reverse' (reverse video keys)
        Converts [x]text to formatted x (brackets removed) when mode is on.
        Also handles x:text patterns by formatting x.
        If first word is all-caps, makes it BOLD.
        """

        mode = self.spins.fancy_headers
        if mode == 'Off':
            # Fancy mode off, just add the line normally
            self.win.add_header(line)
            return

        # Choose the attribute based on mode
        key_attr = (cs.A_UNDERLINE|cs.A_BOLD) if mode == 'Underline' else cs.A_REVERSE

        # Pattern to match [x]text or x:text (single letter before colon)
        # We'll process the line character by character to handle both patterns
        result_sections = []  # List of (text, attr) tuples
        i = 0
        current_text = ""

        # Check if line starts with all-caps word and extract it
        stripped = line.lstrip()
        if stripped:
            first_word_match = stripped.split()[0] if stripped.split() else ''
            if first_word_match and first_word_match.isupper() and first_word_match.isalpha():
                # Add leading whitespace
                leading_space = line[:len(line) - len(stripped)]
                if leading_space:
                    result_sections.append((leading_space, None))
                # Add the all-caps word in BOLD
                result_sections.append((first_word_match, cs.A_BOLD))
                # Skip past it in our processing
                i = len(leading_space) + len(first_word_match)

        while i < len(line):
            # Check for [x]text pattern
            if line[i] == '[' and i + 2 < len(line) and line[i + 2] == ']':
                # Save any accumulated normal text
                if current_text:
                    result_sections.append((current_text, None))
                    current_text = ""

                # Extract the key letter and add it with chosen attribute
                key_char = line[i + 1]
                result_sections.append((key_char, key_attr))
                i += 3  # Skip past [x]

            # Check for multi-character key names like ESC:, ENTER:, TAB:
            elif (i == 0 or line[i - 1] == ' '):
                # Look ahead for uppercase word followed by colon
                match = re.match(r'([A-Z]{2,}|[A-Z]):', line[i:])
                if match:
                    # Found a key name followed by colon
                    if current_text:
                        result_sections.append((current_text, None))
                        current_text = ""

                    key_name = match.group(1)
                    result_sections.append((key_name, key_attr))
                    result_sections.append((':', None))  # Add the colon without formatting
                    i += len(key_name) + 1  # Skip past key and colon
                else:
                    # Not a key pattern, just regular character
                    current_text += line[i]
                    i += 1

            else:
                # Regular character
                current_text += line[i]
                i += 1

        # Add any remaining text
        if current_text:
            result_sections.append((current_text, None))

        # Now output the sections using add_header with resume
        for idx, (text, attr) in enumerate(result_sections):
            resume = bool(idx > 0)  # Resume for all but the first section
            self.win.add_header(text, attr=attr, resume=resume)

    def add_common_head1(self, title):
        """ TBD"""
        header = f'{title} '
        level = self.spins.guide
        esc = ' ESC:back' if self.ss.is_curr(REVIEW_ST) else ''
        header += f' [g]uide={level} [w]rite [R]estore{esc} ?:help [q]uit'
        header += f'  𝚫={len(self.get_diffs())}'
        self.add_fancy_header(header)
        self.hider.write_if_dirty()

    def add_common_head2(self, left):
        """ TBD"""
        tab = self.get_tab()
        review = self.ss.is_curr(REVIEW_ST)
        picked = self.win.pick_pos
        if 0 <= picked < len(self.clues):
            clue = self.clues[picked]
            cat, ident = clue.cat, clue.ident
        else:
            cat, ident = '', ''


        middle =  ''
        if cat == 'param':
            param_name, _, enums, regex = self._get_enums_regex()
            if enums:
                # middle += ' 🡄 🡆'⮕
                # middle += '🠜🠞'
                middle += '⮜–⮞'
            if regex:
                middle += ' [e]dit'
            if not review and param_name:
                middle += ' x:unmark' if self.hider.is_hidden_param(
                            param_name) else ' x:mark'
        if cat == 'warn' and review:
            middle += ' x:unmark' if self.hider.is_hidden_warn(
                        ident) else ' x:mark'

        self.add_fancy_header(f'{left:<{tab.lwid}}  {middle}')

    def add_home_head(self):
        """ TBD"""
        self.add_common_head1('EDIT')
        tab = self.get_tab()

        # if any param is hidden on this screen, then show
        header, cnt = '', self.hidden_stats.param
        if cnt:
            header = 's:hide' if self.show_hidden_params else '[s]how'
            header += f' {cnt} ✘-params'
        header = f'{header:<{tab.lwid}}'

        self.add_common_head2(header)
        self.ensure_visible_group()

    def ensure_visible_group(self):
        """ TBD """
        win = self.win
        pos = win.pick_pos
        group_cnt = 1
        if 0 <= pos < len(self.clues):
            group_cnt = self.clues[pos].group_cnt
        over = pos - win.scroll_pos + group_cnt - win.scroll_view_size
        if over >= 0:
            win.scroll_pos += over + 1 # scroll back by number of out-of-view lines
            self.next_prompt_seconds = [0.1, 0.1]


    def adjust_picked_pos_w_clues(self):
        """ This assumes: the clues were created by the body.
        """

        pos = self.win.pick_pos
        if not self.ss.is_curr((HOME_ST, REVIEW_ST)):
            return pos
        if not self.clues:
            return pos

        pos = max(min(len(self.clues)-1, pos), 0)
        if pos == self.win.pick_pos and pos == self.prev_pos:
            self.ensure_visible_group()
            return pos
        up = bool(pos >= self.prev_pos)
        for _ in range(2):
            clue = self.clues[pos]
            while clue.cat in ('nop', ):
                pos += 1 if up else -1
                if 0 <= pos < len(self.clues):
                    clue = self.clues[pos]
                else:
                    pos = max(min(len(self.clues)-1, pos), 0)
                    break
            up = bool(not up)

        self.win.pick_pos = pos
        self.prev_pos = pos
        # now ensure the whole group is viewable
        self.ensure_visible_group()
        return pos

    def body_param_lines(self, param_name, is_current):
        """ Build a body line for a param """
        tab = self.get_tab()
        marker = ' '
        if self.ss.is_curr(HOME_ST) and self.hider.is_hidden_param(param_name):
            marker = '✘'
        value = self.param_values[param_name]
        line = f'{marker} {param_name[5:]:·<{tab.lwid-2}}'
        indent = len(line)
        line += f'  {value}'
        wid = self.win.cols - 1 # effective width
        if len(line) > wid and is_current:
            line = textwrap.fill(line, width=wid,
                       subsequent_indent=' '*indent)
        elif len(line) > wid and not is_current:
            line = line [:self.win.cols-2] + '⯈'
        return line.splitlines()

    def add_home_body(self):
        """ TBD """
        self.hidden_stats = SimpleNamespace(param=0, warn=0)
        win = self.win # short hand
        picked = win.pick_pos
        emits = []
        #view_size = win.scroll_view_size
        found_current = False
        self.seen_positions = []
        self.clues = []
        for ns in self.positions:
            self.hidden_stats.param += int(self.hider.is_hidden_param(ns.param_name))
            if (not ns.param_name or self.show_hidden_params
                    or not self.hider.is_hidden_param(ns.param_name)):
                self.seen_positions.append(ns)
        for pos, ns in enumerate(self.seen_positions):
            if ns.section_name == ' ':
                win.add_body(f'{ns.section_name}')
                self.clues.append(Clue('nop'))
                continue
            if ns.section_name:
                win.add_body(f'[{ns.section_name}]')
                self.clues.append(Clue('nop'))
                continue

            param_name = ns.param_name
            is_current = bool(picked == pos)
            param_lines = self.body_param_lines(param_name, is_current)
            if pos != picked:
                line = param_lines[0]
                if len(param_lines) > 1:
                    line = line[:self.win.cols-2] + '⯈'
                win.add_body(line)
                self.clues.append(Clue('param', 'param_name'))
                continue
            found_current = True
            # cfg = self.param_cfg[param_name]
            # value = self.param_values[param_name]
            emits += param_lines

            emits += self.drop_down_lines(param_name)

            # truncate the lines to show to all that fit..
            view_size = win.scroll_view_size
            if len(emits) > view_size:
                hide_cnt = 1 + len(emits) - view_size
                emits = emits[0:view_size-1]
                emits.append(f'... beware: {hide_cnt} HIDDEN lines ...')
            for emit in emits:
                win.add_body(emit)
            self.clues.append(Clue('param', 'param_name', len(emits)))
        return found_current

    def drop_down_lines(self, param_name):
        """ TBD """
        def gen_enum_lines():
            nonlocal cfg, wid
            enums = cfg['enums']
            if not enums:
                return []
            value = self.param_values[param_name]
            edit = ' or [e]dit' if cfg['edit_re'] else ''
            # wrapped = f': 🡄 🡆 {edit}:\n'
            wrapped = f': ⮜–⮞ {edit}:\n'
            for enum, descr in cfg['enums'].items():
                star = ' ⯀ ' if str(enum) == str(value) else ' 🞏 '
                line = f' {star}{enum}: {descr}\n'
                wrapped += textwrap.fill(line, width=wid-1, subsequent_indent=' '*5)
                wrapped += '\n'
            return wrapped.split('\n')

        if self.spins.guide == 'Off':
            return []

        cfg = self.param_cfg.get(param_name, None)
        if not cfg:
            return ''
        emits, wraps = [], [] # lines to emit
        lead = '    '
        wid = self.win.cols - len(lead)

        if self.spins.guide == 'Full':
            text = cfg['guidance']
            lines = text.split('\n')
            for line in lines:
                wrapped = ''
                if line.strip() == '%ENUMS%':
                    wraps += gen_enum_lines()
                else:
                    wrapped = textwrap.fill(line, width=wid-1, subsequent_indent=' '*5)
                    wraps += wrapped.split('\n')
        elif self.spins.guide == 'Enums':
            wraps += gen_enum_lines()
        emits = [f'{lead}{wrap}' for wrap in wraps if wrap]
        return emits

    def edit_param(self, win, name, regex):
        """ Prompt user for answer until gets it right"""
        value = self.param_values[name]
        valid = False
        hint, pure_regex = '', ''
        if regex:
            pure_regex = regex.encode().decode('unicode_escape')
            hint += f'  pat={pure_regex}'
        hint = hint[2:]

        while not valid:
            prompt = f'Edit {name} [{hint}]'
            value = win.answer(prompt=prompt, seed=str(value), height=2)
            if value is None: # aborted
                return
            valid = True # until proven otherwise
            if regex and not re.match(regex, str(value)):
                valid, hint = False, f'must match: {pure_regex}'
                win.flash('Invalid input - please try again', duration=1.5)

        self.param_values[name] = value

    def expert_edit_param(self, win, name):
        """ Expert mode edit with minimal validation - escape hatch for grub-wiz errors """
        value = self.param_values[name]
        valid = False
        hint = 'expert mode: minimal checks'

        while not valid:
            prompt = f'Edit {name} [EXPERT MODE: {hint}]'
            value = win.answer(prompt=prompt, seed=str(value), height=2)
            if value is None: # aborted
                return

            # Minimal validation: ensure it's a safe shell token
            # Allow: empty, unquoted word, single-quoted, or double-quoted
            valid = True
            if value and not self._is_valid_shell_token(value):
                valid = False
                hint = 'must be empty, word, or quoted string'
                win.flash('Invalid shell token - check quoting', duration=1.5)

        self.param_values[name] = value

    def _is_valid_shell_token(self, value):
        """ Check if value is a valid shell token (minimal safety check) """
        if not value:  # empty is valid
            return True

        # Single-quoted: everything between quotes is literal
        if value.startswith("'") and value.endswith("'") and len(value) >= 2:
            return True

        # Double-quoted: check for balanced quotes
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            # Basic check: allow escaped quotes, but no bare unescaped quotes inside
            inner = value[1:-1]
            # Replace escaped quotes, then check for any remaining unescaped quotes
            check = inner.replace('\\"', '')
            return '"' not in check

        # Unquoted word: no spaces or special shell chars
        if ' ' in value or '\t' in value or '\n' in value:
            return False
        # Disallow dangerous shell chars in unquoted strings
        dangerous = set(';&|<>(){}[]$`\\!')
        if any(c in value for c in dangerous):
            return False

        return True

    def refresh_backup_list(self):
        """ TBD """
        self.backups = self.backup_mgr.get_backups()
        self.ordered_backup_pairs = sorted(self.backups.items(),
                           key=lambda item: item[1], reverse=True)

    def request_backup_tag(self, prompt, seed='custom'):
        """ Prompt user for a valid tag ... turn spaces into '-'
         automatically """
        regex = r'^[-_A-Za-z0-9]+$'
        hint = f'regex={regex}'
        while True:
            answer = self.win.answer(seed=seed, prompt=f"{prompt} [{hint}]]")
            if answer is None:
                return None
            answer = answer.strip()
            answer = re.sub(r'[-\s]+', '-', answer)
            if re.match(regex, answer):
                return answer

    def do_start_up_backup(self):
        """ On startup
            - install the "orig" backup of none
            - offer to install any uniq backup
        """
        self.refresh_backup_list()
        checksum = self.backup_mgr.calc_checksum(GRUB_DEFAULT_PATH)
        if not self.backups:
            self.backup_mgr.create_backup('orig')

        elif checksum not in self.backups:
            answer = self.request_backup_tag(f'Enter a tag to back up {GRUB_DEFAULT_PATH}')
            if answer:
                self.backup_mgr.create_backup(answer)
        self.grub_checksum = checksum # checksum of loaded grub

    def really_wanna(self, act):
        """ TBD """
        answer = self.win.answer(seed='y', prompt=f"Enter 'yes' to {act}")
        if answer is None:
            return False
        answer = answer.strip().lower()
        return answer.startswith('y')

    def update_grub(self):
        """ TBD """
        if not self.really_wanna('commit changes and update GRUB'):
            return

        contents =  "#--# NOTE: this file was built with 'grub-wiz'\n"
        contents += "#--#     - We suggest updating the following params with 'grub-wiz'\n"
        contents += "#--#       although not required'\n"
        for name, value in self.param_values.items():
            contents += f'{name}={value}\n'
        contents += "#--# NOTE: following are params NOT handled by 'grub-wiz'\n"
        contents += "#--#     - update these manually.\n"
        contents += ''.join(self.parsed.other_lines)

        self.win.stop_curses()
        print("\033[2J\033[H") # 'clear'
        print('\n\n===== Left grub-wiz to update GRUB ====> ')
        # print('Check for correctness...')
        # print('-'*60)
        # print(contents)
        # print('-'*60)
        ok = True
        commit_rv = self.grub_writer.commit_validated_grub_config(contents)
        if not commit_rv[0]: # failure
            print(commit_rv[1])
            ok = False
        else:
            install_rv = self.grub_writer.run_grub_update()
            if not install_rv[0]:
                print(install_rv[1])
                ok = False
        if ok:
            os.system('clear ; echo "OK ... newly installed" ;  cat /etc/default/grub')
            print('\n\nUpdate successful! Choose:')
            print('  [r]eboot now')
            print('  [p]oweroff')
            print('  ENTER to return to grub-wiz')

            choice = input('\n> ').strip().lower()

            if choice == 'r':
                print('\nRebooting...')
                os.system('reboot')
                sys.exit(0)  # Won't reach here, but just in case
            elif choice == 'p':
                print('\nPowering off...')
                os.system('poweroff')
                sys.exit(0)  # Won't reach here, but just in case
            # Otherwise continue to grub-wiz
        else:
            input('\n\n===== Press ENTER to return to grub-wiz ====> ')

        self.win.start_curses()
        if ok:
            self._reinit()
            self.ss = ScreenStack(self.win, self.spins, SCREENS)
            self.do_start_up_backup()

    def find_in(self, value, enums=None, cfg=None):
        """ Find the value in the list of choices using only
        string comparisons (because representation uncertain)

        Returns ns (.idx, .next_idx, .next_value, .prev_idx, .prev_value)
        """
        choices = None
        if cfg:
            enums = cfg.get(enums, [])
        if enums:
            choices = list(enums.keys())
        assert choices

        idx = -1 # default to before first
        for ii, choice in enumerate(choices):
            if str(value) == str(choice):
                idx = ii
                break
        next_idx = (idx+1) % len(choices)
        next_value = choices[next_idx] # choose next
        prev_idx = (idx+len(choices)-1) % len(choices)
        prev_value = choices[prev_idx] # choose next
        return SimpleNamespace(idx=idx, choices=choices,
                       next_idx=next_idx, next_value=next_value,
                       prev_idx=prev_idx, prev_value=prev_value)


    def main_loop(self):
        """ TBD """
        assert self.parsed.get_etc_default_grub()

        self.setup_win()
        self.do_start_up_backup()
        win, spins = self.win, self.spins # shorthand
        self.next_prompt_seconds = [0.1, 0.1]

        while True:
            if self.ss.is_curr(HELP_ST):
                win.set_pick_mode(False)
                self.spinner.show_help_nav_keys(win)
                self.spinner.show_help_body(win)

            elif self.ss.is_curr(VIEW_ST):
                win.set_pick_mode(False)
                self.add_view_body()
                self.add_view_head()

            elif self.ss.is_curr(RESTORE_ST):
                win.set_pick_mode(True)
                self.add_restore_body()
                self.add_restore_head()

            elif self.ss.is_curr(REVIEW_ST):
                win.set_pick_mode(True)
                self.add_review_body()
                self.add_review_head()

            else: # HOME_ST screen
                win.set_pick_mode(True)
                self.add_home_body()
                self.add_home_head()

            win.render()
            key = win.prompt(seconds=self.next_prompt_seconds[0])

            self.next_prompt_seconds.pop(0)
            if not self.next_prompt_seconds:
                self.next_prompt_seconds = [3.0]

            if key is None:
                if self.ss.is_curr(REVIEW_ST
                           ) or self.ss.is_curr(HOME_ST):
                    self.adjust_picked_pos_w_clues()

            if key is not None:
                self.spinner.do_key(key, win)
                if spins.quit:
                    spins.quit = False
                    if self.ss.is_curr(RESTORE_ST):
                        self.prev_pos = self.ss.pop()
                    else:
                        break

                name, _, enums, regex = '', None, {}, ''
                if self.ss.is_curr((HOME_ST, REVIEW_ST)):
                    name, _, enums, regex = self._get_enums_regex()
                if self.ss.act_in('escape', (REVIEW_ST, RESTORE_ST, VIEW_ST)):
                    if self.ss.stack:
                        self.prev_pos = self.ss.pop()
                        self.must_reviews = None  # Reset cached review data
                        self.bak_lines, self.bak_path = None, None
                if spins.help_mode:
                    spins.help_mode = True
                if self.ss.act_in('help_mode', (HOME_ST, REVIEW_ST, RESTORE_ST)):
                    self.prev_pos = self.ss.push(HELP_ST, self.prev_pos)

                if self.ss.act_in('cycle_next', (HOME_ST, REVIEW_ST)):
                    if enums:
                        value = self.param_values[name]
                        found = self.find_in(value, enums)
                        self.param_values[name] = found.next_value

                if self.ss.act_in('cycle_prev', (HOME_ST, REVIEW_ST)):
                    if enums:
                        value = self.param_values[name]
                        found = self.find_in(value, enums)
                        self.param_values[name] = found.prev_value

                if self.ss.act_in('undo', REVIEW_ST):
                    if name:
                        prev_value = self.prev_values[name]
                        self.param_values[name] = prev_value

                if self.ss.act_in('show_hidden', (REVIEW_ST, HOME_ST)):
                    if self.ss.is_curr(REVIEW_ST):
                        self.show_hidden_warns = not self.show_hidden_warns
                    if self.ss.is_curr(HOME_ST):
                        self.show_hidden_params = not self.show_hidden_params

                if self.ss.act_in('edit', (HOME_ST, REVIEW_ST)):
                    if regex:
                        self.edit_param(win, name, regex)

                if self.ss.act_in('expert_edit', (HOME_ST, REVIEW_ST)):
                    if name:
                        self.expert_edit_param(win, name)

                if self.ss.act_in('hide', (HOME_ST, REVIEW_ST)):
                    if self.ss.is_curr(HOME_ST) and name:
                        if self.hider.is_hidden_param(name):
                            self.hider.unhide_param(name)
                        else:
                            self.hider.hide_param(name)
                    if self.ss.is_curr(REVIEW_ST):
                        pos = self.win.pick_pos
                        if self.clues and 0 <= pos < len(self.clues):
                            clue = self.clues[pos]
                            if clue.cat == 'warn':
                                if self.hider.is_hidden_warn(clue.ident):
                                    self.hider.unhide_warn(clue.ident)
                                else:
                                    self.hider.hide_warn(clue.ident)

                if self.ss.act_in('write', (HOME_ST, REVIEW_ST)):
                    if self.ss.is_curr(HOME_ST):
                        self.prev_pos = self.ss.push(REVIEW_ST, self.prev_pos)
                        self.must_reviews = None # reset
                        self.clues = []
                    else: # REVIEW_ST
                        self.update_grub()

                if self.ss.act_in('enter_restore', (HOME_ST, REVIEW_ST)):
                    self.prev_pos = self.ss.push(RESTORE_ST, self.prev_pos)
                    self.do_start_up_backup()

                if spins.restore:
                    spins.restore = True
                if self.ss.act_in('restore', RESTORE_ST):
                    idx = self.win.pick_pos
                    if 0 <= idx < len(self.ordered_backup_pairs):
                        key = self.ordered_backup_pairs[idx][0]
                        self.backup_mgr.restore_backup(self.backups[key])
                        self.prev_pos = self.ss.pop()
                        assert self.ss.is_curr(HOME_ST)
                        self._reinit()
                        self.ss = ScreenStack(self.win, self.spins, SCREENS)
                        self.do_start_up_backup()

                if self.ss.act_in('delete', RESTORE_ST):
                    idx = self.win.pick_pos
                    if 0 <= idx < len(self.ordered_backup_pairs):
                        doomed = self.ordered_backup_pairs[idx][1]
                        if self.really_wanna(f'remove {doomed!r}'):
                            try:
                                os.unlink(doomed.name)
                            except Exception as exce:
                                self.win.alert(
                                    message=f'ERR: unlink({doomed.name}) [{exce}]')
                            self.refresh_backup_list()

                if self.ss.act_in('tag', RESTORE_ST):
                    idx = self.win.pick_pos
                    if 0 <= idx < len(self.ordered_backup_pairs):
                        chosen = self.ordered_backup_pairs[idx][1]
                        tag = self.request_backup_tag(f'Enter tag for {chosen.name}',
                                                      seed='')
                        if tag:
                            new_name = re.sub(r'[^.]+\.bak$', f'{tag}.bak', chosen.name)
                            new_path = chosen.parent / new_name
                            if new_path != chosen:
                                try:
                                    os.rename(chosen, new_path)
                                except Exception as exce:
                                    self.win.alert(
                                        message=f'ERR: rename({chosen.name}, {new_path.name}) [{exce}]')
                            self.refresh_backup_list()

                if self.ss.act_in('view', RESTORE_ST):
                    idx = self.win.pick_pos
                    if 0 <= idx < len(self.ordered_backup_pairs):
                        try:
                            self.bak_path = self.ordered_backup_pairs[idx][1]
                            self.bak_lines = self.bak_path.read_text().splitlines()
                            assert isinstance(self.bak_lines, list)
                            self.prev_pos = self.ss.push(VIEW_ST, self.prev_pos)
                        except Exception as ex:
                            self.win.alert(f'ERR: cannot slurp {self.bak_path} [{ex}]')

            win.clear()

def rerun_module_as_root(module_name):
    """ rerun using the module name """
    if os.geteuid() != 0: # Re-run the script with sudo
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        vp = ['sudo', sys.executable, '-m', module_name] + sys.argv[1:]
        os.execvp('sudo', vp)


def main():
    """ TBD """
    rerun_module_as_root('grub_wiz.main')
    parser = ArgumentParser(description='grub-wiz: your grub-update guide')
    parser.add_argument('--discovery', '--parameter-discovery', default=None,
                        choices=('enable', 'disable', 'show'),
                        help='control/show parameter discovery state')
    parser.add_argument('--factory-reset', action='store_true',
                        help='restore out-of-box experience (but keeping .bak files)')
    parser.add_argument('--validator-demo', action='store_true',
                        help='for test only: run validator demo')
    opts = parser.parse_args()

    wiz = GrubWiz()
    if opts.validator_demo:
        wiz.wiz_validator.demo(wiz.param_defaults)
        sys.exit(0)

    if opts.discovery is not None:
        if opts.discovery in ('enable', 'disable'):
            enabled = wiz.param_discovery.manual_enable(opts.paramd == 'enable')
            print(f'\nParameterDiscovery: {enabled=}')
        else:
            wiz.param_discovery.dump(wiz.defined_param_names)
            absent_params = wiz.param_discovery.get_absent(wiz.defined_param_names)
            print(f'\nPruned {absent_params=}')
        sys.exit(0)

    if opts.factory_reset:
        print('Factory reset: clearing user preferences...')
        deleted = []
        try:
            for target in (wiz.param_discovery.cache_file,
                            wiz.hider.yaml_path):
                if os.path.isfile(target):
                    os.unlink(target)
                    deleted.append(str(target))
            if deleted:
                print(f'Deleted: {", ".join(deleted)}')
            else:
                print('No cached files to delete.')
            print('Factory reset complete. Backup files (.bak) preserved.')
        except Exception as whynot:
            print(f'ERR: failed "factory reset" [{whynot}]')
        sys.exit(0)



    time.sleep(1.0)
    wiz.main_loop()

if __name__ == '__main__':
    try:
        main()
    except Exception as exce:
        if GrubWiz.singleton and GrubWiz.singleton.win:
            GrubWiz.singleton.win.stop_curses()
        print("exception:", str(exce))
        print(traceback.format_exc())
        sys.exit(15)
