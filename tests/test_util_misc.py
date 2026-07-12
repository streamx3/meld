import subprocess
import sys

from meldq.util.misc import (
    char_to_utf16_offset,
    gtk_mnemonic_to_qt,
    utf16_to_char_offset,
)


def test_mnemonic_conversion():
    assert gtk_mnemonic_to_qt("_Match Case") == "&Match Case"
    assert gtk_mnemonic_to_qt("Who_le word") == "Who&le word"
    assert gtk_mnemonic_to_qt("A & B_x") == "A && B&x"


def test_utf16_offsets_roundtrip():
    text = "ab\U0001F600cd"          # emoji is one codepoint, two UTF-16 units
    assert char_to_utf16_offset(text, 3) == 4
    assert utf16_to_char_offset(text, 4) == 3
    for char_off in range(len(text) + 1):
        u16 = char_to_utf16_offset(text, char_off)
        assert utf16_to_char_offset(text, u16) == char_off


def test_utf16_no_astral_is_identity():
    text = "hello world"
    for off in range(len(text) + 1):
        assert char_to_utf16_offset(text, off) == off
        assert utf16_to_char_offset(text, off) == off


def test_misc_imports_no_qt():
    code = ("import sys, meldq.util.misc; "
            "sys.exit(1 if any(m.split('.')[0]=='PyQt6' for m in sys.modules) else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
