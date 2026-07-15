"""LinkMap — connector ribbons drawn between two adjacent FileDiff panes.

For each chunk it fills a curved band from the left pane's line range to the
right's, coloured by kind, reading pixel positions from the panes' `y_for_line()`
so it tracks scrolling. Geometry (`chunk_shapes`) is separated from painting so
it can be tested without pixels. Generic over any adjacent pane pair, so a
3-way view uses two of them (pane0–pane1 and pane1–pane2).

Connectors-only: 3.24 moved click-to-merge off the linkmap onto the gutter.
"""

from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

_KIND_BG = {
    "delete": "delete_bg",
    "insert": "insert_bg",
    "replace": "replace_bg",
    "conflict": "conflict_bg",
}


class LinkMap(QWidget):
    WIDTH = 40

    def __init__(self, left_view, right_view, chunks_fn, theme_fn, parent=None):
        super().__init__(parent)
        self._left = left_view
        self._right = right_view
        self._chunks_fn = chunks_fn      # () -> [(tag, l_lo, l_hi, r_lo, r_hi)]
        self._theme_fn = theme_fn
        self.setFixedWidth(self.WIDTH)

    def chunk_shapes(self):
        """(tag, l_top, l_bottom, r_top, r_bottom) per chunk, in widget y-coords.

        A zero-width side collapses to a single y, so the band tapers to a point.
        """
        shapes = []
        for tag, l_lo, l_hi, r_lo, r_hi in self._chunks_fn():
            shapes.append((
                tag,
                self._left.y_for_line(l_lo), self._left.y_for_line(l_hi),
                self._right.y_for_line(r_lo), self._right.y_for_line(r_hi),
            ))
        return shapes

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        theme = self._theme_fn()
        for tag, l_top, l_bot, r_top, r_bot in self.chunk_shapes():
            base = QColor(getattr(theme, _KIND_BG.get(tag, "replace_bg")))
            fill = QColor(base)
            fill.setAlpha(140)
            path = QPainterPath()
            path.moveTo(0, l_top)
            path.cubicTo(w * 0.5, l_top, w * 0.5, r_top, w, r_top)
            path.lineTo(w, r_bot)
            path.cubicTo(w * 0.5, r_bot, w * 0.5, l_bot, 0, l_bot)
            path.closeSubpath()
            painter.fillPath(path, fill)
            painter.strokePath(path, QPen(base, 1))
        painter.end()
