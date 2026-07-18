"""VcView — the version-control browser (milestone M4, git only).

Lists the files git reports as changed/untracked under a location, coloured by
state; activating one opens a working-vs-repository FileDiff (the committed HEAD
version on the left, the working file on the right — materialising the HEAD
version into a temp file). Commit and the other VC actions layer on next.
"""

import os
import tempfile

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from meldq import gitvc
from meldq.widgets.infobar import InfoBar

ROLE_REL = Qt.ItemDataRole.UserRole + 1
ROLE_STATE = Qt.ItemDataRole.UserRole + 2

_STATE_NAME = {
    gitvc.STATE_MODIFIED: "modified",
    gitvc.STATE_NEW: "new",
    gitvc.STATE_REMOVED: "removed",
    gitvc.STATE_CONFLICT: "conflict",
    gitvc.STATE_IGNORED: "ignored",
}

# state -> (bold, strikethrough) — mode-independent decoration.
_DECOR = {
    gitvc.STATE_MODIFIED: (True, False),
    gitvc.STATE_NEW:      (True, False),
    gitvc.STATE_REMOVED:  (False, True),
    gitvc.STATE_CONFLICT: (True, False),
    gitvc.STATE_IGNORED:  (False, False),
}

# Semantic foreground per theme; the chrome comes from the OS palette.
_FG = {
    "light": {
        gitvc.STATE_MODIFIED: "#1c5fbf", gitvc.STATE_NEW: "#1a8a1a",
        gitvc.STATE_REMOVED: "#cc0000", gitvc.STATE_CONFLICT: "#d17b00",
        gitvc.STATE_IGNORED: "#8a8a8a",
    },
    "dark": {
        gitvc.STATE_MODIFIED: "#6ab0ff", gitvc.STATE_NEW: "#5fd35f",
        gitvc.STATE_REMOVED: "#ff6b6b", gitvc.STATE_CONFLICT: "#f0a54a",
        gitvc.STATE_IGNORED: "#8a8a8a",
    },
}


