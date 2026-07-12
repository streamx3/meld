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

import os

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QTabWidget,
)

from meldq import conf
from meldq.conf import _
from meldq.doc import CloseResponse, Direction


class SchedulerPump(QObject):
    """Drives one scheduler's cooperative tasks from a 0-interval QTimer.

    Replaces the 1.4 gobject.idle_add pump. Only the current tab's
    scheduler is driven; the timer stops when no tasks are pending (so it
    never busy-spins) and restarts from the scheduler's runnable callback.
    """

    status_message = pyqtSignal(str)      # on_idle str branch  (meldapp.py:265-266)
    progress_fraction = pyqtSignal(float)  # float branch        (meldapp.py:267-268)
    progress_pulse = pyqtSignal()         # other-truthy branch (meldapp.py:269-270)
    idle_changed = pyqtSignal(bool)       # True = no tasks pending

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)
        self._scheduler = None

    def set_scheduler(self, scheduler):
        if self._scheduler is not None:
            self._scheduler.runnable_cb = None
        self._scheduler = scheduler
        if scheduler is None:
            self._timer.stop()
            return
        scheduler.runnable_cb = self._on_runnable
        if scheduler.tasks_pending():
            if not self._timer.isActive():
                self._timer.start()
            self.idle_changed.emit(False)
        else:
            self._timer.stop()

    def pause(self):
        self._timer.stop()

    def resume(self):
        if self._scheduler is not None and self._scheduler.tasks_pending():
            self._timer.start()

    def stop(self):
        if self._scheduler is not None:
            self._scheduler.runnable_cb = None
        self._scheduler = None
        self._timer.stop()

    def _on_runnable(self, sched):
        if getattr(self._scheduler, "paused", False):
            return
        if not self._timer.isActive():
            self._timer.start()
        self.idle_changed.emit(False)

    def _tick(self):
        if self._scheduler is None:
            self._timer.stop()
            return
        if getattr(self._scheduler, "paused", False):
            self._timer.stop()
            return
        ret = self._scheduler.iteration()
        if isinstance(ret, str):
            self.status_message.emit(ret)
        elif type(ret) is float:
            self.progress_fraction.emit(ret)
        elif ret:
            self.progress_pulse.emit()
        if not self._scheduler.tasks_pending():
            self._timer.stop()
            self.status_message.emit("")
            self.progress_fraction.emit(0.0)
            self.idle_changed.emit(True)


# Action table: (attr, text_msgid, shortcut, theme_icon, statustip_msgid).
# Texts with '_' carry a GTK mnemonic; conf.mnemonic() converts to Qt '&'.
# Plain English words where 1.4 used a translated stock label are new msgids.
_ACTION_SPEC = [
    ("new", "_New...", "Ctrl+N", "document-new", "Start a new comparison"),
    ("save", "Save", "Ctrl+S", "document-save", "Save the current file"),  # new msgid vs 1.4
    ("save_as", "Save As...", "Ctrl+Shift+S", "document-save-as",
     "Save the current file with a different name"),
    ("close", "Close", "Ctrl+W", "window-close", "Close the current file"),  # new msgid vs 1.4
    ("quit", "Quit", "Ctrl+Q", "application-exit", "Quit the program"),  # new msgid vs 1.4
    ("undo", "Undo", "Ctrl+Z", "edit-undo", "Undo the last action"),  # new msgid vs 1.4
    ("redo", "Redo", "Ctrl+Shift+Z", "edit-redo", "Redo the last undone action"),  # new msgid vs 1.4
    ("cut", "Cut", "Ctrl+X", "edit-cut", "Cut the selection"),  # new msgid vs 1.4
    ("copy", "Copy", "Ctrl+C", "edit-copy", "Copy the selection"),  # new msgid vs 1.4
    ("paste", "Paste", "Ctrl+V", "edit-paste", "Paste the clipboard"),  # new msgid vs 1.4
    ("find", "Find...", "Ctrl+F", "edit-find", "Search for text"),  # new msgid vs 1.4
    ("find_next", "Find Ne_xt", "Ctrl+G", None, "Search forwards for the same text"),
    ("replace", "_Replace", "Ctrl+H", "edit-find-replace", "Find and replace text"),
    ("preferences", "Prefere_nces", None, "preferences-system", "Configure the application"),
    ("prev_change", "Previous change", "Ctrl+E", "go-up", "Go to the previous change"),
    ("next_change", "Next change", "Ctrl+D", "go-down", "Go to the next change"),
    ("stop", "Stop", "Escape", "process-stop", "Stop the current action"),  # new msgid vs 1.4
    ("refresh", "Refresh", "Ctrl+R", "view-refresh", "Refresh the view"),  # new msgid vs 1.4
    ("reload", "Reload", "Ctrl+Shift+R", "view-refresh", "Reload the comparison"),
    ("help", "_Contents", "F1", "help-contents", "Open the Meld manual"),
    ("bug", "Report _Bug", None, None, "Report a bug in Meld"),
    ("about", "About", None, "help-about", "About this program"),  # new msgid vs 1.4
]

