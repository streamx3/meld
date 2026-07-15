"""M2: 3-way FileDiffView via the Differ (pane 1 = base).

Panes are [left/mine, base, right/theirs]. Verifies per-pane change rendering,
conflict detection (both sides change the same base region), dual linkmaps, and
outer→base merge.
"""

import pytest

from meldq.views.filediff import FileDiffView
from meldq.widgets.sciview import KIND_CONFLICT, KIND_INSERT, KIND_REPLACE


@pytest.fixture
def fd3(qapp, qtbot):
    view = FileDiffView(3)
    view.resize(900, 400)
    qtbot.addWidget(view)
    view.show()
    return view


def kinds(fd, pane, line):
    return fd.panes[pane].chunk_kinds_at(line)


def test_construction(fd3):
    assert fd3.num_panes == 3
    assert len(fd3.panes) == 3
    assert len(fd3.linkmaps) == 2


def test_left_only_change(fd3):
    # left edits line 1; right == base.
    fd3.set_texts(["a\nL\nc\n", "a\nx\nc\n", "a\nx\nc\n"])
    assert KIND_REPLACE in kinds(fd3, 0, 1)     # left shows the change
    assert KIND_REPLACE in kinds(fd3, 1, 1)     # base shows it (vs left)
    assert kinds(fd3, 2, 1) == []               # right unchanged


def test_right_only_change(fd3):
    fd3.set_texts(["a\nx\nc\n", "a\nx\nc\n", "a\nR\nc\n"])
    assert kinds(fd3, 0, 1) == []
    assert KIND_REPLACE in kinds(fd3, 1, 1)
    assert KIND_REPLACE in kinds(fd3, 2, 1)


def test_conflict_both_sides_change_same_line(fd3):
    # left: x->L, right: x->R at the same base line -> CONFLICT on all three.
    fd3.set_texts(["a\nL\nc\n", "a\nx\nc\n", "a\nR\nc\n"])
    assert KIND_CONFLICT in kinds(fd3, 0, 1)
    assert KIND_CONFLICT in kinds(fd3, 1, 1)
    assert KIND_CONFLICT in kinds(fd3, 2, 1)


def test_non_conflicting_changes_on_different_lines(fd3):
    # left edits line 1, right edits line 3 -> two independent replaces, no conflict.
    fd3.set_texts(["a\nL\nc\nd\n", "a\nx\nc\nd\n", "a\nx\nc\nR\n"])
    assert KIND_REPLACE in kinds(fd3, 0, 1)     # left change
    assert KIND_CONFLICT not in kinds(fd3, 0, 1)
    assert KIND_REPLACE in kinds(fd3, 2, 3)     # right change
    assert KIND_CONFLICT not in kinds(fd3, 2, 3)


def test_insert_change_uses_change_color(fd3):
    # right adds a line; base/left don't -> "change" (green) not replace.
    fd3.set_texts(["a\nb\n", "a\nb\n", "a\nNEW\nb\n"])
    assert KIND_INSERT in kinds(fd3, 2, 1)      # inserted line on the right
    assert kinds(fd3, 0, 1) == []


def test_base_pane_has_no_merge_arrows(fd3):
    fd3.set_texts(["a\nL\nc\n", "a\nx\nc\n", "a\nR\nc\n"])
    assert fd3.panes[0].has_action_marker(1)    # outer panes get arrows
    assert fd3.panes[2].has_action_marker(1)
    assert not fd3.panes[1].has_action_marker(1)  # base does not


def test_merge_left_into_base(fd3):
    fd3.set_texts(["a\nL\nc\n", "a\nx\nc\n", "a\nx\nc\n"])
    fd3.panes[0].action_clicked.emit(1)         # click left's arrow
    assert fd3.panes[1].text() == "a\nL\nc\n"   # base took left's line


def test_merge_right_into_base(fd3):
    fd3.set_texts(["a\nx\nc\n", "a\nx\nc\n", "a\nR\nc\n"])
    fd3.panes[2].action_clicked.emit(1)
    assert fd3.panes[1].text() == "a\nR\nc\n"


def test_merge_conflict_take_left(fd3):
    fd3.set_texts(["a\nL\nc\n", "a\nx\nc\n", "a\nR\nc\n"])
    fd3.panes[0].action_clicked.emit(1)         # resolve by taking left
    assert fd3.panes[1].text() == "a\nL\nc\n"


def test_linkmap_pair_chunks(fd3):
    fd3.set_texts(["a\nL\nc\n", "a\nx\nc\n", "a\nR\nc\n"])
    left_side = fd3.pair_chunks(0)              # pane0 <-> base
    right_side = fd3.pair_chunks(1)             # base <-> pane2
    assert any(c[0] == "conflict" for c in left_side)
    assert any(c[0] == "conflict" for c in right_side)
    assert len(fd3.linkmaps[0].chunk_shapes()) == len(left_side)
    assert len(fd3.linkmaps[1].chunk_shapes()) == len(right_side)


def test_navigation_across_pane(fd3):
    fd3.set_texts(["a\nL\nc\nd\ne\n", "a\nx\nc\nd\ne\n", "a\nx\nc\nd\nZ\n"])
    fd3.panes[0].setCursorPosition(0, 0)
    assert fd3.next_diff(pane=0) == 1           # left's only change
    fd3.panes[2].setCursorPosition(0, 0)
    assert fd3.next_diff(pane=2) == 4           # right's change (line 4)


def test_paint_does_not_crash(fd3):
    fd3.set_texts(["a\nL\nc\n", "a\nx\nc\n", "a\nR\nc\n"])
    for lm in fd3.linkmaps:
        lm.grab()
