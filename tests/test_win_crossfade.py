"""An element that changes its look in place dissolves as a whole: its
shadow, cloud and plate go with its bitmap, not ahead of it (B-12, live
round 4: the right pad shown, the left one touched — the right pad's row
moves into the gesture connector, and its plate vanished at once while
its label still faded)."""
import copy

import numpy as np
import pytest

from render_sample import SAMPLES
from renderer_split import live_rect
from reveal import FULL, Want, RevealSettings

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, Graphene, Gsk, Gtk  # noqa: E402

SW, SH = 1280, 800


def _pads(gesture):
    st = copy.deepcopy(SAMPLES["base_only"])
    mode = "gestures" if gesture else "mt-trackpad"
    st["trackpads"] = {"left": {"touching": False, "x": 0.3, "y": 0.4, "mode": mode},
                       "right": {"touching": not gesture, "x": 0.6, "y": 0.5, "mode": mode},
                       "gesture": {"touching": gesture, "enabled": True}}
    return st


@pytest.fixture(scope="module")
def app():
    if Gdk.Display.get_default() is None:
        pytest.skip("no display")

    class App(Gtk.Application):
        def _on_groups_changed(self):
            pass

    a = App(application_id="test.win.crossfade")
    a.register(None)
    return a


@pytest.fixture
def hud(app, monkeypatch):
    import layout_choice
    with layout_choice.building("split"):
        import win
    clock = [100.0]
    monkeypatch.setattr(win.time, "monotonic", lambda: clock[0])
    w = win.Win(app, RevealSettings())
    w._need_surface = lambda n: None
    w._set_split_input_region = lambda: None
    w._start_ticking = lambda: None
    r = Gsk.CairoRenderer.new()
    r.realize_for_display(Gdk.Display.get_default())

    def frame():
        s = Gtk.Snapshot()
        w._snapshot_split(s, SW, SH)
        t = r.render_texture(s.to_node(), Graphene.Rect().init(0, 0, SW, SH))
        d = Gdk.TextureDownloader.new(t)
        b, stride = d.download_bytes()
        return np.frombuffer(b.get_data(), np.uint8).reshape(SH, stride // 4, 4)[:, :SW].astype(int)

    def tick(dt):
        clock[0] += dt
        for a in w._all_anims():
            a.tick(clock[0])
        for x in w._xfade.values():
            x.begin(clock[0])

    yield w, frame, tick
    # The window is left alone: destroying it under pytest segfaults GTK.
    r.unrealize()


@pytest.mark.parametrize("name", [None, "neon"])
def test_gesture_start_dissolves_the_pad_with_its_plate(hud, name, monkeypatch):
    """None: the built-in tokens, the plate in each element's own shadow;
    neon: plates merged across elements in their own pass (B-20)."""
    import theme
    monkeypatch.setattr(theme, "_active", theme.current())
    theme.activate(name)
    w, frame, tick = hud
    w.on_state(_pads(False))
    w.set_wants({"RPad": Want(FULL, "detector")})
    tick(1.0)
    frame()
    rest = frame()
    # The gesture: the right pad stays, its row moves into the connector;
    # the left pad (and with it the connector) only starts fading in.
    w.on_state(_pads(True))
    w.set_wants({"RPad": Want(FULL, "detector"), "LPad": Want(FULL, "detector")})
    first = frame()
    assert "RPad" in w._xfade
    assert (w._frame_ctx[1]["groups"]["RPad"].plate is not None) == (name == "neon")
    # Nothing has dissolved yet, so nothing of the right pad's old frame is
    # gone — but its live dot, which turns amber at once.
    gone = (rest[..., 3] - first[..., 3]).clip(0)
    gone[:, :SW // 2] = 0    # the left pad fading in, the connector with it
    lx, ly, llw, llh = (int(v) for v in live_rect("RPad", w._frame_ctx[1], SW, SH))
    gone[max(0, ly - 2):ly + llh + 2, max(0, lx - 2):lx + llw + 2] = 0
    assert gone.max() <= 8, int((gone > 8).sum())
    # Half-way the old row's plate is still partly there; at the end, gone.
    tick(0.0)
    tick(0.03)
    mid = frame()
    tick(0.5)
    end = frame()
    row = (rest[..., 3] - end[..., 3]).clip(0)
    row[:, :SW // 2] = 0
    ys, xs = np.nonzero(row > 40)
    assert len(ys), "the right pad's row leaves no trace at rest"
    old, half, new = (f[ys, xs, 3].mean() for f in (rest, mid, end))
    assert new + 0.1 * (old - new) < half < old - 0.1 * (old - new)
