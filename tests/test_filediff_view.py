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


def test_inline_across_unequal_height_replace(fd):
    # A replace whose sides differ in line count now gets intra-line marks via
    # the joined-region pass (the M1 skeleton skipped these).
    fd.set_texts(["x\ny\n", "P\nQ\nR\n"])
    assert KIND_REPLACE in kinds(fd, 0, 0)
    assert KIND_REPLACE in kinds(fd, 1, 0)
    assert fd.panes[0].has_inline_at(0, 0)      # 'x' differs from 'P'
    assert fd.panes[1].has_inline_at(0, 0)


def test_inline_multiline_region_marks_each_line(fd):
    # A 2-line replace where only the 2nd line's tail changes: the mark lands
    # on the right line, offset within it, not on the joining newline.
    fd.set_texts(["keep\nfoo bar\n", "keep\nfoo baz\n"])
    left, right = fd.panes
    assert left.has_inline_at(1, 6)             # 'r' vs 'z' at col 6
    assert right.has_inline_at(1, 6)
    assert not left.has_inline_at(1, 0)         # 'foo ba' shared
    assert not left.has_inline_at(0, 0)         # line 0 identical -> no mark


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


def test_map_line_aligns_across_insertion():
    # DOC5: influence-map mapping — a 20-line insertion at the top of the left
    # pane means left line 30 corresponds to right line 10, not right line 30.
    left = ["INS"] * 20 + ["common%d" % i for i in range(50)]
    right = ["common%d" % i for i in range(50)]
    # opcodes for this pair: an insert chunk (left 0..20 vs right 0..0).
    chunks = [(0, 20, 0, 0)]                     # (s1,s2,d1,d2) left->right
    assert FileDiffView._map_line(chunks, 30) == 10   # common10 aligns
    assert FileDiffView._map_line(chunks, 0) == 0     # inside the insert -> top
    assert FileDiffView._map_line(chunks, 25) == 5


def test_sync_scroll_aligns_content(fd, qtbot):
    left = "".join("INS\n" for _ in range(20)) + \
        "".join("common%d\n" % i for i in range(50))
    right = "".join("common%d\n" % i for i in range(50))
    fd.set_texts([left, right])
    fd.resize(700, 300)
    fd.show()
    qtbot.waitExposed(fd)
    fd.panes[0].scroll_to_line(30)              # left shows common10 at top
    fd.sender = lambda: fd.panes[0]             # stub the signal sender
    try:
        fd._on_scrolled()
    finally:
        del fd.sender
    lv, rv = fd.panes[0].first_visible_line(), fd.panes[1].first_visible_line()
    assert left.split("\n")[lv] == right.split("\n")[rv]   # same content aligned


# ----- M2: editing + live re-diff + merge -----------------------------------

def test_live_rediff_on_edit(fd):
    fd.set_texts(["one\ntwo\nthree\n", "one\ntwo\nthree\n"])
    assert kinds(fd, 0, 1) == []                # identical -> clean
    fd.panes[1].set_text("one\nCHANGED\nthree\n")   # edits fire textChanged
    assert KIND_REPLACE in kinds(fd, 0, 1)      # diff updated live
    assert KIND_REPLACE in kinds(fd, 1, 1)


def test_chunk_at_line(fd):
    fd.set_texts(["a\nOLD\nb\n", "a\nNEW\nb\n"])
    chunk = fd.chunk_at_line(0, 1)
    assert chunk is not None and chunk[0] == "replace"
    assert fd.chunk_at_line(0, 0) is None       # unchanged line


def test_copy_chunk_left_to_right(fd):
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    chunk = fd.chunk_at_line(0, 1)
    fd.copy_chunk(chunk, src_pane=0, dst_pane=1)
    assert fd.panes[1].text() == "a\nLEFT\nb\n"  # right now matches left
    for ln in range(3):                          # and the diff is now empty
        assert kinds(fd, 0, ln) == [] and kinds(fd, 1, ln) == []


def test_copy_chunk_right_to_left(fd):
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    chunk = fd.chunk_at_line(1, 1)
    fd.copy_chunk(chunk, src_pane=1, dst_pane=0)
    assert fd.panes[0].text() == "a\nRIGHT\nb\n"


