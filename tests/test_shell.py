"""M6: the application shell (meldq.shell.MeldWindow).

Exercises the shell's real integration surface — tab factories, the create_diff
wiring from tree views, CLI-style path dispatch, light/dark theming, save, and
the patch export/import UI — without ever entering a modal dialog (those hang
headless; the fixture stubs the only close-time prompt).
"""

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox

from meldq.shell import MeldWindow, NewComparisonDialog, PatchDialog
from meldq.util.prefs import Preferences
from meldq.views.dirdiff import DirDiffView
from meldq.views.filediff import FileDiffView
from meldq.views.vcview import VcView
from meldq.widgets.sciview import DARK, KIND_REPLACE, LIGHT


@pytest.fixture
def window(qapp, qtbot, tmp_path, monkeypatch):
    prefs = Preferences(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    # Never let close-time teardown raise a modal (would wedge offscreen).
    monkeypatch.setattr(MeldWindow, "_prompt_unsaved",
                        lambda self, view: QMessageBox.StandardButton.Discard)
    win = MeldWindow(prefs)
    qtbot.addWidget(win)
    return win


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.fixture
def two_files(tmp_path):
    a = _write(tmp_path / "a.txt", "one\ntwo\nthree\n")
    b = _write(tmp_path / "b.txt", "one\nTWO\nthree\n")
    return a, b


# ----- structure ------------------------------------------------------------

def test_menus_present(window):
    titles = [a.text() for a in window.menuBar().actions()]
    assert titles == ["&File", "&Edit", "&Changes", "&View", "&Help"]
    assert set(window.menus) == {"file", "edit", "changes", "view", "help"}


def test_starts_empty(window):
    assert window.tabs.count() == 0
    assert not window.action_save.isEnabled()      # nothing to act on
    assert not window.action_refresh.isEnabled()


# ----- filediff factory -----------------------------------------------------

def test_append_filediff_opens_tab_and_renders_diff(window, two_files):
    a, b = two_files
    view = window.append_filediff([a, b])
    assert isinstance(view, FileDiffView)
    assert window.tabs.count() == 1
    assert window.tabs.tabText(0) == "a.txt : b.txt"
    # The changed middle line is marked on both panes -> a real diff rendered.
    assert KIND_REPLACE in view.panes[0].chunk_kinds_at(1)
    assert KIND_REPLACE in view.panes[1].chunk_kinds_at(1)


def test_three_way_filediff(window, tmp_path):
    files = [_write(tmp_path / n, "x\n") for n in ("m.txt", "b.txt", "o.txt")]
    view = window.append_filediff(files)
    assert view.num_panes == 3


def test_four_files_drops_merge_output(window, tmp_path):
    files = [_write(tmp_path / n, "x\n") for n in ("1", "2", "3", "4")]
    view = window.append_filediff(files)
    assert view.num_panes == 3          # 4th (merge-output) slot dropped in v1


def test_bad_file_count_is_soft_error(window, tmp_path):
    assert window.append_filediff([_write(tmp_path / "only.txt", "x")]) is None
    assert window.tabs.count() == 0


# ----- action enablement per view type --------------------------------------

def test_action_state_filediff(window, two_files):
    window.append_filediff(list(two_files))
    assert window.action_save.isEnabled()
    assert window.action_prev_change.isEnabled()
    assert window.action_create_patch.isEnabled()
    assert not window.action_refresh.isEnabled()


def test_action_state_dirdiff(window, tmp_path):
    d1, d2 = tmp_path / "l", tmp_path / "r"
    d1.mkdir(); d2.mkdir()
    window.append_dirdiff([str(d1), str(d2)])
    assert window.action_refresh.isEnabled()
    assert not window.action_save.isEnabled()
    assert not window.action_prev_change.isEnabled()


# ----- path dispatch (CLI/open_paths) ---------------------------------------

def test_open_paths_two_files_makes_filediff(window, two_files):
    view = window.open_paths(list(two_files))
    assert isinstance(view, FileDiffView)


def test_open_paths_two_dirs_makes_dirdiff(window, tmp_path):
    d1, d2 = tmp_path / "l", tmp_path / "r"
    d1.mkdir(); d2.mkdir()
    view = window.open_paths([str(d1), str(d2)])
    assert isinstance(view, DirDiffView)


def test_open_paths_single_dir_makes_vcview(window, tmp_path):
    view = window.open_paths([str(tmp_path)])
    assert isinstance(view, VcView)


def test_open_paths_nonexistent_files_do_not_crash(window, tmp_path):
    # Regression: a missing path opened an empty, creatable pane instead of
    # crashing the app with FileNotFoundError.
    view = window.open_paths([str(tmp_path / "gone-a.txt"),
                              str(tmp_path / "gone-b.txt")])
    assert isinstance(view, FileDiffView)
    assert view.panes[0].text() == "" and view.panes[1].text() == ""


def test_save_creates_a_missing_file(window, tmp_path):
    missing = tmp_path / "new.txt"
    existing = _write(tmp_path / "there.txt", "x\n")
    view = window.open_paths([str(missing), existing])
    view.panes[0].replace_all_text("created\n")
    view.save(0, str(missing))
    assert missing.read_text(encoding="utf-8") == "created\n"


def test_single_path_diff_group_opens_vcview(window, tmp_path):
    # Regression: a 1-path --diff group (routed through open_paths) must open a
    # VC view, not silently fail the 2/3-only dir/file factories.
    view = window.open_paths([str(tmp_path)])
    assert isinstance(view, VcView)


def test_append_diff_mixed_file_and_dir(window, tmp_path):
    (tmp_path / "d").mkdir()
    _write(tmp_path / "d" / "f.txt", "left\n")
    f = _write(tmp_path / "f.txt", "right\n")
    view = window.append_diff([str(tmp_path / "d"), f])
    assert isinstance(view, FileDiffView)


# ----- create_diff wiring from tree views -----------------------------------

def test_dirdiff_row_activation_opens_filediff_tab(window, tmp_path):
    d1, d2 = tmp_path / "l", tmp_path / "r"
    d1.mkdir(); d2.mkdir()
    a = _write(d1 / "x.txt", "a\n")
    b = _write(d2 / "x.txt", "b\n")
    dv = window.append_dirdiff([str(d1), str(d2)])
    assert window.tabs.count() == 1
    dv.create_diff.emit([a, b])         # what on_activated emits for a file row
    assert window.tabs.count() == 2
    assert isinstance(window.tabs.currentWidget(), FileDiffView)


# ----- theming --------------------------------------------------------------

def test_dark_toggle_applies_and_persists(window, two_files):
    view = window.append_filediff(list(two_files))
    assert view.panes[0]._theme is LIGHT
    window.on_toggle_dark(True)
    assert window.prefs.theme == "dark"
    assert view.panes[0]._theme is DARK


def test_new_tab_inherits_current_theme(window, two_files):
    window.on_toggle_dark(True)
    view = window.append_filediff(list(two_files))
    assert view.panes[0]._theme is DARK


def test_theme_action_reflects_pref_at_startup(qapp, qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.setValue("prefs/theme", "dark")
    win = MeldWindow(Preferences(settings))
    qtbot.addWidget(win)
    assert win.action_dark_theme.isChecked()


# ----- save -----------------------------------------------------------------

def test_save_writes_modified_pane(window, two_files):
    a, b = two_files
    view = window.append_filediff([a, b])
    view.panes[1].replace_all_text("one\nEDITED\nthree\n")
    assert view.is_modified(1)
    window.on_save()
    with open(b, encoding="utf-8") as handle:
        assert handle.read() == "one\nEDITED\nthree\n"
    assert not view.is_modified(1)


# ----- patch export ---------------------------------------------------------

def test_patch_dialog_text_and_reverse(window, two_files):
    view = window.append_filediff(list(two_files))
    dialog = PatchDialog(view)
    qtbot_text = dialog.patch_text()
    assert "-two" in qtbot_text and "+TWO" in qtbot_text
    dialog.reverse.setChecked(True)
    reversed_text = dialog.patch_text()
    assert "-TWO" in reversed_text and "+two" in reversed_text


def test_patch_dialog_three_way_pane_selector(window, tmp_path):
    files = [_write(tmp_path / n, "x\n") for n in ("m", "b", "o")]
    view = window.append_filediff(files)
    dialog = PatchDialog(view)
    assert dialog.pair is not None and dialog.pair.count() == 2


# ----- patch import (the differentiator) ------------------------------------

PATCH = """--- a/a.txt
+++ b/a.txt
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
"""


def test_import_patch_opens_diff_of_source_vs_patched(window, tmp_path):
    _write(tmp_path / "a.txt", "one\ntwo\nthree\n")
    views = window.import_patch(str(tmp_path), PATCH)
    assert len(views) == 1
    view = views[0]
    assert view.panes[0].text() == "one\ntwo\nthree\n"      # original
    assert view.panes[1].text() == "one\nTWO\nthree\n"      # patched
    assert window.tabs.tabText(0).startswith("patch:")


def test_import_patch_original_pane_is_read_only(window, tmp_path):
    # The left "original" pane must be read-only so Save can only ever write the
    # patched (right) result, never clobber the source via the shared path.
    _write(tmp_path / "a.txt", "one\ntwo\nthree\n")
    view = window.import_patch(str(tmp_path), PATCH)[0]
    assert view.panes[0].isReadOnly()
    assert not view.panes[1].isReadOnly()


def test_import_patch_missing_source_is_new_file(window, tmp_path):
    add_patch = ("--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,1 @@\n+hello\n")
    views = window.import_patch(str(tmp_path), add_patch)
    assert views[0].panes[0].text() == ""
    assert views[0].panes[1].text() == "hello\n"


# ----- dialogs / lifecycle --------------------------------------------------

def test_new_comparison_dialog_constructs(window):
    dialog = NewComparisonDialog(window)
    assert dialog.notebook.count() == 3


def test_toolbar_and_statusbar_toggle_prefs(window):
    window.action_toolbar_visible.setChecked(False)
    assert window.prefs.toolbar_visible is False
    assert not window.toolbar.isVisibleTo(window)
    window.action_statusbar_visible.setChecked(False)
    assert window.prefs.statusbar_visible is False


def test_close_tab_removes_it(window, two_files):
    window.append_filediff(list(two_files))
    assert window.tabs.count() == 1
    window.on_close_tab()
    assert window.tabs.count() == 0
