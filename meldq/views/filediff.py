"""FileDiffView — the fresh 2- or 3-way text comparison/merge view.

2-way is driven directly by the 3.24-aligned Myers matcher (intuitive
left→right, red/green-by-side). 3-way is driven by the Differ (pane 1 = base):
it renders each pane's changes vs the base with a single "change" colour, blue
for aligned replaces and a distinct colour for conflicts (both sides changed the
same base region), with two LinkMaps and outer→base merge. Both paths share the
editor, load/save, sync-scroll and inline machinery.

Kept separate from the 1.4-era meldq/filediff.py, which remains as reference.
"""

import difflib
import hashlib
import os
import stat
import tempfile

from PyQt6.QtCore import QFileSystemWatcher, QPoint, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPolygon
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from meldq.engine.diffutil import Differ
from meldq.engine.matchers import MyersSequenceMatcher
from meldq.views.linkmap import LinkMap
from meldq.widgets.infobar import InfoBar
from meldq.widgets.sciview import (
    KIND_CONFLICT,
    KIND_DELETE,
    KIND_INSERT,
    KIND_REPLACE,
    LIGHT,
    MeldSciView,
)

# 3-way tag -> chunk-background kind. insert/delete are the same "change" colour
# (a deletion is a gap on one side, not red lines); conflict is distinct.
_KIND_3WAY = {
    "insert": KIND_INSERT, "delete": KIND_INSERT,
    "replace": KIND_REPLACE, "conflict": KIND_CONFLICT,
}


