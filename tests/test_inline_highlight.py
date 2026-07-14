import pytest
from PyQt6.QtCore import QSettings

from meldq.filediff import FileDiff
from meldq.util.prefs import Preferences


@pytest.fixture
def make(qapp, tmp_path):
    def _make(left, right):
        prefs = Preferences(
            QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
        doc = FileDiff(prefs, 2)
        doc.set_num_panes(2)
        doc.textbuffer[0].setPlainText(left)
        doc.textbuffer[1].setPlainText(right)
        for _s in doc._diff_files([None, None], [left, right]):
            pass
        for _s in doc._update_highlighting():
            pass
        return doc
    return _make


def sels(doc, pane):
    return doc.textview[pane].extraSelections()


def test_single_replace_highlighted(make):
    doc = make("abcdef", "abcXef")
    # a 3-char equal prefix ("abc") is NOT absorbed (< 3 only), so the change
    # highlights exactly the differing character
    assert len(sels(doc, 0)) == 1
    assert len(sels(doc, 1)) == 1
    assert sels(doc, 0)[0].cursor.selectedText() == "d"
    assert sels(doc, 1)[0].cursor.selectedText() == "X"


def test_astral_offsets(make):
    # 𝕏 is one codepoint but two UTF-16 units. The 1-char equal prefix "a" is
    # absorbed by the back-heuristic, so the selection covers "a𝕏"/"aY"; the
    # point is the UTF-16 offsets don't drift — the astral char is fully
    # inside pane 0's selection (a codepoint-indexed port would truncate it).
    doc = make("a\U0001D54Fb", "aYb")
    assert sels(doc, 0)[0].cursor.selectedText() == "a\U0001D54F"
    assert sels(doc, 1)[0].cursor.selectedText() == "aY"


def test_large_chunk_bails_to_whole(make):
    left = "x" * 9000
    right = "y" * 9000
    doc = make(left, right)
    # over the 8000-unit limit: one selection covering the whole chunk
    assert len(sels(doc, 0)) == 1
    c0 = sels(doc, 0)[0].cursor
    assert c0.selectionEnd() - c0.selectionStart() == 9000


def test_identical_no_selection(make):
    doc = make("same\ntext", "same\ntext")
    assert sels(doc, 0) == []
    assert sels(doc, 1) == []
