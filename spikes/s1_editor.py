"""S1 gate spike: can QPlainTextEdit carry Meld's filediff rendering model?

Two panes with chunk backgrounds and boundary lines painted under the text,
proportional synchronized scrolling interpolated between chunk boundaries,
and a linkmap widget drawing bezier connectors between corresponding chunks.

Run interactively:      python spikes/s1_editor.py
Run the PASS harness:   python spikes/s1_editor.py --auto [--shots DIR]
"""

import bisect
import json
import os
import sys

if "--auto" in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QPlainTextEdit,
    QWidget,
)

FILL = QColor(180, 210, 250, 120)
BORDER = QColor(96, 140, 190)
LINK_FILL = QColor(180, 210, 250, 90)
LINK_EDGE = QColor(96, 140, 190, 160)
N_CHUNKS = 30
FONT_SIZES = [10, 14, 18]


def build_documents():
    """Two ~2000-line documents differing in N_CHUNKS scattered chunks.

    Returns (left_lines, right_lines, chunks) where each chunk is
    (l_start, l_end, r_start, r_end) in line numbers, end-exclusive.
    """
    left, right, chunks = [], [], []
    shapes = [(3, 5), (4, 0), (0, 6), (2, 2), (6, 3)]
    for i in range(N_CHUNKS):
        for j in range(40 + (i * 7) % 25):
            line = f"common text, section {i}, row {j}, lorem ipsum dolor sit amet"
            left.append(line)
            right.append(line)
        nl, nr = shapes[i % len(shapes)]
        chunks.append((len(left), len(left) + nl, len(right), len(right) + nr))
        left.extend(f"LEFT ONLY chunk {i} line {j} ~~~~~~~~" for j in range(nl))
        right.extend(f"RIGHT ONLY chunk {i} line {j} ########" for j in range(nr))
    for j in range(60):
        line = f"common trailing row {j}"
        left.append(line)
        right.append(line)
    return left, right, chunks


class DiffPane(QPlainTextEdit):
    def __init__(self, lines, ranges):
        super().__init__()
        self.setPlainText("\n".join(lines))
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.ranges = ranges  # sorted (start, end) line ranges
        self._starts = [r[0] for r in ranges]
        self.paint_block_counts = []

    def chunk_at(self, line):
        i = bisect.bisect_right(self._starts, line) - 1
        if i >= 0 and self.ranges[i][0] <= line < max(self.ranges[i][1], self.ranges[i][0] + 1):
            return self.ranges[i]
        return None

    def line_ypos(self, line):
        """Top y of a line in viewport coordinates (bottom of doc for line == blockCount)."""
        doc = self.document()
        if line >= doc.blockCount():
            block = doc.findBlockByNumber(doc.blockCount() - 1)
            return self.blockBoundingGeometry(block).translated(self.contentOffset()).bottom()
        block = doc.findBlockByNumber(line)
        return self.blockBoundingGeometry(block).translated(self.contentOffset()).top()

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        height = self.viewport().rect().height()
        width = self.viewport().width()
        offset = self.contentOffset()
        block = self.firstVisibleBlock()
        count = 0
        while block.isValid():
            geom = self.blockBoundingGeometry(block).translated(offset)
            if geom.top() > height:
                break
            count += 1
            line = block.blockNumber()
            chunk = self.chunk_at(line)
            if chunk is not None and chunk[1] > chunk[0]:
                painter.fillRect(QRectF(0, geom.top(), width, geom.height()), FILL)
                painter.setPen(QPen(BORDER, 1))
                if line == chunk[0]:
                    painter.drawLine(0, int(geom.top()), width, int(geom.top()))
                if line == chunk[1] - 1:
                    painter.drawLine(0, int(geom.bottom()), width, int(geom.bottom()))
            elif chunk is not None:  # zero-height chunk (pure insert on other side)
                painter.setPen(QPen(BORDER, 1))
                painter.drawLine(0, int(geom.top()), width, int(geom.top()))
            block = block.next()
        painter.end()
        self.paint_block_counts.append(count)
        super().paintEvent(event)


class LinkMap(QWidget):
    def __init__(self, left, right, chunks):
        super().__init__()
        self.setFixedWidth(40)
        self.left, self.right, self.chunks = left, right, chunks

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        for l0, l1, r0, r1 in self.chunks:
            y_l0 = self.left.line_ypos(l0)
            y_l1 = self.left.line_ypos(max(l1, l0))
            y_r0 = self.right.line_ypos(r0)
            y_r1 = self.right.line_ypos(max(r1, r0))
            if max(y_l1, y_r1) < 0 or min(y_l0, y_r0) > h:
                continue
            path = QPainterPath()
            path.moveTo(0, y_l0)
            path.cubicTo(w * 0.5, y_l0, w * 0.5, y_r0, w, y_r0)
            path.lineTo(w, y_r1)
            path.cubicTo(w * 0.5, y_r1, w * 0.5, y_l1, 0, y_l1)
            path.closeSubpath()
            painter.fillPath(path, LINK_FILL)
            painter.setPen(QPen(LINK_EDGE, 1))
            painter.drawPath(path)
        painter.end()


class SpikeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        left_lines, right_lines, chunks = build_documents()
        self.chunks = chunks
        self.left = DiffPane(left_lines, [(c[0], c[1]) for c in chunks])
        self.right = DiffPane(right_lines, [(c[2], c[3]) for c in chunks])
        self.linkmap = LinkMap(self.left, self.right, chunks)

        # Piecewise-linear anchors between the panes: chunk starts and ends.
        anchors = [(0, 0)]
        for l0, l1, r0, r1 in chunks:
            anchors.append((l0, r0))
            anchors.append((l1, r1))
        anchors.append((self.left.document().blockCount(),
                        self.right.document().blockCount()))
        self.anchors_l = [a[0] for a in anchors]
        self.anchors_r = [a[1] for a in anchors]

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.left)
        layout.addWidget(self.linkmap)
        layout.addWidget(self.right)
        self.setCentralWidget(central)
        self.setWindowTitle("S1 spike")

        self._syncing = False
        self._font_index = 1
        self.apply_font(FONT_SIZES[self._font_index])

        self.left.verticalScrollBar().valueChanged.connect(
            lambda v: self.sync_scroll(from_left=True))
        self.right.verticalScrollBar().valueChanged.connect(
            lambda v: self.sync_scroll(from_left=False))
        for bar in (self.left.verticalScrollBar(), self.right.verticalScrollBar()):
            bar.valueChanged.connect(self.linkmap.update)

    def apply_font(self, size):
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(size)
        for pane in (self.left, self.right):
            pane.setFont(font)
        self.linkmap.update()

    def cycle_font(self):
        self._font_index = (self._font_index + 1) % len(FONT_SIZES)
        self.apply_font(FONT_SIZES[self._font_index])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F:
            self.cycle_font()
        else:
            super().keyPressEvent(event)

    def map_line(self, line, to_right=True):
        src = self.anchors_l if to_right else self.anchors_r
        dst = self.anchors_r if to_right else self.anchors_l
        i = max(bisect.bisect_right(src, line) - 1, 0)
        if i >= len(src) - 1:
            return dst[-1]
        span_src = src[i + 1] - src[i]
        span_dst = dst[i + 1] - dst[i]
        frac = 0.0 if span_src == 0 else (line - src[i]) / span_src
        return dst[i] + frac * span_dst

    def sync_scroll(self, from_left):
        if self._syncing:
            return
        self._syncing = True
        try:
            src = self.left if from_left else self.right
            dst = self.right if from_left else self.left
            mapped = self.map_line(src.verticalScrollBar().value(),
                                   to_right=from_left)
            dst.verticalScrollBar().setValue(round(mapped))
        finally:
            self._syncing = False
        self.linkmap.update()


def run_auto(shots_dir):
    app = QApplication(sys.argv)
    win = SpikeWindow()
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    os.makedirs(shots_dir, exist_ok=True)
    report = {"pass": True, "checks": {}}

    def grab(name):
        app.processEvents()
        win.grab().save(os.path.join(shots_dir, name))

    # (c) paint cost bounded by visible blocks across a full scroll sweep
    for pane in (win.left, win.right):
        pane.paint_block_counts.clear()
    bar = win.left.verticalScrollBar()
    for v in range(0, bar.maximum() + 1, max(bar.maximum() // 40, 1)):
        bar.setValue(v)
        app.processEvents()
        win.grab()  # force a render pass
    max_blocks = max(max(win.left.paint_block_counts),
                     max(win.right.paint_block_counts))
    report["checks"]["max_blocks_per_paint"] = max_blocks
    report["pass"] &= max_blocks < 200

    # (b)-proxy: anchor alignment — scrolling left pane to a chunk start puts
    # the corresponding right chunk start at the same scrollbar position
    errors = []
    for l0, l1, r0, r1 in win.chunks:
        target = min(l0, bar.maximum())
        bar.setValue(target)
        app.processEvents()
        expected = win.map_line(target, to_right=True)
        errors.append(abs(win.right.verticalScrollBar().value() - expected))
    report["checks"]["max_anchor_error_lines"] = max(errors)
    report["pass"] &= max(errors) <= 1.0

    # reentrancy: setting left must not bounce left via the right handler
    bar.setValue(bar.maximum() // 2)
    app.processEvents()
    before = bar.value()
    for _ in range(3):
        app.processEvents()
    report["checks"]["reentrancy_stable"] = (bar.value() == before)
    report["pass"] &= bar.value() == before

    grab("s1_mid_scroll.png")
    bar.setValue(0)
    grab("s1_top.png")

    # (d) font-size torture: geometry must re-derive consistently
    win.cycle_font()  # 18pt
    app.processEvents()
    font_ok = True
    for pane in (win.left, win.right):
        pane.paint_block_counts.clear()
    bar.setValue(min(200, bar.maximum()))
    grab("s1_font18.png")
    top_block = win.left.firstVisibleBlock().blockNumber()
    y = win.left.line_ypos(top_block)
    font_ok &= -1.0 <= y <= win.left.viewport().height()
    max_blocks_font = max(max(win.left.paint_block_counts, default=0),
                          max(win.right.paint_block_counts, default=0))
    report["checks"]["font_change_geometry_ok"] = font_ok
    report["checks"]["max_blocks_after_font_change"] = max_blocks_font
    report["pass"] &= font_ok and 0 < max_blocks_font < 200

    # resize torture
    win.resize(900, 600)
    grab("s1_resized.png")

    report["screenshots"] = sorted(os.listdir(shots_dir))
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


def main():
    if "--auto" in sys.argv:
        idx = sys.argv.index("--shots") if "--shots" in sys.argv else -1
        shots = sys.argv[idx + 1] if idx >= 0 else "/tmp/s1_shots"
        sys.exit(run_auto(shots))
    app = QApplication(sys.argv)
    win = SpikeWindow()
    win.resize(1200, 800)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
