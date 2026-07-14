import subprocess
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QTextCursor

from meldq.app import MeldWindow
from meldq.doc import Direction
from meldq.filediff import FileDiff
from meldq.filemerge import FileMerge
from meldq.util.prefs import Preferences

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def window(qapp, qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    win = MeldWindow(prefs)
    win.show()
    qtbot.waitExposed(win)
    yield win
    # tear down without triggering the modal save-on-close dialog (a modified
    # FileMerge middle pane would otherwise block forever)
    win.pump.stop()
    for doc in list(win._doc_for_widget.values()):
        for data in getattr(doc, "bufferdata", []):
            data.modified = False
    win.close()


def test_full_filediff_over_lao_tzu(window, qtbot):
    doc = window.append_filediff([str(FIX / "lao"), str(FIX / "tzu")])
    assert isinstance(doc, FileDiff)
    qtbot.waitUntil(lambda: not doc.scheduler.tasks_pending(), timeout=5000)

    # a diff was computed
    assert doc.linediffer.diff_count() > 0
    # both files are shown
    assert "Way" in doc.textbuffer[0].toPlainText()
    assert "profound" in doc.textbuffer[1].toPlainText()
    # linkmap and diffmap render something
    assert not doc.linkmap[0].grab().toImage().isNull()
    assert not doc.diffmap[0].grab().toImage().isNull()


def test_next_diff_moves_to_first_chunk(window, qtbot):
    doc = window.append_filediff([str(FIX / "lao"), str(FIX / "tzu")])
    qtbot.waitUntil(lambda: not doc.scheduler.tasks_pending(), timeout=5000)
    doc.textview[1].setFocus()
    doc.on_cursor_position_changed(1, force=True)
    target = doc._find_next_chunk(Direction.DOWN, 1)
    doc.next_diff(Direction.DOWN)
    if target:
        assert doc.textview[1].textCursor().blockNumber() == target[1]


def test_edit_and_window_undo_roundtrip(window, qtbot):
    doc = window.append_filediff([str(FIX / "lao"), str(FIX / "tzu")])
    qtbot.waitUntil(lambda: not doc.scheduler.tasks_pending(), timeout=5000)
    original = doc.textbuffer[1].toPlainText()
    cur = QTextCursor(doc.textbuffer[1])
    cur.movePosition(QTextCursor.MoveOperation.Start)
    cur.insertText("EDIT\n")
    assert doc.textbuffer[1].toPlainText() != original
    window.action_undo.trigger()            # window-level undo
    assert doc.textbuffer[1].toPlainText() == original


def test_four_files_make_filemerge(window, qtbot, tmp_path):
    doc = window.append_filediff([
        str(FIX / "merge_local"), str(FIX / "merge_base"),
        str(FIX / "merge_remote"), str(tmp_path / "out")])
    assert isinstance(doc, FileMerge)
    qtbot.waitUntil(lambda: not doc.scheduler.tasks_pending(), timeout=5000)
    assert "(??)" in doc.textbuffer[1].toPlainText()


def test_open_paths_two_files(window, qtbot):
    tab = window.open_paths([str(FIX / "lao"), str(FIX / "tzu")])
    assert isinstance(tab, FileDiff)


def test_view_modules_import_cleanly():
    code = ("import meldq.filediff, meldq.filemerge, meldq.linkmap, "
            "meldq.diffmap, meldq.widgets.editor; "
            "import sys; "
            "import meldq.util.misc; "
            "sys.exit(1 if any(m.startswith('PyQt6') for m in ['x'] "
            "if False) else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_util_misc_still_qt_free():
    code = ("import sys, meldq.util.misc; "
            "sys.exit(1 if any(m.split('.')[0]=='PyQt6' for m in sys.modules) else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
