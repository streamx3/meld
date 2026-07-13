### Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>

### This program is free software; you can redistribute it and/or modify
### it under the terms of the GNU General Public License as published by
### the Free Software Foundation; either version 2 of the License, or
### (at your option) any later version.

### This program is distributed in the hope that it will be useful,
### but WITHOUT ANY WARRANTY; without even the implied warranty of
### MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
### GNU General Public License for more details.

### You should have received a copy of the GNU General Public License
### along with this program; if not, write to the Free Software
### Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Directory comparison view (port of meld/dirdiff.py).

WP5.2 lands the Qt-free content-comparison and filter-compilation core; the
DirDiff document itself follows in WP5.3+.
"""

import collections
import filecmp
import os
import re
import stat

from meldq.util import misc

# Stat signature for the content-comparison cache. A namedtuple, NOT the py2
# misc.struct: struct.__cmp__ (misc.py:150) is dead in py3, so `==` fell back to
# identity and the cache-validity check (dirdiff.py:79) NEVER hit — every rescan
# silently re-read every file. namedtuple `==` compares by value, restoring it.
StatSig = collections.namedtuple("StatSig", "mode size mtime")
# Keyed on the path tuple only (not the regexes), matching 1.4. The result
# therefore depends on the *current* text filters, so a filter change must
# invalidate it — DirDiff.update_regexes calls clear_cache() (fixes a 1.4 bug
# where changing filters left stale results for unchanged files).
_cache = {}


def clear_cache():
    _cache.clear()


def _files_same(lof, regexes):
    """Return 0 if the files differ, 1 if identical, 2 if identical only after
    applying the text-filter `regexes`.

    Divergence from 1.4 (accepted, D-level): the original read files in TEXT
    mode and ran the user's str regexes over the raw bytes-as-str. Here files
    are read as BYTES (py3 `open(f, "r")` raises UnicodeDecodeError on binary
    and mistranslates CRLF), and the filters apply to a utf-8/replace-decoded
    view. Files differing only inside invalid-utf-8 bytes that a filter matches
    may classify differently; the parity test pins the new behavior.
    """
    if len(lof) <= 1:
        return 1
    lof = tuple(lof)

    def sig(f):
        s = os.stat(f)
        return StatSig(stat.S_IFMT(s.st_mode), s.st_size, s.st_mtime)

    def all_same(seq):
        return all(x == seq[0] for x in seq[1:])

    sigs = tuple(sig(f) for f in lof)
    arefiles = [stat.S_ISREG(s.mode) for s in sigs]
    if arefiles.count(False) == len(arefiles):      # all directories
        return 1
    elif arefiles.count(False):                     # a file/dir mixture
        return 0
    # No filters and mismatched sizes -> definitely different (skip the read).
    if len(regexes) == 0 and not all_same([s.size for s in sigs]):
        return 0
    # Cache: value-compare the stat signatures (see StatSig note above).
    cached = _cache.get(lof)
    if cached is not None and cached[0] == sigs:
        return cached[1]

    try:
        contents = [open(f, "rb").read() for f in lof]
    except (MemoryError, OverflowError):            # files too large to slurp
        # FIXME: filters are not applied in this fallback (as in 1.4).
        for i in range(len(lof) - 1):
            if not filecmp.cmp(lof[i], lof[i + 1], False):
                return 0
        return 1

    if all_same(contents):
        result = 1
    elif regexes:
        texts = [c.decode("utf-8", errors="replace") for c in contents]
        for r in regexes:
            texts = [re.sub(r, "", t) for t in texts]
        result = 2 if all_same(texts) else 0
    else:
        result = 0
    _cache[lof] = (sigs, result)
    return result


class TypeFilter:
    __slots__ = ("label", "filter", "active")

    def __init__(self, label, active, filter):
        self.label = label
        self.active = active
        self.filter = filter


def _compile_text_filter(value):
    """Compile a text-substitution filter with MULTILINE active.

    The 1.4 original appended "(?m)" to the END of the pattern (dirdiff.py:249),
    which Python 3.11 rejects outright: `re.error: global flags not at the start
    of the expression`. A real flag argument is equivalent and placement-safe.
    """
    return re.compile(value, re.MULTILINE)


def _compile_name_filter(value):
    """Compile a filename filter from whitespace-separated shell globs
    (dirdiff.py:287-296). Returns None for an empty pattern (skip it); raises
    re.error for a malformed glob."""
    bits = value.split()
    if len(bits) > 1:
        regex = "(%s)$" % "|".join(misc.shell_to_regex(b)[:-1] for b in bits)
    elif bits:
        regex = misc.shell_to_regex(bits[0])
    else:
        return None
    return re.compile(regex)


def build_text_filters(regexes_pref, on_error=None):
    """Parse the `regexes` pref into compiled MULTILINE patterns
    (dirdiff.py:244-252). `on_error(value)`, if given, is called for a bad
    pattern (the DirDiff method passes a QMessageBox); pure otherwise."""
    result = []
    for line in regexes_pref.split("\n"):
        if not line.strip():
            continue
        item = misc.ListItem(line)
        if not item.active:
            continue
        try:
            result.append(_compile_text_filter(item.value))
        except re.error:
            if on_error is not None:
                on_error(item.value)
    return result


def build_name_filters(filters_pref, on_error=None):
    """Parse the `filters` pref into TypeFilters (dirdiff.py:285-302). Each
    filter's predicate returns True to KEEP a name (not matched by the hide
    pattern). The `r=cregex` default-arg binding is load-bearing (a bare
    closure would capture the loop variable)."""
    result = []
    for line in filters_pref.split("\n"):
        if not line.strip():
            continue
        item = misc.ListItem(line)
        try:
            cregex = _compile_name_filter(item.value)
        except re.error:
            if on_error is not None:
                on_error(item.value)
            continue
        if cregex is None:      # empty pattern -> skip
            continue
        func = lambda x, r=cregex: r.match(x) is None
        result.append(TypeFilter(item.name, item.active, func))
    return result
