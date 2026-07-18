"""MeldWindow — the M6 application shell.

A tabbed QMainWindow that hosts the three fresh views (FileDiffView,
DirDiffView, VcView), a New-Comparison dialog, CLI dispatch, minimal light/dark
theming, and the patch export/import UI (the product differentiator).

Written fresh against the plain-QWidget view contract (the views are *not*
MeldDoc subclasses and carry no scheduler). The 1.4-era meldq/app.py — built
around the old MeldDoc/scheduler/UIManager machinery — remains only as
reference. See BUILD_PLAN_3.24.md milestone M6.
"""

import os

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QDesktopServices,
    QFontDatabase,
    QIcon,
    QKeySequence,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from meldq import conf
from meldq.conf import _, mnemonic
from meldq.views.dirdiff import DirDiffView
from meldq.views.filediff import FileDiffView
from meldq.views.vcview import VcView
from meldq.widgets.sciview import DARK, LIGHT


class MeldWindow(QMainWindow):
    def __init__(self, prefs=None):
        super().__init__()
        if prefs is None:
            from meldq.util.prefs import Preferences
            prefs = Preferences()
        self.prefs = prefs

        self.setWindowTitle("Meld")
        self.resize(prefs.window_size_x, prefs.window_size_y)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self.setCentralWidget(self.tabs)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        self.prefs.changed.connect(self._on_pref_changed)

        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(500)
        self._geometry_timer.timeout.connect(self._save_geometry)

        self.setAcceptDrops(True)
        # colorSchemeChanged is Qt 6.8+ (the declared floor); guard so a
        # mismatched install degrades to no live OS-follow rather than crashing.
        hints = QApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_os_color_scheme_changed)
        self._apply_theme()
        self._update_action_state()

    # ----- construction -----------------------------------------------------

    # Freedesktop theme name -> QStyle standard pixmap, a fallback for platforms
    # with no icon theme (macOS, Windows) where QIcon.fromTheme returns null.
    _STD_ICON = {
        "document-new": "SP_FileIcon", "document-save": "SP_DialogSaveButton",
        "document-save-as": "SP_DialogSaveButton",
        "window-close": "SP_DialogCloseButton",
        "application-exit": "SP_DialogCloseButton",
        "edit-undo": "SP_ArrowBack", "edit-redo": "SP_ArrowForward",
        "go-up": "SP_ArrowUp", "go-down": "SP_ArrowDown",
        "view-refresh": "SP_BrowserReload", "help-contents": "SP_DialogHelpButton",
        "help-about": "SP_DialogHelpButton", "folder": "SP_DirIcon",
        "folder-remote": "SP_DirIcon", "text-x-generic": "SP_FileIcon",
    }

    def _themed_icon(self, name):
        """A themed icon, falling back to a platform-style standard icon so the
        toolbar/menus/tabs aren't blank where there is no icon theme."""
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
        std = self._STD_ICON.get(name)
        if std is not None:
            from PyQt6.QtWidgets import QStyle
            return self.style().standardIcon(getattr(QStyle.StandardPixmap, std))
        return QIcon()

    def _act(self, text, shortcut=None, icon=None, tip=None, slot=None,
             checkable=False):
        action = QAction(mnemonic(_(text)), self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if icon:
            action.setIcon(self._themed_icon(icon))
        if tip:
            action.setStatusTip(_(tip))
        if checkable:
            action.setCheckable(True)
        if slot is not None:
            if checkable:
                action.toggled.connect(slot)
            else:
                action.triggered.connect(slot)
        return action

    def _build_actions(self):
        self.action_new = self._act(
            "_New...", "Ctrl+N", "document-new",
            "Start a new comparison", self.on_new)
        self.action_save = self._act(
            "_Save", "Ctrl+S", "document-save",
            "Save the current file", self.on_save)
        self.action_save_as = self._act(
            "Save _As...", "Ctrl+Shift+S", "document-save-as",
            "Save the current file with a different name", self.on_save_as)
        self.action_create_patch = self._act(
            "Create _Patch...", None, None,
            "Create a unified diff of the current comparison", self.on_create_patch)
        self.action_import_patch = self._act(
            "_Import Patch...", None, None,
            "Apply an external patch and review it as a comparison",
            self.on_import_patch)
        self.action_close = self._act(
            "_Close", "Ctrl+W", "window-close",
            "Close the current comparison", self.on_close_tab)
        self.action_quit = self._act(
            "_Quit", "Ctrl+Q", "application-exit", "Quit the program", self.close)

        self.action_undo = self._act(
            "_Undo", "Ctrl+Z", "edit-undo",
            "Undo the last action", lambda: self._editor_action("undo"))
        self.action_redo = self._act(
            "_Redo", "Ctrl+Shift+Z", "edit-redo",
            "Redo the last undone action", lambda: self._editor_action("redo"))
        self.action_cut = self._act(
            "Cu_t", "Ctrl+X", "edit-cut",
            "Cut the selection", lambda: self._editor_action("cut"))
        self.action_copy = self._act(
            "_Copy", "Ctrl+C", "edit-copy",
            "Copy the selection", lambda: self._editor_action("copy"))
        self.action_paste = self._act(
            "_Paste", "Ctrl+V", "edit-paste",
            "Paste the clipboard", lambda: self._editor_action("paste"))
        self.action_find = self._act(
            "_Find...", "Ctrl+F", "edit-find", "Search for text", self.on_find)
        self.action_preferences = self._act(
            "Prefere_nces...", QKeySequence.StandardKey.Preferences, None,
            "Configure the editor, theme and filters", self.on_preferences)

        self.action_prev_change = self._act(
            "_Previous Change", "Ctrl+E", "go-up",
            "Go to the previous change", self.on_prev_change)
        self.action_next_change = self._act(
            "_Next Change", "Ctrl+D", "go-down",
            "Go to the next change", self.on_next_change)
        self.action_refresh = self._act(
            "_Refresh", "Ctrl+R", "view-refresh",
            "Rescan the current comparison", self.on_refresh)

        self.action_toolbar_visible = self._act(
            "_Toolbar", None, None, "Show or hide the toolbar",
            lambda checked: setattr(self.prefs, "toolbar_visible", checked),
            checkable=True)
        self.action_toolbar_visible.setChecked(bool(self.prefs.toolbar_visible))
        self.action_statusbar_visible = self._act(
            "_Statusbar", None, None, "Show or hide the statusbar",
            lambda checked: setattr(self.prefs, "statusbar_visible", checked),
            checkable=True)
        self.action_statusbar_visible.setChecked(bool(self.prefs.statusbar_visible))

        self.action_help = self._act(
            "_Contents", "F1", "help-contents", "Open the Meld manual",
            lambda: QDesktopServices.openUrl(QUrl(conf.HELP_URL)))
        self.action_about = self._act(
            "_About", None, "help-about", "About this program", self.show_about)

    def _build_menus(self):
        menubar = self.menuBar()
        self.menus = {}

        def make_menu(key, title):
            menu = menubar.addMenu(mnemonic(_(title)))
            self.menus[key] = menu
            return menu

        file_menu = make_menu("file", "_File")
        file_menu.addAction(self.action_new)
        file_menu.addSeparator()
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.action_create_patch)
        file_menu.addAction(self.action_import_patch)
        file_menu.addSeparator()
        file_menu.addAction(self.action_close)
        file_menu.addAction(self.action_quit)

        edit_menu = make_menu("edit", "_Edit")
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_cut)
        edit_menu.addAction(self.action_copy)
        edit_menu.addAction(self.action_paste)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_find)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_preferences)

        changes_menu = make_menu("changes", "_Changes")
        changes_menu.addAction(self.action_prev_change)
        changes_menu.addAction(self.action_next_change)

        view_menu = make_menu("view", "_View")
        self._build_theme_menu(view_menu)
        view_menu.addSeparator()
        view_menu.addAction(self.action_toolbar_visible)
        view_menu.addAction(self.action_statusbar_visible)
        view_menu.addSeparator()
        view_menu.addAction(self.action_refresh)

        help_menu = make_menu("help", "_Help")
        help_menu.addAction(self.action_help)
        help_menu.addAction(self.action_about)

    def _build_toolbar(self):
        self.toolbar = self.addToolBar("Toolbar")
        self.toolbar.setObjectName("main_toolbar")
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.toolbar.addAction(self.action_new)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_save)
        self.toolbar.addAction(self.action_refresh)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_prev_change)
        self.toolbar.addAction(self.action_next_change)
        self.toolbar.setVisible(bool(self.prefs.toolbar_visible))

    def _build_statusbar(self):
        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)
        self.statusBar().setVisible(bool(self.prefs.statusbar_visible))

    # ----- theming ----------------------------------------------------------

    # Theme pref value -> menu label (order preserved).
    _THEME_CHOICES = (("system", "Follow System"), ("light", "Light"),
                      ("dark", "Dark"))

    def _build_theme_menu(self, parent_menu):
        theme_menu = parent_menu.addMenu(mnemonic(_("_Theme")))
        self._theme_group = QActionGroup(self)
        self._theme_actions = {}
        for value, label in self._THEME_CHOICES:
            action = QAction(_(label), self, checkable=True)
            action.setData(value)
            action.triggered.connect(
                lambda _checked, v=value: self._set_theme_pref(v))
            self._theme_group.addAction(action)
            theme_menu.addAction(action)
            self._theme_actions[value] = action

    def _set_theme_pref(self, value):
        # Writes the pref, which fires changed('theme') -> _apply_theme.
        self.prefs.theme = value

    def _resolve_mode(self):
        """The effective light/dark mode. 'system' follows the OS appearance
        (Qt.ColorScheme.Dark -> dark), else the explicit pref."""
        pref = self.prefs.theme
        if pref in ("light", "dark"):
            return pref
        hints = QApplication.styleHints()
        scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else None
        return "dark" if scheme == Qt.ColorScheme.Dark else "light"

    def _theme_obj(self):
        return DARK if self._resolve_mode() == "dark" else LIGHT

    def _apply_theme(self):
        pref = self.prefs.theme
        # Drive the whole app chrome natively (Qt 6.8+): force a scheme, or
        # Unknown to follow the OS. No-op under the offscreen test platform;
        # guarded so a pre-6.8 install still themes the editors/trees.
        hints = QApplication.styleHints()
        if hasattr(hints, "setColorScheme"):
            scheme = {"light": Qt.ColorScheme.Light,
                      "dark": Qt.ColorScheme.Dark}.get(
                          pref, Qt.ColorScheme.Unknown)
            hints.setColorScheme(scheme)

        mode = self._resolve_mode()
        editor_theme = DARK if mode == "dark" else LIGHT
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, FileDiffView):
                widget.set_theme(editor_theme)
            elif isinstance(widget, (DirDiffView, VcView)):
                widget.set_theme(mode)

        action = self._theme_actions.get(pref)
        if action is not None:
            action.setChecked(True)

    def _on_os_color_scheme_changed(self, _scheme):
        # The OS flipped light<->dark; re-resolve only if we're following it.
        if self.prefs.theme == "system":
            self._apply_theme()

    def _apply_font_to(self, view):
        """Apply the current editor prefs (font + tab width) to every pane of
        `view`."""
        font = self.prefs.get_current_font()
        for pane in view.panes:
            pane.set_base_font(font)
            pane.setTabWidth(int(self.prefs.tab_size))

    def _reapply_font(self):
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, FileDiffView):
                self._apply_font_to(widget)

    # ----- tab helpers ------------------------------------------------------

    def _add_tab(self, widget, title, icon_name=None):
        icon = self._themed_icon(icon_name) if icon_name else QIcon()
        index = self.tabs.addTab(widget, icon, title)
        self.tabs.setTabToolTip(index, title)
        self.tabs.setCurrentIndex(index)
        return widget

    def current_view(self):
        return self.tabs.currentWidget()

    def _current_filediff(self):
        view = self.tabs.currentWidget()
        return view if isinstance(view, FileDiffView) else None

    @staticmethod
    def _diff_title(paths, labels=None):
        parts = []
        for i, path in enumerate(paths):
            if labels and i < len(labels) and labels[i]:
                parts.append(labels[i])
            else:
                parts.append(os.path.basename(str(path).rstrip(os.sep)) or str(path))
        return " : ".join(parts)

    def _warn(self, message):
        # Soft, non-modal: a modal here would wedge headless teardown.
        self.statusBar().showMessage(message, 8000)

    # ----- comparison factories ---------------------------------------------

    def append_filediff(self, files, labels=None):
        files = list(files)
        if len(files) == 4:
            # v1 has no separate merge-output pane; surface the drop instead of
            # silently discarding the 4th path.
            self._warn(_("A 4-file merge (with output) is not supported; "
                         "comparing the first 3 files."))
            files = files[:3]
        if len(files) not in (2, 3):
            self._warn(_("A file comparison needs 2 or 3 files."))
            return None
        view = FileDiffView(len(files))
        view.set_files(files)
        view.set_theme(self._theme_obj())
        self._apply_font_to(view)
        self._add_tab(view, self._diff_title(files, labels), "text-x-generic")
        return view

    def append_dirdiff(self, dirs, labels=None):
        dirs = list(dirs)
        if len(dirs) not in (2, 3):
            self._warn(_("A directory comparison needs 2 or 3 folders."))
            return None
        view = DirDiffView(len(dirs))
        view.create_diff.connect(self._on_child_create_diff)
        view.set_theme(self._resolve_mode())
        default_globs = self.prefs.dirdiff_name_filters
        if default_globs:
            view.apply_name_filter_text(default_globs)   # before the first scan
        view.set_roots(dirs)
        self._add_tab(view, self._diff_title(dirs, labels), "folder")
        return view

    def append_vcview(self, location, labels=None):
        view = VcView()
        view.create_diff.connect(self._on_child_create_diff)
        view.create_merge.connect(self._on_child_create_merge)
        view.set_theme(self._resolve_mode())
        view.set_location(location)
        title = (labels[0] if labels else None) or \
            os.path.basename(os.path.abspath(location).rstrip(os.sep)) or location
        self._add_tab(view, title, "folder-remote")
        return view

    def _on_child_create_diff(self, paths):
        # A dir/VC row was activated -> open a file comparison in a new tab.
        view = self.append_filediff(list(paths))
        # For a VC compare the left pane is the committed (HEAD) version, a
        # read-only reference — never a save target (it is a throwaway temp).
        if view is not None and isinstance(self.sender(), VcView):
            view.panes[0].setReadOnly(True)

    def _on_child_create_merge(self, paths):
        # A conflicted VC file -> 3-way resolve: ours | working | theirs. The
        # outer panes are read-only references (throwaway temps); the middle is
        # the real working file — merge into it, save, then Add marks resolved.
        view = self.append_filediff(list(paths))
        if view is not None and view.num_panes == 3:
            view.panes[0].setReadOnly(True)
            view.panes[2].setReadOnly(True)
            view.infobar.show_message(
                _("Resolve the conflict: merge either side into the middle "
                  "(working) pane, save it, then use Add to mark it resolved."))

    def append_diff(self, paths, labels=None):
        paths = list(paths)
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p)]
        if dirs and files:
            built = []
            lastfilename = os.path.basename(files[0])
            for elem in paths:
                if os.path.isdir(elem):
                    candidate = os.path.join(elem, lastfilename)
                    if os.path.isfile(candidate):
                        elem = candidate
                    else:
                        self._warn(_("Cannot compare a mixture of files and "
                                     "directories."))
                        return None
                else:
                    lastfilename = os.path.basename(elem)
                built.append(elem)
            return self.append_filediff(built, labels)
        if dirs:
            return self.append_dirdiff(paths, labels)
        return self.append_filediff(paths, labels)

    def open_paths(self, paths, auto_compare=False, labels=None):
        paths = list(paths)
        if not paths:
            return None
        if len(paths) == 1:
            path = paths[0]
            location = path if os.path.isdir(path) else \
                (os.path.dirname(os.path.abspath(path)) or ".")
            return self.append_vcview(location, labels)
        return self.append_diff(paths, labels)

    # ----- file actions -----------------------------------------------------

    def on_new(self):
        dialog = NewComparisonDialog(self)
        dialog.show()

    def on_save(self):
        view = self._current_filediff()
        if view is None:
            return
        saved = False
        for pane in range(view.num_panes):
            if view.is_modified(pane) and view.path(pane):
                if self._save_pane(view, pane):
                    saved = True
        if not saved:
            pane = view.focused_pane()
            if view.is_modified(pane) and not view.path(pane):
                self.on_save_as()

    def on_save_as(self):
        view = self._current_filediff()
        if view is None:
            return
        pane = view.focused_pane()
        start = view.path(pane) or ""
        path, _selected = QFileDialog.getSaveFileName(self, _("Save As"), start)
        if path and self._save_pane(view, pane, path):
            index = self.tabs.currentIndex()
            title = self._diff_title([view.path(p) for p in range(view.num_panes)])
            self.tabs.setTabText(index, title)

    def _save_pane(self, view, pane, path=None):
        from meldq.views.filediff import FileChangedOnDiskError
        try:
            view.save(pane, path)
            return True
        except FileChangedOnDiskError:
            self._prompt_overwrite(view, pane, path)
            return False
        except (OSError, ValueError) as exc:
            self._warn(_("Could not save: %s") % exc)
            return False

    def _prompt_overwrite(self, view, pane, path):
        # Non-modal: the file changed on disk since we opened it. Offer to
        # overwrite (force) or reload, rather than silently clobbering.
        name = os.path.basename(view.path(pane) or path or "")
        view.infobar.show_message(
            _('"%s" changed on disk since you opened it.') % name,
            [(_("Overwrite"), lambda: view.save(pane, path, force=True)),
             (_("Reload"), lambda: view.reload(pane))])

    # ----- patch export -----------------------------------------------------

    def on_create_patch(self):
        view = self._current_filediff()
        if view is None:
            return
        dialog = PatchDialog(view, self)
        dialog.show()
        return dialog

    # ----- patch import (the differentiator) --------------------------------

    def on_import_patch(self):
        patch_path, _selected = QFileDialog.getOpenFileName(
            self, _("Import Patch"), "",
            _("Patches (*.patch *.diff);;All Files (*)"))
        if not patch_path:
            return
        base_dir = QFileDialog.getExistingDirectory(
            self, _("Base directory to apply the patch in"),
            os.path.dirname(patch_path))
        if not base_dir:
            return
        try:
            from meldq.patchimport import read_patch_text
            patch_text = read_patch_text(patch_path)
            views = self.import_patch(base_dir, patch_text)
        except Exception as exc:          # PatchError, OSError, decode issues
            QMessageBox.warning(self, "Meld",
                                _("Could not import patch: %s") % exc)
            return
        if not views:
            self._warn(_("The patch did not name any files."))

    def import_patch(self, base_dir, patch_text):
        """Open one FileDiff tab per file in the patch (source on the left,
        patched on the right). Dialog-free core, so it is directly testable.
        A malformed hunk raises meldq.patch.PatchError to the caller."""
        from meldq.patchimport import patch_targets_and_skipped

        targets, skipped = patch_targets_and_skipped(base_dir, patch_text)
        if skipped:
            self._warn(_("Binary changes are not supported and were "
                         "skipped: %s") % ", ".join(skipped))
        views = []
        for target in targets:
            view = FileDiffView(2)
            # Load the untouched source into BOTH panes, then apply the patch to
            # the right pane as a recorded edit. That leaves the right pane
            # genuinely modified (QScintilla's isModified is save-point-relative,
            # so setModified(True) is a no-op) — so File>Save writes it and the
            # unsaved-close prompt fires — and makes the patch undoable.
            view.set_texts([target.original, target.original],
                           [target.path, target.path])
            # Preserve the source's encoding/EOL so accepting + saving writes
            # the file back losslessly (no UTF-8 clobber of a latin-1 source).
            view.set_encoding(0, target.encoding, target.eol)
            view.set_encoding(1, target.encoding, target.eol)
            # Left = the untouched source (reference, read-only); right = the
            # patched result the user reviews. Only the right pane is saveable,
            # so Save can never write the original back over the same path.
            view.panes[0].setReadOnly(True)
            if target.patched != target.original:
                view.panes[1].replace_all_text(target.patched)
            if target.is_delete:
                # Saving writes an empty file; actual deletion is manual — be
                # explicit rather than silently diverging from patch semantics.
                view.infobar.show_message(
                    _('This patch deletes "%s". Saving writes an empty file; '
                      'delete it manually to complete the removal.')
                    % os.path.basename(target.path))
            view.set_theme(self._theme_obj())
            self._apply_font_to(view)
            title = _("patch (delete): %s") if target.is_delete else _("patch: %s")
            self._add_tab(view, title % os.path.basename(target.path),
                          "text-x-generic")
            views.append(view)
        return views

    # ----- edit / navigation ------------------------------------------------

    def _editor_action(self, name):
        # Undo/redo route through the FileDiff view to the pane that actually
        # last changed — a merge edits a pane other than the focused one, so
        # focusWidget().undo() would miss it. Cut/copy/paste stay on focus.
        if name in ("undo", "redo"):
            view = self._current_filediff()
            if view is not None:
                getattr(view, name)()
                return
        widget = self.focusWidget()
        method = getattr(widget, name, None)
        if callable(method):
            method()

    def on_find(self):
        view = self._current_filediff()
        if view is not None:
            view.show_find_bar()

    def on_preferences(self):
        dialog = PreferencesDialog(self)
        dialog.show()
        return dialog

    def on_prev_change(self):
        view = self._current_filediff()
        if view is not None:
            view.prev_diff()

    def on_next_change(self):
        view = self._current_filediff()
        if view is not None:
            view.next_diff()

    def on_refresh(self):
        view = self.tabs.currentWidget()
        if isinstance(view, (DirDiffView, VcView)):
            view.refresh()

    # ----- misc slots -------------------------------------------------------

    def show_about(self):
        from meldq import __version__
        QMessageBox.about(
            self, _("About Meld"),
            f"<h3>Meld {__version__}</h3>"
            f"<p>{_('A visual diff and merge tool (PyQt6 port).')}</p>"
            '<p><a href="https://meldmerge.org/">https://meldmerge.org/</a></p>')

    def on_close_tab(self):
        index = self.tabs.currentIndex()
        if index >= 0:
            self._on_tab_close_requested(index)

    # ----- tab lifecycle ----------------------------------------------------

    def _on_current_tab_changed(self, _index):
        view = self.tabs.currentWidget()
        title = self.tabs.tabText(self.tabs.currentIndex()) if view else ""
        self.setWindowTitle(f"{title} — Meld" if title else "Meld")
        self.status_label.setText(self._status_for(view))
        self._update_action_state()

    @staticmethod
    def _status_for(view):
        if isinstance(view, FileDiffView):
            return _("%d-way file comparison") % view.num_panes
        if isinstance(view, DirDiffView):
            return _("Directory comparison")
        if isinstance(view, VcView):
            return _("Version control: %s") % (view.location or "")
        return ""

    def _update_action_state(self):
        view = self.tabs.currentWidget()
        is_filediff = isinstance(view, FileDiffView)
        is_tree = isinstance(view, (DirDiffView, VcView))
        for action in (self.action_save, self.action_save_as,
                       self.action_create_patch, self.action_prev_change,
                       self.action_next_change, self.action_undo,
                       self.action_redo, self.action_cut, self.action_copy,
                       self.action_paste, self.action_find):
            action.setEnabled(is_filediff)
        self.action_refresh.setEnabled(is_tree)
        self.action_close.setEnabled(view is not None)

    def _on_tab_close_requested(self, index):
        widget = self.tabs.widget(index)
        if isinstance(widget, FileDiffView) and widget.any_modified():
            self.tabs.setCurrentIndex(index)
            response = self._prompt_unsaved(widget)
            if response == QMessageBox.StandardButton.Cancel:
                return
            if response == QMessageBox.StandardButton.Save:
                if not self._save_all_panes(widget):
                    return          # save failed/incomplete -> keep the tab
        self.tabs.removeTab(index)
        widget.deleteLater()

    def _prompt_unsaved(self, view):
        return QMessageBox.warning(
            self, _("Save changes?"),
            _("This comparison has unsaved changes. Save them before closing?"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)

    def _save_all_panes(self, view):
        """Save every modified pane. Returns True only if nothing remained
        unsaved — every write succeeded and no modified pane lacked a path — so
        the caller can refuse to close a tab whose Save failed."""
        ok = True
        for pane in range(view.num_panes):
            if view.is_modified(pane):
                if not view.path(pane):
                    ok = False              # would need Save-As; not saved
                elif not self._save_pane(view, pane):
                    ok = False              # write failed or overwrite-refused
        return ok

    # ----- prefs / geometry -------------------------------------------------

    def _on_pref_changed(self, key):
        if key == "theme":
            self._apply_theme()
        elif key in ("custom_font", "use_custom_font", "tab_size"):
            self._reapply_font()
        elif key == "dirdiff_name_filters":
            for i in range(self.tabs.count()):
                widget = self.tabs.widget(i)
                if isinstance(widget, DirDiffView):
                    widget.apply_name_filter_text(self.prefs.dirdiff_name_filters)
        elif key == "toolbar_visible":
            self.toolbar.setVisible(bool(self.prefs.toolbar_visible))
            self.action_toolbar_visible.setChecked(bool(self.prefs.toolbar_visible))
        elif key == "statusbar_visible":
            self.statusBar().setVisible(bool(self.prefs.statusbar_visible))
            self.action_statusbar_visible.setChecked(bool(self.prefs.statusbar_visible))

    def _save_geometry(self):
        self.prefs.window_size_x = self.width()
        self.prefs.window_size_y = self.height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._geometry_timer.start()

    # ----- DnD --------------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            self.open_paths(paths)

    # ----- close ------------------------------------------------------------

    def closeEvent(self, event):
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, FileDiffView) and widget.any_modified():
                self.tabs.setCurrentIndex(i)
                response = self._prompt_unsaved(widget)
                if response == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if response == QMessageBox.StandardButton.Save:
                    if not self._save_all_panes(widget):
                        event.ignore()      # save failed -> don't lose edits
                        return
        if self._geometry_timer.isActive():
            self._geometry_timer.stop()
        self._save_geometry()
        event.accept()


