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


def test_centre_column_leaves_the_outputs_to_the_osd():
    """The open HUD shows its active outputs where the closed one does, in
    the OSD (osd_win.py) — the centre column draws no second pill row."""
    state = copy.deepcopy(SAMPLES["held_modifier"])
    state["context"]["active_outputs"] = []
    without = _layers(state, {"center": FULL})["center"]
    state["context"]["active_outputs"] = [{"key": "KEY_LEFTCTRL", "silent": False}]
    assert _layers(state, {"center": FULL})["center"] is without


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


# ── The gesture connector as a cached layer with its own shadow ──────────

def _gesture():
    st = copy.deepcopy(SAMPLES["base_only"])
    st["trackpads"] = {"left": {"touching": True, "x": 0.3, "y": 0.4, "mode": "mouse"},
                       "right": {"touching": True, "x": 0.6, "y": 0.5, "mode": "mouse"},
                       "gesture": {"touching": True}}
    return st


def _pads(state, **kw):
    return group_layers(state, SW, SH, {"LPad": FULL, "RPad": FULL}, **kw)


def test_connector_layer_has_a_shadow_like_every_element():
    c = _pads(_gesture())["connector"]
    assert c is not None and c.shadow is not None and c.bleed is not None
    x, y, w, h = c.rect
    assert x < SW / 2 < x + w   # spans screen centre


def test_connector_layer_only_while_gesturing():
    assert _pads(SAMPLES["base_only"])["connector"] is None
    st = _gesture()
    assert group_layers(st, SW, SH, {"LPad": FULL})["connector"] is None


def test_connector_layer_is_cached():
    st = _gesture()
    assert _pads(st)["connector"] is _pads(copy.deepcopy(st))["connector"]


def test_connector_without_shadow_or_glow(monkeypatch):
    import dataclasses
    import theme
    monkeypatch.setattr(theme, "_active", dataclasses.replace(
        theme.Theme(), connector_shadow=False, connector_glow=0.0))
    c = _pads(_gesture())["connector"]
    assert c.shadow is None and c.bleed is None


def test_connector_glow_without_a_shadow(monkeypatch):
    """No plate or cloud, but the neon halo still needs its slot."""
    import dataclasses
    import theme
    monkeypatch.setattr(theme, "_active", dataclasses.replace(
        theme.Theme(), connector_shadow=False, connector_glow=0.8))
    c = _pads(_gesture())["connector"]
    assert c.shadow is not None and c.bleed is None


