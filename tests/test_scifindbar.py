"""Find/replace bar for the QScintilla panes (meldq.widgets.scifindbar)."""

import pytest

from meldq.views.filediff import FileDiffView


@pytest.fixture
def fd(qapp, qtbot):
    view = FileDiffView(2)
    qtbot.addWidget(view)
    view.set_texts(["alpha\nbeta\ngamma\nBeta\n", "alpha\nbeta\ngamma\nBeta\n"])
    return view


def sel(editor):
    return editor.selectedText()


def test_show_find_bar_targets_focused_pane(fd):
    assert not fd.findbar.isVisibleTo(fd)
    fd.show_find_bar()
    assert fd.findbar.isVisibleTo(fd)


def test_find_next_selects_and_wraps(fd):
    fd.show_find_bar()
    fd.findbar.entry.setText("beta")
    assert fd.findbar.find_next()
    assert sel(fd.panes[0]) in ("beta", "Beta")     # case-insensitive default
    first = fd.panes[0].getSelection()
    assert fd.findbar.find_next()                   # second match
    assert fd.findbar.find_next()                   # wraps back around
    assert fd.panes[0].getSelection() == first


def test_case_sensitive_toggle(fd):
    fd.show_find_bar()
    fd.findbar.entry.setText("Beta")
    fd.findbar.case_box.setChecked(True)
    assert fd.findbar.find_next()
    assert sel(fd.panes[0]) == "Beta"               # exact-case match only
    line, _c, _l2, _c2 = fd.panes[0].getSelection()
    assert line == 3                                # the capitalised one


def test_find_miss_flags_entry(fd):
    fd.show_find_bar()
    fd.findbar.entry.setText("nonexistent")
    assert not fd.findbar.find_next()
    assert "background" in fd.findbar.entry.styleSheet()


def test_replace_one(fd):
    fd.show_find_bar()
    fd.findbar.entry.setText("beta")
    fd.findbar.case_box.setChecked(True)
    fd.findbar.replace_entry.setText("BETA")
    fd.findbar.replace_one()
    assert "BETA" in fd.panes[0].text()
    assert fd.panes[0].text().count("beta") == 0    # the lone lowercase replaced


def test_replace_all(fd):
    fd.show_find_bar()
    fd.findbar.entry.setText("a")
    fd.findbar.replace_entry.setText("_")
    fd.findbar.replace_all()
    assert "a" not in fd.panes[0].text().replace("gamma", "")  # all 'a's gone
    fd.panes[0].undo()                              # one undo step
    assert fd.panes[0].text().startswith("alpha")


def test_replace_all_growing_needle_terminates(fd):
    # Replacement containing the needle must not loop forever.
    fd.panes[0].set_text("x\nx\n")
    fd.findbar.attach(fd.panes[0])
    fd.findbar.entry.setText("x")
    fd.findbar.replace_entry.setText("xx")
    fd.findbar.replace_all()                        # must terminate
    assert fd.panes[0].text() == "xx\nxx\n"


def test_replace_readonly_pane_noop(fd):
    fd.panes[0].setReadOnly(True)
    fd.findbar.attach(fd.panes[0])
    fd.findbar.entry.setText("beta")
    fd.findbar.replace_entry.setText("nope")
    before = fd.panes[0].text()
    fd.findbar.replace_all()
    assert fd.panes[0].text() == before


def test_escape_hides_bar(fd):
    fd.show_find_bar()
    fd.findbar.hide_bar()
    assert not fd.findbar.isVisibleTo(fd)


def test_shell_ctrl_f_shows_bar(qapp, qtbot, tmp_path):
    from PyQt6.QtCore import QSettings

    from meldq.shell import MeldWindow
    from meldq.util.prefs import Preferences
    prefs = Preferences(
        QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    win = MeldWindow(prefs)
    qtbot.addWidget(win)
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("one\n")
    b.write_text("two\n")
    view = win.append_filediff([str(a), str(b)])
    win.on_find()
    assert view.findbar.isVisibleTo(view)
