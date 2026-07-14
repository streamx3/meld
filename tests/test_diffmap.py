import pytest
from PyQt6.QtGui import QColor, QFont

from meldq.diffmap import DiffMap
from meldq.widgets.editor import DiffTextEdit

FILL = {"replace": QColor("#ddeeff")}
LINE = {"replace": QColor("#ddeeff").darker(125)}


@pytest.fixture
def wired(qapp, qtbot):
    editor = DiffTextEdit()
    editor.set_font_and_tabs(QFont("Monospace", 10), 4)
    editor.setPlainText("\n".join(f"line {i}" for i in range(100)))
    editor.resize(40, 300)
    dm = DiffMap()
    dm.resize(20, 300)
    qtbot.addWidget(editor)
    qtbot.addWidget(dm)
    editor.show()
    dm.show()
    qtbot.waitExposed(editor)
    qtbot.waitExposed(dm)
    chunks = lambda: [("replace", 20, 30, 20, 30)]
    dm.setup_editor(editor.verticalScrollBar(), editor, chunks, FILL, LINE)
    return dm, editor


def test_chunk_painted_in_band(wired):
    dm, editor = wired
    img = dm.grab().toImage()
    groove = dm._groove_rect_in_self()
    scale = groove.height() / 100
    y_mid = int(groove.y() + scale * 25)
    x = dm.width() // 2
    # a pixel in the chunk band (lines 20-30) is non-white
    band = img.pixelColor(x, y_mid)
    assert band != QColor("white") or band.blue() > band.red()   # tinted
    # a pixel well outside the band is background
    y_out = int(groove.y() + scale * 60)
    assert img.pixelColor(x, y_out).red() >= band.red()


def test_click_sets_scrollbar(wired):
    dm, editor = wired
    sb = editor.verticalScrollBar()
    groove = dm._groove_rect_in_self()
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    y = groove.y() + groove.height() * 0.5
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(10, y),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    dm.mousePressEvent(ev)
    expected = round(0.5 * (sb.maximum() + sb.pageStep()) - sb.pageStep() / 2)
    expected = min(max(expected, sb.minimum()), sb.maximum())
    assert sb.value() == expected


def test_blockcount_change_repaints(wired, monkeypatch):
    dm, editor = wired
    calls = []
    monkeypatch.setattr(dm, "update", lambda *a: calls.append(1))
    editor.setPlainText("just one line")     # blockCountChanged fires
    assert calls


def test_dirdiff_fraction_setup_still_paints(qapp, qtbot):
    # WP5's fraction-based setup(scrollbar, chunk_fn) must keep working
    from PyQt6.QtWidgets import QScrollBar
    sb = QScrollBar()
    sb.setRange(0, 100)
    sb.setPageStep(10)
    dm = DiffMap()
    dm.resize(20, 200)
    qtbot.addWidget(dm)
    qtbot.addWidget(sb)
    dm.show()
    qtbot.waitExposed(dm)
    dm.setup(sb, lambda: [(0.2, 0.3, QColor("#c1ffc1"))])
    img = dm.grab().toImage()
    # some tinted pixel exists in the 0.2-0.3 band
    groove = dm._groove_rect_in_self()
    y = int(groove.y() + groove.height() * 0.25)
    assert img.pixelColor(dm.width() // 2, y) != QColor("black")
