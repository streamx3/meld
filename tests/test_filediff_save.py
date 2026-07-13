import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox

from meldq.doc import RESULT_OK, CloseResponse
from meldq.filediff import CloseDialog, FileDiff
from meldq.util.prefs import Preferences


@pytest.fixture
def doc(qapp, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    return FileDiff(prefs, 2)


def load(doc, files):
    doc.set_num_panes(len(files))
    panetext = ["\n"] * len(files)
    for _s in doc._load_files(files, doc.textbuffer, panetext):
        pass
    for i, f in enumerate(files):
        if f:                      # set the filename so save doesn't prompt
            doc.bufferdata[i].filename = doc.bufferdata[i].label = f


def test_crlf_written_back(doc, tmp_path):
    src = tmp_path / "crlf.txt"
    src.write_bytes(b"one\r\ntwo\r\n")
    load(doc, [str(src), None])
    assert doc.bufferdata[0].newlines == "\r\n"
    # edit and save
    doc.textbuffer[0].setPlainText("one\ntwo\nthree")
    assert doc.save_file(0) == RESULT_OK
    assert src.read_bytes() == b"one\r\ntwo\r\nthree"


def test_mixed_newline_prompt(doc, tmp_path, monkeypatch):
    src = tmp_path / "mixed.txt"
    src.write_bytes(b"a\nb\r\n")
    load(doc, [str(src), None])
    assert isinstance(doc.bufferdata[0].newlines, tuple)

    # answer the mixed-newline prompt with the DOS button
    def fake_exec(self):
        for btn in self.buttons():
            if self.buttonRole(btn) == QMessageBox.ButtonRole.ActionRole \
                    and "DOS" in btn.text():
                self._clicked = btn
                return 0
        return 0
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self._clicked)
    doc.save_file(0)
    assert doc.bufferdata[0].newlines == "\r\n"
    assert src.read_bytes() == b"a\r\nb\r\n"


def test_save_as_utf8_fallback(doc, tmp_path, monkeypatch):
    # latin-1 buffer given a euro sign that latin-1 can't encode -> UTF-8
    src = tmp_path / "l1.txt"
    src.write_bytes("abc\n".encode("iso8859-1"))
    doc.prefs.text_codecs = "iso8859_1"
    load(doc, [str(src), None])
    assert doc.bufferdata[0].encoding == "iso8859_1"
    doc.textbuffer[0].setPlainText("abc€")
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert doc.save_file(0) == RESULT_OK
    assert doc.bufferdata[0].encoding == "utf-8"
    assert src.read_bytes().decode("utf-8") == "abc€"


def test_save_clears_modified_star(doc, tmp_path):
    from PyQt6.QtGui import QTextCursor
    src = tmp_path / "f.txt"
    src.write_bytes(b"content\n")
    load(doc, [str(src), None])       # checkpoints doc 0 (unmodified)
    cur = QTextCursor(doc.textbuffer[0])
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText("more")            # undoCommandAdded -> modified via checkpointed
    assert doc.bufferdata[0].modified
    doc.save_file(0)
    assert not doc.bufferdata[0].modified


def test_close_dialog_disables_unmodified(qapp, doc):
    dialog = CloseDialog(doc.widget, ["a", "b"], [True, False])
    assert dialog.checkboxes[0].isEnabled()
    assert not dialog.checkboxes[1].isEnabled()
    assert dialog.checkboxes[0].isChecked()


def test_on_delete_event_no_modifications(doc):
    assert doc.on_delete_event() == CloseResponse.OK


def test_on_delete_event_discard(doc, tmp_path, monkeypatch):
    src = tmp_path / "f.txt"
    src.write_bytes(b"x\n")
    load(doc, [str(src), None])
    doc.bufferdata[0].modified = True
    monkeypatch.setattr(CloseDialog, "exec", lambda self: CloseDialog.DISCARD)
    assert doc.on_delete_event() == CloseResponse.OK       # discard, no write
