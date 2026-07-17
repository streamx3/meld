"""Unified-diff patch parsing and application — pure Python, no GNU ``patch``.

The product differentiator: importing/applying an external ``.patch`` file, which
neither Meld 1.4 nor 3.24 can do. The interaction model is that patch import is
*just a FileDiff*: parse the patch, apply it to the source to get the target text,
then present source-vs-target so the user accepts/rejects each hunk with the
standard merge UI. Selective apply (a subset of hunks) is what "reject this hunk"
maps to.

This module is the Qt-free core proven in milestone M0.5; the UI wiring lands in
M5. It has NO dependency on the ``patch`` binary — important for Windows, and the
exact portability problem that sank the 1.4 ``vcview.show_patch`` path.

Line model: content is handled via ``splitlines(keepends=True)`` so line endings
(LF today; CRLF/no-final-newline preserved as bytes-of-text) travel *inside* each
line, making apply a pure list splice + ``"".join`` with no separate newline
bookkeeping. Fuzzy context matching (ignoring N context lines) is future
hardening; today's matcher is exact-with-offset-search.
"""

import re
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_OLD_HDR = re.compile(r"^--- (.*?)(?:\t.*)?$")
_NEW_HDR = re.compile(r"^\+\+\+ (.*?)(?:\t.*)?$")
_CONTEXT_RANGE = re.compile(r"^\d+(,\d+)? ----$")   # context-format hunk range


class PatchError(Exception):
    """A hunk could not be applied (context did not match within the offset
    window). Carries the offending hunk so the UI can flag/skip it."""

    def __init__(self, message, hunk=None):
        super().__init__(message)
        self.hunk = hunk


@dataclass
class Hunk:
    src_start: int          # 1-based first source line the hunk covers
    src_len: int
    tgt_start: int          # 1-based first target line
    tgt_len: int
    lines: list = field(default_factory=list)   # (op, content) op in {' ','-','+'}

    def _block(self, ops):
        return [content for op, content in self.lines if op in ops]

    def old_block(self):    # context + removed  (the text present in the source)
        return self._block(" -")

    def new_block(self):    # context + added    (the text after applying)
        return self._block(" +")


@dataclass
class FilePatch:
    old_path: str | None = None
    new_path: str | None = None
    hunks: list = field(default_factory=list)
    binary: bool = False        # "GIT binary patch" / "Binary files ... differ"

    @property
    def target_path(self):
        # "b/foo" -> "foo"; "/dev/null" stays (a deletion)
        p = self.new_path
        if p and p != "/dev/null" and p.startswith("b/"):
            return p[2:]
        return p


def _strip_op(line):
    """Content after the leading op char, keeping the line's own ending."""
    return line[1:]


def _unquote_git_path(path):
    """Decode a git-quoted path (core.quotePath): '"f\\303\\274ile.txt"' ->
    'füile.txt'. Unquoted paths pass through unchanged."""
    if not (path and len(path) >= 2 and path[0] == '"' and path[-1] == '"'):
        return path
    inner = path[1:-1]
    try:
        # unicode_escape resolves \t \" \\ and the octal byte escapes; the
        # resulting chars are the raw bytes, which are UTF-8 of the real name.
        raw = inner.encode("ascii").decode("unicode_escape").encode("latin-1")
        return raw.decode("utf-8", "replace")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return inner


_GIT_DIFF_PATHS = re.compile(
    r'^("(?:[^"\\]|\\.)*"|\S+) ("(?:[^"\\]|\\.)*"|\S+)$')


def _parse_git_diff_line(line):
    """The two paths from a 'diff --git a/x b/y' line (quoted or plain), or
    (None, None) if they cannot be recovered."""
    rest = line[len("diff --git "):].rstrip()
    m = _GIT_DIFF_PATHS.match(rest)
    if m:
        return _unquote_git_path(m.group(1)), _unquote_git_path(m.group(2))
    # Unquoted names containing spaces are ambiguous; git separates them with
    # ' b/', so split at its last occurrence.
    idx = rest.rfind(" b/")
    if idx > 0:
        return rest[:idx], rest[idx + 1:]
    return None, None


