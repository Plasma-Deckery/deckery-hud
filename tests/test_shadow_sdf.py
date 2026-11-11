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
