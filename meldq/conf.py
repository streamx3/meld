"""gettext init (exposes _, ngettext) and resource paths for meldq.

Importing PyQt6 in this module is forbidden: the engine and tests must be
able to import ``_`` headlessly.
"""

import gettext as _gettext_module
from importlib import resources
from pathlib import Path

APPLICATION_NAME = "Meld"
GETTEXT_DOMAIN = "meld"          # MUST stay "meld": the 34 po/ catalogs use this domain
HELP_URL = "https://meldmerge.org/help/"
BUG_REPORT_URL = "http://bugzilla.gnome.org/buglist.cgi?query=product%3Ameld"  # verbatim from meldapp.py:442

_translation = _gettext_module.NullTranslations()


def _(message):
    return _translation.gettext(message)


def ngettext(singular, plural, n):
    return _translation.ngettext(singular, plural, n)


def mnemonic(label):
    """Convert a GTK '_x' mnemonic label (the msgid form) to Qt '&x'."""
    # escape literal '&' first, then replace only the FIRST '_'
    return label.replace("&", "&&").replace("_", "&", 1)


def package_dir():
    return Path(resources.files("meldq"))


def ui_file(name):
    return package_dir() / "ui" / name


def icon_path(name):
    return package_dir() / "resources" / "icons" / name


def running_from_source():
    return (package_dir().parent / "pyproject.toml").exists()


def locale_dir():
    packaged = package_dir() / "resources" / "locale"
    if packaged.exists():
        return packaged
    if running_from_source():
        return package_dir().parent / "build" / "locale"
    return packaged


def init_i18n(localedir=None):
    """Load the gettext catalogs (domain "meld") from `localedir`, defaulting
    to the packaged/built locale dir. Language selection follows the standard
    env vars (LANGUAGE, LC_ALL, LANG); missing catalogs fall back to English.
    Compile catalogs with packaging/compile_translations.py."""
    global _translation
    _translation = _gettext_module.translation(
        GETTEXT_DOMAIN, localedir=str(localedir or locale_dir()),
        fallback=True)
