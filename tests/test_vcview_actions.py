import pytest

from meldq import vcview
from meldq.util.prefs import Preferences
from meldq.vc import git, svn


@pytest.fixture
def view(qapp, qtbot):
    v = vcview.VcView(Preferences())
    qtbot.addWidget(v.widget)
    return v


def test_fifteen_doc_actions(view):
    actions = view.doc_actions()
    # Identity, not just count, so a drop+duplicate can't slip through.
    assert actions == [
        view.action_compare, view.action_open, view.action_commit,
        view.action_update, view.action_add, view.action_add_binary,
        view.action_remove, view.action_resolved, view.action_revert,
        view.action_delete_locally, view.action_flatten,
        view.action_filter_modified, view.action_filter_normal,
        view.action_filter_nonvc, view.action_filter_ignored]


def test_view_menu_contribution(view):
    view_menu = view.menu_contributions()["view"]
    assert view_menu[0] is view.action_flatten
    submenu = view_menu[1].menu()      # the "Version status" QMenu
    assert "Version status" in submenu.title()
    checkable = [a for a in submenu.actions() if a.isCheckable()]
    assert checkable == [view.action_filter_modified, view.action_filter_normal,
                         view.action_filter_nonvc, view.action_filter_ignored]


def test_toolbar_separator_positions(view):
    tb = view.toolbar_contributions()
    assert len(tb) == 15
    assert tb[1].isSeparator()
    assert tb[9].isSeparator()
    assert tb[0] is view.action_compare
    assert tb[10] is view.action_flatten


def test_sensitivity_git_disables_resolved(view):
    # git.py defines no resolved_command -> action disabled; the others map to
    # implemented builders and stay enabled.
    view.vc = git.Vc.__new__(git.Vc)
    view.update_actions_sensitivity()
    assert view.action_resolved.isEnabled() is False
    assert view.action_update.isEnabled() is True
    assert view.action_commit.isEnabled() is True
    assert view.action_add.isEnabled() is True
    assert view.action_revert.isEnabled() is True


def test_sensitivity_svn_enables_all(view):
    view.vc = svn.Vc.__new__(svn.Vc)
    view.update_actions_sensitivity()
    for action in (view.action_compare, view.action_commit, view.action_update,
                   view.action_add, view.action_resolved, view.action_remove,
                   view.action_revert):
        assert action.isEnabled() is True