def parse_patch(text):
    """Parse unified-diff text into a list of :class:`FilePatch`.

    Body lines are consumed by the counts in each ``@@`` header rather than by
    guessing where a hunk ends, so empty/whitespace context lines are safe.
    """
    lines = text.splitlines(keepends=True)
    files = []
    current = None
    expect_headers = False      # a `diff --git` opened an entry; ---/+++ refine it
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        line = raw.rstrip("\r\n")

        # Git extended headers: `diff --git` opens the entry (a pure rename or
        # binary change has no ---/+++ lines at all), rename lines carry the
        # authoritative names, binary markers flag content we cannot apply.
        if line.startswith("diff --git "):
            a_path, b_path = _parse_git_diff_line(line)
            current = FilePatch(old_path=a_path, new_path=b_path)
            files.append(current)
            expect_headers = True
            i += 1
            continue

        if line.startswith("rename from ") and current is not None:
            current.old_path = _unquote_git_path(line[len("rename from "):])
            i += 1
            continue

        if line.startswith("rename to ") and current is not None:
            current.new_path = _unquote_git_path(line[len("rename to "):])
            i += 1
            continue

        if (line == "GIT binary patch" or line.startswith("Binary files ")) \
                and current is not None:
            current.binary = True
            expect_headers = False      # entry complete; a later --- is a new file
            i += 1
            continue

        # File headers. Only reachable *between* hunks — hunk bodies are consumed
        # in the inner loop below, so a removed line like "--- x" never lands here.
        if line.startswith("--- "):
            m = _OLD_HDR.match(line)
            target = m.group(1) if m else None
            # In a context-format diff every hunk has a "--- N,M ----" range
            # line, which would otherwise mis-parse as a unified file header
            # and yield garbage no-op targets. Fail loudly instead.
            if target is not None and _CONTEXT_RANGE.match(target):
                raise PatchError(
                    "context-format (non-unified) diffs are not supported")
            target = _unquote_git_path(target)
            if expect_headers and current is not None and not current.hunks:
                if target is not None:
                    current.old_path = target
            else:
                current = FilePatch(old_path=target)
                files.append(current)
            i += 1
            continue

        if line.startswith("+++ "):
            m = _NEW_HDR.match(line)
            if current is None:
                current = FilePatch()
                files.append(current)
            current.new_path = _unquote_git_path(m.group(1) if m else None)
            i += 1
            continue

        m = _HUNK_RE.match(line)
        if m:
            if current is None:                 # a bare hunk with no file header
                current = FilePatch()
                files.append(current)
            expect_headers = False
            src_start = int(m.group(1))
            src_len = int(m.group(2)) if m.group(2) is not None else 1
            tgt_start = int(m.group(3))
            tgt_len = int(m.group(4)) if m.group(4) is not None else 1
            hunk = Hunk(src_start, src_len, tgt_start, tgt_len)
            i += 1
            old_seen = new_seen = 0
            while i < n:
                body = lines[i]
                op = body[0] if body else " "
                if op == "\\":                  # "\ No newline at end of file"
                    if hunk.lines:              # the previous content line has no EOL
                        pop_op, pop_content = hunk.lines[-1]
                        hunk.lines[-1] = (pop_op, pop_content.rstrip("\r\n"))
                    i += 1
                    continue                    # consumed even after counts are met
                if old_seen >= src_len and new_seen >= tgt_len:
                    break                       # hunk body complete
                if op == "-":
                    hunk.lines.append(("-", _strip_op(body)))
                    old_seen += 1
                elif op == "+":
                    hunk.lines.append(("+", _strip_op(body)))
                    new_seen += 1
                elif op == " ":
                    hunk.lines.append((" ", _strip_op(body)))
                    old_seen += 1
                    new_seen += 1
                elif body in ("\n", "\r\n"):
                    # A blank context line whose leading space was stripped
                    # (mail/editor mangling): the WHOLE line is the content —
                    # _strip_op would eat the newline and never match the source.
                    hunk.lines.append((" ", body))
                    old_seen += 1
                    new_seen += 1
                else:                           # unexpected line ends the hunk
                    break
                i += 1
            # A hunk that promises more lines than its body delivers (truncated
            # download, mangled mail) must not half-apply silently.
            if old_seen < src_len or new_seen < tgt_len:
                raise PatchError(
                    "truncated hunk @ %d: header promises -%d/+%d lines, "
                    "body has -%d/+%d" % (src_start, src_len, tgt_len,
                                          old_seen, new_seen), hunk)
            current.hunks.append(hunk)
            continue

        if line.startswith("@@"):
            # Looked like a hunk header but did not parse (e.g. "@@ -1,3 +1,3 @")
            # — dropping it would silently skip the whole hunk body.
            raise PatchError("malformed hunk header: %r" % line)

        i += 1      # skip diff --git / index / mode / prose lines
    return files


def _find(haystack, needle, center, max_offset):
    """Index where ``needle`` matches ``haystack`` closest to ``center``.

    Searches ``center`` first, then alternating outward. ``-1`` if not found.
    An empty ``needle`` (pure insertion) matches at the clamped ``center``.
    """
    if not needle:
        return max(0, min(center, len(haystack)))
    limit = len(haystack) - len(needle)
    if limit < 0:
        return -1
    for delta in range(max_offset + 1):
        for pos in ({center + delta, center - delta} if delta else {center}):
            if 0 <= pos <= limit and haystack[pos:pos + len(needle)] == needle:
                return pos
    return -1


def apply_hunks(source_text, hunks, reverse=False, max_offset=1000):
    """Apply ``hunks`` (in order) to ``source_text``, returning the patched text.

    Pass a *subset* of a file's hunks to model "accept these, reject the rest".
    ``reverse=True`` un-applies (target -> source). Raises :class:`PatchError`
    on the first hunk whose context cannot be located within ``max_offset``.
    """
    result = source_text.splitlines(keepends=True)
    offset = 0
    for hunk in hunks:
        if reverse:
            old, new = hunk.new_block(), hunk.old_block()
            start = hunk.tgt_start
        else:
            old, new = hunk.old_block(), hunk.new_block()
            start = hunk.src_start
        # A non-empty range starts at 1-based `start` (0-based start-1). A
        # zero-length range (pure insertion, e.g. `@@ -5,0 +6 @@` from
        # `git diff -U0`) means "insert AFTER line `start`", i.e. 0-based
        # index `start` — using start-1 there splices one line too early.
        center = (start if not old else start - 1) + offset
        pos = _find(result, old, center, max_offset)
        if pos < 0:
            raise PatchError(
                f"hunk @ {hunk.src_start} does not apply (context mismatch)",
                hunk)
        result[pos:pos + len(old)] = new
        offset += len(new) - len(old)
    return "".join(result)


def apply_patch(source_text, file_patch, reverse=False, max_offset=1000):
    """Apply every hunk of a :class:`FilePatch` to ``source_text``."""
    return apply_hunks(source_text, file_patch.hunks, reverse=reverse,
                       max_offset=max_offset)