def test_copy_insert_chunk_adds_lines(fd):
    fd.set_texts(["a\nb\n", "a\nX\nY\nb\n"])      # right has 2 inserted lines
    chunk = fd.chunk_at_line(1, 1)
    assert chunk[0] == "insert"
    fd.copy_chunk(chunk, src_pane=1, dst_pane=0)  # bring the insert into left
    assert fd.panes[0].text() == "a\nX\nY\nb\n"


def test_delete_chunk(fd):
    fd.set_texts(["a\nGONE\nb\n", "a\nb\n"])
    chunk = fd.chunk_at_line(0, 1)
    assert chunk[0] == "delete"
    fd.delete_chunk(chunk, pane=0)
    assert fd.panes[0].text() == "a\nb\n"         # deletion resolves the diff


def test_merge_is_undoable(fd):
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    chunk = fd.chunk_at_line(0, 1)
    fd.copy_chunk(chunk, src_pane=0, dst_pane=1)
    assert fd.panes[1].text() == "a\nLEFT\nb\n"
    fd.panes[1].undo()                            # native Scintilla undo
    assert fd.panes[1].text() == "a\nRIGHT\nb\n"  # merge reverted
    assert KIND_REPLACE in kinds(fd, 1, 1)        # and the diff re-renders


def test_merge_near_top_keeps_scroll_position(fd, qtbot):
    # M1: a merge near the top of a long file must NOT throw the view to EOF.
    n = 400
    left = "".join("L%d\n" % i for i in range(n))
    right = "".join(("CHG\n" if i == 5 else "L%d\n" % i) for i in range(n))
    fd.set_texts([left, right])
    fd.resize(700, 300)
    fd.show()
    qtbot.waitExposed(fd)
    for p in fd.panes:
        p.scroll_to_line(0)
    chunk = fd.chunk_at_line(0, 5)
    fd.copy_chunk(chunk, src_pane=0, dst_pane=1)
    assert fd.panes[1].text().split("\n")[5] == "L5"      # merge applied
    # The destination pane stays near the top, not scrolled to the bottom.
    assert fd.panes[1].first_visible_line() < 20


# ----- M2: encoding-aware load / save ---------------------------------------

def test_save_roundtrip_lf(fd, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"one\ntwo\n")
    b.write_bytes(b"one\n2\n")
    fd.set_files([str(a), str(b)])
    fd.save(0)
    assert a.read_bytes() == b"one\ntwo\n"        # unchanged content preserved


def test_save_preserves_crlf(fd, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"one\r\ntwo\r\n")              # CRLF file
    b.write_bytes(b"one\r\ntwo\r\n")
    fd.set_files([str(a), str(b)])
    fd.panes[0].set_text("one\nEDIT\n")           # buffer is LF-normalised...
    fd.save(0)
    assert a.read_bytes() == b"one\r\nEDIT\r\n"   # ...but CRLF restored on save


def test_save_preserves_latin1(fd, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"caf\xe9\n")                    # é in latin-1 (invalid utf-8)
    b.write_bytes(b"cafe\n")
    fd.set_files([str(a), str(b)])
    assert fd._encoding[0] == "latin-1"
    fd.save(0)
    assert a.read_bytes() == b"caf\xe9\n"          # byte-identical write-back


def test_save_no_final_newline(fd, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"x\ny")                          # no trailing newline
    b.write_bytes(b"x\ny\n")
    fd.set_files([str(a), str(b)])
    fd.save(0)
    assert a.read_bytes() == b"x\ny"                # still no trailing newline


def test_modified_tracking(fd, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"a\nb\n")
    b.write_bytes(b"a\nc\n")
    fd.set_files([str(a), str(b)])
    assert not fd.is_modified(0)                    # fresh load is clean
    fd.panes[0].set_text("a\nEDITED\n")
    assert fd.is_modified(0)
    fd.save(0)
    assert not fd.is_modified(0)                    # save clears the flag


def test_merge_then_save(fd, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"k\nLEFT\nm\n")
    b.write_bytes(b"k\nRIGHT\nm\n")
    fd.set_files([str(a), str(b)])
    fd.copy_chunk(fd.chunk_at_line(0, 1), src_pane=0, dst_pane=1)
    fd.save(1)
    assert b.read_bytes() == b"k\nLEFT\nm\n"        # merged result persisted


# ----- M2: ActionGutter (clickable merge arrows) ----------------------------

def test_action_markers_on_chunk_first_lines(fd):
    fd.set_texts(["a\nOLD\nb\n", "a\nNEW\nb\n"])
    assert fd.panes[0].has_action_marker(1)         # replace -> both panes
    assert fd.panes[1].has_action_marker(1)
    assert not fd.panes[0].has_action_marker(0)     # unchanged line: no arrow


