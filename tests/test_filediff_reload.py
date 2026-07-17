"""M2: on-disk change detection + reload for FileDiffView.

The QFileSystemWatcher fires asynchronously on real changes; these tests drive
the handler (_on_file_changed_on_disk) and reload() directly for determinism.
"""

import pytest

from meldq.views.filediff import FileDiffView


@pytest.fixture
def fd(qapp, qtbot, tmp_path):
    view = FileDiffView(2)
    qtbot.addWidget(view)
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"one\ntwo\n")
    b.write_bytes(b"one\n2\n")
    view.set_files([str(a), str(b)])
    view._files = (a, b)                    # stash for tests
    return view


def test_reload_discards_edits(fd):
    a, _b = fd._files
    fd.panes[0].set_text("locally\nedited\n")
    a.write_bytes(b"one\ntwoCHANGED\n")     # external change
    fd.reload(0)
    assert fd.panes[0].text() == "one\ntwoCHANGED\n"
    assert not fd.is_modified(0)


def test_reload_preserves_encoding_and_eol(fd, tmp_path):
    a, _b = fd._files
    a.write_bytes(b"caf\xe9\r\n")            # latin-1 + CRLF, changed on disk
    fd.reload(0)
    assert fd._encoding[0] == "latin-1"
    assert fd._eol[0] == "\r\n"


def test_external_change_prompts(fd):
    a, _b = fd._files
    a.write_bytes(b"one\nEXTERNAL\n")        # real external edit
    fd._on_file_changed_on_disk(str(a))
    assert fd.infobar.message == '"a.txt" changed on disk.'


def test_reload_button_reloads(fd):
    a, _b = fd._files
    a.write_bytes(b"one\nNEW\n")
    fd._on_file_changed_on_disk(str(a))
    fd.infobar._buttons[0].click()           # "Reload"
    assert fd.panes[0].text() == "one\nNEW\n"
    assert fd.infobar.message is None


def test_ignore_button_keeps_local(fd):
    a, _b = fd._files
    fd.panes[0].set_text("mine\nkept\n")
    a.write_bytes(b"one\nOTHER\n")
    fd._on_file_changed_on_disk(str(a))
    fd.infobar._buttons[1].click()           # "Ignore"
    assert fd.panes[0].text() == "mine\nkept\n"    # local edit kept
    assert fd.infobar.message is None
    # Re-firing for the same on-disk state must not prompt again.
    fd._on_file_changed_on_disk(str(a))
    assert fd.infobar.message is None


def test_own_save_does_not_prompt(fd):
    a, _b = fd._files
    fd.panes[0].set_text("one\nsaved\n")
    fd.save(0)                               # our own write
    fd._on_file_changed_on_disk(str(a))      # simulate the watcher firing
    assert fd.infobar.message is None        # not flagged as external


def test_no_prompt_when_content_unchanged(fd):
    a, _b = fd._files
    a.write_bytes(a.read_bytes())            # touch without changing content
    fd._on_file_changed_on_disk(str(a))
    assert fd.infobar.message is None


def test_import_shared_path_no_bogus_reload_on_reference(qapp, qtbot, tmp_path):
    # M9: a patch-import view backs both panes with the same path; pane 0 is
    # the read-only original. Saving pane 1 must not fire a "changed on disk"
    # prompt on the reference pane (whose Reload would load the patched content
    # into it, destroying the original-vs-patched comparison).
    src = tmp_path / "f.txt"
    src.write_bytes(b"one\ntwo\n")
    view = FileDiffView(2)
    qtbot.addWidget(view)
    view.set_texts(["one\ntwo\n", "one\ntwo\n"], [str(src), str(src)])
    view.panes[0].setReadOnly(True)
    view.panes[1].replace_all_text("one\nTWO\n")
    view.save(1)                                  # write patched, arm watcher
    view._on_file_changed_on_disk(str(src))       # simulate the watcher firing
    assert view.infobar.message is None           # no prompt on the reference
    assert view.panes[0].text() == "one\ntwo\n"   # reference untouched
