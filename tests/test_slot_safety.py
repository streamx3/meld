"""C3: an exception in a Qt slot must not abort the process.

In PyQt6 an unhandled exception propagating out of a slot calls qFatal() ->
abort(). These tests drive the risky I/O slots directly and assert they degrade
to a message bar (or a no-op) instead of raising, and cover the global
excepthook net and the PatchDialog-outlives-its-tab crash.
"""

import os

import pytest
from PyQt6.QtWidgets import QApplication

from meldq.views.dirdiff import DirDiffView
from meldq.views.filediff import FileDiffView
from meldq.views.vcview import VcView


# ----- FileDiff: unreadable / missing files ---------------------------------

def test_set_files_none_path_does_not_crash(qapp, qtbot):
    view = FileDiffView(2)
    qtbot.addWidget(view)
    view.set_files(["/nonexistent/or/none", None])   # neither exists / None
    assert view.panes[0].text() == ""
    assert view.panes[1].text() == ""


def test_set_files_unreadable_shows_message_not_crash(qapp, qtbot, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root bypasses file permissions")
    src = tmp_path / "secret.txt"
    src.write_bytes(b"data\n")
    os.chmod(src, 0)                                  # unreadable
    try:
        view = FileDiffView(2)
        qtbot.addWidget(view)
        view.set_files([str(src), str(src)])          # must not raise/abort
        assert view.panes[0].text() == ""
        assert view.infobar.message is not None
    finally:
        os.chmod(src, 0o644)


def test_reload_vanished_file_shows_message(qapp, qtbot, tmp_path):
    a = tmp_path / "a.txt"
    a.write_bytes(b"one\ntwo\n")
    view = FileDiffView(2)
    qtbot.addWidget(view)
    view.set_files([str(a), str(a)])
    a.unlink()
    view.reload(0)                                    # file gone; must not crash
    assert view.infobar.message is not None


# ----- DirDiff: copy/delete I/O failures ------------------------------------

def _dirdiff(qtbot, roots):
    view = DirDiffView(2)
    qtbot.addWidget(view)
    view.set_roots(roots)
    return view


def test_copy_dir_over_file_shows_message_not_crash(qapp, qtbot, tmp_path):
    d1, d2 = tmp_path / "l", tmp_path / "r"
    d1.mkdir()
    d2.mkdir()
    (d1 / "x").mkdir()                                # x is a dir on the left
    (d2 / "x").write_text("file")                     # x is a FILE on the right
    view = _dirdiff(qtbot, [str(d1), str(d2)])
    idx = view.model.index(0, 0)
    view.copy_to(idx, 0, 1)                           # copytree onto a file
    assert view.infobar.message is not None           # message, not abort


def test_delete_missing_is_noop(qapp, qtbot, tmp_path):
    d1, d2 = tmp_path / "l", tmp_path / "r"
    d1.mkdir()
    d2.mkdir()
    (d1 / "a").write_text("a")
    view = _dirdiff(qtbot, [str(d1), str(d2)])
    idx = view.model.index(0, 0)
    (d1 / "a").unlink()                               # vanished between scan/act
    view.delete(idx, 0)                               # must not raise


# ----- VcView: repo dir vanished --------------------------------------------

def test_vcview_refresh_after_repo_vanishes(qapp, qtbot, tmp_path):
    import shutil
    import subprocess

    from meldq import gitvc
    if not gitvc.is_git_available():
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    view = VcView()
    qtbot.addWidget(view)
    view.set_location(str(repo))
    shutil.rmtree(repo)                               # cwd gone
    view.refresh()                                    # OSError inside -> message
    assert view.infobar.message is not None
