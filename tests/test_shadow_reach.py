"""Every shadow layer fades to nothing inside its own bitmap — no hard cut
where a layer, or the content it was traced from, ends (B-14). Needs
cairo/numpy — run in the `deckery` distrobox."""

import dataclasses

import pytest

from render_sample import SAMPLES
from reveal import FULL
from elements import ELEMENT_IDS

SW, SH = 1280, 800


def _alpha(surf):
    import cairo
    import numpy as np
    surf.flush()
    w, h = surf.get_width(), surf.get_height()
    if surf.get_format() == cairo.FORMAT_A8:
        return np.ndarray((h, surf.get_stride()), np.uint8, surf.get_data())[:, :w] / 255.0
    return np.ndarray((h, surf.get_stride() // 4, 4), np.uint8, surf.get_data())[:, :w, 3] / 255.0


def _border(a):
    return max(a[0].max(), a[-1].max(), a[:, 0].max(), a[:, -1].max())


def _styles():
    import theme
    from shadow import PRESETS
    out = {"theme:" + n: theme.load(n).shadow_style() for n in theme.names()}
    out.update({"preset:" + n: s for n, s in PRESETS.items()})
    # Theme tweaks can push every reach: a wide glow, a drop offset, a
    # cloud that isn't grown but has wide legend plates.
    out["extreme"] = dataclasses.replace(
        PRESETS["hauch-kurz"], glow_alpha=1.0, glow_radius=40, glow_text=True,
        offset_x=9, offset_y=-7, bleed_grow=0, legend_padx=40, legend_pady=22,
        core_grow=2, core_gain=3.0)
    return out


@pytest.mark.parametrize("name", sorted(_styles()))
def test_shadow_layers_fade_out_inside_their_bitmaps(name, monkeypatch):
    import renderer_split as rs
    style = _styles()[name]
    monkeypatch.setattr(rs, "shadow_style", lambda: style)
    # The layer caches are keyed on the theme, not on the style patched in.
    for cache in ("_shadow_layer_cache", "_group_cache"):
        monkeypatch.setattr(rs, cache, {})
    monkeypatch.setattr(rs, "_center_cache", [])
    groups = rs.group_layers(SAMPLES["layer_override_and_combo"], SW, SH,
                             {e: FULL for e in ELEMENT_IDS})["groups"]
    for el, layer in groups.items():
        if layer.shadow is not None:
            assert _border(_alpha(layer.shadow[0])) == 0, (name, el, "shadow")
        if layer.bleed is not None:
            assert _border(_alpha(layer.bleed[0])) == 0, (name, el, "bleed")


def _content(fill):
    """A 60x40 layer bitmap whose whole area is `fill` (rgba) — its ink
    runs right up to its own edge, as an element's outline does."""
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 40)
    cr = cairo.Context(surf)
    cr.set_source_rgba(*fill)
    cr.paint()
    return surf


def _drawn(draw, pad=50):
    import cairo
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60 + 2 * pad, 40 + 2 * pad)
    draw(cairo.Context(out), pad, pad)
    return _alpha(out)


def test_glow_spreads_past_the_content_bitmap():
    """The neon halo around a stroke at the bitmap's edge continues outside
    the bitmap and fades out there, instead of stopping at its border."""
    from shadow import PRESETS, draw_glow
    style = dataclasses.replace(PRESETS["hauch-kurz"], glow_alpha=1.0, glow_radius=6)
    a = _drawn(lambda cr, x, y: draw_glow(cr, _content((0.1, 0.9, 0.8, 1)), x, y, style))
    assert a[70, 50 - 4] > 0.3            # 4 px left of the bitmap: still glowing
    assert a[70, 50 - 12] < a[70, 50 - 4]  # ... and fading
    assert _border(a) == 0


def test_edge_shadow_of_a_translucent_fill_stays_faint():
    """The tight edge shadow is the union of shifted copies of the content's
    alpha — a 14 % badge fill must not stack into a dark, hard-edged slab."""
    from shadow import PRESETS, draw_edge_shadow
    style = PRESETS["hauch-kurz"]
    a = _drawn(lambda cr, x, y: draw_edge_shadow(cr, _content((0.3, 0.9, 0.4, 0.14)), x, y, style))
    assert a.max() <= 0.14 * style.edge_alpha * 1.35 + 0.01
