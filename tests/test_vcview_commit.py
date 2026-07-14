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
    # Both shortcuts must exist AND each must actually reach accept().
    for keyname in ("Ctrl+Return", "Ctrl+Enter"):
        dlg = vcview.CommitDialog(view, settings=settings)
        shortcuts = {s.key().toString() for s in dlg.findChildren(QShortcut)}
        assert {"Ctrl+Return", "Ctrl+Enter"} <= shortcuts
        accepted = []
        dlg.accepted.connect(lambda: accepted.append(True))
        sc = next(s for s in dlg.findChildren(QShortcut)
                  if s.key().toString() == keyname)
        sc.activated.emit()               # emulate the shortcut firing
        assert accepted == [True], keyname


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


def test_history_persists_and_preloads(commit_view, settings, tmp_path,
                                       monkeypatch):
    view, _ = commit_view
    dlg = vcview.CommitDialog(view, settings=settings)
    dlg.textview.setPlainText("a remembered message")
    monkeypatch.setattr(dlg, "exec", lambda: QDialog.DialogCode.Accepted)
    dlg.run()
    settings.sync()      # flush to disk

    # A FRESH QSettings reading the same INI proves on-disk persistence, not
    # just in-memory sharing of one object.
    fresh = QSettings(str(tmp_path / "history.ini"), QSettings.Format.IniFormat)
    dlg2 = vcview.CommitDialog(view, settings=fresh)
    assert dlg2.previousentry.itemText(0) == "a remembered message"
    assert dlg2.textview.toPlainText() == ""     # NOT preloaded at construction
    # selecting index 0 is what preloads it into the message box
    dlg2.previousentry.setCurrentIndex(0)
    dlg2.previousentry.activated.emit(0)
    assert dlg2.textview.toPlainText() == "a remembered message"


def test_short_message_commits_but_is_not_remembered(commit_view, settings,
                                                     monkeypatch):
    # HistoryCombo only stores messages LONGER than 3 chars (MIN_ITEM_LEN); a
    # short commit still commits but leaves no history entry.
    view, recorded = commit_view
    dlg = vcview.CommitDialog(view, settings=settings)
    dlg.textview.setPlainText("abc")             # <= 3 chars
    monkeypatch.setattr(dlg, "exec", lambda: QDialog.DialogCode.Accepted)
    dlg.run()
    assert recorded == [["true", "commit", "-m", "abc"]]   # still commits
    dlg2 = vcview.CommitDialog(view, settings=settings)
    assert dlg2.previousentry.count() == 0                  # nothing remembered


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
