import pytest
from PyQt6.QtWidgets import QApplication

from meldq import vcview
from meldq.util.prefs import Preferences
from meldq.vc import _null


@pytest.fixture
def view(qapp, qtbot):
    v = vcview.VcView(Preferences())
    qtbot.addWidget(v.widget)
    return v


def _run_to_result(gen, limit=5000):
    for _ in range(limit):
        try:
            val = next(gen)
        except StopIteration:
            return None
        if isinstance(val, tuple):
            return val
    return None


def test_command_iter_streams_and_returns(view, tmp_path):
    view.vc = _null.Vc(str(tmp_path))
    view.label_text = "repo"
    gen = view._command_iter(["sh", "-c", "echo hello"], [str(tmp_path)], False)
    result = _run_to_result(gen)
    assert result is not None
    workdir, output = result
    assert output == "hello\n"
    console = view.consoleview.toPlainText()
    assert "hello" in console
    assert "echo" in console          # the shelljoined command line was echoed


def test_command_iter_failure_uses_msgarea_not_modal(view, tmp_path):
    view.vc = _null.Vc(str(tmp_path))
    view.label_text = "repo"
    gen = view._command_iter(
        ["definitely-missing-binary-xyz"], [str(tmp_path)], False)
    _run_to_result(gen)                # drains the generator to completion
    # The failure surfaces as a non-modal message area, never a modal dialog
    # (a modal would re-enter the pump and re-enter this generator).
    assert view.msgarea.has_message()
    assert QApplication.activeModalWidget() is None


def test_command_on_selected_empty_selection_warns(view, tmp_path, monkeypatch):
    view.vc = _null.Vc(str(tmp_path))
    view.set_location(str(tmp_path))
    view.treeview.clearSelection()
    infos = []
    monkeypatch.setattr(vcview.QMessageBox, "information",
                        lambda *a, **k: infos.append(a))
    scheduled = []
    monkeypatch.setattr(view, "_command", lambda *a, **k: scheduled.append(a))
    view._command_on_selected(["true", "add"])
    assert len(infos) == 1        # "Select some files first."
    assert scheduled == []        # nothing dispatched
