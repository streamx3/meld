"""M5: patch import — apply an external .patch, review as a FileDiff."""

import difflib

import pytest

from meldq.patch import PatchError
from meldq.patchimport import open_in_filediffs, patch_targets, read_patch_text
from meldq.widgets.sciview import KIND_INSERT, KIND_REPLACE


def make_patch(a, b, path="f.txt"):
    raw = difflib.unified_diff(a.splitlines(keepends=True),
                               b.splitlines(keepends=True),
                               fromfile="a/" + path, tofile="b/" + path)
    out = []
    for ln in raw:
        if ln[:1] in (" ", "-", "+") and not ln.endswith("\n"):
            out.append(ln + "\n\\ No newline at end of file\n")
        else:
            out.append(ln)
    return "".join(out)


def test_patch_targets_modifies_existing(tmp_path):
    (tmp_path / "f.txt").write_text("one\ntwo\n")
    patch = make_patch("one\ntwo\n", "one\nTWO\n")
    targets = patch_targets(str(tmp_path), patch)
    assert len(targets) == 1
    target = targets[0]
    assert target.path.endswith("f.txt")
    assert target.original == "one\ntwo\n"
    assert target.patched == "one\nTWO\n"


def test_patch_targets_new_file(tmp_path):
    # patch adds a file that isn't on disk -> original "", patched = additions
    patch = make_patch("", "hello\nworld\n", path="new.txt")
    target, = patch_targets(str(tmp_path), patch)
    assert target.path.endswith("new.txt")
    assert target.original == ""
    assert target.patched == "hello\nworld\n"


def test_patch_targets_multi_file(tmp_path):
    (tmp_path / "a.txt").write_text("a1\n")
    (tmp_path / "b.txt").write_text("b1\n")
    patch = (make_patch("a1\n", "a2\n", "a.txt")
             + make_patch("b1\n", "b2\n", "b.txt"))
    targets = {t[0].split("/")[-1]: t for t in patch_targets(str(tmp_path), patch)}
    assert targets["a.txt"][2] == "a2\n"
    assert targets["b.txt"][2] == "b2\n"


def test_patch_targets_context_mismatch_raises(tmp_path):
    (tmp_path / "f.txt").write_text("totally\ndifferent\n")
    patch = make_patch("one\ntwo\nthree\n", "one\nTWO\nthree\n")
    with pytest.raises(PatchError):
        patch_targets(str(tmp_path), patch)


def test_open_in_filediffs_shows_change(qapp, qtbot, tmp_path):
    (tmp_path / "f.txt").write_text("one\ntwo\nthree\n")
    patch = make_patch("one\ntwo\nthree\n", "one\nCHANGED\nthree\n")
    views = open_in_filediffs(str(tmp_path), patch)
    assert len(views) == 1
    fd = views[0]
    qtbot.addWidget(fd)
    assert fd.panes[0].text() == "one\ntwo\nthree\n"      # source
    assert fd.panes[1].text() == "one\nCHANGED\nthree\n"  # patched
    assert KIND_REPLACE in fd.panes[0].chunk_kinds_at(1)  # reviewable as a diff


def test_open_in_filediffs_new_file(qapp, qtbot, tmp_path):
    patch = make_patch("", "added\n", path="new.txt")
    fd = open_in_filediffs(str(tmp_path), patch)[0]
    qtbot.addWidget(fd)
    assert fd.panes[0].text() == ""
    assert fd.panes[1].text() == "added\n"
    assert KIND_INSERT in fd.panes[1].chunk_kinds_at(0)


# ----- export + round-trip --------------------------------------------------

def test_make_patch_export(qapp, qtbot):
    from meldq.views.filediff import FileDiffView
    fd = FileDiffView(2)
    qtbot.addWidget(fd)
    fd.set_texts(["one\ntwo\nthree\n", "one\nTWO\nthree\n"], ["f.txt", "f.txt"])
    patch = fd.make_patch()
    assert "@@" in patch and "-two" in patch and "+TWO" in patch


