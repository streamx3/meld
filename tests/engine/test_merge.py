import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from meldq.engine.merge import AutoMergeDiffer, Merger

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "engine" / "merge3"
CASES = sorted(FIXTURE_DIR.glob("*.json"))


def drain(gen):
    last = None
    for last in gen:
        pass
    return last


def make_merger(local, base, remote):
    merger = Merger()
    sequences = [local, base, remote]
    drain(merger.initialize(sequences, sequences))
    return merger


def test_delete_delete_split_tail_seq1(qapp):
    # Regression for meld/merge.py:131 — undefined `seq2` (NameError) in the
    # delete+delete split when seq1 outlives seq0.
    base = ["a", "b", "c", "d", "e"]
    text0 = ["a", "d", "e"]        # deletes b,c
    text2 = ["a", "e"]             # deletes b,c,d
    d = AutoMergeDiffer()
    d.auto_merge = True
    drain(d.set_sequences_iter([text0, base, text2]))
    changes = list(d.all_changes())
    assert changes == [
        (("delete", 1, 3, 1, 1), ("delete", 1, 3, 1, 1)),
        (("conflict", 3, 4, 1, 2), ("conflict", 3, 4, 1, 1)),
    ]


def test_merge3_marks_tail_conflict(qapp):
    base = ["a", "b", "c", "d", "e"]
    text0 = ["a", "d", "e"]
    text2 = ["a", "e"]
    merger = make_merger(text0, base, text2)
    merged = drain(merger.merge_3_files())
    assert merged == "a\n(??)d\ne"
    assert merger.unresolved == [1]


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.stem)
def test_merge3_fixture(case, qapp):
    data = json.loads(case.read_text())
    merger = make_merger(data["local"], data["base"], data["remote"])
    merged = drain(merger.merge_3_files())
    assert merged == "\n".join(data["merged_lines"])
    assert merger.unresolved == data["unresolved"]


@pytest.mark.skipif(shutil.which("diff3") is None, reason="no diff3 on PATH")
@pytest.mark.parametrize(
    "case", [c for c in CASES if json.loads(c.read_text())["diff3_check"]],
    ids=lambda p: p.stem)
def test_merge3_diff3_cross_check(case, qapp):
    data = json.loads(case.read_text())
    merger = make_merger(data["local"], data["base"], data["remote"])
    merged = drain(merger.merge_3_files())
    with tempfile.TemporaryDirectory() as d:
        paths = {}
        for name in ("local", "base", "remote"):
            paths[name] = os.path.join(d, name)
            with open(paths[name], "w") as f:
                f.write("\n".join(data[name]) + "\n")
        out = subprocess.run(
            ["diff3", "-m", paths["local"], paths["base"], paths["remote"]],
            capture_output=True, text=True)
    assert out.returncode == 0, "diff3 saw conflicts in a clean-merge fixture"
    assert out.stdout == merged + "\n"


def test_merge_2_files_applies_changes_both_directions(qapp):
    base = ["1", "2", "3", "4", "5", "6"]
    local = ["ONE", "2", "3", "4", "5", "6"]
    remote = ["1", "2", "3", "4", "FIVE", "6"]
    merger = make_merger(local, base, remote)
    assert drain(merger.merge_2_files(0, 1)) == "\n".join(local)
    assert drain(merger.merge_2_files(2, 1)) == "\n".join(remote)


def test_merge_2_files_skips_conflicts(qapp):
    base = ["a", "b", "c"]
    merger = make_merger(["a", "X", "c"], base, ["a", "Y", "c"])
    assert drain(merger.merge_2_files(0, 1)) == "\n".join(base)


def test_change_sequence_shifts_unresolved(qapp):
    text = [f"l{i}" for i in range(10)]
    d = AutoMergeDiffer()
    d.auto_merge = True
    drain(d.set_sequences_iter([list(text), list(text), list(text)]))
    d.unresolved = [2, 5, 9]
    edited = text[:4] + text[6:]   # remove 2 lines at line 4
    d.change_sequence(1, 4, -2, [list(text), edited, list(text)])
    # hand-walked meld/merge.py:137-158: lo=1, hi=2 -> [5] dropped, 9 -> 7
    assert d.unresolved == [2, 7]
