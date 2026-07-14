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

"""Preferences dialog.

Built in code rather than a Qt Designer .ui file: the layout is static but
hand-authoring Designer XML without Designer is error-prone and the result
is identical and more testable. Follows the 1.4 write-through-on-change
model (no OK/Cancel) — every control writes straight to Preferences, which
emits changed(name).
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFontDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from meldq.conf import _, mnemonic
from meldq.util.misc import ListItem

# Colour prefs, exposed here because gconf (their 1.4 home) is gone.
COLOR_KEYS = [
    ("color_delete_bg", "Delete background"),
    ("color_delete_fg", "Delete text"),
    ("color_replace_bg", "Replace background"),
    ("color_replace_fg", "Replace text"),
    ("color_conflict_bg", "Conflict background"),
    ("color_conflict_fg", "Conflict text"),
    ("color_inline_bg", "Inline background"),
    ("color_inline_fg", "Inline text"),
    ("color_edited_bg", "Edited background"),
    ("color_edited_fg", "Edited text"),
]


class FilterList(QWidget):
    """Editable Name/Active/value list backed by a tab-separated pref string.

    Ports meld/preferences.py:31-116 (ListWidget). Rows serialise to the
    pref as ``name\\tactive\\tvalue`` lines; write-through happens on every
    edit/toggle/reorder.
    """

    def __init__(self, prefs, key, value_header, parent=None):
        super().__init__(parent)
        self.prefs = prefs
        self.key = key
        self._loading = False

        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels([_("Name"), _("Active"), value_header])
        self.model.itemChanged.connect(self._on_item_changed)

        self.view = QTreeView()
        self.view.setModel(self.model)
        self.view.setRootIsDecorated(False)
        self.view.selectionModel().selectionChanged.connect(self._update_sensitivity)

        self.button_new = QPushButton(_("New"))
        self.button_delete = QPushButton(_("Delete"))
        self.button_up = QPushButton(_("Up"))
        self.button_down = QPushButton(_("Down"))
        self.button_revert = QPushButton(_("Revert"))
        self.button_new.clicked.connect(self.on_item_new)
        self.button_delete.clicked.connect(self.on_item_delete)
        self.button_up.clicked.connect(self.on_item_up)
        self.button_down.clicked.connect(self.on_item_down)
        self.button_revert.clicked.connect(self.on_items_revert)

        buttons = QVBoxLayout()
        for b in (self.button_new, self.button_delete, self.button_up,
                  self.button_down, self.button_revert):
            buttons.addWidget(b)
        buttons.addStretch(1)

        layout = QHBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addLayout(buttons)

        self._load_from_prefs()
        self._update_sensitivity()

    def _make_row(self, name, active, value):
        name_item = QStandardItem(name)
        active_item = QStandardItem()
        active_item.setCheckable(True)
        active_item.setEditable(False)
        active_item.setCheckState(
            Qt.CheckState.Checked if active else Qt.CheckState.Unchecked)
        value_item = QStandardItem(value)
        return [name_item, active_item, value_item]

    def _load_from_prefs(self):
        self._loading = True
        self.model.removeRows(0, self.model.rowCount())
        raw = getattr(self.prefs, self.key)
        for line in raw.split("\n"):
            if not line:
                continue
            item = ListItem(line)
            self.model.appendRow(self._make_row(item.name, item.active, item.value))
        self._loading = False

    def _write_to_prefs(self):
        rows = []
        for r in range(self.model.rowCount()):
            name = self.model.item(r, 0).text()
            active = 1 if self.model.item(r, 1).checkState() == Qt.CheckState.Checked else 0
            value = self.model.item(r, 2).text()
            rows.append("%s\t%s\t%s" % (name, active, value))
        setattr(self.prefs, self.key, "\n".join(rows))

    def _on_item_changed(self, item):
        if not self._loading:
            self._write_to_prefs()

    def _selected_row(self):
        indexes = self.view.selectionModel().selectedRows()
        return indexes[0].row() if indexes else None

    def select_row(self, row):
        self.view.setCurrentIndex(self.model.index(row, 0))

    def _update_sensitivity(self, *args):
        row = self._selected_row()
        has = row is not None
        self.button_delete.setEnabled(has)
        self.button_up.setEnabled(has and row > 0)
        self.button_down.setEnabled(has and row < self.model.rowCount() - 1)

    def on_item_new(self):
        self.model.appendRow(self._make_row(_("label"), False, _("pattern")))
        self._write_to_prefs()

    def on_item_delete(self):
        row = self._selected_row()
        if row is not None:
            self.model.removeRow(row)
            self._write_to_prefs()

    def on_item_up(self):
        row = self._selected_row()
        if row is not None and row > 0:
            taken = self.model.takeRow(row)
            self.model.insertRow(row - 1, taken)
            self.select_row(row - 1)
            self._write_to_prefs()

    def on_item_down(self):
        row = self._selected_row()
        if row is not None and row < self.model.rowCount() - 1:
            taken = self.model.takeRow(row)
            self.model.insertRow(row + 1, taken)
            self.select_row(row + 1)
            self._write_to_prefs()

    def on_items_revert(self):
        setattr(self.prefs, self.key, self.prefs.get_default(self.key))
        self._load_from_prefs()
        self._update_sensitivity()


class PreferencesDialog(QDialog):
    def __init__(self, parent, prefs):
        super().__init__(parent)
        self.prefs = prefs
        self.setWindowTitle(_("Meld Preferences"))

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_editor_tab(), _("Editor"))
        self.tabs.addTab(self._build_display_tab(), _("Display"))
        self.tabs.addTab(self._build_file_filters_tab(), _("File Filters"))
        self.tabs.addTab(self._build_text_filters_tab(), _("Text Filters"))
        self.tabs.addTab(self._build_encoding_tab(), _("Encoding"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    # ----- editor tab -------------------------------------------------------

    def _build_editor_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        font_group = QGroupBox(_("Font"))
        font_layout = QVBoxLayout(font_group)
        self.check_default_font = QCheckBox(mnemonic(_("_Use the system fixed width font")))
        self.check_default_font.setChecked(not self.prefs.use_custom_font)
        self.check_default_font.toggled.connect(self._on_default_font_toggled)
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel(mnemonic(_("_Editor font:"))))
        self.button_font = QPushButton()
        self.button_font.clicked.connect(self._on_pick_font)
        self.button_font.setEnabled(bool(self.prefs.use_custom_font))
        self._refresh_font_button()
        font_row.addWidget(self.button_font, 1)
        font_layout.addWidget(self.check_default_font)
        font_layout.addLayout(font_row)
        layout.addWidget(font_group)

        display_group = QGroupBox(_("Display"))
        display_layout = QVBoxLayout(display_group)
        tab_row = QHBoxLayout()
        tab_row.addWidget(QLabel(mnemonic(_("_Tab width:"))))
        self.spin_tabsize = QSpinBox()
        self.spin_tabsize.setRange(1, 32)
        self.spin_tabsize.setValue(int(self.prefs.tab_size))
        self.spin_tabsize.valueChanged.connect(
            lambda v: setattr(self.prefs, "tab_size", int(v)))
        tab_row.addWidget(self.spin_tabsize)
        tab_row.addStretch(1)
        display_layout.addLayout(tab_row)

        self.check_spaces = QCheckBox(mnemonic(_("_Insert spaces instead of tabs")))
        self.check_spaces.setChecked(bool(self.prefs.spaces_instead_of_tabs))
        self.check_spaces.toggled.connect(
            lambda c: setattr(self.prefs, "spaces_instead_of_tabs", c))
        display_layout.addWidget(self.check_spaces)

        self.check_wrap = QCheckBox(mnemonic(_("Enable text _wrapping")))
        self.check_split = QCheckBox(mnemonic(_("Do not _split words over two lines")))
        # 1.4 numbering: 0=none, 1=split allowed, 2=no split (preferences.py:149-201)
        self.check_split.setChecked(True)
        if self.prefs.edit_wrap_lines != 0:
            if self.prefs.edit_wrap_lines == 1:
                self.check_split.setChecked(False)
            self.check_wrap.setChecked(True)
        self.check_split.setEnabled(self.check_wrap.isChecked())
        self.check_wrap.toggled.connect(self._on_wrap_toggled)
        self.check_split.toggled.connect(self._on_split_toggled)
        display_layout.addWidget(self.check_wrap)
        display_layout.addWidget(self.check_split)

        self.check_line_numbers = QCheckBox(mnemonic(_("Show _line numbers")))
        self.check_line_numbers.setChecked(bool(self.prefs.show_line_numbers))
        self.check_line_numbers.toggled.connect(
            lambda c: setattr(self.prefs, "show_line_numbers", c))
        display_layout.addWidget(self.check_line_numbers)

        self.check_syntax = QCheckBox(mnemonic(_("Use s_yntax highlighting")))
        self.check_syntax.setChecked(bool(self.prefs.use_syntax_highlighting))
        self.check_syntax.toggled.connect(
            lambda c: setattr(self.prefs, "use_syntax_highlighting", c))
        display_layout.addWidget(self.check_syntax)
        layout.addWidget(display_group)

        editor_group = QGroupBox(_("External editor"))
        editor_layout = QVBoxLayout(editor_group)
        self.check_system_editor = QCheckBox(mnemonic(_("Use _default system editor")))
        use_default = self.prefs.edit_command_type == "internal"
        self.check_system_editor.setChecked(use_default)
        self.check_system_editor.toggled.connect(self._on_system_editor_toggled)
        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel(mnemonic(_("Edito_r command:"))))
        self.entry_editor = QLineEdit(" ".join(self.prefs.get_custom_editor_command([])))
        self.entry_editor.setEnabled(not use_default)
        self.entry_editor.editingFinished.connect(
            lambda: setattr(self.prefs, "edit_command_custom", self.entry_editor.text()))
        cmd_row.addWidget(self.entry_editor, 1)
        editor_layout.addWidget(self.check_system_editor)
        editor_layout.addLayout(cmd_row)
        layout.addWidget(editor_group)
        layout.addStretch(1)
        return widget

    def _refresh_font_button(self):
        font = QFont()
        font.fromString(self.prefs.custom_font)
        self.button_font.setText(f"{font.family()} {font.pointSize()}")

    def _on_default_font_toggled(self, checked):
        use_custom = not checked
        self.button_font.setEnabled(use_custom)
        self.prefs.use_custom_font = use_custom

    def _on_pick_font(self):
        current = QFont()
        current.fromString(self.prefs.custom_font)
        font, ok = QFontDialog.getFont(current, self)
        if ok:
            self.prefs.custom_font = font.toString()
            self._refresh_font_button()

    def _on_wrap_toggled(self, checked):
        if not checked:
            self.prefs.edit_wrap_lines = 0
            self.check_split.setEnabled(False)
        else:
            self.check_split.setEnabled(True)
            self.prefs.edit_wrap_lines = 2 if self.check_split.isChecked() else 1

    def _on_split_toggled(self, checked):
        if self.check_wrap.isChecked():
            self.prefs.edit_wrap_lines = 2 if checked else 1

    def _on_system_editor_toggled(self, checked):
        self.entry_editor.setEnabled(not checked)
        self.prefs.edit_command_type = "internal" if checked else "custom"

    # ----- display tab ------------------------------------------------------

    def _build_display_tab(self):
        widget = QWidget()
        form = QFormLayout(widget)
        self.color_buttons = {}
        for key, label in COLOR_KEYS:
            button = self._make_color_button(key)
            self.color_buttons[key] = button
            form.addRow(_(label), button)
        return widget

    def _make_color_button(self, key):
        button = QPushButton()

        def refresh():
            color = QColor(getattr(self.prefs, key))
            if not color.isValid():
                color = QColor("#000000")
            button.setText(color.name())
            button.setStyleSheet(f"background-color: {color.name()};")

        def pick():
            color = QColorDialog.getColor(QColor(getattr(self.prefs, key)), self)
            if color.isValid():
                setattr(self.prefs, key, color.name())
                refresh()

        button.clicked.connect(pick)
        refresh()
        return button

    # ----- filter tabs ------------------------------------------------------

    def _build_file_filters_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(_(
            "When performing directory comparisons, you may filter out files "
            "and directories by name. Each pattern is a list of shell style "
            "wildcards separated by spaces."))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.file_filters = FilterList(self.prefs, "filters", _("Pattern"))
        layout.addWidget(self.file_filters, 1)
        self.check_ignore_symlinks = QCheckBox(_("Ignore symbolic links"))
        self.check_ignore_symlinks.setChecked(bool(self.prefs.ignore_symlinks))
        self.check_ignore_symlinks.toggled.connect(
            lambda c: setattr(self.prefs, "ignore_symlinks", c))
        layout.addWidget(self.check_ignore_symlinks)
        return widget

    def _build_text_filters_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(_(
            "When performing file comparisons, you may ignore certain types of "
            "changes. Each pattern here is a python regular expression which "
            "replaces matching text with the empty string before comparison is "
            "performed. If the expression contains groups, only the groups are "
            "replaced. See the user manual for more details."))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.text_filters = FilterList(self.prefs, "regexes", _("Regex"))
        layout.addWidget(self.text_filters, 1)
        self.check_ignore_blank = QCheckBox(
            _("Ignore changes which insert or delete blank lines"))
        self.check_ignore_blank.setChecked(bool(self.prefs.ignore_blank_lines))
        self.check_ignore_blank.toggled.connect(
            lambda c: setattr(self.prefs, "ignore_blank_lines", c))
        layout.addWidget(self.check_ignore_blank)
        return widget

    def _build_encoding_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(
            _("When loading, try these codecs in order. (e.g. utf8, iso8859)")))
        self.entry_codecs = QLineEdit(self.prefs.text_codecs)
        self.entry_codecs.editingFinished.connect(
            lambda: setattr(self.prefs, "text_codecs", self.entry_codecs.text()))
        layout.addWidget(self.entry_codecs)
        layout.addStretch(1)
        return widget
