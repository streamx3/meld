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

"""Version-control comparison view (port of meld/vcview.py).

WP7.8 lands the tree model, the view skeleton (combo/console/layout) and the
VC-plugin chooser; WP7.9 the recursive scan generator, filters and navigation.
The command pipeline, VC actions and commit dialog follow in WP7.10-7.12.
"""

import os
import shutil
from importlib import resources

from PyQt6.QtCore import QPersistentModelIndex, Qt
from PyQt6.QtGui import QAction, QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from meldq import vc
from meldq.conf import _
from meldq.doc import RESULT_OK, Direction, MeldDoc
from meldq.util import misc
from meldq.util.misc import gtk_mnemonic_to_qt
from meldq.widgets.historycombo import FileHistoryCombo
from meldq.widgets.msgarea import MsgAreaController, ResponseId
from meldq.widgets.treemodel import (
    ROLE_PATH,
    STATE_EMPTY,
    STATE_IGNORED,
    STATE_MISSING,
    STATE_NEW,
    STATE_NONE,
    STATE_NORMAL,
    DiffTreeModel,
    TextStyle,
)

# Column layout (replaces meld/tree.py's interleaved scheme). Column 0 is the
# pane column carrying ROLE_PATH/ROLE_STATE/ROLE_ISDIR; 1-5 are plain text.
COL_NAME, COL_LOCATION, COL_STATUS, COL_REVISION, COL_TAG, COL_OPTIONS = range(6)


def _bundled_icon(name):
    return QIcon(str(resources.files("meldq") / "resources" / "icons" / name))


def _commonprefix(files):
    if len(files) != 1:
        workdir = misc.commonprefix(files)
    else:
        workdir = os.path.dirname(files[0]) or "."
    return workdir


class VcTreeModel(DiffTreeModel):
    def __init__(self, parent=None):
        super().__init__(ntree=1, extra_cols=5, parent=parent)
        self.setHorizontalHeaderLabels([
            _("Name"), _("Location"), _("Status"), _("Rev"), _("Tag"),
            _("Options")])
        # Missing files: dark-blue, bold, struck through (vcview.py:92).
        self.text_styles[STATE_MISSING] = TextStyle(
            fg="#000088", bold=True, strikethrough=True)

    def set_columns(self, index, location, status, rev, tag, options):
        """Set the five text columns for the row `index` (column 0) points at.

        add_entries already appended a full row (ntree + extra_cols items), so
        the sibling items exist; we only fill their display text.
        """
        for col, text in ((COL_LOCATION, location), (COL_STATUS, status),
                          (COL_REVISION, rev), (COL_TAG, tag),
                          (COL_OPTIONS, options)):
            item = self.itemFromIndex(index.siblingAtColumn(col))
            if item is not None:
                item.setText(text or "")


