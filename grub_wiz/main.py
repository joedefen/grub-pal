#!/usr/bin/env python3
r"""
    grub-wiz: the help grub file editor assistant

"""
# pylint: disable=invalid-name,broad-exception-caught
# pylint: disable=too-many-locals,too-few-public-methods,too-many-branches
# pylint: disable=too-many-nested-blocks,too-many-statements
# pylint: disable=too-many-public-methods,line-too-long
# pylint: disable=too-many-instance-attributes,too-many-lines


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
from .CannedConfig import CannedConfig, EXPERT_EDIT
from .DistroVars import DistroVars
from .GrubFile import GrubFile
from .GrubCfgParser import get_top_level_grub_entries
from .BackupMgr import BackupMgr, GRUB_DEFAULT_PATH
from .WarnDB import WarnDB
from .GrubWriter import GrubWriter
from .WizValidator import WizValidator
from .ParamDiscovery import ParamDiscovery
from .UserConfigDir import UserConfigDir

HOME_ST, REVIEW_ST, RESTORE_ST, VIEW_ST, COMPARE_ST, WARN_ST, HELP_ST  = 0, 1, 2, 3, 4, 5, 6
SCREENS = 'HOME REVIEW RESTORE VIEW COMPARE WARN HELP'.split() # screen names

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
    def __init__(self, win: ConsoleWindow , spins_obj: object, screens: tuple, screen_objects: dict = None):
        self.win = win
        self.obj = spins_obj
        self.screens = screens
        self.screen_objects = screen_objects or {}  # Dict of screen_num -> Screen instance
        self.stack = []
        self.curr = None
        self.push(HOME_ST, 0)

    def push(self, screen, prev_pos, force=False):
        """
        Push a new screen onto the stack with validation and loop prevention.

        Args:
            screen: Screen number to push
            prev_pos: Previous cursor position
            force: Skip validation hooks if True

        Returns:
            Previous position if successful, None if blocked by validation
        """
        # Loop prevention: Check if screen is already on the stack
        if not force and self.curr and screen == self.curr.num:
            # Trying to push the current screen again - ignore
            return None

        # Check if screen is already in the stack (deeper loop)
        if not force:
            for stacked_screen in self.stack:
                if stacked_screen.num == screen:
                    # Would create a loop - block it
                    return None

        from_screen_num = self.curr.num if self.curr else None
        new_screen_obj = self.screen_objects.get(screen) if self.screen_objects else None

        # Check navigation constraints
        if not force and new_screen_obj:
            # Check if screen is terminal (cannot be pushed)
            if new_screen_obj.is_terminal:
                return None

            # Check come_from whitelist
            if new_screen_obj.come_from_whitelist is not None:
                if from_screen_num not in new_screen_obj.come_from_whitelist:
                    # Navigation from this screen not allowed
                    return None

        # Call on_pause() on current screen (it's being covered)
        if not force and self.curr and self.screen_objects:
            current_screen_obj = self.screen_objects.get(from_screen_num)
            if current_screen_obj:
                if not current_screen_obj.on_pause():
                    # Current screen rejected being paused
                    return None

        # Navigation approved - proceed
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

    def pop(self, force=False):
        """
        Pop the top screen from the stack.
        on_pop() is always called for cleanup (cannot be rejected).
        on_resume() is called on the screen being returned to (typically always succeeds).

        Args:
            force: Skip validation hooks if True

        Returns:
            Previous position if successful, None if stack is empty
        """
        if not self.stack:
            return None

        to_screen_num = self.stack[-1].num
        from_screen_num = self.curr.num if self.curr else None

        # Call on_pop() on current screen (it's being removed - always succeeds)
        if not force and self.curr and self.screen_objects:
            current_screen_obj = self.screen_objects.get(from_screen_num)
            if current_screen_obj:
                current_screen_obj.on_pop()  # Always called, cannot reject

        # Call on_resume() on the screen we're returning to
        if not force and self.screen_objects:
            prev_screen_obj = self.screen_objects.get(to_screen_num)
            if prev_screen_obj:
                if not prev_screen_obj.on_resume():
                    # Previous screen rejected resuming (rare, but allowed)
                    return None

        # Navigation approved - proceed
        self.curr = self.stack.pop()
        self.win.pick_pos = self.curr.pick_pos
        self.win.scroll_pos = self.curr.scroll_pos
        return self.curr.prev_pos

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

class Screen:
    """Base class for all screen types"""
    # Navigation control (class attributes - override in subclasses)
    come_from_whitelist = None  # None = can come from any screen, else list of screen numbers
    is_terminal = False         # True = cannot be pushed onto stack
    cannot_stack_me = False     # True = cannot have other screens pushed on top

    def __init__(self, grub_wiz):
        """
        Constructor serves as initial entry point for screen.
        Called once when screen is first created.
        """
        self.gw = grub_wiz  # Reference to main GrubWiz instance
        self.win = grub_wiz.win

    def draw_screen(self):
        """Draw screen-specific lines (header and body)"""

    def on_pause(self):
        """
        Called when another screen is about to be pushed on top of this one.

        Returns:
            True to allow being paused/covered, False to reject
        """
        return not self.cannot_stack_me

    def on_resume(self):
        """
        Called when this screen becomes the top screen again
        (after a screen that was on top of it was popped).

        Returns:
            True to allow resuming (typically always True)
        """
        return True

    def on_pop(self):
        """
        Called when this screen is being permanently removed from the stack.
        Must always succeed - use for cleanup only.

        Returns:
            Always returns True (cleanup cannot be rejected)
        """
        return True

    def handle_action(self, action_name):
        """
        Dispatch action to screen-specific handler method.
        Looks for method named '{action_name}_action' and calls it if exists.
        Returns True if action was handled, False otherwise.
        """
        method_name = f'{action_name}_ACTION'
        method = getattr(self, method_name, None)
        if method and callable(method):
            method()
            return True
        return False

    def slash_PROMPT(self, current: str):
        """ TBD """
        hint = 'must be a valid python regex'
        regex = None # compiled
        pattern = current

        while True:
            prompt = f'Enter search pattern [{hint}]'
            pattern = self.win.answer(prompt=prompt,
                                  seed=str(pattern), height=1)
            if pattern is None: # aborted
                return '', None

            if not pattern:
                return '', None
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                return regex, pattern
            except Exception as whynot:
                hint = str(whynot)
                continue


