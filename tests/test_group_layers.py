"""Per-element layers of the split renderer (B-12). Needs cairo/numpy — run
in the `deckery` distrobox."""

import copy
import math

import pytest

from render_sample import SAMPLES
from reveal import Content, FULL
from renderer_split import group_layers
from elements import ELEMENTS, ELEMENT_IDS, BUTTON_ELEMENT, side_of
from clusters import CLUSTER_BUTTONS

SW, SH = 1280, 800


def _layers(state, contents, dev_scale=1.0, press_t=None):
    return group_layers(state, SW, SH, contents, press_t=press_t, dev_scale=dev_scale)["groups"]


def _bound(state, *keys):
    state = copy.deepcopy(state)
    for k in keys:
        state["bindings"][k] = {"action": ["KEY_F1"], "kind": "remap", "label": None,
                                "origin": "Steam Deck", "silent": False}
    return state


def _on_screen(layer):
    """The element's surface pasted at its rect on a screen-sized buffer."""
    import cairo
    import numpy as np
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, SW, SH)
    cr = cairo.Context(surf)
    cr.set_source_surface(layer.surface, layer.rect[0], layer.rect[1])
    cr.paint()
    surf.flush()
    return np.ndarray((SH, surf.get_stride() // 4, 4), np.uint8, surf.get_data())[:, :SW].copy()


def test_every_cluster_button_has_one_element():
    for cluster, buttons in CLUSTER_BUTTONS.items():
        for b in buttons:
            assert ELEMENTS[BUTTON_ELEMENT[b]].cluster == cluster, b


def test_full_layers_cover_all_elements():
    groups = _layers(SAMPLES["base_only"], {e: FULL for e in ELEMENT_IDS})
    assert set(groups) == set(ELEMENT_IDS)


def test_only_requested_elements_are_built():
    assert set(_layers(SAMPLES["base_only"], {"LPad": FULL})) == {"LPad"}


def test_element_rect_inside_its_half():
    groups = _layers(SAMPLES["base_only"], {e: FULL for e in ELEMENT_IDS})
    for name, layer in groups.items():
        x, y, w, h = layer.rect
        assert w > 0 and h > 0, name
        assert 0 <= x and x + w <= SW and 0 <= y and y + h <= SH, name
        if side_of(name) == "left":
            assert x + w <= SW / 2, name
        elif side_of(name) == "right":
            assert x >= SW / 2, name


@pytest.mark.parametrize("dev_scale", [1.0, 1.5])
def test_surface_matches_rect(dev_scale):
    groups = _layers(SAMPLES["base_only"], {e: FULL for e in ELEMENT_IDS}, dev_scale)
    for name, layer in groups.items():
        _x, _y, w, h = layer.rect
        assert layer.surface.get_width() == math.ceil(w * dev_scale), name
        assert layer.surface.get_height() == math.ceil(h * dev_scale), name


def test_pad_and_its_pill_are_separate():
    state = _bound(SAMPLES["base_only"], "BTN_BASE")
    groups = _layers(state, {"RPad": FULL, "QAM": FULL})
    pad, qam = _on_screen(groups["RPad"]), _on_screen(groups["QAM"])
    overlap = ((pad[..., 3] > 0) & (qam[..., 3] > 0)).sum()
    assert overlap == 0
    assert (qam[..., 3] > 0).sum() > 0


def test_shoulder_halves_are_separate():
    """L1 and L2 each draw only their half of the shared wedge; the only
    pixels both touch are the antialiased seam along the divider."""
    import numpy as np
    from parts import part_subpaths
    groups = _layers(SAMPLES["base_only"], {"L1": FULL, "L2": FULL})
    a, b = _on_screen(groups["L1"]), _on_screen(groups["L2"])
    ya, yb = (np.nonzero(img[..., 3] > 0)[0].mean() for img in (a, b))
    assert ya < yb   # L1 sits above L2
    ys, xs = np.nonzero((a[..., 3] > 0) & (b[..., 3] > 0))
    ox, oy, s = groups["L1"].tx
    (_, ax, ay), (_, bx, by) = part_subpaths("shoulder_l_split")[0][:2]
    ax, ay, bx, by = ox + ax * s, oy + ay * s, ox + bx * s, oy + by * s
    dist = np.abs((bx - ax) * (ay - ys) - (ax - xs) * (by - ay)) / np.hypot(bx - ax, by - ay)
    assert (dist > 2).sum() == 0


def test_stick_is_not_part_of_the_dpad():
    groups = _layers(SAMPLES["base_only"], {"DPad": FULL, "L3": FULL})
    a, b = _on_screen(groups["DPad"]), _on_screen(groups["L3"])
    assert ((a[..., 3] > 0) & (b[..., 3] > 0)).sum() == 0


def test_dpad_filter_keeps_full_layout_position():
    """A filtered d-pad is a subset of the full one, pixel for pixel — its
    rows sit exactly where they do in the full HUD."""
    state = _bound(SAMPLES["held_modifier"], "BTN_DPAD_DOWN", "BTN_DPAD_LEFT", "BTN_DPAD_RIGHT")
    only_up = Content(frozenset({"BTN_DPAD_UP"}))
    full = _on_screen(_layers(state, {"DPad": FULL})["DPad"])
    filtered = _on_screen(_layers(state, {"DPad": only_up})["DPad"])
    ink = filtered[..., 3] > 0
    assert (filtered[ink] != full[ink]).any(axis=1).sum() <= 0.02 * ink.sum()
    assert ink.sum() < 0.9 * (full[..., 3] > 0).sum()
    again = _layers(state, {"DPad": only_up})["DPad"]
    assert _layers(state, {"DPad": only_up})["DPad"].surface is again.surface


def test_content_union():
    a = Content(frozenset({"BTN_DPAD_UP"}))
    assert a.union(Content(frozenset({"BTN_DPAD_LEFT"}))) == Content(
        frozenset({"BTN_DPAD_UP", "BTN_DPAD_LEFT"}))
    assert a.union(FULL) == FULL


def test_shadow_sits_behind_its_element():
    """Each element's shadow layers cover everything it draws — its shape
    and its legend — so nothing it shows sits outside its own shadow, and
    the shadow isn't shifted off toward the screen centre."""
    from renderer_split import element_box
    groups = _layers(SAMPLES["base_only"], {e: FULL for e in ELEMENT_IDS})
    for name, layer in groups.items():
        x, y, w, h = layer.rect
        for slot in (layer.shadow, layer.bleed):
            _f, sx, sy, sw_, sh_ = slot
            assert sx <= x and sy <= y, name
            assert sx + sw_ >= x + w and sy + sh_ >= y + h, name
        if name != "center":
            bx, by, bw, bh = element_box(ELEMENTS[name], layer.tx)
            assert sx <= bx and sx + sw_ >= bx + bw, name


def _center_shadow_alpha(state):
    import cairo
    import numpy as np
    from renderer_split import paint_scaled
    surf, x, y, w, h = _layers(state, {"center": FULL})["center"].shadow
    big = cairo.ImageSurface(cairo.FORMAT_ARGB32, SW, SH)
    cr = cairo.Context(big)
    cr.translate(x, y)
    paint_scaled(cr, surf, w, h)
    big.flush()
    a = np.ndarray((SH, big.get_stride() // 4, 4), np.uint8, big.get_data())[:, :SW, 3]
    return a.astype(np.float32) / 255.0


def test_glass_pill_casts_a_gentle_shadow():
    """The active-outputs glass pill (B-04) gets pill_shadow's soft cloud,
    not a legend plate plus traced edge — those read as a dark rim (alpha
    ~0.8 right at the pill)."""
    state = copy.deepcopy(SAMPLES["held_modifier"])
    state["context"]["active_outputs"] = []
    without = _center_shadow_alpha(state)
    state["context"]["active_outputs"] = [{"key": "KEY_LEFTCTRL", "silent": False}]
    added = _center_shadow_alpha(state) - without
    assert 0.1 < added.max() < 0.5


def test_shoulder_halves_cast_separate_shadows():
    """L1 and L2 share one wedge; each casts only its own half."""
    groups = _layers(SAMPLES["base_only"], {e: FULL for e in ("L1", "L2")})
    from renderer_split import _shadow_layer_cache
    l1 = _shadow_layer_cache["L1"][0][0]
    l2 = _shadow_layer_cache["L2"][0][0]
    assert l1.parts[0][4] and l2.parts[0][4]
    assert l1.parts[0][4] != l2.parts[0][4]


@pytest.mark.parametrize("btn", ["BTN_GRIPL", "BTN_GRIPL2", "BTN_GRIPR", "BTN_GRIPR2",
                                 "BTN_SOUTH", "BTN_NORTH", "BTN_SELECT", "BTN_START",
                                 "BTN_MODE", "BTN_BASE"])
def test_live_strip_covers_a_pressed_button(btn):
    """A pressed scale-animated button leaves the cached bitmap (it's drawn
    live), so its element's ink can vanish — the live strip must still
    cover the whole button, or the press is drawn cut off (seen live on
    the paddles)."""
    from renderer_split import live_rect, _SCALE_ANIM_PARTS, _PART_OFFSET
    from parts import part_bbox
    part, _cluster = _SCALE_ANIM_PARTS[btn]
    el = BUTTON_ELEMENT[btn]
    layers = group_layers(SAMPLES["base_only"], SW, SH, {el: FULL}, press_t={btn: 1.0})
    ox, oy, scale = layers["groups"][el].tx
    pdx, pdy = _PART_OFFSET.get(part, (0, 0))
    ox, oy = ox + pdx, oy + pdy
    x0, y0, x1, y1 = part_bbox(part)
    lx, ly, lw, lh = live_rect(el, layers, SW, SH)
    assert lx <= ox + x0 * scale and ox + x1 * scale <= lx + lw, btn
    assert ly <= oy + y0 * scale and oy + y1 * scale <= ly + lh, btn


def test_warm_all_names_match_textures():
    from renderer_split import warm_all
    surfaces = warm_all(SAMPLES["base_only"], SW, SH, 1.0)
    assert set(surfaces) == (set(ELEMENT_IDS) | {"shadow_" + e for e in ELEMENT_IDS}
                             | {"bleed_" + e for e in ELEMENT_IDS})


def test_look_ignores_a_press_but_not_a_binding():
    """win.py crossfades an element whose look changes in place (L1 -> R1
    rebinds a key) — but not a press, which only moves the button from the
    bitmap to the live strip."""
    base = _layers(SAMPLES["base_only"], {"A": FULL})["A"]
    held = copy.deepcopy(SAMPLES["base_only"])
    held.setdefault("context", {})["active_buttons"] = ["BTN_SOUTH"]
    pressed = _layers(held, {"A": FULL}, press_t={"BTN_SOUTH": 1.0})["A"]
    assert pressed.surface is not base.surface
    assert pressed.look == base.look
    state = copy.deepcopy(SAMPLES["base_only"])
    state["bindings"]["BTN_SOUTH"] = {"action": ["KEY_F7"], "kind": "remap", "label": "Neu",
                                      "origin": "Steam Deck", "silent": False}
    rebound = _layers(state, {"A": FULL})["A"]
    assert rebound.look != base.look


def test_switching_back_to_a_layer_is_cached():
    """L1 on, off, on: each element keeps its last few looks, so going back
    costs no rebuild (a full-HUD layer change rebuilt everything: ~110 ms)."""
    base, held = SAMPLES["base_only"], SAMPLES["held_modifier"]
    shown = {"L1": FULL, "A": FULL, "center": FULL}
    a = _layers(base, shown)
    _layers(held, shown)
    b = _layers(base, shown)
    for name in shown:
        assert b[name].surface is a[name].surface, name


def test_a_press_after_a_cached_switch_keeps_its_own_shadow():
    """A mid-press build reuses the element's at-rest shadow — that must be
    the shadow of the look on screen, not of the one built last."""
    base = SAMPLES["base_only"]
    other = _bound(base, "BTN_SOUTH")
    rest = _layers(base, {"A": FULL})["A"]
    assert _layers(other, {"A": FULL})["A"].shadow != rest.shadow
    _layers(base, {"A": FULL})
    pressed = _layers(base, {"A": FULL}, press_t={"BTN_SOUTH": 1.0})["A"]
    assert pressed.surface is not rest.surface
    assert pressed.shadow == rest.shadow
