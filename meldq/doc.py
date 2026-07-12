### Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>

### This program is free software; you can redistribute it and/or modify
### it under the terms of the GNU General Public License as published by
### the Free Software Foundation; either version 2 of the License, or
### (at your option) any later version.

### This program is distributed in the hope that it will be useful,
### but WITHOUT ANY WARRANTY; without even the implied warranty of
### MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
### GNU General Public License for more details.

### You should have received a copy of the GNU General Public License
### along with this program; if not, write to the Free Software
### Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import enum
import os
import subprocess

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices

from meldq.conf import _
from meldq.engine import task, undo

# Use these to ensure consistent return values.
RESULT_OK, RESULT_ERROR = (0, 1)


class CloseResponse(enum.IntEnum):     # replaces gtk.RESPONSE_* (melddoc.py:126-135)
    OK = 0        # doc agrees to close
    CANCEL = 1    # doc vetoes close (and app quit)
    CLOSE = 2     # close without further callbacks (app-quit special case)


class Direction(enum.IntEnum):         # replaces gtk.gdk.SCROLL_DOWN/UP (meldapp.py:456-459)
    DOWN = 1                           # §2.2: THE app-wide direction enum; WP5/WP6/WP7 import it
    UP = -1


class MeldDoc(QObject):
    """Base class for documents in the meld application."""

    # contract signals — EXACT names
    label_changed = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    create_diff = pyqtSignal(list)
    closed = pyqtSignal()
    # 1.4-behavior extensions (melddoc.py:36-41), consumed by the shell
    file_changed = pyqtSignal(str)
    next_diff_changed = pyqtSignal(bool, bool)      # (have_prev, have_next)
    current_diff_changed = pyqtSignal()

    def __init__(self, prefs, parent=None):
        super().__init__(parent)
        self.undosequence = undo.UndoSequence(self)
        self.scheduler = task.FifoScheduler()
        self.prefs = prefs
        self.prefs.changed.connect(self.on_preference_changed)
        self.num_panes = 0
        self.label_text = _("untitled")
        self.widget = None      # the tab page; set by subclasses before _append_page

    # doc/shell action contract (normative) — base returns empty
    def doc_actions(self):
        return []

    def menu_contributions(self):
        return {}

    def toolbar_contributions(self):
        return []

    def save(self):
        pass

    def save_as(self):
        pass

    def stop(self):
        if self.scheduler.tasks_pending():
            self.scheduler.remove_task(self.scheduler.get_current_task())

    def _open_files(self, selected):
        files = [f for f in selected if os.path.isfile(f)]
        dirs = [d for d in selected if os.path.isdir(d)]
        if files:
            if self.prefs.edit_command_type == "custom":
                cmd = self.prefs.get_custom_editor_command(files)
                subprocess.Popen(cmd)
            else:   # "internal"
                for f in files:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(f))
        for d in dirs:
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def on_undo_activate(self):
        if self.undosequence.can_undo():
            self.undosequence.undo()

    def on_redo_activate(self):
        if self.undosequence.can_redo():
            self.undosequence.redo()

    def on_refresh_activate(self, *extra):
        self.on_reload_activate(*extra)

    def on_reload_activate(self, *extra):
        pass

    def on_find_activate(self, *extra):
        pass

    def on_find_next_activate(self, *extra):
        pass

    def on_replace_activate(self, *extra):
        pass

    def on_preference_changed(self, key):
        pass

    def on_file_changed(self, filename):
        pass

    def set_labels(self, lst):
        pass

    def next_diff(self, direction):
        pass

    def on_focus_change(self):
        pass

    def on_container_switch_in_event(self):
        """No-arg activation hook; the shell calls it on tab switch-in."""
        pass

    def on_container_switch_out_event(self):
        """Counterpart, called on the outgoing doc."""
        pass

    def on_delete_event(self, appquit=False):
        return CloseResponse.OK

    def on_quit_event(self):
        pass