class HomeScreen(Screen):
    """HOME screen - parameter editing"""
    # Home screen has no restrictions - can navigate anywhere
    def __init__(self, gw):
        super().__init__(gw)
        self.search = ''
        self.regex = None

    def draw_screen(self):
        """ TBD """
        self.win.set_pick_mode(True)
        self.draw_body()
        self.draw_head()

    def body_param_lines(self, param_name, is_current):
        """ Build a body line for a param """
        gw = self.gw
        tab = self.get_tab()
        marker = ' '
        if not gw.is_active_param(param_name):
            marker = '✘'
        value = gw.param_values[param_name]
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


    @staticmethod
    def left_side_box(lines, indent=3):
        """ draw a box """
        if len(lines) <= 0:
            return []
        rv = []
        chars = ['┃'] + ['│'] * (len(lines)-1)
        if len(chars) >= 2:
            chars[0], chars[-1] = '╭', '╰'
        for idx, line in enumerate(lines):
            rv.append(line[:indent] + chars[idx] + line[indent+1:])
        return rv


    def draw_body(self):
        """ TBD """
        gw = self.gw
        gw.hidden_stats = SimpleNamespace(param=0, warn=0)
        win = self.win # short hand
        picked = win.pick_pos
        found_current = False
        gw.clues = []
        first_visible_section = True

        # Iterate through sections directly, hiding empty ones
        for section_name, params in gw.sections.items():
            # Collect visible params for this section
            visible_params = []
            for param_name in params.keys():
                if param_name not in gw.param_cfg:
                    continue  # Param was filtered out (absent from system)

                # Count inactive params regardless of visibility setting
                if not gw.is_active_param(param_name):
                    gw.hidden_stats.param += 1

                # Determine visibility for rendering
                if not gw.show_hidden_params and not gw.is_active_param(param_name):
                    continue
                if gw.show_hidden_params and self.regex:
                    if self.regex.search(param_name[5:]):
                        visible_params.append(param_name)
                else:
                    visible_params.append(param_name)


            # Skip empty sections when in compact mode (hiding params)
            if not visible_params: # and not gw.show_hidden_params:
                continue

            # Add blank line before sections (except first visible section)
            if not first_visible_section:
                win.add_body(' ')
                gw.clues.append(Clue('nop'))
            first_visible_section = False

            # Add section header
            win.add_body(f'[{section_name}]')
            gw.clues.append(Clue('nop'))

            # Add visible params
            for param_name in visible_params:
                pos = len(gw.clues)
                is_current = bool(picked == pos)
                param_lines = self.body_param_lines(param_name, is_current)

                if pos != picked:
                    line = param_lines[0]
                    if len(param_lines) > 1:
                        line = line[:win.cols-2] + '⯈'
                    win.add_body(line)
                    gw.clues.append(Clue('param', param_name))
                    continue

                found_current = True
                emits = param_lines + gw.drop_down_lines(param_name)

                # Truncate if exceeds view size
                view_size = win.scroll_view_size
                if len(emits) > view_size:
                    hide_cnt = 1 + len(emits) - view_size
                    emits = emits[0:view_size-1]
                    emits.append(f'... beware: {hide_cnt} HIDDEN lines ...')
                if len(emits) > 1:
                    emits = [emits[0]] + self.left_side_box(emits[1:])

                for emit in emits:
                    win.add_body(emit)
                gw.clues.append(Clue('param', param_name, len(emits)))

        return found_current

    def add_common_head1(self, title):
        """ TBD"""
        gw = self.gw
        header = ''
        # Add timestamp when verbose headers enabled (helps verify refresh rate)
        if gw.spins.verbose_header:
            timestamp = time.strftime('%H:%M:%S')
            header = f'{timestamp} '
        header += f'{title} '
        level = gw.spins.guide
        esc = ' ESC:back' if gw.ss.is_curr(REVIEW_ST) else ''
        # more = 'm:less-hdr' if gw.spins.verbose_header else '[m]ore-hdr'
        header += f' [g]uide={level}  [w]rite-grub   {esc} ?:help [q]uit'
        header += f'  𝚫={len(gw.get_diffs())}'
        gw.add_fancy_header(header)
        gw.warn_db.write_if_dirty()

    def add_common_head2(self, left):
        """ TBD"""
        gw = self.gw
        param_name, _, enums, regex, value = gw.get_enums_regex()
        review_screen = gw.ss.is_curr(REVIEW_ST)

        if gw.spins.verbose_header:
            style = gw.spins.fancy_headers
            line = '[R]estoreScreen'
            line += '  [W]arningsScreen' if review_screen else ''
            line += f'  [f]ancy={style}'
            if regex:
                line += '  [E]xpertEdit'
            gw.add_fancy_header(line)

        tab = self.get_tab()
        picked = gw.win.pick_pos
        if 0 <= picked < len(gw.clues):
            clue = gw.clues[picked]
            cat, ident = clue.cat, clue.ident
        else:
            cat, ident = '', ''

        middle =  ''
        if cat == 'param':
            if enums:
                middle += '⮜–⮞'
            if regex:
                middle += ' [e]dit'
            if param_name:
                if gw.is_active_param( param_name):
                    middle += ' x:deact'
            if review_screen and param_name:
                if str(value) != str(gw.prev_values[param_name]):
                    middle += ' [u]ndo'

        if cat == 'warn' and review_screen:
            middle += ' x:allow-warning' if gw.warn_db.is_inhibit(
                        ident) else ' x:inhibit-warning'

        if not review_screen and gw.show_hidden_params:
            middle = f'{middle:<15}' ## so search does not move too much
            middle += f'  /{self.search}'

        gw.add_fancy_header(f'{left:<{tab.lwid}}  {middle}')

    def get_tab(self):
        """ get the tab positions of the print cols """
        return Tab(self.win.cols, self.gw.param_name_wid)

    def draw_head(self):
        """ HOME screen header"""
        gw = self.gw
        self.add_common_head1('EDIT')
        tab = self.get_tab()

        # if any param is hidden on this screen, then show
        header, cnt = '', gw.hidden_stats.param
        if cnt:
            if gw.show_hidden_params:
                header += f's:hide-{cnt}-inact-params'
            else:
                header += f'[s]how-all-params({cnt}-inact)'
        header = f'{header:<{tab.lwid}}'

        self.add_common_head2(header)
        gw.ensure_visible_group()

    def hide_ACTION(self):
        """Handle 'x' key on HOME screen - toggle param activation"""
        gw = self.gw
        name, _, _, _, _ = gw.get_enums_regex()
        if name:
            if gw.is_active_param(name):
                gw.deactivate_param(name)
            else:
                gw.activate_param(name)

    def cycle_next_ACTION(self):
        """Handle cycle next key on HOME/REVIEW screen - advance to next enum value"""
        gw = self.gw
        name, _, enums, _, _ = gw.get_enums_regex()
        if enums:
            value = gw.param_values[name]
            found = gw.find_in(value, enums)
            gw.param_values[name] = found.next_value

    def cycle_prev_ACTION(self):
        """Handle cycle prev key on HOME/REVIEW screen - go to previous enum value"""
        gw = self.gw
        name, _, enums, _, _ = gw.get_enums_regex()
        if enums:
            value = gw.param_values[name]
            found = gw.find_in(value, enums)
            gw.param_values[name] = found.prev_value

    def edit_ACTION(self):
        """Handle 'e' key on HOME/REVIEW screen - edit parameter value"""
        gw = self.gw
        name, _, _, regex, _ = gw.get_enums_regex()
        if regex:
            gw.edit_param(self.win, name, regex)

    def expert_edit_ACTION(self):
        """Handle 'E' key on HOME/REVIEW screen - expert edit parameter"""
        gw = self.gw
        name, _, _, _, _ = gw.get_enums_regex()
        if name:
            gw.expert_edit_param(self.win, name)

    def show_hidden_ACTION(self):
        """Handle 's' key on HOME screen - toggle showing hidden params"""
        self.gw.show_hidden_params = not self.gw.show_hidden_params

    def write_ACTION(self):
        """Handle 'w' key on HOME screen - push to REVIEW screen"""
        gw = self.gw
        if gw.navigate_to(REVIEW_ST):
            gw.must_reviews = None  # reset
            gw.clues = []

    def slash_ACTION(self):
        """ TBD"""
        if self.gw.show_hidden_params:
            self.regex, self.search = self.slash_PROMPT(self.search)

