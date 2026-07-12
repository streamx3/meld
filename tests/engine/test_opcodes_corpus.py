import difflib
import json
import shutil
from pathlib import Path

import pytest

from meldq.engine.matchers import MyersSequenceMatcher

from .util import apply_opcodes, gnu_diff_counts, validate_opcodes

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "engine" / "opcodes"
CASES = sorted(FIXTURE_DIR.glob("*.json"))
MATCHERS = ["myers", "incremental", "difflib"]


def load(path):
    return json.loads(path.read_text())


def full_opcodes(kind, a, b):
    if kind == "myers":
        return MyersSequenceMatcher(None, a, b).get_opcodes()
    if kind == "incremental":
        diffutil = pytest.importorskip(
            "meldq.engine.diffutil", reason="lands in T2.3")
        return diffutil.IncrementalSequenceMatcher(None, a, b).get_opcodes()
    return difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


@pytest.mark.parametrize("kind", MATCHERS)
@pytest.mark.parametrize("case", CASES, ids=lambda p: p.stem)
def test_reconstruction_and_validity(case, kind):
    data = load(case)
    a, b = data["a"], data["b"]
    opcodes = full_opcodes(kind, a, b)
    validate_opcodes(opcodes, len(a), len(b))
    assert apply_opcodes(a, b, opcodes) == b


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.stem)
def test_myers_matches_expected(case):
    data = load(case)
    if data["expected"] is None:
        pytest.skip("invariant-only fixture")
    matcher = MyersSequenceMatcher(None, data["a"], data["b"])
    got = matcher.get_difference_opcodes()
    assert got == [tuple(op) for op in data["expected"]]


@pytest.mark.skipif(shutil.which("diff") is None, reason="no diff on PATH")
@pytest.mark.parametrize("case", CASES, ids=lambda p: p.stem)
def test_gnu_diff_cross_check(case):
    data = load(case)
    a, b = data["a"], data["b"]
    diffs = MyersSequenceMatcher(None, a, b).get_difference_opcodes()
    removed = sum(i2 - i1 for _, i1, i2, _, _ in diffs)
    added = sum(j2 - j1 for _, _, _, j1, j2 in diffs)
    gnu_removed, gnu_added = gnu_diff_counts(a, b)
    # Both are minimal edit scripts; totals must agree exactly. Verify by
    # hand before ever weakening this assertion.
    assert (removed, added) == (gnu_removed, gnu_added)

    sm_diffs = [c for c in difflib.SequenceMatcher(
        None, a, b, autojunk=False).get_opcodes() if c[0] != "equal"]
    sm_removed = sum(i2 - i1 for _, i1, i2, _, _ in sm_diffs)
    sm_added = sum(j2 - j1 for _, _, _, j1, j2 in sm_diffs)
    assert sm_removed >= removed and sm_added >= added
