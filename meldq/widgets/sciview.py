"""MeldSciView — the diff/merge text editor, built on QScintilla.

Replaces the 1.4-era QPlainTextEdit editor. It owns, for one pane:
  * text + syntax highlighting (QScintilla lexers, chosen by file extension);
  * chunk backgrounds (full-line Scintilla *markers*, one per diff kind);
  * inline intra-line highlights (a Scintilla *indicator*);
  * the line-number margin and a minimal light/dark theme;
  * the coordinate/scroll helpers the LinkMap and sync-scroll consume
    (mirrors 3.24 MeldSourceView.get_y_for_line_num and our old editor's
    line_ypos/first_visible_line).

FileDiff decides *which* kind each line-range gets; this view just renders it.
Editability is left to the caller (a diff pane may be read-only).
"""

import os
from dataclasses import dataclass

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontDatabase
from PyQt6.Qsci import (
    QsciLexerBash,
    QsciLexerCPP,
    QsciLexerCSS,
    QsciLexerDiff,
    QsciLexerHTML,
    QsciLexerJava,
    QsciLexerJavaScript,
    QsciLexerJSON,
    QsciLexerMakefile,
    QsciLexerMarkdown,
    QsciLexerPerl,
    QsciLexerPython,
    QsciLexerRuby,
    QsciLexerSQL,
    QsciLexerXML,
    QsciLexerYAML,
    QsciScintilla,
)

# Chunk kinds -> Scintilla marker numbers (full-line background markers).
KIND_DELETE, KIND_INSERT, KIND_REPLACE, KIND_CONFLICT = range(4)
_CHUNK_KINDS = (KIND_DELETE, KIND_INSERT, KIND_REPLACE, KIND_CONFLICT)
_INLINE_INDICATOR = 0
MARKER_ACTION = 8               # merge arrow in the clickable action margin


@dataclass(frozen=True)
class Theme:
    name: str                   # "light"/"dark" — selects the token palette
    paper: str
    text: str
    delete_bg: str
    insert_bg: str
    replace_bg: str
    conflict_bg: str
    inline_bg: str
    selection_bg: str
    caret_line_bg: str = "#f6f8fa"

    def bg_for(self, kind):
        return (self.delete_bg, self.insert_bg,
                self.replace_bg, self.conflict_bg)[kind]


# Editor palettes, colours borrowed from GitHub's "Default Light/Dark" themes
# (github/github-vscode-theme, MIT — and colour values are not copyrightable).
LIGHT = Theme(name="light", paper="#ffffff", text="#1f2328",
              delete_bg="#ffebe9", insert_bg="#e6ffec", replace_bg="#ddf4ff",
              conflict_bg="#fff8c5", inline_bg="#8fb6e1", selection_bg="#cce5ff",
              caret_line_bg="#f6f8fa")
DARK = Theme(name="dark", paper="#0d1117", text="#e6edf3",
             delete_bg="#4b2225", insert_bg="#143d28", replace_bg="#16324f",
             conflict_bg="#3d3115", inline_bg="#3a5a80", selection_bg="#2d4f76",
             caret_line_bg="#161b22")

# Syntax token foreground per theme (GitHub Default Light/Dark). Roles are
# matched to each QScintilla lexer's per-style *description* (lexer-agnostic).
_TOKENS = {
    "light": {
        "default": "#1f2328", "comment": "#6e7781", "keyword": "#cf222e",
        "string": "#0a3069", "number": "#0550ae", "function": "#8250df",
        "type": "#953800", "preprocessor": "#cf222e", "decorator": "#8250df",
        "tag": "#116329", "attribute": "#0550ae", "heading": "#0550ae",
        "error": "#cf222e",
    },
    "dark": {
        "default": "#e6edf3", "comment": "#8b949e", "keyword": "#ff7b72",
        "string": "#a5d6ff", "number": "#79c0ff", "function": "#d2a8ff",
        "type": "#ffa657", "preprocessor": "#ff7b72", "decorator": "#d2a8ff",
        "tag": "#7ee787", "attribute": "#79c0ff", "heading": "#1f6feb",
        "error": "#ff7b72",
    },
}


