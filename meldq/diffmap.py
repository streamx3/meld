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
        opt = QStyleOptionSlider()
        self._scrollbar.initStyleOption(opt)
        groove = self._scrollbar.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar, opt,
            QStyle.SubControl.SC_ScrollBarGroove, self._scrollbar)
        top_left = self.mapFromGlobal(
            self._scrollbar.mapToGlobal(groove.topLeft()))
        return QRect(QPoint(0, top_left.y()),
                     QSize(self.width(), groove.height()))

    def paintEvent(self, event):
        # Full painting lands in WP6 T6.7.
        pass