def _arrow_pixmap(direction, color="#707070", size=12):
    """A small solid triangle pointing left/right, for the merge action margin
    (QScintilla has RightArrow but no LeftArrow, so both are drawn here)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    m = 3
    if direction == "right":
        pts = [QPoint(m, m), QPoint(size - m, size // 2), QPoint(m, size - m)]
    else:
        pts = [QPoint(size - m, m), QPoint(m, size // 2), QPoint(size - m, size - m)]
    painter.drawPolygon(QPolygon(pts))
    painter.end()
    return pm


def _file_token(path):
    """A content hash of `path` (None if unreadable or path is None). Used to
    tell a real external change from our own save when the on-disk file
    changes."""
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def load_file(path, codecs=("utf-8",)):
    """Read `path`, returning (text, encoding, eol). Tries `codecs` then falls
    back to latin-1 (which decodes any byte), so loading never fails; the
    encoding + EOL are remembered for a faithful write-back on save."""
    with open(path, "rb") as f:
        raw = f.read()
    text = encoding = None
    for candidate in (*codecs, "latin-1"):
        try:
            text, encoding = raw.decode(candidate), candidate
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        text, encoding = raw.decode("utf-8", errors="replace"), "utf-8"
    eol = "\r\n" if "\r\n" in text else ("\r" if "\r" in text else "\n")
    return text, encoding, eol


class FileDiffView(QWidget):
    def __init__(self, num_panes=2, parent=None):
        super().__init__(parent)
        assert num_panes in (2, 3)
        self.num_panes = num_panes
        self.panes = [MeldSciView() for _ in range(num_panes)]
        self._paths = [None] * num_panes
        self._encoding = ["utf-8"] * num_panes      # remembered for write-back
        self._eol = ["\n"] * num_panes
        self._syncing = False
        self._loading = False           # suppress re-diff while loading files
        self._theme = LIGHT
        self.differ = Differ()          # used for the 3-way path

        # On-disk change monitor: a content token per pane distinguishes an
        # external edit from our own save.
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed_on_disk)
        self._disk_token = [None] * num_panes
        self.infobar = InfoBar()

        # LinkMaps between adjacent panes: 2-way uses opcodes(), 3-way pair_chunks.
        self.linkmaps = []
        for side in range(num_panes - 1):
            if num_panes == 2:
                chunks_fn = self.opcodes
            else:
                chunks_fn = (lambda s=side: self.pair_chunks(s))
            self.linkmaps.append(
                LinkMap(self.panes[side], self.panes[side + 1],
                        chunks_fn, self.theme))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.infobar)
        panes_row = QHBoxLayout()
        panes_row.setContentsMargins(0, 0, 0, 0)
        panes_row.setSpacing(0)
        for side in range(num_panes - 1):
            panes_row.addWidget(self.panes[side], 1)
            panes_row.addWidget(self.linkmaps[side])
        panes_row.addWidget(self.panes[-1], 1)
        outer.addLayout(panes_row)

        # Merge arrows: outer panes point inward. 2-way: left→ / right←. 3-way:
        # pane0→ and pane2← both copy into the base (pane 1).
        self.panes[0].set_action_symbol(_arrow_pixmap("right"))
        self.panes[-1].set_action_symbol(_arrow_pixmap("left"))
        for pane, view in enumerate(self.panes):
            view.scrolled.connect(self._on_scrolled)
            view.textChanged.connect(self._on_text_changed)   # live re-diff
            view.action_clicked.connect(
                lambda line, p=pane: self._on_action(p, line))

    # ----- loading ----------------------------------------------------------

    def set_files(self, paths):
        texts = []
        for i, path in enumerate(paths):
            # A missing/None path opens as an empty, creatable pane (Meld lets
            # you diff against / write a not-yet-existing file). An existing but
            # unreadable file (permissions, races) must not abort the app — a
            # slot exception is fatal in PyQt6 — so it degrades to an empty pane
            # plus a message bar.
            text, encoding, eol = "", "utf-8", "\n"
            if path and os.path.isfile(path):
                try:
                    text, encoding, eol = load_file(path)
                except OSError as exc:
                    self.infobar.show_message(
                        'Could not read "%s": %s'
                        % (os.path.basename(path), exc))
            self._encoding[i] = encoding
            self._eol[i] = eol
            self._disk_token[i] = _file_token(path)
            texts.append(text)
        self.set_texts(texts, paths)
        self._watch_files()

    def _watch_files(self):
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        paths = [p for p in self._paths if p]
        if paths:
            self._watcher.addPaths(paths)

    def reload(self, pane):
        """Re-read `pane`'s file, discarding its edits."""
        path = self._paths[pane]
        if path is None:
            return
        try:
            text, encoding, eol = load_file(path)
        except OSError as exc:
            self.infobar.show_message(
                'Could not reload "%s": %s' % (os.path.basename(path), exc))
            return
        self._encoding[pane] = encoding
        self._eol[pane] = eol
        self._disk_token[pane] = _file_token(path)
        self._loading = True
        try:
            self.panes[pane].set_text(text)
        finally:
            self._loading = False
        self.panes[pane].setModified(False)
        self._recompute()
        self.infobar.clear()

    def _on_file_changed_on_disk(self, path):
        # Editors often replace-then-rename, which drops the watch; re-arm it.
        if path not in self._watcher.files() and os.path.exists(path):
            self._watcher.addPath(path)
        current = _file_token(path)
        for pane, pane_path in enumerate(self._paths):
            if pane_path != path or current is None:
                continue
            if current == self._disk_token[pane]:
                continue                    # our own save, or no real change
            self._prompt_reload(pane, path)

    def _prompt_reload(self, pane, path):
        def ignore():
            # Accept the on-disk state as known so we don't re-prompt for it.
            self._disk_token[pane] = _file_token(path)
        self.infobar.show_message(
            '"%s" changed on disk.' % os.path.basename(path),
            [("Reload", lambda: self.reload(pane)), ("Ignore", ignore)])

    def set_texts(self, texts, paths=None):
        paths = paths or [None] * len(texts)
        self._loading = True
        try:
            for i, view in enumerate(self.panes):
                text = texts[i] if i < len(texts) else ""
                view.set_language_for(paths[i] if i < len(paths) else None)
                view.set_text(text)
                self._paths[i] = paths[i] if i < len(paths) else None
        finally:
            self._loading = False
        for view in self.panes:
            view.setModified(False)     # a freshly-loaded pane is unmodified
        self._recompute()

    # ----- saving -----------------------------------------------------------

    def is_modified(self, pane):
        return self.panes[pane].isModified()

    def any_modified(self):
        return any(self.is_modified(p) for p in range(self.num_panes))

    def path(self, pane):
        """The on-disk path backing `pane`, or None (never loaded from a file)."""
        return self._paths[pane]

    def set_encoding(self, pane, encoding, eol=None):
        """Set the encoding (and optionally EOL) used to write `pane` back.
        A buffer populated via set_texts (e.g. patch import) otherwise defaults
        to utf-8; setting the source's real encoding here keeps save faithful."""
        self._encoding[pane] = encoding or "utf-8"
        if eol:
            self._eol[pane] = eol

    def focused_pane(self):
        """The pane index that currently has keyboard focus (0 if none)."""
        return self._focused_pane()

    def save(self, pane, path=None):
        """Write `pane` back with its original encoding + EOL. The buffer is
        \\n-normalised, so we restore the file's line endings on the way out;
        the trailing-newline state rides along in the text itself.

        The write is encode-first + atomic: the text is encoded before the
        target is touched (so an un-encodable character raises without
        destroying the file), and the bytes go to a sibling temp file that is
        os.replace()d into place (so a crash mid-write can't leave a truncated
        file). Any existing file mode is preserved across the replace."""
        path = path or self._paths[pane]
        if path is None:
            raise ValueError("no path to save pane %d" % pane)
        text = self.panes[pane].text().replace("\n", self._eol[pane])
        data = text.encode(self._encoding[pane] or "utf-8")   # may raise; file untouched
        directory = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".meldq-save-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            try:
                os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
            except OSError:
                pass                        # new file, or stat/chmod unsupported
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        self._paths[pane] = path
        self.panes[pane].setModified(False)
        self._disk_token[pane] = _file_token(path)   # so our write isn't flagged
        if path not in self._watcher.files():
            self._watcher.addPath(path)

    @staticmethod
    def _patch_labels(path_a, path_b):
        """Header labels for an exported diff. Comparing the same relative file
        under two different roots (the DirDiff/VC case) yields that shared
        relative path — so the patch applies at either root with -p1 — else the
        basename (unrelated files have no meaningful common path)."""
        pa = os.path.normpath(os.path.abspath(path_a)).split(os.sep)
        pb = os.path.normpath(os.path.abspath(path_b)).split(os.sep)
        i = 0
        while i < min(len(pa), len(pb)) and pa[i] == pb[i]:
            i += 1
        ra, rb = pa[i:], pb[i:]
        if len(ra) > 1 and len(rb) > 1 and ra[1:] == rb[1:]:
            rel = "/".join(ra[1:])
            return rel, rel
        return os.path.basename(path_a), os.path.basename(path_b)

    def make_patch(self, left_pane=0, right_pane=1, reverse=False):
        """A unified diff between two panes (export). `reverse` swaps old/new;
        for a 3-way view pass the pair to compare. Round-trips with
        meldq.patchimport. Each side's original line endings are restored (the
        buffer is \\n-normalised), so a patch of a CRLF file applies to it."""
        a = self.panes[left_pane].text().replace(
            "\n", self._eol[left_pane]).splitlines(keepends=True)
        b = self.panes[right_pane].text().replace(
            "\n", self._eol[right_pane]).splitlines(keepends=True)
        la, lb = self._patch_labels(self._paths[left_pane] or "a",
                                    self._paths[right_pane] or "b")
        if reverse:
            a, b, la, lb = b, a, lb, la
        lines = []
        for line in difflib.unified_diff(
                a, b, fromfile="a/" + la, tofile="b/" + lb):
            # A body line with no trailing newline means the file's final line
            # lacks one; emit the standard marker so external patch/git apply
            # accept it (meldq's own importer tolerates either form).
            if line[:1] in (" ", "-", "+") and not line.endswith("\n"):
                lines.append(line + "\n\\ No newline at end of file\n")
            else:
                lines.append(line)
        return "".join(lines)

    def theme(self):
        return self._theme

    def set_theme(self, theme):
        self._theme = theme
        for view in self.panes:
            view.apply_theme(theme)
        for lm in self.linkmaps:
            lm.update()

    # ----- diff computation / rendering -------------------------------------

    def _pane_lines(self, i):
        return self.panes[i].text().split("\n")

    def opcodes(self):
        """2-way chunks (tag, left_lo, left_hi, right_lo, right_hi)."""
        return MyersSequenceMatcher(
            None, self._pane_lines(0), self._pane_lines(1)
        ).get_difference_opcodes()

    def pair_chunks(self, side):
        """3-way chunks between adjacent panes `side` and `side+1`, as
        (tag, left_lo, left_hi, right_lo, right_hi). Base is pane 1."""
        result = []
        for c0, c1 in self.differ.all_changes():
            chunk = c0 if side == 0 else c1
            if chunk is None:
                continue
            tag = chunk[0]
            if side == 0:        # left=pane0 (chunk[3:5]), right=base (chunk[1:3])
                result.append((tag, chunk[3], chunk[4], chunk[1], chunk[2]))
            else:                # left=base (chunk[1:3]), right=pane2 (chunk[3:5])
                result.append((tag, chunk[1], chunk[2], chunk[3], chunk[4]))
        return result

    def _recompute(self):
        if self.num_panes == 3:
            seqs = [self._pane_lines(p) for p in range(3)]
            for _ in self.differ.set_sequences_iter(seqs):
                pass
        self._render()

    def _on_text_changed(self):
        # Synchronous full re-diff. Correct + deterministic; the Differ's
        # incremental change_sequence swaps in when large-file perf matters.
        if self._loading:
            return
        self._recompute()

    def _render(self):
        for view in self.panes:
            view.clear_chunks()
            view.clear_inline()
            view.clear_action_markers()
        if self.num_panes == 2:
            self._render_2way()
        else:
            self._render_3way()
        for lm in self.linkmaps:
            lm.update()

    def _render_2way(self):
        left, right = self.panes
        left_lines, right_lines = self._pane_lines(0), self._pane_lines(1)
        for tag, l1, l2, r1, r2 in MyersSequenceMatcher(
                None, left_lines, right_lines).get_difference_opcodes():
            if tag == "delete":
                left.add_chunk(l1, l2, KIND_DELETE)
                left.add_action_marker(l1)          # → send left's lines right
            elif tag == "insert":
                right.add_chunk(r1, r2, KIND_INSERT)
                right.add_action_marker(r1)         # ← send right's lines left
            elif tag == "replace":
                left.add_chunk(l1, l2, KIND_REPLACE)
                right.add_chunk(r1, r2, KIND_REPLACE)
                left.add_action_marker(l1)
                right.add_action_marker(r1)
                self._inline_two_sided(left_lines, right_lines, l1, l2, r1, r2)

    def _render_3way(self):
        lines = [self._pane_lines(p) for p in range(3)]
        for pane in range(3):
            for c in self.differ.single_changes(pane):
                tag, lo, hi, olo, ohi = c[0], c[1], c[2], c[3], c[4]
                if lo < hi:
                    self.panes[pane].add_chunk(lo, hi, _KIND_3WAY[tag])
                    if pane != 1:               # merge arrows on outer panes only
                        self.panes[pane].add_action_marker(lo)
                if tag in ("replace", "conflict") and lo < hi and olo < ohi:
                    self._inline_one_sided(pane, lo, hi, lines[pane],
                                           olo, ohi, lines[1])

    # ----- inline highlighting ----------------------------------------------

    _INLINE_MAX = 10000     # skip intra-line diffing of huge replace regions

    def _inline_two_sided(self, left_lines, right_lines, l1, l2, r1, r2):
        # 2-way: mark both sides of a replace in one pass.
        left_region, right_region = left_lines[l1:l2], right_lines[r1:r2]
        text_l, text_r = "\n".join(left_region), "\n".join(right_region)
        if len(text_l) > self._INLINE_MAX and len(text_r) > self._INLINE_MAX:
            return
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                None, text_l, text_r, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            if i2 > i1:
                self._mark_region(0, l1, left_region, i1, i2)
            if j2 > j1:
                self._mark_region(1, r1, right_region, j1, j2)

    def _inline_one_sided(self, pane, lo, hi, this_lines, olo, ohi, other_lines):
        # 3-way: mark only `pane`'s region against the base; the base marks
        # itself from its own single_changes pass (avoids double-marking).
        this_region, other_region = this_lines[lo:hi], other_lines[olo:ohi]
        text_a, text_b = "\n".join(this_region), "\n".join(other_region)
        if len(text_a) > self._INLINE_MAX and len(text_b) > self._INLINE_MAX:
            return
        for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(
                None, text_a, text_b, autojunk=False).get_opcodes():
            if tag != "equal" and i2 > i1:
                self._mark_region(pane, lo, this_region, i1, i2)

    def _mark_region(self, pane, start_line, region_lines, o1, o2):
        # Map a [o1, o2) char range in "\n".join(region_lines) to per-line
        # inline marks; the joining newlines are separators, never highlighted.
        pos = 0
        for k, line in enumerate(region_lines):
            line_start, line_end = pos, pos + len(line)
            a, b = max(o1, line_start), min(o2, line_end)
            if a < b:
                self.panes[pane].add_inline(start_line + k, a - line_start,
                                            b - line_start)
            pos = line_end + 1      # + the '\n' separator

    # ----- merge ------------------------------------------------------------

    @staticmethod
    def _pane_range(chunk, pane):
        _tag, l1, l2, r1, r2 = chunk
        return (l1, l2) if pane == 0 else (r1, r2)

    def chunk_at_line(self, pane, line):
        """[2-way] the change covering `line` in `pane`, or None. Zero-width
        chunks match at their position."""
        for chunk in self.opcodes():
            lo, hi = self._pane_range(chunk, pane)
            if lo <= line < hi or (lo == hi and line == lo):
                return chunk
        return None

    def copy_chunk(self, chunk, src_pane, dst_pane):
        """[2-way] replace dst_pane's side of `chunk` with src_pane's lines."""
        src_lo, src_hi = self._pane_range(chunk, src_pane)
        dst_lo, dst_hi = self._pane_range(chunk, dst_pane)
        seg = self._pane_lines(src_pane)[src_lo:src_hi]
        self.panes[dst_pane].replace_line_range(dst_lo, dst_hi, seg)

    def delete_chunk(self, chunk, pane):
        """[2-way] remove pane's side of `chunk` (undoable)."""
        lo, hi = self._pane_range(chunk, pane)
        self.panes[pane].replace_line_range(lo, hi, [])

    def outer_chunk_at_line(self, pane, line):
        """[3-way] the change on outer `pane` (0 or 2) covering `line`, as
        (tag, this_lo, this_hi, base_lo, base_hi), or None."""
        for c in self.differ.single_changes(pane):
            lo, hi = c[1], c[2]
            if lo <= line < hi or (lo == hi and line == lo):
                return c
        return None

    def copy_to_base(self, pane, chunk):
        """[3-way] replace the base's (pane 1) side of `chunk` with outer
        `pane`'s lines (undoable)."""
        this_lo, this_hi, base_lo, base_hi = chunk[1], chunk[2], chunk[3], chunk[4]
        seg = self._pane_lines(pane)[this_lo:this_hi]
        self.panes[1].replace_line_range(base_lo, base_hi, seg)

    def _on_action(self, pane, line):
        # Merge arrow clicked. 2-way: send that pane's side to the other pane.
        # 3-way: an outer pane sends its side into the base (pane 1).
        # The action margin is sensitive along its whole height, but only lines
        # that actually carry an arrow are merge points; without this guard a
        # click on the empty margin matches a zero-width chunk and silently
        # performs a destructive merge (deletes the other pane's added lines).
        if not self.panes[pane].has_action_marker(line):
            return
        if self.num_panes == 2:
            chunk = self.chunk_at_line(pane, line)
            if chunk is not None:
                self.copy_chunk(chunk, src_pane=pane, dst_pane=1 - pane)
        elif pane != 1:
            chunk = self.outer_chunk_at_line(pane, line)
            if chunk is not None:
                self.copy_to_base(pane, chunk)

    # ----- navigation -------------------------------------------------------

    def _focused_pane(self):
        for i, view in enumerate(self.panes):
            if view.hasFocus():
                return i
        return 0

    def _pane_change_starts(self, pane):
        if self.num_panes == 2:
            return sorted(self._pane_range(c, pane)[0] for c in self.opcodes())
        return sorted(c[1] for c in self.differ.single_changes(pane))

    def next_diff(self, pane=None):
        """Move the cursor to the next change below it; returns its line or None."""
        return self._go_diff(1, pane)

    def prev_diff(self, pane=None):
        return self._go_diff(-1, pane)

    def _go_diff(self, direction, pane):
        if pane is None:
            pane = self._focused_pane()
        line = self.panes[pane].getCursorPosition()[0]
        starts = self._pane_change_starts(pane)
        if direction > 0:
            target = next((s for s in starts if s > line), None)
        else:
            target = next((s for s in reversed(starts) if s < line), None)
        if target is not None:
            self.panes[pane].setCursorPosition(target, 0)
            self.panes[pane].ensureLineVisible(target)
        return target

    # ----- sync scroll ------------------------------------------------------

    def _on_scrolled(self):
        for lm in self.linkmaps:
            lm.update()                 # connectors follow the scroll
        if self._syncing:
            return
        src = self.sender()
        if src not in self.panes:
            return
        line = src.first_visible_line()
        self._syncing = True
        try:
            for view in self.panes:
                if view is not src:
                    view.scroll_to_line(line)
        finally:
            self._syncing = False


def main(argv=None):
    """Minimal runner: `python -m meldq.views.filediff A B [C]` opens a diff."""
    import sys

    from PyQt6.QtWidgets import QApplication

    argv = list(sys.argv if argv is None else argv)
    files = argv[1:4]
    app = QApplication(argv[:1])
    view = FileDiffView(3 if len(files) == 3 else 2)
    view.set_theme(LIGHT)
    view.resize(300 * view.num_panes, 600)
    if len(files) == view.num_panes:
        view.set_files(files)
    view.setWindowTitle("meldq — " + " : ".join(files) if files else "meldq")
    view.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
