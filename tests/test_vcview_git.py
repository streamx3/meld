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


# ----- V10: confirm before irreversible revert/remove -----------------------

def _row(view, rel):
    m = view.model
    for r in range(m.rowCount()):
        if view.row_relpath(m.index(r, 0)) == rel:
            return m.index(r, 0)
    raise KeyError(rel)


def test_revert_untracked_confirmed(vc, repo, monkeypatch):
    (repo / "fresh.txt").write_text("new\n")           # untracked (STATE_NEW)
    vc.set_location(str(repo))
    monkeypatch.setattr(vc, "_confirm", lambda msg: True)
    vc.revert(_row(vc, "fresh.txt"))
    assert not (repo / "fresh.txt").exists()           # confirmed -> deleted


def test_revert_untracked_declined_keeps_file(vc, repo, monkeypatch):
    (repo / "fresh.txt").write_text("new\n")
    vc.set_location(str(repo))
    monkeypatch.setattr(vc, "_confirm", lambda msg: False)
    vc.revert(_row(vc, "fresh.txt"))
    assert (repo / "fresh.txt").exists()               # declined -> kept


def test_remove_declined_keeps_file(vc, repo, monkeypatch):
    (repo / "tracked.txt").write_text("changed\n")
    vc.set_location(str(repo))
    monkeypatch.setattr(vc, "_confirm", lambda msg: False)
    vc.remove(_row(vc, "tracked.txt"))
    assert (repo / "tracked.txt").exists()             # declined -> not removed


# ----- V1/V2/V3/V5: action correctness + error surfacing --------------------

def test_commit_rename_does_not_duplicate(vc, repo, monkeypatch):
    # V1: committing a rename must not leave the old path in HEAD.
    git(repo, "mv", "tracked.txt", "renamed.txt")
    vc.set_location(str(repo))
    monkeypatch.setattr(vc, "_confirm", lambda m: True)
    vc.commit_files(["renamed.txt"], "rename it")
    tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"],
                          cwd=repo, capture_output=True, text=True).stdout.split()
    assert tree == ["renamed.txt"]                 # old name gone


def test_revert_staged_add_leaves_no_ghost(vc, repo):
    # V5: reverting a staged-added file removes the index entry too (no AD row).
    (repo / "staged.txt").write_text("x\n")
    git(repo, "add", "staged.txt")
    vc.set_location(str(repo))
    vc.revert(_row(vc, "staged.txt")) if False else gitvc.revert(str(repo), "staged.txt")
    assert not (repo / "staged.txt").exists()
    assert "staged.txt" not in gitvc.status(str(repo))   # no ghost entry


def test_action_error_is_surfaced(vc, repo, monkeypatch):
    # V3: a failing backend action shows a message instead of doing nothing.
    (repo / "fresh.txt").write_text("x\n")           # untracked
    vc.set_location(str(repo))
    monkeypatch.setattr(vc, "_confirm", lambda m: True)
    # git rm of an untracked file fails; the error must surface
    vc.remove(_row(vc, "fresh.txt"))
    assert vc.infobar.message is not None


def test_commit_returns_result_with_message_on_failure(repo):
    # empty message would be rejected; force a failure via a bogus pathspec
    result = gitvc.commit(str(repo), "msg", ["does-not-exist.txt"])
    assert not result
    assert result.message


def test_commit_during_merge_commits(vc, tmp_path):
    # V2: git refuses a partial (pathspec) commit mid-merge; commit_files must
    # commit the resolved state anyway and clear the merge.
    r = tmp_path / "mrg"
    r.mkdir()
    git(r, "init", "-q")
    (r / "f.txt").write_text("base\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    git(r, "checkout", "-q", "-b", "other")
    (r / "f.txt").write_text("other\n")
    git(r, "commit", "-qam", "other")
    git(r, "checkout", "-q", "master" if (r / ".git" / "refs" / "heads" / "master").exists() else "main")
    (r / "f.txt").write_text("mine\n")
    git(r, "commit", "-qam", "mine")
    # a conflicting merge
    subprocess.run(["git", "merge", "other"], cwd=r, capture_output=True)
    (r / "f.txt").write_text("resolved\n")            # resolve
    vc.set_location(str(r))
    vc.commit_files(["f.txt"], "merge resolved")
    assert not (r / ".git" / "MERGE_HEAD").exists()   # merge committed
    assert last_commit_msg(r) == "merge resolved"


# ----- V6/V9/V11: scope, git-availability, copied-entry parse ---------------

def test_status_scoped_to_subdir(vc, repo):
    # V6: opening a subdirectory lists only that subtree.
    (repo / "top.txt").write_text("changed\n")
    (repo / "sub").mkdir()
    (repo / "sub" / "inner.txt").write_text("new\n")
    vc.set_location(str(repo / "sub"))
    assert set(rows(vc)) == {"sub/inner.txt"}          # top.txt excluded


def test_missing_git_message(vc, tmp_path, monkeypatch):
    # V9: with git unavailable, say so rather than "Not a git repository".
    monkeypatch.setattr(gitvc, "is_git_available", lambda: False)
    monkeypatch.setattr(gitvc, "find_repo_root", lambda p: None)
    vc.set_location(str(tmp_path))
    assert "git is not installed" in (vc.infobar.message or "")


def test_status_parses_copied_entry():
    # V11: a "C" copy entry carries an origin token that must be consumed.
    class P:
        returncode = 0
        stdout = "C  dest.txt\x00src.txt\x00 M other.txt\x00"
    import meldq.gitvc as g
    saved = g._run
    g._run = lambda *a, **k: P()
    try:
        st = g.status("/x")
    finally:
        g._run = saved
    assert st == {"dest.txt": g.STATE_MODIFIED, "other.txt": g.STATE_MODIFIED}
