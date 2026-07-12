from meldq.engine.diffutil import Differ


def drain(gen):
    for _ in gen:
        pass


def make_differ(*sequences, ignore_blanks=False):
    d = Differ()
    d.ignore_blanks = ignore_blanks
    drain(d.set_sequences_iter(list(sequences)))
    return d


def test_two_way_init_emits_once_and_stores_lists(qapp):
    d = Differ()
    hits = []
    d.diffs_changed.connect(lambda: hits.append(1))
    drain(d.set_sequences_iter([["a", "x", "c"], ["a", "b", "c"]]))
    assert hits == [1]
    assert isinstance(d.diffs[0], list)
    assert d.diffs[0] == [("replace", 1, 2, 1, 2)]


def test_float_index_regression_three_way(qapp):
    # panes 0 and 2 each differ from base: every one of these four calls
    # raises TypeError if the py2 "/2" pane-index divisions survive
    base = ["a", "b", "c"]
    t0 = ["a", "B0", "c"]
    t2 = ["a", "B2", "c"]
    d = make_differ(t0, base, t2)

    changes0 = list(d.single_changes(0))
    changes2 = list(d.single_changes(2))
    assert changes0 == [("conflict", 1, 2, 1, 2)]
    assert changes2 == [("conflict", 1, 2, 1, 2)]

    pair12 = list(d.pair_changes(1, 2))
    pair21 = list(d.pair_changes(2, 1))
    assert pair12 == [("conflict", 1, 2, 1, 2)]
    assert pair21 == [("conflict", 1, 2, 1, 2)]


def test_locate_chunk_line_cache(qapp):
    d = make_differ(["a", "X", "c"], ["a", "b", "c"])
    # pane 1 (base): chunk 0 covers line 1
    assert d.locate_chunk(1, 0) == (None, None, 0)
    assert d.locate_chunk(1, 1) == (0, None, None)
    assert d.locate_chunk(1, 2) == (None, 0, None)
    # one-past-last-line is a valid query (cache allocates l + 1)
    assert d.locate_chunk(1, 3) == (None, 0, None)
    # beyond that: graceful sentinel
    assert d.locate_chunk(1, 4) == (None, None, None)
    # pane 0 sees the same chunk on its own line numbering
    assert d.locate_chunk(0, 1)[0] == 0


def test_change_sequence_matches_fresh_differ(qapp):
    t0 = ["one", "two", "three", "four", "five"]
    t1 = ["one", "two", "X", "four", "five"]
    d = make_differ(t0, t1)

    # insert 2 lines into pane 0 at line 1
    new_t0 = t0[:1] + ["ins1", "ins2"] + t0[1:]
    d.change_sequence(0, 1, 2, [new_t0, t1])

    fresh = make_differ(new_t0, t1)
    assert d.diffs == fresh.diffs
    assert list(d.all_changes()) == list(fresh.all_changes())


def test_three_way_identical_change_is_not_conflict(qapp):
    base = ["a", "b", "c"]
    edited = ["a", "EDIT", "c"]
    d = make_differ(edited, base, list(edited))
    tags = [c[0][0] for c in d.all_changes()]
    assert tags == ["replace"]


def test_three_way_divergent_change_is_conflict(qapp):
    base = ["a", "b", "c"]
    d = make_differ(["a", "X", "c"], base, ["a", "Y", "c"])
    tags = [c[0][0] for c in d.all_changes()]
    assert tags == ["conflict"]


def test_ignore_blanks_drops_blank_only_delete(qapp):
    d = make_differ(["a", "b"], ["a", "", "b"], ignore_blanks=True)
    assert d.diff_count() == 0


def test_ignore_blanks_replace_becomes_insert(qapp):
    # base side of the chunk is a blank line, other side has content
    d = make_differ(["a", "x", "b"], ["a", "", "b"], ignore_blanks=True)
    chunks = [c[0] for c in d.all_changes()]
    assert chunks == [("insert", 2, 2, 1, 2)]


def test_ignore_blanks_replace_becomes_delete(qapp):
    d = make_differ(["a", "", "b"], ["a", "x", "b"], ignore_blanks=True)
    chunks = [c[0] for c in d.all_changes()]
    assert chunks[0][0] == "delete"


def test_sequences_identical(qapp):
    d = Differ()
    assert not d.sequences_identical()
    drain(d.set_sequences_iter([["a", "b"], ["a", "b"]]))
    assert d.sequences_identical()
    d2 = make_differ(["a", "x"], ["a", "b"])
    assert not d2.sequences_identical()
