"""
shadow.py — Shape-following backdrop shadows (B-14), one per HUD element.

Each element (one button with its shape and legend, a stick, a pad, the
centre column — see elements.py) gets a shadow that follows its own
shapes: the trackpad's rounded rectangle, a pill's oval, a stick's circle,
each legend line's text. It is built from these layers:

  core   — a plate hugging every shape and legend line, so the element sits
           on a bit of background of its own;
  bleed  — a wide, soft cloud around the same shapes. Neighbouring elements'
           clouds *merge* rather than stack: every element contributes a soft
           field, the fields are combined first, and only the combined
           field is turned into alpha (a smoothstep between merge_lo and
           merge_hi). Two nearby elements grow a soft neck into one shape,
           like two metaballs, instead of their overlap getting darker;
  edge   — a tight shadow right along every stroke and glyph (outlines,
           callout lines, dots, text), so thin white lines stay legible on
           a white page;
  rim    — a narrow, quiet light line just outside the shapes (not the
           text: a light rim around letters costs contrast on white).

With `tint`, core and bleed are not black but a dark counterpart of the
legend's colour — an active teal line sits on deep teal, the pink Gaming
Mode hint on dark berry, white legends on a slightly cool dark grey. Each
legend line takes its own colour, the shapes take the most colourful legend
of their element, and the rim is a light version of the same. The edge
stays black: it is what keeps legends readable on white.

An element's own shadow depends only on its own shapes, so it looks the same
whether it is shown alone or with others; only the bleed merges with what
else is visible. Everything per element is computed once and cached — never
per animation frame. The merge itself is one pass per frame: the elements'
fields drawn with their own slide/fade, then mapped to alpha — on the GPU a
pair of component-transfer nodes (win.py), in cairo a small 1/4-resolution
canvas.

Needs numpy. No GTK.
"""

import colorsys
import math
import os
from dataclasses import dataclass

import cairo
import numpy as np

from parts import part_subpaths, part_bbox
from svgpath import replay, subpath_bbox
from helpers import _rrect


@dataclass(frozen=True)
class ShadowStyle:
    core_grow: float     # px the shapes are grown by before the core is softened
    core_blur: float     # sigma, px
    core_alpha: float
    bleed_grow: float
    bleed_blur: float    # sigma, px — how far the cloud reaches
    bleed_alpha: float
    merge_lo: float      # combined field -> alpha: 0 below lo ...
    merge_hi: float      # ... full bleed_alpha above hi. Lower = elements reach for each other sooner
    legend: str          # "line": a rounded plate per text line; "glyph": follows the letters
    legend_padx: float
    legend_pady: float
    edge_radius: float   # px, tight stroke/glyph shadow
    edge_alpha: float
    tint: bool = False   # core + bleed in a dark version of the legend colour
    rim_alpha: float = 0.0
    # Tint and rim colour (B-20 themes): how deep and how saturated the dark
    # shadow colour under a coloured legend is, and how saturated its rim.
    tint_value: float = 0.26
    tint_saturation: float = 0.90
    rim_saturation: float = 0.7
    # Neon glow: a soft halo in the legend's own colour around coloured
    # strokes and text, under the tight edge. 0 = none.
    glow_alpha: float = 0.0
    glow_radius: float = 6.0