class ReviewScreen(HomeScreen):
    """REVIEW screen - show diffs and warnings"""
    # Review screen can be accessed from HOME screen

    def __init__(self, grub_wiz):
        """Constructor handles initial setup"""
        super().__init__(grub_wiz)
        # Reset cached review data on construction
        self.gw.must_reviews = None
        self.gw.clues = []

    def on_resume(self):
        """Refresh review data when resuming after being covered"""
        # Reset cached review data when resuming
        self.gw.must_reviews = None
        self.gw.clues = []
        return True

    def draw_screen(self):
        """ TBD """
        self.win.set_pick_mode(True)
        self.add_body()
        self.add_head()

    def add_head(self):
        """ Construct the review screen header
            Presumes the body was created and self.clues[]
            is populated.
        """
        gw = self.gw
        self.add_common_head1('REVIEW')

        # if any warn is hidden on this screen, then show
        header, cnt = '', gw.hidden_stats.warn
        if cnt:
            header = 's:hide' if gw.show_hidden_warns else '[s]how'
            header += f' {cnt} ✘-warns'
        header = f'{header:<24}'
        self.add_common_head2(header)
        gw.ensure_visible_group()

    def add_body(self):
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

        gw = self.gw
        reviews = {}
        gw.hidden_stats = SimpleNamespace(param=0, warn=0)
        diffs = gw.get_diffs()
        warns, all_warn_info = gw.wiz_validator.make_warns(gw.param_values)
        gw.warn_db.audit_info(all_warn_info)
        if gw.must_reviews is None:
            gw.must_reviews = set()
        for param_name in list(diffs.keys()):
            gw.must_reviews.add(param_name)
        for param_name, heys in warns.items():
            for hey in heys:
                words = re.findall(r'\b[_A-Z]+\b', hey[1])
                for word in words:
                    other_name = word
                    if f'GRUB_{word}'in gw.param_values:
                        other_name = f'GRUB_{word}'
                    elif word not in gw.param_values:
                        continue
                    gw.must_reviews.add(other_name)
                gw.must_reviews.add(param_name)

        for param_name in gw.param_names:
            if param_name not in gw.must_reviews:
                continue
            if param_name in diffs:
                old_value, new_value = diffs[param_name]
                item = add_review_item(param_name, new_value, old_value)
            else:
                value = gw.param_values[param_name]
                item = add_review_item(param_name, value)
            heys = warns.get(param_name, None)
            if heys:
                item.heys += heys

        gw.clues = []
        picked = self.win.pick_pos

        for param_name, ns in reviews.items():
            clue_idx = len(gw.clues)
            param_pos = pos = len(gw.clues)
#           keys, indent = [], 30
            tab = self.get_tab()
            is_current = bool(pos==picked)
            param_lines = self.body_param_lines(param_name, is_current)
            gw.clues.append(Clue('param', param_name))
            for line in param_lines:
                self.win.add_body(line)
            pos += len(param_lines)

            changed = bool(ns.old_value is not None
                           and str(ns.value) != str(ns.old_value))
            if changed:
                pos += 1
                self.win.add_body(f'{"└──────── was":>{tab.lwid}}  {ns.old_value}')
                gw.clues.append(Clue('nop'))

            for hey in ns.heys:
                warn_key = WarnDB.make_key(param_name, hey[1])
                is_inhibit = gw.warn_db.is_inhibit(warn_key)
                gw.hidden_stats.warn += int(is_inhibit)
                stars = '🟌' * len(hey[0])

                if not is_inhibit or gw.show_hidden_warns:
                    mark = '✘' if is_inhibit else ' '
                    sub_text = f'└─── {mark} {stars:>4}'
                    line = f'{sub_text:>{tab.lwid}}  {hey[1]}'
                    cnt = gw.add_wrapped_body_line(line,
                                        tab.lwid+2, pos==picked)
                    gw.clues.append(Clue('warn', warn_key, cnt))
                    pos += cnt
            gw.clues[clue_idx].group_cnt = pos - param_pos

            if is_current:
                emits = gw.drop_down_lines(param_name)
                if len(emits) > 1:
                    emits = self.left_side_box(emits)
                pos += len(emits)
                for emit in emits:
                    self.win.add_body(emit)

    def hide_ACTION(self):
        """Handle 'x' key on REVIEW screen - toggle warning suppression"""
        gw = self.gw
        pos = self.win.pick_pos
        if gw.clues and 0 <= pos < len(gw.clues):
            clue = gw.clues[pos]
            if clue.cat == 'warn':
                opposite = not gw.warn_db.is_inhibit(clue.ident)
                gw.warn_db.inhibit(clue.ident, opposite)
                gw.warn_db.write_if_dirty()
            elif clue.cat == 'param':
                gw.deactivate_param(clue.ident)

    def undo_ACTION(self):
        """Handle 'u' key on REVIEW screen - undo parameter change"""
        gw = self.gw
        name, _, _, _, _ = gw.get_enums_regex()
        if name:
            prev_value = gw.prev_values[name]
            gw.param_values[name] = prev_value

    def show_hidden_ACTION(self):
        """Handle 's' key on REVIEW screen - toggle showing hidden warnings"""
        self.gw.show_hidden_warns = not self.gw.show_hidden_warns

    def write_ACTION(self):
        """Handle 'w' key on REVIEW screen - update grub"""
        # Note: update_grub is now a critical requirement, so is_crippled only indicates
        # missing grub_cfg (which affects menu entry enumeration, not update capability)
        self.gw.update_grub()

    def slash_ACTION(self):
        """ TBD"""
        return # does nothing here


