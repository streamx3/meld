import os
import shutil
import subprocess

import pytest

from meldq.doc import Direction
from meldq.util.prefs import Preferences
from meldq import vcview


def _drain(view, limit=100000):
    n = 0
    while view.scheduler.tasks_pending() and n < limit:
        view.scheduler.iteration()
        n += 1
    return n


def _rows(view):
    """Flatten the tree into [(basename, status_text), ...]."""
    out = []

    def walk(parent):
        for r in range(view.model.rowCount(parent)):
            ci = view.model.index(r, 0, parent)
            path = view.model.value_path(ci, 0)
            status = view.model.itemFromIndex(
                ci.siblingAtColumn(vcview.COL_STATUS)).text()
            out.append((os.path.basename(path) if path else "(empty)", status))
            walk(ci)

    walk(view.model.index(0, 0))
    return out


@pytest.fixture
def view(qapp, qtbot):
    v = vcview.VcView(Preferences())
    qtbot.addWidget(v.widget)
    return v


def test_null_backed_filters(view, tmp_path):
    (tmp_path / "a.txt").write_text("x\n")
    (tmp_path / "b.txt").write_text("y\n")
    view.set_location(str(tmp_path))
    _drain(view)
    assert view.vc.NAME == "Null"

    # Default filters are Modified-only + Flatten: unversioned files hidden.
    assert _rows(view) == []
    # Flatten defaults on -> the Location column is shown.
    assert not view.treeview.isColumnHidden(vcview.COL_LOCATION)

    # Toggling Non-VC reveals them as "Unversioned" (STATE_NONE).
    view.action_filter_nonvc.setChecked(True)
    _drain(view)
    assert {name: status for name, status in _rows(view)} == {
        "a.txt": "Unversioned", "b.txt": "Unversioned"}


def test_flatten_toggles_location_column(view, tmp_path):
    view.set_location(str(tmp_path))
    _drain(view)
    assert not view.treeview.isColumnHidden(vcview.COL_LOCATION)
    view.action_flatten.setChecked(False)     # tree mode
    _drain(view)
    assert view.treeview.isColumnHidden(vcview.COL_LOCATION)


def test_next_diff_and_selection(view, tmp_path):
    (tmp_path / "a.txt").write_text("x\n")
    view.set_location(str(tmp_path))
    view.action_filter_nonvc.setChecked(True)   # show the unversioned file
    _drain(view)

    # From the root, next_diff(DOWN) lands on the first non-normal row.
    view.next_diff(Direction.DOWN)
    selected = view._get_selected_files()
    assert [os.path.basename(p) for p in selected] == ["a.txt"]
    assert all(os.path.isabs(p) for p in selected)

    # Boundary: repeated next_diff past the last row is a silent no-op
    # (PEP 479 — the traversal generator must return, never raise).
    for _ in range(10):
        view.next_diff(Direction.DOWN)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_backed_states(view, tmp_path):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull, GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")

    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    git("init")
    (tmp_path / "a.txt").write_text("orig\n")
    (tmp_path / ".gitignore").write_text("*.log\n")
    git("add", "a.txt", ".gitignore")
    git("commit", "-m", "init")
    (tmp_path / "a.txt").write_text("modified\n")   # -> Modified
    (tmp_path / "x.log").write_text("log\n")         # -> Ignored

    view.set_location(str(tmp_path))
    _drain(view)
    assert view.vc.NAME == "Git"

    # Default (Modified filter): only a.txt, and it is "Modified".
    default = {name: status for name, status in _rows(view)}
    assert default.get("a.txt") == "Modified"
    assert "x.log" not in default

    # Enabling the Ignored filter reveals x.log as "Ignored".
    view.action_filter_ignored.setChecked(True)
    _drain(view)
    revealed = {name: status for name, status in _rows(view)}
    assert revealed.get("x.log") == "Ignored"

    # next_diff(DOWN) selects the modified row.
    view.next_diff(Direction.DOWN)
    assert [os.path.basename(p) for p in view._get_selected_files()] == ["a.txt"]
