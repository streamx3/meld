import os
import shutil
import subprocess

import pytest
from PyQt6.QtCore import QSettings

from meldq.app import MeldWindow
from meldq.util.prefs import Preferences


def _make_git_repo(path):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull, GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")

    def git(*a):
        subprocess.run(["git", *a], cwd=path, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    git("init")
    (path / "a.txt").write_text("original\n")
    git("add", "a.txt")
    git("commit", "-m", "init")
    (path / "a.txt").write_text("modified\n")


@pytest.fixture
def window(qapp, qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "prefs.ini"),
                                  QSettings.Format.IniFormat))
    win = MeldWindow(prefs)
    qtbot.addWidget(win)
    yield win
    win.pump.stop()
    win.close()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_vcview_tab_wiring(window, qtbot, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_git_repo(repo)

    # capture status before the pump can tick, so no "Scanning" line is missed
    status_msgs = []
    window.pump.status_message.connect(status_msgs.append)

    view = window.append_vcview([str(repo)])
    assert view.__class__.__name__ == "VcView"

    # The doc's contributions were materialized onto the shell when the tab
    # became current (DocActionManager.set_doc).
    assert view.action_compare in window.toolbar.actions()
    assert view.action_flatten in window.menus["view"].actions()
    assert view.vcstatus_menu.menuAction() in window.menus["view"].actions()
    tb_start = next(a for a in window.toolbar.actions()
                    if a.objectName() == "doc_toolbar_start")
    assert tb_start.isVisible()          # the doc toolbar segment is shown

    # The statusbar shows a "[label] Scanning ..." message while the pump drains.
    qtbot.waitUntil(lambda: not view.scheduler.tasks_pending(), timeout=5000)
    assert any("Scanning" in m for m in status_msgs)

    # Closing the tab runs on_quit_event: the tracked tempdirs are cleaned up.
    leftover = tmp_path / "leftover-meld"
    leftover.mkdir()
    view.tempdirs.append(str(leftover))
    window.try_remove_page(view)
    assert view.tempdirs == []
    assert not leftover.exists()
    assert window.tabs.count() == 0