class RestoreScreen(Screen):
    """RESTORE screen - backup management"""
    # Can be accessed from HOME or REVIEW screens
    come_from_whitelist = [HOME_ST, REVIEW_ST]

    def __init__(self, grub_wiz):
        """Constructor handles initial backup list setup"""
        super().__init__(grub_wiz)
        # Initialize backup list
        self.gw.do_start_up_backup()
        self.gw.refresh_backup_list()
        self.bak_paths = []
        self.baseline_bak = None  # what to compare to

    def on_resume(self):
        """Refresh backup list when resuming"""
        self.gw.refresh_backup_list()
        return True

    def draw_screen(self):
        self.win.set_pick_mode(True)
        self.add_body()
        self.add_head()

    def add_head(self):
        """ TBD """
        gw = self.gw
        pos, base = self.win.pick_pos, '[c]mp [b]aseline'
        if 0 <= pos < len(self.bak_paths):
            if self.bak_paths[pos] == self.baseline_bak:
                base = ''
        header = f'RESTORE [r]estore [d]el [t]ag [v]iew {base}    ESC:back ?:help [q]uit'
        gw.add_fancy_header(header)

    def _ensure_reference(self):
        """ Make sure reference is something valid """
        gw = self.gw
        ref, new_ref = self.baseline_bak, None
        if ref:
            for pair in gw.ordered_backup_pairs:
                if pair[1] == ref:
                    new_ref = ref
                    break
        if not new_ref and gw.ordered_backup_pairs:
            new_ref = gw.ordered_backup_pairs[-1][1]
        self.baseline_bak = new_ref

    def add_body(self):
        """ TBD """
        gw = self.gw
        if not gw.ordered_backup_pairs:
            return
        self._ensure_reference()
        self.bak_paths = []
        for pair in gw.ordered_backup_pairs:
            checksum, bak_path = pair[0], pair[1]
            prefix = '●' if checksum == gw.grub_checksum else ' '
            ref = 'CMP' if self.baseline_bak == bak_path else '   '
            self.bak_paths.append(bak_path)
            self.win.add_body(f'{prefix} {ref} {bak_path.name}')

    def baseline_ACTION(self):
        """Handle 'b' key on RESTORE screen - baseline for CMP"""
        gw = self.gw
        pos = self.win.pick_pos
        if 0 <= pos < len(gw.ordered_backup_pairs):
            bak_path = gw.ordered_backup_pairs[pos][1]
            self.baseline_bak = bak_path

    def compare_ACTION(self):
        """Handle 'c' key on RESTORE screen - set in compare mode"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(self.bak_paths):
            bak_path = self.bak_paths[idx]
            ref_path = self.baseline_bak
            if bak_path and ref_path and bak_path != ref_path:
                if gw.navigate_to(COMPARE_ST):
                    compare_screen = gw.screens[COMPARE_ST]
                    compare_screen.bak1 = bak_path
                    compare_screen.bak2 = ref_path

    def restore_ACTION(self):
        """Handle 'r' key on RESTORE screen - restore selected backup"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            key = gw.ordered_backup_pairs[idx][0]
            gw.backup_mgr.restore_backup(gw.backups[key])
            while gw.navigate_back():
                pass
            gw.reinit_gw()
            gw.ss = ScreenStack(gw.win, gw.spins, SCREENS, gw.screens)
            gw.do_start_up_backup()

    def delete_ACTION(self):
        """Handle 'd' key on RESTORE screen - delete selected backup"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            doomed = gw.ordered_backup_pairs[idx][1]
            if gw.really_wanna(f'remove {doomed!r}'):
                try:
                    os.unlink(doomed)
                except Exception as exce:
                    self.win.alert(
                        message=f'ERR: unlink({doomed}) [{exce}]')
                gw.refresh_backup_list()

    def tag_ACTION(self):
        """Handle 't' key on RESTORE screen - tag/retag selected backup"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            chosen = gw.ordered_backup_pairs[idx][1]
            tag = gw.request_backup_tag(f'Enter tag for {chosen.name}',
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
                gw.refresh_backup_list()

    def view_ACTION(self):
        """Handle 'v' key on RESTORE screen - view selected backup"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            try:
                gw.bak_path = gw.ordered_backup_pairs[idx][1]
                gw.bak_lines = gw.bak_path.read_text().splitlines()
                assert isinstance(gw.bak_lines, list)
                gw.navigate_to(VIEW_ST)
            except Exception as ex:
                self.win.alert(f'ERR: cannot slurp {gw.bak_path} [{ex}]')

class CompareScreen(Screen):
    """  Show the comparison of two backup files """
    come_from_whitelist = [RESTORE_ST]

    """COMPARE screen - compared two backups"""
    def __init__(self, grub_wiz):
        """Constructor validates backup data is loaded"""
        super().__init__(grub_wiz)
        self.bak1 = None # will be a Path
        self.bak2 = None # will be a Path
        self.cnt1, self.cnt2 = None, None
        self.results = None

    def on_pop(self):
        """Clean up backup view data when screen is removed"""
        self.results = None
        return True

    def draw_screen(self):
        """ TBD """
        self.win.set_pick_mode(False)
        self.add_body()
        self.add_head()

    def add_body(self):
        """ TBD """
        def get_val(param, data):
            if param not in data:
                return GrubFile.ABSENT, None
            return data[param].value, data[param].line_num

        gw = self.gw

        if self.results is None:
            self.results, lines = [], []
            grub1 = GrubFile(gw.param_cfg, self.bak1)
            grub2 = GrubFile(gw.param_cfg, self.bak2)
            grub1.param_data.update(grub1.extra_params)
            grub2.param_data.update(grub2.extra_params)
            data1 = grub1.param_data
            data2 = grub2.param_data
            params = sorted(list(set(data1.keys()) | set(data2.keys())))
            self.cnt1 = len(grub1.lines)
            self.cnt2 = len(grub2.lines)

            for param in params:
                value1, num1 = get_val(param, data1)
                value2, num2 = get_val(param, data2)
                if value1 == value2:
                    continue
                line1 = '' if num1 is None else grub1.lines[num1].strip()
                line2 = '' if num2 is None else grub2.lines[num2].strip()

                # Add blank separator
                lines.append('')

                # Add line1 with wrapping
                prefix1 = '< '
                content1 = line1
                lines.append(prefix1 + content1)

                # Add line2 with wrapping
                prefix2 = '> '
                content2 = line2
                lines.append(prefix2 + content2)

            self.results = lines

        # Display with wrapping
        wid = self.win.cols - 3  # Account for '< ' or '> ' prefix (2 chars) + margin
        for line in self.results:
            if not line:
                self.win.add_body('')
                continue

            # Check if line starts with a prefix
            if line.startswith('< ') or line.startswith('> '):
                prefix = line[:2]
                content = line[2:]

                # First line with prefix
                if len(line) <= self.win.cols - 1:
                    self.win.add_body(line)
                else:
                    # Need to wrap
                    self.win.add_body(prefix + content[:wid])
                    content = content[wid:]

                    # Continuation lines with indentation
                    while content:
                        indent = '  '  # 2 spaces to align with content after prefix
                        chunk_size = self.win.cols - len(indent) - 1
                        self.win.add_body(indent + content[:chunk_size])
                        content = content[chunk_size:]
            else:
                self.win.add_body(line)

    def add_head(self):
        """ TBD """
        win = self.win
        win.add_header('COMPARE   ESC:back')
        win.add_header(f'< {self.bak1.name} [#lines={self.cnt1}]')
        win.add_header(f'> {self.bak2.name} [#lines={self.cnt2}]')


class ViewScreen(Screen):
    """VIEW screen - view backup contents"""
    # Can only be accessed from RESTORE screen
    come_from_whitelist = [RESTORE_ST]

    def on_pop(self):
        """Clean up backup view data when screen is removed"""
        self.gw.bak_lines = None
        self.gw.bak_path = None
        return True

    def draw_screen(self):
        """ TBD """
        self.win.set_pick_mode(False)
        self.add_body()
        self.add_head()

    def add_head(self):
        """ TBD """
        gw = self.gw
        header = f'VIEW  {gw.bak_path.name!r}  ESC:back ?:help [q]uit'
        gw.add_fancy_header(header)

    def add_body(self):
        """ TBD """
        gw = self.gw
        wid = self.win.cols - 7 # 4 num + SP before + 2SP after
        for idx, line in enumerate(gw.bak_lines):
            self.win.add_body(f'{idx:>4}', attr=cs.A_BOLD)
            self.win.add_body(f'  {line[:wid]}', resume=True)
            line = line[wid:]
            while line:
                self.win.add_body(f'{' ':>6}{line[:wid]}')
                line = line[wid:]

class WarnScreen(Screen):
    """WARNINGS Screen"""
    # Can only be accessed from REVIEW screen
    come_from_whitelist = [HOME_ST, REVIEW_ST]

    def __init__(self, grub_wiz):
        """Constructor initializes search state"""
        super().__init__(grub_wiz)
        self.keys = []  # key ('param: text') in each position
        self.search = ''
        self.regex = None  # compiled

    def on_pop(self):
        """Save any changes when screen is removed"""
        # Save any inhibit changes before leaving
        self.gw.warn_db.write_if_dirty()
        return True

    def draw_screen(self):
        """ TBD """
        self.win.set_pick_mode(True)
        self.draw_body()
        self.draw_head()

    def draw_head(self):
        """ TBD """
        gw = self.gw
        db = gw.warn_db
        pos = self.win.pick_pos
        inh = False
        if 0 <= pos < len(self.keys):
            key = self.keys[pos]
            inh = db.is_inhibit(key)
        line = 'WARNINGS-CONFIG'
        line += f"   [x]:{'allow-warning' if inh else 'inhibit-warning'}"
        line += f'   /{self.search}'
        line += '   ESC=back [q]uit'
        gw.add_fancy_header(line)

    def draw_body(self):
        """ TBD """
        gw = self.gw
        db = gw.warn_db
        all_info = db.all_info
        keys = sorted(all_info.keys())
        prev_param = None

        for key in keys:
            sev = all_info[key]
            stars = '🟍' * sev

            inh = 'X' if db.is_inhibit(key) else ' '

            # Split key into param_name and message
            if ': ' in key:
                param_name, message = key.split(': ', 1)
                # Strip GRUB_ prefix
                display_param = param_name.replace('GRUB_', '', 1)

                # Create full line for searching (always has param name)
                full_line = f'[{inh}] {stars:>4} {display_param}: {message}'

                # Check if same param as previous DISPLAYED line
                if param_name == prev_param:
                    # Omit param name, just show message with proper spacing
                    line = f'[{inh}] {stars:>4} {" " * (len(display_param) + 2)}{message}'
                else:
                    # Show full line with param name
                    line = full_line
            else:
                # No colon in key, show as-is
                full_line = line = f'[{inh}] {stars:>4} {key}'
                param_name = None

            # Search against full_line, but display line
            if not self.regex or self.regex.search(full_line):
                self.win.add_body(line)
                self.keys.append(key)
                # Only update prev_param for lines that are actually displayed
                prev_param = param_name

    def hide_ACTION(self):
        """ TBD """
        gw = self.gw
        pos = self.win.pick_pos
        if self.keys and 0 <= pos < len(self.keys):
            key = self.keys[pos]
            opposite = not gw.warn_db.is_inhibit(key)
            gw.warn_db.inhibit(key, opposite)
            gw.warn_db.write_if_dirty()

    def slash_ACTION(self):
        """ TBD """
        self.regex, self.search = self.slash_PROMPT(self.search)

class HelpScreen(Screen):
    """HELP screen"""
    def draw_screen(self):
        """ TBD """
        gw, win = self.gw, self.win
        self.win.set_pick_mode(False)
        gw.spinner.show_help_nav_keys(win)
        gw.spinner.show_help_body(win)


class GrubWiz:
    """ TBD """
    singleton = None

    # parameters to give more answer space to
    long_params = ('GRUB_CMDLINE_LINUX GRUB_CMDLINE_LINUX_DEFAULT'
            ' GRUB_CMDLINE_XEN_DEFAULT GRUB_BADRAM GRUB_PRELOAD_MODULES'
            ' GRUB_SERIAL_COMMAND GRUB_GFXMODE GRUB_THEME GRUB_BACKGROUND'
            ' GRUB_TERMINAL_INPUT / GRUB_TERMINAL_OUTPUT').split()

    def __init__(self, cli_opts=None):
        GrubWiz.singleton = self
        self.cli_opts = cli_opts
        self.win = None # place 1st
        self.canned_config = CannedConfig()
        self.distro_vars = DistroVars(self.canned_config.data)
        self.spinner = None
        self.spins = None
        self.sections = None
        self.param_cfg = None
        self.hidden_stats = None
        self.prev_pos = None
        self.defined_param_names = None # all of them
        self.param_names = None
        self.param_values = None
        self.saved_active_param_values = None # for deactivate/activate scenario
        self.param_defaults = None
        self.prev_values = None
        self.param_name_wid = 0
        self.menu_entries = None
        self.backup_mgr = BackupMgr()
        self.warn_db = None
        self.grub_writer = GrubWriter(distro_vars=self.distro_vars)
        self.param_discovery = ParamDiscovery.get_singleton()
        self.wiz_validator = None
        self.backups = None
        self.ordered_backup_pairs = None
        self.must_reviews = None
        self.clues = []
        self.next_prompt_seconds = [3.0]
        self.ss = None
        self.is_other_os = None # don't know yet
        self.show_hidden_params = False
        self.show_hidden_warns = False
        self.grub_checksum = ''
        self.bak_lines = None # the currently viewed .bak file
        self.bak_path = None
        self.screens = []
        self.reinit_gw()

    def reinit_gw(self):
        """ Call to initialize or re-initialize with new /etc/default/grub """
        self.param_cfg = {}
        self.param_values, self.prev_values = {}, {}
        self.saved_active_param_values = {}
        self.param_defaults = {}
        self.must_reviews = None
        self.ss = None
        self.sections = self.canned_config.data
        section_names = list(self.sections.keys())
        for section_name in section_names:
            if section_name.startswith('_'):
                del self.sections[section_name]

        names = []
        for params in self.sections.values():
            for name in params.keys():
                names.append(name)
        absent_param_names = set(self.param_discovery.get_absent(names))
        self.defined_param_names = names

        # Build param_cfg, excluding absent params
        for params in self.sections.values():
            for param_name, cfg in params.items():
                if param_name not in absent_param_names:
                    self.param_cfg[param_name] = cfg
                    self.param_defaults[param_name] = cfg['default']
        if self.wiz_validator is None:
            self.wiz_validator = WizValidator(self.param_cfg)

        self.grub_file = GrubFile(supported_params=self.param_cfg)
        self.grub_file.read_file()
        if self.grub_file.extra_params:
            section_name = 'Unvalidated Params'
            extras = {}
            for extra, cfg in self.grub_file.extra_params.items():
                extras[extra] = cfg
                self.param_cfg[extra] = cfg
                self.param_defaults[extra] = cfg['default']
            self.sections[section_name] = extras
        self.param_names = list(self.param_cfg.keys())
        self.prev_pos = -1024  # to detect direction

        name_wid = 0
        for param_name in self.param_names:
            name_wid = max(name_wid, len(param_name))
            value = self.grub_file.param_data[param_name].value
            self.param_values[param_name] = value
        self.param_name_wid = name_wid - len('GRUB_')
        self.prev_values.update(self.param_values)
        self.menu_entries = get_top_level_grub_entries(
                                self.distro_vars.grub_cfg)
        try:
            self.param_cfg['GRUB_DEFAULT']['enums'].update(self.menu_entries)
        except Exception:
            pass
        self.warn_db = WarnDB(param_cfg=self.param_cfg)

        # Run startup audit to clean orphans and populate warning info
        warns, all_warn_info = self.wiz_validator.make_warns(self.param_values)
        self.warn_db.audit_info(all_warn_info)
        self.warn_db.write_if_dirty()  # Persist any cleanup from orphaned warnings

        self.refresh_backup_list()

    def setup_win(self):
        """TBD """
        spinner = self.spinner = OptionSpinner()
        self.spins = self.spinner.default_obj
        spinner.add_key('escape', 'ESC - back to prev screen', category="action", keys=[27,])
        spinner.add_key('help_mode', '? - enter help screen', category='action')
        spinner.add_key('verbose_header', 'm - more keys shown', vals=[False, True])
        spinner.add_key('quit', 'q,ctl-c - quit the app', category='action', keys={0x3, ord('q')})

        spinner.add_key('cycle_next', '=>,SP - next cycle value',
                        category='action', keys=[cs.KEY_RIGHT, ord(' ')])
        spinner.add_key('cycle_prev', '<=,BS - prev cycle value',
                        category='action', keys=[ord('C'), cs.KEY_LEFT, cs.KEY_BACKSPACE])
        spinner.add_key('edit', 'e - edit value', category='action')
        spinner.add_key('expert_edit', 'E - expert edit (minimal validation)', category='action',
                            keys=[ord('E')])
        spinner.add_key('undo', 'u - revert value', category='action')

        spinner.add_key('hide', 'x - inh/allow warnings', category='action')
        spinner.add_key('show_hidden', 's - show/hide inactive params', category='action')
        spinner.add_key('write', 'w - write params and run "grub-update"', category='action')

        spinner.add_key('guide', 'g - guidance level', vals=['Off', 'Enums', "Full"])
        spinner.add_key('fancy_headers', 'f - cycle fancy headers (Off/Underline/Reverse)',
                        vals=['Underline', 'Reverse', 'Off'])


        spinner.add_key('enter_restore', 'R - enter restore screen', category='action')
        spinner.add_key('enter_warnings', 'W - enter WARNINGs screen', category='action')

        spinner.add_key('restore', 'r - restore selected backup [in restore screen]', category='action')
        spinner.add_key('delete', 'd - delete selected backup [in restore screen]', category='action')
        spinner.add_key('tag', 't - tag/retag a backup file [in restore screen]', category='action')
        spinner.add_key('view', 'v - view a backup file [in restore screen]', category='action')
        spinner.add_key('baseline', 'b - set CMP baseline [in restore screen]', category='action')
        spinner.add_key('compare', 'c - compare with baseline [in restore screen]', category='action')

        spinner.add_key('slash', '/ - filter pattern [in WARNINGS screen]', category='action')



        win_opts = ConsoleWindowOpts()
        win_opts.head_line = True
        win_opts.keys = spinner.keys
        win_opts.ctrl_c_terminates = False
        win_opts.return_if_pos_change = True
        win_opts.single_cell_scroll_indicator = True
        win_opts.dialog_abort = 'ESC'
        win_opts.answer_show_redraws = self.cli_opts.answer_timeout_debug
        self.win = ConsoleWindow(win_opts)

        # Initialize screen objects first (before ScreenStack)
        self.screens = {
            HOME_ST: HomeScreen(self),
            REVIEW_ST: ReviewScreen(self),
            RESTORE_ST: RestoreScreen(self),
            VIEW_ST: ViewScreen(self),
            COMPARE_ST: CompareScreen(self),
            WARN_ST: WarnScreen(self),
            HELP_ST: HelpScreen(self),
        }

        # Create ScreenStack with screen objects for hook invocation
        self.ss = ScreenStack(self.win, self.spins, SCREENS, self.screens)

    def get_enums_regex(self):
        """ TBD"""
        enums, regex, param_name, value = None, None, None, None
        pos = self.win.pick_pos
        if self.ss.is_curr((REVIEW_ST, HOME_ST)):
            if self.clues and 0 <= pos < len(self.clues):
                clue = self.clues[pos]
                if clue.cat == 'param':
                    param_name = clue.ident
        if not param_name:
            return '', {}, {}, '', None

        cfg = self.param_cfg[param_name]
        enums = cfg.get('enums', None)
        regex = cfg.get('edit_re', None)
        value = self.param_values.get(param_name, None)
        return param_name, cfg, enums, regex, value


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
            return self.warn_db.is_inhibit(warn_key)
        return False

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
            if first_word_match and re.match(r'^[\w-]+$', first_word_match):
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
                    match = re.match(r'/(\S+)', line[i:])
                    if match:
                        # Found a search pattern
                        if current_text:
                            result_sections.append((current_text, None))
                            current_text = ""

                        full_pattern = match.group(0)  # includes the /
                        result_sections.append((full_pattern, cs.A_BOLD|cs.A_REVERSE))
                        i += len(full_pattern)
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




    def ensure_visible_group(self):
        """ TBD """
        win = self.win
        pos = win.pick_pos
        group_cnt = 1
        if 0 <= pos < len(self.clues):
            group_cnt = self.clues[pos].group_cnt
        over = pos - win.scroll_pos + group_cnt - win.scroll_view_size
        if over >= 0:
            old_scroll_pos = win.scroll_pos
            win.scroll_pos += over + 1 # scroll back by number of out-of-view lines
            # Only reset refresh timer if we actually scrolled
            if win.scroll_pos != old_scroll_pos:
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

    def is_active_param(self, param_name):
        """ is the param neither commented out nor absent? """
        value = self.param_values.get(param_name, None)
        if value is not None:
            if value not in (GrubFile.COMMENT, GrubFile.ABSENT):
                return True
            return False
        return True # or False is better?

    def activate_param(self, param_name):
        """ TBD """
        value = self.param_values.get(param_name, None)
        if value in (GrubFile.COMMENT, GrubFile.ABSENT):
            value = self.saved_active_param_values.get(param_name, None)
            if value is None:
                value = self.param_cfg[param_name].get('default', '')
            self.param_values[param_name] = value
            return True
        return False # or False is better?

    def deactivate_param(self, param_name):
        """ make a param inactive by commenting it out
            - save the value in case activated
        """
        value = self.param_values.get(param_name, None)
        if value not in (GrubFile.COMMENT, GrubFile.ABSENT):
            self.saved_active_param_values[param_name] = value
            if self.prev_values[param_name] == GrubFile.ABSENT:
                self.param_values[param_name] = GrubFile.ABSENT
            else:
                self.param_values[param_name] = GrubFile.COMMENT
            return True
        return False




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
                if line.strip() == '%ENUMS%':
                    wraps += gen_enum_lines()
                else:
                    wrapped = textwrap.fill(line, width=wid-1, subsequent_indent=' '*5)
                    wraps += wrapped.split('\n')
        elif self.spins.guide == 'Enums':
            wraps += gen_enum_lines()
        emits = [f'{lead}{wrap}' for wrap in wraps if wrap]
        return emits

    @staticmethod
    def _answer_height(param_name):
        return 5 if param_name in GrubWiz.long_params else 1

    def edit_param(self, win, name, regex):
        """ Prompt user for answer until gets it right"""

        # Check if this param uses EXPERT_EDIT mode
        if regex in (EXPERT_EDIT, EXPERT_EDIT[0]):
            self.expert_edit_param(win, name)
            return

        value = self.param_values[name]
        valid = False
        hint = ''

        # Get human description from config
        cfg = self.param_cfg.get(name, {})
        human_desc = cfg.get('edit_re_human', '')

        if human_desc:
            hint = human_desc
        elif regex:
            # Fallback to regex pattern if no human description
            if hasattr(regex, 'pattern'):
                pure_regex = regex.pattern
            else:
                pure_regex = str(regex).encode().decode('unicode_escape')
            hint = f'pat={pure_regex}'

        while not valid:
            prompt = f'Edit {name} [{hint}]'
            value = win.answer(prompt=prompt, seed=str(value),
                               height=self._answer_height(name))
            if value is None: # aborted
                return
            valid = True # until proven otherwise

            # First check regex if provided
            if regex:
                # Handle both compiled patterns and string patterns
                if hasattr(regex, 'match'):
                    match_result = regex.match(str(value))
                else:
                    match_result = re.match(regex, str(value))

                if not match_result:
                    valid = False
                    # Use human description in error message
                    if human_desc:
                        hint = f'must be: {human_desc}'
                    else:
                        if hasattr(regex, 'pattern'):
                            pure_regex = regex.pattern
                        else:
                            pure_regex = str(regex).encode().decode('unicode_escape')
                        hint = f'must match: {pure_regex}'
                    win.flash('Invalid input - please try again', duration=1.5)
                    continue

            # Also validate as shell token for safety (regexes can be permissive)
            if value and not self._is_valid_shell_token(value):
                valid = False
                hint = 'must be valid shell token (check quoting)'
                win.flash('Invalid shell token - check quoting', duration=1.5)

        self.param_values[name] = value

    def expert_edit_param(self, win, name):
        """ Expert mode edit with minimal validation - escape hatch for grub-wiz errors """
        value = self.param_values[name]
        valid = False
        hint = 'expert mode: minimal checks'

        while not valid:
            prompt = f'Edit {name} [EXPERT MODE: {hint}]'
            value = win.answer(prompt=prompt, seed=str(value),
                               height=self._answer_height(name))
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
            return "'" not in value[1:-1]  # Disallow single quotes inside

        # Double-quoted: check for balanced quotes
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            # Basic check: allow escaped quotes, but no bare unescaped quotes inside
            inner = value[1:-1]
            # Replace escaped quotes, then check for any remaining unescaped quotes
            check = inner.replace('\\"', '')
            return '"' not in check

        # Command substitution: $(...)
        if value.startswith('$(') and value.endswith(')'):
            # Basic check: has opening and closing parens
            # We don't deeply validate the command itself
            return True

        # Command substitution: `...` (backtick style)
        if value.startswith('`') and value.endswith('`') and len(value) >= 2:
            # Allow backtick command substitution
            # The shell will handle the validation
            return True

        # Unquoted word: only allow alphanumeric, underscore, hyphen, period
        # Anything fancier (paths, spaces, special chars) must be quoted
        return bool(re.match(r'^[\w.-]+$', value))


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
            answer = self.win.answer(seed=seed,
                        prompt=f"{prompt} [{hint}]]", height=1)
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
            self.refresh_backup_list()

        elif checksum not in self.backups:
            answer = self.request_backup_tag(f'Enter a tag to back up {GRUB_DEFAULT_PATH}')
            if answer:
                self.backup_mgr.create_backup(answer)
                self.refresh_backup_list()

        self.grub_checksum = checksum # checksum of loaded grub

    def really_wanna(self, act):
        """ TBD """
        answer = self.win.answer(seed='y',
                         prompt=f"Enter 'yes' to {act}", height=1)
        if answer is None:
            return False
        answer = answer.strip().lower()
        return answer.startswith('y')

    def update_grub(self):
        """ TBD """
        if not self.really_wanna('commit changes and update GRUB'):
            return

        diffs = self.get_diffs()
        for param_name, pair in diffs.items():
            self.grub_file.param_data[param_name].new_value = pair[1]

        self.win.stop_curses()
        time.sleep(.75)
        print("\033[2J\033[H") # 'clear'
        print('\n\n===== Leaving grub-wiz screens to update GRUB ====> ')
        # print('Check for correctness...')
        # print('-'*60)
        # print(contents)
        # print('-'*60)
        config_dir = UserConfigDir.get_singleton().config_dir
        candidate_path = config_dir / 'etc_default_grub_candidate'

        ok = True
        write_rv = self.grub_file.write_file(candidate_path)
        if not write_rv: # failure
            ok = False

        if ok:
            commit_rv, err = self.grub_writer.commit_validated_grub_config(
                candidate_path)
            if not commit_rv:
                ok = False
                print(err)

        if ok:
            install_rv = self.grub_writer.run_grub_update()
            if not install_rv[0]:
                print(install_rv[1])
                ok = False
        if ok:
            os.system('\n\necho "OK ... /etc/default/grub newly written/updated"')
        else:
            os.system('\n\necho "FAIL ... /etc/default/grub NOT written/updated"')
        print('\n\nChoose:')
        if ok:
            print('  [r]eboot now')
            print('  [p]oweroff')
        print('  [q]uit')
        print('  ENTER to return to grub-wiz screen')

        choice = input('\n> ').strip().lower()

        if choice == 'r':
            print('\nRebooting...')
            os.system('reboot')
            sys.exit(0)  # Won't reach here, but just in case
        elif choice == 'p':
            print('\nPowering off...')
            os.system('poweroff')
            sys.exit(0)  # Won't reach here, but just in case
        elif choice == 'q':
            print('\nQuitting grub-wiz...')
            sys.exit(0)  # Won't reach here, but just in case
        # Otherwise continue to grub-wiz
        else:
            self.win.start_curses()
            if ok:
                self.reinit_gw()
                self.ss = ScreenStack(self.win, self.spins, SCREENS, self.screens)
                self.do_start_up_backup()

    def find_in(self, value, enums=None, cfg=None):
        """ Find the value in the list of choices using only
        string comparisons (because representation uncertain)

        Returns ns (.idx, .next_idx, .next_value, .prev_idx, .prev_value)
        """
        def normalize_value(val):
            """Remove outer quotes for comparison"""
            s = str(val)
            # Strip outer quotes (both single and double)
            if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
                return s[1:-1]
            return s

        choices = None
        if cfg:
            enums = cfg.get(enums, [])
        if enums:
            choices = list(enums.keys())
        assert choices

        # Normalize the value for comparison (strip quotes)
        norm_value = normalize_value(value)

        idx = -1 # default to before first
        for ii, choice in enumerate(choices):
            if norm_value == normalize_value(choice):
                idx = ii
                break
        next_idx = (idx+1) % len(choices)
        next_value = choices[next_idx] # choose next
        prev_idx = (idx+len(choices)-1) % len(choices)
        prev_value = choices[prev_idx] # choose next
        return SimpleNamespace(idx=idx, choices=choices,
                       next_idx=next_idx, next_value=next_value,
                       prev_idx=prev_idx, prev_value=prev_value)

    def navigate_to(self, screen_num):
        """
        Navigate to a screen with validation hooks.

        Args:
            screen_num: Screen number to navigate to

        Returns:
            True if navigation succeeded, False if blocked
        """
        result = self.ss.push(screen_num, self.prev_pos)
        if result is not None:
            self.prev_pos = result
            return True
        return False

    def navigate_back(self):
        """
        Navigate back to previous screen with validation hooks.

        Returns:
            True if navigation succeeded, False if blocked or no stack
        """
        result = self.ss.pop()
        if result is not None:
            self.prev_pos = result
            # Reset cached data when going back
            self.must_reviews = None
            self.bak_lines, self.bak_path = None, None
            return True
        return False

    def handle_escape(self):
        """
        Generic escape handler with context awareness.
        Returns:
            True if escape was handled, False otherwise
        """
        if self.ss.stack:
            return self.navigate_back()
        return False

    def main_loop(self):
        """ TBD """
        self.setup_win()
        self.do_start_up_backup()
        win, spins = self.win, self.spins # shorthand
        self.next_prompt_seconds = [0.1, 0.1]

        while True:

            screen_num = self.ss.curr.num
            self.screens[screen_num].draw_screen()

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
                        self.navigate_back()
                    else:
                        break

                # Handle escape with new generic handler
                if self.ss.act_in('escape'):
                    self.handle_escape()

                # Handle help mode navigation
                if self.ss.act_in('help_mode'):
                    self.navigate_to(HELP_ST)

                # Actions delegated to screen classes
                screen_actions = [
                    'cycle_next', 'cycle_prev', 'undo', 'show_hidden', 'edit',
                    'expert_edit', 'hide', 'write', 'restore', 'delete', 'tag',
                    'view', 'slash', 'baseline', 'compare',
                ]
                current_screen = self.screens[self.ss.curr.num]
                for action in screen_actions:
                    if self.ss.act_in(action):
                        current_screen.handle_action(action)

                # Handle navigation to restore screen
                if self.ss.act_in('enter_restore', (HOME_ST, REVIEW_ST)):
                    self.navigate_to(RESTORE_ST)

                # Handle navigation to warnings screen
                if self.ss.act_in('enter_warnings'):
                    self.navigate_to(WARN_ST)

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
    parser.add_argument('--validate-custom-config', action='store_true',
                        help='test load ~/.config/grub-wiz/custom_config.yaml')
    parser.add_argument('--validator-demo', action='store_true',
                        help='for test only: run validator demo')
    parser.add_argument('--answer-timeout-debug', action='store_true',
                        help='for test only: enables screen redraw indicator')
    opts = parser.parse_args()

    wiz = GrubWiz(cli_opts=opts)
    if opts.validator_demo:
        wiz.wiz_validator.demo(wiz.param_defaults)
        sys.exit(0)

    if opts.validate_custom_config:
        print(f'grub-wiz: using {wiz.canned_config.using_path}')
        if 'custom' not in str(wiz.canned_config.using_path):
            print("NOTE: custom config NOT being used")
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
                            wiz.warn_db.yaml_path):
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
