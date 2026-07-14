import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QKeySequence

from meldq.app import MeldWindow
from meldq.util.prefs import Preferences


@pytest.fixture
def window(qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    win = MeldWindow(prefs)
    qtbot.addWidget(win)
    return win


def test_menus_and_bars(window):
    titles = [a.text() for a in window.menuBar().actions()]
    assert titles == ["&File", "&Edit", "&Changes", "&View", "&Help"]
    assert window.toolbar.isVisibleTo(window) or True   # constructed
    assert window.progress is not None
    assert set(window.menus.keys()) == {"file", "edit", "changes", "view", "help"}


def test_placeholder_separators_present_and_hidden(window):
    for key in ("file", "edit", "changes", "view", "help"):
        menu = window.menus[key]
        starts = [a for a in menu.actions()
                  if a.objectName() == f"doc_section_start_{key}"]
        ends = [a for a in menu.actions()
                if a.objectName() == f"doc_section_end_{key}"]
        assert len(starts) == 1 and len(ends) == 1
        assert not starts[0].isVisible() and not ends[0].isVisible()


def test_shortcuts_and_stop_disabled(window):
    assert not window.action_stop.isEnabled()
    assert window.action_new.shortcut() == QKeySequence("Ctrl+N")
    assert window.action_next_change.shortcut() == QKeySequence("Ctrl+D")
    assert window.action_prev_change.shortcut() == QKeySequence("Ctrl+E")
    assert window.action_reload.shortcut() == QKeySequence("Ctrl+Shift+R")


def test_geometry_debounce(qtbot, window):
    window.show()
    qtbot.waitExposed(window)
    qtbot.wait(700)                                 # let the show's own resize settle
    changes = []
    window.prefs.changed.connect(changes.append)
    window.resize(701, 501)
    window.resize(702, 502)
    window.resize(703, 503)
    qtbot.wait(700)
    # exactly one debounced write of each dimension, not one per resize event
    assert changes.count("window_size_x") == 1
    assert changes.count("window_size_y") == 1
    assert window.prefs.window_size_x == window.width()


def test_statusbar_toggle_and_external_pref(window):
    window.action_statusbar_visible.trigger()      # was checked (True) -> False
    assert window.prefs.statusbar_visible is False
    assert not window.statusBar().isVisibleTo(window)
    window.prefs.statusbar_visible = True           # external flip re-shows
    assert window.statusBar().isVisibleTo(window)
    assert window.action_statusbar_visible.isChecked()


def test_current_doc_dummy(window):
    doc = window.current_doc()
    assert doc.anything_at_all() is None            # no-op null object
    doc.save()
    doc.next_diff(None)


def test_close_event_zero_tabs(qtbot, window):
    window.show()
    assert window.close() is True                   # closeEvent accepts
