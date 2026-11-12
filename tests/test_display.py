"""
test_display.py — display.py (B-31): zoom per screen, output choice, and
the shadow layers' resolution cap.
"""

import cairo
import pytest

import display
import shadow


@pytest.mark.parametrize("sw, sh", [(1164, 728), (1163, 727), (1280, 800 / 1.1)])
def test_the_deck_draws_at_one(sw, sh):
    assert display.zoom(sw, sh) == 1.0


@pytest.mark.parametrize("sw, sh, k", [
    (3840, 2160, 2160 / 728),      # 4K TV at scale 1
    (1920, 1080, 1080 / 728),      # 4K at scale 2, or 1080p at 1
    (2560, 1440, 1440 / 728),
    (1280, 800, 800 / 728),        # the Deck panel at scale 1: same physical size
])
def test_zoom_follows_the_height(sw, sh, k):
    assert display.zoom(sw, sh) == pytest.approx(k)
    vw, vh, _k = display.view(sw, sh)
    assert vh == pytest.approx(728)
    assert vw == pytest.approx(sw / k)


def test_16_9_only_widens_the_view():
    vw, vh, _k = display.view(3840, 2160)
    assert vh == pytest.approx(728) and vw == pytest.approx(1294.2, abs=0.1)


def test_size_scales_but_keeps_room_for_the_centre():
    assert display.zoom(3840, 2160, 1.2) == pytest.approx(1.2 * 2160 / 728)
    # The Deck at 1.5 would leave a 776 px view: stopped at MIN_VIEW_W.
    assert display.zoom(1164, 728, 1.5) == pytest.approx(1164 / display.MIN_VIEW_W)


def test_degenerate_sizes():
    assert display.zoom(0, 0) == 1.0


@pytest.mark.parametrize("policy, active, want", [
    ("auto", "HDMI-A-1", "HDMI-A-1"),
    ("auto", "eDP-1", "eDP-1"),
    ("auto", None, None),               # unknown: the compositor decides
    ("auto", "DP-9", None),             # gone already
    ("internal", "HDMI-A-1", "eDP-1"),
    ("external", "eDP-1", "DP-2"),      # the last one plugged in
])
def test_pick(policy, active, want):
    assert display.pick(["eDP-1", "HDMI-A-1", "DP-2"], policy, active) == want


def test_pick_without_the_kind_asked_for():
    assert display.pick(["eDP-1"], "external", "eDP-1") == "eDP-1"
    assert display.pick(["HDMI-A-1"], "internal") == "HDMI-A-1"
    assert display.pick([], "auto", "eDP-1") is None


def test_shadow_layers_are_capped():
    style = shadow.PRESETS["dezent"]
    spec = shadow.GroupShadowSpec(text_boxes=((100, 100, 80, 20),))
    content = cairo.ImageSurface(cairo.FORMAT_ARGB32, 3 * 90, 3 * 30)
    content.set_device_scale(3, 3)
    cr = cairo.Context(content)
    cr.rectangle(5, 5, 70, 15)
    cr.fill()
    deck, _ = shadow.group_shadow_layers(spec, style, content, (95, 95, 90, 30), 1.1)
    big, _ = shadow.group_shadow_layers(spec, style, content, (95, 95, 90, 30), 3.0)
    (ds, *drect), (bs, *brect) = deck, big
    assert drect == brect                       # same place in logical px
    assert ds.get_device_scale()[0] == 1.1      # the Deck: untouched
    assert bs.get_device_scale()[0] == shadow.SHADOW_MAX_SCALE
