"""T5.5 (state computation) + T5.6 (recursive scan) for meldq.dirdiff.

The scan runs on the cooperative scheduler; tests drain it synchronously with
``scheduler.complete_tasks()`` instead of pumping a real event loop.
"""

import os
import re

import pytest
from PyQt6.QtCore import QSettings

from meldq import dirdiff
from meldq.util.prefs import Preferences
from meldq.widgets.treemodel import (
    STATE_MISSING,
    STATE_MODIFIED,
    STATE_NEW,
    STATE_NOCHANGE,
    STATE_NORMAL,
)


@pytest.fixture
def make_doc(qapp, qtbot, tmp_path):
    def _make(panes=2):
        prefs = Preferences(QSettings(str(tmp_path / "p.ini"),
                                      QSettings.Format.IniFormat))
        d = dirdiff.DirDiff(prefs, panes)
        qtbot.addWidget(d.widget)
        return d
    return _make


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def child_map(doc, parent, pane=0):
    """basename (in `pane`'s column) -> child index, for every child row."""
    model = doc.model
    out = {}
    for row in range(model.rowCount(parent)):
        idx = model.index(row, 0, parent)
        path = model.value_path(idx, pane)
        out[os.path.basename(path) if path else None] = idx
    return out


def scan(doc, locations):
    doc.set_locations([str(loc) for loc in locations])
    doc.scheduler.complete_tasks()


# ---------------------------------------------------------------------------
# T5.6 — the scan actually populates the tree (map-no-op regression)
# ---------------------------------------------------------------------------

def test_scan_populates_top_level(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "same.txt", "hello\n")
    write(right / "same.txt", "hello\n")
    write(left / "diff.txt", "aaa\n")
    write(right / "diff.txt", "bbb\n")
    write(left / "onlyleft.txt", "x\n")
    write(right / "onlyright.txt", "y\n")

    doc = make_doc(2)
    scan(doc, [left, right])

    root = doc.model.index(0, 0)
    kids = child_map(doc, root)
    # Every entry from either side shows up exactly once (the 1.4 map()-for-
    # side-effect no-op would add zero rows under py3).
    assert set(kids) == {"same.txt", "diff.txt", "onlyleft.txt",
                         "onlyright.txt"}


def test_scan_states(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "same.txt", "hello\n")
    write(right / "same.txt", "hello\n")
    write(left / "diff.txt", "aaa\n")
    write(right / "diff.txt", "bbb\n")
    write(left / "onlyleft.txt", "x\n")
    write(right / "onlyright.txt", "y\n")

    doc = make_doc(2)
    scan(doc, [left, right])
    kids = child_map(doc, doc.model.index(0, 0))

    # identical -> NORMAL both panes
    assert doc.model.get_state(kids["same.txt"], 0) == STATE_NORMAL
    assert doc.model.get_state(kids["same.txt"], 1) == STATE_NORMAL
    # differing content -> MODIFIED both panes
    assert doc.model.get_state(kids["diff.txt"], 0) == STATE_MODIFIED
    assert doc.model.get_state(kids["diff.txt"], 1) == STATE_MODIFIED
    # present one side only -> NEW where present, MISSING where absent
    assert doc.model.get_state(kids["onlyleft.txt"], 0) == STATE_NEW
    assert doc.model.get_state(kids["onlyleft.txt"], 1) == STATE_MISSING
    assert doc.model.get_state(kids["onlyright.txt"], 0) == STATE_MISSING
    assert doc.model.get_state(kids["onlyright.txt"], 1) == STATE_NEW


def test_scan_recurses_subdirectories(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "sub" / "nested.txt", "n1\n")
    write(right / "sub" / "nested.txt", "n2\n")

    doc = make_doc(2)
    scan(doc, [left, right])

    root = doc.model.index(0, 0)
    sub = child_map(doc, root)["sub"]
    # A directory row is compared dir-vs-dir -> NORMAL even though its content
    # differs (1.4 shows the difference by expansion, not by colouring dirs).
    assert doc.model.get_state(sub, 0) == STATE_NORMAL
    nested = child_map(doc, sub)["nested.txt"]
    assert doc.model.get_state(nested, 0) == STATE_MODIFIED


def test_scan_expands_to_reveal_differences(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "sub" / "nested.txt", "n1\n")
    write(right / "sub" / "nested.txt", "n2\n")

    doc = make_doc(2)
    scan(doc, [left, right])

    root = doc.model.index(0, 0)
    sub = child_map(doc, root)["sub"]
    # Both the root and the differing sub-directory are auto-expanded in the
    # first tree so the deep MODIFIED file is visible.
    assert doc.treeview[0].isExpanded(root)
    assert doc.treeview[0].isExpanded(sub)


def test_scan_empty_dir_gets_placeholder(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()

    doc = make_doc(2)
    scan(doc, [left, right])

    root = doc.model.index(0, 0)
    # Two empty roots -> a single placeholder row, not an empty tree.
    assert doc.model.rowCount(root) == 1
    placeholder = doc.model.index(0, 0, root)
    assert doc.model.value_path(placeholder, 0) is None


# ---------------------------------------------------------------------------
# T5.6 — name filters and symlink handling
# ---------------------------------------------------------------------------

def test_scan_applies_name_filters(make_doc, tmp_path):
    # The default "Backups" filter (active) hides *~ names.
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "keep.txt", "a\n")
    write(right / "keep.txt", "a\n")
    write(left / "backup~", "junk\n")
    write(right / "backup~", "junk\n")

    doc = make_doc(2)
    scan(doc, [left, right])
    kids = child_map(doc, doc.model.index(0, 0))
    assert "keep.txt" in kids
    assert "backup~" not in kids


