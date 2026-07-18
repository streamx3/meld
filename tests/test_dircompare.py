"""M3: Qt-free directory-comparison core (meldq.dircompare)."""

import re

import pytest

from meldq.dircompare import (
    STATE_ERROR,
    STATE_MISSING,
    STATE_MODIFIED,
    STATE_NEW,
    STATE_NOCHANGE,
    STATE_NORMAL,
    entry_states,
    files_same,
    walk,
)


def write(path, data=b"x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


# ----- files_same -----------------------------------------------------------

def test_files_same_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, b"hello\n")
    write(b, b"hello\n")
    assert files_same([str(a), str(b)]) == 1


def test_files_same_different(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, b"hello\n")
    write(b, b"world\n")
    assert files_same([str(a), str(b)]) == 0


def test_files_same_different_sizes_shortcuts(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, b"short\n")
    write(b, b"much longer content\n")
    assert files_same([str(a), str(b)]) == 0


def test_files_same_after_filter(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, b"code\n")
    write(b, b"code#comment\n")
    assert files_same([str(a), str(b)], [re.compile(r"#.*")]) == 2


def test_files_same_binary_safe(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, b"\x00\x01\xff")
    write(b, b"\x00\x01\xff")
    assert files_same([str(a), str(b)]) == 1


def test_files_same_all_dirs(tmp_path):
    (tmp_path / "d1").mkdir()
    (tmp_path / "d2").mkdir()
    assert files_same([str(tmp_path / "d1"), str(tmp_path / "d2")]) == 1


def test_files_same_file_dir_mix(tmp_path):
    write(tmp_path / "a")
    (tmp_path / "b").mkdir()
    assert files_same([str(tmp_path / "a"), str(tmp_path / "b")]) == 0


# ----- entry_states ---------------------------------------------------------

def test_entry_states_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, b"x\n")
    write(b, b"x\n")
    states, diff = entry_states([str(a), str(b)])
    assert states == [STATE_NORMAL, STATE_NORMAL]
    assert diff is False


def test_entry_states_modified(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, b"x\n")
    write(b, b"y\n")
    states, diff = entry_states([str(a), str(b)])
    assert states == [STATE_MODIFIED, STATE_MODIFIED]
    assert diff is True


def test_entry_states_only_left(tmp_path):
    a = tmp_path / "a"
    write(a, b"x\n")
    states, diff = entry_states([str(a), str(tmp_path / "missing")])
    assert states == [STATE_NEW, STATE_MISSING]
    assert diff is True


def test_entry_states_nochange_after_filter(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, b"code\n")
    write(b, b"code#c\n")
    states, _ = entry_states([str(a), str(b)], [re.compile(r"#.*")])
    assert states == [STATE_NOCHANGE, STATE_NOCHANGE]


# ----- walk -----------------------------------------------------------------

def test_walk_top_level_states(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "same.txt", b"a\n")
    write(right / "same.txt", b"a\n")
    write(left / "diff.txt", b"a\n")
    write(right / "diff.txt", b"b\n")
    write(left / "onlyleft.txt", b"a\n")
    write(right / "onlyright.txt", b"a\n")

    by_name = {e.name: e for e in walk([str(left), str(right)])}
    assert set(by_name) == {"same.txt", "diff.txt", "onlyleft.txt", "onlyright.txt"}
    assert by_name["same.txt"].states == [STATE_NORMAL, STATE_NORMAL]
    assert by_name["diff.txt"].states == [STATE_MODIFIED, STATE_MODIFIED]
    assert by_name["onlyleft.txt"].states == [STATE_NEW, STATE_MISSING]
    assert by_name["onlyright.txt"].states == [STATE_MISSING, STATE_NEW]


def test_walk_recurses_subdirs(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "sub" / "nested.txt", b"1\n")
    write(right / "sub" / "nested.txt", b"2\n")

    entries = list(walk([str(left), str(right)]))
    by_rel = {e.relpath: e for e in entries}
    assert "sub" in by_rel and by_rel["sub"].isdir
    nested_rel = "sub/nested.txt" if "sub/nested.txt" in by_rel else \
        [r for r in by_rel if r.endswith("nested.txt")][0]
    assert by_rel[nested_rel].states == [STATE_MODIFIED, STATE_MODIFIED]
    # parents come before children (breadth-first)
    assert entries.index(by_rel["sub"]) < entries.index(by_rel[nested_rel])


def test_walk_name_filter(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "keep.txt", b"a\n")
    write(right / "keep.txt", b"a\n")
    write(left / "skip.bak", b"a\n")
    write(right / "skip.bak", b"a\n")

    keep_no_bak = lambda n: not n.endswith(".bak")
    names = {e.name for e in walk([str(left), str(right)], [keep_no_bak])}
    assert names == {"keep.txt"}


def test_walk_three_way(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    write(a / "f.txt", b"1\n")
    write(b / "f.txt", b"1\n")
    write(c / "f.txt", b"2\n")     # differs in the third
    entry = next(e for e in walk([str(a), str(b), str(c)]) if e.name == "f.txt")
    assert entry.states == [STATE_MODIFIED] * 3
    assert entry.different is True


# ---------------------------------------------------------------------------
# D4: directory symlink cycles terminate instead of exploding
# ---------------------------------------------------------------------------

def test_walk_symlink_cycle_terminates(tmp_path):
    import os
    left, right = tmp_path / "l", tmp_path / "r"
    (left / "sub").mkdir(parents=True)
    (right / "sub").mkdir(parents=True)
    (left / "sub" / "a.txt").write_bytes(b"1\n")
    (right / "sub" / "a.txt").write_bytes(b"1\n")
    # a loop: sub/back points at its own parent tree
    os.symlink(left, left / "sub" / "back")
    os.symlink(right, right / "sub" / "back")
    entries = list(walk([str(left), str(right)]))     # must not hang/explode
    rels = [e.relpath for e in entries]
    # the loop link appears once as an entry, but is not descended into forever
    assert any(r.endswith("back") for r in rels)
    assert len(entries) < 50
    # every relpath is unique (no phantom replicated subtrees)
    assert len(rels) == len(set(rels))


# ---------------------------------------------------------------------------
# D3: an unreadable directory is flagged ERROR, not reported identical
# ---------------------------------------------------------------------------

def test_unreadable_dir_is_error_not_identical(tmp_path):
    import os
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")
    left, right = tmp_path / "l", tmp_path / "r"
    (left / "secret").mkdir(parents=True)
    (right / "secret").mkdir(parents=True)
    (left / "secret" / "inner.txt").write_bytes(b"x\n")
    (right / "secret" / "inner.txt").write_bytes(b"x\n")
    os.chmod(left / "secret", 0)
    try:
        entries = {e.relpath: e for e in walk([str(left), str(right)])}
        assert STATE_ERROR in entries["secret"].states     # visible error
        assert entries["secret"].different                 # not filtered as same
        assert "secret/inner.txt" not in entries           # not descended/misclassified
    finally:
        os.chmod(left / "secret", 0o755)
