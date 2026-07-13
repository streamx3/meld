import os

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


def _drain_gen(gen, limit=5000):
    for _ in range(limit):
        try:
            next(gen)
        except StopIteration:
            return


def test_show_patch_success_emits_create_diff(view, tmp_path, monkeypatch):
    view.vc = _null.Vc(str(tmp_path))
    (tmp_path / "foo.c").write_text("working copy\n")
    monkeypatch.setattr(view.vc, "get_patch_files", lambda patch: ["foo.c"])
    monkeypatch.setattr(vcview.misc, "write_pipe", lambda cmd, text: 0)

    emitted = []
    view.create_diff.connect(lambda lst: emitted.append(lst))
    view.show_patch(str(tmp_path), "a patch")

    assert len(emitted) == 1
    destfile, pathtofile = emitted[0]
    assert pathtofile == str(tmp_path / "foo.c")
    assert os.path.basename(destfile) == "foo.c"
    assert os.path.exists(destfile)          # original was reconstructed
    assert view.tempdirs                      # tempdir tracked for cleanup


def test_show_patch_missing_file_creates_empty(view, tmp_path, monkeypatch):
    view.vc = _null.Vc(str(tmp_path))
    # foo.c does NOT exist in the working copy -> an empty original is created.
    monkeypatch.setattr(view.vc, "get_patch_files", lambda patch: ["foo.c"])
    monkeypatch.setattr(vcview.misc, "write_pipe", lambda cmd, text: 0)
    emitted = []
    view.create_diff.connect(lambda lst: emitted.append(lst))
    view.show_patch(str(tmp_path), "a patch")
    destfile = emitted[0][0]
    assert os.path.exists(destfile)
    assert open(destfile).read() == ""


def test_show_patch_failure_uses_msgarea_not_modal(view, tmp_path, monkeypatch):
    view.vc = _null.Vc(str(tmp_path))
    (tmp_path / "foo.c").write_text("x\n")
    monkeypatch.setattr(view.vc, "get_patch_files", lambda patch: ["foo.c"])
    monkeypatch.setattr(vcview.misc, "write_pipe", lambda cmd, text: 1)  # fails

    emitted = []
    view.create_diff.connect(lambda lst: emitted.append(lst))
    view.show_patch(str(tmp_path), "a patch")

    assert emitted == []                       # no comparison opened
    assert view.msgarea.has_message()          # error surfaced non-modally
    assert QApplication.activeModalWidget() is None
    assert "patch" in view.consoleview.toPlainText().lower()


def test_run_diff_iter_no_differences(view, tmp_path, monkeypatch):
    view.vc = _null.Vc(str(tmp_path))
    view.label_text = "repo"
    # `true` yields no output -> the patch is empty.
    monkeypatch.setattr(view.vc, "diff_command", lambda: ["true"])
    emitted = []
    view.create_diff.connect(lambda lst: emitted.append(lst))

    _drain_gen(view.run_diff_iter([str(tmp_path)], empty_patch_ok=True))

    assert emitted == []                       # empty patch, nothing opened
    assert view.msgarea.has_message()          # "No differences found."
    assert QApplication.activeModalWidget() is None
