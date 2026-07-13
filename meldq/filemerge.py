### Copyright (C) 2009 Piotr Piastucki <the_leech@users.berlios.de>

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

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QTextCursor, QTextDocument

from meldq.conf import _
from meldq.engine import merge
from meldq.filediff import MASK_CTRL, FileDiff, current_keymask


class FileMerge(FileDiff):
    """3-pane view whose middle pane is an auto-merge of an ancestor and two
    edits (a 4th "output" file is remapped in). The outer panes are read-only
    and the ancestor is loaded into a hidden document."""

    differ = merge.AutoMergeDiffer

    def __init__(self, prefs, num_panes):
        super().__init__(prefs, num_panes)
        self.hidden_textbuffer = QTextDocument(self)
        self.ancestor_file = None
        self.merge_file = None

    def _connect_buffer_handlers(self):
        super()._connect_buffer_handlers()
        self.textview[0].setReadOnly(True)
        self.textview[2].setReadOnly(True)

    def set_files(self, files):
        if len(files) == 4:
            self.ancestor_file = files[1]
            self.merge_file = files[3]
            files[1] = files[3]
            files = files[:3]
        super().set_files(files)

    def _set_files_internal(self, files):
        panetext = ["\n"] * len(files)
        textbuffers = self.textbuffer[:]
        textbuffers[1] = self.hidden_textbuffer     # ancestor loads here, hidden
        files[1] = self.ancestor_file
        for i in self._load_files(files, textbuffers, panetext):
            yield i
        for i in self._merge_files(panetext):
            yield i
        for i in self._diff_files(files, panetext):
            yield i

    def _get_custom_status_text(self):
        return "   Conflicts: %i" % self.linediffer.get_unresolved_count()

    def set_buffer_writable(self, buf, yesno):
        if buf is self.hidden_textbuffer:
            buf = self.textbuffer[1]
            yesno = True
        pane = self.textbuffer.index(buf)
        self.bufferdata[pane].writable = yesno
        self.recompute_label()

    def _merge_files(self, panetext):
        yield _("[%s] Computing differences") % self.label_text
        lines = [p.split("\n") for p in panetext]
        filteredlines = [self._filter_text(p).split("\n") for p in panetext]
        merger = merge.Merger()
        step = merger.initialize(filteredlines, lines)
        while next(step) is None:
            yield 1
        yield _("[%s] Merging files") % self.label_text
        for panetext[1] in merger.merge_3_files():
            yield 1
        self.linediffer.unresolved = merger.unresolved
        cur = QTextCursor(self.textbuffer[1])
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(panetext[1])
        self.bufferdata[1].modified = True
        self.recompute_label()
        yield 1

    def _linkmap_draw_icon(self, painter, which, change, x, f0, t0):
        pix0 = self.pixmap_delete
        keymask = current_keymask()
        if which:
            pix1 = self.pixmap_copy1 if keymask & MASK_CTRL else self.pixmap_apply1
        else:
            pix1 = self.pixmap_copy0 if keymask & MASK_CTRL else self.pixmap_apply0
        if which:
            if change[0] in ("delete",):
                self.paint_pixmap_at(painter, pix0, 0, f0)
            if change[0] in ("insert", "replace", "conflict"):
                self.paint_pixmap_at(painter, pix1, x, t0)
        else:
            if change[0] in ("insert",):
                self.paint_pixmap_at(painter, pix0, x, t0)
            if change[0] in ("delete", "replace", "conflict"):
                self.paint_pixmap_at(painter, pix1, 0, f0)

    def _linkmap_process_event(self, event, which, side, htotal, rect_x,
                               pix_width, pix_height):
        origsrc = which + side
        src = 2 * which
        dst = 1
        linkmap = self.linkmap[which]
        dst_offset = linkmap.mapFromGlobal(
            self.textview[dst].viewport().mapToGlobal(QPoint(0, 0))).y()
        src_offset = linkmap.mapFromGlobal(
            self.textview[src].viewport().mapToGlobal(QPoint(0, 0))).y()
        ey = event.position().y()
        for c in self.linediffer.pair_changes(src, dst):
            if c[0] == "insert":
                if origsrc != 1:
                    continue
                h = self.textview[dst].line_ypos(c[3]) + dst_offset
            else:
                if origsrc == 1:
                    continue
                h = self.textview[src].line_ypos(c[1]) + src_offset
            if h < 0:
                continue
            elif h > htotal:
                break
            elif h < ey < h + pix_height:
                self.mouse_chunk = (
                    (src, dst), (rect_x, h, pix_width, pix_height), c)
                break
