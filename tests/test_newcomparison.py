import pytest
from PyQt6.QtCore import QSettings

from meldq.app import MeldWindow, NewComparisonDialog
from meldq.util.prefs import Preferences


@pytest.fixture
def window(qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    win = MeldWindow(prefs)
    qtbot.addWidget(win)
    return win


@pytest.fixture
def dialog(qtbot, window):
    calls = []
    window.append_filediff = lambda paths: calls.append(("file", paths))
    window.append_dirdiff = lambda paths, auto=False: calls.append(("dir", paths))
    window.append_vcview = lambda paths, auto=False: calls.append(("vc", paths))
    dlg = NewComparisonDialog(window)
    dlg.diff_methods = (window.append_filediff, window.append_dirdiff,
                        window.append_vcview)
    qtbot.addWidget(dlg)
    return dlg, calls


def test_tabs_titles(dialog):
    dlg, _ = dialog
    titles = [dlg.notebook.tabText(i) for i in range(dlg.notebook.count())]
    assert titles == ["&File Comparison", "&Directory Comparison",
                      "&Version Control Browser"]


def test_three_way_enables_other_entry(dialog):
    dlg, _ = dialog
    assert not dlg.fileentry0.isEnabled()      # "Other" disabled until 3-way
    dlg.three_way_compare0.setChecked(True)
    assert dlg.fileentry0.isEnabled()


def test_two_way_file_drops_other(dialog):
    dlg, calls = dialog
    dlg.notebook.setCurrentIndex(0)
    dlg.fileentry1.set_filename("/a")
    dlg.fileentry2.set_filename("/b")
    dlg.accept()
    assert calls == [("file", ["/a", "/b"])]   # pop(0) dropped the Other slot


def test_three_way_file_keeps_order(dialog):
    dlg, calls = dialog
    dlg.notebook.setCurrentIndex(0)
    dlg.three_way_compare0.setChecked(True)
    dlg.fileentry0.set_filename("/other")
    dlg.fileentry1.set_filename("/original")
    dlg.fileentry2.set_filename("/mine")
    dlg.accept()
    assert calls == [("file", ["/other", "/original", "/mine"])]


def test_vc_tab_single_path(dialog):
    dlg, calls = dialog
    dlg.notebook.setCurrentIndex(2)
    dlg.vcentry0.set_filename("/repo")
    dlg.accept()
    assert calls == [("vc", ["/repo"])]


def test_history_persisted_after_accept(qtbot, window):
    from meldq.widgets.historycombo import FileHistoryCombo
    window.append_filediff = lambda paths: None
    dlg = NewComparisonDialog(window)
    dlg.diff_methods = (window.append_filediff, window.append_dirdiff,
                        window.append_vcview)
    qtbot.addWidget(dlg)
    dlg.notebook.setCurrentIndex(0)
    dlg.fileentry1.set_filename("/somewhere/file.txt")
    dlg.fileentry2.set_filename("/elsewhere/file.txt")
    dlg.accept()
    fresh = FileHistoryCombo("file_comparison", settings=window.prefs._settings)
    stored = [fresh.combo.itemText(i) for i in range(fresh.combo.count())]
    assert "/somewhere/file.txt" in stored
    assert "/elsewhere/file.txt" in stored
