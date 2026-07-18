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

from PyQt6.QtCore import QFile, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QHeaderView,
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from meldq.dircompare import (
    STATE_ERROR,
    STATE_MISSING,
    STATE_MODIFIED,
    STATE_NEW,
    STATE_NOCHANGE,
    STATE_NORMAL,
    default_name_filters,
    walk,
)
from meldq.widgets.infobar import InfoBar

ROLE_REL = Qt.ItemDataRole.UserRole + 1
ROLE_STATE = Qt.ItemDataRole.UserRole + 2
ROLE_ISDIR = Qt.ItemDataRole.UserRole + 3

# Font decoration per state (bold, italic, strikethrough) — mode-independent.
_DECOR = {
    STATE_NORMAL:   (False, False, False),
    STATE_NOCHANGE: (False, True, False),
    STATE_MODIFIED: (True, False, False),
    STATE_NEW:      (True, False, False),
    STATE_MISSING:  (False, False, True),
    STATE_ERROR:    (True, False, False),
}

# Semantic foreground per theme. None => use the view's palette text colour, so
# NORMAL/NOCHANGE rows follow light/dark automatically (fixing dark-mode
# black-on-grey). The changed/new/error colours are tuned to read on each
# background; the chrome (base/alt-row/text) comes from the OS palette.
_FG = {
    "light": {
        STATE_NORMAL: None, STATE_NOCHANGE: None,
        STATE_MODIFIED: "#1c5fbf", STATE_NEW: "#1a8a1a",
        STATE_MISSING: "#8a8a8a", STATE_ERROR: "#cc0000",
    },
    "dark": {
        STATE_NORMAL: None, STATE_NOCHANGE: None,
        STATE_MODIFIED: "#6ab0ff", STATE_NEW: "#5fd35f",
        STATE_MISSING: "#8a8a8a", STATE_ERROR: "#ff6b6b",
    },
}


def _row_category(entry):
    """Collapse an entry's per-pane states to one filter category: MODIFIED
    (differing or error), NEW (present on some panes only), else NORMAL."""
    if STATE_MODIFIED in entry.states or STATE_ERROR in entry.states:
        return STATE_MODIFIED
    if STATE_NEW in entry.states:
        return STATE_NEW
    return STATE_NORMAL


