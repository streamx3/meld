### Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>
### Copyright (C) 2009-2010 Kai Willadsen <kai.willadsen@gmail.com>

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

import codecs
import difflib
import functools
import logging
import os
import re
import time
import types

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QIcon,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from meldq import conf
from meldq.conf import _
from meldq.diffmap import DiffMap
from meldq.doc import MeldDoc
from meldq.engine import diffutil
from meldq.linkmap import LinkMap
from meldq.util import misc
from meldq.util.misc import ListItem
from meldq.widgets.editor import DiffTextEdit
from meldq.widgets.findbar import FindBar
from meldq.widgets.historycombo import FileHistoryCombo
from meldq.widgets.msgarea import MsgAreaController, ResponseId

MASK_SHIFT, MASK_CTRL = 1, 2


class CachedSequenceMatcher:
    """Caching difflib wrapper with LRU-based eviction (filediff.py:41-72)."""

    def __init__(self):
        self.cache = {}

    def __call__(self, text1, textn):
        try:
            self.cache[(text1, textn)][1] = time.time()
            return self.cache[(text1, textn)][0]
        except KeyError:
            matcher = difflib.SequenceMatcher(None, text1, textn)
            opcodes = matcher.get_opcodes()
            self.cache[(text1, textn)] = [opcodes, time.time()]
            return opcodes

    def clean(self, size_hint):
        if len(self.cache) < size_hint * 3:
            return
        items = sorted(self.cache.items(), key=lambda it: it[1][1])
        for item in items[:-size_hint * 2]:
            del self.cache[item[0]]


class CursorDetails:
    __slots__ = ("pane", "pos", "line", "offset", "chunk", "prev_chunk", "next_chunk")

    def __init__(self):
        for var in self.__slots__:
            setattr(self, var, None)


class MeldBufferData:
    __slots__ = ("modified", "writable", "filename", "label", "encoding", "newlines")

    def __init__(self, filename=None):
        self.modified = False
        self.writable = True
        self.filename = filename
        self.label = filename
        self.encoding = None
        self.newlines = None


