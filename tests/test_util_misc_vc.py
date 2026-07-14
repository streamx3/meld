"""T7.1: verify the Qt-free subprocess/path helpers meet the VC contract.

These were ported in WP2.6/WP4.1; this pins the behaviour WP7 plugins rely on.
"""

import io
import re
import sys
import time

import pytest

from meldq.util import misc


def test_shell_to_regex_matches_and_has_trailing_dollar():
    pattern = misc.shell_to_regex("{a,b}*.py")
    assert re.match(pattern, "a1.py")
    assert re.match(pattern, "bfoo.py")
    assert not re.match(pattern, "c.py")
    # cvs.py slices the trailing "$" off with [:-1]; keep that contract
    assert pattern.endswith("$")


def test_commonprefix_is_path_component_wise():
    assert misc.commonprefix(["/a/b/c", "/a/b/d"]) == "/a/b"
    # character-wise os.path.commonprefix would return "/a/bc" here
    assert misc.commonprefix(["/a/bc", "/a/bd"]) == "/a"
    assert misc.commonprefix([]) == ""


def test_read_pipe_iter_yields_none_then_full_stdout():
    stream = io.StringIO()
    values = []
    for value in misc.read_pipe_iter(
            ["sh", "-c", "echo out; echo err >&2"], stream, yield_interval=0.02):
        values.append(value)
    assert values[-1].strip() == "out"          # entire stdout as one str
    assert any(v is None for v in values[:-1]) or len(values) == 1
    assert "err" in stream.getvalue()


def test_read_pipe_iter_terminates_abandoned_child():
    stream = io.StringIO()
    gen = misc.read_pipe_iter([sys.executable, "-c", "import time; time.sleep(30)"],
                              stream, yield_interval=0.02)
    start = time.monotonic()
    assert next(gen) is None
    gen.close()                                   # GeneratorExit -> terminate
    assert time.monotonic() - start < 5
    assert "killing" in stream.getvalue()


def test_write_pipe_returns_exit_code():
    assert misc.write_pipe(["cat"], "hello") == 0


def test_shelljoin_quotes_only_whitespace():
    assert misc.shelljoin(["plain", "has space"]) == 'plain "has space"'
