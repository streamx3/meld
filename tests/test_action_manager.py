import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QLabel, QMenu

from meldq.app import MeldWindow
from meldq.doc import CloseResponse, MeldDoc
from meldq.util.prefs import Preferences


class FakeDoc(MeldDoc):
    def __init__(self, prefs, name):
        super().__init__(prefs)
        self.widget = QLabel(name)
        self.label_text = name
        self.edit_action = QAction(f"{name}-Edit", self.widget)
        self.tool_action = QAction(f"{name}-Tool", self.widget)
        self.view_menu = QMenu(f"{name}-View", self.widget)
        self.delete_response = CloseResponse.OK

    def doc_actions(self):
        return [self.edit_action, self.tool_action]

    def menu_contributions(self):
        return {"edit": [self.edit_action], "view": [self.view_menu.menuAction()]}

    def toolbar_contributions(self):
        return [self.tool_action]

    def on_delete_event(self, appquit=False):
        return self.delete_response


@pytest.fixture
def window(qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    win = MeldWindow(prefs)
    qtbot.addWidget(win)
    return win


def edit_section(window):
    menu = window.menus["edit"]
    actions = menu.actions()
    start = next(a for a in actions if a.objectName() == "doc_section_start_edit")
    end = next(a for a in actions if a.objectName() == "doc_section_end_edit")
    return actions[actions.index(start) + 1:actions.index(end)]


def test_append_populates_current_doc_section(window):
    a = FakeDoc(window.prefs, "A")
    b = FakeDoc(window.prefs, "B")
    window._append_page(a, "tree-file-normal")
    window._append_page(b, "tree-file-normal")
    assert window.tabs.count() == 2
    assert window.current_doc() is b
    section = edit_section(window)
    assert b.edit_action in section
    assert a.edit_action not in section
    start = next(x for x in window.menus["edit"].actions()
                 if x.objectName() == "doc_section_start_edit")
    assert start.isVisible()


def test_switch_swaps_sections(window):
    a = FakeDoc(window.prefs, "A")
    b = FakeDoc(window.prefs, "B")
    window._append_page(a, "tree-file-normal")
    window._append_page(b, "tree-file-normal")
    window.tabs.setCurrentIndex(0)
    section = edit_section(window)
    assert a.edit_action in section
    assert b.edit_action not in section


def test_try_remove_page_cancel_and_ok(qtbot, window):
    a = FakeDoc(window.prefs, "A")
    window._append_page(a, "tree-file-normal")
    a.delete_response = CloseResponse.CANCEL
    assert window.try_remove_page(a) == CloseResponse.CANCEL
    assert window.tabs.count() == 1
    a.delete_response = CloseResponse.OK
    with qtbot.waitSignal(a.closed):
        window.try_remove_page(a)
    assert window.tabs.count() == 0


def test_undo_sensitivity_follows_current(window):
    a = FakeDoc(window.prefs, "A")
    b = FakeDoc(window.prefs, "B")
    window._append_page(a, "tree-file-normal")
    window._append_page(b, "tree-file-normal")   # b current
    a.undosequence.can_undo_changed.emit(True)   # not current -> ignored
    assert not window.action_undo.isEnabled()
    window.tabs.setCurrentIndex(0)               # a current
    a.undosequence.can_undo_changed.emit(True)
    assert window.action_undo.isEnabled()


def test_label_changed_updates_tab_and_title(window):
    a = FakeDoc(window.prefs, "A")
    window._append_page(a, "tree-file-normal")
    a.label_changed.emit("renamed")
    idx = window.tabs.indexOf(a.widget)
    assert window.tabs.tabText(idx) == "renamed"
    assert window.windowTitle() == "renamed - Meld"


def test_close_all_right_to_left(window):
    order = []
    docs = []
    for name in ("A", "B", "C"):
        d = FakeDoc(window.prefs, name)
        d.on_delete_event = lambda appquit=False, n=name: (order.append(n) or CloseResponse.OK)
        window._append_page(d, "tree-file-normal")
        docs.append(d)
    window.close()
    assert order == ["C", "B", "A"]


def test_append_filediff_without_module_warns(window, monkeypatch):
    warnings = []
    monkeypatch.setattr("meldq.app.QMessageBox.warning",
                        lambda *a, **k: warnings.append(a))
    result = window.append_filediff(["a", "b"])
    assert result is None
    assert len(warnings) == 1
