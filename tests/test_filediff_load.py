from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from meldq.filediff import FileDiff
from meldq.util.prefs import Preferences

FIX = Path(__file__).parent / "fixtures" / "encodings"


def make_prefs(tmp_path, codecs="utf_8 utf_16"):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    prefs.text_codecs = codecs
    return prefs


def load(doc, files):
    """Drive _load_files to completion; returns panetext list."""
    panetext = ["\n"] * len(files)
    doc.set_num_panes(len(files))
    for _step in doc._load_files(files, doc.textbuffer, panetext):
        pass
    return panetext


@pytest.fixture
def two_pane(qapp, tmp_path):
    def _make(codecs="utf_8 utf_16"):
        return FileDiff(make_prefs(tmp_path, codecs), 2)
    return _make


def test_utf8_loads(two_pane):
    doc = two_pane()
    load(doc, [str(FIX / "utf8.txt"), None])
    assert doc.textbuffer[0].toPlainText().startswith("héllo wörld")
    assert doc.bufferdata[0].encoding == "utf_8"


def test_latin1_falls_through_cascade(two_pane):
    doc = two_pane("utf_8 iso8859_1")
    load(doc, [str(FIX / "latin1.txt"), None])
    assert "café résumé" in doc.textbuffer[0].toPlainText()
    assert doc.bufferdata[0].encoding == "iso8859_1"


def test_utf16_loads_under_default(two_pane):
    doc = two_pane("utf_8 utf_16")
    load(doc, [str(FIX / "utf16.txt"), None])
    assert "hello utf16" in doc.textbuffer[0].toPlainText()


def test_binary_file_shows_msgarea(two_pane):
    doc = two_pane()
    load(doc, [str(FIX / "binary.bin"), None])
    assert doc.textbuffer[0].toPlainText() == ""
    assert doc.msgarea_mgr[0].has_message()


def test_crlf_newlines(two_pane):
    doc = two_pane()
    load(doc, [str(FIX / "crlf.txt"), None])
    assert doc.bufferdata[0].newlines == "\r\n"
    assert "\r" not in doc.textbuffer[0].toPlainText()


def test_mixed_newlines(two_pane):
    doc = two_pane()
    load(doc, [str(FIX / "mixed_newlines.txt"), None])
    assert doc.bufferdata[0].newlines == ("\n", "\r\n")


def test_crlf_split_across_boundary(two_pane, tmp_path):
    # the '\r' of a CRLF is the last byte of the first 4096-read and the '\n'
    # begins the next — must not become a phantom blank line
    payload = b"a" * 4095 + b"\r\n" + b"tail\r\n"
    boundary = tmp_path / "boundary_crlf.txt"
    boundary.write_bytes(payload)
    doc = two_pane()
    load(doc, [str(boundary), None])
    text = doc.textbuffer[0].toPlainText()
    assert text == "a" * 4095 + "\ntail\n"    # no blank line inserted
    assert doc.bufferdata[0].newlines == "\r\n"


def test_utf8_char_split_across_boundary(two_pane, tmp_path):
    # a 3-byte char (€ = e2 82 ac) straddling the 4096 read boundary
    prefix = "a" * 4094
    payload = (prefix + "€" + "b\n").encode("utf-8")
    assert payload[4094:4095] == b"\xe2"       # first byte of € is at 4094
    f = tmp_path / "split_char.txt"
    f.write_bytes(payload)
    doc = two_pane("utf_8 utf_16")
    load(doc, [str(f), None])
    assert doc.textbuffer[0].toPlainText() == prefix + "€b\n"


def test_checkpoint_after_load(two_pane):
    doc = two_pane()
    load(doc, [str(FIX / "utf8.txt"), None])
    # after load the document is at its checkpoint (unmodified)
    assert doc.undosequence.is_at_checkpoint(doc.textbuffer[0])
