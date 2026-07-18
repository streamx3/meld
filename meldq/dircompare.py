"""Qt-free directory-comparison core for DirDiff.

Compares 2 or 3 parallel directory trees and yields, per name, whether it is the
same / modified / present-only-on-some-side across the panes. The Qt tree view
and the cooperative scan scheduler are layered on top (M3 view). Content
comparison reads bytes (never text-decodes, so binaries and CRLF are safe) and
supports optional text filters (regexes stripped before comparing).

State model (a subset of 3.24's, enough for v1 folder compare):
  NORMAL   present everywhere, identical
  NOCHANGE present everywhere, identical only after text filters
  MODIFIED present everywhere, differing content
  NEW      present on this pane, absent on another
  MISSING  absent on this pane, present on another
  ERROR    could not be read/compared
"""

import filecmp
import os
import re
import stat

STATE_NORMAL, STATE_NOCHANGE, STATE_MODIFIED, STATE_NEW, STATE_MISSING, \
    STATE_ERROR = range(6)

# Version-control metadata directories hidden by default (they are large and
# never interesting to diff). The full name/text-filter UI is deferred; this is
# the sane default so comparing two working copies doesn't descend into .git.
VC_METADATA_DIRS = frozenset(
    {".git", ".svn", ".hg", ".bzr", "CVS", "_darcs", ".osc"})


def default_name_filters():
    """Default name-filter predicates (keep a name if the predicate is True)."""
    return [lambda name: name not in VC_METADATA_DIRS]


def _streams_equal(paths, chunk=65536):
    """Byte-compare files of equal size without slurping them whole."""
    handles = [open(p, "rb") for p in paths]
    try:
        while True:
            blocks = [h.read(chunk) for h in handles]
            if any(b != blocks[0] for b in blocks):
                return False
            if not blocks[0]:           # all at EOF together (sizes matched)
                return True
    finally:
        for h in handles:
            h.close()


def files_same(paths, regexes=()):
    """Tri-state content comparison of existing paths: 1 identical, 2 identical
    only after applying `regexes`, 0 different. All-directories -> 1; a
    file/dir mix -> 0."""
    if len(paths) <= 1:
        return 1
    sigs = [os.stat(p) for p in paths]
    are_files = [stat.S_ISREG(s.st_mode) for s in sigs]
    if not any(are_files):              # all directories
        return 1
    if not all(are_files):              # a file/dir mixture
        return 0

    if not regexes:
        # No filters: different sizes differ; else stream-compare in chunks
        # instead of loading every pane's whole file into memory at once.
        if len({s.st_size for s in sigs}) > 1:
            return 0
        return 1 if _streams_equal(paths) else 0

    # Filtered compare needs the full content to strip the regexes. Decode with
    # latin-1 (a lossless 1:1 byte map) NOT utf-8/"replace" — the latter folds
    # every distinct invalid byte to U+FFFD, so two byte-different binaries
    # would compare equal and wrongly report NOCHANGE even when no regex matched.
    try:
        contents = [open(p, "rb").read() for p in paths]
    except (MemoryError, OverflowError):
        for i in range(len(paths) - 1):
            if not filecmp.cmp(paths[i], paths[i + 1], shallow=False):
                return 0
        return 1
    if all(c == contents[0] for c in contents):
        return 1
    texts = [c.decode("latin-1") for c in contents]
    for regex in regexes:
        texts = [re.sub(regex, "", t) for t in texts]
    if all(t == texts[0] for t in texts):
        return 2
    return 0


def entry_states(paths, regexes=()):
    """Per-pane states for one name. `paths` is one path per pane (the name
    joined onto each root; the file may or may not exist). Returns
    (states, different)."""
    n = len(paths)
    present = [os.path.exists(p) for p in paths]
    states = [STATE_MISSING] * n
    if all(present):
        # An unreadable directory would otherwise list as empty, so its contents
        # get misclassified as one-sided and the parent wrongly reads NORMAL
        # ("the trees are identical"). Flag it ERROR so it is visible and the
        # walk can refuse to descend into it.
        if any(os.path.isdir(p) and not os.access(p, os.R_OK) for p in paths):
            return [STATE_ERROR] * n, True
        try:
            same = files_same([p for p in paths], regexes)
        except OSError:
            return [STATE_ERROR] * n, True
        kind = (STATE_NORMAL if same == 1
                else STATE_NOCHANGE if same == 2 else STATE_MODIFIED)
        return [kind] * n, same == 0
    if any(present):
        for i in range(n):
            states[i] = STATE_NEW if present[i] else STATE_MISSING
        return states, True
    return states, False


def _listdir(path, name_filters):
    try:
        names = os.listdir(path)
    except OSError:
        return None
    for keep in name_filters:
        names = [n for n in names if keep(n)]
    return names


class Entry:
    """One compared name in the tree walk."""

    __slots__ = ("relpath", "name", "paths", "isdir", "states", "different",
                 "error")

    def __init__(self, relpath, paths, isdir, states, different, error=False):
        self.relpath = relpath
        self.name = os.path.basename(relpath)
        self.paths = paths                  # one per pane (may not exist)
        self.isdir = isdir
        self.states = states                # per pane
        self.different = different
        self.error = error

    def __repr__(self):
        return "Entry(%r, isdir=%s, states=%s)" % (
            self.relpath, self.isdir, self.states)


def walk(roots, name_filters=(), regexes=()):
    """Yield an :class:`Entry` per name under the parallel `roots`, breadth-
    first (parents before children). `name_filters` are predicates (keep a name
    if all return True); `regexes` are compiled text filters for content
    comparison."""
    todo = [""]                             # relpaths of directories to expand
    visited = set()                         # real paths already expanded
    while todo:
        rel = todo.pop(0)
        dir_paths = [os.path.join(r, rel) if rel else r for r in roots]
        # Cycle guard: a directory symlink pointing at an ancestor would make
        # the walk descend through it forever. Key each expansion by the real
        # paths of its panes and skip one we've already expanded.
        key = tuple(sorted(os.path.realpath(dp)
                           for dp in dir_paths if os.path.isdir(dp)))
        if key in visited:
            continue
        visited.add(key)
        names = set()
        for dp in dir_paths:
            if os.path.isdir(dp):
                listed = _listdir(dp, name_filters)
                if listed:
                    names.update(listed)
        for name in sorted(names):
            child_rel = os.path.join(rel, name) if rel else name
            paths = [os.path.join(dp, name) for dp in dir_paths]
            isdir = any(os.path.isdir(p) for p in paths)
            states, different = entry_states(paths, regexes)
            error = STATE_ERROR in states
            yield Entry(child_rel, paths, isdir, states, different, error=error)
            # Don't descend into an unreadable directory: listing it would
            # misclassify the side that IS readable as wholly new.
            if isdir and not error:
                todo.append(child_rel)
