from meldq.engine.matchers import MyersSequenceMatcher


def test_identical_inputs_single_terminator_block():
    a = ["one", "two", "three"]
    m = MyersSequenceMatcher(None, a, list(a))
    assert m.get_matching_blocks()[-1] == (len(a), len(a), 0)
    assert m.get_difference_opcodes() == []


def test_difference_opcodes_returns_list():
    m = MyersSequenceMatcher(None, ["a", "b", "c"], ["a", "x", "c"])
    result = m.get_difference_opcodes()
    assert isinstance(result, list)
    assert result == [("replace", 1, 2, 1, 2)]
    # iterating twice gives the same output — the py2 filter() trap
    assert list(result) == list(result)


def test_initialise_yields_none_before_final_one():
    a = [f"line {i}" for i in range(300)]
    b = [f"line {i}" for i in range(0, 300, 2)] + [f"new {i}" for i in range(150)]
    values = list(MyersSequenceMatcher(None, a, b).initialise())
    assert values[-1] == 1
    assert all(v is None for v in values[:-1])
    assert len(values) > 1
