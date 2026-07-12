"""S2 gate spike: three QTreeViews sharing one QStandardItemModel.

Validates the dirdiff/vcview model design: one model with one column per
pane, three views each showing only its own column via setTreePosition +
hidden siblings, expansion and selection mirrored across views.

Run interactively:      python spikes/s2_tree.py
Run the PASS harness:   python spikes/s2_tree.py --auto [--shots DIR]
"""

import json
import os
import sys

if "--auto" in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QItemSelectionModel, Qt
from PyQt6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QTreeView, QWidget

NPANES = 3
STATE_COLORS = {0: None, 1: QColor(200, 60, 60), 2: QColor(60, 140, 60)}


def build_model():
    """3 columns; 25 top rows x 4 children x 4 grandchildren = 525 rows."""
    model = QStandardItemModel(0, NPANES)
    model.setHorizontalHeaderLabels([f"pane {i}" for i in range(NPANES)])
    for i in range(25):
        top = [QStandardItem(f"dir-{i} (pane {p})") for p in range(NPANES)]
        for j in range(4):
            mid = [QStandardItem(f"dir-{i}/sub-{j} (pane {p})") for p in range(NPANES)]
            for k in range(4):
                leaf = [QStandardItem(f"dir-{i}/sub-{j}/file-{k} (pane {p})")
                        for p in range(NPANES)]
                state = (i + j + k) % 3
                if STATE_COLORS[state] is not None:
                    for item in leaf:
                        item.setForeground(QBrush(STATE_COLORS[state]))
                mid[0].appendRow(leaf)
            top[0].appendRow(mid)
        model.appendRow(top)
    return model


class SpikeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.model = build_model()
        self.views = []
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        for pane in range(NPANES):
            view = QTreeView()
            view.setModel(self.model)
            view.setTreePosition(pane)
            for col in range(NPANES):
                view.setColumnHidden(col, col != pane)
            view.setHeaderHidden(False)
            view.expanded.connect(lambda idx, p=pane: self._mirror(idx, True))
            view.collapsed.connect(lambda idx, p=pane: self._mirror(idx, False))
            view.selectionModel().currentRowChanged.connect(
                lambda cur, prev: self._mirror_selection(cur))
            layout.addWidget(view)
            self.views.append(view)
        self.setCentralWidget(central)
        self.setWindowTitle("S2 spike")
        self._mirroring = False

    def _mirror(self, index, expand):
        if self._mirroring:
            return
        self._mirroring = True
        try:
            row_index = index.sibling(index.row(), 0)
            for view in self.views:
                if view.isExpanded(row_index) != expand:
                    view.setExpanded(row_index, expand)
        finally:
            self._mirroring = False

    def _mirror_selection(self, current):
        if self._mirroring or not current.isValid():
            return
        self._mirroring = True
        try:
            row_index = current.sibling(current.row(), 0)
            for view in self.views:
                view.selectionModel().setCurrentIndex(
                    row_index,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        finally:
            self._mirroring = False


def run_auto(shots_dir):
    app = QApplication(sys.argv)
    win = SpikeWindow()
    win.resize(1300, 700)
    win.show()
    app.processEvents()
    os.makedirs(shots_dir, exist_ok=True)
    report = {"pass": True, "checks": {}}
    model, views = win.model, win.views

    # expansion mirroring: expand rows on different views, verify all agree
    probes = [(0,), (3,), (3, 1), (7,), (7, 2)]
    for n, path in enumerate(probes):
        idx = model.index(path[0], 0)
        for row in path[1:]:
            idx = model.index(row, 0, idx)
        views[n % NPANES].expand(idx)
    app.processEvents()
    mirrored = all(
        views[a].isExpanded(model.index(p[0], 0)) == views[b].isExpanded(model.index(p[0], 0))
        for p in probes for a in range(NPANES) for b in range(NPANES)
    )
    report["checks"]["expansion_mirrored"] = mirrored
    report["pass"] &= mirrored

    # collapse from view 2, verify view 0 follows
    idx3 = model.index(3, 0)
    views[2].collapse(idx3)
    app.processEvents()
    collapse_ok = not views[0].isExpanded(idx3) and not views[1].isExpanded(idx3)
    report["checks"]["collapse_mirrored"] = collapse_ok
    report["pass"] &= collapse_ok

    # selection mirroring by row
    target = model.index(1, 0, model.index(0, 0, model.index(7, 0)))
    views[1].selectionModel().setCurrentIndex(
        target, QItemSelectionModel.SelectionFlag.ClearAndSelect
        | QItemSelectionModel.SelectionFlag.Rows)
    app.processEvents()
    sel_ok = all(v.selectionModel().currentIndex().row() == target.row()
                 and v.selectionModel().currentIndex().parent() == target.parent()
                 for v in views)
    report["checks"]["selection_mirrored"] = sel_ok
    report["pass"] &= sel_ok

    # no recursion blowups under rapid toggling
    recursion_ok = True
    try:
        for _ in range(50):
            views[0].expand(idx3)
            views[1].collapse(idx3)
    except RecursionError:
        recursion_ok = False
    app.processEvents()
    report["checks"]["no_recursion"] = recursion_ok
    report["pass"] &= recursion_ok

    # hidden columns stay hidden; tree position honored
    cols_ok = all(v.isColumnHidden(c) == (c != p)
                  for p, v in enumerate(views) for c in range(NPANES))
    tree_pos_ok = all(v.treePosition() == p for p, v in enumerate(views))
    report["checks"]["columns_ok"] = cols_ok and tree_pos_ok
    report["pass"] &= cols_ok and tree_pos_ok

    win.grab().save(os.path.join(shots_dir, "s2_three_views.png"))
    report["screenshots"] = ["s2_three_views.png"]
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


def main():
    if "--auto" in sys.argv:
        idx = sys.argv.index("--shots") if "--shots" in sys.argv else -1
        shots = sys.argv[idx + 1] if idx >= 0 else "/tmp/s2_shots"
        sys.exit(run_auto(shots))
    app = QApplication(sys.argv)
    win = SpikeWindow()
    win.resize(1300, 700)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
