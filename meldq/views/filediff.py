"""FileDiffView — the fresh 2-way text comparison view (milestone M1).

The walking skeleton: two MeldSciView panes driven by the 3.24-aligned Myers
matcher, painting chunk backgrounds + inline highlights, with basic sync-scroll.
View-only for now; editing, 3-way, merge (via the Differ), the ActionGutter and
the LinkMap land in M2. Kept separate from the 1.4-era meldq/filediff.py, which
remains as reference until it is retired.
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


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


class FileDiffView(QWidget):
    def __init__(self, num_panes=2, parent=None):
        super().__init__(parent)
        assert num_panes == 2, "M1 FileDiffView is 2-way only"
        self.num_panes = num_panes
        self.panes = [MeldSciView() for _ in range(num_panes)]
        self._paths = [None] * num_panes
        self._lines = [[], []]
        self._syncing = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for view in self.panes:
            view.setReadOnly(True)          # view-only skeleton
            view.scrolled.connect(self._on_scrolled)
            layout.addWidget(view, 1)

    # ----- loading ----------------------------------------------------------

    def set_files(self, paths):
        self.set_texts([read_text(p) for p in paths], paths)

    def set_texts(self, texts, paths=None):
        paths = paths or [None] * len(texts)
        for i, view in enumerate(self.panes):
            text = texts[i] if i < len(texts) else ""
            view.set_language_for(paths[i] if i < len(paths) else None)
            view.set_text(text)
            self._paths[i] = paths[i] if i < len(paths) else None
            self._lines[i] = text.split("\n")
        self._render()

    def set_theme(self, theme):
        for view in self.panes:
            view.apply_theme(theme)

    # ----- rendering --------------------------------------------------------

    def opcodes(self):
        return MyersSequenceMatcher(
            None, self._lines[0], self._lines[1]).get_difference_opcodes()

    def _render(self):
        for view in self.panes:
            view.clear_chunks()
            view.clear_inline()
        left, right = self.panes
        for tag, l1, l2, r1, r2 in self.opcodes():
            if tag == "delete":
                left.add_chunk(l1, l2, KIND_DELETE)
            elif tag == "insert":
                right.add_chunk(r1, r2, KIND_INSERT)
            elif tag == "replace":
                left.add_chunk(l1, l2, KIND_REPLACE)
                right.add_chunk(r1, r2, KIND_REPLACE)
                self._inline_replace(l1, l2, r1, r2)

    def _inline_replace(self, l1, l2, r1, r2):
        # Skeleton inline: only equal-height replaces get intra-line marks;
        # M2 does the full joined-region InlineMyers pass like 3.24.
        if (l2 - l1) != (r2 - r1):
            return
        for k in range(l2 - l1):
            self._inline_line_pair(l1 + k, self._lines[0][l1 + k],
                                   r1 + k, self._lines[1][r1 + k])

    def _inline_line_pair(self, left_line, left_text, right_line, right_text):
        sm = difflib.SequenceMatcher(None, left_text, right_text, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            if i2 > i1:
                self.panes[0].add_inline(left_line, i1, i2)
            if j2 > j1:
                self.panes[1].add_inline(right_line, j1, j2)

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
