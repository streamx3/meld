"""M6: the application shell (meldq.shell.MeldWindow).

Exercises the shell's real integration surface — tab factories, the create_diff
wiring from tree views, CLI-style path dispatch, light/dark theming, save, and
the patch export/import UI — without ever entering a modal dialog (those hang
headless; the fixture stubs the only close-time prompt).
"""

import pytest
from PyQt6.QtCore import QEvent, QSettings
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

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

def test_theme_menu_has_system_light_dark(window):
    assert list(window._theme_actions) == ["system", "light", "dark"]
    assert window.prefs.theme == "system"          # default follows the OS


def test_dark_mode_applies_and_persists(window, two_files):
    view = window.append_filediff(list(two_files))
    assert view.panes[0]._theme is LIGHT
    window._set_theme_pref("dark")
    assert window.prefs.theme == "dark"
    assert view.panes[0]._theme is DARK
    assert window._theme_actions["dark"].isChecked()


def test_new_tab_inherits_current_theme(window, two_files):
    window._set_theme_pref("dark")
    view = window.append_filediff(list(two_files))
    assert view.panes[0]._theme is DARK


def test_theme_action_reflects_pref_at_startup(qapp, qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.setValue("prefs/theme", "dark")
    win = MeldWindow(Preferences(settings))
    qtbot.addWidget(win)
    assert win._theme_actions["dark"].isChecked()


def test_dark_mode_reaches_tree_views(window, tmp_path):
    from meldq.views.dirdiff import ROLE_STATE, _FG
    from meldq.dircompare import STATE_MODIFIED
    d1, d2 = tmp_path / "l", tmp_path / "r"
    d1.mkdir(); d2.mkdir()
    (d1 / "x.txt").write_text("a\n"); (d2 / "x.txt").write_text("b\n")
    dv = window.append_dirdiff([str(d1), str(d2)])
    window._set_theme_pref("dark")
    assert dv._mode == "dark"
    # a modified row now carries the dark-tuned blue, not the light one.
    idx = dv.model.index(0, 0)
    assert dv.model.itemFromIndex(idx).data(ROLE_STATE) == STATE_MODIFIED
    assert dv.model.itemFromIndex(idx).foreground().color().name() == _FG["dark"][STATE_MODIFIED]


def test_dirdiff_tree_has_zebra_and_equal_columns(window, tmp_path):
    from PyQt6.QtWidgets import QHeaderView
    d1, d2 = tmp_path / "l", tmp_path / "r"
    d1.mkdir(); d2.mkdir()
    dv = window.append_dirdiff([str(d1), str(d2)])
    assert dv.tree.alternatingRowColors()
    assert dv.tree.header().sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert dv.tree.header().sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch


def test_vcview_status_column_hugs_label(window, tmp_path):
    # Regression: stretchLastSection (Qt default True) would force Status to
    # fill half the width; it must be off so Name stretches, Status hugs.
    from PyQt6.QtWidgets import QHeaderView
    vv = window.open_paths([str(tmp_path)])
    header = vv.tree.header()
    assert header.stretchLastSection() is False
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.ResizeToContents


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


def test_new_comparison_invalid_input_keeps_dialog(window):
    # X8: OK with insufficient input must not close (discarding what was typed).
    dlg = NewComparisonDialog(window)
    dlg.notebook.setCurrentIndex(0)                 # file tab, nothing entered
    before = window.tabs.count()
    dlg.accept()
    assert window.tabs.count() == before            # no comparison opened
    assert dlg.error_label.text()                   # validation message shown
    assert dlg.result() != QDialog.DialogCode.Accepted
    dlg.reject()


def test_four_file_comparison_warns(window, tmp_path):
    # X7: a 4th file path is dropped, but with a warning (not silently).
    paths = []
    for i in range(4):
        p = tmp_path / f"f{i}.txt"
        p.write_text(f"content {i}\n")
        paths.append(str(p))
    view = window.append_filediff(paths)
    assert view is not None and view.num_panes == 3   # first 3 compared


def test_dirdiff_activate_one_sided_file_opens_tab(window, tmp_path):
    # D1 end-to-end: activating a file present on only one side opens a
    # FileDiff tab (against an empty pane), not a rejected soft-warning.
    left, right = tmp_path / "l", tmp_path / "r"
    (left).mkdir()
    (right).mkdir()
    (left / "only.txt").write_text("hello\n")
    view = window.append_dirdiff([str(left), str(right)])
    from tests.test_dirdiff_view import top_rows
    before = window.tabs.count()
    view.on_activated(top_rows(view)["only.txt"])
    assert window.tabs.count() == before + 1
    fd = window.tabs.currentWidget()
    assert fd.panes[0].text() == "hello\n"
    assert fd.panes[1].text() == ""             # missing side -> empty pane


def test_close_tab_kept_open_when_save_fails(window, two_files, monkeypatch):
    # S1: choosing Save on close must NOT destroy the tab if the save fails.
    a, b = two_files
    view = window.append_filediff([a, b])
    view.panes[0].set_text("edited\n")
    assert view.is_modified(0)

    def boom(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(view, "save", boom)
    monkeypatch.setattr(window, "_prompt_unsaved",
                        lambda v: QMessageBox.StandardButton.Save)
    idx = window.tabs.indexOf(view)
    before = window.tabs.count()
    window._on_tab_close_requested(idx)
    assert window.tabs.count() == before          # tab still open
    assert window.tabs.indexOf(view) >= 0


def test_close_tab_proceeds_when_save_succeeds(window, two_files, monkeypatch):
    a, b = two_files
    view = window.append_filediff([a, b])
    view.panes[0].set_text("edited\n")
    monkeypatch.setattr(window, "_prompt_unsaved",
                        lambda v: QMessageBox.StandardButton.Save)
    before = window.tabs.count()
    window._on_tab_close_requested(window.tabs.indexOf(view))
    assert window.tabs.count() == before - 1      # saved cleanly, tab closed


def test_edit_undo_reverts_a_merge(window, two_files):
    # M3: Edit>Undo (Ctrl+Z) routes through the view so it undoes the merge,
    # which edited the pane that does not hold focus.
    a, b = two_files
    view = window.append_filediff([a, b])
    view.panes[0].action_clicked.emit(1)            # merge left -> right
    merged = view.panes[1].text()
    assert merged == view.panes[0].text()
    view.panes[0].setFocus()
    window.action_undo.trigger()                    # the real menu action
    assert view.panes[1].text() != merged           # merge undone


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
    assert dialog.pair is not None
    pairs = [dialog.pair.itemData(i) for i in range(dialog.pair.count())]
    assert pairs == [(0, 1), (1, 2), (0, 2)]        # incl. Left ↔ Right


def test_patch_dialog_left_right_pair(window, tmp_path):
    files = [_write(tmp_path / "m", "left\n"),
             _write(tmp_path / "b", "base\n"),
             _write(tmp_path / "o", "right\n")]
    view = window.append_filediff(files)
    dialog = PatchDialog(view)
    dialog.pair.setCurrentIndex(2)                  # Left ↔ Right
    text = dialog.patch_text()
    assert "-left" in text and "+right" in text     # diffs panes 0 and 2


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

def test_import_patch_saves_back_with_source_encoding(window, tmp_path):
    # Regression: a latin-1 source patched + accepted must save back losslessly,
    # not get clobbered as UTF-8 (the read used to be utf-8/errors=replace).
    src = tmp_path / "f.txt"
    src.write_bytes("caf\xe9\nline2\n".encode("latin-1"))
    patch = ("--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n"
             " caf\xe9\n-line2\n+LINE2\n")
    view = window.import_patch(str(tmp_path), patch)[0]
    assert view.panes[1].text() == "caf\xe9\nLINE2\n"      # decoded, not mojibake
    view.save(1)                                            # accept -> write back
    assert src.read_bytes() == "caf\xe9\nLINE2\n".encode("latin-1")


def test_patch_dialog_closes_when_its_tab_closes(window, two_files):
    # C3: a modeless PatchDialog holding a FileDiffView must not outlive it —
    # interacting with a dialog whose view was deleted aborts the app.
    view = window.append_filediff(list(two_files))
    dialog = window.on_create_patch()
    closed = []
    dialog.finished.connect(lambda _r: closed.append(True))
    window._on_tab_close_requested(window.tabs.currentIndex())
    # Flush the view's deferred deletion so its destroyed() fires.
    QApplication.sendPostedEvents(view, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    assert closed == [True]                     # dialog auto-closed with its tab


def test_import_patch_on_save_writes_patched_result(window, tmp_path):
    # C4: accept the whole patch, then File>Save. The patched pane must be
    # marked modified so on_save() actually writes it (it used to be a no-op).
    src = tmp_path / "a.txt"
    _write(src, "one\ntwo\nthree\n")
    view = window.import_patch(str(tmp_path), PATCH)[0]
    assert view.is_modified(1)                 # patched pane flagged for save
    assert view.any_modified()
    window.tabs.setCurrentWidget(view)
    window.on_save()
    assert src.read_text() == "one\nTWO\nthree\n"
    assert not view.is_modified(1)


def test_import_patch_noop_is_not_modified(window, tmp_path):
    # A patch whose result equals the source leaves nothing to save.
    src = tmp_path / "a.txt"
    _write(src, "one\ntwo\n")
    noop = "--- a/a.txt\n+++ b/a.txt\n@@ -1,1 +1,1 @@\n-one\n+one\n"
    view = window.import_patch(str(tmp_path), noop)[0]
    assert view.panes[1].text() == "one\ntwo\n"
    assert not view.is_modified(1)


def test_custom_font_pref_applies_to_editors(window, two_files):
    from PyQt6.QtGui import QFont
    view = window.append_filediff(list(two_files))
    window.prefs.use_custom_font = True
    window.prefs.custom_font = QFont("Courier New", 12).toString()
    assert view.panes[0]._base_font.family() == "Courier New"


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


def test_vc_conflict_opens_three_way_resolve(window, tmp_path):
    # Priority-1: activating a UU-conflicted file opens ours|working|theirs with
    # read-only outer panes; merging + saving resolves into the working file.
    import subprocess

    from meldq import gitvc
    if not gitvc.is_git_available():
        import pytest
        pytest.skip("git not available")

    def git(repo, *args):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        *args], cwd=repo, check=True, capture_output=True)

    r = tmp_path / "cr"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "f.txt").write_text("base\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    git(r, "checkout", "-q", "-b", "other")
    (r / "f.txt").write_text("theirs\n")
    git(r, "commit", "-qam", "theirs")
    git(r, "checkout", "-q", "main")
    (r / "f.txt").write_text("ours\n")
    git(r, "commit", "-qam", "ours")
    subprocess.run(["git", "merge", "other"], cwd=r, capture_output=True)

    vc = window.append_vcview(str(r))
    row = vc.model.index(0, 0)
    before = window.tabs.count()
    vc.on_activated(row)
    assert window.tabs.count() == before + 1
    fd = window.tabs.currentWidget()
    assert fd.num_panes == 3
    assert fd.panes[0].isReadOnly() and fd.panes[2].isReadOnly()
    assert not fd.panes[1].isReadOnly()
    assert fd.panes[0].text() == "ours\n"
    assert fd.panes[2].text() == "theirs\n"
    assert "<<<<<<<" in fd.panes[1].text()        # working copy with markers
    # Resolve: take "theirs" wholesale into the middle and save.
    fd.panes[1].set_text("theirs\n")
    fd.save(1, force=True)
    assert (r / "f.txt").read_text() == "theirs\n"
    # Add marks it resolved -> no longer conflicted.
    assert gitvc.add(str(r), "f.txt")
    assert gitvc.status(str(r)).get("f.txt") != gitvc.STATE_CONFLICT


# ----- preferences dialog ----------------------------------------------------

def test_preferences_dialog_writes_prefs(window):
    from meldq.shell import PreferencesDialog
    dlg = PreferencesDialog(window)
    dlg.use_custom.setChecked(True)
    dlg.size_spin.setValue(15)
    dlg.tab_spin.setValue(8)
    dlg.theme_combo.setCurrentIndex(dlg.theme_combo.findData("dark"))
    dlg.filter_edit.setText("*.pyc build")
    dlg.accept()
    assert window.prefs.use_custom_font is True
    assert ",15," in window.prefs.custom_font or ",15" in window.prefs.custom_font
    assert window.prefs.tab_size == 8
    assert window.prefs.theme == "dark"
    assert window.prefs.dirdiff_name_filters == "*.pyc build"


def test_tab_size_pref_applies_to_panes(window, two_files):
    view = window.append_filediff(list(two_files))
    assert view.panes[0].tabWidth() == 4            # default
    window.prefs.tab_size = 8
    assert view.panes[0].tabWidth() == 8            # live re-apply


def test_dirdiff_filter_pref_seeds_new_tabs(window, tmp_path):
    window.prefs.dirdiff_name_filters = "*.bak"
    left, right = tmp_path / "l", tmp_path / "r"
    for d in (left, right):
        d.mkdir()
        (d / "keep.txt").write_text("x")
        (d / "junk.bak").write_text("x")
    view = window.append_dirdiff([str(left), str(right)])
    from tests.test_dirdiff_view import top_rows
    rows = top_rows(view)
    assert "keep.txt" in rows and "junk.bak" not in rows
    assert view.filter_edit.text() == "*.bak"       # visible in the filter bar


def test_dirdiff_filter_pref_updates_open_tabs(window, tmp_path):
    left, right = tmp_path / "l", tmp_path / "r"
    for d in (left, right):
        d.mkdir()
        (d / "keep.txt").write_text("x")
        (d / "junk.tmp").write_text("x")
    view = window.append_dirdiff([str(left), str(right)])
    from tests.test_dirdiff_view import top_rows
    assert "junk.tmp" in top_rows(view)
    window.prefs.dirdiff_name_filters = "*.tmp"     # change pref while open
    assert "junk.tmp" not in top_rows(view)


def test_go_to_line(window, two_files):
    view = window.append_filediff(list(two_files))
    assert view.go_to_line(3) == 2                  # 1-based -> row index 2
    assert view.panes[0].getCursorPosition() == (2, 0)
    assert view.go_to_line(9999) == view.panes[0].lines() - 1   # clamped
    assert window.action_go_to_line.isEnabled()


# ----- zoom (one app-wide level) --------------------------------------------

def test_zoom_is_app_wide_and_syncs_panes(window, two_files):
    v1 = window.append_filediff(list(two_files))
    a2 = _write(__import__("pathlib").Path(v1.path(0)).parent / "c.txt", "x\n")
    v2 = window.append_filediff([a2, v1.path(1)])
    window.on_zoom_in()
    window.on_zoom_in()                             # zoom = 2
    assert window.prefs.zoom == 2
    for v in (v1, v2):
        for pane in v.panes:
            assert pane.SendScintilla(pane.SCI_GETZOOM) == 2   # every pane, every tab
    window.on_zoom_normal()
    assert all(p.SendScintilla(p.SCI_GETZOOM) == 0
               for v in (v1, v2) for p in v.panes)


def test_user_pane_zoom_propagates(window, two_files):
    v = window.append_filediff(list(two_files))
    v.panes[0].zoomTo(3)                            # simulate Ctrl+scroll on one pane
    v.panes[0].zoom_changed.emit(3)                 # the signal Scintilla would emit
    assert window.prefs.zoom == 3
    assert v.panes[1].SendScintilla(v.panes[1].SCI_GETZOOM) == 3   # sibling caught up


# ----- editor display prefs -------------------------------------------------

def test_editor_display_prefs_apply(window, two_files):
    v = window.append_filediff(list(two_files))
    window.prefs.show_line_numbers = False
    assert v.panes[0].marginWidth(0) == 0
    window.prefs.show_line_numbers = True
    assert v.panes[0].marginWidth(0) > 0
    from PyQt6.Qsci import QsciScintilla
    window.prefs.show_right_margin = True
    window.prefs.right_margin_column = 100
    assert v.panes[0].edgeColumn() == 100
    assert v.panes[0].edgeMode() != QsciScintilla.EdgeMode.EdgeNone


def test_syntax_toggle_off_drops_lexer(window, tmp_path):
    a = _write(tmp_path / "a.py", "x = 1\n")
    b = _write(tmp_path / "b.py", "x = 2\n")
    v = window.append_filediff([a, b])
    assert v.panes[0].lexer() is not None           # python lexer on by default
    window.prefs.use_syntax_highlighting = False
    assert v.panes[0].lexer() is None


# ----- managed filter lists + folder prefs ----------------------------------

def test_file_filter_list_hides_matching_names(window, tmp_path):
    window.prefs.set_filter_entries(
        "filters", [("Objects", True, "*.o *.obj")])
    left, right = tmp_path / "l", tmp_path / "r"
    for d in (left, right):
        d.mkdir()
        (d / "keep.c").write_text("x")
        (d / "junk.o").write_text("x")
    view = window.append_dirdiff([str(left), str(right)])
    from tests.test_dirdiff_view import top_rows
    rows = top_rows(view)
    assert "keep.c" in rows and "junk.o" not in rows


def test_shallow_pref_applies(window, tmp_path):
    window.prefs.folder_shallow = True
    left, right = tmp_path / "l", tmp_path / "r"
    for d in (left, right):
        d.mkdir()
    # same size + mtime but different content -> shallow reports NORMAL
    import os
    (left / "f.txt").write_bytes(b"AAA")
    (right / "f.txt").write_bytes(b"BBB")
    t = 1_600_000_000
    os.utime(left / "f.txt", (t, t))
    os.utime(right / "f.txt", (t, t))
    view = window.append_dirdiff([str(left), str(right)])
    from meldq.dircompare import STATE_NORMAL
    from tests.test_dirdiff_view import top_rows
    assert view.row_state(top_rows(view)["f.txt"], 0) == STATE_NORMAL


def test_swap_panes(window, two_files):
    a, b = two_files
    view = window.append_filediff([a, b])
    left_before = view.panes[0].text()
    assert view.swap_panes()
    assert view.panes[1].text() == left_before        # texts exchanged
    assert view.path(0) == b and view.path(1) == a    # paths exchanged
    assert window.tabs.tabText(0) == "a.txt : b.txt"  # (title refresh via action)
    window.on_swap_panes()                            # swap back via the action
    assert view.path(0) == a
    assert window.tabs.tabText(0) == "a.txt : b.txt"


def test_swap_refused_when_modified(window, two_files):
    view = window.append_filediff(list(two_files))
    view.panes[0].set_text("edited\n")
    assert view.is_modified(0)
    assert not view.swap_panes()                      # refused, nothing lost
    assert view.panes[0].text() == "edited\n"
