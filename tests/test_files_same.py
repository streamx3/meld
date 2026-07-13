import builtins
import os
import re

import pytest

from meldq import dirdiff


@pytest.fixture(autouse=True)
def clear_cache():
    dirdiff._cache.clear()
    yield
    dirdiff._cache.clear()


def test_single_and_all_dirs_and_mixture(tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    assert dirdiff._files_same([str(f)], []) == 1        # single -> identical
    d1 = tmp_path / "d1"
    d1.mkdir()
    d2 = tmp_path / "d2"
    d2.mkdir()
    assert dirdiff._files_same([str(d1), str(d2)], []) == 1     # all dirs
    assert dirdiff._files_same([str(d1), str(f)], []) == 0      # file/dir mix


def test_binary_identical_and_different(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"\x00\x01\x02")
    b.write_bytes(b"\x00\x01\x02")
    assert dirdiff._files_same([str(a), str(b)], []) == 1
    b.write_bytes(b"\x00\x01\x03")                        # same size, new mtime
    assert dirdiff._files_same([str(a), str(b)], []) == 0


def test_text_filter_makes_equal(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("hello\n$Id: aaa $\nworld\n")
    b.write_text("hello\n$Id: bbb $\nworld\n")
    idfilt = [re.compile(r"\$Id:.*\$")]
    assert dirdiff._files_same([str(a), str(b)], idfilt) == 2
    # the cache is keyed on paths only (as in 1.4), so a filter change must
    # clear it — DirDiff.update_regexes does exactly this.
    dirdiff.clear_cache()
    assert dirdiff._files_same([str(a), str(b)], []) == 0     # no filter -> differ


def test_invalid_utf8_with_filters_no_exception(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"\xff\xfe data")
    b.write_bytes(b"\xff\xfe other")
    # decoded utf-8/replace THEN filtered; must not raise UnicodeDecodeError
    result = dirdiff._files_same([str(a), str(b)], [re.compile("data|other")])
    assert result == 2       # the invalid bytes decode identically, words filtered


def test_cache_avoids_reread(tmp_path, monkeypatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    reads = {"n": 0}
    real_open = builtins.open

    def counting_open(f, *args, **kwargs):
        if (args and args[0] == "rb") or kwargs.get("mode") == "rb":
            reads["n"] += 1
        return real_open(f, *args, **kwargs)

    monkeypatch.setattr("builtins.open", counting_open)
    assert dirdiff._files_same([str(a), str(b)], []) == 1
    assert reads["n"] == 2                       # both files read once

    reads["n"] = 0
    assert dirdiff._files_same([str(a), str(b)], []) == 1
    assert reads["n"] == 0                        # cache hit, no reads

    os.utime(str(a), (0, 0))                      # mtime change invalidates cache
    reads["n"] = 0
    assert dirdiff._files_same([str(a), str(b)], []) == 1
    assert reads["n"] == 2                        # re-read


def test_memoryerror_falls_back_to_filecmp(tmp_path, monkeypatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"z")
    b.write_bytes(b"z")

    def boom(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr(dirdiff.filecmp, "cmp", lambda x, y, shallow: True)
    assert dirdiff._files_same([str(a), str(b)], []) == 1
    monkeypatch.setattr(dirdiff.filecmp, "cmp", lambda x, y, shallow: False)
    assert dirdiff._files_same([str(a), str(b)], []) == 0


def test_build_text_filters_multiline_no_error():
    # only the active line compiles; MULTILINE is set (the 1.4 trailing-"(?m)"
    # would have been a py3.11 re.error).
    compiled = dirdiff.build_text_filters("keep\t1\t//.*\ndrop\t0\t#.*")
    assert len(compiled) == 1
    assert compiled[0].flags & re.MULTILINE
    errs = []
    dirdiff.build_text_filters("x\t1\t^foo$", on_error=errs.append)
    assert errs == []


def test_build_name_filters():
    pref = ("Backups\t1\t*.bak *.tmp\n"
            "Single\t1\t*.log\n"
            "Empty\t1\t\n"
            "Bad\t1\t[z-a]")
    errs = []
    filters = dirdiff.build_name_filters(pref, on_error=errs.append)
    labels = [f.label for f in filters]
    assert "Backups" in labels and "Single" in labels
    assert "Empty" not in labels            # empty pattern skipped
    assert "Bad" not in labels              # invalid glob -> on_error, skipped
    assert errs == ["[z-a]"]

    backups = next(f for f in filters if f.label == "Backups")
    assert backups.filter("x.bak") is False    # matched -> hidden
    assert backups.filter("x.tmp") is False
    assert backups.filter("x.py") is True      # kept