def test_export_then_import_roundtrip(qapp, qtbot, tmp_path):
    from meldq.views.filediff import FileDiffView
    src = "alpha\nbeta\ngamma\n"
    tgt = "alpha\nBETA\ngamma\ndelta\n"
    (tmp_path / "f.txt").write_text(src)
    # export a patch from a source-vs-target comparison...
    fd = FileDiffView(2)
    qtbot.addWidget(fd)
    fd.set_texts([src, tgt], [str(tmp_path / "f.txt"), str(tmp_path / "f.txt")])
    patch = fd.make_patch()
    # ...then importing it against the source reproduces the target.
    target, = patch_targets(str(tmp_path), patch)
    assert target.original == src
    assert target.patched == tgt


def test_export_marks_missing_final_newline(qapp, qtbot, tmp_path):
    # A file whose last line lacks a trailing newline must round-trip: the
    # exported patch carries the "\ No newline at end of file" marker and the
    # importer reproduces the exact target.
    from meldq.views.filediff import FileDiffView
    src, tgt = "a\nb\nc", "a\nB\nc"          # no trailing newline
    (tmp_path / "f.txt").write_text(src)
    fd = FileDiffView(2)
    qtbot.addWidget(fd)
    fd.set_texts([src, tgt], [str(tmp_path / "f.txt")] * 2)
    patch = fd.make_patch()
    assert "\\ No newline at end of file" in patch
    target, = patch_targets(str(tmp_path), patch)
    assert target.patched == tgt


def test_patch_targets_preserves_non_utf8_encoding(tmp_path):
    # A latin-1 source (0xe9 = 'é') must be decoded faithfully and its encoding
    # reported, so accepting + saving the patch never clobbers it as UTF-8.
    (tmp_path / "f.txt").write_bytes("caf\xe9\nline2\n".encode("latin-1"))
    patch = make_patch("caf\xe9\nline2\n", "caf\xe9\nLINE2\n")
    target, = patch_targets(str(tmp_path), patch)
    assert target.original == "caf\xe9\nline2\n"       # decoded, not mojibake
    assert target.encoding == "latin-1"
    assert target.patched == "caf\xe9\nLINE2\n"
    # round-trip: re-encoding with the reported codec reproduces the bytes.
    assert target.patched.encode(target.encoding) == "caf\xe9\nLINE2\n".encode("latin-1")


# ---------------------------------------------------------------------------
# P1: patch files are read as bytes — CRLF content and non-UTF-8 survive
# ---------------------------------------------------------------------------

def test_read_patch_text_preserves_crlf(tmp_path):
    # A patch OF a CRLF file carries \r\n inside its content lines. Text-mode
    # reading (newline translation) used to strip them -> context mismatch.
    src = tmp_path / "f.txt"
    src.write_bytes(b"one\r\ntwo\r\n")
    patch_file = tmp_path / "c.patch"
    patch_file.write_bytes(
        b"--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n"
        b" one\r\n-two\r\n+TWO\r\n")
    text = read_patch_text(str(patch_file))
    assert "\r\n" in text
    target, = patch_targets(str(tmp_path), text)
    assert target.patched == "one\r\nTWO\r\n"


def test_read_patch_text_latin1_fallback(tmp_path):
    src = tmp_path / "f.txt"
    src.write_bytes("caf\xe9\n".encode("latin-1"))
    patch_file = tmp_path / "l.patch"
    patch_file.write_bytes(
        "--- a/f.txt\n+++ b/f.txt\n@@ -1,1 +1,2 @@\n"
        " caf\xe9\n+line2\n".encode("latin-1"))
    text = read_patch_text(str(patch_file))
    target, = patch_targets(str(tmp_path), text)
    assert target.patched == "caf\xe9\nline2\n"
    assert target.encoding == "latin-1"
