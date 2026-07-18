"""Overview map (ChunkMap): geometry, chunk collection, and click-scrub."""

import pytest

from meldq.views.filediff import FileDiffView


@pytest.fixture
def fd(qapp, qtbot):
    view = FileDiffView(2)
    view.resize(700, 300)
    qtbot.addWidget(view)
    view.show()
    return view


def test_chunkmap_collects_last_pane_chunks(fd):
    left = "".join("line %d\n" % i for i in range(200))
    right = "".join(("CHG\n" if i in (10, 150) else "line %d\n" % i)
                    for i in range(200))
    fd.set_texts([left, right])
    chunks = fd._chunkmap_chunks()
    assert [(t, lo, hi) for t, lo, hi in chunks] == [
        ("replace", 10, 11), ("replace", 150, 151)]


def test_chunkmap_scrub_scrolls_pane(fd, qtbot):
    text = "".join("line %d\n" % i for i in range(400))
    other = text.replace("line 5\n", "X\n", 1)
    fd.set_texts([text, other])
    fd.show()
    qtbot.waitExposed(fd)
    cm = fd.chunkmap
    cm.resize(cm.WIDTH, 300)
    before = fd.panes[1].first_visible_line()
    cm._scrub_to(cm.height() - 5)          # click near the bottom
    after = fd.panes[1].first_visible_line()
    assert after > before                   # scrolled down toward EOF


def test_chunkmap_handle_tracks_viewport(fd, qtbot):
    text = "".join("line %d\n" % i for i in range(400))
    fd.set_texts([text, text])
    fd.show()
    qtbot.waitExposed(fd)
    cm = fd.chunkmap
    cm.resize(cm.WIDTH, 300)
    fd.panes[1].scroll_to_line(0)
    top0, _ = cm.handle_rect()
    fd.panes[1].scroll_to_line(200)
    top1, _ = cm.handle_rect()
    assert top1 > top0                      # handle moves down as you scroll


def test_chunkmap_three_way_uses_last_pane(qapp, qtbot):
    view = FileDiffView(3)
    qtbot.addWidget(view)
    view.set_texts(["a\nx\nc\n", "a\nx\nc\n", "a\nR\nc\n"])   # pane2 changed
    chunks = view._chunkmap_chunks()
    assert any(lo <= 1 < hi for _t, lo, hi in chunks)         # change at line 1
