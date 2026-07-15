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
