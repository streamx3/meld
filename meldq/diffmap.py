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

"""Overview bar beside a scrollbar, painting all chunks in miniature.

Two setup APIs coexist: setup(scrollbar, chunk_fn) is the fraction-based
form consumed by dirdiff (WP5); setup_editor(...) is the line-scaled form
consumed by filediff. The painting/geometry is completed in WP6 T6.7.
"""

from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QStyle, QStyleOptionSlider, QWidget


class DiffMap(QWidget):
    WIDTH = 20          # was style property 'width', diffmap.py:135-140
    X_PADDING = 2.5     # was 'x-padding', diffmap.py:141-147

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self._scrollbar = None
        self._editor = None
        self._chunk_fn = None            # fraction-based (dirdiff)
        self._change_chunk_fn = None     # line-based (filediff)
        self._fill_colors = {}
        self._line_colors = {}
        self._filtered_conn = None

    # ----- dirdiff (fraction-based) API -------------------------------------

    def setup(self, scrollbar, chunk_fn):
        self._scrollbar = scrollbar
        self._chunk_fn = chunk_fn
        self._editor = None
        self._change_chunk_fn = None
        self.update()

    # ----- filediff (line-based) API ----------------------------------------

    def setup_editor(self, scrollbar, editor, change_chunk_fn,
                     fill_colors, line_colors):
        if self._editor is not None:
            try:
                self._editor.document().blockCountChanged.disconnect(
                    self._on_blockcount_changed)
            except (TypeError, RuntimeError):
                pass
        self._scrollbar = scrollbar
        self._editor = editor
        self._change_chunk_fn = change_chunk_fn
        self._fill_colors = fill_colors
        self._line_colors = line_colors
        self._chunk_fn = None
        editor.document().blockCountChanged.connect(self._on_blockcount_changed)
        self.update()

    def _on_blockcount_changed(self, _count):
        self.update()

    def sizeHint(self):
        return QSize(self.WIDTH, 0)

    def _groove_rect_in_self(self):
        if self._scrollbar is None:
            return self.rect()
        sb = self._scrollbar
        # Build the option manually: initStyleOption is protected and PyQt
        # forbids calling it on a C++-created scrollbar (the editor's own).
        opt = QStyleOptionSlider()
        opt.initFrom(sb)
        opt.orientation = sb.orientation()
        opt.minimum = sb.minimum()
        opt.maximum = sb.maximum()
        opt.sliderPosition = sb.sliderPosition()
        opt.sliderValue = sb.value()
        opt.singleStep = sb.singleStep()
        opt.pageStep = sb.pageStep()
        opt.rect = sb.rect()
        groove = sb.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar, opt,
            QStyle.SubControl.SC_ScrollBarGroove, sb)
        top_left = self.mapFromGlobal(sb.mapToGlobal(groove.topLeft()))
        return QRect(QPoint(0, top_left.y()),
                     QSize(self.width(), groove.height()))

    def paintEvent(self, event):
        groove = self._groove_rect_in_self()
        if self._change_chunk_fn is not None and self._editor is not None:
            self._paint_editor(groove)
        elif self._chunk_fn is not None:
            self._paint_fractions(groove)

    def _paint_editor(self, groove):
        num_lines = self._editor.document().blockCount()
        if num_lines <= 0:
            return
        scale = groove.height() / num_lines
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.translate(0, groove.y())
        width = self.width()
        for c in self._change_chunk_fn():
            fill = self._fill_colors[c[0]]
            line = self._line_colors[c[0]]
            y0 = round(scale * c[1]) - 0.5
            y1 = round(scale * c[2]) - 0.5
            rect = QRectF(self.X_PADDING, y0,
                          width - 2 * self.X_PADDING, int(y1 - y0))
            painter.fillRect(rect, fill)
            painter.setPen(line)
            painter.drawRect(rect)
        painter.end()

    def _paint_fractions(self, groove):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.translate(0, groove.y())
        width = self.width()
        height = groove.height()
        for start_frac, end_frac, color in self._chunk_fn():
            color = QColor(color)
            y0 = round(height * start_frac) - 0.5
            y1 = round(height * end_frac) - 0.5
            rect = QRectF(self.X_PADDING, y0,
                          width - 2 * self.X_PADDING, int(y1 - y0))
            painter.fillRect(rect, color)
            painter.setPen(color.darker(125))
            painter.drawRect(rect)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._scrollbar is None:
            return
        groove = self._groove_rect_in_self()
        if groove.height() <= 0:
            return
        fraction = (event.position().y() - groove.y()) / groove.height()
        sb = self._scrollbar
        # GTK adj.upper includes the page; QScrollBar.maximum() excludes it.
        upper = sb.maximum() + sb.pageStep()
        val = fraction * upper - sb.pageStep() / 2
        sb.setValue(round(min(max(val, sb.minimum()), sb.maximum())))
