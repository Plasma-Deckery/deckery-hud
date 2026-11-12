"""Shadow tint follows each item's own colour, locally (B-14): white and
grey items cast the neutral shadow, a coloured one tints only its own
surroundings, and its rim is the light counterpart of the same hue. Needs
cairo/numpy — run in the `deckery` distrobox."""

import colorsys
import copy

from render_sample import SAMPLES
from reveal import FULL

SW, SH = 1280, 800
AMBER, GREEN, WHITE = (1.0, 0.72, 0.1), (0.25, 0.85, 0.35), (0.95, 0.95, 0.95)


def _style():
    from shadow import PRESETS
    return PRESETS["hauch-kurz"]


def _spec(badge_colour):
    """A strip at (100, 100): a white label on the left, a coloured badge
    (an outlined, filled rect with its text) on the right."""
    import cairo
    from shadow import GroupShadowSpec, ink_colours
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 120)
    cr = cairo.Context(surf)
    cr.set_source_rgb(*WHITE)
    cr.rectangle(10, 40, 80, 14)
    cr.fill()
    cr.set_source_rgba(*badge_colour, 0.9)
    cr.rectangle(300, 40, 80, 14)
    cr.fill()
    cr.set_line_width(2)
    cr.rectangle(290, 30, 100, 34)
    cr.stroke()
    rect = (100, 100, 400, 120)
    return GroupShadowSpec(rrects=((389, 129, 102, 36, 4),),
                           text_boxes=((110, 140, 80, 14), (400, 140, 80, 14)),
                           ink=rect, text_colours=(WHITE, badge_colour),
                           ink_colours=ink_colours(surf, rect))


def _tint_at(spec, points):
    """Shadow colour at screen points, from the element's tint map."""
    from shadow import _FIELD_DOWN, _field_reach, _grid, _spec_bounds, _tint_map
    style = _style()
    x0, y0, w, h = _grid(_spec_bounds(spec), _field_reach(style), _FIELD_DOWN)
    t = _tint_map(spec, x0, y0, w, h, _FIELD_DOWN, style)
    return [t[int((y - y0) / _FIELD_DOWN), int((x - x0) / _FIELD_DOWN)] for x, y in points]


def _chroma(c):
    return max(c) - min(c)


def _hue(c):
    return colorsys.rgb_to_hsv(*c)[0]


def test_white_item_casts_the_neutral_shadow():
    from shadow import _NEUTRAL_DARK
    white, badge = _tint_at(_spec(AMBER), [(150, 147), (440, 147)])
    assert max(abs(a - b) for a, b in zip(white, _NEUTRAL_DARK)) < 0.01
    assert _chroma(badge) > 0.1
    assert abs(_hue(badge) - _hue(AMBER)) < 0.04


def test_badge_colour_change_stays_local():
    """Paused (amber) -> Active (green) retints the badge's surroundings,
    not the white label 250 px away."""
    pts = [(150, 147), (110, 120), (190, 175)]
    a = _tint_at(_spec(AMBER), pts)
    b = _tint_at(_spec(GREEN), pts)
    for ca, cb in zip(a, b):
        assert max(abs(x - y) for x, y in zip(ca, cb)) < 1 / 255


def test_rim_is_the_light_side_of_the_shadow_hue():
    import numpy as np
    from shadow import group_shadow
    spec = _spec(AMBER)
    surf, x, y = group_shadow(spec, _style()).rim
    surf.flush()
    px = np.ndarray((surf.get_height(), surf.get_stride() // 4, 4), np.uint8,
                    surf.get_data())[:, :surf.get_width()].astype(float)
    a = px[..., 3]
    iy, ix = np.unravel_index(np.argmax(a), a.shape)
    rim = tuple(px[iy, ix, [2, 1, 0]] / a[iy, ix])
    (shadow,) = _tint_at(spec, [(x + ix, y + iy)])
    assert _chroma(rim) > 0.1
    assert abs(_hue(rim) - _hue(shadow)) < 0.04


def _centre_tint(paused, monkeypatch):
    """Shadow colour of the live centre column at its title and its first
    breadcrumb, with the status badge paused or active — under a tinted
    style (the themes may not use one)."""
    import renderer_split as rs
    import shadow
    monkeypatch.setattr(rs, "shadow_style", _style)
    # The layer caches are keyed on the theme, not on the style patched in.
    for cache in ("_shadow_layer_cache", "_group_cache"):
        monkeypatch.setattr(rs, cache, {})
    monkeypatch.setattr(rs, "_center_cache", [])
    state = copy.deepcopy(SAMPLES["base_only"])
    state.setdefault("context", {})["paused"] = paused
    rs.group_layers(state, SW, SH, {"center": FULL})
    key, _layers = rs._shadow_layer_cache["center"]
    spec, texts = key[0], key[1]
    out = {}
    for want in ("Deckery HUD", "Steam Deck"):
        bx, by, bw, bh = spec.text_boxes[texts.index(want)]
        (out[want],) = _tint_at(spec, [(bx + bw / 2, by + bh / 2)])
    gs = shadow.group_shadow(spec, rs.shadow_style())
    assert gs.tint_surface is not None
    return out


def test_centre_title_and_breadcrumb_stay_neutral(monkeypatch):
    from shadow import _NEUTRAL_DARK
    for paused in (True, False):
        for name, c in _centre_tint(paused, monkeypatch).items():
            assert max(abs(a - b) for a, b in zip(c, _NEUTRAL_DARK)) < 0.01, (paused, name, c)


def test_status_toggle_leaves_the_title_alone(monkeypatch):
    a, b = _centre_tint(True, monkeypatch), _centre_tint(False, monkeypatch)
    for name in a:
        assert max(abs(x - y) for x, y in zip(a[name], b[name])) < 2 / 255, name