PRESETS = {
    # A — tight and quiet, no merging cloud to speak of.
    "dezent": ShadowStyle(core_grow=4, core_blur=8, core_alpha=0.55,
                          bleed_grow=6, bleed_blur=16, bleed_alpha=0.25,
                          merge_lo=0.20, merge_hi=0.70,
                          legend="line", legend_padx=8, legend_pady=4,
                          edge_radius=1.5, edge_alpha=0.55),
    # B — a darker plate per element, fraying outward.
    "platte": ShadowStyle(core_grow=8, core_blur=2.5, core_alpha=0.45,
                          bleed_grow=8, bleed_blur=24, bleed_alpha=0.50,
                          merge_lo=0.05, merge_hi=0.55,
                          legend="line", legend_padx=10, legend_pady=5,
                          edge_radius=1.5, edge_alpha=0.55),
    # C3 — tight core plus a wide cloud that merges neighbours into one band.
    "wolke": ShadowStyle(core_grow=4, core_blur=8, core_alpha=0.45,
                         bleed_grow=10, bleed_blur=40, bleed_alpha=0.55,
                         merge_lo=0.03, merge_hi=0.40,
                         legend="line", legend_padx=14, legend_pady=8,
                         edge_radius=1.5, edge_alpha=0.55),
    # E + tint 2 — tight core as in wolke, a long, light cloud that fades out
    # instead of stopping short, tinted, with a quiet rim on the shapes.
    "hauch": ShadowStyle(core_grow=4, core_blur=10, core_alpha=0.45,
                         bleed_grow=10, bleed_blur=90, bleed_alpha=0.36,
                         merge_lo=0.0, merge_hi=0.60,
                         legend="line", legend_padx=14, legend_pady=8,
                         edge_radius=1.5, edge_alpha=0.55,
                         tint=True, rim_alpha=0.5),
    # hauch with a solid dark halo: every shape and legend line wrapped in a
    # wide, dark plate (grown 16 px, ~3/4 opaque), then the same soft
    # falloff — for bright pages and games, where hauch's light cloud left
    # the items standing on almost nothing.
    "hauch-dicht": ShadowStyle(core_grow=16, core_blur=14, core_alpha=0.78,
                               bleed_grow=28, bleed_blur=90, bleed_alpha=0.48,
                               merge_lo=0.0, merge_hi=0.45,
                               legend="line", legend_padx=24, legend_pady=14,
                               edge_radius=1.5, edge_alpha=0.55,
                               tint=True, rim_alpha=0.5),
    # Heavier still: a bigger, nearly opaque halo.
    "hauch-satt": ShadowStyle(core_grow=22, core_blur=18, core_alpha=0.85,
                              bleed_grow=36, bleed_blur=90, bleed_alpha=0.55,
                              merge_lo=0.0, merge_hi=0.40,
                              legend="line", legend_padx=28, legend_pady=16,
                              edge_radius=1.5, edge_alpha=0.55,
                              tint=True, rim_alpha=0.5),
    # hauch-dicht's halo with a short falloff: the dark plate stays close to
    # the items, the cloud around it ends within ~80 px instead of
    # spreading a grey haze across the page — neighbours still join by a
    # soft neck where they sit close.
    "hauch-kurz": ShadowStyle(core_grow=16, core_blur=14, core_alpha=0.78,
                              bleed_grow=20, bleed_blur=26, bleed_alpha=0.30,
                              merge_lo=0.0, merge_hi=0.50,
                              legend="line", legend_padx=24, legend_pady=14,
                              edge_radius=1.5, edge_alpha=0.55,
                              tint=True, rim_alpha=0.5),
}
DEFAULT_PRESET = "hauch-kurz"


def style_from_env():
    """DECKERY_HUD_SHADOW=<preset>[,glyph|line] — a stand-in until the
    settings work (B-15) owns this."""
    raw = os.environ.get("DECKERY_HUD_SHADOW", "")
    name, _, legend = raw.partition(",")
    style = PRESETS.get(name.strip() or DEFAULT_PRESET, PRESETS[DEFAULT_PRESET])
    if legend.strip() in ("line", "glyph"):
        style = ShadowStyle(**{**style.__dict__, "legend": legend.strip()})
    return style


@dataclass(frozen=True)
class GroupShadowSpec:
    """Everything an element's shadow is built from, in logical screen px at
    rest. Hashable — it is the cache key.

    parts:      (part_name, ox, oy, scale, clip) — filled silhouette of a parts.py
                shape; clip is None or a polygon in the part's own SVG space
                that cuts it (one half of a shoulder wedge)
    rrects:     (x, y, w, h, r) — shapes drawn as plain rounded rects (paddles)
    text_boxes: (x, y, w, h) — one per drawn text line / label pill
    text_colours: (r, g, b) or None per text box — the legend's colour
    ink:        (x, y, w, h) — everything the element draws; the shadow layers
                always cover it, so the edge shadow reaches strokes that are
                neither a part nor text (e.g. the centre's close button)
    """
    parts: tuple = ()
    rrects: tuple = ()
    text_boxes: tuple = ()
    ink: tuple = None
    text_colours: tuple = ()


# ── small numpy helpers ───────────────────────────────────────────────────