class FileDiff(MeldDoc):
    """Two or three way diff of text files."""

    differ = diffutil.Differ            # overridden by FileMerge
    MSG_SAME = 0

    def __init__(self, prefs, num_panes):
        super().__init__(prefs)

        self.warned_bad_comparison = False
        self.keymask = 0
        self.textview_overwrite = False
        self.textview_focussed = None
        self._sync_vscroll_lock = False
        self._sync_hscroll_lock = False
        self._inline_cache = set()
        self._inline_ranges = {}
        self._cached_match = CachedSequenceMatcher()
        self.cursor = CursorDetails()
        self.linediffer = self.differ()
        self.linediffer.ignore_blanks = self.prefs.ignore_blank_lines

        self._build_widgets()
        self._prev_blockcount = [doc.blockCount() for doc in self.textbuffer]
        self.bufferdata = [MeldBufferData() for _ in self.textbuffer]

        self._update_regexes()
        self._build_colors()
        self.load_font()

        for doc in self.textbuffer:
            self.undosequence.register_document(doc)
        self.undosequence.checkpointed.connect(self.on_undo_checkpointed)
        self.linediffer.diffs_changed.connect(self.on_diffs_changed)
        self.current_diff_changed.connect(self._on_current_diff_changed)

        for i, view in enumerate(self.textview):
            view.cursorPositionChanged.connect(
                functools.partial(self.on_cursor_position_changed, i))
            view.focus_changed.connect(
                functools.partial(self._on_editor_focus, i))
            view.insert_toggle_cb = self._toggle_overwrite
            view.spaces_instead_of_tabs = bool(self.prefs.spaces_instead_of_tabs)
            view.chunk_fn = functools.partial(self._chunk_fn_for_pane, i)
            view.is_current_chunk_fn = self._is_current_chunk
            view.focus_line_fn = lambda: self.cursor.line
            view.fill_colors = self.fill_colors
            view.line_colors = self.line_colors

        self.prefs.changed.connect(self.on_preference_changed)
        self.set_num_panes(num_panes)

    # ----- widget construction ---------------------------------------------

    def _build_widgets(self):
        self.textview = [DiffTextEdit() for _ in range(3)]
        self.textbuffer = [tv.document() for tv in self.textview]
        self.fileentry = [
            FileHistoryCombo("fileentry", settings=self.prefs._settings)
            for _ in range(3)]
        self.statusimage = [QLabel() for _ in range(3)]
        self.msgarea_mgr = [MsgAreaController() for _ in range(3)]
        self.diffmap = [DiffMap(), DiffMap()]
        self.linkmap = [LinkMap(), LinkMap()]
        self.vbox = [QWidget() for _ in range(3)]
        self.findbar = FindBar()

        assert len(self.textview) == len(self.fileentry) == 3
        assert len(self.diffmap) == len(self.linkmap) == 2

        grid = QGridLayout()
        grid.setSpacing(0)
        grid.setContentsMargins(0, 0, 0, 0)

        # Row 0: status images and file entries.
        grid.addWidget(self.statusimage[0], 0, 0)
        grid.addWidget(self.fileentry[0], 0, 1)
        grid.addWidget(self.statusimage[1], 0, 2)
        grid.addWidget(self.fileentry[1], 0, 3)
        grid.addWidget(self.statusimage[2], 0, 4)
        grid.addWidget(self.fileentry[2], 0, 5)

        # Row 1: per-pane (msgarea over editor), linkmaps, diffmaps.
        pane_cols = (1, 3, 5)
        for i in range(3):
            box = QVBoxLayout(self.vbox[i])
            box.setSpacing(0)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(self.msgarea_mgr[i])
            box.addWidget(self.textview[i], 1)
            grid.addWidget(self.vbox[i], 1, pane_cols[i])
        grid.addWidget(self.diffmap[0], 1, 0)
        grid.addWidget(self.linkmap[0], 1, 2)
        grid.addWidget(self.linkmap[1], 1, 4)
        grid.addWidget(self.diffmap[1], 1, 6)

        for col in (1, 3, 5):
            grid.setColumnStretch(col, 1)

        self.widget = QWidget()
        outer = QVBoxLayout(self.widget)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(grid, 1)
        outer.addWidget(self.findbar)
        self.findbar.hide()

    def _build_colors(self):
        def color(spec, fallback):
            c = QColor(spec)
            return c if c.isValid() else QColor(fallback)

        delete = color(self.prefs.color_delete_bg, "#c1ffc1")
        conflict = color(self.prefs.color_conflict_bg, "#ffc0cb")
        replace = color(self.prefs.color_replace_bg, "#ddeeff")
        # "insert" and "delete" deliberately share color_delete_bg (:167-168)
        self.fill_colors = {
            "insert": delete, "delete": delete,
            "conflict": conflict, "replace": replace,
        }
        # darker(125) == the old x*0.8 multiply (:172)
        self.line_colors = {k: v.darker(125) for k, v in self.fill_colors.items()}
        self.inline_format = QTextCharFormat()
        self.inline_format.setBackground(
            color(self.prefs.color_inline_bg, "#bcd2ee"))
        self.inline_format.setForeground(
            color(self.prefs.color_inline_fg, "#ff0000"))

    def _update_regexes(self):
        self.regexes = []
        for r in [ListItem(i) for i in self.prefs.regexes.split("\n") if i]:
            if r.active:
                try:
                    # 1.4 appended "(?m)"; trailing inline flags error on
                    # py3.11+, so pass re.MULTILINE instead (same effect).
                    self.regexes.append((re.compile(r.value, re.MULTILINE), r.value))
                except re.error:
                    pass

    def load_font(self):
        font = self.prefs.get_current_font()
        self.pixels_per_line = round(QFontMetricsF(font).height())
        for view in self.textview:
            view.set_font_and_tabs(font, self.prefs.tab_size)
        icon_dir = conf.package_dir() / "resources" / "icons"

        def load(name):
            return QPixmap(str(icon_dir / f"button_{name}.png")).scaledToHeight(
                self.pixels_per_line, Qt.TransformationMode.SmoothTransformation)

        self.pixmap_apply0 = load("apply0")
        self.pixmap_apply1 = load("apply1")
        self.pixmap_delete = load("delete")
        self.pixmap_copy0 = load("copy0")
        self.pixmap_copy1 = load("copy1")
        for lm in self.linkmap:
            lm.update()

    # ----- paint hooks ------------------------------------------------------

    def _chunk_fn_for_pane(self, pane, bounds):
        if self.num_panes <= 1:
            return ()
        return self.linediffer.single_changes(pane, bounds)

    def _is_current_chunk(self, line):
        chunk = self.linediffer.locate_chunk(self.cursor.pane or 0, line)[0]
        return chunk is not None and chunk == self.cursor.chunk

    # ----- panes / labels ---------------------------------------------------

    def set_num_panes(self, n):
        if n != self.num_panes and n in (1, 2, 3):
            self.num_panes = n
            toshow = (self.vbox[:n] + self.fileentry[:n]
                      + self.linkmap[:n - 1] + self.diffmap[:n])
            for w in toshow:
                w.setVisible(True)
            tohide = (self.statusimage + self.vbox[n:] + self.fileentry[n:]
                      + self.linkmap[n - 1:] + self.diffmap[n:])
            for w in tohide:
                w.setVisible(False)

            def chunk_change_fn(i):
                return lambda: self.linediffer.single_changes(i)

            for w, i in zip(self.diffmap, (0, self.num_panes - 1)):
                w.setup_editor(self.textview[i].verticalScrollBar(),
                               self.textview[i], chunk_change_fn(i),
                               self.fill_colors, self.line_colors)
            for i in range(self.num_panes - 1):
                self.linkmap[i].setup(self, i)
            for i in range(self.num_panes):
                if self.bufferdata[i].modified:
                    self.statusimage[i].setVisible(True)
            self._queue_draw()
            self.recompute_label()

    def _get_pane_label(self, i):
        #TRANSLATORS: this is the name of a new file which has not yet been saved
        return self.bufferdata[i].label or _("<unnamed>")

    def set_labels(self, lst):
        assert len(lst) <= len(self.bufferdata)
        for label, data in zip(lst, self.bufferdata):
            if len(label):
                data.label = label

    def recompute_label(self):
        filenames = [self._get_pane_label(i) for i in range(self.num_panes)]
        shortnames = misc.shorten_names(*filenames)
        style = self.widget.style()
        for i in range(self.num_panes):
            icon = None
            if self.bufferdata[i].modified:
                shortnames[i] += "*"
                if self.bufferdata[i].writable:
                    icon = QIcon.fromTheme(
                        "document-save",
                        style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
                else:
                    icon = QIcon.fromTheme(
                        "document-save-as",
                        style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
            elif not self.bufferdata[i].writable:
                icon = QIcon.fromTheme(
                    "emblem-readonly",
                    style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
            if icon is not None:
                self.statusimage[i].setPixmap(icon.pixmap(16, 16))
                self.statusimage[i].setVisible(True)
            else:
                self.statusimage[i].setVisible(False)
        self.label_text = " : ".join(shortnames)
        self.label_changed.emit(self.label_text)

    def _queue_draw(self):
        for view in self.textview:
            view.viewport().update()
        for i in range(self.num_panes - 1):
            self.linkmap[i].update()
        for dm in self.diffmap:
            dm.update()

    # ----- prefs / undo -----------------------------------------------------

    def on_preference_changed(self, key):
        if key == "tab_size":
            for view in self.textview:
                view.set_font_and_tabs(self.prefs.get_current_font(),
                                       self.prefs.tab_size)
        elif key in ("use_custom_font", "custom_font"):
            self.load_font()
        elif key == "regexes":
            self._update_regexes()
        elif key == "spaces_instead_of_tabs":
            for view in self.textview:
                view.spaces_instead_of_tabs = bool(self.prefs.spaces_instead_of_tabs)
        elif key == "ignore_blank_lines":
            self.linediffer.ignore_blanks = self.prefs.ignore_blank_lines
            self.set_files([None] * self.num_panes)
        # show_line_numbers / edit_wrap_lines / use_syntax_highlighting: no-op

    def on_undo_checkpointed(self, doc, is_at_checkpoint):
        pane = self.textbuffer.index(doc)
        self.bufferdata[pane].modified = not is_at_checkpoint
        self.recompute_label()

    def _toggle_overwrite(self):
        self.textview_overwrite = not self.textview_overwrite
        for view in self.textview:
            view.setOverwriteMode(self.textview_overwrite)
        if self.cursor.pane is not None:
            self.on_cursor_position_changed(self.cursor.pane, force=True)

    def _on_editor_focus(self, pane, focused):
        if focused:
            self.textview_focussed = self.textview[pane]
            self.cursor.pane = pane
        self._on_current_diff_changed()

    # ----- buffer handlers --------------------------------------------------

    def _ensure_contents_slots(self):
        if not hasattr(self, "_contents_slots"):
            self._contents_slots = [
                functools.partial(self._on_contents_change, i)
                for i in range(len(self.textbuffer))]

    def _connect_buffer_handlers(self):
        for view in self.textview:
            view.setReadOnly(False)
        self._ensure_contents_slots()
        for i, doc in enumerate(self.textbuffer):
            self._prev_blockcount[i] = doc.blockCount()
            doc.contentsChange.connect(self._contents_slots[i])
        self._buffer_connected = True

    def _disconnect_buffer_handlers(self):
        for view in self.textview:
            view.setReadOnly(True)
        if getattr(self, "_buffer_connected", False):
            self._ensure_contents_slots()
            for i, doc in enumerate(self.textbuffer):
                try:
                    doc.contentsChange.disconnect(self._contents_slots[i])
                except (TypeError, RuntimeError):
                    pass
            self._buffer_connected = False

    def set_buffer_writable(self, buf, yesno):
        pane = self.textbuffer.index(buf)
        self.bufferdata[pane].writable = yesno
        self.recompute_label()

    def set_buffer_modified(self, buf, yesno):
        pane = self.textbuffer.index(buf)
        self.bufferdata[pane].modified = yesno
        self.recompute_label()

    # ----- file loading -----------------------------------------------------

    def set_files(self, files):
        """Set num panes to len(files) and load each given file.

        A None element leaves that pane's text as-is.
        """
        self._disconnect_buffer_handlers()
        self._inline_cache = set()
        for i, f in enumerate(files):
            if f:
                self.textbuffer[i].clear()
                absfile = os.path.abspath(f)
                self.fileentry[i].set_filename(absfile)
                self.fileentry[i].prepend_history(absfile)
                bold, bnew = self.bufferdata[i], MeldBufferData(absfile)
                if bold.filename == bnew.filename:
                    bnew.label = bold.label
                self.bufferdata[i] = bnew
                self.msgarea_mgr[i].clear()
        self.recompute_label()
        self.textview[int(len(files) >= 2)].setFocus()
        self._connect_buffer_handlers()
        self.scheduler.add_task(self._set_files_internal(files).__next__)

    def add_dismissable_msg(self, pane, icon, primary, secondary):
        controller = self.msgarea_mgr[pane]
        msgarea = controller.new_from_text_and_icon(icon, primary, secondary)
        msgarea.add_stock_button_with_text(
            misc.gtk_mnemonic_to_qt(_("Hi_de")), "window-close",
            ResponseId.CLOSE)
        msgarea.response.connect(lambda *args: controller.clear())
        return msgarea

    def _load_files(self, files, textbuffers, panetext):
        self.undosequence.clear()
        yield _("[%s] Set num panes") % self.label_text
        self.set_num_panes(len(files))
        self._disconnect_buffer_handlers()
        self.linediffer.clear()
        self._queue_draw()
        try_codecs = self.prefs.text_codecs.split() or ["utf_8", "utf_16"]
        yield _("[%s] Opening files") % self.label_text
        tasks = []

        for i, f in enumerate(files):
            buf = textbuffers[i]
            if f:
                try:
                    task = types.SimpleNamespace(
                        filename=f, pane=i, buf=buf,
                        codecs_left=try_codecs[:],
                        fileobj=open(f, "rb"),
                        decoder=codecs.getincrementaldecoder(try_codecs[0])(),
                        text=[], was_cr=False, newline_kinds=set())
                    tasks.append(task)
                except (OSError, LookupError) as e:
                    buf.clear()
                    self.add_dismissable_msg(
                        i, "dialog-error", _("Could not read file"), str(e))
            else:
                panetext[i] = buf.toPlainText()
        yield _("[%s] Reading files") % self.label_text

        while tasks:
            for t in tasks[:]:
                raw = t.fileobj.read(4096)
                is_eof = len(raw) == 0
                try:
                    nextbit = t.decoder.decode(raw, final=is_eof)
                except UnicodeDecodeError as err:
                    t.codecs_left.pop(0)
                    if t.codecs_left:
                        t.fileobj.close()
                        t.fileobj = open(t.filename, "rb")
                        t.decoder = codecs.getincrementaldecoder(
                            t.codecs_left[0])()
                        t.buf.clear()
                        t.text = []
                        t.was_cr = False
                        t.newline_kinds = set()
                    else:
                        logging.warning("codec error fallback: %s", err)
                        t.buf.clear()
                        self.add_dismissable_msg(
                            t.pane, "dialog-error", _("Could not read file"),
                            _("%s is not in encodings: %s")
                            % (t.filename, try_codecs))
                        tasks.remove(t)
                    continue

                if "\x00" in nextbit:
                    t.buf.clear()
                    self.add_dismissable_msg(
                        t.pane, "dialog-error", _("Could not read file"),
                        _("%s appears to be a binary file.") % t.filename)
                    tasks.remove(t)
                    continue

                self._append_decoded(t, nextbit)

                if is_eof:
                    if t.was_cr:                 # dangling trailing lone CR
                        t.newline_kinds.add("\r")
                        self._append_normalized(t, "\n")
                        t.was_cr = False
                    self.set_buffer_writable(
                        t.buf, os.access(t.filename, os.W_OK))
                    self.bufferdata[t.pane].encoding = t.codecs_left[0]
                    kinds = t.newline_kinds
                    if len(kinds) == 1:
                        self.bufferdata[t.pane].newlines = next(iter(kinds))
                    elif kinds:
                        self.bufferdata[t.pane].newlines = tuple(sorted(kinds))
                    else:
                        self.bufferdata[t.pane].newlines = None
                    panetext[t.pane] = "".join(t.text)
                    t.fileobj.close()
                    tasks.remove(t)
            yield 1

        for b in self.textbuffer:
            self.undosequence.checkpoint(b)

    def _append_decoded(self, t, nextbit):
        # Rejoin a CR held from the previous chunk, then hold a trailing CR
        # (it may pair with a leading LF in the next chunk).
        if t.was_cr:
            nextbit = "\r" + nextbit
            t.was_cr = False
        if nextbit.endswith("\r"):
            t.was_cr = True
            nextbit = nextbit[:-1]
        # Count line endings BEFORE normalizing.
        crlf = nextbit.count("\r\n")
        lone_cr = nextbit.count("\r") - crlf
        lone_lf = nextbit.count("\n") - crlf
        if crlf:
            t.newline_kinds.add("\r\n")
        if lone_cr:
            t.newline_kinds.add("\r")
        if lone_lf:
            t.newline_kinds.add("\n")
        nextbit = nextbit.replace("\r\n", "\n").replace("\r", "\n")
        self._append_normalized(t, nextbit)

    @staticmethod
    def _append_normalized(t, text):
        cur = QTextCursor(t.buf)
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(text)
        t.text.append(text)

    def _set_files_internal(self, files):
        panetext = ["\n"] * len(files)
        for i in self._load_files(files, self.textbuffer, panetext):
            yield i
        for i in self._diff_files(files, panetext):
            yield i

    # ----- stubs completed by later WP6 tasks -------------------------------

    def _diff_files(self, files, panetext):
        yield 0                 # T6.4

    def _on_contents_change(self, pane, position, removed, added):
        pass                    # T6.4

    def on_cursor_position_changed(self, pane, force=False):
        pass                    # T6.11

    def _on_current_diff_changed(self, *args):
        pass                    # T6.9

    def on_diffs_changed(self):
        pass                    # T6.9 / T6.11

    def next_diff(self, direction):
        pass                    # T6.9
