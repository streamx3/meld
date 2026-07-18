import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from meldq.widgets.editor import DiffTextEdit


@pytest.fixture
def editor(qapp, qtbot):
    ed = DiffTextEdit()
    ed.set_font_and_tabs(QFont("Monospace", 10), 4)
    ed.setPlainText("\n".join(f"line {i}" for i in range(200)))
    ed.resize(400, 300)
    qtbot.addWidget(ed)
    ed.show()
    qtbot.waitExposed(ed)
    return ed


def test_line_ypos_top(editor):
    editor.verticalScrollBar().setValue(0)
    # line 0's top is at the document margin (viewport-relative), less than a
    # line height; chunk rects use the same coordinate system so they align
    margin = editor.document().documentMargin()
    assert editor.line_ypos(0) == pytest.approx(margin, abs=1.0)
    assert 0 <= editor.line_ypos(0) < editor.line_height()


def test_uniform_line_height(editor):
    editor.verticalScrollBar().setValue(0)
    h = editor.line_height()
    assert h > 0
    first, last = editor.lines_visible()
    for n in range(first, min(last, first + 5)):
        delta = editor.line_ypos(n + 1) - editor.line_ypos(n)
        assert delta == pytest.approx(h, abs=1.0)


def test_line_at_ypos_roundtrip(editor):
    editor.verticalScrollBar().setValue(0)
    first, last = editor.lines_visible()
    for k in range(first, min(last, first + 5)):
        y = int(editor.line_ypos(k)) + 1
        assert editor.line_at_ypos(y) == k


def test_lines_visible_spans_shown(editor):
    editor.verticalScrollBar().setValue(0)
    first, last = editor.lines_visible()
    assert first == 0
    assert last > first
    # the reported last line's top is within the viewport
    assert editor.line_ypos(last - 1) < editor.viewport().height()


def test_eof_sentinel(editor):
    editor.verticalScrollBar().setValue(editor.verticalScrollBar().maximum())
    doc = editor.document()
    last_block_bottom = editor.blockBoundingGeometry(
        doc.lastBlock()).translated(editor.contentOffset()).bottom()
    assert editor.line_ypos(doc.blockCount()) == pytest.approx(last_block_bottom - 1.0)


def test_ctrl_z_does_not_modify_document(editor, qtbot):
    editor.setPlainText("hello")
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    qtbot.keyClicks(editor, " world")
    assert editor.toPlainText() == "hello world"
    qtbot.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    # editor swallows Ctrl+Z; without a window UndoSequence the text is unchanged
    assert editor.toPlainText() == "hello world"


def test_ctrl_d_does_not_duplicate_line(qapp, qtbot):
    from PyQt6.QtCore import Qt
    from meldq.widgets.sciview import MeldSciView
    v = MeldSciView()
    qtbot.addWidget(v)
    v.set_text("line0\nline1\n")
    v.setCursorPosition(0, 0)
    qtbot.keyClick(v, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert v.text() == "line0\nline1\n"     # Ctrl+D no longer duplicates


def test_margin_width_grows_with_line_count(qapp, qtbot):
    from meldq.widgets.sciview import MeldSciView
    v = MeldSciView()
    qtbot.addWidget(v)
    v.set_text("a\nb\n")
    small = v.marginWidth(0)
    v.set_text("".join("l%d\n" % i for i in range(150000)))   # 6-digit lines
    assert v.marginWidth(0) > small                # margin widened to fit
