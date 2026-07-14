import pytest
from PyQt6.QtCore import QSettings, Qt

from meldq.prefsdialog import COLOR_KEYS, PreferencesDialog
from meldq.util.prefs import Preferences


@pytest.fixture
def prefs(tmp_path):
    return Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))


@pytest.fixture
def dialog(qtbot, prefs):
    dlg = PreferencesDialog(None, prefs)
    qtbot.addWidget(dlg)
    return dlg


def test_tabs_present(dialog):
    titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert titles == ["Editor", "Display", "File Filters", "Text Filters", "Encoding"]


def test_checkbox_writes_through(qtbot, dialog, prefs):
    assert not dialog.check_spaces.isChecked()
    with qtbot.waitSignal(prefs.changed) as blocker:
        dialog.check_spaces.setChecked(True)
    assert blocker.args == ["spaces_instead_of_tabs"]
    assert prefs.spaces_instead_of_tabs is True


def test_tab_size_spinbox(dialog, prefs):
    dialog.spin_tabsize.setValue(8)
    assert prefs.tab_size == 8


def test_value_survives_restart(qtbot, tmp_path):
    settings_path = str(tmp_path / "t.ini")
    prefs = Preferences(QSettings(settings_path, QSettings.Format.IniFormat))
    dlg = PreferencesDialog(None, prefs)
    qtbot.addWidget(dlg)
    dlg.check_line_numbers.setChecked(True)
    prefs._settings.sync()
    reloaded = Preferences(QSettings(settings_path, QSettings.Format.IniFormat))
    assert reloaded.show_line_numbers is True


def test_system_editor_toggle(dialog, prefs):
    dialog.check_system_editor.setChecked(False)
    assert prefs.edit_command_type == "custom"
    assert dialog.entry_editor.isEnabled()
    dialog.check_system_editor.setChecked(True)
    assert prefs.edit_command_type == "internal"
    assert not dialog.entry_editor.isEnabled()


def test_wrap_toggle_stores_mode(dialog, prefs):
    dialog.check_wrap.setChecked(True)          # split checked by default -> 2
    assert prefs.edit_wrap_lines == 2
    dialog.check_split.setChecked(False)        # -> 1
    assert prefs.edit_wrap_lines == 1
    dialog.check_wrap.setChecked(False)         # -> 0
    assert prefs.edit_wrap_lines == 0


def test_filter_list_add_edit_delete_roundtrip(dialog, prefs):
    flist = dialog.file_filters
    start_rows = flist.model.rowCount()
    flist.on_item_new()
    assert flist.model.rowCount() == start_rows + 1
    # edit the new row's name and pattern
    flist.model.item(start_rows, 0).setText("MyFilter")
    flist.model.item(start_rows, 2).setText("*.tmp")
    assert "MyFilter\t0\t*.tmp" in prefs.filters
    # delete it
    flist.select_row(start_rows)
    flist.on_item_delete()
    assert flist.model.rowCount() == start_rows
    assert "MyFilter" not in prefs.filters


def test_filter_list_loads_defaults(dialog, prefs):
    # the default filters begin with "Backups"
    assert dialog.file_filters.model.item(0, 0).text() == "Backups"
    # text filters begin with "CVS keywords"
    assert dialog.text_filters.model.item(0, 0).text() == "CVS keywords"


def test_filter_revert(dialog, prefs):
    flist = dialog.file_filters
    flist.on_item_new()
    changed_count = flist.model.rowCount()
    flist.on_items_revert()
    # back to the default set (which does not include the blank "label" row)
    assert flist.model.rowCount() != changed_count
    assert flist.model.item(0, 0).text() == "Backups"


def test_color_button_writes_hex(dialog, prefs):
    key = "color_delete_bg"
    button = dialog.color_buttons[key]
    assert button.text() == prefs.color_delete_bg     # shows current hex
    assert len(COLOR_KEYS) == 10


def test_active_checkbox_toggle_writes(dialog, prefs):
    flist = dialog.text_filters
    item = flist.model.item(0, 1)
    before = prefs.regexes
    new_state = (Qt.CheckState.Unchecked
                 if item.checkState() == Qt.CheckState.Checked
                 else Qt.CheckState.Checked)
    item.setCheckState(new_state)
    assert prefs.regexes != before
