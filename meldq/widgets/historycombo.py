### Copyright (C) 2008-2009 Kai Willadsen <kai.willadsen@gmail.com>

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

"""Editable combo box with persistent history, and a file-entry wrapper.

Replaces meld/ui/historyentry.py. History persists under QSettings key
``history/<history_id>`` (gconf and gnomevfs are gone). Stable ids used by
consumers: file_comparison, dir_comparison, vc_directory, direntry,
fileentry, previousentry.
"""

import os

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QPushButton, QWidget

from meldq.conf import _
from meldq.util.misc import gtk_mnemonic_to_qt

MIN_ITEM_LEN = 3                    # historyentry.py:32
DEFAULT_HISTORY_LENGTH = 10         # historyentry.py:33


def _as_str_list(value):
    # QSettings' INI backend returns a bare str for single-element lists,
    # None for missing keys — normalize both (the QSettings bytes/str trap).
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(v) for v in value]


class HistoryCombo(QComboBox):
    def __init__(self, history_id=None, settings=None, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.completer().setCompletionMode(
            self.completer().CompletionMode.InlineCompletion)
        self.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
        self._settings = settings if settings is not None else QSettings()
        self._history_id = history_id
        self._history_length = DEFAULT_HISTORY_LENGTH
        self._load_history()

    def _settings_key(self):
        if self._history_id is None:
            return None
        return f"history/{self._history_id}"

    def prepend_text(self, text):
        if not text:
            return
        if len(text) <= MIN_ITEM_LEN:      # must be LONGER than 3 chars (:95)
            return
        key = self._settings_key()
        if key is not None:
            # Settings-authoritative: build on the CURRENTLY persisted list, not
            # this combo's (possibly stale) in-memory items. Otherwise sibling
            # combos sharing a history_id — the three New-Comparison file rows —
            # each save their own list and the last writer clobbers the rest.
            items = [i for i in _as_str_list(self._settings.value(key))
                     if i != text]
            items.insert(0, text)
            items = items[:self._history_length]
            self._settings.setValue(key, items)
            edited = self.lineEdit().text()
            self.clear()
            for item in items:
                self.addItem(item)
            self.lineEdit().setText(edited)
            return
        # No persistence: just update the combo in place.
        edited = self.lineEdit().text()    # insertItem shifts the line edit
        existing = self.findText(
            text, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive)
        if existing >= 0:
            self.removeItem(existing)
        else:
            while self.count() > self._history_length - 1:
                self.removeItem(self.count() - 1)
        self.insertItem(0, text)
        self.lineEdit().setText(edited)

    def set_history_length(self, n):
        if n <= 0:
            return
        self._history_length = n
        if self.count() > n:
            self._load_history()

    def get_history_length(self):
        return self._history_length

    def clear_history(self):
        # NOT named clear() — QComboBox.clear() already exists
        self.clear()
        self._save_history()

    def set_history_id(self, history_id):
        self._history_id = history_id
        self._load_history()

    def _save_history(self):
        key = self._settings_key()
        if key is None:
            return
        items = [self.itemText(i) for i in range(self.count())]
        self._settings.setValue(key, items)

    def _load_history(self):
        key = self._settings_key()
        edited = self.lineEdit().text()
        self.clear()
        if key is not None:
            for item in _as_str_list(self._settings.value(key))[:self._history_length]:
                self.addItem(item)
        self.lineEdit().setText(edited)


def _expand_filename(filename, default_dir):
    """Verbatim port of historyentry.py:191-202."""
    if not filename:
        return ""
    if os.path.isabs(filename):
        return filename
    if filename.startswith("~"):
        return os.path.expanduser(filename)
    if default_dir:
        return os.path.expanduser(os.path.join(default_dir, filename))
    else:
        return os.path.join(os.getcwd(), filename)


class FileHistoryCombo(QWidget):
    activated = pyqtSignal()           # replaces the glade 'activate' autoconnect

    def __init__(self, history_id=None, browse_dialog_title=None,
                 directory_entry=False, default_path="~", settings=None,
                 parent=None):
        super().__init__(parent)
        self._title = browse_dialog_title
        self._directory_entry = directory_entry
        self._default_path = default_path

        self.combo = HistoryCombo(history_id, settings)
        self.combo.setAccessibleName(_("Path"))
        self.combo.setAccessibleDescription(_("Path to file"))
        browse = QPushButton(gtk_mnemonic_to_qt(_("_Browse...")))
        browse.setAccessibleDescription(_("Pop up a file selector to choose a file"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self.combo, 1)
        layout.addWidget(browse)

        self.combo.lineEdit().returnPressed.connect(self.activated)
        browse.clicked.connect(self._browse_clicked)

        self.setAcceptDrops(True)
        self.combo.lineEdit().setAcceptDrops(False)

    def get_full_path(self):
        text = self.combo.currentText()
        if not text:
            return None
        return _expand_filename(text, self._default_path)

    def set_filename(self, filename):
        self.combo.setEditText(filename)      # text only, NO history write

    def prepend_history(self, text):
        self.combo.prepend_text(text)

    def focus_entry(self):
        self.combo.lineEdit().setFocus()

    def set_default_path(self, path):
        self._default_path = os.path.abspath(path) if path else None

    def set_history_id(self, history_id):
        self.combo.set_history_id(history_id)

    def set_directory_entry(self, is_dir):
        self._directory_entry = is_dir

    def get_directory_entry(self):
        return self._directory_entry

    def _browse_clicked(self):
        start = self.get_full_path() or os.path.expanduser(self._default_path or "~")
        if self._directory_entry:
            path = QFileDialog.getExistingDirectory(
                self, self._title or _("Select directory"), start)
        else:
            path = QFileDialog.getOpenFileName(
                self, self._title or _("Select file"), start)[0]
        if path:
            self.set_filename(path)
            self.activated.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.set_filename(path)
                event.acceptProposedAction()
                self.activated.emit()
                return
