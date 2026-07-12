### Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>

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

"""Shared tree model for dirdiff and vcview.

Replaces meld/tree.py's DiffTreeStore: one QStandardItemModel with one
column per pane, per-pane state stored in item roles and rendered via
Foreground/Font/Decoration in data() — no Pango markup, no HTML delegate.
"""

import os
from dataclasses import dataclass
from importlib import resources

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)

# STATE constants — canonical for the UI layer; the vc WP imports these or
# keeps values identical. Frozen at range(12) (meld/vc/_vc.py:33-36).
STATE_IGNORED, STATE_NONE, STATE_NORMAL, STATE_NOCHANGE, \
    STATE_ERROR, STATE_EMPTY, STATE_NEW, \
    STATE_MODIFIED, STATE_CONFLICT, STATE_REMOVED, \
    STATE_MISSING, STATE_MAX = range(12)

ROLE_PATH = Qt.ItemDataRole.UserRole + 1    # str | None
ROLE_STATE = Qt.ItemDataRole.UserRole + 2   # int STATE_*
ROLE_ISDIR = Qt.ItemDataRole.UserRole + 3   # bool


@dataclass(frozen=True)
class TextStyle:
    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False


# Transcribed from meld/tree.py:49-61 (Pango markup -> role styling).
DEFAULT_TEXT_STYLES = [
    TextStyle(fg="#888888"),                                  # IGNORED
    TextStyle(fg="#888888"),                                  # NONE
    TextStyle(fg="black"),                                    # NORMAL
    TextStyle(fg="black", italic=True),                       # NOCHANGE
    TextStyle(fg="#ff0000", bg="yellow", bold=True),          # ERROR
    TextStyle(fg="#999999", italic=True),                     # EMPTY
    TextStyle(fg="#008800", bold=True),                       # NEW
    TextStyle(fg="#880000", bold=True),                       # MODIFIED
    TextStyle(fg="#ff0000", bg="#ffeeee", bold=True),         # CONFLICT
    TextStyle(fg="#880000", bold=True, strikethrough=True),   # REMOVED
    TextStyle(fg="#888888", strikethrough=True),              # MISSING
]
assert len(DEFAULT_TEXT_STYLES) == STATE_MAX

# (icon_filename, width) pairs per state (tree.py:30-38, :63-76); None = no icon.
_ICON_FILES = [
    ("tree-file-normal.png", "tree-folder-normal.png"),      # IGNORED
    ("tree-file-normal.png", "tree-folder-normal.png"),      # NONE
    ("tree-file-normal.png", "tree-folder-normal.png"),      # NORMAL
    ("tree-file-normal.png", "tree-folder-normal.png"),      # NOCHANGE
    (None, None),                                            # ERROR
    (None, None),                                            # EMPTY
    ("tree-file-new.png", "tree-folder-new.png"),            # NEW
    ("tree-file-changed.png", "tree-folder-changed.png"),    # MODIFIED
    ("tree-file-changed.png", "tree-folder-changed.png"),    # CONFLICT
    ("tree-file-changed.png", "tree-folder-changed.png"),    # REMOVED
    ("tree-file-missing.png", "tree-folder-missing.png"),    # MISSING
]

_icon_cache = None


def state_icons():
    """Lazily load the (file_icon, folder_icon) pair for each state.

    Lazy because QPixmap requires a running QGuiApplication (tree.py:30-38
    loaded at import; Qt cannot).
    """
    global _icon_cache
    if _icon_cache is not None:
        return _icon_cache
    icon_dir = resources.files("meldq") / "resources" / "icons"

    def load(name, width):
        if name is None:
            return None
        pixmap = QPixmap(str(icon_dir / name)).scaledToWidth(
            width, Qt.TransformationMode.SmoothTransformation)
        return QIcon(pixmap)

    _icon_cache = [(load(f, 14), load(d, 20)) for f, d in _ICON_FILES]
    return _icon_cache


class DiffTreeModel(QStandardItemModel):
    def __init__(self, ntree=3, extra_cols=0, parent=None):
        super().__init__(0, ntree + extra_cols, parent)
        self.ntree = ntree
        self.extra_cols = extra_cols
        # instance-level so vcview can override one entry (vcview.py:92)
        self.text_styles = list(DEFAULT_TEXT_STYLES)

    def _row_items(self):
        return [QStandardItem() for _ in range(self.ntree + self.extra_cols)]

    def _parent_item(self, parent):
        if parent is None or not parent.isValid():
            return self.invisibleRootItem()
        return self.itemFromIndex(parent.siblingAtColumn(0))

    def add_entries(self, parent, names):
        items = self._row_items()
        self._parent_item(parent).appendRow(items)
        for pane, name in enumerate(names):
            if pane < self.ntree:
                items[pane].setData(name, ROLE_PATH)
        return items[0].index()

    def add_empty(self, parent, text="empty folder"):
        items = self._row_items()
        self._parent_item(parent).appendRow(items)
        for pane in range(self.ntree):
            items[pane].setData(STATE_EMPTY, ROLE_STATE)
            items[pane].setData(None, ROLE_PATH)
            items[pane].setText(text)
        return items[0].index()

    def add_error(self, parent, msg, pane):
        items = self._row_items()
        self._parent_item(parent).appendRow(items)
        for i in range(self.ntree):
            items[i].setData(STATE_ERROR, ROLE_STATE)
        items[pane].setText(msg)
        return items[0].index()

    def value_path(self, index, pane):
        item = self.itemFromIndex(index.siblingAtColumn(pane))
        return item.data(ROLE_PATH) if item is not None else None

    def value_paths(self, index):
        return [self.value_path(index, pane) for pane in range(self.ntree)]

    def set_state(self, index, pane, state, isdir=False):
        item = self.itemFromIndex(index.siblingAtColumn(pane))
        item.setData(state, ROLE_STATE)
        item.setData(bool(isdir), ROLE_ISDIR)
        path = item.data(ROLE_PATH)
        if path is not None:
            item.setText(os.path.basename(path))

    def get_state(self, index, pane):
        item = self.itemFromIndex(index.siblingAtColumn(pane))
        return item.data(ROLE_STATE)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and index.column() < self.ntree:
            state = super().data(index, ROLE_STATE)
            if state is not None and 0 <= state < len(self.text_styles):
                style = self.text_styles[state]
                if role == Qt.ItemDataRole.ForegroundRole and style.fg:
                    return QBrush(QColor(style.fg))
                if role == Qt.ItemDataRole.BackgroundRole and style.bg:
                    return QBrush(QColor(style.bg))
                if role == Qt.ItemDataRole.FontRole:
                    font = QFont()
                    font.setBold(style.bold)
                    font.setItalic(style.italic)
                    font.setStrikeOut(style.strikethrough)
                    return font
                if role == Qt.ItemDataRole.DecorationRole:
                    isdir = bool(super().data(index, ROLE_ISDIR))
                    return state_icons()[state][1 if isdir else 0]
        return super().data(index, role)
