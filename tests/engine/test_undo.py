import pytest
from PyQt6.QtGui import QTextCursor, QTextDocument

from meldq.engine.undo import UndoSequence


def insert_at_end(doc, text):
    cursor = QTextCursor(doc)
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText(text)


def insert_at_start(doc, text):
    cursor = QTextCursor(doc)
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    cursor.insertText(text)


@pytest.fixture
def seq_docs(qapp):
    seq = UndoSequence()
    doc_a, doc_b = QTextDocument(), QTextDocument()
    seq.register_document(doc_a)
    seq.register_document(doc_b)
    return seq, doc_a, doc_b


def test_cross_pane_undo_order(seq_docs):
    seq, a, b = seq_docs
    insert_at_end(a, "first-a")
    insert_at_end(b, "first-b")
    insert_at_start(a, "@")
    assert a.toPlainText() == "@first-a"
    assert len(seq._stack) == 3
    assert seq.can_undo() and not seq.can_redo()

    seq.undo()
    assert a.toPlainText() == "first-a"
    seq.undo()
    assert b.toPlainText() == ""
    seq.undo()
    assert a.toPlainText() == ""
    assert not seq.can_undo() and seq.can_redo()

    seq.redo()
    assert a.toPlainText() == "first-a"
    seq.redo()
    assert b.toPlainText() == "first-b"
    seq.redo()
    assert a.toPlainText() == "@first-a"
    assert seq.can_undo() and not seq.can_redo()


def test_signal_transitions(seq_docs):
    seq, a, b = seq_docs
    undo_log, redo_log = [], []
    seq.can_undo_changed.connect(undo_log.append)
    seq.can_redo_changed.connect(redo_log.append)

    insert_at_end(a, "one")
    insert_at_end(b, "two")
    assert undo_log == [True]          # only on the transition
    assert redo_log == []

    seq.undo()
    assert redo_log == [True]
    seq.undo()
    assert undo_log == [True, False]
    assert redo_log == [True]

    seq.redo()
    seq.redo()
    assert undo_log == [True, False, True]
    assert redo_log == [True, False]


def test_group_is_single_undo_step(seq_docs):
    seq, a, _ = seq_docs
    hits = []
    a.undoCommandAdded.connect(lambda: hits.append(1))

    seq.begin_group(a)
    insert_at_end(a, "hello")
    insert_at_start(a, "*")
    seq.end_group()

    assert len(hits) == 1
    assert len(seq._stack) == 1
    seq.undo()
    assert a.toPlainText() == ""


def test_nested_group_is_single_step(seq_docs):
    seq, a, _ = seq_docs
    seq.begin_group(a)
    seq.begin_group(a)
    insert_at_end(a, "x")
    seq.end_group()
    insert_at_start(a, "y")
    seq.end_group()
    assert len(seq._stack) == 1
    seq.undo()
    assert a.toPlainText() == ""


def test_empty_group_adds_nothing(seq_docs):
    seq, a, _ = seq_docs
    seq.begin_group(a)
    seq.end_group()
    assert len(seq._stack) == 0
    assert not seq.can_undo()


def test_group_multi_doc_asserts(seq_docs):
    seq, a, b = seq_docs
    seq.begin_group(a)
    with pytest.raises(AssertionError):
        seq.begin_group(b)
    seq.end_group()


def test_checkpoint_with_mixed_docs_at_stack_top(seq_docs):
    # Regression for the meld/undo.py:182 IndexError shape: checkpoint on a
    # partially-undone mixed-document stack must not raise.
    seq, a, b = seq_docs
    insert_at_end(a, "a-edit")
    insert_at_end(b, "b-edit")
    seq.undo()                       # stack [A, B], next_redo == 1
    seq.checkpoint(a)                # 1.4 crashed exactly here
    assert seq.is_at_checkpoint(a)


def test_modified_flag_roundtrip(seq_docs):
    seq, a, _ = seq_docs
    log = []
    seq.checkpointed.connect(lambda doc, flag: log.append((doc is a, flag)))
    seq.checkpoint(a)
    assert log == [(True, True)]     # checkpoint() emits unconditionally

    insert_at_end(a, "dirty")
    assert log == [(True, True), (True, False)]
    seq.undo()
    assert log[-1] == (True, True)
    seq.redo()
    assert log[-1] == (True, False)


def test_checkpoint_destroyed_by_divergent_edit(seq_docs):
    seq, a, _ = seq_docs
    insert_at_end(a, "v1")
    seq.checkpoint(a)                # checkpoint at height 1
    seq.undo()
    insert_at_end(a, "v2")           # diverge: checkpointed state unreachable
    assert not seq.is_at_checkpoint(a)
    # height matches the old checkpoint numerically, but it was destroyed
    assert seq._height(a) == 1
    assert seq._checkpoint_heights[a] is None


def test_cross_doc_checkpoint_destroyed_by_truncation(seq_docs):
    seq, a, b = seq_docs
    insert_at_end(a, "a1")
    insert_at_end(b, "b1")
    seq.checkpoint(b)                # B at height 1
    seq.undo()
    seq.undo()
    insert_at_end(a, "a-new")        # truncates the tail containing B's step
    assert seq._checkpoint_heights[b] is None
    assert not seq.is_at_checkpoint(b)


def test_busy_guard(seq_docs):
    seq, a, b = seq_docs
    seq._busy = True
    insert_at_end(a, "ignored")
    assert seq._stack == []
    seq._busy = False

    # use the clean document: the busy-window edit above left an untracked
    # command in a's internal stack that adjacent inserts would merge into
    insert_at_end(b, "tracked")
    stack_len = len(seq._stack)
    assert stack_len == 1
    seq.undo()                       # doc.undo() must not re-record
    assert len(seq._stack) == stack_len
    assert seq._next_redo == stack_len - 1


def test_clear(seq_docs):
    seq, a, b = seq_docs
    insert_at_end(a, "a1")
    insert_at_end(b, "b1")
    seq.checkpoint(a)
    seq.clear()
    assert not seq.can_undo() and not seq.can_redo()
    with pytest.raises(AssertionError):
        seq.undo()
    assert not seq.is_at_checkpoint(a)
    seq.checkpoint(a)
    assert seq.is_at_checkpoint(a)
