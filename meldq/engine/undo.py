### Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>
### Copyright (C) 2009-2010 Kai Willadsen <kai.willadsen@gmail.com>

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

"""Cross-pane undo coordination over QTextDocument-native undo stacks.

The 1.4 action-object machinery (BufferAction/BufferInsertionAction/
BufferDeletionAction and GroupAction) is not ported: recording is
automatic via QTextDocument.undoCommandAdded, which fires exactly once
per new undo step. Re-diffing on edit is driven from
QTextDocument.contentsChange by the file-comparison views, not from
undo bookkeeping.
"""

import functools

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QTextCursor, QTextDocument


class UndoSequence(QObject):
    """One window-level undo stack spanning all panes' documents.

    Undo/redo hit the document the most recent step belongs to; user
    actions group into one step via begin_group/end_group; per-document
    save-point checkpoints drive the modified flag via the checkpointed
    signal.

    Invariant: only UndoSequence may ever call doc.undo()/doc.redo().
    The editor widget swallows Ctrl+Z/Ctrl+Shift+Z/Ctrl+Y so the
    built-in widget undo can never desynchronize the coordinator stack.

    Loading content into a registered document fires undoCommandAdded
    once; either follow the 1.4 flow (load, then clear(), then
    checkpoint(doc)) or wrap loads in setUndoRedoEnabled(False).
    """

    can_undo_changed = pyqtSignal(bool)
    can_redo_changed = pyqtSignal(bool)
    checkpointed = pyqtSignal(object, bool)   # (QTextDocument, is_at_checkpoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._docs = []
        self._stack = []            # one QTextDocument entry per undo step
        self._next_redo = 0         # index into _stack
        self._checkpoint_heights = {}   # doc -> int | None (None = destroyed)
        self._checkpoint_state = {}     # doc -> last emitted flag
        self._group_doc = None
        self._group_cursor = None
        self._group_depth = 0
        self._busy = False
        self._can_undo = False
        self._can_redo = False

    def register_document(self, doc):
        if doc in self._docs:
            return
        doc.setUndoRedoEnabled(True)
        doc.undoCommandAdded.connect(
            functools.partial(self._on_undo_command_added, doc))
        self._docs.append(doc)
        self._checkpoint_heights[doc] = 0
        self._checkpoint_state[doc] = True

    def _height(self, doc):
        return sum(1 for d in self._stack[:self._next_redo] if d is doc)

    def _on_undo_command_added(self, doc):
        if self._busy:
            return
        # Truncate the redo tail. The other documents' internal redo
        # stacks are not cleared by Qt, but this coordinator is the sole
        # caller of doc.redo(), so orphaned internal redo entries are
        # unreachable.
        del self._stack[self._next_redo:]
        for d, height in self._checkpoint_heights.items():
            if height is not None and height > self._height(d):
                self._checkpoint_heights[d] = None
        self._stack.append(doc)
        self._next_redo = len(self._stack)
        self._refresh_can_flags()
        self._refresh_checkpoint(doc)

    def can_undo(self):
        return self._next_redo > 0

    def can_redo(self):
        return self._next_redo < len(self._stack)

    def undo(self):
        assert self._next_redo > 0
        doc = self._stack[self._next_redo - 1]
        self._next_redo -= 1
        self._busy = True
        doc.undo()
        self._busy = False
        self._refresh_can_flags()
        self._refresh_checkpoint(doc)

    def redo(self):
        assert self._next_redo < len(self._stack)
        doc = self._stack[self._next_redo]
        self._next_redo += 1
        self._busy = True
        doc.redo()
        self._busy = False
        self._refresh_can_flags()
        self._refresh_checkpoint(doc)

    def begin_group(self, doc):
        if self._busy:
            return
        if self._group_depth == 0:
            self._group_doc = doc
            self._group_cursor = QTextCursor(doc)
            self._group_cursor.beginEditBlock()
        else:
            assert doc is self._group_doc, \
                "multi-document undo groups are not supported"
            self._group_cursor.beginEditBlock()
        self._group_depth += 1

    def end_group(self):
        if self._busy:
            return
        assert self._group_depth > 0
        self._group_cursor.endEditBlock()
        self._group_depth -= 1
        if self._group_depth == 0:
            self._group_doc = None
            self._group_cursor = None

    def checkpoint(self, doc):
        self._checkpoint_heights[doc] = self._height(doc)
        self._checkpoint_state[doc] = True
        self.checkpointed.emit(doc, True)

    def is_at_checkpoint(self, doc):
        cp = self._checkpoint_heights.get(doc)
        return cp is not None and cp == self._height(doc)

    def clear(self):
        assert self._group_depth == 0
        for doc in self._docs:
            doc.clearUndoRedoStacks(
                QTextDocument.Stacks.UndoAndRedoStacks)
        self._stack.clear()
        self._next_redo = 0
        for doc in self._checkpoint_heights:
            self._checkpoint_heights[doc] = None
        if self._can_undo:
            self._can_undo = False
            self.can_undo_changed.emit(False)
        if self._can_redo:
            self._can_redo = False
            self.can_redo_changed.emit(False)

    def _refresh_can_flags(self):
        can_undo = self.can_undo()
        if can_undo != self._can_undo:
            self._can_undo = can_undo
            self.can_undo_changed.emit(can_undo)
        can_redo = self.can_redo()
        if can_redo != self._can_redo:
            self._can_redo = can_redo
            self.can_redo_changed.emit(can_redo)

    def _refresh_checkpoint(self, doc):
        new = self.is_at_checkpoint(doc)
        if new != self._checkpoint_state.get(doc, True):
            self._checkpoint_state[doc] = new
            self.checkpointed.emit(doc, new)
