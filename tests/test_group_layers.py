"""Per-group layers of the split renderer (B-12). Needs cairo/numpy — run in
the `deckery` distrobox."""

import copy
import math

import pytest

from render_sample import SAMPLES
from reveal import Content, FULL, PAD_ONLY
from renderer_split import group_layers
from clusters import LEFT_STACK, RIGHT_STACK

GROUPS = LEFT_STACK + RIGHT_STACK + ("center",)
SW, SH = 1280, 800


def _layers(state, contents, dev_scale=1.0):
    return group_layers(state, SW, SH, contents, dev_scale=dev_scale)["groups"]


def test_full_layers_cover_all_groups():
    groups = _layers(SAMPLES["base_only"], {g: FULL for g in GROUPS})
    assert set(groups) == set(GROUPS)


def test_only_requested_groups_are_built():
    groups = _layers(SAMPLES["base_only"], {"l_pad": PAD_ONLY})
    assert set(groups) == {"l_pad"}


def test_group_rect_inside_screen():
    groups = _layers(SAMPLES["base_only"], {g: FULL for g in GROUPS})
    for name, layer in groups.items():
        x, y, w, h = layer.rect
        assert w > 0 and h > 0, name
        assert 0 <= x and x + w <= SW and 0 <= y and y + h <= SH, name
        if name in LEFT_STACK:
            assert x + w <= SW / 2, name
        elif name in RIGHT_STACK:
            assert x >= SW / 2, name


@pytest.mark.parametrize("dev_scale", [1.0, 1.5])
def test_surface_matches_rect(dev_scale):
    groups = _layers(SAMPLES["base_only"], {g: FULL for g in GROUPS}, dev_scale)
    for name, layer in groups.items():
        _x, _y, w, h = layer.rect
        assert layer.surface.get_width() == math.ceil(w * dev_scale), name
        assert layer.surface.get_height() == math.ceil(h * dev_scale), name


def test_pad_only_hides_base_legend():
    state = copy.deepcopy(SAMPLES["base_only"])
    state["bindings"]["BTN_BASE"] = {"action": ["KEY_F1"], "kind": "remap", "label": None,
                                     "origin": "Steam Deck", "silent": False}
    full = _layers(state, {"r_pad": FULL})["r_pad"]
    pad = _layers(state, {"r_pad": PAD_ONLY})["r_pad"]
    assert pad.rect[2] < full.rect[2]


def test_modifier_filter_drops_rows():
    state = copy.deepcopy(SAMPLES["held_modifier"])
    state["bindings"]["BTN_DPAD_DOWN"] = {"action": ["KEY_DOWN"], "kind": "remap", "label": None,
                                          "origin": "Steam Deck", "silent": False}
    only_up = Content(frozenset({"BTN_DPAD_UP"}), False, "all")
    full = _layers(state, {"l_face": FULL})["l_face"]
    filtered = _layers(state, {"l_face": only_up})["l_face"]
    assert filtered.rect != full.rect
    again = _layers(state, {"l_face": only_up})["l_face"]
    assert again.surface is filtered.surface


def test_content_union():
    a = Content(frozenset({"BTN_TL"}), False, "all")
    assert a.union(PAD_ONLY) == Content(frozenset({"BTN_TL"}), True, "all")
    assert a.union(FULL) == FULL


def _on_screen(layer):
    """The group's surface pasted at its rect on a screen-sized buffer."""
    import cairo
    import numpy as np
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, SW, SH)
    cr = cairo.Context(surf)
    cr.set_source_surface(layer.surface, layer.rect[0], layer.rect[1])
    cr.paint()
    surf.flush()
    return np.ndarray((SH, surf.get_stride() // 4, 4), np.uint8, surf.get_data())[:, :SW].copy()


def test_filtered_rows_keep_full_layout_position():
    """A filtered group is a subset of the full one, pixel for pixel — its
    rows sit exactly where they do in the full HUD."""
    state = copy.deepcopy(SAMPLES["held_modifier"])
    for k, a in (("BTN_DPAD_DOWN", "KEY_DOWN"), ("BTN_DPAD_LEFT", "KEY_LEFT"),
                 ("BTN_DPAD_RIGHT", "KEY_RIGHT")):
        state["bindings"][k] = {"action": [a], "kind": "remap", "label": None,
                                "origin": "Steam Deck", "silent": False}
    only_up = Content(frozenset({"BTN_DPAD_UP"}), False, "all")
    full = _on_screen(_layers(state, {"l_face": FULL})["l_face"])
    filtered = _on_screen(_layers(state, {"l_face": only_up})["l_face"])
    ink = filtered[..., 3] > 0
    mismatch = (filtered[ink] != full[ink]).any(axis=1).sum()
    assert mismatch <= 0.02 * ink.sum()


def test_shadow_sits_behind_its_group():
    """Interim shadow (until B-14): centred on the cluster's own art, not
    shifted toward the screen centre."""
    from layout_split import compute_layout
    clusters, _ax, _center = compute_layout(SW, SH)
    groups = _layers(SAMPLES["base_only"], {g: FULL for g in GROUPS})
    for name, layer in groups.items():
        if name == "center":
            continue
        x, y, w, h, _s = clusters[name]
        _f, sx, sy, sw_, sh_ = layer.shadow
        assert abs((sx + sw_ / 2) - (x + w / 2)) < 1, name
        assert abs((sy + sh_ / 2) - (y + h / 2)) < 1, name


@pytest.mark.parametrize("btn", ["BTN_GRIPL", "BTN_GRIPL2", "BTN_GRIPR", "BTN_GRIPR2",
                                 "BTN_SOUTH", "BTN_NORTH", "BTN_SELECT", "BTN_START",
                                 "BTN_MODE", "BTN_BASE"])
def test_live_strip_covers_a_pressed_button(btn):
    """A pressed scale-animated button leaves the cached bitmap (it's drawn
    live), so the group's ink shrinks — the live strip must still cover the
    whole button, or the press is drawn cut off (seen live on the paddles)."""
    from renderer_split import live_rect, _SCALE_ANIM_PARTS
    from parts import part_bbox
    part, group = _SCALE_ANIM_PARTS[btn]
    layers = group_layers(SAMPLES["base_only"], SW, SH, {group: FULL}, press_t={btn: 1.0})
    ox, oy, scale = layers["groups"][group].tx
    x0, y0, x1, y1 = part_bbox(part)
    lx, ly, lw, lh = live_rect(group, layers, SW, SH)
    assert lx <= ox + x0 * scale and ox + x1 * scale <= lx + lw, btn
    assert ly <= oy + y0 * scale and oy + y1 * scale <= ly + lh, btn
