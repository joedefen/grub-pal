#!/usr/bin/env python3
r"""
    grub-wiz: the help grub file editor assistant

1. WARNING Screen
    Exhaustive view of ALL validation checks (not just triggered ones)
    Launched from REVIEW screen
    Flat list: param_name, severity (1-4 stars), warning_text, state (triggered/inhibited)
    Filterable and sortable
    X-key toggle to inhibit/allow individual warnings
    Already done: WarnDB refactoring, all_warn_info with severity
2. [m]ore Key - Extended Options Header
    Toggle visibility of third header line on REVIEW, EDIT, RESTORE screens
    Shows additional keys: warning-db, restore, expert-edit, header-style
    Keys work whether visible or not (pure progressive disclosure)
    Pushes existing second header line down when active
3. Backup Comparison (RESTORE screen)
    REF/BASE column - exclusive designation for one backup file
    Key to set/unset REF on selected backup
    [c]ompare key - shows param-by-param diff between selected backup and REF
    Only displays changed params (value changes or comment status changes)
    Format: PARAM: old_value → new_value

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
from .CannedConfig import CannedConfig, EXPERT_EDIT
from .GrubFile import GrubFile
from .GrubCfgParser import get_top_level_grub_entries
from .BackupMgr import BackupMgr, GRUB_DEFAULT_PATH
from .WarnDB import WarnDB
from .GrubWriter import GrubWriter
from .WizValidator import WizValidator
from .ParamDiscovery import ParamDiscovery

HOME_ST, REVIEW_ST, RESTORE_ST, VIEW_ST, WARN_ST, HELP_ST  = 0, 1, 2, 3, 4, 5
SCREENS = ('HOME', 'REVIEW', 'RESTORE', 'VIEW', 'WARN', 'HELP') # screen names

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

        # Call leave_screen hook on current screen
        if not force and self.curr and self.screen_objects:
            current_screen_obj = self.screen_objects.get(from_screen_num)
            if current_screen_obj:
                if not current_screen_obj.leave_screen(screen):
                    # Current screen blocked the navigation
                    return None

        # Call enter_screen hook on new screen
        if not force and self.screen_objects:
            new_screen_obj = self.screen_objects.get(screen)
            if new_screen_obj:
                if not new_screen_obj.enter_screen(from_screen_num):
                    # New screen blocked the entry
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
        Pop the top screen from the stack with validation.

        Args:
            force: Skip validation hooks if True

        Returns:
            Previous position if successful, None if stack is empty or blocked
        """
        if not self.stack:
            return None

        to_screen_num = self.stack[-1].num
        from_screen_num = self.curr.num if self.curr else None

        # Call leave_screen hook on current screen
        if not force and self.curr and self.screen_objects:
            current_screen_obj = self.screen_objects.get(from_screen_num)
            if current_screen_obj:
                if not current_screen_obj.leave_screen(to_screen_num):
                    # Current screen blocked the navigation
                    return None

        # Call enter_screen hook on the screen we're returning to
        if not force and self.screen_objects:
            prev_screen_obj = self.screen_objects.get(to_screen_num)
            if prev_screen_obj:
                if not prev_screen_obj.enter_screen(from_screen_num):
                    # Previous screen blocked the re-entry
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
    def __init__(self, grub_wiz):
        self.gw = grub_wiz  # Reference to main GrubWiz instance
        self.win = grub_wiz.win

    def draw_screen(self):
        """Draw screen-specific lines (header and body)"""

    def enter_screen(self, from_screen):
        """
        Hook called when entering this screen from another screen.

        Args:
            from_screen: Screen number we're coming from (or None if initial screen)

        Returns:
            True to allow entry, False to block entry
        """
        return True

    def leave_screen(self, to_screen):
        """
        Hook called when leaving this screen to go to another screen.

        Args:
            to_screen: Screen number we're going to (or None if exiting app)

        Returns:
            True to allow leaving, False to block leaving
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


class HomeScreen(Screen):
    """HOME screen - parameter editing"""
    def leave_screen(self, to_screen):
        """
        Hook called when leaving home screen.
        Can add validation here if needed (e.g., warn about unsaved changes).
        """
        # For now, always allow leaving
        # Future: could check for unsaved changes and prompt user
        return True

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
        if gw.ss.is_curr(HOME_ST) and not gw.is_active_param(param_name):
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
                if gw.show_hidden_params or gw.is_active_param(param_name):
                    visible_params.append(param_name)


            # Skip empty sections when in compact mode (hiding params)
            if not visible_params and not gw.show_hidden_params:
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

                for emit in emits:
                    win.add_body(emit)
                gw.clues.append(Clue('param', param_name, len(emits)))

        return found_current

    def add_common_head1(self, title):
        """ TBD"""
        gw = self.gw
        header = f'{title} '
        level = gw.spins.guide
        esc = ' ESC:back' if gw.ss.is_curr(REVIEW_ST) else ''
        header += f' [g]uide={level} [w]rite [R]estore{esc} ?:help [q]uit'
        header += f'  𝚫={len(gw.get_diffs())}'
        gw.add_fancy_header(header)
        gw.warn_db.write_if_dirty()

    def add_common_head2(self, left):
        """ TBD"""
        gw = self.gw
        tab = self.get_tab()
        review_screen = gw.ss.is_curr(REVIEW_ST)
        picked = gw.win.pick_pos
        if 0 <= picked < len(gw.clues):
            clue = gw.clues[picked]
            cat, ident = clue.cat, clue.ident
        else:
            cat, ident = '', ''

        middle =  ''
        if cat == 'param':
            param_name, _, enums, regex, value = gw.get_enums_regex()
            if enums:
                middle += '⮜–⮞'
            if regex:
                middle += ' [e]dit'
            if not review_screen and param_name:
                middle += (' x:comment-out' if gw.is_active_param(
                            param_name) else ' x:uncomment' if value == GrubFile.COMMENT
                            else ' x:create')
            if review_screen and param_name:
                if str(value) != str(gw.prev_values[param_name]):
                    middle += ' [u]ndo'

        if cat == 'warn' and review_screen:
            middle += ' x:allow' if gw.warn_db.is_inhibit(
                        ident) else ' x:inh'

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
            header = 's:hide' if gw.show_hidden_params else '[s]how'
            header += f' {cnt} ✘-params'
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

    def delete_ACTION(self):
        """Handle 'd' key on HOME/REVIEW screen - set param to '##'"""
        gw = self.gw
        name, _, _, _, _ = gw.get_enums_regex()
        if name:
            value = gw.param_values[name]
            if value != '<>':
                gw.param_values[name] = '##'


class ReviewScreen(HomeScreen):
    """REVIEW screen - show diffs and warnings"""
    def enter_screen(self, from_screen):
        """
        Hook called when entering review screen.
        Resets cached data to ensure fresh review.
        """
        # Reset cached review data when entering from any screen
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
                self.win.add_body(f'{"was":>{tab.lwid}}  {ns.old_value}')
                gw.clues.append(Clue('nop'))

            for hey in ns.heys:
                warn_key = f'{param_name} {hey[1]}'
                is_inhibit = gw.warn_db.is_inhibit(warn_key)
                gw.hidden_stats.warn += int(is_inhibit)

                if not is_inhibit or gw.show_hidden_warns:
                    mark = '✘' if is_inhibit else ' '
                    sub_text = f'{mark} {hey[0]:>4}'
                    line = f'{sub_text:>{tab.lwid}}  {hey[1]}'
                    cnt = gw.add_wrapped_body_line(line,
                                        tab.lwid+2, pos==picked)
                    gw.clues.append(Clue('warn', warn_key, cnt))
                    pos += cnt
            gw.clues[clue_idx].group_cnt = pos - param_pos

            if is_current:
                emits = gw.drop_down_lines(param_name)
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
        self.gw.update_grub()


class RestoreScreen(Screen):
    """RESTORE screen - backup management"""
    def enter_screen(self, from_screen):
        """
        Hook called when entering restore screen.
        Refreshes backup list to show current state.
        """
        self.gw.do_start_up_backup()
        self.gw.refresh_backup_list()
        return True

    def draw_screen(self):
        self.win.set_pick_mode(True)
        self.add_body()
        self.add_head()

    def add_head(self):
        """ TBD """
        gw = self.gw
        header = 'RESTORE [d]elete [t]ag [r]estore [v]iew ESC:back ?:help [q]uit'
        gw.add_fancy_header(header)

    def add_body(self):
        """ TBD """
        gw = self.gw
        for pair in gw.ordered_backup_pairs:
            prefix = '●' if pair[0] == gw.grub_checksum else ' '
            self.win.add_body(f'{prefix} {pair[1].name}')

    def restore_ACTION(self):
        """Handle 'r' key on RESTORE screen - restore selected backup"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            key = gw.ordered_backup_pairs[idx][0]
            gw.backup_mgr.restore_backup(gw.backups[key])
            if gw.navigate_back():
                assert gw.ss.is_curr(HOME_ST)
                gw._reinit()
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

