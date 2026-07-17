"""M2: LinkMap connector geometry + painting (fresh meldq/views/linkmap)."""

import pytest

from meldq.views.filediff import FileDiffView


@pytest.fixture
def fd(qapp, qtbot):
    view = FileDiffView(2)
    view.resize(700, 400)
    qtbot.addWidget(view)
    view.show()
    return view


def test_one_shape_per_chunk_with_matching_tags(fd):
    fd.set_texts(["a\nOLD\nb\nc\ngone\nd\n",
                  "a\nNEW\nb\nc\nd\nADDED\n"])
    shapes = fd.linkmaps[0].chunk_shapes()
    ops = fd.opcodes()
    assert len(shapes) == len(ops)
    assert [s[0] for s in shapes] == [o[0] for o in ops]


def test_identical_files_no_shapes(fd):
    fd.set_texts(["a\nb\nc\n", "a\nb\nc\n"])
    assert fd.linkmaps[0].chunk_shapes() == []


def test_shape_y_extents_are_ordered(fd):
    # A multi-line replace band's top must sit above its bottom on each side.
    fd.set_texts(["x\nAAA\nBBB\ny\n", "x\nCCC\nDDD\ny\n"])
    tag, l_top, l_bot, r_top, r_bot = fd.linkmaps[0].chunk_shapes()[0]
    assert tag == "replace"
    assert l_top < l_bot
    assert r_top < r_bot


def test_insert_band_tapers_on_left(fd):
    # An inserted block has no left line: the left side collapses to a point.
    fd.set_texts(["a\nb\n", "a\nX\nY\nb\n"])
    shapes = [s for s in fd.linkmaps[0].chunk_shapes() if s[0] == "insert"]
    assert shapes
    _tag, l_top, l_bot, r_top, r_bot = shapes[0]
    assert l_top == l_bot           # left collapses to a point
    assert r_top < r_bot            # right spans the inserted lines


def test_shapes_update_after_merge(fd):
    fd.set_texts(["a\nLEFT\nb\n", "a\nRIGHT\nb\n"])
    assert len(fd.linkmaps[0].chunk_shapes()) == 1
    fd.copy_chunk(fd.chunk_at_line(0, 1), src_pane=0, dst_pane=1)
    assert fd.linkmaps[0].chunk_shapes() == []      # resolved -> no connectors


def test_paint_does_not_crash(fd):
    fd.set_texts(["a\nOLD\nb\n", "a\nNEW\nb\n"])
    fd.linkmaps[0].grab()               # forces a real paintEvent


def test_last_line_change_without_newline_has_visible_band(fd):
    # M10: a change confined to the final line of a no-trailing-newline file
    # ended at hi == line count; y_for_line clamped it, giving a zero-height
    # (invisible) band. It must now have real height.
    fd.set_texts(["a\nb\nlast_L", "a\nb\nlast_R"])   # no trailing newline
    shapes = fd.linkmaps[0].chunk_shapes()
    assert len(shapes) == 1
    tag, l_top, l_bot, r_top, r_bot = shapes[0]
    assert l_bot > l_top and r_bot > r_top           # visible, not zero-height
