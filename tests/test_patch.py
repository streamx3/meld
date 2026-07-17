"""M0.5 patch-import feasibility proof: pure-Python unified-diff parse + apply.

Proves the differentiator (import/apply an external .patch, no GNU `patch`) is
sound before the app exists. The apply model doubles as the UI model: patched =
apply(source, hunks), and "reject a hunk" = apply a subset.
"""

import difflib

import pytest

from meldq.patch import (
    PatchError,
    apply_hunks,
    apply_patch,
    parse_patch,
)


def make_patch(a, b, path="f"):
    """A standard unified diff of a->b. difflib omits the `\\ No newline at end
    of file` markers (and would otherwise run a no-EOL line into the next), so
    we add them — yielding the real-world format git/GNU diff emit."""
    raw = difflib.unified_diff(
        a.splitlines(keepends=True), b.splitlines(keepends=True),
        fromfile="a/" + path, tofile="b/" + path)
    out = []
    for ln in raw:
        if ln[:1] in (" ", "-", "+") and not ln.endswith("\n"):
            out.append(ln + "\n")
            out.append("\\ No newline at end of file\n")
        else:
            out.append(ln)
    return "".join(out)


# ---------------------------------------------------------------------------
# round-trip: apply(source, patch) == target, and reverse == source
# ---------------------------------------------------------------------------

def test_roundtrip_simple():
    a = "one\ntwo\nthree\n"
    b = "one\nTWO\nthree\n"
    fp = parse_patch(make_patch(a, b))[0]
    assert apply_patch(a, fp) == b
    assert apply_patch(b, fp, reverse=True) == a


def test_multi_hunk():
    a = "".join(f"line {i}\n" for i in range(1, 21))
    b = a.replace("line 3\n", "line 3 changed\n").replace(
        "line 17\n", "line 17 changed\n")
    fp = parse_patch(make_patch(a, b))[0]
    assert len(fp.hunks) == 2          # two well-separated changes
    assert apply_patch(a, fp) == b


def test_pure_insertion():
    a = "top\nbottom\n"
    b = "top\nMIDDLE\nbottom\n"
    fp = parse_patch(make_patch(a, b))[0]
    assert apply_patch(a, fp) == b
    assert apply_patch(b, fp, reverse=True) == a


def test_pure_deletion():
    a = "keep\ndrop\nkeep2\n"
    b = "keep\nkeep2\n"
    fp = parse_patch(make_patch(a, b))[0]
    assert apply_patch(a, fp) == b


# ---------------------------------------------------------------------------
# zero-context (`git diff -U0`) insert lands AFTER the named line, not before
# ---------------------------------------------------------------------------

def test_u0_insert_position():
    src = "".join("L%d\n" % i for i in range(1, 11))
    # git diff -U0 form: insert one line after L5.
    patch = "--- a/f\n+++ b/f\n@@ -5,0 +6 @@\n+INSERTED\n"
    out = apply_patch(src, parse_patch(patch)[0])
    lines = out.splitlines()
    assert lines[4:6] == ["L5", "INSERTED"]     # after L5, before L6


def test_u0_insert_at_start():
    src = "L1\nL2\n"
    patch = "--- a/f\n+++ b/f\n@@ -0,0 +1 @@\n+HEAD\n"
    out = apply_patch(src, parse_patch(patch)[0])
    assert out.splitlines() == ["HEAD", "L1", "L2"]


def test_u0_two_inserts_both_land_correctly():
    src = "".join("L%d\n" % i for i in range(1, 11))
    # Insert A after L1 and B after L6; the second hunk's offset accounts for A.
    patch = ("--- a/f\n+++ b/f\n"
             "@@ -1,0 +2 @@\n+A\n"
             "@@ -6,0 +8 @@\n+B\n")
    out = apply_patch(src, parse_patch(patch)[0]).splitlines()
    assert out[1] == "A"                        # after L1
    assert out[out.index("B") - 1] == "L6"      # after L6


# ---------------------------------------------------------------------------
# offset tolerance: patch made against an older revision still applies
# ---------------------------------------------------------------------------

