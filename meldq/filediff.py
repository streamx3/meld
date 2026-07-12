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
import struct
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
from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QMessageBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from meldq import conf
from meldq.conf import _
from meldq.diffmap import DiffMap
from meldq.doc import Direction, MeldDoc
from meldq.engine import diffutil
from meldq.linkmap import LinkMap
from meldq.util import misc
from meldq.util.misc import ListItem
from meldq.widgets.editor import DiffTextEdit
from meldq.widgets.findbar import FindBar
from meldq.widgets.historycombo import FileHistoryCombo
from meldq.widgets.msgarea import MsgAreaController, ResponseId

MASK_SHIFT, MASK_CTRL = 1, 2

# QTextCursor.selectedText() uses U+2029 (paragraph separator) for block breaks.
_PARAGRAPH = "\u2029"


def position_at_line_or_eof(doc, line):
    """Document position of the start of `line`, or the last valid position
    for the EOF sentinel (filediff.py:82-85)."""
    if line >= doc.blockCount():
        return doc.characterCount() - 1
    return doc.findBlockByNumber(line).position()


def insert_text_at_line(doc, line, text):
    """Insert `text` at the start of `line`, prefixing a newline for the EOF
    case (filediff.py:87-90, minus the tag)."""
    if line >= doc.blockCount():
        text = "\n" + text
    cur = QTextCursor(doc)
    cur.setPosition(position_at_line_or_eof(doc, line))
    cur.insertText(text)


def text_between_lines(doc, lo, hi):
    cur = QTextCursor(doc)
    cur.setPosition(position_at_line_or_eof(doc, lo))
    cur.setPosition(position_at_line_or_eof(doc, hi),
                    QTextCursor.MoveMode.KeepAnchor)
    return cur.selectedText().replace(_PARAGRAPH, "\n")


