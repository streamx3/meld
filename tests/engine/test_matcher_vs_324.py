"""M1 engine alignment: prove our MyersSequenceMatcher produces byte-identical
opcodes to Meld 3.24's own matcher.

3.24's meld/matchers/myers.py imports gi only under TYPE_CHECKING, so we can
load it in isolation and diff its output against ours over edge cases and a
seeded random corpus. This is what "the engine matches 3.24" actually means.
"""

import importlib.util
import os
import random

import pytest

from meldq.engine.matchers import MyersSequenceMatcher


def _load_reference():
    path = os.path.join(os.path.dirname(__file__), "..", "..",
                        "meld", "matchers", "myers.py")
    spec = importlib.util.spec_from_file_location("ref_myers_324", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_REF = _load_reference()


def ours(a, b):
    return [tuple(c) for c in MyersSequenceMatcher(None, a, b).get_opcodes()]


def ref(a, b):
    return [tuple(c) for c in _REF.MyersSequenceMatcher(None, a, b).get_opcodes()]


EDGE_CASES = [
    ([], []),
    ([], ["a"]),
    (["a"], []),                       # empty side — 1.4 crashed here
    (["a"], ["a"]),
    (["a", "b", "c"], ["a", "x", "c"]),
    (list("abcdef"), list("abcdef")),
    (list("abcdef"), list("abXdef")),
    (list("abcdef"), list("Xbcdef")),
    (list("abcdef"), list("abcdeX")),
    (list("abcabc"), list("abc")),      # repeats — greedy snakes to coalesce
    (list("abcabcabc"), list("abcXabc")),
    (list("aXbXcX"), list("abc")),
    (["", "", "x"], ["", "x"]),         # blank lines
    (list("the quick brown"), list("the slow brown")),
]


@pytest.mark.parametrize("a,b", EDGE_CASES)
def test_edge_cases_match_324(a, b):
    assert ours(a, b) == ref(a, b)


def test_empty_side_does_not_crash():
    # The exact 1.4 crash the alignment fixes (find_common_prefix on []).
    assert ours([], ["a", "b"]) == ref([], ["a", "b"])
    assert ours(["a", "b"], []) == ref(["a", "b"], [])


def test_random_corpus_matches_324():
    rng = random.Random(20260714)
    for _ in range(800):
        alphabet = "abcd"                # small alphabet -> many coalesce cases
        a = [rng.choice(alphabet) for _ in range(rng.randint(0, 18))]
        b = [rng.choice(alphabet) for _ in range(rng.randint(0, 18))]
        assert ours(a, b) == ref(a, b), (a, b)


def test_postprocess_actually_coalesces():
    # A case where greedy Myers would split a run that postprocess rejoins:
    # both matchers must agree, and the result must not be needlessly fragmented.
    a = list("abcabcabc")
    b = list("abcabc")
    result = ours(a, b)
    assert result == ref(a, b)
    # equal opcodes should be maximal runs, not single-line slivers
    equal_lens = [c[2] - c[1] for c in result if c[0] == "equal"]
    assert max(equal_lens) >= 3
