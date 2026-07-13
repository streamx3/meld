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

"""Directory comparison view (port of meld/dirdiff.py).

WP5.2 lands the Qt-free content-comparison and filter-compilation core; the
DirDiff document itself follows in WP5.3+.
"""

import collections
import filecmp
import os
import re
import stat

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QMessageBox,
    QTreeView,
    QWidget,
)

from meldq.conf import _
from meldq.diffmap import DiffMap
from meldq.doc import MeldDoc
from meldq.util import misc
from meldq.widgets.historycombo import FileHistoryCombo
from meldq.widgets.treemodel import (
    STATE_MODIFIED,
    STATE_NEW,
    STATE_NORMAL,
    DiffTreeModel,
)

# Stat signature for the content-comparison cache. A namedtuple, NOT the py2
# misc.struct: struct.__cmp__ (misc.py:150) is dead in py3, so `==` fell back to
# identity and the cache-validity check (dirdiff.py:79) NEVER hit — every rescan
# silently re-read every file. namedtuple `==` compares by value, restoring it.
StatSig = collections.namedtuple("StatSig", "mode size mtime")
# Keyed on the path tuple only (not the regexes), matching 1.4. The result
# therefore depends on the *current* text filters, so a filter change must
# invalidate it — DirDiff.update_regexes calls clear_cache() (fixes a 1.4 bug
# where changing filters left stale results for unchanged files).
_cache = {}


def clear_cache():
    _cache.clear()


def _files_same(lof, regexes):
    """Return 0 if the files differ, 1 if identical, 2 if identical only after
    applying the text-filter `regexes`.

    Divergence from 1.4 (accepted, D-level): the original read files in TEXT
    mode and ran the user's str regexes over the raw bytes-as-str. Here files
    are read as BYTES (py3 `open(f, "r")` raises UnicodeDecodeError on binary
    and mistranslates CRLF), and the filters apply to a utf-8/replace-decoded
    view. Files differing only inside invalid-utf-8 bytes that a filter matches
    may classify differently; the parity test pins the new behavior.
    """
    if len(lof) <= 1:
        return 1
    lof = tuple(lof)

    def sig(f):
        s = os.stat(f)
        return StatSig(stat.S_IFMT(s.st_mode), s.st_size, s.st_mtime)

    def all_same(seq):
        return all(x == seq[0] for x in seq[1:])

    sigs = tuple(sig(f) for f in lof)
    arefiles = [stat.S_ISREG(s.mode) for s in sigs]
    if arefiles.count(False) == len(arefiles):      # all directories
        return 1
    elif arefiles.count(False):                     # a file/dir mixture
        return 0
    # No filters and mismatched sizes -> definitely different (skip the read).
    if len(regexes) == 0 and not all_same([s.size for s in sigs]):
        return 0
    # Cache: value-compare the stat signatures (see StatSig note above).
    cached = _cache.get(lof)
    if cached is not None and cached[0] == sigs:
        return cached[1]

    try:
        contents = [open(f, "rb").read() for f in lof]
    except (MemoryError, OverflowError):            # files too large to slurp
        # FIXME: filters are not applied in this fallback (as in 1.4).
        for i in range(len(lof) - 1):
            if not filecmp.cmp(lof[i], lof[i + 1], False):
                return 0
        return 1

    if all_same(contents):
        result = 1
    elif regexes:
        texts = [c.decode("utf-8", errors="replace") for c in contents]
        for r in regexes:
            texts = [re.sub(r, "", t) for t in texts]
        result = 2 if all_same(texts) else 0
    else:
        result = 0
    _cache[lof] = (sigs, result)
    return result


class TypeFilter:
    __slots__ = ("label", "filter", "active")

    def __init__(self, label, active, filter):
        self.label = label
        self.active = active
        self.filter = filter


def _compile_text_filter(value):
    """Compile a text-substitution filter with MULTILINE active.

    The 1.4 original appended "(?m)" to the END of the pattern (dirdiff.py:249),
    which Python 3.11 rejects outright: `re.error: global flags not at the start
    of the expression`. A real flag argument is equivalent and placement-safe.
    """
    return re.compile(value, re.MULTILINE)


def _compile_name_filter(value):
    """Compile a filename filter from whitespace-separated shell globs
    (dirdiff.py:287-296). Returns None for an empty pattern (skip it); raises
    re.error for a malformed glob."""
    bits = value.split()
    if len(bits) > 1:
        regex = "(%s)$" % "|".join(misc.shell_to_regex(b)[:-1] for b in bits)
    elif bits:
        regex = misc.shell_to_regex(bits[0])
    else:
        return None
    return re.compile(regex)


