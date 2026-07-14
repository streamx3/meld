import pytest
from PyQt6.QtCore import QSettings

from meldq.widgets.historycombo import HistoryCombo


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "h.ini"), QSettings.Format.IniFormat)


def items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def test_min_item_len(qapp, settings):
    combo = HistoryCombo("test", settings)
    combo.prepend_text("abc")            # len 3, rejected
    assert combo.count() == 0
    combo.prepend_text("abcd")           # len 4, stored
    assert items(combo) == ["abcd"]


def test_dedup_moves_to_top(qapp, settings):
    combo = HistoryCombo("test", settings)
    combo.prepend_text("aaaa")
    combo.prepend_text("bbbb")
    combo.prepend_text("aaaa")
    assert items(combo) == ["aaaa", "bbbb"]


def test_clamp_at_history_length(qapp, settings):
    combo = HistoryCombo("test", settings)
    for i in range(12):
        combo.prepend_text(f"item{i:02d}")
    assert combo.count() == 10
    assert combo.itemText(0) == "item11"    # newest first


def test_persistence_roundtrip(qapp, tmp_path):
    path = str(tmp_path / "h.ini")
    combo = HistoryCombo("test", QSettings(path, QSettings.Format.IniFormat))
    combo.prepend_text("firstitem")
    combo.prepend_text("seconditem")
    reloaded = HistoryCombo("test", QSettings(path, QSettings.Format.IniFormat))
    assert items(reloaded) == ["seconditem", "firstitem"]


def test_single_item_roundtrip(qapp, tmp_path):
    path = str(tmp_path / "h.ini")
    combo = HistoryCombo("solo", QSettings(path, QSettings.Format.IniFormat))
    combo.prepend_text("onlyitem")
    reloaded = HistoryCombo("solo", QSettings(path, QSettings.Format.IniFormat))
    assert items(reloaded) == ["onlyitem"]      # str-vs-list normalization


def test_no_history_id_no_write(qapp, settings):
    combo = HistoryCombo(None, settings)
    combo.prepend_text("something")
    settings.sync()
    assert not settings.allKeys()


def test_prepend_preserves_line_edit(qapp, settings):
    combo = HistoryCombo("test", settings)
    combo.lineEdit().setText("typed text")
    combo.prepend_text("storeditem")
    assert combo.lineEdit().text() == "typed text"


import os

from PyQt6.QtCore import QMimeData, Qt, QUrl
from PyQt6.QtWidgets import QFileDialog

from meldq.widgets.historycombo import FileHistoryCombo, _expand_filename


def test_expand_filename():
    assert _expand_filename("/abs/path", "/base") == "/abs/path"
    assert _expand_filename("~", None) == os.path.expanduser("~")
    assert _expand_filename("rel", "/base") == "/base/rel"
    assert _expand_filename("rel", None) == os.path.join(os.getcwd(), "rel")
    assert _expand_filename("", "/base") == ""


def test_get_full_path_empty_is_none(qapp, settings):
    fhc = FileHistoryCombo("fileentry", settings=settings)
    assert fhc.get_full_path() is None


def test_enter_emits_activated(qapp, qtbot, settings):
    fhc = FileHistoryCombo("fileentry", settings=settings)
    fhc.combo.setEditText("something")
    with qtbot.waitSignal(fhc.activated):
        qtbot.keyClick(fhc.combo.lineEdit(), Qt.Key.Key_Return)


def test_browse_dir_mode_regression(qapp, qtbot, settings, monkeypatch):
    # regression for historyentry.py:314-318 (the setter that never worked)
    calls = {}
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        lambda *a, **k: (calls.setdefault("dir", a), "/chosen/dir")[1])
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (calls.setdefault("file", a), ("/chosen/file", ""))[1])
    fhc = FileHistoryCombo("fileentry", directory_entry=False, settings=settings)
    fhc.set_directory_entry(True)
    with qtbot.waitSignal(fhc.activated):
        fhc._browse_clicked()
    assert "dir" in calls and "file" not in calls
    assert fhc.combo.currentText() == "/chosen/dir"


def test_drop_local_file(qapp, qtbot, settings):
    fhc = FileHistoryCombo("fileentry", settings=settings)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/dropped/file.txt")])

    class FakeEvent:
        def mimeData(self):
            return mime
        def acceptProposedAction(self):
            pass

    with qtbot.waitSignal(fhc.activated):
        fhc.dropEvent(FakeEvent())
    assert fhc.combo.currentText() == "/dropped/file.txt"


def test_set_filename_no_history(qapp, settings):
    fhc = FileHistoryCombo("fileentry", settings=settings)
    before = fhc.combo.count()
    fhc.set_filename("/some/file")
    assert fhc.combo.count() == before
    assert fhc.combo.currentText() == "/some/file"