class ViewScreen(Screen):
    """VIEW screen - view backup contents"""
    def enter_screen(self, from_screen):
        """
        Hook called when entering view screen.
        Validates that backup data is loaded.
        """
        # Ensure we have backup data to display
        if not self.gw.bak_lines:
            # No backup loaded - this shouldn't happen, but handle gracefully
            return False
        return True

    def leave_screen(self, to_screen):
        """
        Hook called when leaving view screen.
        Cleans up backup view data.
        """
        # Clean up when leaving view screen
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
    """ WARNINGS Screen"""
    def __init__(self, grub_wiz):
        super().__init__(grub_wiz)
        self.keys = []  # key ('param: text') in each position
        self.search = ''
        self.regex = None # compiled

    def enter_screen(self, from_screen):
        """
        Hook called when entering warnings screen.
        """
        # self.search = ''
        # self.regex = None
        return True

    def leave_screen(self, to_screen):
        """
        Hook called when leaving warnings screen.
        Write any changes before leaving.
        """
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
        line = 'WARNINGS'
        line += f"   [x]:{'allow' if inh else 'inh'}"
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
            inh = 'X' if db.is_inhibit(key) else ' '

            # Split key into param_name and message
            if ': ' in key:
                param_name, message = key.split(': ', 1)
                # Strip GRUB_ prefix
                display_param = param_name.replace('GRUB_', '', 1)

                # Create full line for searching (always has param name)
                full_line = f'[{inh}] {"*"*sev:>4} {display_param}: {message}'

                # Check if same param as previous DISPLAYED line
                if param_name == prev_param:
                    # Omit param name, just show message with proper spacing
                    line = f'[{inh}] {"*"*sev:>4} {" " * (len(display_param) + 2)}{message}'
                else:
                    # Show full line with param name
                    line = full_line
            else:
                # No colon in key, show as-is
                full_line = line = f'[{inh}] {"*"*sev:>4} {key}'
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
        hint = 'must be a valid python regex'
        regex = None # compiled
        pattern = self.search

        while True:
            prompt = f'Enter search pattern [{hint}]'
            pattern = self.win.answer(prompt=prompt, seed=str(pattern), height=2)
            if pattern is None: # aborted
                return

            if not pattern:
                self.search = ''
                self.regex = None
                return
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                self.regex, self.search = regex, pattern
                return
            except Exception as whynot:
                hint = str(whynot)
                continue

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
    def __init__(self):
        GrubWiz.singleton = self
        self.win = None # place 1st
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
        self.grub_writer = GrubWriter()
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
        self._reinit()

    def _reinit(self):
        """ Call to initialize or re-initialize with new /etc/default/grub """
        self.param_cfg = {}
        self.param_values, self.prev_values = {}, {}
        self.saved_active_param_values = {}
        self.param_defaults = {}
        self.must_reviews = None
        self.ss = None
        self.sections = CannedConfig().data

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

        self.menu_entries = get_top_level_grub_entries()
        try:
            self.param_cfg['GRUB_DEFAULT']['enums'].update(self.menu_entries)
        except Exception:
            pass
        self.warn_db = WarnDB(param_cfg=self.param_cfg)

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
        spinner.add_key('enter_warnings', 'W - enter WARNINGs screen', category='action')
        spinner.add_key('restore', 'r - restore selected backup [in restore screen]', category='action')
        spinner.add_key('delete', 'd - delete selected backup [in restore screen]', category='action')
        spinner.add_key('tag', 't - tag/retag a backup file [in restore screen]', category='action')
        spinner.add_key('view', 'v - view a backup file [in restore screen]', category='action')
        spinner.add_key('write', 'w - write params and run "grub-update"', category='action')
        spinner.add_key('escape', 'ESC - back to prev screen',
                        category="action", keys=[27,])
        spinner.add_key('slash', '/ - filter pattern', category='action')
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

        # Initialize screen objects first (before ScreenStack)
        self.screens = {
            HOME_ST: HomeScreen(self),
            REVIEW_ST: ReviewScreen(self),
            RESTORE_ST: RestoreScreen(self),
            VIEW_ST: ViewScreen(self),
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

        # Check if this param uses EXPERT_EDIT mode
        if regex in (EXPERT_EDIT, EXPERT_EDIT[0]):
            self.expert_edit_param(win, name)
            return

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

            # First check regex if provided
            if regex and not re.match(regex, str(value)):
                valid, hint = False, f'must match: {pure_regex}'
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

        diffs = self.get_diffs()
        for param_name, pair in diffs.items():
            self.grub_file.param_data[param_name].new_value = pair[1]

        self.win.stop_curses()
        print("\033[2J\033[H") # 'clear'
        print('\n\n===== Left grub-wiz to update GRUB ====> ')
        # print('Check for correctness...')
        # print('-'*60)
        # print(contents)
        # print('-'*60)
        ok = True
        commit_rv = self.grub_file.write_file()
        if not commit_rv: # failure
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
            self.ss = ScreenStack(self.win, self.spins, SCREENS, self.screens)
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
                    'view', 'slash'
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
