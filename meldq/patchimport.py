"""Patch import — apply an external .patch and open it as a FileDiff.

The product differentiator: neither Meld 1.4 nor 3.24 can import/apply a .patch.
The model (proven in M0.5): patch import = FileDiff(source, apply(source, patch)),
so the user reviews and accepts/rejects each hunk with the normal merge UI. This
module resolves each file named in a patch to its source under a base directory
and computes the patched text; the caller opens a FileDiff per file.

Qt-free (imported headlessly); the read is encoding-aware so a non-UTF-8 source
is decoded faithfully and its encoding travels to the FileDiff for a lossless
write-back on save.
"""

import os
from collections import namedtuple

from meldq.patch import apply_patch, parse_patch

# Codecs tried in order; latin-1 decodes any byte, so decode never fails and a
# round-trip (decode -> encode with the same codec) is byte-preserving.
_CODECS = ("utf-8", "latin-1")

# path      : resolved source path under base_dir
# original  : source text (decoded), "" if the source is absent (a new file)
# patched   : text after applying the file's hunks to `original`
# encoding  : codec `original` was decoded with (use it to write back)
# eol       : the source's dominant line ending ("\n"/"\r\n"/"\r")
PatchTarget = namedtuple(
    "PatchTarget", "path original patched encoding eol")


def _relpath(file_patch):
    for candidate in (file_patch.new_path, file_patch.old_path):
        if candidate and candidate != "/dev/null":
            return candidate[2:] if candidate[:2] in ("a/", "b/") else candidate
    return ""


def _read_source(path):
    """Decode `path`, returning (text, encoding). Tries UTF-8 then latin-1
    (which accepts any byte), so a non-UTF-8 file is read without corruption."""
    with open(path, "rb") as handle:
        raw = handle.read()
    for encoding in _CODECS:
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _detect_eol(text):
    return "\r\n" if "\r\n" in text else ("\r" if "\r" in text else "\n")


def patch_targets(base_dir, patch_text):
    """[PatchTarget] for each file named in the patch.

    A missing source yields original "" (a newly-added file). A PatchError from
    the apply layer (context mismatch) propagates to the caller.
    """
    targets = []
    for file_patch in parse_patch(patch_text):
        rel = _relpath(file_patch)
        path = os.path.join(base_dir, rel)
        if os.path.isfile(path):
            original, encoding = _read_source(path)
        else:
            original, encoding = "", "utf-8"
        patched = apply_patch(original, file_patch)
        targets.append(
            PatchTarget(path, original, patched, encoding, _detect_eol(original)))
    return targets


def open_in_filediffs(base_dir, patch_text, parent=None):
    """Open one FileDiffView per file in the patch (source on the left, patched
    on the right). Returns the views so the caller can keep them alive."""
    from meldq.views.filediff import FileDiffView

    views = []
    for target in patch_targets(base_dir, patch_text):
        view = FileDiffView(2, parent)
        view.set_texts([target.original, target.patched],
                       [target.path, target.path])
        view.set_encoding(0, target.encoding, target.eol)
        view.set_encoding(1, target.encoding, target.eol)
        view.setWindowTitle("meldq patch — %s" % os.path.basename(target.path))
        views.append(view)
    return views
