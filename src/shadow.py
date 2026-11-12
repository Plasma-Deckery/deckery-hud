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
    glow_text: bool = False      # the glow around text too (blurs small letters)
    glow_text_alpha: float = 1.0  # with glow_text: its strength around text, × glow_alpha
    glow_neutral: float = 0.0    # white/light-grey ink glows too, in white: 0..1
    # Shape of the shadow (B-20 themes):
    offset_x: float = 0.0        # px — a drop shadow: plate, edge and cloud move,
    offset_y: float = 0.0        #      the rim and glow stay on their shapes
    core_gain: float = 1.6       # how hard the plate's edge is: higher = crisper
    plate_radius: float = -1.0   # corner radius of the legend plates; -1 = round ends
    shadow_rgb: tuple = (0.0, 0.0, 0.0)   # colour without tint, and of the edge
    # Distance-field shadow (B-20, profile = "sdf"): every layer is a curve
    # of the distance to the element's shapes and legend plates, instead of
    # a blurred mask. The plate is solid out to core_grow and fades over
    # core_soft px; the veil around it (bleed_alpha) ends exactly
    # bleed_reach px beyond the plate. bleed_curve shapes that fade: small =
    # most of the veil hugs the plate with a light tail, large = an even
    # S-ramp. Neighbours merge by an exponential smooth-min — the fields add
    # — so close elements grow a soft neck. merge_lo/merge_hi are derived.
    profile: str = "blur"        # "blur" | "sdf"
    core_soft: float = 8.0       # px, width of the plate's edge
    bleed_reach: float = 32.0    # px beyond the plate where the veil ends
    bleed_curve: float = 12.0    # px, decay length of the merge field
    # sdf only — the plate as a surface of its own:
    plate_shape: str = "round"   # legend plates: "round" (plate_radius) | "chamfer" (cut = plate_radius)
    plate_border: tuple = (0.0, 0.0, 0.0, 0.0)   # rgba contour along the plate's edge
    plate_border_width: float = 1.0
    plate_lines: float = 0.0     # CRT scanlines across the plate: 0..1 strength
    bleed_rgb: tuple = ()        # colour of the veil; () = the plate's colour
    bleed_dx: float = 0.0        # px the veil is moved by (an elevation shadow
    bleed_dy: float = 0.0        #    under a light plate)

    def __post_init__(self):
        if self.profile == "sdf":
            lo = max(math.exp(-self.bleed_reach / max(self.bleed_curve, 1e-3)), 0.04)
            object.__setattr__(self, "merge_lo", lo)
            object.__setattr__(self, "merge_hi", 1.0)


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
    # B-20 neon: a smoked-glass plate that hugs every shape and legend line
    # (solid out to its edge, a short soft edge) and a light veil that ends
    # 26 px out and joins close neighbours by a neck — no haze across the
    # page, no blurry blobs that don't follow the shapes.
    "aura": ShadowStyle(core_grow=7, core_blur=0, core_alpha=0.80,
                        bleed_grow=0, bleed_blur=0, bleed_alpha=0.28,
                        merge_lo=0, merge_hi=1,
                        legend="line", legend_padx=10, legend_pady=4,
                        edge_radius=1.5, edge_alpha=0.55,
                        shadow_rgb=(0.035, 0.04, 0.06), glow_alpha=0.6, glow_radius=5,
                        profile="sdf", core_soft=7, bleed_reach=26, bleed_curve=9),
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
    ink_colours: InkColours of the element's bitmap, or None — what the tint
                follows (see _local_tint); without it, the text boxes' colours
    """
    parts: tuple = ()
    rrects: tuple = ()
    text_boxes: tuple = ()
    ink: tuple = None
    text_colours: tuple = ()
    ink_colours: object = None


# ── small numpy helpers ───────────────────────────────────────────────────

def _box_blur(a, r, axis):
    if r < 1:
        return a
    n = a.shape[axis]
    # Zero-padded running sum along `axis` (slices, not np.pad/np.take:
    # same numbers, a fraction of the overhead on these small arrays).
    shape = list(a.shape)
    shape[axis] = n + 2 * r + 1
    padded = np.zeros(shape, np.float32)
    inner = [slice(None)] * a.ndim
    inner[axis] = slice(r + 1, r + 1 + n)
    padded[tuple(inner)] = a
    c = np.cumsum(padded, axis=axis, dtype=np.float32)
    hi, lo = [slice(None)] * a.ndim, [slice(None)] * a.ndim
    hi[axis], lo[axis] = slice(2 * r + 1, 2 * r + 1 + n), slice(0, n)
    return (c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)


def _box_radius(sigma):
    return max(1, int(round((math.sqrt(4 * sigma * sigma + 1) - 1) / 2)))


def _blur(a, sigma):
    """Gaussian approximated by three box passes per axis."""
    if sigma < 0.5:
        return a
    r = _box_radius(sigma)
    for _ in range(3):
        a = _box_blur(_box_blur(a, r, 0), r, 1)
    return a


def _blur_support(sigma):
    """How far (in array px) _blur spreads anything: exactly zero beyond."""
    return 0 if sigma < 0.5 else 3 * _box_radius(sigma)


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
    return _NEUTRAL_DARK if style.tint else tuple(style.shadow_rgb)


def _hsv_rgb(h, s, v):
    """colorsys.hsv_to_rgb over arrays."""
    i = np.floor(h * 6.0) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    sel = [i == n for n in range(6)]
    return np.stack([np.select(sel, c) for c in
                     ((v, q, p, p, t, v), (t, v, v, q, p, p), (p, p, t, v, v, q))], axis=-1)


def _rgb_hsv(rgb):
    """colorsys.rgb_to_hsv over an (..., 3) array."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, (g - b) / d, np.where(mx == g, 2 + (b - r) / d, 4 + (r - g) / d))
    return (h / 6.0) % 1.0, np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0), mx


