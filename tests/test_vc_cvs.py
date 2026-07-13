import os

import pytest

from meldq.vc import _vc, cvs


def make_cvs(tmp_path, entries="", entries_log=None, cvsignore=None):
    """Build a CVS working dir under tmp_path and return its Vc.

    HOME is redirected to an empty dir so a developer's real ~/.cvsignore
    can't pollute the ignore tests.
    """
    cvsdir = tmp_path / "CVS"
    cvsdir.mkdir()
    (cvsdir / "Entries").write_text(entries)
    if entries_log is not None:
        (cvsdir / "Entries.Log").write_text(entries_log)
    if cvsignore is not None:
        (tmp_path / ".cvsignore").write_text(cvsignore)
    return cvs.Vc(str(tmp_path))


@pytest.fixture(autouse=True)
def clean_home(tmp_path, monkeypatch):
    home = tmp_path / "_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _entry(name, rev, date, opts="", tag=""):
    return f"/{name}/{rev}/{date}/{opts}/{tag}\n"


def test_all_file_states(tmp_path):
    # NORMAL: mtime matches the stored asctime date
    (tmp_path / "norm.c").write_text("x\n")
    os.utime(tmp_path / "norm.c", (0, 0))
    # MODIFIED: real file whose mtime disagrees with the stored date
    (tmp_path / "mod.c").write_text("x\n")
    os.utime(tmp_path / "mod.c", (0, 0))
    # CONFLICT: "+"-marked date and a file carrying conflict markers
    (tmp_path / "conflict.c").write_text("a\n=======\nb\n")
    # subdir present on disk -> NORMAL dir
    (tmp_path / "subdir").mkdir()
    # missing.c / gone.c / new.c / mod2.c / stale.c: no file on disk needed

    epoch = "Thu Jan  1 00:00:00 1970"
    entries = (
        _entry("norm.c", "1.1", epoch)
        + _entry("mod.c", "1.1", "Wed Dec 31 00:00:00 1969")      # mismatch
        + _entry("gone.c", "-1.1", epoch)                          # removed
        + _entry("new.c", "0", "dummy timestamp")                  # new
        + _entry("mod2.c", "1.1", "dummy timestamp from new-entry")
        + _entry("conflict.c", "1.1", "Result of merge+" + epoch)
        + _entry("missing.c", "1.1", epoch)                        # no file
        + _entry("stale.c", "1.5", "dummy timestamp")              # -> ERROR
        + "D/subdir////\n"
    )
    vc = make_cvs(tmp_path, entries=entries)
    dirs, files = vc._get_dirsandfiles(str(tmp_path), [], [])

    fs = {f.name: f.state for f in files}
    assert fs["norm.c"] == _vc.STATE_NORMAL
    assert fs["mod.c"] == _vc.STATE_MODIFIED
    assert fs["gone.c"] == _vc.STATE_REMOVED
    assert fs["new.c"] == _vc.STATE_NEW
    assert fs["mod2.c"] == _vc.STATE_MODIFIED
    assert fs["conflict.c"] == _vc.STATE_CONFLICT
    assert fs["missing.c"] == _vc.STATE_MISSING
    # Stale-state regression: dummy timestamp with a non-"0" rev is an explicit
    # ERROR, NOT the previous (alphabetically prior norm.c) file's NORMAL state.
    assert fs["stale.c"] == _vc.STATE_ERROR
    assert {d.name: d.state for d in dirs} == {"subdir": _vc.STATE_NORMAL}


def test_conflict_without_markers_is_modified(tmp_path):
    (tmp_path / "c.c").write_text("no markers here\n")
    entries = _entry("c.c", "1.1", "Result of merge+Thu Jan  1 00:00:00 1970")
    vc = make_cvs(tmp_path, entries=entries)
    _, files = vc._get_dirsandfiles(str(tmp_path), [], [])
    assert {f.name: f.state for f in files}["c.c"] == _vc.STATE_MODIFIED


def test_entries_log_add_remove_add(tmp_path):
    # A then R cancel file1; A file2 survives and is parsed as a NEW file.
    log = ("A /file1/0/dummy timestamp//\n"
           "R /file1/0/dummy timestamp//\n"
           "A /file2/0/dummy timestamp//\n")
    vc = make_cvs(tmp_path, entries="", entries_log=log)
    _, files = vc._get_dirsandfiles(str(tmp_path), [], [])
    by_name = {f.name: f.state for f in files}
    assert "file1" not in by_name
    assert by_name["file2"] == _vc.STATE_NEW


def test_membership_uses_set_not_oneshot_map(tmp_path):
    # Two known files + two unknown. With the py2 map() iterator the first
    # `in` test exhausts it, so later known files get re-added as unversioned.
    entries = (_entry("known1.c", "0", "dummy timestamp")
               + _entry("known2.c", "0", "dummy timestamp"))
    vc = make_cvs(tmp_path, entries=entries)
    passed_files = [(n, str(tmp_path / n))
                    for n in ("known1.c", "known2.c", "unknown1.c", "unknown2.c")]
    _, files = vc._get_dirsandfiles(str(tmp_path), [], passed_files)

    # Each known file appears exactly once, keeping its CVS state (NEW) —
    # never re-added as STATE_NONE.
    for known in ("known1.c", "known2.c"):
        hits = [f for f in files if f.name == known]
        assert len(hits) == 1, known
        assert hits[0].state == _vc.STATE_NEW
    unknown = {f.name: f.state for f in files if f.name.startswith("unknown")}
    assert unknown == {"unknown1.c": _vc.STATE_NONE,
                       "unknown2.c": _vc.STATE_NONE}


def test_cvsignore_marks_ignored(tmp_path):
    vc = make_cvs(tmp_path, entries="", cvsignore="*.log {a,b}.tmp\n")
    passed = [(n, str(tmp_path / n))
              for n in ("foo.log", "a.tmp", "b.tmp", "bar.txt")]
    _, files = vc._get_dirsandfiles(str(tmp_path), [], passed)
    st = {f.name: f.state for f in files}
    assert st["foo.log"] == _vc.STATE_IGNORED
    assert st["a.tmp"] == _vc.STATE_IGNORED
    assert st["b.tmp"] == _vc.STATE_IGNORED
    assert st["bar.txt"] == _vc.STATE_NONE


def test_bad_cvsignore_pattern_warns_and_falls_back(tmp_path):
    # "[z-a]" compiles to an invalid character range -> re.error. The old code
    # left ignore_re unbound and then crashed with NameError; now it records a
    # warning and treats everything as un-ignored (STATE_NONE).
    vc = make_cvs(tmp_path, entries="", cvsignore="[z-a]\n")
    passed = [("anything.log", str(tmp_path / "anything.log"))]
    _, files = vc._get_dirsandfiles(str(tmp_path), [], passed)   # must not raise
    assert files[0].state == _vc.STATE_NONE
    assert vc.warnings
    assert "regular expression" in vc.warnings[0]


def test_no_cvs_dir_returns_all_none(tmp_path):
    # directory without a CVS/Entries file: everything is unversioned.
    (tmp_path / "sub").mkdir()
    vc = cvs.Vc.__new__(cvs.Vc)          # skip __init__/root-walk
    vc.warnings = []
    dirs, files = vc._get_dirsandfiles(
        str(tmp_path), [("sub", str(tmp_path / "sub"))],
        [("a.txt", str(tmp_path / "a.txt"))])
    assert files[0].state == _vc.STATE_NONE
    assert dirs[0].state == _vc.STATE_NONE