def test_connector_glows_in_its_own_colour(monkeypatch):
    import dataclasses
    import numpy as np
    import theme
    monkeypatch.setattr(theme, "_active", dataclasses.replace(
        theme.Theme(), connector_color=(0.0, 1.0, 0.0), connector_shadow=False,
        connector_glow=1.0))
    c = _pads(_gesture())["connector"]
    surf = c.shadow[0]
    surf.flush()
    px = np.ndarray((surf.get_height(), surf.get_stride() // 4, 4), np.uint8, surf.get_data())
    lit = px[px[..., 3] > 40]
    assert len(lit) and (lit[:, 1] > lit[:, 2] + 40).mean() > 0.9   # green, not red/blue


def test_reference_path_draws_the_connector_at_rest_and_mid_slide():
    import cairo
    from renderer_split import draw_hud_split
    for open_t in (0.5, 1.0):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, SW, SH)
        draw_hud_split(cairo.Context(surf), None, None, _gesture(), SW, SH, open_t=open_t)
        surf.flush()
        import numpy as np
        px = np.ndarray((SH, surf.get_stride() // 4, 4), np.uint8, surf.get_data())
        assert px[:, SW // 2 - 200, 3].max() > 0, open_t   # the line, left of the label



def _crumb_texts(state, content):
    """The breadcrumb pills' labels the centre layer draws."""
    import renderer_split
    renderer_split._center_cache.clear()
    seen = []
    real = renderer_split._pill_row

    def spy(cr, x, y, labels, *a, **kw):
        seen.extend(labels)
        return real(cr, x, y, labels, *a, **kw)
    renderer_split._pill_row = spy
    try:
        _layers(state, {"center": content})
    finally:
        renderer_split._pill_row = real
    return seen


def _in_claude(*held):
    st = copy.deepcopy(SAMPLES["base_only"])
    st["context"]["config_stack"] = ["Steam Deck Base", "Claude Desktop"]
    st["context"]["held_modifiers"] = list(held)
    return st


def test_breadcrumbs_alone_are_a_slice_of_the_centre():
    from reveal import crumbs
    st = _in_claude("BTN_TL")
    full = _layers(st, {"center": FULL})["center"]
    part = _layers(st, {"center": crumbs({"Claude Desktop"})})["center"]
    fx, fy, fw, fh = full.rect
    x, y, w, h = part.rect
    assert fx <= x and fy <= y and x + w <= fx + fw and y + h <= fy + fh
    assert h < fh / 2
    assert part.look != full.look
    assert part.shadow is not None


def test_breadcrumbs_show_only_the_relevant_layers():
    from reveal import crumbs
    st = _in_claude("BTN_TL", "BTN_TR")
    texts = _crumb_texts(st, crumbs(()))
    assert "Claude Desktop" not in texts and "Steam Deck Base" not in texts
    assert {"L1", "R1"} <= set(texts)
    assert "Claude Desktop" in _crumb_texts(st, crumbs({"Claude Desktop"}))


def test_the_base_is_hidden_in_the_full_hud_too():
    texts = _crumb_texts(_in_claude(), FULL)
    assert "Claude Desktop" in texts and "Steam Deck Base" not in texts


def test_the_base_can_be_shown(monkeypatch):
    import dataclasses
    import theme
    monkeypatch.setattr(theme, "_active", dataclasses.replace(theme.Theme(), crumbs_base=True))
    assert "Steam Deck Base" in _crumb_texts(_in_claude(), FULL)


def test_filled_buttons_cast_one_shadow():
    """A filled button (the Controls badge, Classic, Theme, the X) is one
    shape for the shadow: noted as a shape, its label gets no text plate of
    its own — that plate, narrower than the fill, cut the badge into three
    (B-04)."""
    from helpers import capture_text_boxes
    from layout_split import compute_layout
    from renderer_split import _draw_center, CENTER_BUTTONS, center_button
    import cairo
    center = compute_layout(SW, SH)[2]
    with capture_text_boxes() as cap:
        _draw_center(cairo.Context(cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)),
                     SAMPLES["base_only"], center, 1.0)
    rects = [center_button(SAMPLES["base_only"], center, n)[:4] for n in CENTER_BUTTONS]
    assert [tuple(round(v) for v in s[:4]) for s in cap.shapes] == \
        [tuple(round(v) for v in r) for r in rects]
    for x, y, w, h in cap.boxes:
        for bx, by, bw, bh in rects:
            inside = bx <= x + w / 2 <= bx + bw and by <= y + h / 2 <= by + bh
            assert not inside, cap.texts
    assert "Deckery HUD" in cap.texts


def _shadow_alpha_left_of(layer, x_max, y0, y1):
    """Summed shadow alpha in a band of the screen, logical px."""
    import numpy as np
    surf, sx, sy, sw, sh = layer.shadow
    a = np.ndarray((surf.get_height(), surf.get_stride() // 4, 4), np.uint8,
                   surf.get_data())[:, :surf.get_width(), 3]
    fx, fy = surf.get_width() / sw, surf.get_height() / sh
    cols = slice(0, max(0, int((x_max - sx) * fx)))
    rows = slice(max(0, int((y0 - sy) * fy)), max(0, int((y1 - sy) * fy)))
    return int(a[rows, cols].sum())


def test_a_press_that_changes_the_legend_traces_a_new_shadow():
    """··· held as a modifier drops its Gaming Mode line (B-18). The at-rest
    shadow a press normally keeps would still shadow that line."""
    from renderer_split import element_box
    base = SAMPLES["base_only"]
    rest = _layers(base, {"QAM": FULL})["QAM"]
    held = copy.deepcopy(base)
    held["context"]["held_modifiers"] = held["context"]["active_buttons"] = ["BTN_BASE"]
    pressed = _layers(held, {"QAM": FULL}, press_t={"BTN_BASE": 1.0})["QAM"]
    bx, by, bw, bh = element_box(ELEMENTS["QAM"], rest.tx)
    band = (bx - 80, by - 10, by + bh + 10)   # past the pill's own falloff
    assert _shadow_alpha_left_of(rest, *band) > 0, "the line cast no shadow at rest"
    assert _shadow_alpha_left_of(pressed, *band) == 0
    # A press that leaves the legends alone still keeps the at-rest shadow.
    assert _layers(base, {"QAM": FULL})["QAM"].shadow == rest.shadow
    again = _layers(base, {"QAM": FULL}, press_t={"BTN_BASE": 1.0})["QAM"]
    assert again.shadow == rest.shadow


# ── Release 2.0.0: no state from makima, in the split design ─────────────

def test_split_says_why_it_has_no_state_legibly():
    """The classic HUD's three lines (main, aa803c7), on a dark plate: the
    split overlay has no background of its own, and white text alone was
    unreadable on a light page."""
    import cairo
    import numpy as np
    from helpers import capture_text_boxes
    from renderer_split import draw_hud_split
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, SW, SH)
    with capture_text_boxes() as cap:
        draw_hud_split(cairo.Context(surf), None, None, SAMPLES["unreadable"], SW, SH)
    assert cap.texts == ["No state from makima", f"Cannot read {SAMPLES['unreadable']['unreadable']}",
                         "Is makima.service running?"]
    surf.flush()
    px = np.ndarray((SH, surf.get_stride() // 4, 4), np.uint8, surf.get_data())
    bx, by, bw, bh = cap.boxes[0]
    assert px[int(by) - 6, SW // 2, 3] > 180   # a plate above the first line, not bare text