def _box_blur(a, r, axis):
    if r < 1:
        return a
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad), axis=axis, dtype=np.float32)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / (2 * r + 1)


def _blur(a, sigma):
    """Gaussian approximated by three box passes per axis."""
    if sigma < 0.5:
        return a
    r = max(1, int(round((math.sqrt(4 * sigma * sigma + 1) - 1) / 2)))
    for _ in range(3):
        a = _box_blur(_box_blur(a, r, 0), r, 1)
    return a


def _smoothstep(lo, hi, x):
    t = np.clip((x - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _alpha_surface(alpha, rgb=None):
    """ARGB32 surface whose alpha is `alpha` (0..1), black or coloured by the
    straight (h, w, 3) `rgb`."""
    h, w = alpha.shape
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    buf = np.ndarray((h, s.get_stride() // 4, 4), np.uint8, s.get_data())
    a = np.clip(alpha, 0.0, 1.0)
    if rgb is None:
        buf[:, :w, :3] = 0
    else:
        pm = (np.clip(rgb, 0.0, 1.0) * a[..., None] * 255.0 + 0.5).astype(np.uint8)
        buf[:, :w, 0], buf[:, :w, 1], buf[:, :w, 2] = pm[..., 2], pm[..., 1], pm[..., 0]
    buf[:, :w, 3] = (a * 255.0 + 0.5).astype(np.uint8)
    s.mark_dirty()
    return s


# ── tint ──────────────────────────────────────────────────────────────────

_NEUTRAL_DARK = (0.07, 0.08, 0.10)    # white legends: a slightly cool dark grey
_NEUTRAL_LIGHT = (0.86, 0.90, 0.98)


def _chroma(colour):
    """0 for white/grey legends, 1 for clearly coloured ones."""
    if colour is None:
        return 0.0
    return min(1.0, max(0.0, (max(colour) - min(colour) - 0.12) / 0.25))


def _mix(a, b, k):
    return tuple(x * (1 - k) + y * k for x, y in zip(a, b))


def dark_of(colour, style=None):
    """The shadow colour under a legend of `colour`."""
    k = _chroma(colour)
    if k <= 0:
        return _NEUTRAL_DARK
    h, _s, _v = colorsys.rgb_to_hsv(*colour)
    sat, val = (style.tint_saturation, style.tint_value) if style else (0.90, 0.26)
    return _mix(_NEUTRAL_DARK, colorsys.hsv_to_rgb(h, sat, val), k)


def light_of(colour, style=None):
    """The rim colour for shapes whose legend is `colour`."""
    k = _chroma(colour)
    if k <= 0:
        return _NEUTRAL_LIGHT
    h, s, _v = colorsys.rgb_to_hsv(*colour)
    cap = style.rim_saturation if style else 0.7
    return _mix(_NEUTRAL_LIGHT, colorsys.hsv_to_rgb(h, min(s, cap), 1.0), k)


def neutral_rgb(style):
    """Shadow colour under white/grey legends (and glass pills) for `style`."""
    return _NEUTRAL_DARK if style.tint else (0.0, 0.0, 0.0)


def element_colour(spec):
    """An element's own colour: its most colourful legend (None if all are
    white/grey)."""
    best = max(spec.text_colours, key=_chroma, default=None)
    return best if _chroma(best) > 0 else None


# ── one element ────────────────────────────────────────────────────────────

_CORE_DOWN = 2    # core is computed at 1/2 resolution
_FIELD_DOWN = 4   # bleed field at 1/4 — very low-frequency


def _spec_bounds(spec):
    xs0, ys0, xs1, ys1 = [], [], [], []
    for name, ox, oy, scale, _clip in spec.parts:
        x0, y0, x1, y1 = part_bbox(name)
        xs0.append(ox + x0 * scale); ys0.append(oy + y0 * scale)
        xs1.append(ox + x1 * scale); ys1.append(oy + y1 * scale)
    for x, y, w, h, _r in spec.rrects:
        xs0.append(x); ys0.append(y); xs1.append(x + w); ys1.append(y + h)
    for x, y, w, h in spec.text_boxes + ((spec.ink,) if spec.ink else ()):
        xs0.append(x); ys0.append(y); xs1.append(x + w); ys1.append(y + h)
    if not xs0:
        return None
    return min(xs0), min(ys0), max(xs1), max(ys1)


def _mask(spec, x0, y0, w, h, down, grow, padx, pady, with_text=True):
    """Filled silhouettes (+ legend plates), grown by `grow`, rasterized into
    a (w/down x h/down) A8 grid whose origin is (x0, y0) in screen px."""
    mw, mh = max(1, int(math.ceil(w / down))), max(1, int(math.ceil(h / down)))
    surf = cairo.ImageSurface(cairo.FORMAT_A8, mw, mh)
    cr = cairo.Context(surf)
    cr.scale(1 / down, 1 / down)
    cr.translate(-x0, -y0)
    cr.set_source_rgba(0, 0, 0, 1)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.set_line_width(2 * grow)

    def fill_grown():
        cr.fill_preserve()
        if grow > 0:
            cr.stroke()
        else:
            cr.new_path()

    for name, ox, oy, scale, clip in spec.parts:
        cr.save()
        if clip:
            cr.new_path()
            for i, (px, py) in enumerate(clip):
                (cr.line_to if i else cr.move_to)(ox + px * scale, oy + py * scale)
            cr.close_path()
            cr.clip()
        cr.new_path()
        replay(cr, part_subpaths(name), ox, oy, scale)
        fill_grown()
        cr.restore()
    for x, y, rw, rh, r in spec.rrects:
        _rrect(cr, x, y, rw, rh, r)
        fill_grown()
    if with_text:
        for x, y, tw, th in spec.text_boxes:
            bh = th + 2 * pady
            _rrect(cr, x - padx, y - pady, tw + 2 * padx, bh, min(bh / 2, 10 + pady))
            cr.fill()
    surf.flush()
    a = np.ndarray((mh, surf.get_stride()), np.uint8, surf.get_data())[:, :mw]
    return a.astype(np.float32) / 255.0


@dataclass
class GroupShadow:
    x: float             # screen px the bleed field covers
    y: float
    w: float
    h: float
    field_surface: object       # pre-curve bleed field at 1/_FIELD_DOWN, tinted or black
    core_rect: tuple            # (x, y, w, h) screen px the core covers — far smaller
    core_surface: object        # core alpha (A8) at 1/_CORE_DOWN
    tint_surface: object = None  # opaque shadow colour at 1/_FIELD_DOWN over (x, y), or None
    rim: tuple = None           # (surface, x, y) in screen px, or None
    field: np.ndarray = None    # the pre-curve field itself (pill_shadow.py maps it)


_group_cache = {}


def _grid(b, reach, down):
    """Origin and size of a grid snapped to `down` around bounds b ± reach."""
    x0 = math.floor((b[0] - reach) / down) * down
    y0 = math.floor((b[1] - reach) / down) * down
    return (x0, y0, math.ceil((b[2] + reach - x0) / down) * down,
            math.ceil((b[3] + reach - y0) / down) * down)


def group_shadow(spec, style):
    """The cached, per-element part of the shadow (core plate, bleed field,
    tint, rim). None for an element with nothing to cast a shadow."""
    key = (spec, style)
    hit = _group_cache.get(key)
    if hit is not None or key in _group_cache:
        return hit
    b = _spec_bounds(spec)
    if b is None:
        _group_cache[key] = None
        return None
    # The field reaches far (a long fade); snapped to the field grid so
    # elements combine on one shared grid. The core only needs its own blur.
    x0, y0, w, h = _grid(b, style.bleed_grow + 3 * style.bleed_blur + style.legend_padx,
                         _FIELD_DOWN)
    # +24: room for the glass pills' own shadow (pill_shadow.py), which the
    # centre paints into this same slot.
    core_rect = _grid(b, max(style.core_grow, style.legend_padx) + 3 * style.core_blur + 24,
                      _CORE_DOWN)

    # In "glyph" mode the legend's core comes from the letters themselves
    # (see edge_shadow); the plate is shapes only.
    core = _mask(spec, *core_rect, _CORE_DOWN, style.core_grow,
                 style.legend_padx, style.legend_pady, with_text=style.legend == "line")
    core = np.clip(_blur(core, style.core_blur / _CORE_DOWN) * 1.6, 0, 1) * style.core_alpha

    field = _mask(spec, x0, y0, w, h, _FIELD_DOWN, style.bleed_grow,
                  style.legend_padx + 4, style.legend_pady + 3)
    field = _blur(field, style.bleed_blur / _FIELD_DOWN)

    tint = _tint_map(spec, x0, y0, w, h, _FIELD_DOWN, style) if style.tint else None
    gs = GroupShadow(x0, y0, w, h, _alpha_surface(field, tint), core_rect, _alpha_surface(core),
                     _alpha_surface(np.ones(tint.shape[:2], np.float32), tint)
                     if tint is not None else None,
                     _rim(spec, style), field)
    if len(_group_cache) > 160:
        _group_cache.clear()
    _group_cache[key] = gs
    return gs


def _tint_map(spec, x0, y0, w, h, down, style=None):
    """Straight (h, w, 3) shadow colour over an element's grid: near a legend
    line its own dark colour, elsewhere the element's (see dark_of)."""
    mw, mh = max(1, int(math.ceil(w / down))), max(1, int(math.ceil(h / down)))
    base = dark_of(element_colour(spec), style)
    num = np.empty((mh, mw, 3), np.float32)
    num[...] = base
    num *= 1e-3
    den = np.full((mh, mw), 1e-3, np.float32)
    shapes = _mask(GroupShadowSpec(spec.parts, spec.rrects), x0, y0, w, h, down, 0, 0, 0)
    if shapes.any():
        f = _blur(shapes, 40 / down)
        num += f[..., None] * base
        den += f
    # Lines of one colour share one mask and one blur.
    by_colour = {}
    for box, colour in zip(spec.text_boxes, spec.text_colours or (None,) * len(spec.text_boxes)):
        by_colour.setdefault(dark_of(colour, style), []).append(box)
    for dark, boxes in by_colour.items():
        m = _mask(GroupShadowSpec(text_boxes=tuple(boxes)), x0, y0, w, h, down, 0, 0, 0)
        f = _blur(m, 10 / down) * 6
        num += f[..., None] * dark
        den += f
    return num / den[..., None]


def _rim(spec, style):
    """The quiet light line just outside an element's shapes, at 1 px per
    screen px — (surface, x, y) or None."""
    if style.rim_alpha <= 0 or not (spec.parts or spec.rrects):
        return None
    b = _spec_bounds(GroupShadowSpec(spec.parts, spec.rrects))
    x0, y0 = math.floor(b[0]) - 6, math.floor(b[1]) - 6
    w, h = math.ceil(b[2]) + 6 - x0, math.ceil(b[3]) + 6 - y0
    sil = _mask(GroupShadowSpec(spec.parts, spec.rrects), x0, y0, w, h, 1, 0, 0, 0)
    ring = np.clip(_blur(sil, 1.2) * 2.0, 0, 1) * (1 - sil) * style.rim_alpha
    rgb = np.empty(ring.shape + (3,), np.float32)
    rgb[...] = light_of(element_colour(spec), style)
    return _alpha_surface(ring, rgb), x0, y0


def _placed(surf, x, y, down):
    """`surf` (a grid at 1/down with origin x, y) as a bilinear pattern in
    screen px."""
    pat = cairo.SurfacePattern(surf)
    pat.set_matrix(cairo.Matrix(xx=1 / down, yy=1 / down, x0=-x / down, y0=-y / down))
    pat.set_filter(cairo.FILTER_BILINEAR)
    pat.set_extend(cairo.EXTEND_PAD)
    return pat


# ── per-element layers and the merged bleed ────────────────────────────────

def group_shadow_layers(spec, style, content, content_rect, dev_scale=1.0):
    """An element's two shadow layers, each (surface, x, y, w, h) in logical px:

    shadow — core plate + tight edge shadow + rim, final alpha: drawn as
             is, with the element's own translate/opacity;
    bleed  — the pre-curve field: every visible element's bleed is drawn
             with its translate/opacity into one pass, and only that pass
             is mapped to alpha (see bleed_transfer / paint_bleed) — so
             neighbouring clouds fuse instead of stacking.

    content/content_rect: the element's cached layer and where it sits; its
    strokes and glyphs are what the edge shadow traces. (None, None) when
    the element casts no shadow."""
    gs = group_shadow(spec, style)
    if gs is None:
        return None, None
    cx, cy, cw, ch = gs.core_rect
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(math.ceil(cw * dev_scale)),
                              int(math.ceil(ch * dev_scale)))
    surf.set_device_scale(dev_scale, dev_scale)
    cr = cairo.Context(surf)
    cr.translate(-cx, -cy)
    if gs.tint_surface is not None:
        cr.set_source(_placed(gs.tint_surface, gs.x, gs.y, _FIELD_DOWN))
    else:
        cr.set_source_rgb(0, 0, 0)
    cr.mask(_placed(gs.core_surface, cx, cy, _CORE_DOWN))
    if content is not None:
        if style.glow_alpha > 0:
            draw_glow(cr, content, content_rect[0], content_rect[1], style, spec.text_boxes)
        draw_edge_shadow(cr, content, content_rect[0], content_rect[1], style, spec.text_boxes)
    if gs.rim is not None:
        rim, rx, ry = gs.rim
        cr.set_source_surface(rim, rx, ry)
        cr.paint()
    return (surf, cx, cy, cw, ch), (gs.field_surface, gs.x, gs.y, gs.w, gs.h)


def _bleed_curve(style, x):
    return _smoothstep(style.merge_lo, style.merge_hi, x) * style.bleed_alpha


def bleed_transfer(style, n=8):
    """The field -> alpha curve for the GPU path, as two component-transfer
    steps: a linear map of [merge_lo, merge_hi] onto [0, 1] (clamped), then
    a small smoothstep table scaled to bleed_alpha. GSK's GPU renderer
    refuses large tables ("tables too big in component transfer"), and the
    whole curve lives in the low part of the field's range, so one uniform
    table over [0, 1] would need far too many entries to resolve it."""
    span = max(style.merge_hi - style.merge_lo, 1e-6)
    t = np.linspace(0.0, 1.0, n)
    table = [float(v) for v in t * t * (3.0 - 2.0 * t) * style.bleed_alpha]
    return 1.0 / span, -style.merge_lo / span, table


def paint_bleed(cr, items, sw, sh, style):
    """Cairo-path equivalent of the GPU bleed pass: items are
    (bleed, dx, opacity) with bleed = (surface, x, y, w, h). Fields are
    composited (OVER: they combine like alpha, 1 - Π(1 - f)) on a small
    canvas, then mapped through the curve and painted stretched."""
    down = _FIELD_DOWN
    cw, ch = int(math.ceil(sw / down)), int(math.ceil(sh / down))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, cw, ch)
    ccr = cairo.Context(canvas)
    for (surf, x, y, w, h), dx, opacity in items:
        if opacity <= 0:
            continue
        ccr.save()
        ccr.translate((x + dx) / down, y / down)
        ccr.scale(w / down / surf.get_width(), h / down / surf.get_height())
        ccr.set_source_surface(surf, 0, 0)
        ccr.get_source().set_filter(cairo.FILTER_BILINEAR)
        ccr.paint_with_alpha(opacity)
        ccr.restore()
    canvas.flush()
    px = np.ndarray((ch, canvas.get_stride() // 4, 4), np.uint8, canvas.get_data())[:, :cw]
    a = px[..., 3].astype(np.float32) / 255.0
    # The curve reshapes alpha only; the colour (unpremultiplied) is kept —
    # as the GPU's component transfer does.
    rgb = px[..., [2, 1, 0]].astype(np.float32) / 255.0 / np.maximum(a, 1e-6)[..., None]
    paint_scaled(cr, _alpha_surface(_bleed_curve(style, a), rgb), sw, sh)


def paint_scaled(cr, surf, sw, sh, alpha=1.0):
    """Paint a (possibly downscaled) shadow surface stretched over (sw, sh)
    with bilinear filtering and padded edges, so the screen border doesn't
    fade toward transparent where the filter would sample outside it."""
    w, h = surf.get_width(), surf.get_height()
    cr.save()
    cr.scale(sw / w, sh / h)
    cr.set_source_surface(surf, 0, 0)
    pat = cr.get_source()
    pat.set_filter(cairo.FILTER_BILINEAR)
    pat.set_extend(cairo.EXTEND_PAD)
    cr.rectangle(0, 0, w, h)
    cr.clip()
    cr.paint_with_alpha(alpha)
    cr.restore()


# ── tight edge shadow ─────────────────────────────────────────────────────

def _ring(radius, n):
    return [(radius * math.cos(2 * math.pi * i / n), radius * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def _stamp(cr, content, x, y, offsets):
    """Union of `content`'s alpha (placed at x, y) shifted by every offset —
    a cheap dilation done by cairo/pixman instead of numpy."""
    cr.push_group()
    cr.set_source_rgba(0, 0, 0, 1)
    for dx, dy in offsets:
        cr.mask_surface(content, x + dx, y + dy)
    cr.pop_group_to_source()


def draw_edge_shadow(cr, content, x, y, style, text_boxes=()):
    """Tight shadow along every stroke and glyph of `content` (a cached
    layer's ARGB surface), drawn into `cr` at the layer's own position.
    In "glyph" legend mode the text additionally gets a wider, letter-shaped
    plate — clipped to the text boxes, so lines and outlines keep only the
    tight edge."""
    r = style.edge_radius
    _stamp(cr, content, x, y, [(0, 0)] + _ring(r, 8))
    cr.paint_with_alpha(style.edge_alpha)
    _stamp(cr, content, x, y, _ring(r * 2.2, 12))
    cr.paint_with_alpha(style.edge_alpha * 0.35)
    if style.legend == "glyph" and text_boxes:
        cr.save()
        for bx, by, bw, bh in text_boxes:
            cr.rectangle(bx - 12, by - 10, bw + 24, bh + 20)
        cr.clip()
        for rad, n, a in ((3, 12, style.core_alpha), (6, 16, style.core_alpha * 0.55),
                          (10, 20, style.core_alpha * 0.3)):
            _stamp(cr, content, x, y, _ring(rad, n))
            cr.paint_with_alpha(a)
        cr.restore()


# ── neon glow ─────────────────────────────────────────────────────────────

_GLOW_DOWN = 2


def draw_glow(cr, content, x, y, style, text_boxes=()):
    """Soft halo in the content's own colour around its coloured strokes —
    outlines, callout lines, dots: the neon tubes. Text casts none (a halo
    fills the gaps between letters and blurs them) and neither does white
    or grey ink. `content` is a cached layer's ARGB surface placed at
    (x, y); the halo is computed at 1/_GLOW_DOWN of its device pixels."""
    content.flush()
    sx = content.get_device_scale()[0]
    w, h = content.get_width(), content.get_height()
    px = np.ndarray((h, content.get_stride() // 4, 4), np.uint8,
                    content.get_data())[:h:_GLOW_DOWN, :w:_GLOW_DOWN].astype(np.float32) / 255.0
    a = px[..., 3]
    rgb = px[..., [2, 1, 0]] / np.maximum(a, 1e-6)[..., None]
    k = np.clip((rgb.max(axis=2) - rgb.min(axis=2) - 0.12) / 0.25, 0.0, 1.0) * a
    for bx, by, bw, bh in text_boxes:
        # text boxes are in the same logical px as (x, y)
        f = sx / _GLOW_DOWN
        c0, r0 = max(0, int((bx - x) * f) - 1), max(0, int((by - y) * f) - 1)
        c1, r1 = int((bx + bw - x) * f) + 2, int((by + bh - y) * f) + 2
        k[r0:r1, c0:c1] = 0
    if not k.any():
        return
    sigma = style.glow_radius * sx / _GLOW_DOWN
    kb = _blur(k, sigma)
    col = np.stack([_blur(rgb[..., i] * k, sigma) for i in range(3)], axis=2)
    col /= np.maximum(kb, 1e-6)[..., None]
    # Full brightness, so the halo reads as light, not as a stain.
    col /= np.maximum(col.max(axis=2), 1e-6)[..., None]
    halo = _alpha_surface(np.clip(kb * 4.0, 0.0, 1.0) * style.glow_alpha, col)
    cr.save()
    cr.translate(x, y)
    cr.scale(_GLOW_DOWN / sx, _GLOW_DOWN / sx)
    pat = cairo.SurfacePattern(halo)
    pat.set_filter(cairo.FILTER_BILINEAR)
    cr.set_source(pat)
    cr.paint()
    cr.restore()
