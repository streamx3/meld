import pytest
from PyQt6.QtGui import QTextDocument

from meldq.filediff import FakeText, text_between_lines


def identity(x):
    return x


@pytest.fixture
def doc(qapp):
    d = QTextDocument()
    d.setPlainText("one\ntwo\nthree\nfour\nfive")   # 5 lines, no trailing NL
    return d


def test_slice_matches_split_oracle(doc):
    ft = FakeText(doc, identity)
    oracle = doc.toPlainText().split("\n")
    # a mid-file slice drops the trailing partial element (old __getslice__)
    assert ft[1:3] == oracle[1:3]
    assert ft[0:2] == oracle[0:2]


def test_slice_to_eof_keeps_last(doc):
    ft = FakeText(doc, identity)
    # hi >= blockCount keeps the last split element
    assert ft[0:doc.blockCount()] == doc.toPlainText().split("\n")
    assert ft[3:doc.blockCount()] == ["four", "five"]


def test_slice_open_stop(doc):
    ft = FakeText(doc, identity)
    assert ft[2:] == ["three", "four", "five"]


def test_single_index_unfiltered(qapp):
    d = QTextDocument()
    d.setPlainText("keep XXX this\nsecond")

    def drop_xxx(txt):
        return txt.replace("XXX ", "")

    ft = FakeText(d, drop_xxx)
    # single index returns the raw line, filter NOT applied
    assert ft[0] == "keep XXX this"
    # slice applies the filter
    assert ft[0:1] == ["keep this"]


def test_no_paragraph_separator_leaks(doc):
    ft = FakeText(doc, identity)
    for line in ft[0:doc.blockCount()]:
        assert "\u2029" not in line
    # spaces in content are preserved (not converted to newlines)
    d = QTextDocument()
    d.setPlainText("a b c\nd e")
    assert FakeText(d, identity)[0:2] == ["a b c", "d e"]


def test_text_between_lines_empty_last_block(qapp):
    d = QTextDocument()
    d.setPlainText("a\nb\n")          # trailing newline -> empty last block
    ft = FakeText(d, identity)
    assert ft[0:d.blockCount()] == ["a", "b", ""]
