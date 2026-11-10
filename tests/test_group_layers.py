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
