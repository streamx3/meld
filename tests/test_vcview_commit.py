import os

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QShortcut
from PyQt6.QtWidgets import QDialog

from meldq import vcview
from meldq.util.prefs import Preferences
from meldq.vc import _null


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "history.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def commit_view(qapp, qtbot, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "p.ini"),
                                  QSettings.Format.IniFormat))
    view = vcview.VcView(prefs)
    qtbot.addWidget(view.widget)
    view.vc = _null.Vc(str(tmp_path))
    view._get_selected_files = lambda: [str(tmp_path / "a.txt"),
                                        str(tmp_path / "b.txt")]
    recorded = []
    view._command_on_selected = lambda cmd: recorded.append(cmd)
    return view, recorded


def test_texts_and_changed_files_summary(commit_view, settings, tmp_path):
    view, _ = commit_view
    dlg = vcview.CommitDialog(view, settings=settings)
    assert dlg.windowTitle() == "VC Log"
    assert dlg.groupbox_files.title() == "Commit Files"
    assert dlg.groupbox_message.title() == "Log Message"
    assert dlg.previouslogs_label.text() == "Previous Logs"
    # "(in <commonprefix>) <name> <name>" with the prefix stripped from each.
    summary = dlg.changedfiles.text()
    assert summary.startswith("(in %s) " % str(tmp_path))
    assert "a.txt" in summary and "b.txt" in summary


def test_previous_entry_readonly(commit_view, settings):
    view, _ = commit_view
    dlg = vcview.CommitDialog(view, settings=settings)
    assert dlg.previousentry.lineEdit().isReadOnly()   # picker, no typing


def test_ctrl_return_and_enter_accept(commit_view, settings):
    view, _ = commit_view
    dlg = vcview.CommitDialog(view, settings=settings)
    shortcuts = {s.key().toString() for s in dlg.findChildren(QShortcut)}
    assert {"Ctrl+Return", "Ctrl+Enter"} <= shortcuts
    accepted = []
    dlg.accepted.connect(lambda: accepted.append(True))
    ctrl_return = next(s for s in dlg.findChildren(QShortcut)
                       if s.key().toString() == "Ctrl+Return")
    ctrl_return.activated.emit()          # emulate the shortcut firing
    assert accepted == [True]


def test_run_accept_records_commit_command(commit_view, settings, monkeypatch):
    view, recorded = commit_view
    dlg = vcview.CommitDialog(view, settings=settings)
    dlg.textview.setPlainText("commit message here")
    monkeypatch.setattr(dlg, "exec", lambda: QDialog.DialogCode.Accepted)
    dlg.run()
    assert recorded == [["true", "commit", "-m", "commit message here"]]


def test_run_cancel_does_not_commit_but_keeps_history(commit_view, settings,
                                                       monkeypatch):
    view, recorded = commit_view
    dlg = vcview.CommitDialog(view, settings=settings)
    dlg.textview.setPlainText("drafted then cancelled")
    monkeypatch.setattr(dlg, "exec", lambda: QDialog.DialogCode.Rejected)
    dlg.run()
    assert recorded == []                 # nothing committed
    # ...but the drafted message is still remembered (1.4 behavior).
    dlg2 = vcview.CommitDialog(view, settings=settings)
    assert dlg2.previousentry.itemText(0) == "drafted then cancelled"


def test_history_persists_and_preloads(commit_view, settings, monkeypatch):
    view, _ = commit_view
    dlg = vcview.CommitDialog(view, settings=settings)
    dlg.textview.setPlainText("a remembered message")
    monkeypatch.setattr(dlg, "exec", lambda: QDialog.DialogCode.Accepted)
    dlg.run()

    dlg2 = vcview.CommitDialog(view, settings=settings)
    assert dlg2.previousentry.itemText(0) == "a remembered message"
    # selecting index 0 preloads it into the message box
    dlg2.previousentry.setCurrentIndex(0)
    dlg2.previousentry.activated.emit(0)
    assert dlg2.textview.toPlainText() == "a remembered message"


def test_on_button_commit_opens_dialog(commit_view, monkeypatch):
    view, _ = commit_view
    calls = []

    class FakeDialog:
        def __init__(self, parent):
            calls.append(("init", parent))

        def run(self):
            calls.append("run")

    monkeypatch.setattr(vcview, "CommitDialog", FakeDialog)
    view.on_button_commit_clicked()
    assert calls == [("init", view), "run"]