# checkable actions: (attr, text_msgid, shortcut, statustip_msgid, pref_name|None)
_TOGGLE_SPEC = [
    ("fullscreen", "Full Screen", "F11", "View the comparison in full screen", None),
    ("toolbar_visible", "_Toolbar", None, "Show or hide the toolbar", "toolbar_visible"),
    ("statusbar_visible", "_Statusbar", None, "Show or hide the statusbar", "statusbar_visible"),
]


class _DummyDoc:
    """Null object: any method call is a no-op (matches 1.4's DummyDoc)."""

    def __getattr__(self, name):
        return lambda *a, **k: None


_DUMMY_DOC = _DummyDoc()


class MeldWindow(QMainWindow):
    def __init__(self, prefs):
        super().__init__()
        self.prefs = prefs
        self._doc_for_widget = {}
        self._current_doc = None
        self._current_connections = []
        self._transient_pumps = []

        self.setWindowTitle("Meld")
        self.resize(prefs.window_size_x, prefs.window_size_y)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self.setCentralWidget(self.tabs)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self.dam = DocActionManager(self)

        self.pump = SchedulerPump(self)
        self.pump.status_message.connect(self.set_task_status)
        self.pump.progress_fraction.connect(self._on_progress_fraction)
        self.pump.progress_pulse.connect(self._on_progress_pulse)
        self.pump.idle_changed.connect(self._on_idle_changed)
        self.action_stop.setEnabled(False)

        self.prefs.changed.connect(self._on_pref_changed)

        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.setInterval(500)
        self._geometry_save_timer.timeout.connect(self._save_geometry)

        self.setAcceptDrops(True)

    # ----- construction -----------------------------------------------------

    def _build_actions(self):
        for attr, text, shortcut, icon, tip in _ACTION_SPEC:
            action = QAction(conf.mnemonic(_(text)), self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            if icon:
                action.setIcon(QIcon.fromTheme(icon))
            action.setStatusTip(_(tip))
            setattr(self, f"action_{attr}", action)
        for attr, text, shortcut, tip, pref_name in _TOGGLE_SPEC:
            action = QAction(conf.mnemonic(_(text)), self)
            action.setCheckable(True)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.setStatusTip(_(tip))
            if pref_name is not None:
                action.setChecked(bool(getattr(self.prefs, pref_name)))
            setattr(self, f"action_{attr}", action)

        self.action_new.triggered.connect(self.on_menu_file_new_activate)
        self.action_save.triggered.connect(lambda: self.current_doc().save())
        self.action_save_as.triggered.connect(lambda: self.current_doc().save_as())
        self.action_close.triggered.connect(self._close_current_tab)
        self.action_quit.triggered.connect(self.close)
        self.action_undo.triggered.connect(lambda: self.current_doc().on_undo_activate())
        self.action_redo.triggered.connect(lambda: self.current_doc().on_redo_activate())
        self.action_cut.triggered.connect(lambda: self._clipboard_action("cut"))
        self.action_copy.triggered.connect(lambda: self._clipboard_action("copy"))
        self.action_paste.triggered.connect(lambda: self._clipboard_action("paste"))
        self.action_find.triggered.connect(lambda: self.current_doc().on_find_activate())
        self.action_find_next.triggered.connect(lambda: self.current_doc().on_find_next_activate())
        self.action_replace.triggered.connect(lambda: self.current_doc().on_replace_activate())
        self.action_preferences.triggered.connect(self.on_menu_preferences_activate)
        self.action_prev_change.triggered.connect(lambda: self.current_doc().next_diff(Direction.UP))
        self.action_next_change.triggered.connect(lambda: self.current_doc().next_diff(Direction.DOWN))
        self.action_stop.triggered.connect(lambda: self.current_doc().stop())
        self.action_refresh.triggered.connect(lambda: self.current_doc().on_refresh_activate())
        self.action_reload.triggered.connect(lambda: self.current_doc().on_reload_activate())
        self.action_help.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(conf.HELP_URL)))
        self.action_bug.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(conf.BUG_REPORT_URL)))
        self.action_about.triggered.connect(self.show_about)
        self.action_fullscreen.triggered.connect(self._toggle_fullscreen)
        self.action_toolbar_visible.triggered.connect(
            lambda checked: setattr(self.prefs, "toolbar_visible", checked))
        self.action_statusbar_visible.triggered.connect(
            lambda checked: setattr(self.prefs, "statusbar_visible", checked))

    def _add_placeholder(self, menu, key):
        start = QAction(menu)
        start.setSeparator(True)
        start.setObjectName(f"doc_section_start_{key}")
        start.setVisible(False)
        end = QAction(menu)
        end.setSeparator(True)
        end.setObjectName(f"doc_section_end_{key}")
        end.setVisible(False)
        menu.addAction(start)
        menu.addAction(end)

    def _build_menus(self):
        menubar = self.menuBar()
        self.menus = {}

        def make_menu(key, title):
            menu = menubar.addMenu(conf.mnemonic(_(title)))
            self.menus[key] = menu
            return menu

        file_menu = make_menu("file", "_File")
        file_menu.addAction(self.action_new)
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)
        self._add_placeholder(file_menu, "file")
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
        self._add_placeholder(edit_menu, "edit")
        edit_menu.addAction(self.action_find)
        edit_menu.addAction(self.action_find_next)
        edit_menu.addAction(self.action_replace)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_preferences)

        changes_menu = make_menu("changes", "_Changes")
        changes_menu.addAction(self.action_prev_change)
        changes_menu.addAction(self.action_next_change)
        self._add_placeholder(changes_menu, "changes")

        view_menu = make_menu("view", "_View")
        view_menu.addAction(self.action_toolbar_visible)
        view_menu.addAction(self.action_statusbar_visible)
        view_menu.addAction(self.action_fullscreen)
        self._add_placeholder(view_menu, "view")
        view_menu.addSeparator()
        view_menu.addAction(self.action_stop)
        view_menu.addAction(self.action_refresh)
        view_menu.addAction(self.action_reload)

        help_menu = make_menu("help", "_Help")
        help_menu.addAction(self.action_help)
        help_menu.addAction(self.action_bug)
        help_menu.addAction(self.action_about)
        self._add_placeholder(help_menu, "help")

    def _build_toolbar(self):
        self.toolbar = self.addToolBar("Toolbar")
        self.toolbar.setObjectName("main_toolbar")
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.toolbar.addAction(self.action_new)
        start = QAction(self.toolbar)
        start.setSeparator(True)
        start.setObjectName("doc_toolbar_start")
        start.setVisible(False)
        end = QAction(self.toolbar)
        end.setSeparator(True)
        end.setObjectName("doc_toolbar_end")
        end.setVisible(False)
        self.toolbar.addAction(start)
        self.toolbar.addAction(end)
        self.toolbar.addAction(self.action_prev_change)
        self.toolbar.addAction(self.action_next_change)
        self.toolbar.addAction(self.action_stop)
        self.toolbar.setVisible(bool(self.prefs.toolbar_visible))

    def _build_statusbar(self):
        self.progress = QProgressBar()
        self.progress.setFixedWidth(150)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.task_status_label = QLabel()
        self.doc_status_label = QLabel()
        statusbar = self.statusBar()
        statusbar.addPermanentWidget(self.progress)
        statusbar.addPermanentWidget(self.task_status_label)
        statusbar.addPermanentWidget(self.doc_status_label)
        statusbar.setVisible(bool(self.prefs.statusbar_visible))

    # ----- status / progress ------------------------------------------------

    def set_task_status(self, text):
        self.task_status_label.setText(text)

    def set_doc_status(self, text):
        self.doc_status_label.setText(text)

    def _on_progress_fraction(self, fraction):
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(int(fraction * 100))

    def _on_progress_pulse(self):
        self.progress.setRange(0, 0)

    def _on_idle_changed(self, idle):
        self.action_stop.setEnabled(not idle)
        if idle and self.progress.maximum() == 0:
            self.progress.setRange(0, 100)

    # ----- prefs / geometry -------------------------------------------------

    def _on_pref_changed(self, key):
        if key == "toolbar_visible":
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
        self._geometry_save_timer.start()

    # ----- DnD / focus ------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.open_paths(paths)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange:
            for doc in self._doc_for_widget.values():
                doc.on_focus_change()
        super().changeEvent(event)

    # ----- slots ------------------------------------------------------------

    def _clipboard_action(self, name):
        method = getattr(self.focusWidget(), name, None)
        if callable(method):
            method()

    def on_menu_file_new_activate(self):
        # replaced by NewComparisonDialog in T3.8
        QMessageBox.information(self, "Meld",
                                _("New comparison dialog not available yet"))

    def on_menu_preferences_activate(self):
        from meldq.prefsdialog import PreferencesDialog
        dialog = PreferencesDialog(self, self.prefs)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def show_about(self):
        from meldq import __version__
        html = (
            f"<h3>Meld {__version__}</h3>"
            f"<p>{_('Copyright © 2002-2009 Stephen Kennedy')}</p>"
            '<p><a href="http://meld.sourceforge.net/">http://meld.sourceforge.net/</a></p>'
        )
        QMessageBox.about(self, _("About Meld"), html)

    # ----- tab lifecycle ----------------------------------------------------

    def current_doc(self):
        return self._doc_for_widget.get(self.tabs.currentWidget(), _DUMMY_DOC)

    def _close_current_tab(self):
        widget = self.tabs.currentWidget()
        if widget is None:
            return
        doc = self._doc_for_widget.get(widget)
        if doc is not None:
            self.try_remove_page(doc)

    def _on_tab_close_requested(self, index):
        doc = self._doc_for_widget.get(self.tabs.widget(index))
        if doc is not None:
            self.try_remove_page(doc)

    def _connect(self, signal, slot):
        signal.connect(slot)
        self._current_connections.append((signal, slot))

    def _disconnect_current(self):
        for signal, slot in self._current_connections:
            try:
                signal.disconnect(slot)
            except TypeError:
                pass
        self._current_connections = []

    def _on_current_tab_changed(self, index):
        old = self._current_doc
        if old is not None:
            old.on_container_switch_out_event()
            self._disconnect_current()

        if index < 0:
            self._current_doc = None
            self.dam.set_doc(None)
            self.pump.set_scheduler(None)
            self.setWindowTitle("Meld")
            for action in (self.action_undo, self.action_redo,
                           self.action_prev_change, self.action_next_change):
                action.setEnabled(False)
            return

        doc = self._doc_for_widget.get(self.tabs.widget(index))
        if doc is None:
            self._current_doc = None
            return
        self._current_doc = doc
        self.action_undo.setEnabled(doc.undosequence.can_undo())
        self.action_redo.setEnabled(doc.undosequence.can_redo())
        self._connect(doc.undosequence.can_undo_changed, self.action_undo.setEnabled)
        self._connect(doc.undosequence.can_redo_changed, self.action_redo.setEnabled)
        self._connect(doc.next_diff_changed, self._on_next_diff_changed)
        self.setWindowTitle(f"{self.tabs.tabText(index)} - Meld")
        self.set_doc_status("")
        self.dam.set_doc(doc)
        self.pump.set_scheduler(doc.scheduler)
        doc.on_container_switch_in_event()

    def _on_next_diff_changed(self, have_prev, have_next):
        self.action_prev_change.setEnabled(have_prev)
        self.action_next_change.setEnabled(have_next)

    def _append_page(self, doc, icon_name):
        self._doc_for_widget[doc.widget] = doc
        self.tabs.addTab(doc.widget, QIcon.fromTheme(icon_name), doc.label_text)
        self.tabs.setCurrentWidget(doc.widget)
        doc.label_changed.connect(lambda text, d=doc: self.on_label_changed(d, text))
        doc.file_changed.connect(lambda fn, d=doc: self.on_file_changed_broadcast(d, fn))
        doc.create_diff.connect(self.append_diff)
        doc.status_changed.connect(self.set_doc_status)

    def on_label_changed(self, doc, text):
        idx = self.tabs.indexOf(doc.widget)
        if idx >= 0:
            self.tabs.setTabText(idx, text)
            self.tabs.setTabToolTip(idx, text)
            if idx == self.tabs.currentIndex():
                self.setWindowTitle(f"{text} - Meld")

    def on_file_changed_broadcast(self, source_doc, filename):
        for doc in self._doc_for_widget.values():
            if doc is not source_doc:
                doc.on_file_changed(filename)

    def try_remove_page(self, doc, appquit=False):
        resp = doc.on_delete_event(appquit)
        if resp != CloseResponse.CANCEL:
            if doc is self._current_doc:
                self.dam.set_doc(None)
                self.pump.set_scheduler(None)
                self._disconnect_current()
                self._current_doc = None
            idx = self.tabs.indexOf(doc.widget)
            if idx >= 0:
                self.tabs.removeTab(idx)
            self._doc_for_widget.pop(doc.widget, None)
            doc.closed.emit()
            if self.tabs.count() == 0:
                self.setWindowTitle("Meld")
        return resp

    # ----- comparison factories (lazy doc imports) --------------------------

    def _unavailable(self, exc):
        QMessageBox.warning(
            self, "Meld",
            _("This comparison type is not available yet: %s") % exc)

    def append_dirdiff(self, dirs, auto_compare=False):
        assert len(dirs) in (1, 2, 3)
        try:
            from meldq import dirdiff
        except ImportError as exc:
            self._unavailable(exc)
            return None
        doc = dirdiff.DirDiff(self.prefs, len(dirs))
        self._append_page(doc, "tree-folder-normal")
        doc.set_locations(dirs)
        # FIXME: This doesn't work, as dirdiff behaves differently to vcview
        if auto_compare:
            doc.on_button_diff_clicked(None)
        return doc

    def append_filediff(self, files):
        assert len(files) in (1, 2, 3, 4)
        try:
            from meldq import filediff, filemerge
        except ImportError as exc:
            self._unavailable(exc)
            return None
        if len(files) == 4:
            doc = filemerge.FileMerge(self.prefs, 3)
        else:
            doc = filediff.FileDiff(self.prefs, len(files))
        doc.undosequence.clear()
        self._append_page(doc, "tree-file-normal")
        doc.set_files(files)
        return doc

    def append_diff(self, paths, auto_compare=False):
        dirslist = [p for p in paths if os.path.isdir(p)]
        fileslist = [p for p in paths if os.path.isfile(p)]
        if dirslist and fileslist:
            # build a file list appending the previous filename to dirs (like diff)
            lastfilename = fileslist[0]
            builtfilelist = []
            for elem in paths:
                if os.path.isdir(elem):
                    builtfilename = os.path.join(elem, lastfilename)
                    if os.path.isfile(builtfilename):
                        elem = builtfilename
                    else:
                        QMessageBox.warning(
                            self, "Meld",
                            _("Cannot compare a mixture of files and directories.\n"))
                        return
                else:
                    lastfilename = os.path.basename(elem)
                builtfilelist.append(elem)
            return self.append_filediff(builtfilelist)
        elif dirslist:
            return self.append_dirdiff(paths, auto_compare)
        else:
            return self.append_filediff(paths)

    def append_vcview(self, locations, auto_compare=False):
        assert len(locations) in (1,)
        try:
            from meldq import vcview
        except ImportError as exc:
            self._unavailable(exc)
            return None
        doc = vcview.VcView(self.prefs)
        self._append_page(doc, "vc-icon")
        doc.set_location(locations[0])
        if auto_compare:
            doc.on_button_diff_clicked(None)
        return doc

    def _single_file_open(self, path):
        try:
            from meldq import vcview
        except ImportError as exc:
            self._unavailable(exc)
            return
        doc = vcview.VcView(self.prefs)
        pump = SchedulerPump(self)
        entry = (pump, doc)
        self._transient_pumps.append(entry)

        def on_idle(idle):
            if idle:
                pump.stop()
                if entry in self._transient_pumps:
                    self._transient_pumps.remove(entry)

        pump.idle_changed.connect(on_idle)
        pump.set_scheduler(doc.scheduler)
        doc.create_diff.connect(self.append_diff)
        doc.run_diff([path])

    def open_paths(self, paths, auto_compare=False):
        tab = None
        if len(paths) == 1:
            a = paths[0]
            if os.path.isfile(a):
                self._single_file_open(a)
            else:
                tab = self.append_vcview([a], auto_compare)
        elif len(paths) in (2, 3, 4):
            tab = self.append_diff(paths, auto_compare)
        return tab

    def closeEvent(self, event):
        for i in range(self.tabs.count() - 1, -1, -1):
            self.tabs.setCurrentIndex(i)
            doc = self._doc_for_widget.get(self.tabs.widget(i))
            if doc is None:
                continue
            resp = self.try_remove_page(doc, appquit=True)
            if resp == CloseResponse.CANCEL:
                event.ignore()
                return
        for doc in list(self._doc_for_widget.values()):
            doc.on_quit_event()
        if self._geometry_save_timer.isActive():
            self._geometry_save_timer.stop()
            self._save_geometry()
        event.accept()


