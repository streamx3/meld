import pytest
from PyQt6.QtCore import QSettings, QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QMouseEvent
from PyQt6.QtWidgets import QApplication

from meldq.filediff import FileDiff
from meldq.util.prefs import Preferences


@pytest.fixture
def doc(qapp, qtbot, tmp_path):
    prefs = Preferences(
        QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    d = FileDiff(prefs, 2)
    d.set_num_panes(2)
    for view in d.textview[:2]:
        view.set_font_and_tabs(QFont("Monospace", 10), 4)
    left = "\n".join(["same"] * 10 + ["LEFT changed here"] + ["tail"] * 10)
    right = "\n".join(["same"] * 10 + ["RIGHT changed here"] + ["tail"] * 10)
    d.textbuffer[0].setPlainText(left)
    d.textbuffer[1].setPlainText(right)
    for _s in d._diff_files([None, None], [left, right]):
        pass
    d.widget.resize(700, 400)
    qtbot.addWidget(d.widget)
    d.widget.show()
    qtbot.waitExposed(d.widget)
    return d


def press(lm, x, y, mods=Qt.KeyboardModifier.NoModifier):
    return QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, mods)


def release(lm, x, y, mods=Qt.KeyboardModifier.NoModifier):
    return QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(x, y),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, mods)


def chunk_y(doc, lm):
    # y (in linkmap coords) of the changed chunk on the source (left) pane
    from PyQt6.QtCore import QPoint
    off = lm.mapFromGlobal(doc.textview[0].viewport().mapToGlobal(QPoint(0, 0))).y()
    return doc.textview[0].line_ypos(10) + off + 2


def test_linkmap_renders_chunk(doc):
    lm = doc.linkmap[0]
    img = lm.grab().toImage()
    # scan for a non-background (tinted) pixel
    found = False
    for y in range(0, lm.height(), 3):
        for x in range(0, lm.width(), 3):
            c = img.pixelColor(x, y)
            if c.alpha() > 0 and (c.red(), c.green(), c.blue()) != (255, 255, 255) \
                    and c != QColor("black"):
                found = True
                break
        if found:
            break
    assert found


def test_click_replaces_chunk(doc, monkeypatch):
    lm = doc.linkmap[0]
    calls = []
    monkeypatch.setattr(doc, "replace_chunk", lambda *a: calls.append(a))
    y = chunk_y(doc, lm)
    lm.mousePressEvent(press(lm, 2, y))
    assert doc.mouse_chunk is not None
    lm.mouseReleaseEvent(release(lm, 2, y))
    assert len(calls) == 1
    src, dst, chunk = calls[0]
    assert (src, dst) == (0, 1)


def test_shift_click_deletes_chunk(doc, monkeypatch):
    lm = doc.linkmap[0]
    calls = []
    monkeypatch.setattr(doc, "delete_chunk", lambda *a: calls.append(a))
    monkeypatch.setattr(QApplication, "keyboardModifiers",
                        staticmethod(lambda: Qt.KeyboardModifier.ShiftModifier))
    y = chunk_y(doc, lm)
    lm.mousePressEvent(press(lm, 2, y, Qt.KeyboardModifier.ShiftModifier))
    lm.mouseReleaseEvent(release(lm, 2, y, Qt.KeyboardModifier.ShiftModifier))
    assert len(calls) == 1


def test_wheel_navigates(doc, monkeypatch):
    from meldq.doc import Direction
    lm = doc.linkmap[0]
    calls = []
    monkeypatch.setattr(doc, "next_diff", lambda d: calls.append(d))
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtCore import QPoint
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, -120),
                     QPoint(0, -120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    lm.wheelEvent(ev)
    assert calls == [Direction.DOWN]