def _role_for(description):
    """Map a QScintilla lexer style description to a token-palette role.
    Ordered specific-first so e.g. 'Comment block' -> comment, 'Secondary
    keywords and identifiers' -> keyword, 'Escape sequence' -> string."""
    d = description.lower()
    if "comment" in d:
        return "comment"
    if "string" in d or "here document" in d or "backtick" in d \
            or "escape sequence" in d:
        return "string"
    if "keyword" in d:
        return "keyword"
    if "number" in d:
        return "number"
    if "decorator" in d:
        return "decorator"
    if "pre-processor" in d or "preprocessor" in d:
        return "preprocessor"
    if "class" in d or "typedef" in d or "type" in d:
        return "type"
    if "function" in d or "method" in d:
        return "function"
    if "tag" in d:
        return "tag"
    if "attribute" in d or "property" in d:
        return "attribute"
    if "header" in d:
        return "heading"
    if "unclosed" in d or d == "error":
        return "error"
    return "default"           # default text, identifiers, operators

# File extension -> lexer factory. Unknown -> no highlighting.
_LEXERS = {
    ".py": QsciLexerPython, ".pyw": QsciLexerPython,
    ".c": QsciLexerCPP, ".h": QsciLexerCPP, ".cpp": QsciLexerCPP,
    ".cc": QsciLexerCPP, ".cxx": QsciLexerCPP, ".hpp": QsciLexerCPP,
    ".js": QsciLexerJavaScript, ".mjs": QsciLexerJavaScript,
    ".ts": QsciLexerJavaScript,
    ".json": QsciLexerJSON,
    ".html": QsciLexerHTML, ".htm": QsciLexerHTML,
    ".xml": QsciLexerXML, ".svg": QsciLexerXML,
    ".css": QsciLexerCSS,
    ".sh": QsciLexerBash, ".bash": QsciLexerBash,
    ".md": QsciLexerMarkdown, ".markdown": QsciLexerMarkdown,
    ".java": QsciLexerJava,
    ".rb": QsciLexerRuby,
    ".yaml": QsciLexerYAML, ".yml": QsciLexerYAML,
    ".sql": QsciLexerSQL,
    ".pl": QsciLexerPerl, ".pm": QsciLexerPerl,
    ".diff": QsciLexerDiff, ".patch": QsciLexerDiff,
    "makefile": QsciLexerMakefile,
}


