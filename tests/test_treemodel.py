from PyQt6.QtCore import Qt

from meldq.widgets import treemodel as tm
from meldq.widgets.treemodel import (
    STATE_EMPTY,
    STATE_ERROR,
    STATE_MISSING,
    STATE_MODIFIED,
    STATE_NEW,
    DiffTreeModel,
)


def test_state_constants_verbatim():
    assert (tm.STATE_IGNORED, tm.STATE_NONE, tm.STATE_NORMAL, tm.STATE_NOCHANGE,
            tm.STATE_ERROR, tm.STATE_EMPTY, tm.STATE_NEW, tm.STATE_MODIFIED,
            tm.STATE_CONFLICT, tm.STATE_REMOVED, tm.STATE_MISSING, tm.STATE_MAX) \
        == tuple(range(12))


def test_add_entries_and_paths(qapp):
    model = DiffTreeModel(ntree=3)
    idx = model.add_entries(None, ["/a/x", None, "/c/x"])
    assert model.value_paths(idx) == ["/a/x", None, "/c/x"]


def test_set_state_styles(qapp):
    model = DiffTreeModel(ntree=3)
    idx = model.add_entries(None, ["/a/file.py", None, None])
    model.set_state(idx, 0, STATE_MODIFIED, isdir=False)
    assert model.get_state(idx, 0) == STATE_MODIFIED
    sib0 = idx.siblingAtColumn(0)
    assert model.data(sib0, Qt.ItemDataRole.ForegroundRole).color().name() == "#880000"
    assert model.data(sib0, Qt.ItemDataRole.FontRole).bold() is True
    assert model.data(sib0, Qt.ItemDataRole.DisplayRole) == "file.py"
    icon = model.data(sib0, Qt.ItemDataRole.DecorationRole)
    assert icon is not None and not icon.isNull()


def test_error_state_has_no_icon(qapp):
    model = DiffTreeModel(ntree=3)
    idx = model.add_error(None, "boom", 1)
    assert model.get_state(idx, 1) == STATE_ERROR
    sib1 = idx.siblingAtColumn(1)
    assert model.data(sib1, Qt.ItemDataRole.DecorationRole) is None
    assert model.data(sib1, Qt.ItemDataRole.DisplayRole) == "boom"


def test_add_empty_path_is_none(qapp):
    # regression for tree.py:88 which stored a pixstyle tuple in COL_PATH
    model = DiffTreeModel(ntree=3)
    idx = model.add_empty(None)
    assert model.value_path(idx, 0) is None
    assert model.get_state(idx, 0) == STATE_EMPTY
    assert model.data(idx.siblingAtColumn(0), Qt.ItemDataRole.DisplayRole) == "empty folder"


def test_new_state_icon_present(qapp):
    model = DiffTreeModel(ntree=3)
    idx = model.add_entries(None, ["/a/n", None, None])
    model.set_state(idx, 0, STATE_NEW)
    icon = model.data(idx.siblingAtColumn(0), Qt.ItemDataRole.DecorationRole)
    assert icon is not None and not icon.isNull()


def test_instance_style_override(qapp):
    m1 = DiffTreeModel(ntree=1)
    m2 = DiffTreeModel(ntree=1)
    m2.text_styles[STATE_MISSING] = tm.TextStyle(fg="#000088", bold=True, strikethrough=True)
    for model in (m1, m2):
        idx = model.add_entries(None, ["/a/x"])
        model.set_state(idx, 0, STATE_MISSING)
    c1 = m1.data(m1.index(0, 0), Qt.ItemDataRole.ForegroundRole).color().name()
    c2 = m2.data(m2.index(0, 0), Qt.ItemDataRole.ForegroundRole).color().name()
    assert c1 == "#888888"
    assert c2 == "#000088"


def test_extra_columns_are_plain(qapp):
    model = DiffTreeModel(ntree=1, extra_cols=2)
    assert model.columnCount() == 3
    idx = model.add_entries(None, ["/a/x"])
    # extra columns carry no state styling
    extra = idx.siblingAtColumn(1)
    assert model.data(extra, Qt.ItemDataRole.FontRole) is None


def _fixture_tree():
    # A(A0, A1(A1a)), B, C(C0)
    model = DiffTreeModel(ntree=1)
    a = model.add_entries(None, ["A"])
    model.add_entries(a, ["A0"])
    a1 = model.add_entries(a, ["A1"])
    model.add_entries(a1, ["A1a"])
    model.add_entries(None, ["B"])
    c = model.add_entries(None, ["C"])
    model.add_entries(c, ["C0"])
    return model, a


def test_search_down_terminates(qapp):
    model, a = _fixture_tree()
    order = [model.rowpath(i) for i in model.inorder_search_down(a)]
    assert order == [(0, 0), (0, 1), (0, 1, 0), (1,), (2,), (2, 0)]


def test_search_up_terminates(qapp):
    model, _ = _fixture_tree()
    c0 = model.index_for_rowpath((2, 0))
    order = [model.rowpath(i) for i in model.inorder_search_up(c0)]
    assert order == [(2,), (1,), (0, 1, 0), (0, 1), (0, 0), (0,)]


def test_rowpath_roundtrip(qapp):
    model, _ = _fixture_tree()
    for rp in [(0,), (0, 0), (0, 1), (0, 1, 0), (1,), (2,), (2, 0)]:
        idx = model.index_for_rowpath(rp)
        assert idx.isValid()
        assert model.rowpath(idx) == rp
    assert not model.index_for_rowpath((9, 9)).isValid()