def utf16_units(s):
    """UTF-16 code-unit values of `s` (no BOM: utf-16-le, so no strip).

    These match QTextCursor positions exactly, so `base + offset` lands on
    the right character even for astral-plane text (unlike GTK's char
    counting, filediff.py:895-898).
    """
    b = s.encode("utf-16-le")
    return struct.unpack("%dH" % (len(b) // 2), b)


class FakeText:
    """Lazy line-list view over a QTextDocument (filediff.py:392-410).

    Slicing returns filtered lines; single indexing returns one unfiltered
    line (matches the old __getitem__/__getslice__ split).
    """

    def __init__(self, doc, textfilter):
        self.doc = doc
        self.textfilter = textfilter

    def __getitem__(self, key):
        if isinstance(key, slice):
            lo = key.start or 0
            hi = self.doc.blockCount() if key.stop is None else key.stop
            txt = self.textfilter(text_between_lines(self.doc, lo, hi))
            if hi >= self.doc.blockCount():
                return txt.split("\n")
            return txt.split("\n")[:-1]
        block = self.doc.findBlockByNumber(min(key, self.doc.blockCount() - 1))
        return block.text()

    def __len__(self):
        return self.doc.blockCount()


class FakeTextArray:
    def __init__(self, docs, textfilter):
        self.texts = [FakeText(d, textfilter) for d in docs]

    def __getitem__(self, i):
        return self.texts[i]

    def __len__(self):
        return len(self.texts)


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
            view.verticalScrollBar().valueChanged.connect(
                lambda _v, i=i: self._sync_vscroll(i))
            view.horizontalScrollBar().valueChanged.connect(self._sync_hscroll)

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

    # ----- synchronized scrolling -------------------------------------------

    def _sync_hscroll(self, value):
        if self._sync_hscroll_lock:
            return
        self._sync_hscroll_lock = True
        for i in range(self.num_panes):
            sb = self.textview[i].horizontalScrollBar()
            if sb.value() != value:
                sb.setValue(value)
        self._sync_hscroll_lock = False

    def _sync_vscroll(self, master):
        # Line-unit port of filediff.py:1154-1206. QPlainTextEdit's vertical
        # scrollbar is line-indexed with wrap off, so the GTK pixel math
        # collapses to line arithmetic.
        if self._sync_vscroll_lock:
            return
        shift = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        if not shift:
            self._sync_vscroll_lock = True
            syncpoint = 0.5
            line = (self.textview[master].first_visible_line_fraction()
                    + self.textview[master].verticalScrollBar().pageStep() * syncpoint)
            scrollbar_influence = ((1, 2), (0, 2), (1, 0))
            for i in scrollbar_influence[master][:self.num_panes - 1]:
                sb = self.textview[i].verticalScrollBar()
                mbegin, mend = 0, self.textbuffer[master].blockCount()
                obegin, oend = 0, self.textbuffer[i].blockCount()
                for c in self.linediffer.pair_changes(master, i):
                    if c[1] >= line:
                        mend, oend = c[1], c[3]
                        break
                    elif c[2] >= line:
                        mbegin, mend = c[1], c[2]
                        obegin, oend = c[3], c[4]
                        break
                    else:
                        mbegin, obegin = c[2], c[4]
                fraction = (line - mbegin) / ((mend - mbegin) or 1)
                other_line = obegin + fraction * (oend - obegin)
                # GTK clamped to upper - page_size; QScrollBar.maximum()
                # already excludes pageStep(), so clamp to maximum() directly.
                val = other_line - sb.pageStep() * syncpoint
                sb.setValue(round(min(max(val, sb.minimum()), sb.maximum())))
                if i == 1:                       # central bar becomes the master
                    master, line = 1, other_line
            self._sync_vscroll_lock = False
        for lm in self.linkmap[:self.num_panes - 1]:
            lm.update()
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

    # ----- diff pipeline ----------------------------------------------------

    def _get_texts(self, raw=0):
        textfilter = [self._filter_text, lambda x: x][raw]
        return FakeTextArray(self.textbuffer, textfilter)

    def _filter_text(self, txt):
        def killit(m):
            assert m.group().count("\n") == 0
            if len(m.groups()):
                s = m.group()
                for g in m.groups():
                    if g:
                        s = s.replace(g, "")
                return s
            return ""
        r = None
        try:
            for c, r in self.regexes:
                txt = c.sub(killit, txt)
        except AssertionError:
            if not self.warned_bad_comparison:
                self.scheduler.paused = True
                try:
                    QMessageBox.warning(
                        self.widget, "Meld",
                        _("Regular expression '%s' changed the number of lines "
                          "in the file. Comparison will be incorrect. See the "
                          "user manual for more details.") % r)
                finally:
                    self.scheduler.paused = False
                self.warned_bad_comparison = True
        return txt

    def _diff_files(self, files, panetext):
        yield _("[%s] Computing differences") % self.label_text
        panetext = [self._filter_text(p) for p in panetext]
        lines = [p.split("\n") for p in panetext]
        step = self.linediffer.set_sequences_iter(lines)
        while next(step) is None:
            yield 1

        chunk, prev, nxt = self.linediffer.locate_chunk(1, 0)
        self.cursor.next_chunk = chunk if chunk is not None else nxt
        cur = QTextCursor(self.textbuffer[1])
        self.textview[1].setTextCursor(cur)
        self.scheduler.add_task(lambda: self.next_diff(Direction.DOWN), True)
        self._queue_draw()
        self.scheduler.add_task(self._update_highlighting().__next__)
        self._connect_buffer_handlers()
        self._set_merge_action_sensitivity()
        yield 0

    def _get_focused_pane(self):
        for i, view in enumerate(self.textview):
            if view.hasFocus():
                return i
        return -1

    def _on_contents_change(self, pane, position, removed, added):
        doc = self.textbuffer[pane]
        new_count = doc.blockCount()
        sizechange = new_count - self._prev_blockcount[pane]
        self._prev_blockcount[pane] = new_count
        startline = doc.findBlock(position).blockNumber()
        self._after_text_modified(pane, startline, sizechange)

    def _after_text_modified(self, pane, startline, sizechange):
        if self.num_panes > 1:
            self.linediffer.change_sequence(
                pane, startline, sizechange, self._get_texts())
            focused_pane = self._get_focused_pane()
            if focused_pane != -1:
                self.on_cursor_position_changed(focused_pane, force=True)
            self.scheduler.add_task(self._update_highlighting().__next__)
            self._queue_draw()

    # ----- inline highlighting ----------------------------------------------

    def _update_highlighting(self):
        # Wholesale rebuild of per-pane ExtraSelection lists. Unlike the GTK
        # tag machinery, selections are replaced atomically, so the old
        # progress-mark incremental cleaning is unnecessary. The expensive
        # difflib call stays cached via self._cached_match.
        alltexts = [t for t in self._get_texts(raw=1)]
        newcache = set()
        sels = [[] for _ in self.textbuffer]

        def add_sel(pane, start_pos, end_pos):
            sel = QTextEdit.ExtraSelection()
            sel.format = self.inline_format
            cur = QTextCursor(self.textbuffer[pane])
            cur.setPosition(start_pos)
            cur.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cur
            sels[pane].append(sel)

        for chunk in self.linediffer.all_changes():
            for i, c in enumerate(chunk):
                if c and c[0] == "replace":
                    pane1, panen = 1, i * 2
                    cacheitem = (i, c, tuple(alltexts[1][c[1]:c[2]]),
                                 tuple(alltexts[i * 2][c[3]:c[4]]))
                    newcache.add(cacheitem)
                    base1 = position_at_line_or_eof(self.textbuffer[pane1], c[1])
                    basen = position_at_line_or_eof(self.textbuffer[panen], c[3])
                    text1 = utf16_units("\n".join(alltexts[1][c[1]:c[2]]))
                    textn = utf16_units("\n".join(alltexts[i * 2][c[3]:c[4]]))
                    if len(text1) > 8000 and len(textn) > 8000:
                        add_sel(pane1, base1,
                                position_at_line_or_eof(self.textbuffer[pane1], c[2]))
                        add_sel(panen, basen,
                                position_at_line_or_eof(self.textbuffer[panen], c[4]))
                        continue
                    back = (0, 0)
                    for o in self._cached_match(text1, textn):
                        if o[0] == "equal":
                            if (o[2] - o[1] < 3) or (o[4] - o[3] < 3):
                                back = o[4] - o[3], o[2] - o[1]
                            continue
                        for j, (pane, base) in enumerate(((pane1, base1),
                                                          (panen, basen))):
                            add_sel(pane, base + o[1 + 2 * j] - back[j],
                                    base + o[2 + 2 * j])
                        back = (0, 0)
                    yield 1
        for pane, s in enumerate(sels):
            self.textview[pane].setExtraSelections(s)
        self._inline_cache = newcache
        self._cached_match.clean(len(self._inline_cache))

    # ----- stubs completed by later WP6 tasks -------------------------------

    def _set_merge_action_sensitivity(self):
        pass                    # T6.9

    def on_cursor_position_changed(self, pane, force=False):
        pass                    # T6.11

    def _on_current_diff_changed(self, *args):
        pass                    # T6.9

    def on_diffs_changed(self):
        pass                    # T6.9 / T6.11

    def next_diff(self, direction):
        pass                    # T6.9