class VcTreeView(QTreeView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAllColumnsShowFocus(True)
        self.setHeaderHidden(False)

    def mousePressEvent(self, event):
        # A right-click on an already-selected row must keep the whole multi-
        # selection (so the context menu acts on all of it), replicating the
        # return-value trick at meld/vcview.py:399-403.
        if event.button() == Qt.MouseButton.RightButton:
            index = self.indexAt(event.pos())
            if index.isValid() and index.siblingAtColumn(0) in \
                    self.selectionModel().selectedRows(0):
                return
        super().mousePressEvent(event)


# ----- filters (verbatim from meld/vcview.py:97-100) -------------------------
entry_modified = lambda x: (x.state >= STATE_NEW) or (x.isdir and (x.state > STATE_NONE))  # noqa: E731
entry_normal = lambda x: (x.state == STATE_NORMAL)  # noqa: E731
entry_nonvc = lambda x: (x.state == STATE_NONE) or (x.isdir and (x.state > STATE_IGNORED))  # noqa: E731
entry_ignored = lambda x: (x.state == STATE_IGNORED) or x.isdir  # noqa: E731


class VcView(MeldDoc):

    def __init__(self, prefs):
        super().__init__(prefs)

        self.tempdirs = []
        self.location = None
        self.vc = None

        self.widget = QWidget()
        outer = QVBoxLayout(self.widget)

        self.msgarea = MsgAreaController()
        outer.addWidget(self.msgarea)

        top_row = QHBoxLayout()
        self.fileentry = FileHistoryCombo(
            history_id="direntry", directory_entry=True)
        self.fileentry.activated.connect(self.on_fileentry_activate)
        self.combobox_vcs = QComboBox()
        top_row.addWidget(self.fileentry, 1)
        top_row.addWidget(self.combobox_vcs)
        outer.addLayout(top_row)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.treeview = VcTreeView()
        self.model = VcTreeModel()
        self.treeview.setModel(self.model)
        self.treeview.activated.connect(self.on_row_activated)
        self.splitter.addWidget(self.treeview)
        self.splitter.addWidget(self._build_console())
        self.splitter.setSizes([250, 70])
        outer.addWidget(self.splitter, 1)

        self._make_filter_actions()
        self._make_command_actions()
        self._build_menus()
        self.treeview.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.treeview.customContextMenuRequested.connect(self._tree_context_menu)
        self.treeview.setColumnHidden(
            COL_LOCATION, not self.action_flatten.isChecked())

        self.combobox_vcs.currentIndexChanged.connect(self.on_vc_change)

    # ----- console ----------------------------------------------------------

    def _build_console(self):
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)

        self.console_toggle = QToolButton()
        self.console_toggle.setAutoRaise(True)
        self.console_toggle.setCheckable(True)
        self.consoleview = QPlainTextEdit()
        self.consoleview.setReadOnly(True)
        self.consoleview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.consoleview.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.consoleview.customContextMenuRequested.connect(
            self._console_context_menu)
        self.consolestream = _ConsoleStream(self.consoleview)

        layout.addWidget(self.console_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.consoleview)

        visible = bool(self.prefs.vc_console_visible)
        self.console_toggle.setChecked(visible)
        self.consoleview.setVisible(visible)
        self.console_toggle.setArrowType(
            Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)
        self.console_toggle.toggled.connect(self._on_console_toggle)
        return section

    def _on_console_toggle(self, checked):
        self.prefs.vc_console_visible = checked
        self.consoleview.setVisible(checked)
        self.console_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def _console_context_menu(self, pos):
        menu = self.consoleview.createStandardContextMenu()
        first = menu.actions()[0] if menu.actions() else None
        clear = QAction(_("Clear"), menu)
        clear.triggered.connect(self.consoleview.clear)
        menu.insertAction(first, clear)
        menu.insertSeparator(first)
        menu.exec(self.consoleview.mapToGlobal(pos))

    # ----- filter/flatten toggle actions ------------------------------------

    def _make_filter_actions(self):
        w = self.widget

        def toggle(text, icon, tip, checked):
            action = QAction(gtk_mnemonic_to_qt(text), w)
            if icon:
                action.setIcon(_bundled_icon(icon))
            action.setStatusTip(tip)
            action.setCheckable(True)
            action.setChecked(checked)
            return action

        self.action_flatten = toggle(
            _("_Flatten"), None, _("Flatten directories"), True)
        self.action_flatten.setIcon(QIcon.fromTheme("go-bottom"))
        self.action_filter_modified = toggle(
            _("_Modified"), "filter-modified-24.png", _("Show modified"), True)
        self.action_filter_normal = toggle(
            _("_Normal"), "filter-normal-24.png", _("Show normal"), False)
        self.action_filter_nonvc = toggle(
            _("Non _VC"), "filter-nonvc-24.png", _("Show unversioned files"),
            False)
        self.action_filter_ignored = toggle(
            _("Ignored"), "filter-ignored-24.png", _("Show ignored files"),
            False)

        # Connect only after the initial checked state is set, so toggling
        # during construction doesn't call refresh() before self.vc exists.
        self.action_flatten.toggled.connect(self.on_button_flatten_toggled)
        for action in (self.action_filter_modified, self.action_filter_normal,
                       self.action_filter_nonvc, self.action_filter_ignored):
            action.toggled.connect(self.on_button_filter_toggled)

    def on_button_flatten_toggled(self, checked=False):
        self.treeview.setColumnHidden(
            COL_LOCATION, not self.action_flatten.isChecked())
        self.refresh()

    def on_button_filter_toggled(self, checked=False):
        self.refresh()

    # ----- VC plugin chooser ------------------------------------------------

    # ----- command actions / contributions ----------------------------------

    def _make_command_actions(self):
        w = self.widget

        def make(text, bundled, theme, tip, slot):
            action = QAction(gtk_mnemonic_to_qt(text), w)
            if theme:
                action.setIcon(QIcon.fromTheme(theme))
            elif bundled:
                action.setIcon(_bundled_icon(bundled))
            action.setStatusTip(tip)
            action.triggered.connect(slot)
            return action

        self.action_compare = make(
            _("_Compare"), None, "dialog-information", _("Compare selected"),
            self.on_button_diff_clicked)
        self.action_open = make(
            _("Open"), None, "document-open", _("Open selected"),
            self.on_button_open_clicked)
        self.action_commit = make(
            _("_Commit"), "vc-commit-24.png", None, _("Commit"),
            self.on_button_commit_clicked)
        self.action_update = make(
            _("_Update"), "vc-update-24.png", None, _("Update"),
            self.on_button_update_clicked)
        self.action_add = make(
            _("_Add"), "vc-add-24.png", None, _("Add to VC"),
            self.on_button_add_clicked)
        self.action_add_binary = make(
            _("Add _Binary"), None, "list-add", _("Add binary to VC"),
            self.on_button_add_binary_clicked)
        self.action_remove = make(
            _("_Remove"), "vc-remove-24.png", None, _("Remove from VC"),
            self.on_button_remove_clicked)
        self.action_resolved = make(
            _("_Resolved"), "vc-resolve-24.png", None,
            _("Mark as resolved for VC"), self.on_button_resolved_clicked)
        self.action_revert = make(
            _("Revert"), None, "document-revert", _("Revert to original"),
            self.on_button_revert_clicked)
        self.action_delete_locally = make(
            _("Delete"), None, "edit-delete", _("Delete locally"),
            self.on_button_delete_clicked)

    def _build_menus(self):
        self.vcstatus_menu = QMenu(
            gtk_mnemonic_to_qt(_("Version status")), self.widget)
        for action in (self.action_filter_modified, self.action_filter_normal,
                       self.action_filter_nonvc, self.action_filter_ignored):
            self.vcstatus_menu.addAction(action)

    def _tree_context_menu(self, pos):
        menu = QMenu(self.treeview)
        menu.addAction(self.action_compare)
        menu.addAction(self.action_update)
        menu.addAction(self.action_commit)
        menu.addSeparator()
        menu.addAction(self.action_open)
        menu.addSeparator()
        menu.addAction(self.action_add)
        menu.addAction(self.action_add_binary)
        menu.addAction(self.action_resolved)
        menu.addAction(self.action_remove)
        menu.addAction(self.action_revert)
        menu.addSeparator()
        menu.addAction(self.action_delete_locally)
        menu.exec(self.treeview.viewport().mapToGlobal(pos))

    def doc_actions(self):
        return [self.action_compare, self.action_open, self.action_commit,
                self.action_update, self.action_add, self.action_add_binary,
                self.action_remove, self.action_resolved, self.action_revert,
                self.action_delete_locally, self.action_flatten,
                self.action_filter_modified, self.action_filter_normal,
                self.action_filter_nonvc, self.action_filter_ignored]

    def menu_contributions(self):
        return {
            "file": [],
            "edit": [],
            "changes": [],
            "view": [self.action_flatten, self.vcstatus_menu.menuAction()],
        }

    def toolbar_contributions(self):
        def sep():
            action = QAction(self.widget)
            action.setSeparator(True)
            return action

        return [self.action_compare, sep(), self.action_commit,
                self.action_update, self.action_add, self.action_resolved,
                self.action_remove, self.action_revert,
                self.action_delete_locally, sep(), self.action_flatten,
                self.action_filter_modified, self.action_filter_normal,
                self.action_filter_nonvc, self.action_filter_ignored]

    def update_actions_sensitivity(self):
        """Disable actions whose VC plugin method is not implemented."""
        # Probe each command builder (side-effect-free: it only assembles an
        # argv list). Verbatim mapping from meld/vcview.py:109-118.
        action_vc_cmds_map = {
            self.action_compare: ("diff_command", ()),
            self.action_commit: ("commit_command", ("",)),
            self.action_update: ("update_command", ()),
            self.action_add: ("add_command", ()),
            self.action_add_binary: ("add_command", ()),
            self.action_resolved: ("resolved_command", ()),
            self.action_remove: ("remove_command", ()),
            self.action_revert: ("revert_command", ()),
        }
        for action, (meth_name, args) in action_vc_cmds_map.items():
            try:
                getattr(self.vc, meth_name)(*args)
                action.setEnabled(True)
            except NotImplementedError:
                action.setEnabled(False)

    def choose_vc(self, vcs):
        """Populate the VC combo for the location, disabling unusable plugins."""
        self.combobox_vcs.blockSignals(True)
        self.combobox_vcs.clear()
        tooltip_texts = [_("Choose one Version Control"),
                         _("Only one Version Control in this directory")]
        default_active = -1
        valid_vcs = []
        for idx, avc in enumerate(vcs):
            err_str = ""
            if shutil.which(avc.CMD) is None:
                # FIX (meld/vcview.py:245): translate the template, THEN format
                # — the old `_("%s Not Installed" % CMD)` never matched a msgid.
                err_str = _("%s Not Installed") % avc.CMD
            elif not avc.valid_repo():
                err_str = _("Invalid Repository")
            else:
                valid_vcs.append(idx)
                if self.vc is not None and self.vc.__class__ == avc.__class__:
                    default_active = idx

            if err_str:
                self.combobox_vcs.addItem(_("%s (%s)") % (avc.NAME, err_str))
                self.combobox_vcs.model().item(idx).setEnabled(False)
            else:
                self.combobox_vcs.addItem(avc.NAME)
            self.combobox_vcs.setItemData(idx, avc, Qt.ItemDataRole.UserRole)

        if valid_vcs and default_active == -1:
            default_active = min(valid_vcs)

        # Reset to -1 while blocked so the real setCurrentIndex below always
        # produces a change and fires on_vc_change (GTK's set_active did too).
        self.combobox_vcs.setCurrentIndex(-1)
        self.combobox_vcs.setToolTip(tooltip_texts[len(vcs) == 1])
        self.combobox_vcs.setEnabled(len(vcs) > 1)
        self.combobox_vcs.blockSignals(False)
        self.combobox_vcs.setCurrentIndex(default_active)

    def on_vc_change(self, index):
        # Guard: an all-invalid location (e.g. a git repo with git uninstalled)
        # leaves the combo at -1; don't crash trying to use a missing plugin.
        if index < 0:
            return
        self.vc = self.combobox_vcs.itemData(index)
        if self.vc is None:
            return
        self._set_location(self.vc.root)
        self.update_actions_sensitivity()

    # ----- location / label -------------------------------------------------

    def set_location(self, location):
        self.choose_vc(vc.get_vcs(os.path.abspath(location or ".")))

    def _set_location(self, location):
        self.location = location
        self.model.removeRows(0, self.model.rowCount())
        self.fileentry.set_filename(location)
        self.fileentry.prepend_history(location)
        root_index = self.model.add_entries(None, [location])
        self.model.set_state(root_index, 0, STATE_NORMAL, isdir=True)
        self.treeview.setFocus()
        self.treeview.setCurrentIndex(root_index)
        self.recompute_label()
        self.scheduler.remove_all_tasks()

        # No point scanning a repository when the user is diffing a single file.
        if os.path.isdir(self.vc.location):
            self.scheduler.add_task(
                self._search_recursively_iter(root_index).__next__)

    def recompute_label(self):
        self.label_text = os.path.basename(self.location)
        self.label_changed.emit(self.label_text)

    # ----- recursive scan ---------------------------------------------------

    def _search_recursively_iter(self, start_index):
        start_rowpath = self.model.rowpath(start_index)
        yield _("[%s] Scanning %s") % (self.label_text, "")
        root_index = self.model.index(0, 0)
        rootname = self.model.value_path(
            self.model.index_for_rowpath(start_rowpath), 0)
        prefixlen = 1 + len(self.model.value_path(root_index, 0))
        todo = [(start_rowpath, rootname)]

        filters = []
        if self.action_filter_modified.isChecked():
            filters.append(entry_modified)
        if self.action_filter_normal.isChecked():
            filters.append(entry_normal)
        if self.action_filter_nonvc.isChecked():
            filters.append(entry_nonvc)
        if self.action_filter_ignored.isChecked():
            filters.append(entry_ignored)

        def showable(entry):
            for f in filters:
                if f(entry):
                    return True
            return False

        recursive = self.action_flatten.isChecked()
        self.vc.cache_inventory(rootname)
        while todo:
            # Depth-first. Sort key avoids py3's None-vs-tuple TypeError; a
            # flatten-mode dir is queued as (None, path), a tree row as
            # (rowpath, None).
            todo.sort(key=lambda t: (t[0] or (), t[1] or ""))
            rowpath, name = todo.pop(0)
            if rowpath is not None:
                it = self.model.index_for_rowpath(rowpath)
                root = self.model.value_path(it, 0)
            else:
                it = root_index
                root = name
            yield _("[%s] Scanning %s") % (self.label_text, root[prefixlen:])

            # MUST be a list: len(entries) is taken below, and a lazy py3
            # filter object would both break len() and be a one-shot iterator.
            entries = [e for e in self.vc.listdir(root) if showable(e)]
            differences = False
            for e in entries:
                differences |= (e.state != STATE_NORMAL)
                if e.isdir and recursive:
                    todo.append((None, e.path))
                    continue
                child = self.model.add_entries(it, [e.path])
                self._update_item_state(child, e, root[prefixlen:])
                if e.isdir:
                    todo.append((self.model.rowpath(child), None))
            if not recursive:      # expand parents
                if len(entries) == 0:
                    self.model.add_empty(it, _("(Empty)"))
                if differences or len(rowpath) == 1:
                    self._expand_to_root(it)
            else:                  # just the root
                self.treeview.expand(root_index)
        self.vc.uncache_inventory()
        self._surface_warnings()

    def _expand_to_root(self, index):
        """Expand every row from the model root down to (and including) index."""
        chain = []
        idx = index
        while idx.isValid():
            chain.append(idx)
            idx = idx.parent()
        for idx in reversed(chain):
            self.treeview.expand(idx)

    def _update_item_state(self, index, vcentry, location):
        e = vcentry
        self.model.set_state(index, 0, e.state, e.isdir)
        self.model.set_columns(
            index, location, e.get_status(), e.rev, e.tag, e.options)

    # ----- refresh / navigation ---------------------------------------------

    def refresh(self):
        if self.vc is None:
            return
        root_index = self.model.index(0, 0)
        if not root_index.isValid():
            return
        self.set_location(self.model.value_path(root_index, 0))

    def refresh_partial(self, where):
        if not self.action_flatten.isChecked():
            index = self.find_index_by_name(where)
            if index is None or not index.isValid():
                return
            parent_index = index.parent()
            parent_item = (self.model.itemFromIndex(parent_index)
                           if parent_index.isValid()
                           else self.model.invisibleRootItem())
            row = index.row()
            items = self.model._row_items()
            items[0].setData(where, ROLE_PATH)
            parent_item.insertRow(row + 1, items)
            new_index = items[0].index()
            self.model.set_state(new_index, 0, STATE_NORMAL, isdir=True)
            # The old row shifts the new one up by one when removed; a
            # persistent index tracks it across the mutation.
            persistent = QPersistentModelIndex(new_index)
            parent_item.removeRow(row)
            new_index = self.model.index(
                persistent.row(), 0, persistent.parent())
            self.scheduler.add_task(
                self._search_recursively_iter(new_index).__next__)
        else:       # XXX fixme
            self.refresh()

    def find_index_by_name(self, name):
        index = self.model.index(0, 0)
        path = self.model.value_path(index, 0)
        while index.isValid():
            if name == path:
                return index
            elif path is not None and name.startswith(path):
                child = self.model.index(0, 0, index)
                while child.isValid():
                    path = self.model.value_path(child, 0)
                    if name == path:
                        return child
                    elif path is not None and name.startswith(path):
                        break
                    else:
                        child = self.model.index(child.row() + 1, 0, index)
                index = child
            else:
                break
        return None

    def on_row_activated(self, index):
        index = index.siblingAtColumn(0)
        if self.model.hasChildren(index):
            if self.treeview.isExpanded(index):
                self.treeview.collapse(index)
            else:
                self.treeview.expand(index)
        else:
            path = self.model.value_path(index, 0)
            if path is not None:
                self.run_diff([path])

    def next_diff(self, direction):
        selected = self._get_selected_paths()
        start_index = selected[-1] if selected else self.model.index(0, 0)
        if direction == Direction.UP:
            search = self.model.inorder_search_up
        else:
            search = self.model.inorder_search_down
        for it in search(start_index):
            state = self.model.get_state(it, 0)
            if state is not None and \
                    int(state) not in (STATE_NORMAL, STATE_EMPTY):
                self._expand_to_root(it)
                self.treeview.setCurrentIndex(it)
                self.treeview.scrollTo(it)
                return

    def on_file_changed(self, filename):
        index = self.find_index_by_name(filename)
        if index is None or not index.isValid():
            return
        path = self.model.value_path(index, 0)
        files = self.vc.lookup_files(
            [], [(os.path.basename(path), path)])[1]
        for e in files:
            if e.path == path:
                prefixlen = 1 + len(
                    self.model.value_path(self.model.index(0, 0), 0))
                self._update_item_state(index, e, e.parent[prefixlen:])
                return

    # ----- selection --------------------------------------------------------

    def _get_selected_paths(self):
        return self.treeview.selectionModel().selectedRows(0)

    def _get_selected_files(self):
        paths = []
        for index in self.treeview.selectionModel().selectedRows(0):
            path = self.model.value_path(index, 0)
            if path is None:      # empty-row placeholder
                continue
            paths.append(path[:-1] if path.endswith("/") else path)
        return paths

    # ----- button handlers --------------------------------------------------

    def on_button_diff_clicked(self, *args):
        files = self._get_selected_files()
        if files:
            self.run_diff(files, empty_patch_ok=True)

    def on_button_open_clicked(self, *args):
        self._open_files(self._get_selected_files())

    def on_button_update_clicked(self, *args):
        self._command_on_selected(self.vc.update_command())

    def on_button_commit_clicked(self, *args):
        # WP7.12 replaces this interim with the full CommitDialog (a changed-
        # files summary + a Previous-Logs history combo). QInputDialog is modal
        # but runs from a QAction slot (event-loop context), so it is safe.
        files = self._get_selected_files()
        if not files:
            QMessageBox.information(
                self.widget, "Meld", _("Select some files first."))
            return
        msg, ok = QInputDialog.getMultiLineText(
            self.widget, _("Commit"), _("Log Message"))
        if ok:
            self._command_on_selected(self.vc.commit_command(msg))

    def on_button_add_clicked(self, *args):
        self._command_on_selected(self.vc.add_command())

    def on_button_add_binary_clicked(self, *args):
        self._command_on_selected(self.vc.add_command(binary=1))

    def on_button_remove_clicked(self, *args):
        self._command_on_selected(self.vc.remove_command())

    def on_button_resolved_clicked(self, *args):
        self._command_on_selected(self.vc.resolved_command())

    def on_button_revert_clicked(self, *args):
        self._command_on_selected(self.vc.revert_command())

    def on_button_delete_clicked(self, *args):
        files = self._get_selected_files()
        for name in files:
            try:
                if os.path.isfile(name):
                    os.remove(name)
                elif os.path.isdir(name):
                    if QMessageBox.question(
                            self.widget, "Meld",
                            _("'%s' is a directory.\nRemove recursively?")
                            % os.path.basename(name),
                            QMessageBox.StandardButton.Ok
                            | QMessageBox.StandardButton.Cancel
                            ) == QMessageBox.StandardButton.Ok:
                        shutil.rmtree(name)
            except OSError as e:
                QMessageBox.warning(
                    self.widget, "Meld",
                    _("Error removing %s\n\n%s.") % (name, e))
        if files:
            self.refresh_partial(_commonprefix(files))

    # ----- command pipeline -------------------------------------------------

    def run_diff(self, path_list, empty_patch_ok=False):
        # WP7.11 replaces this with the diff/patch pipeline (run_diff_iter ->
        # _command_iter -> show_patch). Until then, open a plain comparison.
        for path in path_list:
            self.create_diff.emit([path])

    def _command_iter(self, command, files, refresh):
        """Run `command` on `files`, streaming output to the console.

        Yields status strings while running; the final yielded value is
        (workdir, output). Runs inside a scheduler pump tick.
        """
        msg = misc.shelljoin(command)
        yield "[%s] %s" % (self.label_text, msg.replace("\n", "↲"))

        def relpath(pbase, p):
            kill = 0
            if len(pbase) and p.startswith(pbase):
                kill = len(pbase) + 1
            return p[kill:] or "."

        if len(files) == 1 and os.path.isdir(files[0]):
            workdir = self.vc.get_working_directory(files[0])
        else:
            workdir = self.vc.get_working_directory(_commonprefix(files))
        files = [relpath(workdir, f) for f in files]
        r = None
        self.consolestream.write(
            misc.shelljoin(command + files) + " (in %s)\n" % workdir)
        readfunc = misc.read_pipe_iter(
            command + files, self.consolestream, workdir=workdir).__next__
        try:
            while r is None:
                r = readfunc()
                self.consolestream.write(r)
                yield 1
        except OSError as e:
            # This runs inside a pump tick: a modal dialog would re-enter the
            # event loop and call next() on THIS generator (ValueError:
            # generator already executing). Use the non-modal msgarea instead.
            self._add_dismissable_msg(
                "dialog-error",
                _("Error running command.\n'%s'\n\nThe error was:\n%s")
                % (misc.shelljoin(command), e))
        if refresh:
            self.refresh_partial(workdir)
        self._surface_warnings()
        yield workdir, r

    def _command(self, command, files, refresh=True):
        self.scheduler.add_task(
            self._command_iter(command, files, refresh).__next__)

    def _command_on_selected(self, command, refresh=True):
        files = self._get_selected_files()
        if files:
            self._command(command, files, refresh)
        else:
            QMessageBox.information(
                self.widget, "Meld", _("Select some files first."))

    def _add_dismissable_msg(self, icon, primary, secondary=None):
        area = self.msgarea.new_from_text_and_icon(icon, primary, secondary)
        area.add_stock_button_with_text(
            gtk_mnemonic_to_qt(_("Hi_de")), "window-close", ResponseId.CLOSE)
        area.response.connect(lambda *args: self.msgarea.clear())
        return area

    def _surface_warnings(self):
        # Where plugin warnings (e.g. the cvs .cvsignore compile error, T7.6)
        # reach the user, replacing the old modal misc.run_dialog.
        for w in self.vc.warnings:
            self.msgarea.new_from_text_and_icon("dialog-warning", w)
        self.vc.warnings.clear()

    # ----- lifecycle --------------------------------------------------------

    def on_fileentry_activate(self):
        self.set_location(self.fileentry.get_full_path())

    def on_reload_activate(self, *extra):
        self.on_fileentry_activate()

    def on_quit_event(self):
        self.scheduler.remove_all_tasks()
        for f in self.tempdirs:
            if os.path.exists(f):
                shutil.rmtree(f, ignore_errors=True)
        self.tempdirs = []

    def on_delete_event(self, appquit=False):
        self.on_quit_event()
        return RESULT_OK


class _ConsoleStream:
    """A file-like sink writing to the console QPlainTextEdit (str only)."""

    def __init__(self, textedit):
        self.textedit = textedit

    def write(self, s):
        if s:
            cursor = self.textedit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.textedit.setTextCursor(cursor)
            self.textedit.insertPlainText(s)
            self.textedit.ensureCursorVisible()
