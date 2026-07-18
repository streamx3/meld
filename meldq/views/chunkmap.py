"""ChunkMap — a full-height overview strip beside a FileDiff pane.

Paints every diff chunk scaled to the whole document height (a bird's-eye view
of where the changes are), draws a "you-are-here" handle for the current
viewport, and scrolls the pane when clicked or dragged. Geometry (`_y_for_line`)
is separated from painting so it can be reasoned about without pixels.

3.24 calls this the overview/ChunkMap; the connector ribbons between panes are
the separate LinkMap.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

_KIND_BG = {
    "delete": "delete_bg",
    "insert": "insert_bg",
    "replace": "replace_bg",
    "conflict": "conflict_bg",
}
_MIN_BAND = 2       # px — a one-line change stays visible when scaled down


class ChunkMap(QWidget):
    WIDTH = 16

    def __init__(self, view, chunks_fn, theme_fn, total_lines_fn, parent=None):
        super().__init__(parent)
        self._view = view                 # the MeldSciView this scrolls
        self._chunks_fn = chunks_fn        # () -> [(tag, lo, hi)] (0-based lines)
        self._theme_fn = theme_fn
        self._total_lines_fn = total_lines_fn
        self.setFixedWidth(self.WIDTH)
        self._view.scrolled.connect(self.update)

    # ----- geometry ---------------------------------------------------------

    def _y_for_line(self, line, total):
        return self.height() * line / max(1, total)

    def _line_for_y(self, y, total):
        return int(y / max(1, self.height()) * total)

    def handle_rect(self):
        """(top_y, height) of the you-are-here viewport handle, in widget px."""
        total = self._total_lines_fn()
        top = self._view.first_visible_line()
        visible = self._view.lines_on_screen()
        y1 = self._y_for_line(top, total)
        y2 = self._y_for_line(top + visible, total)
        return y1, max(_MIN_BAND, y2 - y1)

    # ----- painting ---------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        theme = self._theme_fn()
        total = self._total_lines_fn()
        w = self.width()
        for tag, lo, hi in self._chunks_fn():
            y1 = self._y_for_line(lo, total)
            y2 = self._y_for_line(hi, total)
            colour = QColor(getattr(theme, _KIND_BG.get(tag, "replace_bg")))
            painter.fillRect(0, int(y1), w, max(_MIN_BAND, int(y2 - y1)), colour)
        # you-are-here handle
        top, height = self.handle_rect()
        pen = QPen(QColor(theme.text))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, int(top), w - 1, int(height))
        painter.end()

    # ----- interaction ------------------------------------------------------

    def _scrub_to(self, y):
        total = self._total_lines_fn()
        line = self._line_for_y(y, total)
        # centre the clicked line in the viewport
        line = max(0, line - self._view.lines_on_screen() // 2)
        self._view.scroll_to_line(line)

    def mousePressEvent(self, event):
        self._scrub_to(event.position().y())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._scrub_to(event.position().y())
