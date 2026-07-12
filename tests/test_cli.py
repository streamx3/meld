import pytest

from meldq.main import _missing_reqs, parse_args


def test_diff_groups():
    args = parse_args(["--diff", "a", "b", "--diff", "x", "y", "z"])
    assert args.diff == [["a", "b"], ["x", "y", "z"]]


def test_diff_empty_group_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args(["--diff"])
    assert exc.value.code == 2


def test_diff_five_paths_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args(["--diff", "a", "b", "c", "d", "e"])
    assert exc.value.code == 2
    assert "wrong number of arguments supplied to --diff" in capsys.readouterr().err


def test_diff_single_path_accepted():
    assert parse_args(["--diff", "a"]).diff == [["a"]]


def test_too_many_positionals(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args(["p1", "p2", "p3", "p4", "p5"])
    assert exc.value.code == 2
    assert "too many arguments (wanted 0-4, got 5)" in capsys.readouterr().err


def test_labels_and_ignored_flags():
    args = parse_args(["-L", "one", "-L", "two", "-u", "-c", "-r"])
    assert args.label == ["one", "two"]
    assert parse_args([]).paths == []


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "meldq 2.0.0a0"


def test_missing_reqs_uses_parameter_not_leaked_global(capsys):
    # regression for bin/meld:77 (leaked except-var NameError path)
    with pytest.raises(SystemExit) as exc:
        _missing_reqs("PyQt6", ImportError("nope"))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "PyQt6" in err and "nope" in err
