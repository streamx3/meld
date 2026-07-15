"""LinkMap — the connector ribbons drawn between the two FileDiff panes.

For each diff chunk it fills a curved band from the left pane's line range to the
right pane's range, coloured by kind. It reads pixel positions from the panes'
`y_for_line()` (MeldSciView), so it stays in sync as they scroll. Geometry is
separated from painting (`chunk_shapes()`) so it can be tested without pixels.

This is the connectors-only linkmap: 3.24 removed the 1.4 click-to-merge icons
(that interaction moved to the ActionGutter), so nothing is drawn here but the
bands and their outlines.
"""

from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

_KIND_BG = {
    "delete": "delete_bg",
    "insert": "insert_bg",
    "replace": "replace_bg",
}


class LinkMap(QWidget):
    WIDTH = 40

    def __init__(self, filediff, parent=None):
        super().__init__(parent)
        self._fd = filediff
        self.setFixedWidth(self.WIDTH)

    def chunk_shapes(self):
        """(tag, l_top, l_bottom, r_top, r_bottom) per chunk, in widget y-coords.

        A zero-width side (an insert has no line on the left) collapses to a
        single y, so the band tapers to a point there.
        """
        left, right = self._fd.panes
        shapes = []
        for tag, l1, l2, r1, r2 in self._fd.opcodes():
            shapes.append((
                tag,
                left.y_for_line(l1), left.y_for_line(l2),
                right.y_for_line(r1), right.y_for_line(r2),
            ))
        return shapes

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        theme = self._fd.theme()
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