def test_scan_ignore_symlinks_pref(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "real.txt", "a\n")
    write(right / "real.txt", "a\n")
    os.symlink(left / "real.txt", left / "link.txt")
    os.symlink(right / "real.txt", right / "link.txt")

    doc = make_doc(2)
    doc.prefs.ignore_symlinks = True
    scan(doc, [left, right])
    kids = child_map(doc, doc.model.index(0, 0))
    assert "real.txt" in kids
    assert "link.txt" not in kids


# ---------------------------------------------------------------------------
# T5.5 — filter-equal (NOCHANGE) and state filtering
# ---------------------------------------------------------------------------

def test_nochange_state_after_text_filter(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "f.txt", "code\n")
    write(right / "f.txt", "code#comment\n")

    doc = make_doc(2)
    # A "#..." comment filter makes the two files identical after filtering
    # (both reduce to "code\n").
    doc.regexes = [re.compile(r"#.*", re.MULTILINE)]
    dirdiff.clear_cache()
    scan(doc, [left, right])

    f = child_map(doc, doc.model.index(0, 0))["f.txt"]
    assert doc.model.get_state(f, 0) == STATE_NOCHANGE
    assert doc.model.get_state(f, 1) == STATE_NOCHANGE


def test_state_filter_hides_identical(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "same.txt", "x\n")
    write(right / "same.txt", "x\n")
    write(left / "diff.txt", "a\n")
    write(right / "diff.txt", "b\n")

    doc = make_doc(2)
    # Drop STATE_NORMAL from the active filters: identical files disappear.
    doc.state_filters = [STATE_MODIFIED, STATE_NEW]
    scan(doc, [left, right])

    kids = child_map(doc, doc.model.index(0, 0))
    assert "diff.txt" in kids
    assert "same.txt" not in kids


# ---------------------------------------------------------------------------
# T5.5 — newest emblem
# ---------------------------------------------------------------------------

def test_newer_emblem_on_newest_pane(make_doc, tmp_path):
    from meldq.widgets.treemodel import ROLE_NEWER

    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "diff.txt", "old\n")
    write(right / "diff.txt", "new\n")
    # Make the right copy strictly newer.
    os.utime(left / "diff.txt", (1000, 1000))
    os.utime(right / "diff.txt", (2000, 2000))

    doc = make_doc(2)
    scan(doc, [left, right])
    diff = child_map(doc, doc.model.index(0, 0))["diff.txt"]

    item0 = doc.model.itemFromIndex(diff.siblingAtColumn(0))
    item1 = doc.model.itemFromIndex(diff.siblingAtColumn(1))
    assert item0.data(ROLE_NEWER) is False
    assert item1.data(ROLE_NEWER) is True


# ---------------------------------------------------------------------------
# T5.5 — file_deleted / file_created incremental updates
# ---------------------------------------------------------------------------

def test_file_deleted_refreshes_when_present_elsewhere(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "same.txt", "x\n")
    write(right / "same.txt", "x\n")

    doc = make_doc(2)
    scan(doc, [left, right])
    root = doc.model.index(0, 0)
    same = child_map(doc, root)["same.txt"]

    (left / "same.txt").unlink()
    doc.file_deleted(doc.model.rowpath(same), 0)

    # Row survives (still on the right) and flips to MISSING / NEW.
    same = child_map(doc, root)["same.txt"]
    assert doc.model.get_state(same, 0) == STATE_MISSING
    assert doc.model.get_state(same, 1) == STATE_NEW


def test_file_deleted_removes_when_gone_everywhere(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "same.txt", "x\n")
    write(right / "same.txt", "x\n")

    doc = make_doc(2)
    scan(doc, [left, right])
    root = doc.model.index(0, 0)
    same = doc.model.rowpath(child_map(doc, root)["same.txt"])

    (left / "same.txt").unlink()
    (right / "same.txt").unlink()
    doc.file_deleted(same, 0)

    assert "same.txt" not in child_map(doc, root)


def test_file_created_refreshes_row(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "onlyleft.txt", "x\n")
    right.mkdir()

    doc = make_doc(2)
    scan(doc, [left, right])
    root = doc.model.index(0, 0)
    row = child_map(doc, root)["onlyleft.txt"]
    assert doc.model.get_state(row, 1) == STATE_MISSING

    write(right / "onlyleft.txt", "x\n")           # copy created on the right
    doc.file_created(doc.model.rowpath(row), 1)

    row = child_map(doc, root)["onlyleft.txt"]
    assert doc.model.get_state(row, 0) == STATE_NORMAL
    assert doc.model.get_state(row, 1) == STATE_NORMAL


# ---------------------------------------------------------------------------
# T5.6 — rescan clears stale children before repopulating
# ---------------------------------------------------------------------------

def test_rescan_replaces_children(make_doc, tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    write(left / "a.txt", "1\n")
    write(right / "a.txt", "1\n")

    doc = make_doc(2)
    scan(doc, [left, right])
    assert set(child_map(doc, doc.model.index(0, 0))) == {"a.txt"}

    (left / "a.txt").unlink()
    (right / "a.txt").unlink()
    write(left / "b.txt", "2\n")
    write(right / "b.txt", "2\n")
    doc.refresh()
    doc.scheduler.complete_tasks()

    # No leftover a.txt row from the first scan.
    assert set(child_map(doc, doc.model.index(0, 0))) == {"b.txt"}
