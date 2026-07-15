"""InfoBar banner behaviour."""

import pytest

from meldq.widgets.infobar import InfoBar


@pytest.fixture
def bar(qapp, qtbot):
    b = InfoBar()               # manages its own visibility; don't force show()
    qtbot.addWidget(b)
    return b


def test_hidden_by_default(bar):
    assert not bar.isVisible()
    assert bar.message is None


def test_show_message(bar):
    bar.show_message("file changed")
    assert bar.isVisible()
    assert bar.message == "file changed"


def test_button_invokes_callback_and_dismisses(bar):
    fired = []
    bar.show_message("changed", [("Reload", lambda: fired.append("reload")),
                                 ("Ignore", None)])
    # click the first button
    bar._buttons[0].click()
    assert fired == ["reload"]
    assert not bar.isVisible()          # dismissed after action
    assert bar.message is None


def test_clear(bar):
    bar.show_message("x", [("Ok", None)])
    bar.clear()
    assert not bar.isVisible()
    assert bar._buttons == []


def test_second_message_replaces_first(bar):
    bar.show_message("first", [("A", None)])
    bar.show_message("second", [("B", None), ("C", None)])
    assert bar.message == "second"
    assert len(bar._buttons) == 2