class VcView(QWidget):
    create_diff = pyqtSignal(list)      # [repo_version_path, working_path]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.location = None
        self.repo_root = None
        self._mode = "light"
        # A TemporaryDirectory (not a bare mkdtemp) so the materialised HEAD
        # versions are cleaned up when the view is GC'd or the process exits,
        # instead of leaking one temp tree per opened VC tab.
        self._tempdir_obj = None

        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Name", "Status"])
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)    # zebra striping (OS palette)
        header = self.tree.header()
        # stretchLastSection (True by default) would force the last column to
        # fill the width, overriding ResizeToContents — turn it off so Name
        # stretches and Status hugs its short label.
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.activated.connect(self.on_activated)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.infobar = InfoBar()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.infobar)
        layout.addWidget(self.tree, 1)

    # ----- loading ----------------------------------------------------------

    def set_location(self, path):
        self.location = os.path.abspath(path)
        self.repo_root = gitvc.find_repo_root(self.location)
        if self.repo_root is None:
            self.infobar.show_message("Not a git repository.")
        else:
            self.infobar.clear()
        self.refresh()

    def refresh(self):
        self.model.removeRows(0, self.model.rowCount())
        if self.repo_root is None:
            return
        # git shells out; if the repo dir vanished or git is missing the call
        # raises OSError. A slot exception is fatal in PyQt6, so degrade to a
        # message bar rather than aborting the app.
        try:
            rows = sorted(gitvc.status(self.repo_root).items())
        except OSError as exc:
            self.infobar.show_message("Version control error: %s" % exc)
            return
        for relpath, state in rows:
            self.model.appendRow(self._make_row(relpath, state))

    def _make_row(self, relpath, state):
        name = QStandardItem(relpath)
        name.setData(relpath, ROLE_REL)
        name.setData(state, ROLE_STATE)
        status = QStandardItem(_STATE_NAME.get(state, "?"))
        self._style_row(name, status, state)
        return [name, status]

    def _style_row(self, name, status, state):
        fg = _FG[self._mode].get(state, "#8a8a8a")
        bold, strike = _DECOR.get(state, (False, False))
        for item in (name, status):
            item.setEditable(False)
            item.setForeground(QBrush(QColor(fg)))
            font = QFont()
            font.setBold(bold)
            font.setStrikeOut(strike)
            item.setFont(font)

    # ----- theming ----------------------------------------------------------

    def set_theme(self, mode):
        """Switch the semantic state colours to the light/dark palette and
        restyle existing rows; the chrome comes from the OS palette."""
        self._mode = "dark" if mode == "dark" else "light"
        for row in range(self.model.rowCount()):
            name = self.model.item(row, 0)
            status = self.model.item(row, 1)
            if name is not None and status is not None:
                self._style_row(name, status, name.data(ROLE_STATE))

    # ----- queries ----------------------------------------------------------

    def row_relpath(self, index):
        item = self.model.itemFromIndex(index.siblingAtColumn(0))
        return item.data(ROLE_REL) if item is not None else None

    def row_state(self, index):
        item = self.model.itemFromIndex(index.siblingAtColumn(0))
        return item.data(ROLE_STATE) if item is not None else None

    # ----- compare vs repository --------------------------------------------

    def on_activated(self, index):
        relpath = self.row_relpath(index)
        if relpath is None or self.repo_root is None:
            return
        working = os.path.join(self.repo_root, relpath)
        try:
            head_bytes = gitvc.repo_file_content(self.repo_root, relpath)
        except OSError as exc:
            self.infobar.show_message("Version control error: %s" % exc)
            return
        left = self._materialize(relpath, head_bytes)
        right = working if os.path.exists(working) else self._materialize(
            relpath + ".missing", b"")
        self.create_diff.emit([left, right])

    # ----- vc actions -------------------------------------------------------

    def _act(self, index, fn):
        relpath = self.row_relpath(index)
        if relpath is not None and self.repo_root is not None:
            try:
                fn(self.repo_root, relpath)
            except OSError as exc:
                self.infobar.show_message("Version control error: %s" % exc)
                return
            self.refresh()

    def add(self, index):
        self._act(index, gitvc.add)

    def remove(self, index):
        rel = self.row_relpath(index)
        if rel is None:
            return
        if not self._confirm(
                'Remove "%s" from version control and delete it from the '
                'working tree?' % rel):
            return
        self._act(index, gitvc.remove)

    def revert(self, index):
        rel = self.row_relpath(index)
        if rel is None:
            return
        # Reverting an untracked/added file deletes the only copy (it is not in
        # git and not in the trash) — confirm before that irreversible loss.
        if self.row_state(index) == gitvc.STATE_NEW and not self._confirm(
                'Revert will permanently delete the untracked file "%s". '
                'Continue?' % rel):
            return
        self._act(index, gitvc.revert)

    def _confirm(self, message):
        """Yes/No confirmation for an irreversible action. A method so tests can
        stub it without a modal dialog."""
        from PyQt6.QtWidgets import QMessageBox
        return QMessageBox.question(self, "Confirm", message) \
            == QMessageBox.StandardButton.Yes

    def _selected_relpaths(self):
        out = []
        for index in self.tree.selectionModel().selectedRows(0):
            rel = self.row_relpath(index)
            if rel:
                out.append(rel)
        return out

    def commit_files(self, relpaths, message):
        """Commit the given files with `message` and refresh (no dialog)."""
        if relpaths and message.strip() and self.repo_root is not None:
            try:
                gitvc.commit(self.repo_root, message, relpaths)
            except OSError as exc:
                self.infobar.show_message("Version control error: %s" % exc)
                return
            self.refresh()

    def on_commit(self):
        if self.repo_root is None:
            return
        files = self._selected_relpaths() or sorted(gitvc.status(self.repo_root))
        if not files:
            return
        dialog = CommitDialog(files, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.commit_files(files, dialog.commit_message())

    def _context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self.tree)
        for label, slot in (("Compare", lambda: self.on_activated(index)),
                            ("Commit…", self.on_commit),
                            ("Add", lambda: self.add(index)),
                            ("Revert", lambda: self.revert(index)),
                            ("Remove", lambda: self.remove(index))):
            action = QAction(label, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _materialize(self, relpath, data):
        """Write `data` (the repo version, or empty) to a temp file mirroring
        the repo layout, and return its path."""
        if self._tempdir_obj is None:
            self._tempdir_obj = tempfile.TemporaryDirectory(prefix="meldq-vc-")
        dest = os.path.join(self._tempdir_obj.name, relpath)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data or b"")
        return dest


class CommitDialog(QDialog):
    """A commit-message dialog listing the files to be committed. Built in code
    (project convention). commit_message() returns the entered text."""

    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Commit")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Commit %d file(s):" % len(files)))
        files_label = QLabel("\n".join(files))
        files_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(files_label)
        layout.addWidget(QLabel("Message:"))
        self.message = QPlainTextEdit()
        self.message.setMinimumHeight(120)
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.message.setFocus()

    def commit_message(self):
        return self.message.toPlainText()


def main(argv=None):
    import sys

    from PyQt6.QtWidgets import QApplication

    argv = list(sys.argv if argv is None else argv)
    location = argv[1] if len(argv) > 1 else "."
    app = QApplication(argv[:1])
    view = VcView()
    view.resize(700, 600)
    windows = []

    def open_diff(paths):
        from meldq.views.filediff import FileDiffView
        fd = FileDiffView(2)
        fd.resize(900, 600)
        fd.set_files(paths)
        fd.show()
        windows.append(fd)

    view.create_diff.connect(open_diff)
    view.set_location(location)
    view.setWindowTitle("meldq — %s" % location)
    view.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