class MeldSciView(QsciScintilla):
    focus_changed = pyqtSignal(bool)
    scrolled = pyqtSignal()             # vertical scroll changed (drives sync-scroll)
    action_clicked = pyqtSignal(int)    # merge arrow clicked at this line
    action_shift_clicked = pyqtSignal(int)   # Shift+click: reverse-direction merge
    zoom_changed = pyqtSignal(int)      # USER zoomed this pane (Ctrl+wheel/keypad)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = LIGHT
        self._lexer = None              # hold a ref; QScintilla doesn't own it
        # A uniform monospace font for every style. QScintilla lexers default
        # their *comment* style to "Comic Sans MS" (a long-standing upstream
        # Scintilla in-joke) and strings to Courier; set_base_font forces one
        # font over all styles so the editor stays uniformly monospaced.
        self._base_font = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont)

        self.setUtf8(True)
        self.setFont(self._base_font)
        self.setEolMode(QsciScintilla.EolMode.EolUnix)   # display in \n; text() is \n-only
        self.setIndentationsUseTabs(False)
        self.setTabWidth(4)

        # Line-number margin (0) + a clickable action margin (1) for merge arrows.
        self.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
        self.setMarginLineNumbers(0, True)
        self._update_margin_width()
        self.linesChanged.connect(self._update_margin_width)
        self.setMarginType(1, QsciScintilla.MarginType.SymbolMargin)
        self.setMarginWidth(1, 16)
        self.setMarginSensitivity(1, True)
        self.setMarginMarkerMask(1, 1 << MARKER_ACTION)   # only the arrow shows here
        self.marginClicked.connect(self._on_margin_clicked)

        for kind in _CHUNK_KINDS:
            self.markerDefine(QsciScintilla.MarkerSymbol.Background, kind)
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.StraightBoxIndicator, _INLINE_INDICATOR)
        self.SendScintilla(self.SCI_INDICSETUNDER, _INLINE_INDICATOR, True)

        # Free Ctrl+D from Scintilla's built-in "duplicate line" so the shell's
        # "Next Change" shortcut reaches its QAction instead of silently
        # mutating the buffer while an editor pane has focus.
        self.SendScintilla(self.SCI_CLEARCMDKEY,
                           ord("D") | (self.SCMOD_CTRL << 16))

        # Zoom sync: Scintilla zooms each instance independently (Ctrl+wheel /
        # keypad ±), which desyncs pane line heights. Surface every user zoom
        # via zoom_changed so the shell can apply ONE level app-wide;
        # set_zoom applies silently (no echo, no feedback loop).
        self._applying_zoom = False
        self.SCN_ZOOM.connect(self._on_scn_zoom)

        self.apply_theme(LIGHT)
        # Scroll detection must catch EVERY cause, not just scrollbar drags:
        # caret navigation (next-change jumps via SCI_GOTOPOS), keyboard paging
        # and wheel all scroll Scintilla internally without a QScrollBar
        # valueChanged. SCN_UPDATEUI fires on any view update, so both sources
        # funnel through one first-visible-line change guard.
        self._last_first_visible = 0
        self.verticalScrollBar().valueChanged.connect(self._maybe_emit_scrolled)
        self.SCN_UPDATEUI.connect(self._maybe_emit_scrolled)

    # ----- theme ------------------------------------------------------------

    def _update_margin_width(self):
        """Size the line-number margin to the document's line count (was fixed
        at 5 digits, truncating numbers in >99,999-line files)."""
        if not getattr(self, "_show_line_numbers", True):
            self.setMarginWidth(0, 0)
            return
        digits = max(5, len(str(max(1, self.lines()))))
        self.setMarginWidth(0, "0" * (digits + 1))

    def _maybe_emit_scrolled(self, *_args):
        fv = self.first_visible_line()
        if fv != self._last_first_visible:
            self._last_first_visible = fv
            self.scrolled.emit()

    # ----- zoom (one app-wide level; see shell) -----------------------------

    def _on_scn_zoom(self):
        if not self._applying_zoom:
            self.zoom_changed.emit(self.SendScintilla(self.SCI_GETZOOM))

    def set_zoom(self, level):
        """Apply `level` without re-emitting zoom_changed."""
        self._applying_zoom = True
        try:
            self.zoomTo(int(level))
        finally:
            self._applying_zoom = False

    def set_base_font(self, font):
        """Set the editor font across every style (overriding the lexers'
        Comic-Sans comment / Courier string defaults). Honours the user's
        custom-font preference when the shell passes it in."""
        self._base_font = font
        self.setFont(font)
        if self._lexer is not None:
            self._lexer.setDefaultFont(font)
            self._lexer.setFont(font, -1)

    def apply_theme(self, theme):
        self._theme = theme
        paper, text = QColor(theme.paper), QColor(theme.text)
        self.setColor(text)                     # governs plain (un-lexed) text
        self.setPaper(paper)
        self.setCaretLineBackgroundColor(QColor(theme.caret_line_bg))
        self.setMarginsBackgroundColor(paper)
        self.setMarginsForegroundColor(text)
        self.setSelectionBackgroundColor(QColor(theme.selection_bg))
        self.setCaretForegroundColor(text)
        for kind in _CHUNK_KINDS:
            self.setMarkerBackgroundColor(QColor(theme.bg_for(kind)), kind)
        self.setIndicatorForegroundColor(
            QColor(theme.inline_bg), _INLINE_INDICATOR)
        # Re-assert the lexer's per-style colours so syntax highlighting tracks
        # the theme (and flips fully on an OS light<->dark change).
        self._apply_lexer_theme(theme)

    def _apply_lexer_theme(self, theme):
        """Paint every syntax-token style from the GitHub palette for `theme`.
        Without this, QScintilla lexers keep their built-in light-mode token
        colours (navy keywords, grey default), which are unreadable on a dark
        paper — the classic "black on dark grey" in dark mode."""
        if self._lexer is None:
            return
        paper = QColor(theme.paper)
        tokens = _TOKENS[theme.name]
        default_fg = QColor(tokens["default"])
        self._lexer.setDefaultPaper(paper)
        self._lexer.setDefaultColor(default_fg)
        self._lexer.setPaper(paper, -1)          # uniform background, all styles
        self._lexer.setColor(default_fg, -1)     # baseline foreground
        self._lexer.setFont(self._base_font, -1)
        for style in range(128):
            description = self._lexer.description(style)
            if not description:
                continue
            self._lexer.setColor(QColor(tokens[_role_for(description)]), style)
            self._lexer.setPaper(paper, style)
        self.recolor()                           # repaint with the new styles

    # ----- content / language ----------------------------------------------

    def set_text(self, text):
        ro = self.isReadOnly()
        self.setReadOnly(False)
        self.setText(text)
        self.convertEols(QsciScintilla.EolMode.EolUnix)
        self.setReadOnly(ro)

    def replace_all_text(self, text):
        """Replace the whole document as ONE undoable edit (native Scintilla
        undo), unlike setText which resets the document and clears undo."""
        self.beginUndoAction()
        self.selectAll(True)
        self.replaceSelectedText(text)
        self.endUndoAction()

    def replace_line_range(self, line_from, line_to, seg_lines):
        """Replace document lines [line_from, line_to) with `seg_lines` (a list
        of line strings, no trailing newlines) as ONE undoable edit, WITHOUT
        throwing the view to end-of-document. Unlike replace_all_text
        (selectAll -> caret at EOF -> scroll to EOF), this touches only the
        chunk's range and restores the first visible line, so a merge near the
        top of a long file keeps the user's place."""
        first_visible = self.first_visible_line()
        start = self.positionFromLineIndex(line_from, 0)
        if line_to < self.lines():
            end = self.positionFromLineIndex(line_to, 0)
            payload = ("\n".join(seg_lines) + "\n") if seg_lines else ""
        else:
            end = self.length()
            payload = "\n".join(seg_lines)
        sl, si = self.lineIndexFromPosition(start)
        el, ei = self.lineIndexFromPosition(end)
        self.beginUndoAction()
        self.setSelection(sl, si, el, ei)
        self.replaceSelectedText(payload)
        self.endUndoAction()
        self.scroll_to_line(first_visible)

    # ----- editor display prefs ---------------------------------------------

    def set_show_line_numbers(self, on):
        self._show_line_numbers = bool(on)
        self._update_margin_width()

    def set_show_whitespace(self, on):
        self.setWhitespaceVisibility(
            QsciScintilla.WhitespaceVisibility.WsVisible if on
            else QsciScintilla.WhitespaceVisibility.WsInvisible)

    def set_wrap(self, on):
        self.setWrapMode(QsciScintilla.WrapMode.WrapWord if on
                         else QsciScintilla.WrapMode.WrapNone)

    def set_highlight_current_line(self, on):
        self.setCaretLineVisible(bool(on))

    def set_right_margin(self, column):
        """Show a vertical guide at `column`; None/0 hides it."""
        if column:
            self.setEdgeMode(QsciScintilla.EdgeMode.EdgeLine)
            self.setEdgeColumn(int(column))
        else:
            self.setEdgeMode(QsciScintilla.EdgeMode.EdgeNone)

    def set_syntax_enabled(self, on):
        """Toggle syntax highlighting (re-deriving the lexer from the last
        path set via set_language_for)."""
        on = bool(on)
        if on != getattr(self, "_syntax_enabled", True):
            self._syntax_enabled = on
            self.set_language_for(getattr(self, "_language_path", None))

    def set_language_for(self, path):
        self._language_path = path
        ext = os.path.splitext(path or "")[1].lower()
        factory = _LEXERS.get(ext) or _LEXERS.get(os.path.basename(path or "").lower())
        if not getattr(self, "_syntax_enabled", True):
            factory = None
        if factory is None:
            self._lexer = None
            self.setLexer(None)
            self.apply_theme(self._theme)      # re-assert plain colours
            return
        lexer = factory(self)
        lexer.setDefaultFont(self._base_font)
        self._lexer = lexer                    # keep a Python ref alive
        self.setLexer(lexer)
        # Paint the whole style table from the current theme (background, the
        # GitHub token foregrounds, and the monospace font over Comic Sans).
        self._apply_lexer_theme(self._theme)

    # ----- chunk backgrounds ------------------------------------------------

    def clear_chunks(self):
        for kind in _CHUNK_KINDS:
            self.markerDeleteAll(kind)

    def add_chunk(self, line_from, line_to, kind):
        """Mark [line_from, line_to) (0-based, end-exclusive) with a kind bg."""
        for line in range(line_from, line_to):
            self.markerAdd(line, kind)

    def chunk_kinds_at(self, line):
        mask = self.markersAtLine(line)
        return [k for k in _CHUNK_KINDS if mask & (1 << k)]

    # ----- inline highlights ------------------------------------------------

    def clear_inline(self):
        self.SendScintilla(self.SCI_SETINDICATORCURRENT, _INLINE_INDICATOR)
        self.SendScintilla(self.SCI_INDICATORCLEARRANGE, 0, self.length())

    def add_inline(self, line, col_from, col_to):
        self.fillIndicatorRange(line, col_from, line, col_to, _INLINE_INDICATOR)

    def has_inline_at(self, line, col):
        pos = self.positionFromLineIndex(line, col)
        return bool(self.SendScintilla(
            self.SCI_INDICATORVALUEAT, _INLINE_INDICATOR, pos))

    # ----- action margin (merge arrows) -------------------------------------

    def set_action_symbol(self, symbol):
        """Define the arrow drawn in the action margin (a MarkerSymbol or a
        QPixmap — left/right arrows are drawn as pixmaps by the caller)."""
        self.markerDefine(symbol, MARKER_ACTION)

    def clear_action_markers(self):
        self.markerDeleteAll(MARKER_ACTION)

    def add_action_marker(self, line):
        self.markerAdd(line, MARKER_ACTION)

    def has_action_marker(self, line):
        return bool(self.markersAtLine(line) & (1 << MARKER_ACTION))

    def _on_margin_clicked(self, margin, line, state):
        if margin == 1:
            if state & Qt.KeyboardModifier.ShiftModifier:
                self.action_shift_clicked.emit(line)
            else:
                self.action_clicked.emit(line)

    # ----- coordinates / scroll (for LinkMap + sync-scroll) -----------------

    def line_height(self):
        return self.SendScintilla(self.SCI_TEXTHEIGHT, 0)

    def first_visible_line(self):
        vis = self.SendScintilla(self.SCI_GETFIRSTVISIBLELINE)
        return self.SendScintilla(self.SCI_DOCLINEFROMVISIBLE, vis)

    def lines_on_screen(self):
        return self.SendScintilla(self.SCI_LINESONSCREEN)

    def y_for_line(self, line):
        pos = self.positionFromLineIndex(line, 0)
        return self.SendScintilla(self.SCI_POINTYFROMPOSITION, 0, pos)

    def scroll_to_line(self, line):
        self.SendScintilla(self.SCI_SETFIRSTVISIBLELINE,
                           self.SendScintilla(self.SCI_VISIBLEFROMDOCLINE, line))

    # ----- focus ------------------------------------------------------------

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focus_changed.emit(False)