def test_action_markers_delete_left_only(fd):
    fd.set_texts(["a\nGONE\nb\n", "a\nb\n"])
    assert fd.panes[0].has_action_marker(1)         # left has the deleted line
    assert not fd.panes[1].has_action_marker(1)     # right side is zero-width


def test_action_markers_insert_right_only(fd):
    fd.set_texts(["a\nb\n", "a\nX\nb\n"])
    assert fd.panes[1].has_action_marker(1)
    assert not fd.panes[0].has_action_marker(1)


def test_click_left_arrow_sends_right(fd):
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    fd.panes[0].action_clicked.emit(1)              # click left pane's arrow
    assert fd.panes[1].text() == "a\nLEFT\nb\n"     # right now matches left


def test_click_right_arrow_sends_left(fd):
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    fd.panes[1].action_clicked.emit(1)
    assert fd.panes[0].text() == "a\nRIGHT\nb\n"


def test_click_insert_arrow_pulls_into_left(fd):
    fd.set_texts(["a\nb\n", "a\nX\nY\nb\n"])
    fd.panes[1].action_clicked.emit(1)              # right's inserted block
    assert fd.panes[0].text() == "a\nX\nY\nb\n"


def test_action_markers_cleared_after_merge(fd):
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    fd.panes[0].action_clicked.emit(1)
    assert not fd.panes[0].has_action_marker(1)     # diff resolved -> no arrows
    assert not fd.panes[1].has_action_marker(1)


def test_click_empty_margin_is_noop(fd):
    # M2: an insert chunk draws an arrow only on the right (zero-width on left).
    # Clicking the LEFT margin at that line (no arrow) must NOT merge — it used
    # to match the zero-width chunk and delete the right pane's added lines.
    fd.set_texts(["a\nb\n", "a\nX\nY\nb\n"])
    assert not fd.panes[0].has_action_marker(1)
    fd.panes[0].action_clicked.emit(1)              # click the empty left margin
    assert fd.panes[1].text() == "a\nX\nY\nb\n"     # right pane untouched


def test_reject_mode_restores_original_into_patched_pane(fd):
    # M6: patch-review layout (left read-only original, right editable patched).
    # A gutter click rejects the hunk: restores the original into the right pane,
    # never writes the read-only left pane.
    original = "a\nb\nc\nd\ne\n"
    patched = "a\nBEE\nc\nd\nEEE\n"        # two separated changes: b->BEE, e->EEE
    fd.set_texts([original, patched])
    fd.panes[0].setReadOnly(True)
    assert fd._is_reject_mode()
    # reject the first change (line 1): only that chunk reverts, not the whole file
    fd.panes[1].action_clicked.emit(1)
    assert fd.panes[1].text() == "a\nb\nc\nd\nEEE\n"   # b restored, EEE kept
    assert fd.panes[0].text() == original             # original untouched


def test_reject_mode_removes_an_inserted_hunk(fd):
    fd.set_texts(["a\nb\n", "a\nINS\nb\n"])            # patch inserted INS
    fd.panes[0].setReadOnly(True)
    # the insert arrow sits on the patched (right) pane
    line = next(ln for ln in range(3) if fd.panes[1].has_action_marker(ln))
    fd.panes[1].action_clicked.emit(line)
    assert fd.panes[1].text() == "a\nb\n"             # inserted hunk rejected


def test_click_empty_margin_unchanged_line_is_noop(fd):
    fd.set_texts(["a\nOLD\nb\n", "a\nNEW\nb\n"])
    before = (fd.panes[0].text(), fd.panes[1].text())
    fd.panes[0].action_clicked.emit(0)              # an unchanged line
    assert (fd.panes[0].text(), fd.panes[1].text()) == before


def test_view_undo_reverts_merge_regardless_of_focus(fd):
    # M3: a merge edits the OTHER pane; view-level undo must revert it even
    # though the source pane holds focus (shell routes Ctrl+Z here).
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    fd.panes[0].action_clicked.emit(1)              # merge left -> right pane 1
    assert fd.panes[1].text() == "a\nLEFT\nb\n"
    fd.panes[0].setFocus()                          # focus on the SOURCE pane
    fd.undo()
    assert fd.panes[1].text() == "a\nRIGHT\nb\n"    # merge reverted
    fd.redo()
    assert fd.panes[1].text() == "a\nLEFT\nb\n"     # and redoable


