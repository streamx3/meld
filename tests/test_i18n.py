"""i18n wiring: compiled catalogs load and translate the shared msgids."""

import shutil
import subprocess

import pytest

from meldq import conf

pytestmark = pytest.mark.skipif(
    shutil.which("msgfmt") is None, reason="gettext (msgfmt) not installed")


@pytest.fixture
def uk_locale(tmp_path):
    dest = tmp_path / "uk" / "LC_MESSAGES"
    dest.mkdir(parents=True)
    subprocess.run(["msgfmt", "--output-file", str(dest / "meld.mo"),
                    "po/uk.po"], check=True, capture_output=True)
    return tmp_path


def test_catalog_translates_shared_msgids(uk_locale, monkeypatch):
    monkeypatch.setenv("LANGUAGE", "uk")
    try:
        conf.init_i18n(localedir=uk_locale)
        # "_Save" is a msgid both the fresh shell and the upstream catalogs
        # share; it must come back translated (not the English fallback).
        assert conf._("_Save") != "_Save"
        # A fresh-only string falls back to English untranslated.
        assert conf._("Zoom _In") == "Zoom _In"
    finally:
        conf._translation = __import__("gettext").NullTranslations()


def test_missing_localedir_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGUAGE", "uk")
    try:
        conf.init_i18n(localedir=tmp_path / "nope")
        assert conf._("_Save") == "_Save"           # English fallback, no crash
    finally:
        conf._translation = __import__("gettext").NullTranslations()
