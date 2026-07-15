"""M1: FileDiffView 2-way rendering — MeldSciView + aligned engine integration.

Chunk backgrounds and inline highlights are read back through the same Scintilla
marker/indicator APIs the sciview tests use, so these assert the real rendering.
"""

import pytest

from meldq.views.filediff import FileDiffView
from meldq.widgets.sciview import (
    KIND_DELETE,
    KIND_INSERT,
    KIND_REPLACE,
)


@pytest.fixture
def fd(qapp, qtbot):
    view = FileDiffView(2)
    qtbot.addWidget(view)
    return view


def kinds(fd, pane, line):
    return fd.panes[pane].chunk_kinds_at(line)


def test_identical_files_no_chunks(fd):
    fd.set_texts(["a\nb\nc\n", "a\nb\nc\n"])
    for pane in (0, 1):
        for line in range(4):
            assert kinds(fd, pane, line) == []


def test_replace_marks_both_panes(fd):
    fd.set_texts(["one\ntwo\nthree\n", "one\nTWO\nthree\n"])
    assert KIND_REPLACE in kinds(fd, 0, 1)      # left line "two"
    assert KIND_REPLACE in kinds(fd, 1, 1)      # right line "TWO"
    assert kinds(fd, 0, 0) == []                # unchanged lines clean
    assert kinds(fd, 0, 2) == []


def test_insert_marks_right_only(fd):
    fd.set_texts(["a\nb\n", "a\nNEW\nb\n"])
    assert KIND_INSERT in kinds(fd, 1, 1)       # inserted "NEW" on the right
    # the left has no inserted line to mark
    assert all(KIND_INSERT not in kinds(fd, 0, ln) for ln in range(3))


def test_delete_marks_left_only(fd):
    fd.set_texts(["a\nGONE\nb\n", "a\nb\n"])
    assert KIND_DELETE in kinds(fd, 0, 1)       # deleted "GONE" on the left
    assert all(KIND_DELETE not in kinds(fd, 1, ln) for ln in range(3))


def test_inline_highlight_within_replace(fd):
    # "hello" -> "hallo": only the differing char span is inline-marked.
    fd.set_texts(["hello\n", "hallo\n"])
    left, right = fd.panes
    assert left.has_inline_at(0, 1)             # the 'e'/'a' position
    assert right.has_inline_at(0, 1)
    assert not left.has_inline_at(0, 4)         # shared 'l','o' not marked


def test_inline_skipped_for_unequal_height_replace(fd):
    # A replace whose sides differ in line count: skeleton keeps the block
    # background but adds no intra-line marks (M2 handles the joined region).
    fd.set_texts(["x\ny\n", "P\nQ\nR\n"])
    assert KIND_REPLACE in kinds(fd, 0, 0)
    assert KIND_REPLACE in kinds(fd, 1, 0)
    assert not fd.panes[0].has_inline_at(0, 0)


def test_rerender_clears_previous(fd):
    fd.set_texts(["one\ntwo\n", "one\nTWO\n"])
    assert KIND_REPLACE in kinds(fd, 0, 1)
    fd.set_texts(["same\n", "same\n"])          # now identical
    assert kinds(fd, 0, 0) == []


def test_language_set_from_path(fd, tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("x = 1\n")
    b.write_text("x = 2\n")
    fd.set_files([str(a), str(b)])
    from PyQt6.Qsci import QsciLexerPython
    assert isinstance(fd.panes[0].lexer(), QsciLexerPython)
    assert KIND_REPLACE in kinds(fd, 0, 0)


def test_sync_scroll_no_infinite_recursion(fd):
    fd.set_texts(["\n".join(str(i) for i in range(300)),
                  "\n".join(str(i) for i in range(300))])
    # Manually fire the sync path; the _syncing guard must prevent re-entry.
    fd.panes[0].scroll_to_line(120)
    fd._on_scrolled()                           # would loop if unguarded
    assert fd._syncing is False