class PatchDialog(QDialog):
    """Patch export: show the unified diff of a FileDiff, with a reverse toggle
    and (for 3-way) a pane-pair selector, plus copy/save. patch_text() is the
    dialog-free core used by tests."""

    def __init__(self, filediff, parent=None):
        super().__init__(parent)
        self.filediff = filediff
        self.setWindowTitle(_("Create Patch"))
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.reverse = QCheckBox(_("Reverse"))
        self.reverse.toggled.connect(self._refresh)
        controls.addWidget(self.reverse)
        if filediff.num_panes == 3:
            self.pair = QComboBox()
            self.pair.addItem(_("Left ↔ Middle"), (0, 1))
            self.pair.addItem(_("Middle ↔ Right"), (1, 2))
            self.pair.currentIndexChanged.connect(self._refresh)
            controls.addWidget(self.pair)
        else:
            self.pair = None
        controls.addStretch(1)
        layout.addLayout(controls)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.text, 1)

        buttons = QDialogButtonBox()
        copy_btn = buttons.addButton(
            _("Copy"), QDialogButtonBox.ButtonRole.ActionRole)
        save_btn = buttons.addButton(
            _("Save..."), QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        copy_btn.clicked.connect(self._copy)
        save_btn.clicked.connect(self._save)
        layout.addWidget(buttons)

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # If the underlying comparison tab is closed, this modeless dialog would
        # be left holding a deleted FileDiffView; any interaction then calls
        # make_patch on freed C++ panes and aborts the app. Close with the view.
        filediff.destroyed.connect(self.reject)
        self._refresh()

    def _pair(self):
        return self.pair.currentData() if self.pair else (0, 1)

    def patch_text(self):
        try:
            left, right = self._pair()
            return self.filediff.make_patch(left, right, self.reverse.isChecked())
        except RuntimeError:            # underlying view already deleted
            return ""

    def _refresh(self, *args):
        self.text.setPlainText(self.patch_text())

    def _copy(self):
        QApplication.clipboard().setText(self.patch_text())

    def _save(self):
        path, _selected = QFileDialog.getSaveFileName(
            self, _("Save Patch"), "changes.diff")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(self.patch_text())
            except OSError as exc:
                QMessageBox.warning(
                    self, "Meld", _("Could not save patch: %s") % exc)


class PreferencesDialog(QDialog):
    """Editor font / tab width, theme, and default DirDiff filters. Values are
    written to prefs on OK; the shell reacts through the prefs.changed signal
    (built in code, project convention)."""

    def __init__(self, window):
        super().__init__(window)
        from PyQt6.QtGui import QFont
        from PyQt6.QtWidgets import (
            QFontComboBox,
            QLineEdit,
            QSpinBox,
            QTabWidget as _QTabWidget,
        )

        self.prefs = window.prefs
        self.setWindowTitle(_("Preferences"))
        self.setMinimumWidth(420)
        tabs = _QTabWidget()

        # --- Editor -------------------------------------------------------
        editor_tab = QWidget()
        form = QFormLayout(editor_tab)
        self.use_custom = QCheckBox(_("Use a custom font"))
        self.use_custom.setChecked(bool(self.prefs.use_custom_font))
        current = QFont()
        current.fromString(self.prefs.custom_font)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(current)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 72)
        self.size_spin.setValue(max(6, current.pointSize()))
        self.font_combo.setEnabled(self.use_custom.isChecked())
        self.size_spin.setEnabled(self.use_custom.isChecked())
        self.use_custom.toggled.connect(self.font_combo.setEnabled)
        self.use_custom.toggled.connect(self.size_spin.setEnabled)
        self.tab_spin = QSpinBox()
        self.tab_spin.setRange(1, 16)
        self.tab_spin.setValue(int(self.prefs.tab_size))
        form.addRow(self.use_custom)
        form.addRow(_("Font"), self.font_combo)
        form.addRow(_("Size"), self.size_spin)
        form.addRow(_("Tab width"), self.tab_spin)
        tabs.addTab(editor_tab, _("Editor"))

        # --- Display ------------------------------------------------------
        display_tab = QWidget()
        display_form = QFormLayout(display_tab)
        self.theme_combo = QComboBox()
        for value, label in MeldWindow._THEME_CHOICES:
            self.theme_combo.addItem(_(label), value)
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(self.prefs.theme)))
        display_form.addRow(_("Theme"), self.theme_combo)
        tabs.addTab(display_tab, _("Display"))

        # --- Folder comparison -------------------------------------------
        folder_tab = QWidget()
        folder_form = QFormLayout(folder_tab)
        self.filter_edit = QLineEdit(self.prefs.dirdiff_name_filters)
        self.filter_edit.setPlaceholderText(
            _("Globs to hide, space-separated (e.g. *.pyc build)"))
        folder_form.addRow(_("Hide names"), self.filter_edit)
        tabs.addTab(folder_tab, _("Folder Comparison"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def accept(self):
        p = self.prefs
        p.use_custom_font = self.use_custom.isChecked()
        font = self.font_combo.currentFont()
        font.setPointSize(self.size_spin.value())
        p.custom_font = font.toString()
        p.tab_size = self.tab_spin.value()
        p.theme = self.theme_combo.currentData()
        p.dirdiff_name_filters = self.filter_edit.text()
        super().accept()


class NewComparisonDialog(QDialog):
    """Modeless "Choose files" dialog with File / Directory / Version-Control
    tabs, each row a FileHistoryCombo. Accepting dispatches to the window's
    append_* factory. Adapted from the 1.4 dialog for the fresh views."""

    def __init__(self, window):
        super().__init__(window)
        from meldq.widgets.historycombo import FileHistoryCombo

        self.window = window
        self.setWindowTitle(_("Choose Files"))
        settings = window.prefs._settings
        self.notebook = QTabWidget()

        def file_row(history_id, directory):
            return FileHistoryCombo(history_id, directory_entry=directory,
                                    settings=settings)

        # File comparison tab
        file_tab = QWidget()
        file_layout = QVBoxLayout(file_tab)
        self.three_way_file = QCheckBox(mnemonic(_("_3-way comparison")))
        self.fileentry0 = file_row("file_comparison", False)   # Other / ancestor
        self.fileentry1 = file_row("file_comparison", False)   # Original
        self.fileentry2 = file_row("file_comparison", False)   # Mine
        form_file = QFormLayout()
        form_file.addRow(_("Other"), self.fileentry0)
        form_file.addRow(_("Original"), self.fileentry1)
        form_file.addRow(_("Mine"), self.fileentry2)
        file_layout.addWidget(self.three_way_file)
        file_layout.addLayout(form_file)
        self.notebook.addTab(file_tab, mnemonic(_("_File Comparison")))

        # Directory comparison tab
        dir_tab = QWidget()
        dir_layout = QVBoxLayout(dir_tab)
        self.three_way_dir = QCheckBox(mnemonic(_("_3-way comparison")))
        self.direntry0 = file_row("dir_comparison", True)
        self.direntry1 = file_row("dir_comparison", True)
        self.direntry2 = file_row("dir_comparison", True)
        form_dir = QFormLayout()
        form_dir.addRow(_("Other"), self.direntry0)
        form_dir.addRow(_("Original"), self.direntry1)
        form_dir.addRow(_("Mine"), self.direntry2)
        dir_layout.addWidget(self.three_way_dir)
        dir_layout.addLayout(form_dir)
        self.notebook.addTab(dir_tab, mnemonic(_("_Directory Comparison")))

        # Version-control tab
        vc_tab = QWidget()
        vc_layout = QFormLayout(vc_tab)
        self.vcentry0 = file_row("vc_directory", True)
        vc_layout.addRow(_("Directory"), self.vcentry0)
        self.notebook.addTab(vc_tab, mnemonic(_("_Version Control Browser")))

        self.buttonbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)
        self.buttonbox.button(
            QDialogButtonBox.StandardButton.Ok).setDefault(True)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #cc0000;")

        layout = QVBoxLayout(self)
        layout.addWidget(self.notebook)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttonbox)

        self.entrylists = (
            [self.fileentry0, self.fileentry1, self.fileentry2],
            [self.direntry0, self.direntry1, self.direntry2],
            [self.vcentry0],
        )
        self.three_way = [self.three_way_file, self.three_way_dir]
        for page, checkbox in enumerate(self.three_way):
            checkbox.toggled.connect(
                lambda checked, p=page: self._on_three_way(p, checked))
            self.entrylists[page][0].setEnabled(checkbox.isChecked())
        for entries in self.entrylists:
            for idx, entry in enumerate(entries):
                entry.activated.connect(self._make_activate_handler(entries, idx))

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def _on_three_way(self, page, checked):
        entries = self.entrylists[page]
        entries[0].setEnabled(checked)
        (entries[0] if checked else entries[1]).focus_entry()

    def _make_activate_handler(self, entries, idx):
        def handler():
            if idx + 1 < len(entries):
                entries[idx + 1].focus_entry()
            else:
                self.buttonbox.button(
                    QDialogButtonBox.StandardButton.Ok).setFocus()
        return handler

    def accept(self):
        page = self.notebook.currentIndex()
        entries = self.entrylists[page]
        paths = [e.get_full_path() or "" for e in entries]
        if page < 2 and not self.three_way[page].isChecked():
            paths.pop(0)                       # drop the "Other" slot in 2-way
        paths = [p for p in paths if p]
        # Validate BEFORE closing so insufficient input isn't silently discarded
        # (the dialog is WA_DeleteOnClose — a premature super().accept() throws
        # away everything the user typed).
        needed = 1 if page == 2 else 2
        if len(paths) < needed:
            self.error_label.setText(
                _("Choose a directory to open.") if page == 2
                else _("Choose at least two items to compare."))
            return
        self.error_label.clear()
        for entry in entries:
            value = entry.get_full_path()
            if value:
                entry.prepend_history(value)
        if page == 0:
            self.window.append_filediff(paths)
        elif page == 1:
            self.window.append_dirdiff(paths)
        else:
            self.window.append_vcview(paths[0])
        super().accept()
