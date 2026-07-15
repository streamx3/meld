"""Patch import — apply an external .patch and open it as a FileDiff.

The product differentiator: neither Meld 1.4 nor 3.24 can import/apply a .patch.
The model (proven in M0.5): patch import = FileDiff(source, apply(source, patch)),
so the user reviews and accepts/rejects each hunk with the normal merge UI. This
module resolves each file named in a patch to its source under a base directory
and computes the patched text; the caller opens a FileDiff per file.
"""

import os

from meldq.patch import apply_patch, parse_patch


def _relpath(file_patch):
    for candidate in (file_patch.new_path, file_patch.old_path):
        if candidate and candidate != "/dev/null":
            return candidate[2:] if candidate[:2] in ("a/", "b/") else candidate
    return ""


def patch_targets(base_dir, patch_text):
    """[(source_path, original_text, patched_text)] for each file in the patch.

    A missing source yields original "" (a newly-added file). A PatchError from
    the apply layer (context mismatch) propagates to the caller.
    """
    targets = []
    for file_patch in parse_patch(patch_text):
        rel = _relpath(file_patch)
        path = os.path.join(base_dir, rel)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as handle:
                original = handle.read()
        else:
            original = ""
        patched = apply_patch(original, file_patch)
        targets.append((path, original, patched))
    return targets


def open_in_filediffs(base_dir, patch_text, parent=None):
    """Open one FileDiffView per file in the patch (source on the left, patched
    on the right). Returns the views so the caller can keep them alive."""
    from meldq.views.filediff import FileDiffView

    views = []
    for path, original, patched in patch_targets(base_dir, patch_text):
        view = FileDiffView(2, parent)
        view.set_texts([original, patched], [path, path])
        view.setWindowTitle("meldq patch — %s" % os.path.basename(path))
        views.append(view)
    return views
