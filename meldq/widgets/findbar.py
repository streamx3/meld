### Copyright (C) 2002-2009 Stephen Kennedy <stevek@gnome.org>

### This program is free software; you can redistribute it and/or modify
### it under the terms of the GNU General Public License as published by
### the Free Software Foundation; either version 2 of the License, or
### (at your option) any later version.

### This program is distributed in the hope that it will be useful,
### but WITHOUT ANY WARRANTY; without even the implied warranty of
### MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
### GNU General Public License for more details.

### You should have received a copy of the GNU General Public License
### along with this program; if not, write to the Free Software
### Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Find/replace bar operating on any QPlainTextEdit.

Replaces meld/ui/findbar.py + findbar.glade. The regex engine stays
Python `re` (consistent with the app-wide filter dialect); UTF-16 offset
helpers bridge codepoint indices and QTextCursor positions.

Note: hide() is overridden at the Python level only. All 1.4 call sites
are Python; WP6 must call hide(), not setVisible(False), so the
text_edit reset runs.
"""

import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)

from meldq.conf import _
from meldq.util.misc import (
    char_to_utf16_offset,
    gtk_mnemonic_to_qt,
    utf16_to_char_offset,
)
from meldq.widgets.msgarea import _themed_icon


class FindBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.text_edit = None

        m = gtk_mnemonic_to_qt
        self.find_label = QLabel(m(_("_Search for")))
        self.find_label.setObjectName("find_label")
        self.find_entry = QLineEdit()
        self.find_entry.setObjectName("find_entry")
        self.find_label.setBuddy(self.find_entry)

        self.replace_label = QLabel(m(_("Replace _With")))
        self.replace_label.setObjectName("replace_label")
        self.replace_entry = QLineEdit()
        self.replace_entry.setObjectName("replace_entry")
        self.replace_label.setBuddy(self.replace_entry)

        self.find_next_button = QPushButton(m(_("_Next")))
        self.find_next_button.setObjectName("find_next_button")
        self.find_previous_button = QPushButton(m(_("_Previous")))
        self.find_previous_button.setObjectName("find_previous_button")
        self.replace_button = QPushButton(m(_("_Replace")))
        self.replace_button.setObjectName("replace_button")
        self.replace_all_button = QPushButton(m(_("Replace _All")))
        self.replace_all_button.setObjectName("replace_all_button")

        self.findbar_close = QToolButton()
        self.findbar_close.setObjectName("findbar_close")
        self.findbar_close.setIcon(_themed_icon(self, "window-close"))

        self.match_case = QCheckBox(m(_("_Match Case")))
        self.match_case.setObjectName("match_case")
        self.whole_word = QCheckBox(m(_("Who_le word")))
        self.whole_word.setObjectName("whole_word")
        self.regex = QCheckBox(m(_("Regular E_xpression")))
        self.regex.setObjectName("regex")

        layout = QGridLayout(self)
        layout.addWidget(self.find_label, 0, 0)
        layout.addWidget(self.find_entry, 0, 1)
        layout.addWidget(self.find_previous_button, 0, 2)
        layout.addWidget(self.find_next_button, 0, 3)
        layout.addWidget(self.findbar_close, 0, 4)
        layout.addWidget(self.replace_label, 1, 0)
        layout.addWidget(self.replace_entry, 1, 1)
        layout.addWidget(self.replace_button, 1, 2)
        layout.addWidget(self.replace_all_button, 1, 3)
        options = QHBoxLayout()
        options.addWidget(self.match_case)
        options.addWidget(self.whole_word)
        options.addWidget(self.regex)
        options.addStretch(1)
        layout.addLayout(options, 2, 0, 1, 5)

        self.findbar_close.clicked.connect(self.hide)
        self.find_entry.returnPressed.connect(self.find_next_button.click)
        self.replace_entry.returnPressed.connect(self.replace_button.click)
        self.find_entry.textChanged.connect(self._clear_tint)
        self.find_next_button.clicked.connect(lambda: self._find_text(1))
        self.find_previous_button.clicked.connect(
            lambda: self._find_text(1, backwards=True))
        self.replace_button.clicked.connect(self._replace_clicked)
        self.replace_all_button.clicked.connect(self._replace_all_clicked)

    # ----- visibility state machine -----------------------------------------

    def hide(self):
        self.text_edit = None
        super().hide()

    def _set_replace_widgets_visible(self, visible):
        for w in (self.replace_label, self.replace_entry,
                  self.replace_button, self.replace_all_button):
            w.setVisible(visible)

    def start_find(self, text_edit):
        self.text_edit = text_edit
        self._set_replace_widgets_visible(False)
        self.show()
        self.find_entry.setFocus()
        self.find_entry.selectAll()

    def start_find_next(self, text_edit):
        self.text_edit = text_edit
        if self.find_entry.text():
            self.find_next_button.click()
        else:
            self.start_find(text_edit)

    def start_replace(self, text_edit):
        self.text_edit = text_edit
        self._set_replace_widgets_visible(True)
        self.show()
        self.find_entry.setFocus()
        self.find_entry.selectAll()

    def _clear_tint(self):
        self.find_entry.setStyleSheet("")

    # ----- find/replace engine ----------------------------------------------

    def _find_text(self, start_offset=1, backwards=False, wrap=True):
        if self.text_edit is None:
            return False
        text = self.text_edit.toPlainText()
        insert_char = utf16_to_char_offset(text, self.text_edit.textCursor().position())

        tofind = self.find_entry.text()
        if not self.regex.isChecked():
            tofind = re.escape(tofind)
        if self.whole_word.isChecked():
            tofind = r"\b" + tofind + r"\b"
        flags = re.M | (0 if self.match_case.isChecked() else re.I)
        try:
            pattern = re.compile(tofind, flags)
        except re.error as e:
            QMessageBox.critical(self, "Meld",
                                 _("Regular expression error\n'%s'") % e)
            return False

        match = None
        if not backwards:
            match = pattern.search(text, insert_char + start_offset)
            if match is None and wrap:
                match = pattern.search(text, 0)
        else:
            candidates = list(pattern.finditer(text[:insert_char]))
            if candidates:
                match = candidates[-1]
            elif wrap:
                candidates = list(pattern.finditer(text, insert_char))
                if candidates:
                    match = candidates[-1]

        if match is not None:
            start16 = char_to_utf16_offset(text, match.start())
            end16 = char_to_utf16_offset(text, match.end())
            cursor = self.text_edit.textCursor()
            cursor.setPosition(end16)
            cursor.setPosition(start16, QTextCursor.MoveMode.KeepAnchor)
            self.text_edit.setTextCursor(cursor)
            self.text_edit.ensureCursorVisible()
            return True

        cursor = self.text_edit.textCursor()
        cursor.setPosition(cursor.position())    # collapse any selection
        self.text_edit.setTextCursor(cursor)
        self.find_entry.setStyleSheet("QLineEdit { background: #ffdddd; }")
        return False

    @staticmethod
    def _selection_span(cursor):
        if cursor.hasSelection():
            return (cursor.selectionStart(), cursor.selectionEnd())
        return None

    def _replace_clicked(self):
        if self.text_edit is None:
            return
        old = self._selection_span(self.text_edit.textCursor())
        match = self._find_text(0)
        new = self._selection_span(self.text_edit.textCursor())
        if match and old is not None and old == new:
            cursor = self.text_edit.textCursor()
            cursor.beginEditBlock()
            cursor.insertText(self.replace_entry.text())
            self.text_edit.setTextCursor(cursor)
            self._find_text(0)
            cursor.endEditBlock()

    def _replace_all_clicked(self):
        if self.text_edit is None:
            return
        saved = self.text_edit.textCursor()      # auto-adjusts across edits
        work = self.text_edit.textCursor()
        work.movePosition(QTextCursor.MoveOperation.Start)
        self.text_edit.setTextCursor(work)
        work.beginEditBlock()
        try:
            prev_end = -1
            while self._find_text(0, wrap=False):
                cur = self.text_edit.textCursor()
                if (cur.selectionEnd() == cur.selectionStart()
                        and cur.selectionEnd() == prev_end):
                    break                        # zero-length match, no progress
                cur.insertText(self.replace_entry.text())
                self.text_edit.setTextCursor(cur)
                prev_end = cur.position()
        finally:
            work.endEditBlock()
        self.text_edit.setTextCursor(saved)
        self.text_edit.ensureCursorVisible()
