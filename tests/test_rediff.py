import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QTextCursor

from meldq.filediff import FileDiff
from meldq.util.prefs import Preferences


@pytest.fixture
def diffed(qapp, tmp_path):
    """A 2-pane FileDiff with content loaded and diffed, handlers connected."""
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    doc = FileDiff(prefs, 2)
    doc.set_num_panes(2)
    left = "\n".join(f"line {i}" for i in range(10))
    right = "\n".join(f"line {i}" for i in range(10))
    doc.textbuffer[0].setPlainText(left)
    doc.textbuffer[1].setPlainText(right)
    panetext = [left, right]
    for _step in doc._diff_files([None, None], panetext):
        pass
    # _diff_files already connected the buffer handlers at its end
    return doc


def test_identical_no_chunks(diffed):
    assert diffed.linediffer.diff_count() == 0


def test_insert_line_calls_change_sequence(diffed, monkeypatch):
    calls = []
    orig = diffed.linediffer.change_sequence
    monkeypatch.setattr(diffed.linediffer, "change_sequence",
                        lambda *a: (calls.append(a), orig(*a))[1])
    # insert a differing line into pane 0 at line 3
    cur = QTextCursor(diffed.textbuffer[0])
    cur.setPosition(diffed.textbuffer[0].findBlockByNumber(3).position())
    cur.insertText("BRAND NEW LINE\n")
    assert len(calls) == 1
    pane, startline, sizechange, _texts = calls[0]
    assert pane == 0
    assert startline == 3
    assert sizechange == 1
    assert diffed.linediffer.diff_count() > 0


def test_delete_lines_negative_sizechange(diffed, monkeypatch):
    calls = []
    orig = diffed.linediffer.change_sequence
    monkeypatch.setattr(diffed.linediffer, "change_sequence",
                        lambda *a: (calls.append(a), orig(*a))[1])
    doc0 = diffed.textbuffer[0]
    cur = QTextCursor(doc0)
    cur.setPosition(doc0.findBlockByNumber(2).position())
    cur.setPosition(doc0.findBlockByNumber(5).position(), QTextCursor.MoveMode.KeepAnchor)
    cur.removeSelectedText()          # deletes 3 lines
    assert calls[-1][2] == -3         # sizechange


def test_edit_reschedules_highlighting(diffed, monkeypatch):
    added = []
    monkeypatch.setattr(diffed.scheduler, "add_task",
                        lambda task, *a, **k: added.append(task))
    cur = QTextCursor(diffed.textbuffer[1])
    cur.setPosition(diffed.textbuffer[1].findBlockByNumber(1).position())
    cur.insertText("x")
    assert added                      # _update_highlighting rescheduled
