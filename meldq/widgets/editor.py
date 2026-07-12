### Copyright (C) 2002-2009 Stephen Kennedy <stevek@gnome.org>

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

"""Diff-aware text editor: a QPlainTextEdit that paints chunk backgrounds
under the text and exposes per-line geometry for the linkmap/diffmap/sync
scroll.

Deliberate deviation from 1.4: word wrap is OFF (prefs.edit_wrap_lines is
ignored in this first Qt version) so every block has uniform height and the
vertical scrollbar is line-indexed. All geometry below assumes that.

Undo is window-level through the shared UndoSequence; this widget swallows
Ctrl+Z/Ctrl+Shift+Z/Ctrl+Y (both as ShortcutOverride and keyPressEvent) so
the window QAction fires and the native per-document stack is never driven
by the widget directly. Do NOT call document().setUndoRedoEnabled(False) —
UndoSequence needs the native stack.
"""

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import QPlainTextEdit


class DiffTextEdit(QPlainTextEdit):
    focus_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # paint hooks, set by FileDiff
        self.chunk_fn = None
        self.is_current_chunk_fn = None
        self.focus_line_fn = None
        self.fill_colors = {}
        self.line_colors = {}
        # editing policy hooks, set by FileDiff
        self.insert_toggle_cb = None
        self.spaces_instead_of_tabs = False
        self.tab_size = 4

    # ----- geometry layer ---------------------------------------------------

    def line_height(self):
        return self.blockBoundingRect(self.document().firstBlock()).height()

    def line_ypos(self, line):
        """Viewport y of the top edge of `line` (0-based); the EOF sentinel
        (line >= blockCount()) returns bottom-of-last-block minus 1, mirroring
        filediff.py:1236-1237."""
        doc = self.document()
        if line >= doc.blockCount():
            geom = self.blockBoundingGeometry(doc.lastBlock()).translated(
                self.contentOffset())
            return geom.bottom() - 1.0
        block = doc.findBlockByNumber(line)
        return self.blockBoundingGeometry(block).translated(
            self.contentOffset()).top()

    def line_at_ypos(self, y):
        return self.cursorForPosition(QPoint(0, int(y))).blockNumber()

    def first_visible_line_fraction(self):
        block = self.firstVisibleBlock()
        geom = self.blockBoundingGeometry(block).translated(self.contentOffset())
        h = self.blockBoundingRect(block).height()
        return block.blockNumber() + (-geom.top() / h if h > 0 else 0.0)

    def lines_visible(self):
        first = self.firstVisibleBlock().blockNumber()
        last = self.cursorForPosition(
            QPoint(0, self.viewport().height() - 1)).blockNumber()
        return first, last + 1

    # ----- painting ---------------------------------------------------------

    def paintEvent(self, event):
        if self.chunk_fn is not None:
            painter = QPainter(self.viewport())
            painter.setClipRect(event.rect())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            bounds = (self.line_at_ypos(event.rect().top()),
                      self.line_at_ypos(event.rect().bottom() + 1))
            width = self.viewport().width()
            for change in self.chunk_fn(bounds):
                ypos0 = self.line_ypos(change[1])
                ypos1 = self.line_ypos(change[2])
                rect = QRectF(-0.5, ypos0 - 0.5, width + 1, ypos1 - ypos0)
                if change[1] != change[2]:
                    painter.fillRect(rect, self.fill_colors[change[0]])
                    if self.is_current_chunk_fn and self.is_current_chunk_fn(change[1]):
                        painter.fillRect(rect, QColor(255, 255, 255, 128))
                pen = QPen(self.line_colors[change[0]])
                pen.setWidthF(1.0)
                painter.setPen(pen)
                if ypos1 == ypos0:
                    painter.drawLine(QPointF(-0.5, ypos0 - 0.5),
                                     QPointF(width + 0.5, ypos0 - 0.5))
                else:
                    painter.drawRect(rect)
            if self.hasFocus() and self.focus_line_fn is not None:
                line = self.focus_line_fn()
                if line is not None:
                    y = self.line_ypos(min(line, self.document().blockCount() - 1))
                    painter.fillRect(QRectF(0, y, width, self.line_height()),
                                     QColor(255, 255, 0, 64))
            painter.end()
        super().paintEvent(event)

    # ----- key / focus policy ----------------------------------------------

    @staticmethod
    def _is_undo_redo(e):
        return (e.matches(QKeySequence.StandardKey.Undo)
                or e.matches(QKeySequence.StandardKey.Redo)
                or (bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
                    and e.key() == Qt.Key.Key_Y))

    def event(self, e):
        if e.type() == QEvent.Type.ShortcutOverride and self._is_undo_redo(e):
            e.ignore()
            return False
        return super().event(e)

    def keyPressEvent(self, e):
        if self._is_undo_redo(e):
            e.ignore()
            return                               # window QAction fires undo/redo
        if e.key() == Qt.Key.Key_Insert and self.insert_toggle_cb:
            self.insert_toggle_cb()
            return
        if e.key() == Qt.Key.Key_Tab and self.spaces_instead_of_tabs:
            col = self.textCursor().positionInBlock()
            self.insertPlainText(" " * (self.tab_size - col % self.tab_size))
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focus_changed.emit(False)

    # ----- font -------------------------------------------------------------

    def set_font_and_tabs(self, font, tab_size):
        self.setFont(font)
        self.tab_size = tab_size
        self.setTabStopDistance(
            tab_size * QFontMetricsF(font).horizontalAdvance(" "))
