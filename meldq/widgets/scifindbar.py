"""SciFindBar — find/replace for the QScintilla panes.

A slim bar the FileDiff view shows on Ctrl+F: search field, previous/next,
case-sensitivity toggle, and a replace row (replace / replace-all). Wraps
QScintilla's built-in findFirst/findNext/replace machinery, targeting whichever
pane the caller passes (the focused one). Esc hides it; F3/Shift+F3 keep
working while it is open or closed via the view's shortcuts.

Replaces the one-shot QInputDialog the shell used for Edit ▸ Find.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class SciFindBar(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._editor = None

        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Find")
        self.entry.setClearButtonEnabled(True)
        self.entry.returnPressed.connect(self.find_next)
        self.entry.textChanged.connect(self._restart_search)

        self.prev_btn = QToolButton()
        self.prev_btn.setText("‹")
        self.prev_btn.setToolTip("Previous match (Shift+F3)")
        self.prev_btn.clicked.connect(self.find_prev)
        self.next_btn = QToolButton()
        self.next_btn.setText("›")
        self.next_btn.setToolTip("Next match (F3)")
        self.next_btn.clicked.connect(self.find_next)

        self.case_box = QCheckBox("Match case")
        self.case_box.toggled.connect(self._restart_search)

        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self.hide_bar)

        find_row = QHBoxLayout()
        find_row.setContentsMargins(4, 2, 4, 2)
        find_row.addWidget(self.entry, 1)
        find_row.addWidget(self.prev_btn)
        find_row.addWidget(self.next_btn)
        find_row.addWidget(self.case_box)
        find_row.addWidget(close_btn)

        self.replace_entry = QLineEdit()
        self.replace_entry.setPlaceholderText("Replace with")
        self.replace_btn = QPushButton("Replace")
        self.replace_btn.clicked.connect(self.replace_one)
        self.replace_all_btn = QPushButton("Replace All")
        self.replace_all_btn.clicked.connect(self.replace_all)

        replace_row = QHBoxLayout()
        replace_row.setContentsMargins(4, 0, 4, 2)
        replace_row.addWidget(self.replace_entry, 1)
        replace_row.addWidget(self.replace_btn)
        replace_row.addWidget(self.replace_all_btn)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addLayout(find_row)
        box.addLayout(replace_row)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self,
                  self.hide_bar, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self._search_started = False
        self.setVisible(False)

    # ----- lifecycle --------------------------------------------------------

    def attach(self, editor):
        """Target `editor` (a MeldSciView) for subsequent finds."""
        if editor is not self._editor:
            self._editor = editor
            self._search_started = False

    def show_bar(self, editor):
        self.attach(editor)
        self.setVisible(True)
        # Prefill with the editor's selection, if any.
        if editor is not None and editor.hasSelectedText():
            self.entry.setText(editor.selectedText())
        self.entry.setFocus()
        self.entry.selectAll()

    def hide_bar(self):
        self.setVisible(False)
        self._search_started = False
        if self._editor is not None:
            self._editor.setFocus()
        self.closed.emit()

    # ----- searching --------------------------------------------------------

    def _restart_search(self, *_args):
        # A changed needle/options starts a fresh search from the caret.
        self._search_started = False

    def _find(self, forward):
        editor = self._editor
        text = self.entry.text()
        if editor is None or not text:
            return False
        # findFirst(term, regex, case, whole-word, wrap, forward)
        found = editor.findFirst(text, False, self.case_box.isChecked(),
                                 False, True, forward)
        self._search_started = found
        self._flag_result(found)
        return found

    def find_next(self):
        if self._search_started:
            found = self._editor.findNext() if self._editor else False
            self._flag_result(found)
            return found
        return self._find(True)

    def find_prev(self):
        # QScintilla's findNext always continues in the original direction, so
        # a backward step restarts a backward findFirst from the caret.
        return self._find(False)

    def _flag_result(self, found):
        self.entry.setStyleSheet(
            "" if found or not self.entry.text() else
            "QLineEdit { background: #ffd9d9; color: #55191c; }")

    # ----- replacing --------------------------------------------------------

    def replace_one(self):
        """Replace the current match (finding one first if needed), then move
        to the next."""
        editor = self._editor
        if editor is None or not self.entry.text() or editor.isReadOnly():
            return
        if not editor.hasSelectedText() and not self.find_next():
            return
        editor.replace(self.replace_entry.text())
        self.find_next()

    def replace_all(self):
        editor = self._editor
        needle = self.entry.text()
        if editor is None or not needle or editor.isReadOnly():
            return
        editor.beginUndoAction()
        try:
            # Restart from the top; findFirst(..., wrap=False) so the loop
            # terminates deterministically.
            found = editor.findFirst(needle, False, self.case_box.isChecked(),
                                     False, False, True, 0, 0)
            while found:
                editor.replace(self.replace_entry.text())
                found = editor.findNext()
        finally:
            editor.endUndoAction()
        self._search_started = False
