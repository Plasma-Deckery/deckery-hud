"""B-20: the distance-field shadow (profile = "sdf")."""

import dataclasses
import math

import numpy as np

import shadow
import theme


def _brute(inside):
    ys, xs = np.nonzero(inside)
    h, w = inside.shape
    yy, xx = np.mgrid[0:h, 0:w]
    return np.sqrt(((yy[..., None] - ys) ** 2 + (xx[..., None] - xs) ** 2).min(axis=2))


def test_edt_is_exact_within_its_cap():
    rng = np.random.default_rng(3)
    inside = rng.random((23, 31)) > 0.97
    inside[5, 5] = True
    d = shadow._edt(inside, 6)
    ref = _brute(inside)
    assert np.allclose(d, np.minimum(ref, 6), atol=1e-4)


AURA = shadow.PRESETS["aura"]
SPEC = shadow.GroupShadowSpec(rrects=((100, 100, 60, 40, 8),), text_boxes=((180, 110, 50, 16),),
                              ink=(100, 100, 130, 40), text_colours=((1, 1, 1),))


def _at(surf, x, y):
    """Alpha (0..1) of an ARGB32 surface at pixel (x, y)."""
    surf.flush()
    px = np.ndarray((surf.get_height(), surf.get_stride() // 4, 4), np.uint8, surf.get_data())
    return px[int(y), int(x), 3] / 255.0


def test_plate_is_solid_on_the_shapes_and_ends_past_its_soft_edge():
    gs = shadow.group_shadow(SPEC, AURA)
    cx, cy, _w, _h = gs.core_rect
    d = shadow._CORE_DOWN
    inside = _at(gs.core_surface, (130 - cx) / d, (120 - cy) / d)
    assert inside == np.float32(round(AURA.core_alpha * 255) / 255) or abs(inside - AURA.core_alpha) < 0.01
    far = 100 - AURA.core_grow - AURA.core_soft - 4
    assert _at(gs.core_surface, (far - cx) / d, (120 - cy) / d) == 0


def test_veil_ends_inside_its_own_grid():
    """The field maps to zero alpha before the grid's border — no hard cut."""
    gs = shadow.group_shadow(SPEC, AURA)
    edge = np.concatenate([gs.field[0], gs.field[-1], gs.field[:, 0], gs.field[:, -1]])
    assert shadow._bleed_curve(AURA, edge).max() == 0
    assert AURA.merge_lo == math.exp(-AURA.bleed_reach / AURA.bleed_curve)
    assert AURA.merge_hi == 1.0


def test_neighbours_merge_by_their_fields():
    """Two plates a little further apart than the veil reaches alone still
    join: their fields add in the merge pass."""
    gs = shadow.group_shadow(SPEC, AURA)
    f = gs.field
    assert f.max() == 1.0
    one = math.exp(-(AURA.bleed_reach + 4) / AURA.bleed_curve)
    assert one < AURA.merge_lo < 2 * one


def test_plate_border_and_lines_draw_in_the_rim_slot():
    plain = shadow.group_shadow(SPEC, AURA)
    assert plain.rim is None
    framed = dataclasses.replace(AURA, plate_border=(0, 1, 1, 1), plate_shape="chamfer",
                                 plate_radius=6, plate_lines=0.3)
    gs = shadow.group_shadow(SPEC, framed)
    surf, x, y = gs.rim
    # along the top edge of the shape's plate (grown by core_grow): the border
    top = 100 - framed.core_grow
    assert max(_at(surf, 130 - x, yy - y) for yy in (top, top + 1)) > 0.9
    assert _at(surf, 130 - x, top - 3 - y) == 0
    # well inside: only scanlines, on every third row
    rows = [_at(surf, 130 - x, yy - y) for yy in range(118, 124)]
    assert max(rows) > 0.2 and min(rows) == 0


def test_every_builtin_theme_builds_its_shadow():
    try:
        for name in theme.names():
            theme.activate(name)
            st = theme.current().shadow_style()
            a, b = shadow.group_shadow_layers(SPEC, st, None, None)
            assert a is not None and b is not None
    finally:
        theme.activate(theme.DEFAULT)


def _glow_of(rgba, **kw):
    import cairo
    content = cairo.ImageSurface(cairo.FORMAT_ARGB32, 40, 20)
    cr = cairo.Context(content)
    cr.set_source_rgba(*rgba)
    cr.rectangle(10, 8, 20, 4)
    cr.fill()
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, 80, 60)
    style = dataclasses.replace(AURA, glow_alpha=1.0, glow_radius=3, **kw)
    shadow.draw_glow(cairo.Context(out), content, 20, 20, style)
    return _at(out, 40, 34)          # 4 px below the bar


def test_white_ink_glows_only_with_glow_neutral():
    assert _glow_of((1, 1, 1, 1)) == 0
    assert _glow_of((1, 1, 1, 1), glow_neutral=1.0) > 0.2
    assert _glow_of((0.1, 0.1, 0.1, 1), glow_neutral=1.0) == 0      # dark ink never
    assert _glow_of((0.1, 0.9, 0.8, 1)) > 0.2                       # colour always


def test_text_glow_scales_inside_text_boxes():
    import cairo
    content = cairo.ImageSurface(cairo.FORMAT_ARGB32, 40, 20)
    cr = cairo.Context(content)
    cr.set_source_rgba(0.1, 0.9, 0.8, 1)
    cr.rectangle(10, 8, 20, 4)
    cr.fill()
    style = dataclasses.replace(AURA, glow_alpha=1.0, glow_radius=3)
    vals = []
    for text in (0.0, 0.5, 1.0):
        out = cairo.ImageSurface(cairo.FORMAT_ARGB32, 80, 60)
        shadow.draw_glow(cairo.Context(out), content, 20, 20, style, ((28, 26, 24, 8),), text)
        vals.append(_at(out, 40, 34))
    assert vals[0] == 0 and 0 < vals[1] < vals[2]


# ── plates merged across elements ───────────────────────────────────────────

def _row(y):
    """One element: a legend line at y, like one face button's."""
    return shadow.GroupShadowSpec(text_boxes=((200, y, 80, 14),), ink=(200, y, 80, 14),
                                  text_colours=((1, 1, 1),))


def _plates(style, specs, opacity=1.0):
    import cairo
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, 480, 320)
    shadow.paint_plates(cairo.Context(out), [(shadow.plate_layer(s, style), 0.0, opacity)
                                             for s in specs], 480, 320, style)
    return out


