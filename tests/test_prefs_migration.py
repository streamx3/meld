import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QFont

from meldq.util.prefs import (
    Preferences,
    pango_font_to_qfont_string,
    x11_color_to_hex,
)

# literal tabs and literal backslashes, as the 1.4 backend wrote them
INI = (
    "[DEFAULT]\n"
    "window_size_x = 1000\n"
    "use_custom_font = True\n"
    "custom_font = Monospace 12\n"
    "color_delete_bg = DarkSeaGreen1\n"
    "color_edited_bg = gray90\n"
    "edit_command_type = gnome\n"
    "tab_size = 8\n"
    "regexes = CVS keywords\t0\t\\$\\w+(:[^\\n$]+)?\\$\n"
)


@pytest.fixture
def make_prefs(tmp_path):
    def _make():
        settings = QSettings(str(tmp_path / "cfg.ini"), QSettings.Format.IniFormat)
        return Preferences(settings), settings
    return _make


def write_ini(tmp_path):
    ini = tmp_path / "meldrc.ini"
    ini.write_text(INI, encoding="utf-8")
    return ini


def test_migration_converts_values(tmp_path):
    ini = write_ini(tmp_path)
    settings = QSettings(str(tmp_path / "cfg.ini"), QSettings.Format.IniFormat)
    from meldq.util.prefs import migrate_legacy_prefs
    migrate_legacy_prefs(settings, ini)
    p = Preferences(settings)
    assert p.window_size_x == 1000 and isinstance(p.window_size_x, int)
    assert p.use_custom_font is True
    f = QFont()
    f.fromString(p.custom_font)
    assert f.family() == "Monospace"
    assert f.pointSize() == 12
    assert p.color_delete_bg == "#c1ffc1"
    assert p.color_edited_bg == "#e5e5e5"
    assert p.edit_command_type == "internal"
    assert p.tab_size == 8
    # RawConfigParser preserved the % / $ / backslashes verbatim
    assert p.regexes == "CVS keywords\t0\t\\$\\w+(:[^\\n$]+)?\\$"


def test_migration_is_idempotent(tmp_path):
    ini = write_ini(tmp_path)
    settings = QSettings(str(tmp_path / "cfg.ini"), QSettings.Format.IniFormat)
    from meldq.util.prefs import migrate_legacy_prefs
    assert migrate_legacy_prefs(settings, ini) is True
    ini.unlink()
    # second run must not lose migrated values and must not re-run
    assert migrate_legacy_prefs(settings, ini) is False
    p = Preferences(settings)
    assert p.tab_size == 8


def test_no_ini_sets_flag(tmp_path):
    settings = QSettings(str(tmp_path / "cfg.ini"), QSettings.Format.IniFormat)
    from meldq.util.prefs import migrate_legacy_prefs
    assert migrate_legacy_prefs(settings, tmp_path / "absent.ini") is False
    assert settings.value("migration/meldrc_done")
    p = Preferences(settings)
    assert p.tab_size == 4          # defaults intact


def test_x11_color_to_hex():
    assert x11_color_to_hex("grey42") == "#6b6b6b"
    assert x11_color_to_hex("gray90") == "#e5e5e5"
    assert x11_color_to_hex("Pink") == "#ffc0cb"
    assert x11_color_to_hex("totaljunkcolor") is None


def test_pango_font_conversion():
    s = pango_font_to_qfont_string("Monospace 12")
    f = QFont()
    f.fromString(s)
    assert f.family() == "Monospace" and f.pointSize() == 12
    bold = pango_font_to_qfont_string("DejaVu Sans Mono Bold 10")
    fb = QFont()
    fb.fromString(bold)
    assert fb.family() == "DejaVu Sans Mono" and fb.bold()
