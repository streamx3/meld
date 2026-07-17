"""C1: FileDiffView.save() is encode-first and atomic.

An un-encodable character must NOT destroy the file (the old code opened "wb",
truncating to 0 bytes, before evaluating text.encode()). The write also goes
through a temp file + os.replace so a crash mid-write can't truncate the target.
"""

import os

import pytest

from meldq.views.filediff import FileDiffView


@pytest.fixture
def fd(qapp, qtbot):
    view = FileDiffView(2)
    qtbot.addWidget(view)
    return view


def test_unencodable_char_leaves_file_intact(fd, tmp_path):
    src = tmp_path / "latin.txt"
    src.write_bytes("caf\xe9\n".encode("latin-1"))    # 5 bytes, latin-1
    fd.set_files([str(src), str(src)])
    assert fd._encoding[0] == "latin-1"

    # A euro sign is not representable in latin-1.
    fd.panes[0].set_text(fd.panes[0].text() + "price €100\n")
    with pytest.raises(UnicodeEncodeError):
        fd.save(0)

    # The original file must be byte-for-byte intact (not truncated to 0).
    assert src.read_bytes() == "caf\xe9\n".encode("latin-1")


def test_save_roundtrips_encoding_and_eol(fd, tmp_path):
    src = tmp_path / "crlf.txt"
    src.write_bytes(b"caf\xe9\r\n")                    # latin-1 + CRLF
    fd.set_files([str(src), str(src)])
    fd.panes[0].set_text("caf\xe9\r\nline2")
    fd.save(0)
    assert src.read_bytes() == b"caf\xe9\r\nline2".replace(b"\r\n", b"\r\n")
    assert not fd.is_modified(0)


def test_save_preserves_file_mode(fd, tmp_path):
    src = tmp_path / "exec.txt"
    src.write_bytes(b"one\ntwo\n")
    os.chmod(src, 0o750)
    fd.set_files([str(src), str(src)])
    fd.panes[0].set_text("one\ntwoX\n")
    fd.save(0)
    assert oct(os.stat(src).st_mode & 0o777) == oct(0o750)


def test_save_leaves_no_temp_files(fd, tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"one\n")
    fd.set_files([str(src), str(src)])
    fd.panes[0].set_text("one\ntwo\n")
    fd.save(0)
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.name.startswith(".meldq-save-")]
    assert leftovers == []
    assert src.read_bytes() == b"one\ntwo\n"


def test_bom_preserved_on_save(fd, tmp_path):
    # M7: a UTF-8 BOM must survive an edit+save (was silently dropped).
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbfhello\nworld\n")
    fd.set_files([str(p), str(p)])
    assert fd._encoding[0] == "utf-8-sig"
    assert not fd.panes[0].text().startswith("﻿")   # BOM not in the buffer
    fd.panes[0].set_text(fd.panes[0].text() + "x\n")
    fd.save(0)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")     # BOM restored


def test_plain_utf8_does_not_gain_a_bom(fd, tmp_path):
    p = tmp_path / "plain.txt"
    p.write_bytes(b"hello\nworld\n")
    fd.set_files([str(p), str(p)])
    assert fd._encoding[0] == "utf-8"
    fd.panes[0].set_text("HELLO\n")
    fd.save(0)
    assert p.read_bytes() == b"HELLO\n"                   # no BOM added
