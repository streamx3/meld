from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from meldq.filemerge import FileMerge
from meldq.util.prefs import Preferences

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def merged(qapp, qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    doc = FileMerge(prefs, 3)
    output = tmp_path / "merged.out"
    doc.set_files([str(FIX / "merge_local"), str(FIX / "merge_base"),
                   str(FIX / "merge_remote"), str(output)])
    # drain the scheduled load -> merge -> diff pipeline
    guard = 0
    while doc.scheduler.tasks_pending() and guard < 10000:
        doc.scheduler.iteration()
        guard += 1
    return doc


def test_middle_pane_is_automerged(merged):
    text = merged.textbuffer[1].toPlainText()
    # clean changes applied from each side
    assert "LOCAL_A" in text
    assert "REMOTE_E" in text
    # the conflicting line 3 is marked
    assert "(??)" in text


def test_conflict_count_in_status(merged):
    status = merged._get_custom_status_text()
    assert "Conflicts: 1" in status
    assert merged.linediffer.get_unresolved_count() == 1


def test_outer_panes_read_only(merged):
    assert merged.textview[0].isReadOnly()
    assert merged.textview[2].isReadOnly()
    assert not merged.textview[1].isReadOnly()


def test_middle_pane_modified(merged):
    assert merged.bufferdata[1].modified


def test_ancestor_in_hidden_buffer(merged):
    # the ancestor text lives in the hidden document, not a visible pane
    assert merged.hidden_textbuffer.toPlainText().strip() != ""
    # and the hidden buffer is not registered with undo
    assert merged.hidden_textbuffer not in merged.undosequence._docs
