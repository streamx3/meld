import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QFont

from meldq.filediff import FileDiff
from meldq.util.prefs import Preferences


@pytest.fixture
def doc(qapp, qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    d = FileDiff(prefs, 2)
    d.set_num_panes(2)
    for view in d.textview[:2]:
        view.set_font_and_tabs(QFont("Monospace", 10), 4)
    # pane 1 has a 20-line block inserted around line 50 of 200
    base = [f"line {i:03d}" for i in range(200)]
    left = base
    right = base[:50] + [f"inserted {j}" for j in range(20)] + base[50:]
    ltext, rtext = "\n".join(left), "\n".join(right)
    d.textbuffer[0].setPlainText(ltext)
    d.textbuffer[1].setPlainText(rtext)
    for _s in d._diff_files([None, None], [ltext, rtext]):
        pass
    d.widget.resize(600, 300)
    qtbot.addWidget(d.widget)
    d.widget.show()
    qtbot.waitExposed(d.widget)
    return d


def sb(doc, pane):
    return doc.textview[pane].verticalScrollBar()


def test_diff_present(doc):
    assert doc.linediffer.diff_count() == 1


def test_scroll_before_chunk_tracks_one_to_one(doc, qtbot):
    # content is identical before line 50: panes should track ~equally
    sb(doc, 0).setValue(10)
    qtbot.wait(10)
    assert abs(sb(doc, 1).value() - sb(doc, 0).value()) <= 1


def test_scroll_after_chunk_is_offset(doc, qtbot):
    # after the 20-line insertion in pane 1, pane 1 leads pane 0 by ~20 lines
    sb(doc, 0).setValue(sb(doc, 0).maximum())
    qtbot.wait(10)
    assert sb(doc, 1).value() > sb(doc, 0).value()
    assert abs((sb(doc, 1).value() - sb(doc, 0).value()) - 20) <= 3


def test_no_recursive_pingpong(doc, qtbot):
    counter = {"n": 0}
    sb(doc, 1).valueChanged.connect(lambda _v: counter.__setitem__("n", counter["n"] + 1))
    sb(doc, 0).setValue(80)
    qtbot.wait(20)
    # a single master change yields a bounded number of follower updates
    assert counter["n"] <= 2
    assert not doc._sync_vscroll_lock


def test_shift_disables_sync(doc, qtbot, monkeypatch):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication, "keyboardModifiers",
                        staticmethod(lambda: Qt.KeyboardModifier.ShiftModifier))
    before = sb(doc, 1).value()
    sb(doc, 0).setValue(120)
    qtbot.wait(10)
    assert sb(doc, 1).value() == before          # follower untouched


def test_hscroll_syncs(doc, qtbot):
    wide = "x" * 500 + "\n" + "y" * 500
    doc.textbuffer[0].setPlainText(wide)
    doc.textbuffer[1].setPlainText(wide)      # both panes equally wide
    qtbot.wait(10)
    hsb0 = doc.textview[0].horizontalScrollBar()
    hsb1 = doc.textview[1].horizontalScrollBar()
    assert hsb0.maximum() > 0
    hsb0.setValue(hsb0.maximum() // 2)
    qtbot.wait(10)
    assert hsb1.value() == hsb0.value()
