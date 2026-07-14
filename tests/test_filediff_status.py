import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QTextCursor

from meldq.filediff import FileDiff
from meldq.util.prefs import Preferences


@pytest.fixture
def doc(qapp, qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    d = FileDiff(prefs, 2)
    d.set_num_panes(2)
    qtbot.addWidget(d.widget)
    return d


def test_cursor_status_text(doc):
    doc.textbuffer[0].setPlainText("line one\nline two\nline three")
    messages = []
    doc.status_changed.connect(messages.append)
    cur = QTextCursor(doc.textbuffer[0])
    cur.setPosition(doc.textbuffer[0].findBlockByNumber(1).position() + 2)
    doc.textview[0].setTextCursor(cur)
    doc.on_cursor_position_changed(0, force=True)
    assert messages[-1] == "INS : Ln 2, Col 3"


def test_overwrite_toggle_shows_ovr(doc):
    doc.textbuffer[0].setPlainText("abc")
    messages = []
    doc.status_changed.connect(messages.append)
    doc._toggle_overwrite()
    assert doc.textview[0].overwriteMode()
    assert doc.textview[1].overwriteMode()
    doc.on_cursor_position_changed(0, force=True)
    assert messages[-1].startswith("OVR :")


def test_identical_files_banner(doc):
    same = "identical\ncontent"
    doc.textbuffer[0].setPlainText(same)
    doc.textbuffer[1].setPlainText(same)
    for _s in doc._diff_files([None, None], [same, same]):
        pass
    doc.on_diffs_changed()
    assert doc.msgarea_mgr[0].has_message()
    assert doc.msgarea_mgr[1].has_message()
    assert doc.msgarea_mgr[0].get_msg_id() == FileDiff.MSG_SAME


def test_banner_cleared_when_differ(doc):
    doc.textbuffer[0].setPlainText("same")
    doc.textbuffer[1].setPlainText("same")
    for _s in doc._diff_files([None, None], ["same", "same"]):
        pass
    doc.on_diffs_changed()
    assert doc.msgarea_mgr[0].has_message()
    # now make them differ and re-diff
    doc.textbuffer[1].setPlainText("different")
    for _s in doc._diff_files([None, None], ["same", "different"]):
        pass
    doc.on_diffs_changed()
    assert not doc.msgarea_mgr[0].has_message()


def test_escape_shortcut_hides_findbar(doc):
    from PyQt6.QtGui import QKeySequence, QShortcut
    doc.textview_focussed = doc.textview[0]
    doc.on_find_activate()
    assert doc.findbar.text_edit is doc.textview[0]
    escape = [s for s in doc.widget.findChildren(QShortcut)
              if s.key() == QKeySequence(Qt.Key.Key_Escape)]
    assert escape, "Escape shortcut not wired"
    escape[0].activated.emit()
    assert doc.findbar.text_edit is None      # hide() ran and reset the target


def test_custom_status_text_default(doc):
    assert doc._get_custom_status_text() == ""
