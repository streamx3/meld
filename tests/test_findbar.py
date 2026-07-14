import pytest
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QMessageBox, QPlainTextEdit

from meldq.widgets.findbar import FindBar


@pytest.fixture
def fb_edit(qapp, qtbot):
    edit = QPlainTextEdit()
    fb = FindBar()
    qtbot.addWidget(edit)
    qtbot.addWidget(fb)
    return fb, edit


def move_end(edit):
    cursor = edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    edit.setTextCursor(cursor)


def move_start(edit):
    cursor = edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    edit.setTextCursor(cursor)


def test_find_wraps(fb_edit):
    fb, edit = fb_edit
    edit.setPlainText("foo bar foo")
    fb.start_find(edit)
    fb.find_entry.setText("foo")
    move_end(edit)
    assert fb._find_text(1) is True
    assert edit.textCursor().selectionStart() == 0     # wrapped to first match


def test_find_backwards(fb_edit):
    fb, edit = fb_edit
    edit.setPlainText("foo bar foo baz")
    fb.start_find(edit)
    fb.find_entry.setText("foo")
    move_end(edit)
    assert fb._find_text(1, backwards=True) is True
    assert edit.textCursor().selectionStart() == 8     # previous (last) match
    move_start(edit)
    assert fb._find_text(1, backwards=True) is True
    assert edit.textCursor().selectionStart() == 8     # wraps to last


def test_whole_word(fb_edit):
    fb, edit = fb_edit
    edit.setPlainText("words word")
    fb.start_find(edit)
    fb.find_entry.setText("word")
    fb.whole_word.setChecked(True)
    move_start(edit)
    assert fb._find_text(1) is True
    assert edit.textCursor().selectedText() == "word"
    assert edit.textCursor().selectionStart() == 6     # not inside "words"


def test_regex_error_dialog(fb_edit, monkeypatch):
    fb, edit = fb_edit
    edit.setPlainText("hello")
    fb.start_find(edit)
    fb.find_entry.setText("(")
    fb.regex.setChecked(True)
    calls = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: calls.append(a))
    assert fb._find_text(1) is False
    assert len(calls) == 1


def test_no_match_tints_entry(fb_edit):
    fb, edit = fb_edit
    edit.setPlainText("hello")
    fb.start_find(edit)
    fb.find_entry.setText("zzz")
    assert fb._find_text(1) is False
    assert "#ffdddd" in fb.find_entry.styleSheet()
    fb.find_entry.setText("zzzy")       # textChanged clears the tint
    assert fb.find_entry.styleSheet() == ""


def test_replace_only_if_selected(fb_edit):
    fb, edit = fb_edit
    edit.setPlainText("one two one two")
    fb.start_replace(edit)
    fb.find_entry.setText("one")
    fb.replace_entry.setText("X")
    move_start(edit)
    fb._replace_clicked()               # #1: finds, does not replace
    assert edit.toPlainText() == "one two one two"
    fb._replace_clicked()               # #2: selection matches -> replace once
    assert edit.toPlainText() == "X two one two"


def test_replace_all_single_undo(fb_edit):
    fb, edit = fb_edit
    edit.setPlainText("a b a b a")
    fb.start_replace(edit)
    fb.find_entry.setText("a")
    fb.replace_entry.setText("X")
    fb._replace_all_clicked()
    assert edit.toPlainText() == "X b X b X"
    edit.undo()                          # single edit block
    assert edit.toPlainText() == "a b a b a"


@pytest.mark.timeout(5)
def test_replace_all_terminates_when_replacement_contains_pattern(fb_edit):
    fb, edit = fb_edit
    edit.setPlainText("aaa")
    fb.start_replace(edit)
    fb.find_entry.setText("a")
    fb.replace_entry.setText("aa")
    fb._replace_all_clicked()
    assert edit.toPlainText() == "aaaaaa"


@pytest.mark.timeout(5)
def test_replace_all_zero_length_pattern_terminates(fb_edit):
    fb, edit = fb_edit
    edit.setPlainText("ab")
    fb.start_replace(edit)
    fb.find_entry.setText("x*")
    fb.regex.setChecked(True)
    fb.replace_entry.setText("-")
    fb._replace_all_clicked()            # must return, not hang


def test_astral_offsets(fb_edit):
    fb, edit = fb_edit
    edit.setPlainText("\U0001F600\U0001F600 target")
    fb.start_find(edit)
    fb.find_entry.setText("target")
    move_start(edit)
    assert fb._find_text(1) is True
    assert edit.textCursor().selectedText() == "target"
