"""DirDiffView — the fresh folder-comparison view (milestone M3).

A QTreeView with one column per pane, populated from the Qt-free
`meldq.dircompare.walk()` core. Each cell shows a name coloured by its per-pane
state (green new, blue modified, grey/struck missing, red error), and the tree
auto-expands to reveal differences. The scan is synchronous for now; the
scheduler-driven incremental scan, size/mtime columns, filter UI and the
compare/copy/trash-delete actions layer on next.
"""

import os
import shutil

from PyQt6.QtCore import QFile, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import QMenu, QTreeView, QVBoxLayout, QWidget

from meldq.dircompare import (
    STATE_ERROR,
    STATE_MISSING,
    STATE_MODIFIED,
    STATE_NEW,
    STATE_NOCHANGE,
    STATE_NORMAL,
    walk,
)
from meldq.widgets.infobar import InfoBar

ROLE_REL = Qt.ItemDataRole.UserRole + 1
ROLE_STATE = Qt.ItemDataRole.UserRole + 2
ROLE_ISDIR = Qt.ItemDataRole.UserRole + 3

# state -> (foreground, bold, italic, strikethrough)
_STYLE = {
    STATE_NORMAL:   ("#000000", False, False, False),
    STATE_NOCHANGE: ("#000000", False, True, False),
    STATE_MODIFIED: ("#1c5fbf", True, False, False),
    STATE_NEW:      ("#1a8a1a", True, False, False),
    STATE_MISSING:  ("#999999", False, False, True),
    STATE_ERROR:    ("#cc0000", True, False, False),
}