def _tint_colours(rgb, style=None):
    """dark_of and light_of over an (..., 3) array of straight colours, as
    one (..., 6) array: the shadow colour, then its rim colour."""
    k = np.clip((rgb.max(-1) - rgb.min(-1) - 0.12) / 0.25, 0, 1)[..., None]
    h, s, _v = _rgb_hsv(rgb)
    sat, val = (style.tint_saturation, style.tint_value) if style else (0.90, 0.26)
    cap = style.rim_saturation if style else 0.7
    dark = _hsv_rgb(h, np.full_like(h, sat), np.full_like(h, val))
    light = _hsv_rgb(h, np.minimum(s, cap), np.ones_like(h))
    return np.concatenate([np.asarray(_NEUTRAL_DARK, np.float32) * (1 - k) + dark * k,
                           np.asarray(_NEUTRAL_LIGHT, np.float32) * (1 - k) + light * k], -1)


@dataclass(frozen=True)
class InkColours:
    """An element's bitmap at 1/_FIELD_DOWN on the shared field grid: how
    much ink each cell holds and in which colour. Hashable — part of the
    shadow's cache key — so a colour change in the bitmap retints."""
    x: int          # screen px of cell (0, 0), a multiple of _FIELD_DOWN
    y: int
    w: int          # cells
    h: int
    data: bytes     # (h, w, 4) uint8 premultiplied BGRA, as cairo stores it