def build_text_filters(regexes_pref, on_error=None):
    """Parse the `regexes` pref into compiled MULTILINE patterns
    (dirdiff.py:244-252). `on_error(value)`, if given, is called for a bad
    pattern (the DirDiff method passes a QMessageBox); pure otherwise."""
    result = []
    for line in regexes_pref.split("\n"):
        if not line.strip():
            continue
        item = misc.ListItem(line)
        if not item.active:
            continue
        try:
            result.append(_compile_text_filter(item.value))
        except re.error:
            if on_error is not None:
                on_error(item.value)
    return result


def build_name_filters(filters_pref, on_error=None):
    """Parse the `filters` pref into TypeFilters (dirdiff.py:285-302). Each
    filter's predicate returns True to KEEP a name (not matched by the hide
    pattern). The `r=cregex` default-arg binding is load-bearing (a bare
    closure would capture the loop variable)."""
    result = []
    for line in filters_pref.split("\n"):
        if not line.strip():
            continue
        item = misc.ListItem(line)
        try:
            cregex = _compile_name_filter(item.value)
        except re.error:
            if on_error is not None:
                on_error(item.value)
            continue
        if cregex is None:      # empty pattern -> skip
            continue
        func = lambda x, r=cregex: r.match(x) is None
        result.append(TypeFilter(item.name, item.active, func))
    return result


class DirTreeView(QTreeView):
    """One of the (up to three) directory panes.

    Holds a back-reference to its DirDiff so a press anywhere (including empty
    space) can clear the other panes' selections — the `pressed` signal would
    miss clicks off any row (meld/dirdiff.py:838-841).
    """

    def __init__(self, dirdiff, parent=None):
        super().__init__(parent)
        self._dirdiff = dirdiff

    def mousePressEvent(self, event):
        self._dirdiff.on_pane_pressed(self)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        # T5.7 adds the Left/Right cross-pane hop; default handling until then.
        super().keyPressEvent(event)


