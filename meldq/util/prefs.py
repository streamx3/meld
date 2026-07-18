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

import configparser
import os
import pathlib
import re
import sys

from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontInfo

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
    # Theming: "system" follows the OS appearance (and live changes), "light"
    # or "dark" force a mode. No user colour pickers (per BUILD_PLAN_3.24).
    "theme": Value(STRING, "system"),
    # Default DirDiff name-filter globs (space-separated, e.g. "*.pyc build"),
    # pre-loaded into every new folder comparison's filter bar.
    "dirdiff_name_filters": Value(STRING, ""),
}


# ---------------------------------------------------------------------------
# One-time migration from the 1.4 ~/.meld/meldrc.ini
# ---------------------------------------------------------------------------

# At least the 1.4 default palette plus common X11 tint names. Values are
# lowercase name -> "#rrggbb"; grayN/greyN are handled programmatically.
X11_COLORS = {
    "darkseagreen1": "#c1ffc1", "darkseagreen2": "#b4eeb4",
    "darkseagreen3": "#9bcd9b", "darkseagreen4": "#698b69",
    "lightsteelblue1": "#cae1ff", "lightsteelblue2": "#bcd2ee",
    "lightsteelblue3": "#a2b5cd", "lightsteelblue4": "#6e7b8b",
    "lightsteelblue": "#b0c4de",
    "seagreen1": "#54ff9f", "seagreen2": "#4eee94", "seagreen3": "#43cd80",
    "steelblue1": "#63b8ff", "steelblue2": "#5cacee",
    "lightblue1": "#bfefff", "lightyellow1": "#ffffe0",
    "mistyrose1": "#ffe4e1", "azure1": "#f0ffff", "honeydew1": "#f0fff0",
    "pink": "#ffc0cb", "lightpink": "#ffb6c1",
    "red": "#ff0000", "black": "#000000", "white": "#ffffff",
    "lavender": "#e6e6fa", "ivory": "#fffff0", "beige": "#f5f5dc",
    "khaki": "#f0e68c", "salmon": "#fa8072", "gold": "#ffd700",
    "orange": "#ffa500", "green": "#008000", "blue": "#0000ff",
    "yellow": "#ffff00",
}


def legacy_ini_path():
    if sys.platform == "win32":
        base = pathlib.Path(os.getenv("APPDATA", "")) / "Meld"
    else:
        base = pathlib.Path(os.path.expanduser("~")) / ".meld"
    return base / "meldrc.ini"


def x11_color_to_hex(name):
    key = name.strip().lower().replace(" ", "")
    m = re.fullmatch(r"gr[ae]y(\d{1,3})", key)
    if m:
        # truncate (matches real X11 and the converted defaults): gray90 -> #e5e5e5
        v = int(min(int(m.group(1)), 100) * 255 / 100)
        return "#%02x%02x%02x" % (v, v, v)
    if key in X11_COLORS:
        return X11_COLORS[key]
    c = QColor(name)
    if c.isValid():
        return c.name()
    return None


def pango_font_to_qfont_string(pango):
    tokens = pango.replace(",", " ").split()
    size = 10
    if tokens and tokens[-1].lstrip("-").isdigit():
        size = int(tokens.pop())
    bold = italic = False
    while tokens and tokens[-1].lower() in ("bold", "italic", "oblique"):
        word = tokens.pop().lower()
        if word == "bold":
            bold = True
        else:
            italic = True
    family = " ".join(tokens) if tokens else "monospace"
    f = QFont(family, size)
    f.setBold(bold)
    f.setItalic(italic)
    return f.toString()


def migrate_legacy_prefs(settings, ini_path=None):
    """Copy 1.4 meldrc.ini values into QSettings once. Returns True if run."""
    if settings.value("migration/meldrc_done"):
        return False
    if ini_path is None:
        ini_path = legacy_ini_path()
    if not ini_path.exists():
        settings.setValue("migration/meldrc_done", True)
        return False
    # RawConfigParser: stored regex/filter values contain % and $ that
    # interpolation would choke on; the 1.4 backend wrote everything into
    # [DEFAULT] (util/prefs.py:193,206).
    parser = configparser.RawConfigParser()
    parser.read(ini_path, encoding="utf-8")
    for key, raw in parser.defaults().items():
        if key not in DEFAULTS:
            continue
        try:
            coerced = _coerce(raw, DEFAULTS[key].type)
        except (ValueError, TypeError):
            continue
        if key.startswith("color_"):
            if not (isinstance(coerced, str) and coerced.startswith("#")):
                hexval = x11_color_to_hex(coerced)
                if hexval is None:
                    continue          # unknown name -> fall back to new default
                coerced = hexval
        elif key == "custom_font":
            coerced = pango_font_to_qfont_string(coerced)
        elif key == "edit_command_type" and coerced == "gnome":
            coerced = "internal"
        elif key in ("window_size_x", "window_size_y"):
            coerced = max(int(coerced), 100)
        settings.setValue(f"prefs/{key}", coerced)
    settings.setValue("migration/meldrc_done", True)
    settings.sync()
    return True


class Preferences(QObject):
    changed = pyqtSignal(str)      # pref name; receivers read the new value off the object

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.__dict__["_values"] = {
            name: Value(v.type, v.default) for name, v in DEFAULTS.items()}
        self.__dict__["_settings"] = settings if settings is not None else make_settings()
        migrate_legacy_prefs(self._settings)
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
            # "monospace" is a real family on Linux/fontconfig but not on macOS
            # (it resolves to the proportional system UI font). Force a
            # fixed-pitch fallback so a migrated meldrc font stays monospaced.
            if not QFontInfo(f).fixedPitch():
                fixed = QFontDatabase.systemFont(
                    QFontDatabase.SystemFont.FixedFont)
                f.setFamily(fixed.family())
            return f
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

    def get_custom_editor_command(self, files):
        return self.edit_command_custom.split() + files