def ink_colours(content, rect):
    """InkColours of a layer bitmap `content` placed at rect (x, y, w, h)."""
    d = _FIELD_DOWN
    x, y = math.floor(rect[0] / d) * d, math.floor(rect[1] / d) * d
    w = int(math.ceil((rect[0] + rect[2] - x) / d))
    h = int(math.ceil((rect[1] + rect[3] - y) / d))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    cr.scale(1 / d, 1 / d)
    cr.translate(-x, -y)
    cr.set_source_surface(content, rect[0], rect[1])
    cr.get_source().set_filter(cairo.FILTER_GOOD)   # area average, not point samples
    cr.paint()
    surf.flush()
    px = np.ndarray((h, surf.get_stride() // 4, 4), np.uint8, surf.get_data())[:, :w]
    return InkColours(x, y, w, h, px.tobytes())


# How far one item's colour carries: the shadow right around an item takes
# the colour of the ink nearest it (white ink counts, as neutral), the far
# cloud the mix of what is near, and beyond all of it it is neutral.
_TINT_NEAR = 8.0    # sigma, px
_TINT_FAR = 28.0


def _local_tint(spec, x0, y0, w, h, down, style=None):
    """Straight (h, w, 6) colours over a grid at 1/down with origin (x0, y0):
    the shadow colour (dark_of) of the ink around each cell, then the rim
    colour (light_of) of the same ink — so the two always share a hue."""
    mw, mh = max(1, int(math.ceil(w / down))), max(1, int(math.ceil(h / down)))
    a = np.zeros((mh, mw), np.float32)
    rgb = np.zeros((mh, mw, 3), np.float32)
    ic = spec.ink_colours
    if ic is not None and down == _FIELD_DOWN:
        px = np.frombuffer(ic.data, np.uint8).reshape(ic.h, ic.w, 4).astype(np.float32) / 255.0
        cx, cy = (ic.x - x0) // down, (ic.y - y0) // down
        sx0, sy0 = max(0, -cx), max(0, -cy)
        sx1, sy1 = min(ic.w, mw - cx), min(ic.h, mh - cy)
        if sx1 > sx0 and sy1 > sy0:
            src = px[sy0:sy1, sx0:sx1]
            ca = src[..., 3]
            a[cy + sy0:cy + sy1, cx + sx0:cx + sx1] = ca
            rgb[cy + sy0:cy + sy1, cx + sx0:cx + sx1] = (
                src[..., [2, 1, 0]] / np.maximum(ca, 1e-6)[..., None])
    else:
        # No bitmap to read: each text box in its legend's colour.
        for box, colour in zip(spec.text_boxes, spec.text_colours or (None,) * len(spec.text_boxes)):
            m = _mask(GroupShadowSpec(text_boxes=(box,)), x0, y0, w, h, down, 0, 0, 0)
            a = np.maximum(a, m)
            rgb[m > 0] = colour if colour is not None else (1.0, 1.0, 1.0)
    neutral = np.asarray(_NEUTRAL_DARK + _NEUTRAL_LIGHT, np.float32)
    out = np.empty((mh, mw, 6), np.float32)
    out[...] = neutral
    inked = a > 0
    if not inked.any():
        return out
    # Only the window the ink can reach is mixed; beyond it, neutral.
    rows, cols = np.nonzero(inked.any(1))[0], np.nonzero(inked.any(0))[0]
    m = 2 * _blur_support(_TINT_FAR / down / 2) + 4
    r0, r1 = max(0, rows[0] - m), min(mh, rows[-1] + 1 + m)
    c0, c1 = max(0, cols[0] - m), min(mw, cols[-1] + 1 + m)
    a, rgb, inked = a[r0:r1, c0:c1], rgb[r0:r1, c0:c1], inked[r0:r1, c0:c1]
    wh, ww = a.shape
    # Weight and weighted colour blurred together (axes 0, 1 of one stack).
    stack = np.zeros((wh, ww, 7), np.float32)
    stack[..., 0] = a
    stack[inked, 1:] = a[inked, None] * _tint_colours(np.clip(rgb[inked], 0, 1), style)
    # The far mix is smooth: blurred at half the grid's resolution.
    ph, pw = wh + wh % 2, ww + ww % 2
    half = np.pad(stack, ((0, ph - wh), (0, pw - ww), (0, 0)))
    half = half.reshape(ph // 2, 2, pw // 2, 2, 7).mean(axis=(1, 3))
    far = _blur(half, _TINT_FAR / down / 2).repeat(2, 0).repeat(2, 1)
    far = _box_blur(_box_blur(far, 1, 0), 1, 1)[:wh, :ww]
    mixed = _blur(stack, _TINT_NEAR / down) + 0.05 * far
    out[r0:r1, c0:c1] = (mixed[..., 1:] + 1e-4 * neutral) / (mixed[..., :1] + 1e-4)
    return out


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


def _mask(spec, x0, y0, w, h, down, grow, padx, pady, with_text=True, radius=-1.0):
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
            _rrect(cr, x - padx, y - pady, tw + 2 * padx, bh,
                   min(bh / 2, 10 + pady) if radius < 0 else min(bh / 2, radius))
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


def _field_reach(style):
    """Screen px the bleed field can spread past an element's bounds: its
    grown shapes or padded legend plates (see group_shadow), plus the
    blur's full support."""
    grown = max(style.bleed_grow, style.legend_padx + 4, style.legend_pady + 3)
    return grown + _blur_support(style.bleed_blur / _FIELD_DOWN) * _FIELD_DOWN + _FIELD_DOWN


def _core_reach(style):
    """Screen px the shadow slot (core plate, edge, glow, rim) can spread
    past an element's bounds. The glow and rim are drawn shifted back by the
    drop offset, so it adds to theirs."""
    plate = (max(style.core_grow, style.legend_padx, style.legend_pady)
             + _blur_support(style.core_blur / _CORE_DOWN) * _CORE_DOWN)
    edge = 2.2 * style.edge_radius + 2 + (10 if style.legend == "glyph" else 0)
    off = max(abs(style.offset_x), abs(style.offset_y))
    glow = (_blur_support(style.glow_radius / _GLOW_DOWN) + 2) * _GLOW_DOWN + off \
        if style.glow_alpha > 0 else 0
    # +24: headroom, from when the centre painted its glass pills' shadow
    # into this slot; kept so every slot stays the size it was.
    return max(plate, edge, glow, 6 + off) + 24


def group_shadow(spec, style):
    """The cached, per-element part of the shadow (core plate, bleed field,
    tint, rim). None for an element with nothing to cast a shadow."""
    key = (spec, style)
    hit = _group_cache.get(key)
    if hit is not None or key in _group_cache:
        return hit
    if style.profile == "sdf":
        return _sdf_group_shadow(spec, style)
    b = _spec_bounds(spec)
    if b is None:
        _group_cache[key] = None
        return None
    # Each grid covers everything its layer can spread to, so the layer
    # fades out inside it (see _field_reach / _core_reach). The field is
    # snapped to the field grid so elements combine on one shared grid.
    x0, y0, w, h = _grid(b, _field_reach(style), _FIELD_DOWN)
    core_rect = _grid(b, _core_reach(style), _CORE_DOWN)

    # In "glyph" mode the legend's core comes from the letters themselves
    # (see edge_shadow); the plate is shapes only.
    core = _mask(spec, *core_rect, _CORE_DOWN, style.core_grow,
                 style.legend_padx, style.legend_pady, with_text=style.legend == "line",
                 radius=style.plate_radius)
    core = np.clip(_blur(core, style.core_blur / _CORE_DOWN) * style.core_gain, 0, 1) * style.core_alpha

    field = _mask(spec, x0, y0, w, h, _FIELD_DOWN, style.bleed_grow,
                  style.legend_padx + 4, style.legend_pady + 3, radius=style.plate_radius)
    field = _blur(field, style.bleed_blur / _FIELD_DOWN)

    # Shadow and rim colours, local to each item; the rim takes the light
    # side of the local hue even when the shadow itself stays untinted.
    colours = (_local_tint(spec, x0, y0, w, h, _FIELD_DOWN, style)
               if style.tint or style.rim_alpha > 0 else None)
    tint = colours[..., :3] if style.tint else None
    plain = None
    if tint is None and tuple(style.shadow_rgb) != (0.0, 0.0, 0.0):
        plain = np.empty(field.shape + (3,), np.float32)
        plain[...] = style.shadow_rgb
    gs = GroupShadow(x0, y0, w, h, _alpha_surface(field, tint if tint is not None else plain),
                     core_rect, _alpha_surface(core),
                     _alpha_surface(np.ones(tint.shape[:2], np.float32), tint)
                     if tint is not None else None,
                     _rim(spec, style, (colours[..., 3:], x0, y0) if colours is not None else None),
                     field)
    if len(_group_cache) > 160:
        _group_cache.clear()
    _group_cache[key] = gs
    return gs


def _edt(inside, cap):
    """Euclidean distance (in cells) from every cell to the nearest True
    cell of `inside`, exact up to `cap` cells and `cap` beyond: a column
    pass, then per row the minimum over horizontal shifts within cap."""
    h, w = inside.shape
    g = np.where(inside, np.float32(0), np.float32(cap)).astype(np.float32)
    for y in range(1, h):
        np.minimum(g[y], g[y - 1] + 1, out=g[y])
    for y in range(h - 2, -1, -1):
        np.minimum(g[y], g[y + 1] + 1, out=g[y])
    g2 = g * g
    out = g2.copy()
    for k in range(1, min(cap, w - 1) + 1):
        k2 = np.float32(k * k)
        np.minimum(out[:, k:], g2[:, :-k] + k2, out=out[:, k:])
        np.minimum(out[:, :-k], g2[:, k:] + k2, out=out[:, :-k])
    return np.sqrt(np.minimum(out, np.float32(cap * cap)))


def _sdf_mask(spec, x0, y0, w, h, down, style, dx=0.0, dy=0.0):
    """The element's plate as a filled mask: its shapes grown by core_grow,
    each legend line on a plate padded by legend_padx/pady — rounded or
    chamfered. (dx, dy) moves the content within the grid."""
    m = _mask(GroupShadowSpec(spec.parts, spec.rrects), x0 - dx, y0 - dy, w, h, down,
              style.core_grow, 0, 0, with_text=False)
    if style.legend != "line" or not spec.text_boxes:
        return m
    mw, mh = m.shape[1], m.shape[0]
    surf = cairo.ImageSurface(cairo.FORMAT_A8, mw, mh)
    cr = cairo.Context(surf)
    cr.scale(1 / down, 1 / down)
    cr.translate(-(x0 - dx), -(y0 - dy))
    px, py = style.legend_padx, style.legend_pady
    for x, y, tw, th in spec.text_boxes:
        bx, by, bw, bh = x - px, y - py, tw + 2 * px, th + 2 * py
        if style.plate_shape == "chamfer":
            c = min(bh / 2, max(style.plate_radius, 0) if style.plate_radius >= 0 else 7)
            cr.move_to(bx + c, by)
            cr.line_to(bx + bw, by)
            cr.line_to(bx + bw, by + bh - c)
            cr.line_to(bx + bw - c, by + bh)
            cr.line_to(bx, by + bh)
            cr.line_to(bx, by + c)
            cr.close_path()
        else:
            _rrect(cr, bx, by, bw, bh,
                   bh / 2 if style.plate_radius < 0 else min(bh / 2, style.plate_radius))
        cr.fill()
    surf.flush()
    t = np.ndarray((mh, surf.get_stride()), np.uint8, surf.get_data())[:, :mw]
    return np.maximum(m, t.astype(np.float32) / 255.0)


def _signed(m, down, reach, inner=0.0):
    """Signed screen-px distance to the edge of mask `m` (negative inside),
    exact out to `reach` px outside and `inner` px inside (0: inside is 0)."""
    inside = m >= 0.5
    d = _edt(inside, int(math.ceil(reach / down)) + 2) * down
    if inner > 0:
        d = np.where(inside, -_edt(~inside, int(math.ceil(inner / down)) + 2) * down, d)
    # The true edge lies about half a cell between the two sides' centres;
    # a one-cell blur takes out the staircase of the thresholded mask.
    # (Padded with its own border values: _blur pads with zeros, which
    # would pull the distance down at the grid's edge.)
    d = np.pad(d - np.where(inside, -down * 0.5 if inner > 0 else 0.0, down * 0.5), 4, mode="edge")
    return _blur(d, 1.0)[4:-4, 4:-4]


def _upsample(a, down, w, h):
    """Bilinear upsampling of a grid at 1/down (cell centres) to (h, w)."""
    ys = (np.arange(h, dtype=np.float32) + 0.5) / down - 0.5
    xs = (np.arange(w, dtype=np.float32) + 0.5) / down - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, a.shape[0] - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, a.shape[1] - 1)
    y1 = np.minimum(y0 + 1, a.shape[0] - 1)
    x1 = np.minimum(x0 + 1, a.shape[1] - 1)
    fy = np.clip(ys - y0, 0, 1)[:, None]
    fx = np.clip(xs - x0, 0, 1)[None, :]
    rows = a[y0] * (1 - fy) + a[y1] * fy
    return rows[:, x0] * (1 - fx) + rows[:, x1] * fx


def _plate_overlay(sd, rect, style):
    """Full-resolution plate details — its contour and scanlines — from the
    plate's signed distance at 1/_CORE_DOWN: (surface, x, y) or None. Drawn
    in the rim's slot, so it stays on the shapes under an offset."""
    bw, (br, bg, bb, ba) = style.plate_border_width, style.plate_border
    if ba <= 0 and style.plate_lines <= 0:
        return None
    x, y, w, h = (int(v) for v in rect)
    d = _upsample(sd, _CORE_DOWN, w, h)
    alpha = np.zeros((h, w), np.float32)
    rgb = np.zeros((h, w, 3), np.float32)
    if style.plate_lines > 0:
        inside = np.clip(0.5 - d, 0, 1)
        rows = ((np.arange(h) + y) % 3 == 0).astype(np.float32)[:, None]
        alpha = inside * rows * style.plate_lines
        rgb[...] = style.shadow_rgb
    if ba > 0:
        ring = np.clip(bw / 2 + 0.5 - np.abs(d + bw / 2), 0, 1) * ba
        if style.plate_lines > 0:
            under = alpha * (1 - ring)
            rgb = (rgb * under[..., None] + np.array((br, bg, bb), np.float32)
                   * ring[..., None]) / np.maximum(under + ring, 1e-6)[..., None]
            alpha = ring + under
        else:
            rgb[...] = (br, bg, bb)
            alpha = ring
    return _alpha_surface(alpha, rgb), x, y


def _sdf_group_shadow(spec, style):
    """group_shadow for profile = "sdf": plate and veil as curves of the
    distance to the element's plate (see ShadowStyle). The veil field is
    exp(-distance / bleed_curve), so the merge pass adds neighbours' fields
    — an exponential smooth-min — and the curve ends at bleed_reach."""
    key = (spec, style)
    b = _spec_bounds(spec)
    if b is None:
        _group_cache[key] = None
        return None
    soft = max(style.core_soft, 0.5)
    pad = max(style.legend_padx, style.legend_pady, style.core_grow)
    shift = max(abs(style.bleed_dx), abs(style.bleed_dy))
    x0, y0, w, h = _grid(b, pad + style.bleed_reach + shift + 4 * _FIELD_DOWN, _FIELD_DOWN)
    core_rect = _grid(b, pad + soft + 24, _CORE_DOWN)

    sd = _signed(_sdf_mask(spec, *core_rect, _CORE_DOWN, style), _CORE_DOWN,
                 soft + 4, soft / 2 + style.plate_border_width + 4)
    t = np.clip(sd / soft + 0.5, 0.0, 1.0)
    core = (1.0 - t * t * (3.0 - 2.0 * t)) * style.core_alpha

    fd = np.maximum(_signed(_sdf_mask(spec, x0, y0, w, h, _FIELD_DOWN, style,
                                      style.bleed_dx, style.bleed_dy), _FIELD_DOWN,
                            style.bleed_reach + 2 * _FIELD_DOWN), 0.0)
    # Past bleed_reach the curve maps the field to nothing anyway; there it
    # tapers to exactly 0 before the grid's border, so neighbours' fields,
    # which add, never meet a cut edge.
    taper = np.clip((style.bleed_reach + 1.5 * _FIELD_DOWN - fd) / _FIELD_DOWN, 0.0, 1.0)
    field = (np.exp(-fd / max(style.bleed_curve, 1e-3)) * taper).astype(np.float32)

    tint = _tint_map(spec, x0, y0, w, h, _FIELD_DOWN, style) if style.tint else None
    veil = None
    if style.bleed_rgb:
        veil = np.empty(field.shape + (3,), np.float32)
        veil[...] = style.bleed_rgb
    elif tint is not None:
        veil = tint
    elif tuple(style.shadow_rgb) != (0.0, 0.0, 0.0):
        veil = np.empty(field.shape + (3,), np.float32)
        veil[...] = style.shadow_rgb
    gs = GroupShadow(x0, y0, w, h, _alpha_surface(field, veil),
                     core_rect, _alpha_surface(core),
                     _alpha_surface(np.ones(tint.shape[:2], np.float32), tint)
                     if tint is not None else None,
                     _plate_overlay(sd, core_rect, style), field)
    if len(_group_cache) > 160:
        _group_cache.clear()
    _group_cache[key] = gs
    return gs


def _tint_map(spec, x0, y0, w, h, down, style=None):
    """Straight (h, w, 3) shadow colour over an element's grid: around each
    item the dark counterpart of its own colour, neutral around white and
    grey ones (see _local_tint)."""
    return _local_tint(spec, x0, y0, w, h, down, style)[..., :3]


def _rim(spec, style, tint=None):
    """The quiet light line just outside an element's shapes, at 1 px per
    screen px — (surface, x, y) or None. Its colour is the light side of the
    shadow's own hue right there: `tint`, (rgb, x, y) of the field-grid rim
    colours from _local_tint, or neutral."""
    if style.rim_alpha <= 0 or not (spec.parts or spec.rrects):
        return None
    b = _spec_bounds(GroupShadowSpec(spec.parts, spec.rrects))
    x0, y0 = math.floor(b[0]) - 6, math.floor(b[1]) - 6
    w, h = math.ceil(b[2]) + 6 - x0, math.ceil(b[3]) + 6 - y0
    sil = _mask(GroupShadowSpec(spec.parts, spec.rrects), x0, y0, w, h, 1, 0, 0, 0)
    ring = np.clip(_blur(sil, 1.2) * 2.0, 0, 1) * (1 - sil) * style.rim_alpha
    if tint is None:
        rgb = np.empty(ring.shape + (3,), np.float32)
        rgb[...] = _NEUTRAL_LIGHT
        return _alpha_surface(ring, rgb), x0, y0
    rgb, tx, ty = tint
    light = _alpha_surface(np.ones(rgb.shape[:2], np.float32), rgb)
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(out)
    cr.translate(-x0, -y0)
    cr.set_source(_placed(light, tx, ty, _FIELD_DOWN))
    cr.mask_surface(_alpha_surface(ring), x0, y0)
    return out, x0, y0


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
        cr.set_source_rgb(*style.shadow_rgb)
    cr.mask(_placed(gs.core_surface, cx, cy, _CORE_DOWN))
    # The layer is placed offset as a whole (a drop shadow); what has to
    # stay on its shapes is drawn shifted back.
    ox, oy = style.offset_x, style.offset_y
    if content is not None:
        if style.glow_alpha > 0:
            draw_glow(cr, content, content_rect[0] - ox, content_rect[1] - oy, style,
                      tuple((bx - ox, by - oy, bw, bh) for bx, by, bw, bh in spec.text_boxes),
                      style.glow_text_alpha if style.glow_text else 0.0)
        draw_edge_shadow(cr, content, content_rect[0], content_rect[1], style, spec.text_boxes)
    if gs.rim is not None:
        rim, rx, ry = gs.rim
        cr.set_source_surface(rim, rx - ox, ry - oy)
        cr.paint()
    return ((surf, cx + ox, cy + oy, cw, ch),
            (gs.field_surface, gs.x + ox, gs.y + oy, gs.w, gs.h))


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


def _stamp(cr, content, x, y, offsets, rgb=(0.0, 0.0, 0.0)):
    """Union (max) of `content`'s alpha (placed at x, y) shifted by every
    offset — a dilation. Each shift is resampled by cairo/pixman; the union
    is taken in numpy, since painting the shifts over each other would
    stack a translucent fill (a 14 % badge) into a dark slab."""
    sx = content.get_device_scale()[0]
    m = int(math.ceil(max(max(abs(dx), abs(dy)) for dx, dy in offsets) * sx)) + 1
    w, h = content.get_width() + 2 * m, content.get_height() + 2 * m
    alpha = cairo.ImageSurface(cairo.FORMAT_A8, content.get_width(), content.get_height())
    alpha.set_device_scale(sx, sx)
    acr = cairo.Context(alpha)
    acr.set_operator(cairo.OPERATOR_SOURCE)
    acr.set_source_surface(content, 0, 0)
    acr.paint()
    shifted = cairo.ImageSurface(cairo.FORMAT_A8, w, h)
    shifted.set_device_scale(sx, sx)
    scr = cairo.Context(shifted)
    scr.set_operator(cairo.OPERATOR_SOURCE)
    union = None
    for dx, dy in offsets:
        # SOURCE over the whole surface: the shifted copy, zero around it.
        scr.set_source_surface(alpha, m / sx + dx, m / sx + dy)
        scr.paint()
        shifted.flush()
        a = np.ndarray((h, shifted.get_stride()), np.uint8, shifted.get_data())[:, :w]
        union = a.copy() if union is None else np.maximum(union, a, out=union)
    out = np.ndarray((h, shifted.get_stride()), np.uint8, shifted.get_data())
    out[:, :w] = union
    shifted.mark_dirty()
    cr.push_group()
    cr.set_source_rgba(*rgb, 1)
    cr.mask_surface(shifted, x - m / sx, y - m / sx)
    cr.pop_group_to_source()


def draw_edge_shadow(cr, content, x, y, style, text_boxes=()):
    """Tight shadow along every stroke and glyph of `content` (a cached
    layer's ARGB surface), drawn into `cr` at the layer's own position.
    In "glyph" legend mode the text additionally gets a wider, letter-shaped
    plate — clipped to the text boxes, so lines and outlines keep only the
    tight edge."""
    r = style.edge_radius
    if style.edge_alpha > 0:
        _stamp(cr, content, x, y, [(0, 0)] + _ring(r, 8), style.shadow_rgb)
        cr.paint_with_alpha(style.edge_alpha)
        _stamp(cr, content, x, y, _ring(r * 2.2, 12), style.shadow_rgb)
        cr.paint_with_alpha(style.edge_alpha * 0.35)
    if style.legend == "glyph" and text_boxes:
        cr.save()
        for bx, by, bw, bh in text_boxes:
            cr.rectangle(bx - 12, by - 10, bw + 24, bh + 20)
        cr.clip()
        for rad, n, a in ((3, 12, style.core_alpha), (6, 16, style.core_alpha * 0.55),
                          (10, 20, style.core_alpha * 0.3)):
            _stamp(cr, content, x, y, _ring(rad, n), style.shadow_rgb)
            cr.paint_with_alpha(a)
        cr.restore()


# ── neon glow ─────────────────────────────────────────────────────────────

_GLOW_DOWN = 2


def draw_glow(cr, content, x, y, style, text_boxes=(), text=0.0):
    """Soft halo in the content's own colour around its coloured strokes —
    outlines, callout lines, dots: the neon tubes. Ink inside text_boxes
    glows at `text` × that strength (0 by default: a halo fills the gaps
    between letters and blurs them). White and light-grey ink glows white
    at style.glow_neutral × the strength; dark ink never. `content` is a
    cached layer's ARGB surface placed at (x, y); the halo is computed at
    1/_GLOW_DOWN of its device pixels."""
    content.flush()
    sx = content.get_device_scale()[0]
    w, h = content.get_width(), content.get_height()
    px = np.ndarray((h, content.get_stride() // 4, 4), np.uint8,
                    content.get_data())[:h:_GLOW_DOWN, :w:_GLOW_DOWN].astype(np.float32) / 255.0
    a = px[..., 3]
    rgb = px[..., [2, 1, 0]] / np.maximum(a, 1e-6)[..., None]
    k = np.clip((rgb.max(axis=2) - rgb.min(axis=2) - 0.12) / 0.25, 0.0, 1.0)
    if style.glow_neutral > 0:
        light = np.clip((rgb.max(axis=2) - 0.55) / 0.3, 0.0, 1.0)
        k = np.maximum(k, (1.0 - k) * light * style.glow_neutral)
    k *= a
    for bx, by, bw, bh in text_boxes:
        # text boxes are in the same logical px as (x, y)
        f = sx / _GLOW_DOWN
        c0, r0 = max(0, int((bx - x) * f) - 1), max(0, int((by - y) * f) - 1)
        c1, r1 = int((bx + bw - x) * f) + 2, int((by + bh - y) * f) + 2
        k[r0:r1, c0:c1] *= text
    if not k.any():
        return
    sigma = style.glow_radius * sx / _GLOW_DOWN
    # The halo spreads past the bitmap (whose ink runs to within 2 px of its
    # edge): computed on a canvas grown by the blur's full reach, so it
    # fades out instead of being cut where the bitmap ends.
    p = _blur_support(sigma) + 1
    k = np.pad(k, p)
    rgb = np.pad(rgb, ((p, p), (p, p), (0, 0)))
    kb = _blur(k, sigma)
    col = np.stack([_blur(rgb[..., i] * k, sigma) for i in range(3)], axis=2)
    col /= np.maximum(kb, 1e-6)[..., None]
    # Full brightness, so the halo reads as light, not as a stain.
    col /= np.maximum(col.max(axis=2), 1e-6)[..., None]
    halo = _alpha_surface(np.clip(kb * 4.0, 0.0, 1.0) * style.glow_alpha, col)
    cr.save()
    cr.translate(x - p * _GLOW_DOWN / sx, y - p * _GLOW_DOWN / sx)
    cr.scale(_GLOW_DOWN / sx, _GLOW_DOWN / sx)
    pat = cairo.SurfacePattern(halo)
    pat.set_filter(cairo.FILTER_BILINEAR)
    cr.set_source(pat)
    cr.paint()
    cr.restore()
