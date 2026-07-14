import pytest
from PyQt6.QtCore import QSettings

from meldq.diffmap import DiffMap
from meldq.filediff import FileDiff
from meldq.linkmap import LinkMap
from meldq.util.prefs import Preferences
from meldq.widgets.editor import DiffTextEdit


@pytest.fixture
def prefs(tmp_path):
    return Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))


def test_widget_hierarchy(qapp, prefs):
    doc = FileDiff(prefs, 2)
    assert len(doc.widget.findChildren(DiffTextEdit)) == 3
    assert len(doc.widget.findChildren(LinkMap)) == 2
    assert len(doc.widget.findChildren(DiffMap)) == 2
    assert doc.num_panes == 2


def test_set_num_panes_show_hide(qapp, qtbot, prefs):
    doc = FileDiff(prefs, 2)
    qtbot.addWidget(doc.widget)
    # in 2-pane mode, pane 2 and linkmap1 are hidden
    assert not doc.vbox[2].isVisibleTo(doc.widget)
    assert not doc.linkmap[1].isVisibleTo(doc.widget)
    doc.set_num_panes(3)
    assert doc.vbox[2].isVisibleTo(doc.widget)
    assert doc.linkmap[1].isVisibleTo(doc.widget)
    doc.set_num_panes(2)
    assert not doc.vbox[2].isVisibleTo(doc.widget)


def test_colors_share_delete(qapp, prefs):
    doc = FileDiff(prefs, 2)
    assert doc.fill_colors["insert"] == doc.fill_colors["delete"]
    # line colors are darker than fills
    assert doc.line_colors["replace"].value() < doc.fill_colors["replace"].value()


def test_label_changed_emitted(qapp, qtbot, prefs):
    doc = FileDiff(prefs, 2)
    with qtbot.waitSignal(doc.label_changed) as blocker:
        doc.set_labels(["a", "b"])
        doc.recompute_label()
    assert blocker.args == ["a : b"]


def test_documents_registered_with_undo(qapp, prefs):
    doc = FileDiff(prefs, 2)
    # all three pane documents are registered with the undo coordinator
    assert len(doc.undosequence._docs) == 3


def test_regexes_compiled(qapp, prefs):
    doc = FileDiff(prefs, 2)
    # default prefs include some active regexes; none should raise
    assert isinstance(doc.regexes, list)
