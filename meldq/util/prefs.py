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

"""QSettings-backed application preferences.

The ``changed(str)`` signal carries only the pref *name*; receivers must
re-read the new value from the Preferences object (the 1.4 notify_add
delivered (attr, val), the contract narrows it to the name).
"""

from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtGui import QFont, QFontDatabase

from meldq.conf import _

# types of values allowed (util/prefs.py:56-59)
BOOL = "bool"
INT = "int"
STRING = "string"
FLOAT = "float"


class Value:
    """Represents a settable preference."""

    __slots__ = ("type", "default", "current")

    def __init__(self, t, d):
        self.type = t
        self.default = d
        self.current = d


def make_settings():
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                     "meldq", "meldq")


def _coerce(raw, type_tag):
    if type_tag == BOOL:
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("true", "1"):
            return True
        if s in ("false", "0"):
            return False
        raise ValueError(raw)
    if type_tag == INT:
        return int(raw)
    if type_tag == FLOAT:
        return float(raw)
    return str(raw)


def _vc_filter_pattern():
    try:
        from meldq.vc import get_plugins_metadata
        from meldq.util.misc import shell_escape
        return shell_escape(" ".join(get_plugins_metadata()))
    except ImportError:
        # the descoped-plugin set; brace-escaping only mattered for tla {arch}
        return "CVS .svn .hg .bzr .git"


# The escape sequences in the regexes/filters defaults are doubled at the
# SOURCE level so py3 emits no SyntaxWarning, while the runtime string value
# stays byte-identical to 1.4 (so the 34 po/ catalogs keep matching these
# msgids). e.g. source "\\$" -> value backslash-dollar, as py2's "\$" was.
DEFAULTS = {
    "window_size_x": Value(INT, 600),
    "window_size_y": Value(INT, 600),
    "use_custom_font": Value(BOOL, 0),
    "custom_font": Value(STRING, "monospace,14"),
    "tab_size": Value(INT, 4),
    "spaces_instead_of_tabs": Value(BOOL, False),
    "show_line_numbers": Value(BOOL, 0),
    "use_syntax_highlighting": Value(BOOL, 0),
    "edit_wrap_lines": Value(INT, 0),
    "edit_command_type": Value(STRING, "internal"),   # internal, custom
    "edit_command_custom": Value(STRING, "gedit"),
    "text_codecs": Value(STRING, "utf8 latin1"),
    "ignore_symlinks": Value(BOOL, 0),
    "vc_console_visible": Value(BOOL, 0),
    "color_delete_bg": Value(STRING, "#c1ffc1"),
    "color_delete_fg": Value(STRING, "#ff0000"),
    "color_replace_bg": Value(STRING, "#ddeeff"),
    "color_replace_fg": Value(STRING, "#000000"),
    "color_conflict_bg": Value(STRING, "#ffc0cb"),
    "color_conflict_fg": Value(STRING, "#000000"),
    "color_inline_bg": Value(STRING, "#bcd2ee"),
    "color_inline_fg": Value(STRING, "#ff0000"),
    "color_edited_bg": Value(STRING, "#e5e5e5"),
    "color_edited_fg": Value(STRING, "#000000"),
    "filters": Value(STRING,
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("Backups\t1\t#*# .#* ~* *~ *.{orig,bak,swp}\n") +
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("Version Control\t1\t%s\n") % _vc_filter_pattern() +
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("Binaries\t1\t*.{pyc,a,obj,o,so,la,lib,dll}\n") +
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("Media\t0\t*.{jpg,gif,png,wav,mp3,ogg,xcf,xpm}")),
    "regexes": Value(STRING,
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("CVS keywords\t0\t\\$\\w+(:[^\\n$]+)?\\$\n") +
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("C++ comment\t0\t//.*\n") +
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("C comment\t0\t/\\*.*?\\*/\n") +
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("All whitespace\t0\t[ \\t\\r\\f\\v]*\n") +
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("Leading whitespace\t0\t^[ \\t\\r\\f\\v]*\n") +
        #TRANSLATORS: translate this string ONLY to the first "\t", leave it and the following parts intact
        _("Script comment\t0\t#.*")),
    "ignore_blank_lines": Value(BOOL, False),
    "toolbar_visible": Value(BOOL, True),
    "statusbar_visible": Value(BOOL, True),
}


class Preferences(QObject):
    changed = pyqtSignal(str)      # pref name; receivers read the new value off the object

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.__dict__["_values"] = {
            name: Value(v.type, v.default) for name, v in DEFAULTS.items()}
        self.__dict__["_settings"] = settings if settings is not None else make_settings()
        for name, value in self._values.items():
            key = f"prefs/{name}"
            if self._settings.contains(key):
                try:
                    value.current = _coerce(self._settings.value(key), value.type)
                except (ValueError, TypeError):
                    value.current = value.default

    def __getattr__(self, name):
        values = self.__dict__.get("_values")
        if values is not None and name in values:
            return values[name].current
        raise AttributeError(name)

    def __setattr__(self, name, value):
        values = self.__dict__.get("_values")
        if values is not None and name in values:
            v = values[name]
            if v.current != value:
                v.current = value
                self._settings.setValue(f"prefs/{name}", value)
                self.changed.emit(name)
        else:
            super().__setattr__(name, value)

    def get_default(self, name):
        return self._values[name].default

    def get_current_font(self):
        if self.use_custom_font:
            f = QFont()
            f.fromString(self.custom_font)
            return f
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

    def get_custom_editor_command(self, files):
        return self.edit_command_custom.split() + files