def test_applies_with_offset():
    a = "one\ntwo\nthree\nfour\n"
    b = "one\ntwo\nTHREE\nfour\n"
    patch = make_patch(a, b)
    # The real file has gained a preamble the patch author never saw. The hunk's
    # context ("two"/"three"/"four") is now 3 lines lower — apply must find it.
    shifted = "pre-a\npre-b\npre-c\n" + a
    fp = parse_patch(patch)[0]
    got = apply_patch(shifted, fp)
    assert got == "pre-a\npre-b\npre-c\n" + b


def test_context_mismatch_raises():
    a = "one\ntwo\nthree\n"
    b = "one\nTWO\nthree\n"
    fp = parse_patch(make_patch(a, b))[0]
    with pytest.raises(PatchError):
        apply_patch("completely\ndifferent\ncontent\n", fp, max_offset=2)


# ---------------------------------------------------------------------------
# selective apply — the "accept this hunk, reject that one" UI primitive
# ---------------------------------------------------------------------------

def test_selective_apply_subset():
    a = "".join(f"line {i}\n" for i in range(1, 21))
    b = a.replace("line 3\n", "line 3 changed\n").replace(
        "line 17\n", "line 17 changed\n")
    fp = parse_patch(make_patch(a, b))[0]
    assert len(fp.hunks) == 2

    # Accept only the first hunk -> only line 3 changes.
    only_first = apply_hunks(a, fp.hunks[:1])
    assert "line 3 changed" in only_first
    assert "line 17 changed" not in only_first

    # Accept only the second -> only line 17 changes (offset independent).
    only_second = apply_hunks(a, fp.hunks[1:])
    assert "line 3 changed" not in only_second
    assert "line 17 changed" in only_second


# ---------------------------------------------------------------------------
# newline edge cases (endings travel inside each line)
# ---------------------------------------------------------------------------

def test_no_trailing_newline_roundtrip():
    a = "alpha\nbeta"          # no final newline
    b = "alpha\nBETA"          # still no final newline
    fp = parse_patch(make_patch(a, b))[0]
    got = apply_patch(a, fp)
    assert got == b
    assert not got.endswith("\n")


def test_add_trailing_newline():
    a = "x\ny"                 # no final newline
    b = "x\ny\n"               # gains one
    fp = parse_patch(make_patch(a, b))[0]
    assert apply_patch(a, fp) == b


# ---------------------------------------------------------------------------
# multi-file parse + hand-written (non-difflib) patch shape
# ---------------------------------------------------------------------------

def test_parse_multiple_files():
    a1, b1 = "a1\nl2\n", "A1\nl2\n"
    a2, b2 = "a2\nm2\n", "a2\nM2\n"
    patch = make_patch(a1, b1, path="one.txt") + make_patch(a2, b2, path="two.txt")
    files = parse_patch(patch)
    assert len(files) == 2
    assert files[0].target_path == "one.txt"
    assert files[1].target_path == "two.txt"
    assert apply_patch(a1, files[0]) == b1
    assert apply_patch(a2, files[1]) == b2


def test_hand_written_patch_with_git_headers():
    # A git-style patch (extra header lines the parser must skip).
    patch = (
        "diff --git a/greet.py b/greet.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/greet.py\n"
        "+++ b/greet.py\n"
        "@@ -1,3 +1,3 @@\n"
        " def greet(name):\n"
        '-    return "hi " + name\n'
        '+    return "hello " + name\n'
        " # end\n"
    )
    src = 'def greet(name):\n    return "hi " + name\n# end\n'
    want = 'def greet(name):\n    return "hello " + name\n# end\n'
    files = parse_patch(patch)
    assert len(files) == 1
    assert files[0].target_path == "greet.py"
    assert apply_patch(src, files[0]) == want


# ---------------------------------------------------------------------------
# the UI insight: patched text re-diffs into hunks matching the patch
# ---------------------------------------------------------------------------

def test_patched_rediffs_to_same_change_count():
    a = "".join(f"L{i}\n" for i in range(1, 31))
    b = a.replace("L5\n", "L5!\n").replace("L20\n", "L20!\n")
    fp = parse_patch(make_patch(a, b))[0]
    patched = apply_patch(a, fp)
    # Re-diffing source vs patched yields the same two change regions, i.e.
    # "patch import" reduces to a normal FileDiff(source, patched).
    rediff = parse_patch(make_patch(a, patched))[0]
    assert len(rediff.hunks) == len(fp.hunks) == 2
    assert patched == b
