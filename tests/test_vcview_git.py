"""M4: VcView over a real temp git repo — listing + compare-vs-repo."""

import subprocess

import pytest

from meldq import gitvc
from meldq.views.vcview import VcView

pytestmark = pytest.mark.skipif(
    not gitvc.is_git_available(), reason="git not installed")


def git(repo, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    (r / "tracked.txt").write_text("original\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    return r


@pytest.fixture
def vc(qapp, qtbot):
    view = VcView()
    qtbot.addWidget(view)
    return view


def rows(view):
    m = view.model
    return {view.row_relpath(m.index(r, 0)): view.row_state(m.index(r, 0))
            for r in range(m.rowCount())}


def test_lists_changes(vc, repo):
    (repo / "tracked.txt").write_text("changed\n")
    (repo / "fresh.txt").write_text("new\n")
    vc.set_location(str(repo))
    assert rows(vc) == {
        "tracked.txt": gitvc.STATE_MODIFIED,
        "fresh.txt": gitvc.STATE_NEW,
    }


def test_clean_repo_empty(vc, repo):
    vc.set_location(str(repo))
    assert rows(vc) == {}


def test_non_repo_shows_banner(vc, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    vc.set_location(str(plain))
    assert vc.repo_root is None
    assert "git" in vc.infobar.message.lower()


def test_activate_opens_working_vs_repo(vc, repo):
    (repo / "tracked.txt").write_text("locally changed\n")
    vc.set_location(str(repo))
    got = []
    vc.create_diff.connect(got.append)
    idx = vc.model.index(0, 0)
    vc.on_activated(idx)
    assert len(got) == 1
    left, right = got[0]
    # left = committed HEAD version; right = working copy
    with open(left, "rb") as f:
        assert f.read() == b"original\n"
    with open(right, "rb") as f:
        assert f.read() == b"locally changed\n"


def test_activate_new_file_left_is_empty(vc, repo):
    (repo / "fresh.txt").write_text("brand new\n")
    vc.set_location(str(repo))
    got = []
    vc.create_diff.connect(got.append)
    vc.on_activated(vc.model.index(0, 0))
    left, right = got[0]
    with open(left, "rb") as f:
        assert f.read() == b""              # no HEAD version -> empty
    with open(right, "rb") as f:
        assert f.read() == b"brand new\n"


def test_refresh_reflects_new_change(vc, repo):
    vc.set_location(str(repo))
    assert rows(vc) == {}
    (repo / "tracked.txt").write_text("edited\n")
    vc.refresh()
    assert rows(vc) == {"tracked.txt": gitvc.STATE_MODIFIED}


# ----- vc actions -----------------------------------------------------------

def test_backend_add_stages_untracked(repo):
    (repo / "fresh.txt").write_text("x\n")
    assert gitvc.status(str(repo))["fresh.txt"] == gitvc.STATE_NEW
    assert gitvc.add(str(repo), "fresh.txt")
    # still NEW, but now staged (A ) rather than untracked (??) -> classify NEW
    assert gitvc.status(str(repo))["fresh.txt"] == gitvc.STATE_NEW


def test_backend_revert_restores_modified(repo):
    (repo / "tracked.txt").write_text("changed\n")
    assert gitvc.revert(str(repo), "tracked.txt")
    assert (repo / "tracked.txt").read_text() == "original\n"
    assert gitvc.status(str(repo)) == {}


def test_backend_revert_deletes_untracked(repo):
    (repo / "junk.txt").write_text("y\n")
    assert gitvc.revert(str(repo), "junk.txt")
    assert not (repo / "junk.txt").exists()


def test_backend_remove(repo):
    assert gitvc.remove(str(repo), "tracked.txt")
    assert not (repo / "tracked.txt").exists()
    assert gitvc.status(str(repo))["tracked.txt"] == gitvc.STATE_REMOVED


def test_view_revert_action_refreshes(vc, repo):
    (repo / "tracked.txt").write_text("changed\n")
    vc.set_location(str(repo))
    assert rows(vc) == {"tracked.txt": gitvc.STATE_MODIFIED}
    vc.revert(vc.model.index(0, 0))
    assert rows(vc) == {}                     # reverted -> clean, list refreshed
    assert (repo / "tracked.txt").read_text() == "original\n"


# ----- commit ---------------------------------------------------------------

def last_commit_msg(repo):
    return subprocess.run(["git", "log", "-1", "--pretty=%B"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()


def test_backend_commit_modified(repo):
    (repo / "tracked.txt").write_text("v2\n")
    assert gitvc.commit(str(repo), "update tracked", ["tracked.txt"])
    assert gitvc.status(str(repo)) == {}
    assert last_commit_msg(repo) == "update tracked"


def test_backend_commit_untracked(repo):
    (repo / "new.txt").write_text("hi\n")
    assert gitvc.commit(str(repo), "add new", ["new.txt"])
    assert "new.txt" not in gitvc.status(str(repo))     # now tracked + committed


def test_commit_dialog_returns_message(qapp, qtbot):
    from meldq.views.vcview import CommitDialog
    dlg = CommitDialog(["a.txt", "b.txt"])
    qtbot.addWidget(dlg)
    dlg.message.setPlainText("my message")
    assert dlg.commit_message() == "my message"


def test_view_commit_files(vc, repo):
    (repo / "tracked.txt").write_text("edited\n")
    vc.set_location(str(repo))
    vc.commit_files(["tracked.txt"], "committed via view")
    assert rows(vc) == {}                     # committed -> clean, refreshed
    assert last_commit_msg(repo) == "committed via view"


def test_view_commit_ignores_empty_message(vc, repo):
    (repo / "tracked.txt").write_text("edited\n")
    vc.set_location(str(repo))
    vc.commit_files(["tracked.txt"], "   ")   # blank -> no commit
    assert rows(vc) == {"tracked.txt": gitvc.STATE_MODIFIED}
