import pytest
from PyQt6.QtCore import QSettings

from meldq.doc import Direction
from meldq.filediff import FileDiff
from meldq.util.prefs import Preferences


def build(qtbot, tmp_path, left, right):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    doc = FileDiff(prefs, 2)
    doc.set_num_panes(2)
    doc.textbuffer[0].setPlainText(left)
    doc.textbuffer[1].setPlainText(right)
    for _s in doc._diff_files([None, None], [left, right]):
        pass
    return doc


@pytest.fixture
def lao_tzu(qapp, qtbot, tmp_path):
    from pathlib import Path
    fix = Path(__file__).parent / "fixtures"
    left = fix.joinpath("lao").read_text()
    right = fix.joinpath("tzu").read_text()
    return build(qtbot, tmp_path, left.rstrip("\n"), right.rstrip("\n"))


def test_diff_has_chunks(lao_tzu):
    assert lao_tzu.linediffer.diff_count() > 0


def test_replace_chunk_equalizes(qapp, qtbot, tmp_path):
    doc = build(qtbot, tmp_path, "a\nOLD\nc", "a\nNEW\nc")
    before = doc.linediffer.diff_count()
    assert before == 1
    chunk = doc.linediffer.get_chunk(0, 0, 1)   # pane0 -> pane1
    doc.replace_chunk(0, 1, chunk)
    for _s in doc._diff_files([None, None],
                              [doc.textbuffer[0].toPlainText(),
                               doc.textbuffer[1].toPlainText()]):
        pass
    assert doc.textbuffer[0].toPlainText() == doc.textbuffer[1].toPlainText()
    assert doc.linediffer.diff_count() == 0


def test_replace_is_single_undo(qapp, qtbot, tmp_path):
    doc = build(qtbot, tmp_path, "a\nOLD\nc", "a\nNEW\nc")
    original = doc.textbuffer[1].toPlainText()
    chunk = doc.linediffer.get_chunk(0, 0, 1)
    doc.replace_chunk(0, 1, chunk)
    assert doc.textbuffer[1].toPlainText() != original
    doc.undosequence.undo()
    assert doc.textbuffer[1].toPlainText() == original


def test_delete_chunk_at_eof_removes_preceding_newline(qapp, qtbot, tmp_path):
    # pane 0 has an extra trailing line vs pane 1
    doc = build(qtbot, tmp_path, "a\nb\nEXTRA", "a\nb")
    # the chunk covering EXTRA touches EOF in pane 0
    chunk = doc.linediffer.get_chunk(0, 0, 1)
    doc.delete_chunk(0, chunk)
    # deleting removes the newline before EXTRA, no trailing blank line
    assert doc.textbuffer[0].toPlainText() == "a\nb"


def test_copy_chunk_down(qapp, qtbot, tmp_path):
    doc = build(qtbot, tmp_path, "a\nX\nc", "a\nc")
    chunk = doc.linediffer.get_chunk(0, 0, 1)
    doc.copy_chunk(0, 1, chunk, copy_up=False)
    # X is inserted into pane 1
    assert "X" in doc.textbuffer[1].toPlainText()


def test_navigation_moves_cursor(lao_tzu):
    doc = lao_tzu
    doc.textview[1].setFocus()
    # cursor starts at line 0; next_diff jumps to the first chunk start
    doc.cursor.pane = 1
    doc.cursor.line = 0
    chunk, prev, nxt = doc.linediffer.locate_chunk(1, 0)
    doc.cursor.next_chunk = chunk if chunk is not None else nxt
    doc.next_diff(Direction.DOWN)
    target = doc._find_next_chunk(Direction.DOWN, 1)
    if target:
        assert doc.textview[1].textCursor().blockNumber() == target[1]


def test_sensitivity_push_directions(qapp, qtbot, tmp_path):
    doc = build(qtbot, tmp_path, "a\nLEFT\nc", "a\nRIGHT\nc")
    doc.textview[0].setFocus()
    doc.cursor.pane = 0
    doc.cursor.chunk = 0
    doc._on_current_diff_changed()
    # cursor in a chunk of pane 0 (2-pane): can push right, not left
    assert doc.action_push_right.isEnabled()
    assert not doc.action_push_left.isEnabled()
