import subprocess
import sys

import pytest
from PyQt6.QtCore import QSettings

from meldq.util.prefs import Preferences


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)


def test_defaults_readable(settings):
    p = Preferences(settings)
    assert p.tab_size == 4
    assert p.get_default("tab_size") == 4
    assert p.text_codecs == "utf8 latin1"
    assert p.toolbar_visible is True


def test_set_persists_typed(settings, tmp_path):
    p = Preferences(settings)
    p.tab_size = 8
    settings.sync()
    p2 = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    assert p2.tab_size == 8
    assert isinstance(p2.tab_size, int)


def test_changed_signal(qtbot, settings):
    p = Preferences(settings)
    with qtbot.waitSignal(p.changed) as blocker:
        p.tab_size = 8
    assert blocker.args == ["tab_size"]


def test_equal_value_emits_nothing(settings):
    p = Preferences(settings)
    hits = []
    p.changed.connect(hits.append)
    p.tab_size = p.tab_size          # no change
    assert hits == []


def test_bool_roundtrip_through_ini(settings, tmp_path):
    p = Preferences(settings)
    p.show_line_numbers = True
    settings.sync()
    # legacy capitalized bool string also coerces
    settings.setValue("prefs/spaces_instead_of_tabs", "True")
    settings.sync()
    p2 = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    assert p2.show_line_numbers is True
    assert p2.spaces_instead_of_tabs is True


def test_unknown_key_raises(settings):
    p = Preferences(settings)
    with pytest.raises(AttributeError):
        _ = p.nonexistent_key
    # plain instance attributes still work
    assert p._settings is settings


def test_escape_regression_msgid_preserved(settings):
    p = Preferences(settings)
    regex_first = p.regexes.split("\n")[0] + "\n"
    assert regex_first == "CVS keywords\t0\t\\$\\w+(:[^\\n$]+)?\\$\n"
    assert "/\\*.*?\\*/" in p.regexes         # C comment line, literal backslash-star


def test_no_syntaxwarning_on_import():
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", "import meldq.util.prefs"])
    assert result.returncode == 0


def test_custom_font_falls_back_to_fixed_family(qapp, settings):
    # X4: a migrated "monospace" family is proportional on macOS; get_current_font
    # must fall back to the system fixed-pitch family.
    from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo
    probe = QFont()
    probe.fromString("monospace,13")
    p = Preferences(settings)
    p.use_custom_font = True
    p.custom_font = "monospace,13"
    f = p.get_current_font()
    if not QFontInfo(probe).fixedPitch():
        # "monospace" resolved proportional -> we forced the fixed family
        assert f.family() == QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont).family()
    else:
        assert f.family()               # platform has a real monospace family
