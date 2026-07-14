from meldq.conf import _
from meldq.util.misc import gtk_mnemonic_to_qt
from meldq.widgets.msgarea import MsgArea, MsgAreaController, ResponseId


def test_response_signal(qapp, qtbot):
    controller = MsgAreaController()
    area = controller.new_from_text_and_icon("dialog-information",
                                             "Files are identical")
    button = area.add_stock_button_with_text(
        gtk_mnemonic_to_qt(_("Hi_de")), "window-close", ResponseId.CLOSE)
    with qtbot.waitSignal(area.response) as blocker:
        button.click()
    assert blocker.args == [-7]


def test_button_for_response_regression(qapp):
    # the 1.4 __find_button raised AttributeError on ANY call (msgarea.py:72)
    area = MsgArea()
    area.add_button("Cancel", ResponseId.CANCEL)
    area.add_button("Close", ResponseId.CLOSE)
    assert area.button_for_response(ResponseId.CANCEL) is not None
    assert area.button_for_response(ResponseId.CLOSE) is not None
    assert area.button_for_response(999) is None


def test_controller_lifecycle(qapp):
    controller = MsgAreaController()
    assert not controller.has_message()
    controller.new_from_text_and_icon("dialog-warning", "careful")
    controller.set_msg_id("mymsg")
    assert controller.has_message()
    assert controller.get_msg_id() == "mymsg"
    controller.clear()
    assert not controller.has_message()
    assert controller.get_msg_id() is None


def test_no_shared_buttons_default(qapp):
    # mutable-default regression (msgarea.py:242)
    controller = MsgAreaController()
    controller.new_from_text_and_icon("dialog-information", "first")
    second = controller.new_from_text_and_icon("dialog-information", "second")
    assert len(second._buttons) == 0


def test_markup_escaped(qapp):
    area = MsgArea()
    area.set_text_and_icon("dialog-information", "a <b> & c")
    labels = area.findChildren(type(area._make_label("")))
    texts = [label.text() for label in labels]
    assert any("&lt;b&gt;" in t and "&amp;" in t for t in texts)


def test_response_sensitive(qapp):
    area = MsgArea()
    area.add_button("Close", ResponseId.CLOSE)
    area.set_response_sensitive(ResponseId.CLOSE, False)
    assert not area.button_for_response(ResponseId.CLOSE).isEnabled()
    area.set_response_sensitive(999, False)      # unknown respid: silent no-op