class DirDiffView(QWidget):
    # Emitted with the list of existing files to compare when a file row is
    # activated; the host opens a FileDiff. Mirrors the MeldDoc create_diff.
    create_diff = pyqtSignal(list)

    def __init__(self, num_panes=2, parent=None):
        super().__init__(parent)
        assert num_panes in (2, 3)
        self.num_panes = num_panes
        self._roots = None
        self._mode = "light"
        self.name_filters = default_name_filters()   # hide .git/.svn/… by default
        self.regexes = []
        self.state_filters = {STATE_NORMAL, STATE_NEW, STATE_MODIFIED}

        self.model = QStandardItemModel()
        self.model.setColumnCount(num_panes)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setAlternatingRowColors(True)    # zebra striping (OS palette)
        self.tree.header().setSectionResizeMode(    # one equal-width column/pane
            QHeaderView.ResizeMode.Stretch)
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
        self._populate(auto_expand_diffs=True)

    def refresh(self):
        # Re-scan, preserving the current expansion (a mutating action or a
        # re-scan shouldn't collapse the tree).
        self._populate(auto_expand_diffs=False)

    def set_state_filters(self, states):
        """Show only rows in these categories (STATE_NORMAL/NEW/MODIFIED)."""
        self.state_filters = set(states)
        self.refresh()

    def _populate(self, auto_expand_diffs):
        expanded = self._expanded_relpaths()
        self.model.removeRows(0, self.model.rowCount())
        if not self._roots:
            return
        entries = list(walk(self._roots, self.name_filters, self.regexes))
        errored = [e.relpath for e in entries if e.error]
        if errored:
            self.infobar.show_message(
                "Some items could not be read and are marked as errors: "
                + ", ".join(errored[:5])
                + (" …" if len(errored) > 5 else ""))
        else:
            self.infobar.clear()
        keep = self._filter_entries(entries)
        items_by_rel = {}
        differing = []
        for entry in entries:
            if entry.relpath not in keep:
                continue
            parent_rel = os.path.dirname(entry.relpath)
            parent_item = items_by_rel.get(parent_rel) or \
                self.model.invisibleRootItem()
            row = self._make_row(entry)
            parent_item.appendRow(row)
            items_by_rel[entry.relpath] = row[0]
            if entry.different:
                differing.append(entry.relpath)

        to_expand = set(expanded)
        if auto_expand_diffs:
            for rel in differing:
                to_expand.update(self._ancestors(rel))
        for rel in sorted(to_expand):
            item = items_by_rel.get(rel)
            if item is not None:
                self.tree.expand(item.index())

    def _filter_entries(self, entries):
        """Relpaths to show: files matching the state filter (+ dirs that match,
        e.g. a wholly-new folder), plus every ancestor directory of a shown row
        so the path to it stays visible."""
        if self.state_filters >= {STATE_NORMAL, STATE_NEW, STATE_MODIFIED}:
            return {e.relpath for e in entries}
        keep = set()
        for entry in entries:
            if _row_category(entry) in self.state_filters:
                keep.add(entry.relpath)
        for rel in list(keep):
            keep.update(self._ancestors(rel))
        return keep

    @staticmethod
    def _ancestors(relpath):
        parts = relpath.split(os.sep)
        return {os.sep.join(parts[:i]) for i in range(1, len(parts))}

    def _expanded_relpaths(self):
        result = set()

        def visit(parent):
            for r in range(self.model.rowCount(parent)):
                idx = self.model.index(r, 0, parent)
                if self.tree.isExpanded(idx):
                    rel = self.row_relpath(idx)
                    if rel:
                        result.add(rel)
                    visit(idx)

        visit(QModelIndex())
        return result

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
                item.setToolTip(self._size_time_tooltip(entry.paths[pane]))
            self._style(item, entry.states[pane])
            items.append(item)
        return items

    @staticmethod
    def _size_time_tooltip(path):
        """Size + modification time for a cell's file (the size/time info the
        v1 scope calls for, surfaced as a tooltip rather than extra columns)."""
        try:
            st = os.stat(path)
        except OSError:
            return ""
        import datetime
        when = datetime.datetime.fromtimestamp(st.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S")
        if os.path.isdir(path):
            return "Folder\nModified: %s" % when
        size = st.st_size
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                shown = ("%d %s" % (size, unit) if unit == "B"
                         else "%.1f %s" % (size, unit))
                break
            size /= 1024
        return "Size: %s\nModified: %s" % (shown, when)

    def _style(self, item, state):
        bold, italic, strike = _DECOR.get(state, _DECOR[STATE_NORMAL])
        fg = _FG[self._mode].get(state)
        if fg is not None:
            item.setForeground(QBrush(QColor(fg)))
        else:
            # Clear any override so the row uses the palette text colour, which
            # follows light/dark with the OS.
            item.setData(None, Qt.ItemDataRole.ForegroundRole)
        font = QFont()
        font.setBold(bold)
        font.setItalic(italic)
        font.setStrikeOut(strike)
        item.setFont(font)

    # ----- theming ----------------------------------------------------------

    def set_theme(self, mode):
        """Switch the semantic state colours to the light or dark palette and
        restyle the existing rows. The chrome (background, alternate-row shade,
        default text) comes from the OS palette, so it needs no work here."""
        self._mode = "dark" if mode == "dark" else "light"
        self._restyle()

    def _restyle(self):
        def visit(parent):
            for r in range(self.model.rowCount(parent)):
                for c in range(self.num_panes):
                    item = self.model.itemFromIndex(self.model.index(r, c, parent))
                    if item is not None:
                        state = item.data(ROLE_STATE)
                        if state is not None:
                            self._style(item, state)
                visit(self.model.index(r, 0, parent))

        visit(QModelIndex())

    @staticmethod
    def _icon(isdir):
        return QIcon.fromTheme("folder" if isdir else "text-x-generic")

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
        # Emit ALL pane paths (not just the existing ones) so a file present on
        # only one side opens a comparison against an empty, creatable pane —
        # the most useful rows in a directory diff are the new/deleted ones.
        if any(os.path.isfile(p) for p in paths):
            self.create_diff.emit(paths)

    def copy_to(self, index, src_pane, dst_pane):
        """Copy the row's file/dir from src_pane to dst_pane (same relpath)."""
        src, dst = self._path(index, src_pane), self._path(index, dst_pane)
        if src is None or not os.path.lexists(src):   # lexists: also broken links
            return
        # An I/O failure (dir-over-file collision, permissions, full disk) must
        # not abort the app — a slot exception is fatal in PyQt6 — so surface it
        # as a message bar instead. Symlinks are copied as links (not
        # dereferenced), matching 3.24.
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.islink(src):
                if os.path.lexists(dst):
                    if os.path.isdir(dst) and not os.path.islink(dst):
                        shutil.rmtree(dst)
                    else:
                        os.remove(dst)
                os.symlink(os.readlink(src), dst)
            elif os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=True)
            else:
                shutil.copy2(src, dst)
        except OSError as exc:
            self.infobar.show_message("Could not copy: %s" % exc)
            return
        self.refresh()

    def delete(self, index, pane, to_trash=True):
        """Delete the row's file/dir on `pane` (to Trash by default)."""
        path = self._path(index, pane)
        if path is None or not os.path.exists(path):
            return
        try:
            if to_trash:
                if QFile.moveToTrash(path):
                    self.refresh()
                    return
                # Trash is unavailable (NFS, a volume with no trash location).
                # Confirm before an IRREVERSIBLE delete rather than silently
                # destroying the file.
                if not self._confirm(
                        'Could not move "%s" to Trash. Delete it permanently?'
                        % os.path.basename(path)):
                    return
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as exc:
            self.infobar.show_message("Could not delete: %s" % exc)
            return
        self.refresh()

    def _confirm(self, message):
        """Yes/No confirmation for an irreversible action. A method so tests
        (and a future headless caller) can stub it without a modal dialog."""
        from PyQt6.QtWidgets import QMessageBox
        return QMessageBox.question(self, "Confirm", message) \
            == QMessageBox.StandardButton.Yes

    # ----- context menu -----------------------------------------------------

    # Copy directions per pane count: (src, dst, label). 3-way copies between
    # each outer pane and the middle (so copy is reachable, not only in 2-way).
    _COPY_DIRS = {
        2: ((0, 1, "Copy to Right"), (1, 0, "Copy to Left")),
        3: ((0, 1, "Copy Left → Middle"), (1, 0, "Copy Middle → Left"),
            (1, 2, "Copy Middle → Right"), (2, 1, "Copy Right → Middle")),
    }

    def _build_context_menu(self, index):
        menu = QMenu(self.tree)
        compare = QAction("Compare", menu)
        compare.triggered.connect(lambda: self.on_activated(index))
        menu.addAction(compare)
        menu.addSeparator()
        for src, dst, label in self._COPY_DIRS.get(self.num_panes, ()):
            act = QAction(label, menu)
            act.triggered.connect(
                lambda _=False, s=src, d=dst: self.copy_to(index, s, d))
            menu.addAction(act)
        menu.addSeparator()
        for pane in range(self.num_panes):
            act = QAction("Delete (pane %d)" % pane, menu)
            act.triggered.connect(lambda _=False, p=pane: self.delete(index, p))
            menu.addAction(act)
        return menu

    def _context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        menu = self._build_context_menu(index)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # no per-click leak
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
