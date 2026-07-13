import io
import shutil

import pytest

from meldq.vc import _vc, bzr


@pytest.fixture
def bzr_vc(tmp_path):
    bzr.Vc.check_repo_root = lambda self, location: location
    vc = bzr.Vc(str(tmp_path))
    vc.root = str(tmp_path)
    vc.location = str(tmp_path)
    return vc


def _popen_root_then(status, root="/repo"):
    """bzr calls popen twice: `root <dir>` then `status <branch_root>`."""
    def fake(cmd, cwd=None):
        if "root" in cmd:
            return io.StringIO(root + "\n")
        return io.StringIO(status)
    return fake


def test_sections_parsed_pending_merges_stops(bzr_vc, monkeypatch):
    status = ("added:\n  new.txt\n"
              "modified:\n  mod.txt\n"
              "pending merges:\n  something\n")   # everything below must stop
    monkeypatch.setattr(bzr._vc, "popen", _popen_root_then(status))
    tree = bzr_vc._lookup_tree_cache("/repo")
    assert tree == {
        "/repo/new.txt": _vc.STATE_NEW,
        "/repo/mod.txt": _vc.STATE_MODIFIED,
    }
    assert "/repo/something" not in tree


def test_orphan_indented_line_before_header(bzr_vc, monkeypatch):
    # Regression: a leading indented line with no preceding section header used
    # to reference cur_state before assignment -> UnboundLocalError. With the
    # fix it is silently skipped and parsing continues.
    status = "  orphan-line\nmodified:\n  mod.txt\n"
    monkeypatch.setattr(bzr._vc, "popen", _popen_root_then(status))
    tree = bzr_vc._lookup_tree_cache("/repo")   # must not raise
    assert tree == {"/repo/mod.txt": _vc.STATE_MODIFIED}
    assert "/repo/orphan-line" not in tree


def test_get_dirsandfiles_splits_dirs_and_files(bzr_vc, monkeypatch):
    # bzr appends "/" to directory entries; they route to retdirs.
    status = ("added:\n  new.txt\n  subdir/\n"
              "modified:\n  mod.txt\n")
    monkeypatch.setattr(bzr._vc, "popen", _popen_root_then(status, root="/repo"))
    dirs, files = bzr_vc._get_dirsandfiles("/repo", [], [])
    assert {f.name: f.state for f in files} == {
        "new.txt": _vc.STATE_NEW,
        "mod.txt": _vc.STATE_MODIFIED,
    }
    assert {d.name: d.state for d in dirs} == {"subdir": _vc.STATE_NEW}


def test_nested_entries_excluded(bzr_vc, monkeypatch):
    # Only entries whose parent dir == the scanned directory are surfaced.
    status = "modified:\n  mod.txt\n  sub/deep.txt\n"
    monkeypatch.setattr(bzr._vc, "popen", _popen_root_then(status, root="/repo"))
    dirs, files = bzr_vc._get_dirsandfiles("/repo", [], [])
    assert {f.name for f in files} == {"mod.txt"}


@pytest.mark.skipif(shutil.which("bzr") is None, reason="bazaar not installed")
def test_real_repo_smoke(tmp_path):
    import os
    import subprocess
    env = dict(os.environ, BZR_EMAIL="t <t@t>", BRZ_EMAIL="t <t@t>")

    def run(*args):
        subprocess.run(["bzr", "--no-aliases", "--no-plugins", *args],
                       cwd=tmp_path, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run("init")
    (tmp_path / "a.txt").write_text("original\n")
    run("add", "a.txt")
    run("commit", "-m", "init")
    (tmp_path / "a.txt").write_text("modified\n")

    vc = bzr.Vc(str(tmp_path))
    dirs, files = vc._get_dirsandfiles(str(tmp_path), [], [])
    by_name = {f.name: f.state for f in files}
    assert by_name.get("a.txt") == _vc.STATE_MODIFIED
