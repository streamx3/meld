import subprocess
import sys
from pathlib import Path

import pytest

from meldq.vc import _vc


def test_state_constants_match_treemodel():
    from meldq.widgets import treemodel
    for name in ("STATE_IGNORED", "STATE_NONE", "STATE_NORMAL", "STATE_NOCHANGE",
                 "STATE_ERROR", "STATE_EMPTY", "STATE_NEW", "STATE_MODIFIED",
                 "STATE_CONFLICT", "STATE_REMOVED", "STATE_MISSING", "STATE_MAX"):
        assert getattr(_vc, name) == getattr(treemodel, name), name


def test_conflict_markup_stripped_but_msgid_intact():
    assert _vc.Entry.states[_vc.STATE_CONFLICT] == "Conflict"
    # the SOURCE literal must still carry <b>Conflict</b> so the catalogs match
    src = Path(_vc.__file__).read_text(encoding="utf-8")
    assert "<b>Conflict</b>" in src


def test_dir_and_file_flags():
    d = _vc.Dir("/repo/sub", "sub", _vc.STATE_NORMAL)
    assert d.isdir is True
    f = _vc.File("/repo/a.py", "a.py", _vc.STATE_MODIFIED)
    assert f.isdir is False
    assert f.get_status() == "Modified"


def test_file_rejects_trailing_slash():
    with pytest.raises(AssertionError):
        _vc.File("/repo/x/", "x", _vc.STATE_NORMAL)


def test_popen_text_mode_utf8():
    out = _vc.popen(["printf", "héllo"]).read()
    assert out == "héllo"


def test_popen_replaces_invalid_utf8():
    out = _vc.popen(["printf", "\\377"]).read()      # a lone 0xff byte
    assert out == "�"                           # replaced, not an exception


def test_call_return_codes():
    assert _vc.call(["true"]) == 0
    assert _vc.call(["false"]) == 1


def test_find_repo_root_walks_up(tmp_path):
    class FakeVc(_vc.Vc):
        VC_DIR = ".fake"
    marker = tmp_path / ".fake"
    marker.mkdir()
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    vc = FakeVc(str(deep))
    assert vc.root == str(tmp_path)


def test_find_repo_root_raises_past_fs_root(tmp_path):
    class FakeVc(_vc.Vc):
        VC_DIR = ".nonexistent_marker"
    with pytest.raises(ValueError):
        FakeVc(str(tmp_path))


def test_get_patch_files():
    class GitLike(_vc.Vc):
        VC_DIR = ".git"
        PATCH_INDEX_RE = "^diff --git a/(.*) b/.*$"
        def __init__(self):
            pass
    patch = ("diff --git a/foo.py b/foo.py\n"
             "index abc..def 100644\n"
             "diff --git a/bar/baz.c b/bar/baz.c\n")
    assert GitLike().get_patch_files(patch) == ["foo.py", "bar/baz.c"]


def test_vc_package_is_qt_free():
    code = ("import sys, meldq.vc._vc; "
            "sys.exit(1 if any(m.split('.')[0]=='PyQt6' for m in sys.modules) else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
