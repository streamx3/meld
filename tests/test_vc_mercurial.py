import io
import os
import shutil
import subprocess

import pytest

from meldq.vc import _vc, mercurial


@pytest.fixture
def hg_vc(tmp_path):
    mercurial.Vc.check_repo_root = lambda self, location: location
    vc = mercurial.Vc(str(tmp_path))
    vc.root = str(tmp_path)
    vc.location = str(tmp_path)
    return vc


# `hg status -A .` output: "<char> <path>". Nested paths (with "/") belong to a
# later per-directory scan and must be filtered out at this depth.
STATUS_A = (
    "M mod.txt\n"
    "A added.txt\n"
    "? unknown.txt\n"
    "C clean.txt\n"
    "! missing.txt\n"
    "R removed.txt\n"
    "I ignored.txt\n"
    "M sub/inner.txt\n"     # depth-1 -> excluded by the "/" filter
)


def test_depth0_state_mapping(hg_vc, monkeypatch):
    monkeypatch.setattr(mercurial._vc, "popen",
                        lambda cmd, cwd=None: io.StringIO(STATUS_A))
    dirs, files = hg_vc._get_dirsandfiles("/repo", [], [])
    by_name = {f.name: f.state for f in files}
    assert by_name == {
        "mod.txt": _vc.STATE_MODIFIED,
        "added.txt": _vc.STATE_NEW,
        "unknown.txt": _vc.STATE_NONE,
        "clean.txt": _vc.STATE_NORMAL,
        "missing.txt": _vc.STATE_MISSING,
        "removed.txt": _vc.STATE_REMOVED,
        "ignored.txt": _vc.STATE_IGNORED,
    }
    # the nested file is not surfaced at this depth
    assert "inner.txt" not in by_name


def test_unlisted_files_fall_through_to_normal(hg_vc, monkeypatch):
    monkeypatch.setattr(mercurial._vc, "popen",
                        lambda cmd, cwd=None: io.StringIO("M mod.txt\n"))
    # extra.txt is not in hg's status output -> defaults to STATE_NORMAL
    dirs, files = hg_vc._get_dirsandfiles(
        "/repo", [("subd", "/repo/subd")], [("extra.txt", "/repo/extra.txt")])
    by_name = {f.name: f.state for f in files}
    assert by_name["mod.txt"] == _vc.STATE_MODIFIED
    assert by_name["extra.txt"] == _vc.STATE_NORMAL
    assert {d.name: d.state for d in dirs} == {"subd": _vc.STATE_NORMAL}


@pytest.mark.skipif(shutil.which("hg") is None, reason="mercurial not installed")
def test_real_repo_states(tmp_path):
    env = dict(os.environ, HGRCPATH=os.devnull)

    def run(*args):
        subprocess.run(["hg", *args], cwd=tmp_path, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run("init")
    (tmp_path / "a.txt").write_text("original\n")
    run("add", "a.txt")
    run("commit", "-u", "t <t@t>", "-m", "init")
    (tmp_path / "a.txt").write_text("modified\n")
    (tmp_path / "new.txt").write_text("new\n")

    vc = mercurial.Vc(str(tmp_path))
    dirs, files = vc._get_dirsandfiles(str(tmp_path), [], [])
    by_name = {f.name: f.state for f in files}
    assert by_name["a.txt"] == _vc.STATE_MODIFIED
    assert by_name["new.txt"] == _vc.STATE_NONE
