import pytest

from meldq import vc


def test_plain_dir_falls_back_to_null(tmp_path):
    vcs = vc.get_vcs(str(tmp_path))
    assert len(vcs) == 1
    assert vcs[0].NAME == "Null"


def test_git_dir_selects_git(tmp_path):
    (tmp_path / ".git").mkdir()
    vcs = vc.get_vcs(str(tmp_path))
    assert [v.NAME for v in vcs] == ["Git"]


def test_deepest_root_wins(tmp_path):
    # outer is a git checkout; outer/inner is a mercurial checkout nested in it.
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / ".git").mkdir()
    (inner / ".hg").mkdir()
    # git.Vc walks up to `outer`; hg.Vc stops at `inner` (a longer root) -> hg.
    vcs = vc.get_vcs(str(inner))
    assert [v.NAME for v in vcs] == ["Mercurial"]


def test_metadata_covers_known_markers():
    meta = set(vc.get_plugins_metadata())
    assert {".git", ".svn", ".hg", ".bzr", "CVS"} <= meta


def test_descoped_backends_absent():
    names = set(vc._PLUGIN_MODULE_NAMES)
    assert names == {"bzr", "cvs", "git", "mercurial", "svn"}
    for dead in ("cdv", "darcs", "monotone", "rcs", "svk", "tla", "_null", "_vc"):
        assert dead not in names


def test_only_valueerror_is_caught(monkeypatch, tmp_path):
    # A plugin constructor raising ValueError means "not my repo" (skipped);
    # anything else must propagate, breaking discovery loudly.
    class Boom:
        class Vc:
            def __init__(self, location):
                raise RuntimeError("boom")

    monkeypatch.setattr(vc, "_plugins", [Boom])
    with pytest.raises(RuntimeError):
        vc.get_vcs(str(tmp_path))
