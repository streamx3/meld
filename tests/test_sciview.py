"""M1: MeldSciView (QScintilla diff editor) — the visual foundation.

Headless assertions read state back through Scintilla (marker masks, indicator
values) the same way the M0 gate spike did.
"""

import pytest
from PyQt6.Qsci import QsciLexerCPP, QsciLexerPython

from meldq.widgets.sciview import (
    DARK,
    KIND_DELETE,
    KIND_INSERT,
    KIND_REPLACE,
    LIGHT,
    MeldSciView,
)


@pytest.fixture
def view(qapp, qtbot):
    v = MeldSciView()
    qtbot.addWidget(v)
    return v


def test_set_and_get_text(view):
    view.set_text("alpha\nbeta\ngamma\n")
    assert view.text() == "alpha\nbeta\ngamma\n"


def test_set_text_respects_readonly_but_still_loads(view):
    view.setReadOnly(True)
    view.set_text("x\ny\n")            # set_text must load even when read-only
    assert view.text() == "x\ny\n"
    assert view.isReadOnly()           # and restore the flag


def test_language_by_extension(view):
    view.set_language_for("module.py")
    assert isinstance(view.lexer(), QsciLexerPython)
    view.set_language_for("main.cpp")
    assert isinstance(view.lexer(), QsciLexerCPP)


def test_language_unknown_extension_no_lexer(view):
    view.set_language_for("data.unknownext")
    assert view.lexer() is None


def test_language_by_basename_makefile(view):
    view.set_language_for("/proj/Makefile")
    assert view.lexer() is not None


def test_chunk_backgrounds(view):
    view.set_text("l0\nl1\nl2\nl3\n")
    view.add_chunk(1, 3, KIND_REPLACE)          # lines 1 and 2 (end-exclusive)
    assert KIND_REPLACE in view.chunk_kinds_at(1)
    assert KIND_REPLACE in view.chunk_kinds_at(2)
    assert view.chunk_kinds_at(0) == []
    assert view.chunk_kinds_at(3) == []


def test_chunk_kinds_are_independent(view):
    view.set_text("l0\nl1\nl2\n")
    view.add_chunk(0, 1, KIND_DELETE)
    view.add_chunk(1, 2, KIND_INSERT)
    assert view.chunk_kinds_at(0) == [KIND_DELETE]
    assert view.chunk_kinds_at(1) == [KIND_INSERT]


def test_clear_chunks(view):
    view.set_text("a\nb\nc\n")
    view.add_chunk(0, 3, KIND_REPLACE)
    view.clear_chunks()
    assert all(view.chunk_kinds_at(i) == [] for i in range(3))


def test_inline_highlight(view):
    view.set_text("hello world\n")
    view.add_inline(0, 0, 5)                     # "hello"
    assert view.has_inline_at(0, 2)
    assert not view.has_inline_at(0, 8)          # "world" not highlighted
    view.clear_inline()
    assert not view.has_inline_at(0, 2)


def test_apply_theme_light_and_dark(view):
    view.set_language_for("x.py")
    view.apply_theme(DARK)
    assert view._theme is DARK
    view.apply_theme(LIGHT)
    assert view._theme is LIGHT                  # switching back must not raise


def test_coordinate_helpers(view):
    view.set_text("\n".join(f"line {i}" for i in range(50)))
    assert view.line_height() > 0
    assert view.first_visible_line() == 0
    assert view.lines_on_screen() >= 0
    assert view.y_for_line(0) <= view.y_for_line(10)  # y increases down the doc


def test_scroll_to_line_does_not_raise(view):
    view.set_text("\n".join(str(i) for i in range(200)))
    view.scroll_to_line(100)                     # exercises SCI_VISIBLEFROMDOCLINE


# ----- font normalisation (kill the QScintilla Comic Sans comment default) ---

def test_lexer_comment_font_is_not_comic_sans(view):
    # QScintilla lexers default the comment style to "Comic Sans MS"; MeldSciView
    # must force a uniform monospace font over every style.
    for path, comment_style in (("x.py", 1), ("x.cpp", 2), ("x.js", 2)):
        view.set_language_for(path)
        fam = view._lexer.font(comment_style).family()
        assert fam != "Comic Sans MS"
        assert fam == view._base_font.family()


def test_set_base_font_propagates_to_lexer(view):
    from PyQt6.QtGui import QFont
    view.set_language_for("x.py")
    view.set_base_font(QFont("Courier New", 13))
    assert view._base_font.family() == "Courier New"       # recorded
    assert view._lexer.font(1).family() == "Courier New"   # comment style follows


# ----- GitHub token palette (readable syntax colours in dark mode) ----------

def test_dark_mode_paints_readable_token_colours(view):
    from meldq.widgets.sciview import _TOKENS
    view.set_language_for("main.py")
    view.apply_theme(DARK)
    lx = view._lexer
    # Not QScintilla's built-in navy/grey (unreadable on dark) — GitHub colours.
    assert lx.color(5).name() == _TOKENS["dark"]["keyword"]     # keyword
    assert lx.color(1).name() == _TOKENS["dark"]["comment"]     # comment
    assert lx.color(3).name() == _TOKENS["dark"]["string"]      # string
    assert lx.color(0).name() == _TOKENS["dark"]["default"]     # default text
    assert lx.paper(0).name() == DARK.paper                     # dark background


def test_theme_flip_reasserts_all_token_styles(view):
    from meldq.widgets.sciview import _TOKENS
    view.set_language_for("main.py")
    view.apply_theme(DARK)
    view.apply_theme(LIGHT)
    assert view._lexer.color(5).name() == _TOKENS["light"]["keyword"]
    view.apply_theme(DARK)                       # flip back must fully re-apply
    assert view._lexer.color(5).name() == _TOKENS["dark"]["keyword"]


def test_role_classifier_maps_descriptions():
    from meldq.widgets.sciview import _role_for
    assert _role_for("Comment block") == "comment"
    assert _role_for("Secondary keywords and identifiers") == "keyword"
    assert _role_for("Double-quoted string") == "string"
    assert _role_for("Escape sequence") == "string"
    assert _role_for("Class name") == "type"
    assert _role_for("Function or method name") == "function"
    assert _role_for("Pre-processor block") == "preprocessor"
    assert _role_for("Identifier") == "default"
    assert _role_for("Operator") == "default"
