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

"""Canvas between two panes: bezier connectors and merge-action icons.

The keymask that morphs the icons (apply / copy / delete) is polled from
QApplication.keyboardModifiers() at every paint / press / release rather
than tracked via key events; a consequence is that pressing Shift or Ctrl
while the mouse is motionless does not repaint until the next mouse move.

The icon drawing and hit-testing live on FileDiff (paint_pixmap_at,
_linkmap_draw_icon, _linkmap_process_event) so FileMerge can override them.
"""

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class LinkMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setFixedWidth(50)
        self._doc = None
        self._which = 0

    def setup(self, doc, which):
        self._doc = doc
        self._which = which
        self.update()

    def paintEvent(self, event):
        doc, which = self._doc, self._which
        if doc is None or which + 1 >= doc.num_panes:
            return
        wtotal, htotal = self.width(), self.height()
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tv_src, tv_dst = doc.textview[which], doc.textview[which + 1]
        off_src = self.mapFromGlobal(
            tv_src.viewport().mapToGlobal(QPoint(0, 0))).y()
        off_dst = self.mapFromGlobal(
            tv_dst.viewport().mapToGlobal(QPoint(0, 0))).y()
        visible = [None, *tv_src.lines_visible(), *tv_dst.lines_visible()]
        x_steps = [-0.5, wtotal / 3.0, 2.0 * wtotal / 3.0, wtotal + 0.5]
        pix_x = wtotal - doc.pixmap_apply0.width()

        for c in doc.linediffer.pair_changes(which, which + 1, visible[1:5]):
            f0 = tv_src.line_ypos(c[1]) + off_src
            f1 = tv_src.line_ypos(c[2]) + off_src
            t0 = tv_dst.line_ypos(c[3]) + off_dst
            t1 = tv_dst.line_ypos(c[4]) + off_dst
            path = QPainterPath()
            path.moveTo(x_steps[0], f0 - 0.5)
            path.cubicTo(x_steps[1], f0 - 0.5, x_steps[2], t0 - 0.5,
                         x_steps[3], t0 - 0.5)
            path.lineTo(x_steps[3], t1 - 0.5)
            path.cubicTo(x_steps[2], t1 - 0.5, x_steps[1], f1 - 0.5,
                         x_steps[0], f1 - 0.5)
            path.closeSubpath()
            painter.fillPath(path, doc.fill_colors[c[0]])
            if doc.linediffer.locate_chunk(which, c[1])[0] == doc.cursor.chunk:
                painter.fillPath(path, QColor(255, 255, 255, 128))
            painter.strokePath(path, QPen(doc.line_colors[c[0]], 1.0))
            doc._linkmap_draw_icon(painter, which, c, pix_x, f0, t0)

        mid = int(0.5 * tv_src.height()) + 0.5
        painter.setPen(QPen(QColor(0, 0, 0, 128), 1.0))
        painter.drawLine(QPointF(0.35 * wtotal, mid), QPointF(0.65 * wtotal, mid))
        painter.end()

    def mousePressEvent(self, event):
        from meldq.filediff import MASK_CTRL, current_keymask
        if event.button() != Qt.MouseButton.LeftButton or self._doc is None:
            return
        doc, which = self._doc, self._which
        doc.mouse_chunk = None
        wtotal = self.width()
        htotal = self.height()
        pix_width = doc.pixmap_apply0.width()
        pix_height = doc.pixmap_apply0.height()
        if current_keymask() == MASK_CTRL:      # copy up/down half-zone hack
            pix_height *= 2
        x = event.position().x()
        if x < pix_width:
            side, rect_x = 0, 0
        elif x > wtotal - pix_width:
            side, rect_x = 1, wtotal - pix_width
        else:
            return
        doc._linkmap_process_event(event, which, side, htotal, rect_x,
                                   pix_width, pix_height)

    def mouseReleaseEvent(self, event):
        from meldq.filediff import MASK_CTRL, MASK_SHIFT, current_keymask
        if event.button() != Qt.MouseButton.LeftButton or self._doc is None:
            return
        doc = self._doc
        if not doc.mouse_chunk:
            return
        (src, dst), rect, chunk = doc.mouse_chunk
        doc.mouse_chunk = None
        px, py = event.position().x(), event.position().y()
        inrect = (rect[0] < px < rect[0] + rect[2]
                  and rect[1] < py < rect[1] + rect[3])
        if not inrect:
            return
        keymask = current_keymask()
        if keymask & MASK_SHIFT:
            doc.delete_chunk(src, chunk)
        elif keymask & MASK_CTRL:
            copy_up = py - rect[1] < 0.5 * rect[3]
            doc.copy_chunk(src, dst, chunk, copy_up)
        else:
            doc.replace_chunk(src, dst, chunk)

    def mouseMoveEvent(self, event):
        self.update()               # re-poll modifiers -> morph icons

    def wheelEvent(self, event):
        from meldq.doc import Direction
        if self._doc is None:
            return
        direction = (Direction.DOWN if event.angleDelta().y() < 0
                     else Direction.UP)
        self._doc.next_diff(direction)