# ----- M2: next/previous change navigation ----------------------------------

def test_next_diff_walks_chunks(fd):
    # changes at lines 1 and 4 on the left
    fd.set_texts(["a\nX\nb\nc\nY\nd\n", "a\n1\nb\nc\n2\nd\n"])
    fd.panes[0].setCursorPosition(0, 0)
    assert fd.next_diff(pane=0) == 1                # first change
    assert fd.next_diff(pane=0) == 4                # second change
    assert fd.next_diff(pane=0) is None             # no more below


def test_prev_diff_walks_back(fd):
    fd.set_texts(["a\nX\nb\nc\nY\nd\n", "a\n1\nb\nc\n2\nd\n"])
    fd.panes[0].setCursorPosition(5, 0)
    assert fd.prev_diff(pane=0) == 4
    assert fd.prev_diff(pane=0) == 1
    assert fd.prev_diff(pane=0) is None


def test_next_diff_moves_cursor(fd):
    fd.set_texts(["a\nb\nCHANGED\nd\n", "a\nb\ndifferent\nd\n"])
    fd.panes[0].setCursorPosition(0, 0)
    fd.next_diff(pane=0)
    assert fd.panes[0].getCursorPosition()[0] == 2   # cursor jumped to the chunk


def test_next_diff_none_when_identical(fd):
    fd.set_texts(["a\nb\n", "a\nb\n"])
    fd.panes[0].setCursorPosition(0, 0)
    assert fd.next_diff(pane=0) is None


def test_large_file_edit_debounces_rediff(fd, qtbot):
    # PF: on a large document a live edit schedules a coalesced re-diff via the
    # timer rather than running the full diff synchronously per keystroke.
    n = 3000
    text = "".join("line %d\n" % i for i in range(n))
    fd.set_texts([text, text])
    assert fd.panes[0].lines() > fd._LIVE_REDIFF_SYNC_MAX
    fd.panes[0].append("x\n")                      # a user edit
    assert fd._rediff_timer.isActive()             # debounced, not synchronous
    qtbot.wait(250)                                # let the timer fire
    assert not fd._rediff_timer.isActive()


def test_small_file_rediff_is_synchronous(fd):
    fd.set_texts(["a\nb\n", "a\nb\n"])
    fd.panes[0].append("c\n")
    assert not fd._rediff_timer.isActive()         # small file: immediate


def test_shift_click_pulls_other_side_into_clicked_pane(fd):
    # 2-way reverse merge: Shift+click pulls the OTHER pane's version in.
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    fd.panes[0].action_shift_clicked.emit(1)
    assert fd.panes[0].text() == "a\nRIGHT\nb\n"     # left took right's line
    assert fd.panes[1].text() == "a\nRIGHT\nb\n"     # right untouched


def test_cooperative_rediff_completes_and_renders(fd, qtbot):
    # PF2: a large-file re-diff runs cooperatively (yields across event-loop
    # slices) and still renders the change.
    fd._COOP_SLICE_S = -1                    # force a yield after every step
    left = "".join("line %d\n" % i for i in range(2500))
    right = left.replace("line 100\n", "CHANGED\n", 1)
    fd.set_texts([left, right])
    assert fd._coop_gen is not None          # deferred, not run all at once
    qtbot.waitUntil(lambda: fd._coop_gen is None, timeout=10000)
    assert fd.panes[0].chunk_kinds_at(100)   # the change rendered


def test_opcodes_cache_invalidated_on_edit(fd):
    fd.set_texts(["a\nb\n", "a\nB\n"])
    first = fd.opcodes()
    assert fd.opcodes() is first             # cached (same object)
    fd.panes[1].set_text("a\nb\n")           # now identical -> cache invalidated
    assert fd.opcodes() != first
    assert fd.opcodes() == []                # no differences


def test_push_change_keyboard_2way(fd):
    # Alt+Right from the left pane pushes the chunk under the cursor rightward.
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    fd.panes[0].setCursorPosition(1, 0)
    fd.push_change(+1, pane=0)
    assert fd.panes[1].text() == "a\nLEFT\nb\n"
    # Pushing off the edge is a no-op.
    before = fd.panes[0].text()
    fd.push_change(-1, pane=0)
    assert fd.panes[0].text() == before
