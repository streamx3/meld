import os
import subprocess
import tempfile

TAGS = {"equal", "replace", "insert", "delete"}


def apply_opcodes(a, b, opcodes):
    """Reconstruct b from a given full opcodes — the universal correctness oracle."""
    out = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            out.extend(a[i1:i2])
        else:
            out.extend(b[j1:j2])
    return out


def validate_opcodes(opcodes, len_a, len_b):
    pos_a = pos_b = 0
    for op in opcodes:
        assert len(op) == 5, op
        tag, i1, i2, j1, j2 = op
        assert tag in TAGS, op
        assert i1 == pos_a and j1 == pos_b, f"gap before {op}"
        assert i1 <= i2 and j1 <= j2, op
        if tag == "insert":
            assert i1 == i2, op
        if tag == "delete":
            assert j1 == j2, op
        if tag == "equal":
            assert i2 - i1 == j2 - j1, op
        pos_a, pos_b = i2, j2
    assert pos_a == len_a and pos_b == len_b, "coverage incomplete"


def gnu_diff_counts(a, b):
    """(removed, added) line counts from GNU/BSD diff's minimal edit script."""
    with tempfile.TemporaryDirectory() as d:
        fa, fb = os.path.join(d, "a"), os.path.join(d, "b")
        with open(fa, "w") as f:
            f.write("\n".join(a) + "\n")
        with open(fb, "w") as f:
            f.write("\n".join(b) + "\n")
        out = subprocess.run(["diff", fa, fb],
                             capture_output=True, text=True).stdout
    removed = sum(1 for line in out.splitlines() if line.startswith("< "))
    added = sum(1 for line in out.splitlines() if line.startswith("> "))
    return removed, added