def test_merged_plates_dont_stack_where_they_overlap():
    """Two face buttons' legend plates overlap; drawn in one pass they are
    one plate of the plate's own strength, not a darker band where both are."""
    style = dataclasses.replace(AURA, core_soft=2)
    a, b = _row(100), _row(120)
    both = _plates(style, (a, b))
    assert abs(_at(both, 240, 117) - style.core_alpha) < 0.02   # in the overlap
    assert abs(_at(both, 240, 107) - style.core_alpha) < 0.02   # in one plate only


def test_a_merged_plate_alone_is_its_own_plate():
    """A single revealed element looks as it would with its own plate."""
    style = dataclasses.replace(AURA, core_soft=2)
    spec = _row(100)
    alone = _plates(style, (spec,))
    gs = shadow.group_shadow(spec, style)
    cx, cy, _w, _h = gs.core_rect
    d = shadow._CORE_DOWN
    # Inside and outside, 2 px off its edges (the own plate is sampled on
    # its half-resolution grid).
    left, top = 200 - style.legend_padx, 100 - style.legend_pady
    for x, y in ((240, 107), (left + 2, 107), (left - 2, 107), (240, top + 2), (240, top - 3),
                 (240, 80)):
        own = _at(gs.core_surface, (x - cx) / d, (y - cy) / d)
        assert abs(_at(alone, x, y) - own) < 0.12, (x, y)


def test_merged_plates_fade_instead_of_shrinking():
    style = dataclasses.replace(AURA, core_soft=2)
    half = _plates(style, (_row(100), _row(120)), 0.5)
    assert abs(_at(half, 240, 117) - style.core_alpha / 2) < 0.02


def test_merged_contour_runs_round_the_union_not_through_it():
    style = dataclasses.replace(AURA, core_soft=1, plate_border=(1.0, 1.0, 1.0, 1.0),
                                plate_border_width=1.5)
    both = _plates(style, (_row(100), _row(120)))
    inner = 120 - style.legend_pady     # where the lower plate's own top edge was
    assert _at(both, 240, inner) - style.core_alpha < 0.05
    top = 100 - style.legend_pady
    assert max(_at(both, 240, top + dy) for dy in (-1, 0, 1)) > 0.9


def test_merging_leaves_the_plate_out_of_the_element_shadow():
    spec = _row(100)
    merged, _ = shadow.group_shadow_layers(spec, AURA, None, None, plate=False)
    own, _ = shadow.group_shadow_layers(spec, AURA, None, None)
    gs = shadow.group_shadow(spec, AURA)
    x, y = (240 - merged[1]), (107 - merged[2])
    assert _at(merged[0], x, y) == 0 and _at(own[0], x, y) > 0.5
    assert shadow.plate_layer(spec, dataclasses.replace(AURA, plate_merge=0)) is None
    assert gs.plate is not None


def test_classic_presets_dont_merge_plates():
    for name, style in shadow.PRESETS.items():
        assert shadow.merges_plates(style) == (name == "aura"), name
