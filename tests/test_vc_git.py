import io
import os
import shutil
import subprocess

import pytest

from meldq.vc import _vc, git


@pytest.fixture
def parser_repo(tmp_path, monkeypatch):
    """A Git Vc whose repo-root check is stubbed so no real .git is needed."""
    monkeypatch.setattr(git.Vc, "check_repo_root",
                        lambda self, location: location)
    vc = git.Vc(str(tmp_path))
    vc.root = str(tmp_path)
    vc.location = str(tmp_path)
    return vc, str(tmp_path)


def test_lookup_tree_cache_parses_and_dedups(parser_repo, monkeypatch):
    vc, root = parser_repo
    outputs = {
        "diff-index": "M\tmod.txt\nD\tgone.txt\n",
        "diff-files": "M\tmod.txt\n",             # duplicate of the above
        "ls-files": "ignored.log\n",
    }
    monkeypatch.setattr(_vc, "call", lambda cmd, cwd=None: 0)
    monkeypatch.setattr(git._vc, "popen",
                        lambda cmd, cwd=None: io.StringIO(outputs[cmd[1]]))
    tree = vc._lookup_tree_cache(root)
    assert tree[os.path.join(root, "mod.txt")] == _vc.STATE_MODIFIED
    assert tree[os.path.join(root, "gone.txt")] == _vc.STATE_REMOVED
    assert tree[os.path.join(root, "ignored.log")] == _vc.STATE_IGNORED
    # mod.txt appeared twice (diff-index + diff-files) but is one entry
    assert list(tree.keys()).count(os.path.join(root, "mod.txt")) == 1


def test_get_dirsandfiles_synthesizes_removed(parser_repo, monkeypatch):
    vc, root = parser_repo
    gone = os.path.join(root, "gone.txt")
    monkeypatch.setattr(vc, "_get_tree_cache",
                        lambda directory: {gone: _vc.STATE_REMOVED})
    dirs, files = vc._get_dirsandfiles(root, [], [])
    # the removed file is absent from disk but synthesized into the listing
    names = [f.name for f in files]
    assert "gone.txt" in names
    assert files[0].state == _vc.STATE_REMOVED


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_real_repo_states(tmp_path):
    env = dict(os.environ)
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def run(*args):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run("init")
    (tmp_path / "a.txt").write_text("original\n")
    (tmp_path / ".gitignore").write_text("*.log\n")
    run("add", "a.txt", ".gitignore")
    run("commit", "-m", "init")
    (tmp_path / "a.txt").write_text("modified\n")   # -> MODIFIED
    (tmp_path / "new.txt").write_text("new\n")       # -> NORMAL (see below)
    (tmp_path / "x.log").write_text("log\n")         # -> IGNORED

    vc = git.Vc(str(tmp_path))
    vc.cache_inventory(str(tmp_path))
    dirs, files = vc.lookup_files(
        [], [(n, str(tmp_path / n)) for n in ("a.txt", "new.txt", "x.log")])
    by_name = {f.name: f.state for f in files}
    assert by_name["a.txt"] == _vc.STATE_MODIFIED
    # Faithful original behavior: the scan only queries diff-index/diff-files
    # plus ls-files --others --ignored, so a plain untracked (non-ignored) file
    # never enters the tree cache and defaults to STATE_NORMAL, not STATE_NONE.
    assert by_name["new.txt"] == _vc.STATE_NORMAL
    assert by_name["x.log"] == _vc.STATE_IGNORED
