import io
import os
import shutil
import subprocess

import pytest

from meldq.vc import _vc, svn


@pytest.fixture
def parser_vc(tmp_path, monkeypatch):
    """An svn Vc whose repo-root check is stubbed so no real .svn is needed."""
    monkeypatch.setattr(svn.Vc, "check_repo_root",
                        lambda self, location: location)
    vc = svn.Vc(str(tmp_path))
    vc.root = str(tmp_path)
    vc.location = str(tmp_path)
    return vc


# A single `svn status -Nv` capture exercising every branch of _get_matches:
#   - a 1.6+ tree-conflict line (must be skipped)
#   - modified / normal(space) / missing / conflict version-controlled files
#   - an unknown (non-vc) file
#   - a moved file (re_status_moved) and a plain locally-added file
#   - a modern wide status field (svn 1.7+ uses more status columns)
STATUS_NV = (
    "      >   local missing, incoming edit upon update\n"
    "M            4        4 alice        /r/foo.c\n"
    "             4        4 alice        /r/normal.c\n"
    "?                                    /r/new.c\n"
    "!            4        4 alice        /r/gone.c\n"
    "C            4        4 alice        /r/conflict.c\n"
    "A  +    -    ?     ?   /r/dest.c\n"
    "A            0        ?      ?         /r/added.c\n"
    "M               8        8 bob          /r/wide.c\n"
)


def test_get_matches_parses_and_sorts(parser_vc, monkeypatch):
    monkeypatch.setattr(svn._vc, "popen",
                        lambda cmd, cwd=None: io.StringIO(STATUS_NV))
    matches = parser_vc._get_matches("/r")
    assert matches == [
        ("/r/added.c", "A", "?"),
        ("/r/conflict.c", "C", "4"),
        ("/r/dest.c", "A", "?"),      # moved form -> revision column is "?"
        ("/r/foo.c", "M", "4"),
        ("/r/gone.c", "!", "4"),
        ("/r/new.c", "?", ""),         # non-vc -> empty revision
        ("/r/normal.c", " ", "4"),     # leading-space status preserved
        ("/r/wide.c", "M", "8"),
    ]


def test_tree_conflict_line_skipped(parser_vc, monkeypatch):
    fixture = "      >   local missing, incoming edit upon update\n"
    monkeypatch.setattr(svn._vc, "popen",
                        lambda cmd, cwd=None: io.StringIO(fixture))
    assert parser_vc._get_matches("/r") == []


def test_text_mode_stream_parses(parser_vc, monkeypatch):
    # Positive half of the text-mode contract: a *text* stream (what _vc.popen
    # yields with text=True) parses cleanly, trailing "\n" and all.
    monkeypatch.setattr(svn._vc, "popen",
                        lambda cmd, cwd=None: io.StringIO(STATUS_NV))
    assert len(parser_vc._get_matches("/r")) == 8


def test_bytes_stream_raises_typeerror(parser_vc, monkeypatch):
    # The py3 hard break, pinned at the break site: the four status regexes are
    # *str* patterns, so a bytes line (what a non-text popen would yield) raises
    # "cannot use a string pattern on a bytes-like object". _vc.popen's text=True
    # is what prevents this — a StringIO stub could never exercise it.
    monkeypatch.setattr(svn._vc, "popen",
                        lambda cmd, cwd=None: io.BytesIO(STATUS_NV.encode()))
    with pytest.raises(TypeError):
        parser_vc._get_matches("/r")


def test_secondary_column_lines_dropped_parity(parser_vc, monkeypatch):
    # Shared quirk with Meld 1.4, pinned for PARITY (not a bug): a line whose
    # primary status column is blank/normal but a *secondary* column is set —
    # property-only mods ("MM", " M") or a lock ("K") — matches no pattern and
    # is silently dropped. If the regexes are ever widened, this flags the
    # behavior change. Switching to `svn status --xml` is out of scope.
    fixture = (
        "MM           4        4 alice        /r/propmod.c\n"
        " M           4        4 alice        /r/prop2.c\n"
        "     K       4        4 alice        /r/locked.c\n"
    )
    monkeypatch.setattr(svn._vc, "popen",
                        lambda cmd, cwd=None: io.StringIO(fixture))
    assert parser_vc._get_matches("/r") == []


def test_get_dirsandfiles_state_mapping(parser_vc, tmp_path, monkeypatch):
    tmp = str(tmp_path)
    (tmp_path / "mod.c").write_text("x\n")        # real file -> MODIFIED
    (tmp_path / "norm.c").write_text("x\n")        # real file -> NORMAL (" ")
    (tmp_path / "added.c").write_text("x\n")       # real file -> NEW ("A")
    (tmp_path / "subdir").mkdir()                   # real dir  -> NORMAL dir
    # gone.c is never created -> os.path.isdir False -> MISSING File
    fixture = (
        f"M            4        4 alice        {tmp}/mod.c\n"
        f"             4        4 alice        {tmp}/norm.c\n"
        f"A            0        ?      ?         {tmp}/added.c\n"
        f"!            4        4 alice        {tmp}/gone.c\n"
        f"             4        4 alice        {tmp}/subdir\n"
        f"             4        4 alice        {tmp}\n"   # the scanned dir itself
    )
    monkeypatch.setattr(svn._vc, "popen",
                        lambda cmd, cwd=None: io.StringIO(fixture))

    dirs, files = parser_vc._get_dirsandfiles(tmp, [], [])

    files_by_name = {f.name: f.state for f in files}
    assert files_by_name["mod.c"] == _vc.STATE_MODIFIED
    assert files_by_name["norm.c"] == _vc.STATE_NORMAL
    assert files_by_name["added.c"] == _vc.STATE_NEW
    # A vanished path is never a dir, so svn's "!" surfaces as a MISSING File.
    assert files_by_name["gone.c"] == _vc.STATE_MISSING
    dirs_by_name = {d.name: d.state for d in dirs}
    assert dirs_by_name == {"subdir": _vc.STATE_NORMAL}
    # The scanned directory itself (name == directory) is excluded.
    assert os.path.basename(tmp) not in dirs_by_name
    assert os.path.basename(tmp) not in files_by_name


@pytest.mark.skipif(shutil.which("svn") is None or shutil.which("svnadmin") is None,
                    reason="subversion not installed")
def test_real_repo_states(tmp_path):
    repo = tmp_path / "repo"
    wc = tmp_path / "wc"
    subprocess.run(["svnadmin", "create", str(repo)], check=True)
    url = "file://" + str(repo)
    subprocess.run(["svn", "checkout", url, str(wc)], check=True,
                   stdout=subprocess.DEVNULL)
    (wc / "a.txt").write_text("original\n")
    subprocess.run(["svn", "add", str(wc / "a.txt")], check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run(["svn", "commit", "-m", "init", str(wc)], check=True,
                   stdout=subprocess.DEVNULL)
    (wc / "a.txt").write_text("modified\n")     # -> MODIFIED
    (wc / "new.txt").write_text("new\n")          # -> NONE (unknown)

    vc = svn.Vc(str(wc))
    dirs, files = vc._get_dirsandfiles(str(wc), [], [])
    by_name = {f.name: f.state for f in files}
    assert by_name["a.txt"] == _vc.STATE_MODIFIED
    assert by_name["new.txt"] == _vc.STATE_NONE
