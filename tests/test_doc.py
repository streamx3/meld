import pytest
from PyQt6.QtCore import QSettings

from meldq.doc import CloseResponse, Direction, MeldDoc
from meldq.util.prefs import Preferences


@pytest.fixture
def prefs(tmp_path):
    return Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))


def test_signal_signatures(qapp, prefs):
    doc = MeldDoc(prefs)
    got = {}
    doc.label_changed.connect(lambda s: got.setdefault("label", s))
    doc.create_diff.connect(lambda lst: got.setdefault("diff", lst))
    doc.next_diff_changed.connect(lambda a, b: got.setdefault("nav", (a, b)))
    doc.label_changed.emit("hello")
    doc.create_diff.emit(["a", "b"])
    doc.next_diff_changed.emit(True, False)
    assert got == {"label": "hello", "diff": ["a", "b"], "nav": (True, False)}


def test_close_response(qapp, prefs):
    doc = MeldDoc(prefs)
    assert doc.on_delete_event() == CloseResponse.OK
    assert CloseResponse.CANCEL != CloseResponse.OK
    assert Direction.DOWN == 1 and Direction.UP == -1


def test_stop_removes_current_task(qapp, prefs):
    doc = MeldDoc(prefs)
    def gen():
        while True:
            yield 1
    doc.scheduler.add_task(gen())
    assert doc.scheduler.tasks_pending()
    doc.stop()
    assert not doc.scheduler.tasks_pending()


def test_preference_change_delivers_key_name(qapp, prefs):
    seen = []

    class RecordingDoc(MeldDoc):
        def on_preference_changed(self, key):
            seen.append(key)

    doc = RecordingDoc(prefs)       # keep a reference so the connection survives
    prefs.tab_size = 8
    assert seen == ["tab_size"]
    assert doc is not None


def test_open_files_custom_editor(qapp, prefs, monkeypatch):
    prefs.edit_command_type = "custom"
    prefs.edit_command_custom = "echo"
    recorded = {}
    monkeypatch.setattr("subprocess.Popen", lambda argv, *a, **k: recorded.setdefault("argv", argv))
    doc = MeldDoc(prefs)
    doc._open_files([__file__])
    assert recorded["argv"] == ["echo", __file__]
