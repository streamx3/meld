import io
import os
import re
import sys
import time

from meldq.util import misc


def test_shorten_names_common_dir():
    assert misc.shorten_names("/tmp/foo1", "/tmp/foo2") == ["foo1", "foo2"]


def test_shorten_names_same_basename():
    assert misc.shorten_names("/a/x/file.c", "/a/y/file.c") == \
        ["[x] file.c", "[y] file.c"]


def test_shorten_names_single():
    assert misc.shorten_names("/tmp/foo") == ["foo"]


def test_shorten_names_empty_becomes_none_marker():
    assert misc.shorten_names("/a/b", "/a/") == ["b", "[None]"]


def test_shorten_names_returns_reiterable_list():
    result = misc.shorten_names("/tmp/foo1", "/tmp/foo2")
    assert isinstance(result, list)
    assert list(result) == list(result)


def test_struct_equality():
    a = misc.struct(x=1, y="z")
    b = misc.struct(x=1, y="z")
    c = misc.struct(x=2, y="z")
    assert a == b
    assert a != c


def test_all_equal():
    assert misc.all_equal([]) is True
    assert misc.all_equal(["a", "a"]) is True
    assert misc.all_equal(["a", "b"]) is False


def test_shelljoin_quotes_falsy_strings():
    joined = misc.shelljoin(["a b", "", " c", "plain"])
    assert joined == '"a b" "" " c" plain'


def test_shell_to_regex():
    assert re.match(misc.shell_to_regex("*.py"), "x.py")
    assert not re.match(misc.shell_to_regex("*.py"), "x.pyc")
    brace = misc.shell_to_regex("{a,b}c")
    assert re.match(brace, "ac") and re.match(brace, "bc")
    assert not re.match(brace, "cc")
    negated = misc.shell_to_regex("[!x]")
    assert re.match(negated, "y") and not re.match(negated, "x")
    escaped = misc.shell_to_regex(r"\*")
    assert re.match(escaped, "*") and not re.match(escaped, "a")


def test_commonprefix():
    assert misc.commonprefix([]) == ''
    assert misc.commonprefix(["/usr/local/bin", "/usr/local/share"]) == "/usr/local"
    assert misc.commonprefix(["/a/b", "/c/d"]) == ''


def test_copy2_and_copytree(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("data")
    (src / "sub").mkdir()
    (src / "sub" / "inner.txt").write_text("inner")
    os.symlink("file.txt", src / "link")

    dst = tmp_path / "dst"
    misc.copytree(str(src), str(dst))
    assert (dst / "file.txt").read_text() == "data"
    assert (dst / "sub" / "inner.txt").read_text() == "inner"
    assert os.path.islink(dst / "link")
    assert os.readlink(dst / "link") == "file.txt"
    # existing destination *directories* are tolerated (mkdir EEXIST guard);
    # symlink collisions raise, exactly as in 1.4
    src2 = tmp_path / "src2"
    src2.mkdir()
    (src2 / "sub").mkdir()
    (src2 / "sub" / "other.txt").write_text("other")
    misc.copytree(str(src2), str(dst))
    assert (dst / "sub" / "other.txt").read_text() == "other"
    assert (dst / "sub" / "inner.txt").read_text() == "inner"


def test_cmdout():
    assert misc.cmdout(["echo", "hi"]) == ("hi\n", 0)


def test_write_pipe():
    assert misc.write_pipe(["cat"], "x") == 0


def test_read_pipe_iter_yields_none_then_output():
    code = ("import sys,time; print('out'); sys.stderr.write('err'); "
            "sys.stderr.flush(); time.sleep(0.3); print('done')")
    errorstream = io.StringIO()
    nones = 0
    final = None
    for value in misc.read_pipe_iter([sys.executable, "-c", code],
                                     errorstream, yield_interval=0.05):
        if value is None:
            nones += 1
        else:
            final = value
            break
    assert nones >= 1
    assert "out" in final and "done" in final
    assert "err" in errorstream.getvalue()


def test_read_pipe_iter_kills_on_close():
    errorstream = io.StringIO()
    gen = misc.read_pipe_iter(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        errorstream, yield_interval=0.05)
    start = time.monotonic()
    assert next(gen) is None
    gen.close()
    assert time.monotonic() - start < 5
    assert "killing" in errorstream.getvalue()
    assert "killed" in errorstream.getvalue()
