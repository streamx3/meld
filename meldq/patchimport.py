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

from meldq.patch import PatchError, apply_patch, parse_patch

# Codecs tried in order; latin-1 decodes any byte, so decode never fails and a
# round-trip (decode -> encode with the same codec) is byte-preserving.
_CODECS = ("utf-8", "latin-1")

# path      : resolved target path under base_dir (the new name for a rename)
# original  : source text (decoded), "" if the source is absent (a new file)
# patched   : text after applying the file's hunks to `original`
# encoding  : codec `original` was decoded with (use it to write back)
# eol       : the source's dominant line ending ("\n"/"\r\n"/"\r")
# is_delete : the patch deletes this file (+++ /dev/null)
PatchTarget = namedtuple(
    "PatchTarget", "path original patched encoding eol is_delete",
    defaults=(False,))


def _strip_prefix(path):
    """A header path as a relative path: strip the a/ b/ prefix; None for an
    absent side (None or /dev/null)."""
    if not path or path == "/dev/null":
        return None
    return path[2:] if path[:2] in ("a/", "b/") else path


def _relpath(file_patch):
    for candidate in (file_patch.new_path, file_patch.old_path):
        rel = _strip_prefix(candidate)
        if rel:
            return rel
    return ""


def _resolve_under(base_dir, rel):
    """`rel` joined onto `base_dir`, refusing escapes: an absolute header path
    or a ../ traversal must not read or target files outside the directory the
    user chose (a hostile patch is still just a text file)."""
    base = os.path.abspath(base_dir)
    resolved = os.path.abspath(os.path.join(base, rel))
    try:
        contained = os.path.commonpath([base, resolved]) == base
    except ValueError:                    # e.g. different drives on Windows
        contained = False
    if not contained or resolved == base:
        raise PatchError(
            "patch names a path outside the chosen base directory: %r" % rel)
    return resolved


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


def read_patch_text(path):
    """Read a .patch file preserving its bytes' meaning: binary read (so the
    \\r in CRLF content lines survives — text mode's newline translation broke
    every CRLF patch) and encoding-aware decode (utf-8 then latin-1, so a
    legacy-encoded patch isn't corrupted by errors='replace')."""
    with open(path, "rb") as handle:
        raw = handle.read()
    for encoding in _CODECS:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def patch_targets(base_dir, patch_text):
    """[PatchTarget] for each text file named in the patch.

    A missing source yields original "" (a newly-added file). For a rename the
    source is read from the OLD name and the target path is the new name. A
    binary entry yields no target (returned separately — see
    patch_targets_and_skipped). A PatchError from the parse/apply layer
    propagates to the caller.
    """
    return patch_targets_and_skipped(base_dir, patch_text)[0]


def patch_targets_and_skipped(base_dir, patch_text):
    """(targets, skipped): the applyable text targets plus the names of binary
    entries meldq cannot apply (so callers can tell the user instead of
    silently dropping them)."""
    targets = []
    skipped = []
    for file_patch in parse_patch(patch_text):
        rel = _relpath(file_patch)
        if file_patch.binary:
            skipped.append(rel or "?")
            continue
        old_rel = _strip_prefix(file_patch.old_path)
        is_rename = bool(old_rel and rel and old_rel != rel)
        if not file_patch.hunks and not is_rename:
            continue          # header-only noise (e.g. a mode-change entry)
        if not rel:
            raise PatchError("patch does not name a target file")
        path = _resolve_under(base_dir, rel)
        src_path = path
        if not os.path.isfile(path) and is_rename:
            # Rename: the content lives under the old name pre-apply.
            candidate = _resolve_under(base_dir, old_rel)
            if os.path.isfile(candidate):
                src_path = candidate
        if os.path.isfile(src_path):
            original, encoding = _read_source(src_path)
        else:
            original, encoding = "", "utf-8"
        patched = apply_patch(original, file_patch)
        is_delete = file_patch.new_path == "/dev/null"
        targets.append(
            PatchTarget(path, original, patched, encoding,
                        _detect_eol(original), is_delete))
    return targets, skipped


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
