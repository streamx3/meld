"""FileDiffView — the fresh 2-way text comparison/merge view.

M1 (walking skeleton): two MeldSciView panes driven by the 3.24-aligned Myers
matcher, painting chunk backgrounds + inline highlights, with basic sync-scroll.
M2 so far: editable panes with live re-diff, and undoable 2-way merge
(copy/delete a chunk). Still to come in M2: the Differ (incremental re-diff,
3-way, conflicts), the ActionGutter merge UI, the LinkMap connectors, the full
joined-region InlineMyers pass, and encoding-aware load/save + on-disk reload.
Kept separate from the 1.4-era meldq/filediff.py, which remains as reference.
"""

import difflib

from PyQt6.QtWidgets import QHBoxLayout, QWidget

from meldq.engine.matchers import MyersSequenceMatcher
from meldq.widgets.sciview import (
    KIND_DELETE,
    KIND_INSERT,
    KIND_REPLACE,
    LIGHT,
    MeldSciView,
)


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
        assert num_panes == 2, "FileDiffView is 2-way for now (3-way in M2)"
        self.num_panes = num_panes
        self.panes = [MeldSciView() for _ in range(num_panes)]
        self._paths = [None] * num_panes
        self._encoding = ["utf-8"] * num_panes      # remembered for write-back
        self._eol = ["\n"] * num_panes
        self._syncing = False
        self._loading = False           # suppress re-diff while loading files

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for view in self.panes:
            view.scrolled.connect(self._on_scrolled)
            view.textChanged.connect(self._on_text_changed)   # live re-diff
            layout.addWidget(view, 1)

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
        self._render()

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

    def set_theme(self, theme):
        for view in self.panes:
            view.apply_theme(theme)

    # ----- rendering --------------------------------------------------------

    def _pane_lines(self, i):
        return self.panes[i].text().split("\n")

    def opcodes(self):
        return MyersSequenceMatcher(
            None, self._pane_lines(0), self._pane_lines(1)
        ).get_difference_opcodes()

    def _render(self):
        for view in self.panes:
            view.clear_chunks()
            view.clear_inline()
        left, right = self.panes
        left_lines, right_lines = self._pane_lines(0), self._pane_lines(1)
        for tag, l1, l2, r1, r2 in MyersSequenceMatcher(
                None, left_lines, right_lines).get_difference_opcodes():
            if tag == "delete":
                left.add_chunk(l1, l2, KIND_DELETE)
            elif tag == "insert":
                right.add_chunk(r1, r2, KIND_INSERT)
            elif tag == "replace":
                left.add_chunk(l1, l2, KIND_REPLACE)
                right.add_chunk(r1, r2, KIND_REPLACE)
                self._inline_replace(left_lines, right_lines, l1, l2, r1, r2)

    def _on_text_changed(self):
        # Synchronous full re-diff. Correct + deterministic; M2 swaps in the
        # Differ's incremental change_sequence when large-file perf matters.
        if self._loading:
            return
        self._render()

    def _inline_replace(self, left_lines, right_lines, l1, l2, r1, r2):
        # Skeleton inline: only equal-height replaces get intra-line marks;
        # M2 does the full joined-region InlineMyers pass like 3.24.
        if (l2 - l1) != (r2 - r1):
            return
        for k in range(l2 - l1):
            self._inline_line_pair(l1 + k, left_lines[l1 + k],
                                   r1 + k, right_lines[r1 + k])

    def _inline_line_pair(self, left_line, left_text, right_line, right_text):
        sm = difflib.SequenceMatcher(None, left_text, right_text, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            if i2 > i1:
                self.panes[0].add_inline(left_line, i1, i2)
            if j2 > j1:
                self.panes[1].add_inline(right_line, j1, j2)

    # ----- merge ------------------------------------------------------------

    @staticmethod
    def _pane_range(chunk, pane):
        _tag, l1, l2, r1, r2 = chunk
        return (l1, l2) if pane == 0 else (r1, r2)

    def chunk_at_line(self, pane, line):
        """The change covering `line` in `pane`, or None. Zero-width chunks
        (an insert has no line on the opposite pane) match at their position."""
        for chunk in self.opcodes():
            lo, hi = self._pane_range(chunk, pane)
            if lo <= line < hi or (lo == hi and line == lo):
                return chunk
        return None

    def copy_chunk(self, chunk, src_pane, dst_pane):
        """Replace dst_pane's side of `chunk` with src_pane's lines (undoable)."""
        src_lo, src_hi = self._pane_range(chunk, src_pane)
        dst_lo, dst_hi = self._pane_range(chunk, dst_pane)
        src_lines = self._pane_lines(src_pane)
        dst_lines = self._pane_lines(dst_pane)
        seg = src_lines[src_lo:src_hi]
        new_dst = dst_lines[:dst_lo] + seg + dst_lines[dst_hi:]
        self.panes[dst_pane].replace_all_text("\n".join(new_dst))

    def delete_chunk(self, chunk, pane):
        """Remove pane's side of `chunk` (undoable)."""
        lo, hi = self._pane_range(chunk, pane)
        lines = self._pane_lines(pane)
        self.panes[pane].replace_all_text("\n".join(lines[:lo] + lines[hi:]))

    # ----- sync scroll ------------------------------------------------------

    def _on_scrolled(self):
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
    """Minimal runner: `python -m meldq.views.filediff A B` opens a diff window."""
    import sys

    from PyQt6.QtWidgets import QApplication

    argv = list(sys.argv if argv is None else argv)
    files = argv[1:3]
    app = QApplication(argv[:1])
    view = FileDiffView(2)
    view.set_theme(LIGHT)
    view.resize(900, 600)
    if len(files) == 2:
        view.set_files(files)
    view.setWindowTitle("meldq — %s : %s" % tuple(files) if len(files) == 2
                        else "meldq")
    view.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
