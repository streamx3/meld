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

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
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


@dataclass(frozen=True)
class Theme:
    paper: str
    text: str
    delete_bg: str
    insert_bg: str
    replace_bg: str
    conflict_bg: str
    inline_bg: str

    def bg_for(self, kind):
        return (self.delete_bg, self.insert_bg,
                self.replace_bg, self.conflict_bg)[kind]


# v1: exactly one light + one dark palette (no user color pickers).
LIGHT = Theme(paper="#ffffff", text="#000000",
              delete_bg="#ffdddd", insert_bg="#ddffdd",
              replace_bg="#ddeeff", conflict_bg="#ffe0b0", inline_bg="#8fb6e1")
DARK = Theme(paper="#1e1e1e", text="#d4d4d4",
             delete_bg="#4a2323", insert_bg="#234a23",
             replace_bg="#233a5a", conflict_bg="#5a4423", inline_bg="#3a5a80")

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = LIGHT
        self._lexer = None              # hold a ref; QScintilla doesn't own it

        self.setUtf8(True)
        self.setEolMode(QsciScintilla.EolMode.EolUnix)   # display in \n; text() is \n-only
        self.setIndentationsUseTabs(False)
        self.setTabWidth(4)

        # Line-number margin (0); no symbol margin.
        self.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
        self.setMarginLineNumbers(0, True)
        self.setMarginWidth(0, "00000")
        self.setMarginWidth(1, 0)

        for kind in _CHUNK_KINDS:
            self.markerDefine(QsciScintilla.MarkerSymbol.Background, kind)
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.StraightBoxIndicator, _INLINE_INDICATOR)
        self.SendScintilla(self.SCI_INDICSETUNDER, _INLINE_INDICATOR, True)

        self.apply_theme(LIGHT)
        self.verticalScrollBar().valueChanged.connect(
            lambda _v: self.scrolled.emit())

    # ----- theme ------------------------------------------------------------

    def apply_theme(self, theme):
        self._theme = theme
        paper, text = QColor(theme.paper), QColor(theme.text)
        self.setColor(text)
        self.setPaper(paper)
        self.setMarginsBackgroundColor(paper)
        self.setMarginsForegroundColor(text)
        for kind in _CHUNK_KINDS:
            self.setMarkerBackgroundColor(QColor(theme.bg_for(kind)), kind)
        self.setIndicatorForegroundColor(
            QColor(theme.inline_bg), _INLINE_INDICATOR)
        if self._lexer is not None:
            self._lexer.setDefaultPaper(paper)
            self._lexer.setPaper(paper, -1)

    # ----- content / language ----------------------------------------------

    def set_text(self, text):
        ro = self.isReadOnly()
        self.setReadOnly(False)
        self.setText(text)
        self.convertEols(QsciScintilla.EolMode.EolUnix)
        self.setReadOnly(ro)

    def replace_all_text(self, text):
        """Replace the whole document as ONE undoable edit (native Scintilla
        undo), unlike setText which resets the document and clears undo. Used
        by merge operations so they can be undone."""
        self.beginUndoAction()
        self.selectAll(True)
        self.replaceSelectedText(text)
        self.endUndoAction()

    def set_language_for(self, path):
        ext = os.path.splitext(path or "")[1].lower()
        factory = _LEXERS.get(ext) or _LEXERS.get(os.path.basename(path or "").lower())
        if factory is None:
            self._lexer = None
            self.setLexer(None)
            self.apply_theme(self._theme)      # re-assert plain colours
            return
        lexer = factory(self)
        lexer.setDefaultPaper(QColor(self._theme.paper))
        lexer.setPaper(QColor(self._theme.paper), -1)
        self._lexer = lexer                    # keep a Python ref alive
        self.setLexer(lexer)

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
