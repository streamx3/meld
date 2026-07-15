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

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPolygon
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from meldq.engine.diffutil import Differ
from meldq.engine.matchers import MyersSequenceMatcher
from meldq.views.linkmap import LinkMap
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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for side in range(num_panes - 1):
            layout.addWidget(self.panes[side], 1)
            layout.addWidget(self.linkmaps[side])
        layout.addWidget(self.panes[-1], 1)

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
            text, encoding, eol = load_file(path)
            self._encoding[i] = encoding
            self._eol[i] = eol
            texts.append(text)
        self.set_texts(texts, paths)

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

    def save(self, pane, path=None):
        """Write `pane` back with its original encoding + EOL. The buffer is
        \\n-normalised, so we restore the file's line endings on the way out;
        the trailing-newline state rides along in the text itself."""
        path = path or self._paths[pane]
        if path is None:
            raise ValueError("no path to save pane %d" % pane)
        text = self.panes[pane].text().replace("\n", self._eol[pane])
        with open(path, "wb") as f:
            f.write(text.encode(self._encoding[pane] or "utf-8"))
        self._paths[pane] = path
        self.panes[pane].setModified(False)

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
        src_lines = self._pane_lines(src_pane)
        dst_lines = self._pane_lines(dst_pane)
        seg = src_lines[src_lo:src_hi]
        new_dst = dst_lines[:dst_lo] + seg + dst_lines[dst_hi:]
        self.panes[dst_pane].replace_all_text("\n".join(new_dst))

    def delete_chunk(self, chunk, pane):
        """[2-way] remove pane's side of `chunk` (undoable)."""
        lo, hi = self._pane_range(chunk, pane)
        lines = self._pane_lines(pane)
        self.panes[pane].replace_all_text("\n".join(lines[:lo] + lines[hi:]))

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
        base_lines = self._pane_lines(1)
        new_base = base_lines[:base_lo] + seg + base_lines[base_hi:]
        self.panes[1].replace_all_text("\n".join(new_base))

    def _on_action(self, pane, line):
        # Merge arrow clicked. 2-way: send that pane's side to the other pane.
        # 3-way: an outer pane sends its side into the base (pane 1).
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
