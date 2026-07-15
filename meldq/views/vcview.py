"""VcView — the version-control browser (milestone M4, git only).

Lists the files git reports as changed/untracked under a location, coloured by
state; activating one opens a working-vs-repository FileDiff (the committed HEAD
version on the left, the working file on the right — materialising the HEAD
version into a temp file). Commit and the other VC actions layer on next.
"""

import os
import tempfile

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QTreeView, QVBoxLayout, QWidget

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

# state -> (foreground, bold, strikethrough)
_STYLE = {
    gitvc.STATE_MODIFIED: ("#1c5fbf", True, False),
    gitvc.STATE_NEW:      ("#1a8a1a", True, False),
    gitvc.STATE_REMOVED:  ("#cc0000", False, True),
    gitvc.STATE_CONFLICT: ("#d17b00", True, False),
    gitvc.STATE_IGNORED:  ("#999999", False, False),
}


class VcView(QWidget):
    create_diff = pyqtSignal(list)      # [repo_version_path, working_path]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.location = None
        self.repo_root = None
        self._tempdir = None

        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Name", "Status"])
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.activated.connect(self.on_activated)
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
        for relpath, state in sorted(gitvc.status(self.repo_root).items()):
            self.model.appendRow(self._make_row(relpath, state))

    def _make_row(self, relpath, state):
        name = QStandardItem(relpath)
        name.setData(relpath, ROLE_REL)
        name.setData(state, ROLE_STATE)
        status = QStandardItem(_STATE_NAME.get(state, "?"))
        fg, bold, strike = _STYLE.get(state, ("#000000", False, False))
        for item in (name, status):
            item.setEditable(False)
            item.setForeground(QBrush(QColor(fg)))
            font = QFont()
            font.setBold(bold)
            font.setStrikeOut(strike)
            item.setFont(font)
        return [name, status]

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
        head_bytes = gitvc.repo_file_content(self.repo_root, relpath)
        left = self._materialize(relpath, head_bytes)
        right = working if os.path.exists(working) else self._materialize(
            relpath + ".missing", b"")
        self.create_diff.emit([left, right])

    def _materialize(self, relpath, data):
        """Write `data` (the repo version, or empty) to a temp file mirroring
        the repo layout, and return its path."""
        if self._tempdir is None:
            self._tempdir = tempfile.mkdtemp(prefix="meldq-vc-")
        dest = os.path.join(self._tempdir, relpath)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data or b"")
        return dest


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