class DirDiff(MeldDoc):
    """Two- or three-way directory comparison (port of meld/dirdiff.py).

    WP5.3 lands the skeleton (layout, model wiring, pane switching); the state
    computation (T5.5), scan generator (T5.6), cross-pane sync (T5.7) and
    operations (T5.8) fill the methods stubbed here.
    """

    def __init__(self, prefs, num_panes):
        super().__init__(prefs)

        self.focus_pane = None
        self.treeview_focussed = None
        self.state_filters = [STATE_NORMAL, STATE_MODIFIED, STATE_NEW]
        self.ignore_case = False
        self.regexes = []
        self.name_filters = []
        self.name_filters_available = []
        self._syncing = False

        self.widget = QWidget()
        self.treeview = [DirTreeView(self) for _ in range(3)]
        self.fileentry = [
            FileHistoryCombo(history_id="dir_comparison", directory_entry=True)
            for _ in range(3)]
        # DiffMaps (T5.9 wires setup); linkmaps are plain 50px spacers — in 1.4
        # dirdiff they are blank and their glade scroll wiring is dead.
        self.diffmap = [DiffMap(), DiffMap()]
        self.linkmap = [QWidget(), QWidget()]
        for spacer in self.linkmap:
            spacer.setFixedWidth(50)

        self._build_ui()

        for view in self.treeview:
            view.setHeaderHidden(True)
            view.setSelectionMode(
                QAbstractItemView.SelectionMode.ExtendedSelection)
            view.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows)
            view.setUniformRowHeights(True)
            # The row-activation handler (T5.7) owns dir expand/collapse; Qt's
            # default double-click-expands would toggle it a second time.
            view.setExpandsOnDoubleClick(False)
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            view.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            view.activated.connect(self.on_treeview_row_activated)

        self.create_name_filters()
        self.set_num_panes(num_panes)
        self.update_regexes()

    def _build_ui(self):
        # Columns: diffmap0 | pane0 | spacer0 | pane1 | spacer1 | pane2 | diffmap1
        grid = QGridLayout(self.widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        for pane in range(3):
            grid.addWidget(self.fileentry[pane], 0, 1 + pane * 2)
        grid.addWidget(self.diffmap[0], 1, 0)
        grid.addWidget(self.treeview[0], 1, 1)
        grid.addWidget(self.linkmap[0], 1, 2)
        grid.addWidget(self.treeview[1], 1, 3)
        grid.addWidget(self.linkmap[1], 1, 4)
        grid.addWidget(self.treeview[2], 1, 5)
        grid.addWidget(self.diffmap[1], 1, 6)
        for col in (1, 3, 5):
            grid.setColumnStretch(col, 1)

    # ----- model wiring / pane count ----------------------------------------

    def _set_model(self, model):
        """Attach a fresh model to the first ntree views.

        setModel replaces each view's QItemSelectionModel and un-hides its
        columns, so ALL selection wiring and column hiding lives here, not in
        __init__ — set_num_panes rebuilds the model on every comparison, and
        wiring only in __init__ would go stale after the second one.
        """
        self.model = model
        for i in range(model.ntree):
            view = self.treeview[i]
            view.setModel(model)
            view.setTreePosition(i)             # column i is the tree column
            for col in range(model.columnCount()):
                view.setColumnHidden(col, col != i)
            view.selectionModel().currentRowChanged.connect(
                self.on_treeview_cursor_changed)

    def set_num_panes(self, n):
        if n != self.num_panes and n in (1, 2, 3):
            self._set_model(DiffTreeModel(n))
            # Explicit loops, NOT map(...) — map is lazy in py3, so 1.4's
            # `map(lambda x: x.show(), toshow)` (dirdiff.py:863/:866) is a
            # silent no-op that would leave pane switching broken.
            toshow = (self.treeview[:n] + self.fileentry[:n]
                      + self.linkmap[:n - 1] + self.diffmap[:n])
            for widget in toshow:
                widget.show()
            tohide = (self.treeview[n:] + self.fileentry[n:]
                      + self.linkmap[n - 1:] + self.diffmap[n:])
            for widget in tohide:
                widget.hide()
            if self.num_panes != 0:             # not the first time through
                self.num_panes = n
                self.on_fileentry_activate(None)
            else:
                self.num_panes = n

    # ----- locations / label ------------------------------------------------

    def set_locations(self, locations):
        self.set_num_panes(len(locations))
        locations = [os.path.abspath(loc or ".") for loc in locations]
        self.model.removeRows(0, self.model.rowCount())
        for pane, loc in enumerate(locations):
            self.fileentry[pane].set_filename(loc)
            self.fileentry[pane].prepend_history(loc)
        child = self.model.add_entries(None, locations)
        self.treeview[0].setFocus()
        self._update_item_state(child)
        self.recompute_label()
        self.scheduler.remove_all_tasks()
        self.recursively_update((0,))

    def on_fileentry_activate(self, *args):
        # set_num_panes calls this with None; accept zero meaningful args.
        locations = [self.fileentry[pane].get_full_path()
                     for pane in range(self.num_panes)]
        self.set_locations(locations)

    def refresh(self):
        root = self.model.index(0, 0)
        if root.isValid():
            self.set_locations(self.model.value_paths(root))

    def recompute_label(self):
        root = self.model.index(0, 0)
        filenames = self.model.value_paths(root)
        shortnames = misc.shorten_names(*filenames)
        self.label_text = " : ".join(shortnames)
        self.label_changed.emit(self.label_text)

    # ----- filters (pref -> state; QActions land in T5.4) -------------------

    def update_regexes(self):
        self.regexes = build_text_filters(
            self.prefs.regexes, on_error=self._filter_error)
        clear_cache()       # filters changed -> the content cache is stale

    def create_name_filters(self):
        self.name_filters_available = build_name_filters(
            self.prefs.filters, on_error=self._filter_error)
        self.name_filters = [f for f in self.name_filters_available if f.active]

    def _filter_error(self, value):
        QMessageBox.warning(
            self.widget, "Meld",
            _("Error converting pattern '%s' to regular expression") % value)

    # ----- stubs filled by later tasks --------------------------------------

    def _update_item_state(self, it):
        # T5.5 computes real states via _files_same; skeleton marks present
        # panes NORMAL so the root row displays its directory names.
        for pane in range(self.model.ntree):
            path = self.model.value_path(it, pane)
            if path is not None:
                self.model.set_state(it, pane, STATE_NORMAL,
                                     isdir=os.path.isdir(path))

    def recursively_update(self, path):
        # T5.6 adds the scan task; skeleton just purges children and refreshes
        # the row's own state.
        it = self.model.index_for_rowpath(path)
        if not it.isValid():
            return
        self.model.removeRows(0, self.model.rowCount(it), it)
        self._update_item_state(it)

    def on_treeview_cursor_changed(self, *args):
        pass        # T5.7: status line

    def on_pane_pressed(self, view):
        pass        # T5.7: clear other panes' selections

    def on_treeview_row_activated(self, index):
        pass        # T5.7/T5.8: expand dirs / launch a comparison