class DocActionManager(QObject):
    """Replaces gtk.UIManager per-tab merging.

    Populates each menu's named placeholder section and the toolbar's doc
    segment from the current doc's menu_contributions()/toolbar_contributions()
    on tab switch. Contributed actions stay parented to the doc widget; a
    removeAction here just makes them inert, so their shortcuts fire only
    while the doc is current.
    """

    MENU_KEYS = ("file", "edit", "changes", "view")

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def set_doc(self, doc):
        window = self.window
        for key in self.MENU_KEYS:
            self._clear_section(window.menus[key],
                                f"doc_section_start_{key}", f"doc_section_end_{key}")
        self._clear_section(window.toolbar, "doc_toolbar_start", "doc_toolbar_end")
        if doc is None:
            return

        contributions = doc.menu_contributions()
        for key in self.MENU_KEYS:
            menu = window.menus[key]
            section = self._materialize(menu, contributions.get(key, []))
            start = self._find(menu, f"doc_section_start_{key}")
            end = self._find(menu, f"doc_section_end_{key}")
            menu.insertActions(end, section)
            start.setVisible(bool(section))
            end.setVisible(bool(section))

        tb_section = self._materialize(window.toolbar, doc.toolbar_contributions())
        tb_start = self._find(window.toolbar, "doc_toolbar_start")
        tb_end = self._find(window.toolbar, "doc_toolbar_end")
        window.toolbar.insertActions(tb_end, tb_section)
        tb_start.setVisible(bool(tb_section))
        tb_end.setVisible(bool(tb_section))

        self._assert_no_shortcut_collision(doc)

    @staticmethod
    def _find(widget, object_name):
        for action in widget.actions():
            if action.objectName() == object_name:
                return action
        return None

    def _clear_section(self, widget, start_name, end_name):
        actions = widget.actions()
        start = self._find(widget, start_name)
        end = self._find(widget, end_name)
        if start is None or end is None:
            return
        for action in actions[actions.index(start) + 1:actions.index(end)]:
            widget.removeAction(action)

    @staticmethod
    def _materialize(parent, section):
        result = []
        for action in section:
            if action is None:      # §2.4: None -> separator (insertActions rejects None)
                separator = QAction(parent)
                separator.setSeparator(True)
                result.append(separator)
            else:
                result.append(action)
        return result

    def _assert_no_shortcut_collision(self, doc):
        shell = set()
        for name in dir(self.window):
            if name.startswith("action_"):
                shortcut = getattr(self.window, name).shortcut()
                if not shortcut.isEmpty():
                    shell.add(shortcut.toString())
        for action in doc.doc_actions():
            shortcut = action.shortcut()
            if not shortcut.isEmpty():
                assert shortcut.toString() not in shell, (
                    f"doc action shortcut {shortcut.toString()} "
                    "collides with a shell action")
