"""M4: Qt-free git backend (meldq.gitvc). Uses a real temp repo."""

import subprocess

import pytest

from meldq import gitvc

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
    (r / "todelete.txt").write_text("bye\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    return r


def test_find_repo_root(repo):
    root = gitvc.find_repo_root(str(repo / "tracked.txt"))
    assert root is not None
    # macOS /tmp may be symlinked; compare basenames + existence
    assert root.endswith("repo")


def test_find_repo_root_none_outside(tmp_path):
    assert gitvc.find_repo_root(str(tmp_path)) is None


def test_status_clean_repo(repo):
    assert gitvc.status(str(repo)) == {}


def test_status_modified(repo):
    (repo / "tracked.txt").write_text("changed\n")
    assert gitvc.status(str(repo)) == {"tracked.txt": gitvc.STATE_MODIFIED}


def test_status_untracked_is_new(repo):
    (repo / "fresh.txt").write_text("new\n")
    assert gitvc.status(str(repo))["fresh.txt"] == gitvc.STATE_NEW


def test_status_added_is_new(repo):
    (repo / "staged.txt").write_text("s\n")
    git(repo, "add", "staged.txt")
    assert gitvc.status(str(repo))["staged.txt"] == gitvc.STATE_NEW


def test_status_deleted_is_removed(repo):
    (repo / "todelete.txt").unlink()
    assert gitvc.status(str(repo))["todelete.txt"] == gitvc.STATE_REMOVED


def test_status_path_with_space(repo):
    (repo / "a b.txt").write_text("x\n")
    assert "a b.txt" in gitvc.status(str(repo))


def test_repo_file_content_head(repo):
    (repo / "tracked.txt").write_text("locally changed\n")
    # working tree changed, but HEAD still has the original
    assert gitvc.repo_file_content(str(repo), "tracked.txt") == b"original\n"


def test_repo_file_content_absent(repo):
    assert gitvc.repo_file_content(str(repo), "never-existed.txt") is None
