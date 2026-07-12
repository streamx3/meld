import subprocess
import sys

from meldq import conf


def test_conf_is_qt_free():
    code = "import meldq.conf, sys; sys.exit(1 if 'PyQt6' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_mnemonic():
    assert conf.mnemonic("_File") == "&File"
    assert conf.mnemonic("Find Ne_xt") == "Find Ne&xt"
    assert conf.mnemonic("A & B_x") == "A && B&x"


def test_gettext_before_and_after_init():
    assert conf._("anything") == "anything"          # NullTranslations
    conf.init_i18n()                                  # fallback=True, no catalogs present
    assert conf._("anything") == "anything"


def test_resource_paths():
    ui = conf.ui_file("newcomparison.ui")
    assert ui.parent.name == "ui"
    assert "meldq" in str(ui)
    icon = conf.icon_path("icon.png")
    assert icon.exists()
    assert icon.parent.name == "icons"


def test_running_from_source_true_in_repo():
    # this test tree lives next to pyproject.toml
    assert conf.running_from_source() is True
