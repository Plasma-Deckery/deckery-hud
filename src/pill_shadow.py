"""
pill_shadow.py — The frosted-glass pill's own shadow (B-04).

A light glass pill on a light page needs something under it to stay
readable, but B-14's legend plate and traced edge read as a dark rim around
it. Glass pills get a gentle, rim-less cloud instead: B-14's "dezent" shape
at about half its strength (picked from a variant sheet over white, dark and
busy game backgrounds). Shared by the split centre, which paints it into the
centre element's shadow slot, and the OSD.

Needs numpy (via shadow.py). No GTK.
"""

import cairo

from shadow import PRESETS, GroupShadowSpec, ShadowStyle, group_shadow, _alpha_surface, _bleed_curve

STYLE = ShadowStyle(**{**PRESETS["dezent"].__dict__, "core_alpha": 0.28, "bleed_alpha": 0.14})

# spec -> (GroupShadow, [alpha surfaces]); the OSD repaints every frame.
_cache = {}


def _layers(boxes):
    spec = GroupShadowSpec(text_boxes=tuple(tuple(round(v) for v in b) for b in boxes))
    hit = _cache.get(spec)
    if hit is None:
        gs = group_shadow(spec, STYLE)
        hit = (gs, [(_alpha_surface(_bleed_curve(STYLE, gs.field)), (gs.x, gs.y, gs.w, gs.h)),
                    (gs.core_surface, gs.core_rect)])
        if len(_cache) > 32:
            _cache.clear()
        _cache[spec] = hit
    return hit


def paint(cr, boxes, rgb=(0, 0, 0)):
    """Shadow for glass pills at `boxes` ((x, y, w, h), as noted by
    helpers.capture_text_boxes), painted in cr's user space."""
    if not boxes:
        return
    _gs, surfs = _layers(boxes)
    for s, (x, y, w, h) in surfs:
        cr.save()
        cr.translate(x, y)
        cr.scale(w / s.get_width(), h / s.get_height())
        pat = cairo.SurfacePattern(s)
        pat.set_filter(cairo.FILTER_BILINEAR)
        cr.set_source_rgb(*rgb)
        cr.mask(pat)
        cr.restore()