class DirDiffView(QWidget):
    # Emitted with the list of existing files to compare when a file row is
    # activated; the host opens a FileDiff. Mirrors the MeldDoc create_diff.
    create_diff = pyqtSignal(list)

    def __init__(self, num_panes=2, parent=None):
        super().__init__(parent)
        assert num_panes in (2, 3)
        self.num_panes = num_panes
        self._roots = None
        self.name_filters = []
        self.regexes = []

        self.model = QStandardItemModel()
        self.model.setColumnCount(num_panes)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setExpandsOnDoubleClick(False)   # activation opens a diff
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

    def set_roots(self, roots):
        self._roots = [os.path.abspath(r) for r in roots]
        self.model.setHorizontalHeaderLabels(
            [os.path.basename(r.rstrip(os.sep)) or r for r in self._roots])
        self.refresh()

    def refresh(self):
        self.model.removeRows(0, self.model.rowCount())
        if not self._roots:
            return
        items_by_rel = {}
        differing = []
        for entry in walk(self._roots, self.name_filters, self.regexes):
            parent_rel = os.path.dirname(entry.relpath)
            parent_item = items_by_rel.get(parent_rel) or \
                self.model.invisibleRootItem()
            row = self._make_row(entry)
            parent_item.appendRow(row)
            items_by_rel[entry.relpath] = row[0]
            if entry.different:
                differing.append(entry.relpath)
        self._expand_to(differing, items_by_rel)

    def _make_row(self, entry):
        items = []
        for pane in range(self.num_panes):
            item = QStandardItem()
            item.setEditable(False)
            item.setData(entry.relpath, ROLE_REL)
            item.setData(entry.states[pane], ROLE_STATE)
            item.setData(entry.isdir, ROLE_ISDIR)
            if entry.states[pane] != STATE_MISSING:
                item.setText(entry.name)
                item.setIcon(self._icon(entry.isdir))
            self._style(item, entry.states[pane])
            items.append(item)
        return items

    def _style(self, item, state):
        fg, bold, italic, strike = _STYLE.get(state, _STYLE[STATE_NORMAL])
        item.setForeground(QBrush(QColor(fg)))
        font = QFont()
        font.setBold(bold)
        font.setItalic(italic)
        font.setStrikeOut(strike)
        item.setFont(font)

    @staticmethod
    def _icon(isdir):
        return QIcon.fromTheme("folder" if isdir else "text-x-generic")

    def _expand_to(self, differing, items_by_rel):
        to_expand = set()
        for rel in differing:
            parts = rel.split(os.sep)
            for i in range(1, len(parts)):        # every ancestor directory
                to_expand.add(os.sep.join(parts[:i]))
        for rel in sorted(to_expand):
            item = items_by_rel.get(rel)
            if item is not None:
                self.tree.expand(item.index())

    # ----- queries (for tests / later actions) ------------------------------

    def row_state(self, index, pane):
        item = self.model.itemFromIndex(index.siblingAtColumn(pane))
        return item.data(ROLE_STATE) if item is not None else None

    def row_relpath(self, index):
        item = self.model.itemFromIndex(index.siblingAtColumn(0))
        return item.data(ROLE_REL) if item is not None else None

    def _path(self, index, pane):
        rel = self.row_relpath(index)
        return os.path.join(self._roots[pane], rel) if rel is not None else None

    # ----- actions ----------------------------------------------------------

    def on_activated(self, index):
        """Activate a row: a file opens a comparison, a directory toggles."""
        rel = self.row_relpath(index)
        if rel is None or not self._roots:
            return
        paths = [self._path(index, p) for p in range(self.num_panes)]
        if any(os.path.isdir(p) for p in paths):
            col0 = index.siblingAtColumn(0)
            self.tree.setExpanded(col0, not self.tree.isExpanded(col0))
            return
        existing = [p for p in paths if os.path.isfile(p)]
        if existing:
            self.create_diff.emit(existing)

    def copy_to(self, index, src_pane, dst_pane):
        """Copy the row's file/dir from src_pane to dst_pane (same relpath)."""
        src, dst = self._path(index, src_pane), self._path(index, dst_pane)
        if src is None or not os.path.exists(src):
            return
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        self.refresh()

    def delete(self, index, pane, to_trash=True):
        """Delete the row's file/dir on `pane` (to Trash by default)."""
        path = self._path(index, pane)
        if path is None or not os.path.exists(path):
            return
        if to_trash and QFile.moveToTrash(path):
            pass
        elif os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        self.refresh()

    # ----- context menu -----------------------------------------------------

    def _context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self.tree)
        compare = QAction("Compare", menu)
        compare.triggered.connect(lambda: self.on_activated(index))
        menu.addAction(compare)
        menu.addSeparator()
        if self.num_panes == 2:
            to_right = QAction("Copy to Right", menu)
            to_right.triggered.connect(lambda: self.copy_to(index, 0, 1))
            to_left = QAction("Copy to Left", menu)
            to_left.triggered.connect(lambda: self.copy_to(index, 1, 0))
            menu.addAction(to_right)
            menu.addAction(to_left)
        menu.addSeparator()
        for pane in range(self.num_panes):
            act = QAction("Delete (pane %d)" % pane, menu)
            act.triggered.connect(lambda _=False, p=pane: self.delete(index, p))
            menu.addAction(act)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


def main(argv=None):
    import sys

    from PyQt6.QtWidgets import QApplication

    argv = list(sys.argv if argv is None else argv)
    roots = argv[1:4]
    app = QApplication(argv[:1])
    view = DirDiffView(len(roots) if len(roots) in (2, 3) else 2)
    view.resize(300 * view.num_panes, 600)

    windows = []                # keep FileDiff windows alive

    def open_diff(paths):
        from meldq.views.filediff import FileDiffView
        fd = FileDiffView(len(paths) if len(paths) in (2, 3) else 2)
        fd.resize(900, 600)
        fd.set_files(paths[:fd.num_panes])
        fd.setWindowTitle("meldq — " + " : ".join(paths))
        fd.show()
        windows.append(fd)

    view.create_diff.connect(open_diff)
    if len(roots) == view.num_panes:
        view.set_roots(roots)
    view.setWindowTitle("meldq — " + " : ".join(roots) if roots else "meldq")
    view.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
