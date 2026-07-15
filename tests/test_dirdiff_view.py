"""M3: DirDiffView tree — populated from the dircompare core."""

import pytest

from meldq.dircompare import (
    STATE_MISSING,
    STATE_MODIFIED,
    STATE_NEW,
    STATE_NORMAL,
)
from meldq.views.dirdiff import ROLE_REL, DirDiffView


def write(path, data=b"x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def dd(qapp, qtbot):
    view = DirDiffView(2)
    view.resize(700, 400)
    qtbot.addWidget(view)
    return view


def top_rows(view):
    """{name: index} for the top-level rows (pane 0 column)."""
    model = view.model
    out = {}
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        # a row's name is whichever pane has it; read the rel role
        rel = view.row_relpath(idx)
        out[rel] = idx
    return out


def test_top_level_states(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "same.txt", b"a\n")
    write(right / "same.txt", b"a\n")
    write(left / "diff.txt", b"a\n")
    write(right / "diff.txt", b"b\n")
    write(left / "onlyleft.txt", b"a\n")
    write(right / "onlyright.txt", b"a\n")
    dd.set_roots([str(left), str(right)])

    rows = top_rows(dd)
    assert set(rows) == {"same.txt", "diff.txt", "onlyleft.txt", "onlyright.txt"}
    assert dd.row_state(rows["same.txt"], 0) == STATE_NORMAL
    assert dd.row_state(rows["diff.txt"], 0) == STATE_MODIFIED
    assert dd.row_state(rows["onlyleft.txt"], 0) == STATE_NEW
    assert dd.row_state(rows["onlyleft.txt"], 1) == STATE_MISSING


def test_missing_cell_is_blank(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "onlyleft.txt", b"a\n")
    right.mkdir()
    dd.set_roots([str(left), str(right)])
    idx = top_rows(dd)["onlyleft.txt"]
    left_item = dd.model.itemFromIndex(idx.siblingAtColumn(0))
    right_item = dd.model.itemFromIndex(idx.siblingAtColumn(1))
    assert left_item.text() == "onlyleft.txt"
    assert right_item.text() == ""          # absent on the right


def test_subdir_nested_rows(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "sub" / "nested.txt", b"1\n")
    write(right / "sub" / "nested.txt", b"2\n")
    dd.set_roots([str(left), str(right)])

    sub = top_rows(dd)["sub"]
    assert dd.model.hasChildren(sub)
    child = dd.model.index(0, 0, sub)
    assert dd.row_relpath(child).endswith("nested.txt")
    assert dd.row_state(child, 0) == STATE_MODIFIED


def test_expands_to_reveal_difference(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "sub" / "nested.txt", b"1\n")
    write(right / "sub" / "nested.txt", b"2\n")
    dd.set_roots([str(left), str(right)])
    sub = top_rows(dd)["sub"]
    assert dd.tree.isExpanded(sub)          # ancestor of the differing file


def test_refresh_reflects_changes(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "f.txt", b"a\n")
    write(right / "f.txt", b"a\n")
    dd.set_roots([str(left), str(right)])
    assert dd.row_state(top_rows(dd)["f.txt"], 0) == STATE_NORMAL
    (right / "f.txt").write_bytes(b"changed\n")
    dd.refresh()
    assert dd.row_state(top_rows(dd)["f.txt"], 0) == STATE_MODIFIED


def test_name_filter_applied(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "keep.txt", b"a\n")
    write(right / "keep.txt", b"a\n")
    write(left / "junk.bak", b"a\n")
    write(right / "junk.bak", b"a\n")
    dd.name_filters = [lambda n: not n.endswith(".bak")]
    dd.set_roots([str(left), str(right)])
    assert set(top_rows(dd)) == {"keep.txt"}


def test_activate_file_emits_create_diff(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "same.txt", b"a\n")
    write(right / "same.txt", b"a\n")
    dd.set_roots([str(left), str(right)])
    got = []
    dd.create_diff.connect(got.append)
    dd.on_activated(top_rows(dd)["same.txt"])
    assert len(got) == 1
    assert len(got[0]) == 2
    assert all(p.endswith("same.txt") for p in got[0])


def test_activate_file_only_one_side(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "onlyleft.txt", b"a\n")
    right.mkdir()
    dd.set_roots([str(left), str(right)])
    got = []
    dd.create_diff.connect(got.append)
    dd.on_activated(top_rows(dd)["onlyleft.txt"])
    assert got == [[str(left / "onlyleft.txt")]]     # only the existing file


def test_activate_dir_toggles_expand(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "sub" / "a.txt", b"1\n")
    write(right / "sub" / "a.txt", b"1\n")           # identical -> not auto-expanded
    dd.set_roots([str(left), str(right)])
    sub = top_rows(dd)["sub"]
    assert not dd.tree.isExpanded(sub)
    dd.on_activated(sub)
    assert dd.tree.isExpanded(sub)
    dd.on_activated(sub)
    assert not dd.tree.isExpanded(sub)


def test_copy_to_right_resolves_diff(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "onlyleft.txt", b"a\n")
    right.mkdir()
    dd.set_roots([str(left), str(right)])
    dd.copy_to(top_rows(dd)["onlyleft.txt"], 0, 1)
    assert (right / "onlyleft.txt").read_bytes() == b"a\n"
    assert dd.row_state(top_rows(dd)["onlyleft.txt"], 0) == STATE_NORMAL


def test_copy_to_left_overwrites(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "f.txt", b"OLD\n")
    write(right / "f.txt", b"NEW\n")
    dd.set_roots([str(left), str(right)])
    dd.copy_to(top_rows(dd)["f.txt"], 1, 0)           # right -> left
    assert (left / "f.txt").read_bytes() == b"NEW\n"


def test_delete_removes_and_updates(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "f.txt", b"a\n")
    write(right / "f.txt", b"a\n")
    dd.set_roots([str(left), str(right)])
    dd.delete(top_rows(dd)["f.txt"], 0, to_trash=False)  # hard-delete for the test
    assert not (left / "f.txt").exists()
    assert dd.row_state(top_rows(dd)["f.txt"], 0) == STATE_MISSING


def test_state_filter_hides_same(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "same.txt", b"a\n")
    write(right / "same.txt", b"a\n")
    write(left / "diff.txt", b"a\n")
    write(right / "diff.txt", b"b\n")
    dd.set_roots([str(left), str(right)])
    assert set(top_rows(dd)) == {"same.txt", "diff.txt"}
    dd.set_state_filters({STATE_MODIFIED, STATE_NEW})    # drop "same" (NORMAL)
    assert set(top_rows(dd)) == {"diff.txt"}


def test_state_filter_keeps_ancestor_dirs(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "sub" / "same.txt", b"a\n")
    write(right / "sub" / "same.txt", b"a\n")
    write(left / "sub" / "diff.txt", b"a\n")
    write(right / "sub" / "diff.txt", b"b\n")
    dd.set_roots([str(left), str(right)])
    dd.set_state_filters({STATE_MODIFIED})               # only the changed file
    rows = top_rows(dd)
    assert "sub" in rows                                 # ancestor dir kept
    sub = rows["sub"]
    kids = [dd.row_relpath(dd.model.index(r, 0, sub))
            for r in range(dd.model.rowCount(sub))]
    assert all(k.endswith("diff.txt") for k in kids)     # same.txt hidden


def test_refresh_preserves_expansion(dd, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "sub" / "a.txt", b"1\n")
    write(right / "sub" / "a.txt", b"1\n")               # identical: not auto-expanded
    dd.set_roots([str(left), str(right)])
    sub = top_rows(dd)["sub"]
    dd.tree.expand(sub)                                  # user expands it
    assert dd.tree.isExpanded(sub)
    dd.refresh()
    assert dd.tree.isExpanded(top_rows(dd)["sub"])       # still expanded after re-scan


def test_three_way(qapp, qtbot, tmp_path):
    view = DirDiffView(3)
    qtbot.addWidget(view)
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    write(a / "f.txt", b"1\n")
    write(b / "f.txt", b"1\n")
    write(c / "f.txt", b"2\n")
    view.set_roots([str(a), str(b), str(c)])
    assert view.model.columnCount() == 3
    idx = view.model.index(0, 0)
    assert view.row_state(idx, 2) == STATE_MODIFIED
