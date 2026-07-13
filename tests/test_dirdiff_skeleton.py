import os

import pytest
from PyQt6.QtCore import QSettings

from meldq import dirdiff
from meldq.util.prefs import Preferences


@pytest.fixture
def doc(qapp, qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "p.ini"),
                                  QSettings.Format.IniFormat))
    d = dirdiff.DirDiff(prefs, 2)
    qtbot.addWidget(d.widget)
    return d


def test_initial_two_pane_layout(doc):
    assert doc.num_panes == 2
    assert doc.model.ntree == 2
    assert doc.treeview[0].isVisibleTo(doc.widget)
    assert doc.treeview[1].isVisibleTo(doc.widget)
    assert not doc.treeview[2].isVisibleTo(doc.widget)
    assert sum(fe.isVisibleTo(doc.widget) for fe in doc.fileentry) == 2


def test_column_hiding_per_view(doc):
    # Each view shows only its own pane's column as the tree column.
    for i in range(2):
        assert doc.treeview[i].treePosition() == i
        hidden = [c for c in range(doc.model.columnCount())
                  if doc.treeview[i].isColumnHidden(c)]
        assert hidden == [c for c in range(doc.model.columnCount()) if c != i]


def test_pane_count_switch_visibility(doc, tmp_path):
    # The map-for-side-effect no-op regression (dirdiff.py:863/:866): switching
    # pane counts must actually show/hide the right widgets.
    a = tmp_path / "a"
    a.mkdir()
    for fe in doc.fileentry:
        fe.set_filename(str(a))

    doc.set_num_panes(3)
    assert all(w.isVisibleTo(doc.widget) for w in doc.treeview)
    assert all(w.isVisibleTo(doc.widget) for w in doc.fileentry)
    assert all(w.isVisibleTo(doc.widget) for w in doc.diffmap)
    assert all(w.isVisibleTo(doc.widget) for w in doc.linkmap)

    doc.set_num_panes(1)
    assert doc.treeview[0].isVisibleTo(doc.widget)
    assert not doc.treeview[1].isVisibleTo(doc.widget)
    assert not doc.treeview[2].isVisibleTo(doc.widget)
    assert doc.fileentry[0].isVisibleTo(doc.widget)
    assert not doc.fileentry[1].isVisibleTo(doc.widget)
    assert doc.diffmap[0].isVisibleTo(doc.widget)         # diffmap[:1] shown
    assert not doc.diffmap[1].isVisibleTo(doc.widget)
    assert not doc.linkmap[0].isVisibleTo(doc.widget)     # linkmap[:0] shown


def test_set_locations_root_and_label(doc, tmp_path):
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    doc.set_locations([str(a), str(b)])
    root = doc.model.index(0, 0)
    assert root.isValid()
    assert doc.model.value_paths(root) == [str(a), str(b)]
    assert [os.path.basename(p) for p in doc.model.value_paths(root)] == \
        ["alpha", "beta"]
    assert doc.label_text == "alpha : beta"


def test_selection_signal_rewired_after_model_rebuild(doc, tmp_path):
    # After setModel the view gets a fresh selection model; _set_model must
    # reconnect currentRowChanged, or the status line goes stale after the
    # second comparison (dirdiff.py:858/AC10). Patch the slot before the
    # pane-count switch that rebuilds the model.
    fired = []
    doc.on_treeview_cursor_changed = lambda *a: fired.append(1)
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    doc.set_locations([str(tmp_path / "a"), str(tmp_path / "b"),
                       str(tmp_path / "c")])          # 2 -> 3: model rebuilt
    doc.treeview[0].setCurrentIndex(doc.model.index(0, 0))
    assert fired


def test_filters_compiled_from_prefs(doc):
    # update_regexes / create_name_filters compiled the pref-driven filters
    # (the py3.11 trailing-"(?m)" crash is avoided by re.M).
    import re
    assert all(r.flags & re.MULTILINE for r in doc.regexes)
    assert isinstance(doc.name_filters, list)
