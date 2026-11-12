"""
osd_look.py — The OSD's toast and pill row as finished sprites (B-21).

The pop animation (osd_anim.py) scales and fades whole sprites, so a toast or
a pill row is rasterized once — shadow and all — and every frame only paints
that bitmap under a transform. Text is never laid out again mid-animation
(the "dancing letters" a per-frame layout under a scale gives).

In the split design they speak the HUD's language (B-14, shadow.py): a toast
is a coloured legend on a plate tinted with a dark version of its colour,
with the soft cloud and the tight black edge; the glass pills keep their own
gentle shadow in the neutral tint (pill_shadow.py). In classic they look as
the slide animation draws them. Colours, pill material and shadow come from
the active theme (theme.py, B-20); every sprite is cached per theme.

Needs numpy (via shadow.py). No GTK.
"""

import math
from dataclasses import dataclass

import cairo
import numpy as np

from helpers import _pill_row, _txt_icon, _rrect, _K, capture_text_boxes
import theme
import pill_shadow
from shadow import (GroupShadowSpec, group_shadow_layers, neutral_rgb, _alpha_surface,
                    _bleed_curve, _FIELD_DOWN)
from toast import toast_label

TOAST_SIZE = 11     # the neon toast's legend: bold, a touch larger than a HUD callout
ICON_RATIO = 2.2    # an output pill's glyph canvas per pt of its text: 24 at 11 pt


@dataclass(frozen=True)
class Sprite:
    surface: object   # ARGB32 at the device scale it was built for
    x: float          # logical px of its top-left, relative to the element's centre
    y: float


def _raster(rec, dev_scale, pad=2):
    """A recording surface cut to its ink at device resolution, aligned to
    whole device pixels: (surface, (x, y, w, h)) in logical px."""
    ix, iy, iw, ih = rec.ink_extents()
    s = dev_scale
    x0, y0 = math.floor((ix - pad) * s), math.floor((iy - pad) * s)
    x1, y1 = math.ceil((ix + iw + pad) * s), math.ceil((iy + ih + pad) * s)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, x1 - x0), max(1, y1 - y0))
    surf.set_device_scale(s, s)
    cr = cairo.Context(surf)
    cr.translate(-x0 / s, -y0 / s)
    cr.set_source_surface(rec, 0, 0)
    cr.paint()
    surf.flush()
    return surf, (x0 / s, y0 / s, (x1 - x0) / s, (y1 - y0) / s)


def _record(draw):
    rec = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
    with capture_text_boxes() as cap:
        draw(cairo.Context(rec))
    return rec, cap


def _mapped_bleed(cr, bleed, style):
    """One element's cloud on its own: the pre-curve field mapped to its
    final alpha, keeping its tint (as shadow.paint_bleed does for the HUD's
    merged pass)."""
    surf, x, y, w, h = bleed
    surf.flush()
    fw, fh = surf.get_width(), surf.get_height()
    px = np.ndarray((fh, surf.get_stride() // 4, 4), np.uint8, surf.get_data())[:, :fw]
    a = px[..., 3].astype(np.float32) / 255.0
    rgb = px[..., [2, 1, 0]].astype(np.float32) / 255.0 / np.maximum(a, 1e-6)[..., None]
    # The field is cut at the edge of its grid; mapped on its own (in the
    # HUD the merged pass hides it) that cut would show as a faint box.
    # Fade the outer fifth on every side down to nothing.
    ramp = lambda n: np.clip(np.minimum(np.arange(n), np.arange(n)[::-1]) / (0.2 * n), 0, 1)
    edge = np.outer(ramp(fh), ramp(fw)).astype(np.float32)
    mapped = _alpha_surface(_bleed_curve(style, a) * edge * edge * (3 - 2 * edge), rgb)
    cr.save()
    cr.translate(x, y)
    cr.scale(w / fw, h / fh)
    cr.set_source_surface(mapped, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_BILINEAR)
    cr.paint()
    cr.restore()


def _sprite(compose, dev_scale):
    rec = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
    compose(cairo.Context(rec))
    surf, (x, y, _w, _h) = _raster(rec, dev_scale, pad=0)
    return Sprite(surf, x, y)


_cache = {}


def _cached(key, build):
    hit = _cache.get(key)
    if hit is None:
        if len(_cache) > 24:
            _cache.clear()
        hit = _cache[key] = build()
    return hit


def toast_sprite(la, split, style, dev_scale=1.0):
    """A toast for last_action `la`, centred on (0, 0)."""
    label, col = toast_label(la)
    return _cached(("toast", label, col, split, style, dev_scale, theme.current()),
                   lambda: _neon_toast(label, col, style, dev_scale) if split
                   else _classic_toast(label, col, dev_scale))


def _classic_toast(label, col, dev_scale):
    def draw(cr):
        _pill_row(cr, 0, 0, [label], size=10, bg=(*col, 0.15), fg=(*col, 1.0),
                  border=(*col, 0.85), sep_rgba=(0, 0, 0, 0), ha="center")
    rec, _cap = _record(draw)
    return _sprite(lambda cr: (cr.set_source_surface(rec, 0, 0), cr.paint()), dev_scale)


def _neon_toast(label, col, style, dev_scale):
    def draw(cr):
        cr.set_source_rgb(*col)
        _txt_icon(cr, 0, 0, label, size=TOAST_SIZE, ha="center", va="mid", bold=True)
    rec, cap = _record(draw)
    content, rect = _raster(rec, dev_scale)
    spec = GroupShadowSpec(text_boxes=tuple(tuple(round(v) for v in b) for b in cap.boxes),
                           text_colours=tuple(cap.colours), ink=tuple(round(v) for v in rect))
    shadow, bleed = group_shadow_layers(spec, style, content, rect, dev_scale)

    def compose(cr):
        if bleed is not None:
            _mapped_bleed(cr, bleed, style)
        if shadow is not None:
            surf, sx, sy, _sw, _sh = shadow
            cr.set_source_surface(surf, sx, sy)
            cr.paint()
        cr.set_source_surface(content, rect[0], rect[1])
        cr.paint()
    return _sprite(compose, dev_scale)


# ── Output pills ────────────────────────────────────────────────────────────
# One pill per held output key (makima's active_outputs). Modifiers read as
# their symbol and name, a mouse button as the mouse with that side lit,
# any other key as the keyboard glyph and its name.

_MOD_LABEL = {
    "KEY_LEFTSHIFT": "⇧ Shift", "KEY_RIGHTSHIFT": "⇧ Shift",
    "KEY_LEFTMETA": "❖ Super",  "KEY_RIGHTMETA": "❖ Super",
    "KEY_LEFTALT": "⌥ Alt",     "KEY_RIGHTALT": "⌥ AltGr",
    "KEY_LEFTCTRL": "⌃ Ctrl",   "KEY_RIGHTCTRL": "⌃ Ctrl",
}
_CLICKS = ("BTN_LEFT", "BTN_RIGHT")


def output_keys(active_outputs, with_silent=False):
    """The keys to show pills for, from makima's active_outputs: plain
    strings or {key, silent, ...} dicts. Silent ones only `with_silent` —
    while the HUD is open (makima paused), where the row says what a press
    holds; with it closed silent keeps quiet, as it always did (B-26)."""
    def silent(e):
        return isinstance(e, dict) and e.get("silent", False)
    keys = (e.get("key", "") if isinstance(e, dict) else e
            for e in active_outputs or () if with_silent or not silent(e))
    return tuple(k for k in keys if k)


def pill_keys(ctx, over_hud):
    """The OSD's pill row for makima's state context: silent outputs too
    while it sits over the open HUD or makima is paused."""
    return output_keys(ctx.get("active_outputs"),
                       with_silent=over_hud or ctx.get("paused", False))


def output_label(key):
    """The text an output pill shows for `key` ("" for a mouse button,
    whose pill is the glyph alone)."""
    if key in _CLICKS:
        return ""
    return _MOD_LABEL.get(key) or _K.get(key, key.replace("KEY_", "").replace("BTN_", ""))


def pill_size(scale=1.0):
    """The output pills' text size in pt: the theme's, times `[osd] pill_scale`."""
    return theme.current().osd_pill_size * scale


def _draw_kbd_icon(cr, x, y, color, size):
    """Keyboard glyph, hand-drawn rather than themed (B-06): Breeze's
    input-keyboard-symbolic reads busier and heavier than the mouse beside
    it. This one shares the mouse's 1px outline: two rows of five 2x2 keys
    and a spacebar, built in whole *device* pixels so it stays crisp under
    fractional scaling (the Deck runs at 1.1). x is its left edge, y its
    vertical centre."""
    ds = cr.get_target().get_device_scale()[0]
    m = cr.get_matrix()
    cx = x + size / 2
    cr.save()
    if (m.xx, m.yx, m.xy, m.yy) == (1, 0, 0, 1):
        # Translation-only CTM: switch to device pixels and snap to them.
        cx, cy = (cx + m.x0) * ds, (y + m.y0) * ds
        cr.identity_matrix()
        cr.scale(1 / ds, 1 / ds)
        u = size * ds / 26
    else:
        cy, u = y, size / 26
    key, gap, lw = max(1, round(2 * u)), max(1, round(u)), max(1, round(u))
    hpad, vpad = round(2 * u), max(1, round(u))
    row_w = 5 * key + 4 * gap
    space_w = round(8 * u)
    space_w += (row_w - space_w) % 2  # keep it centred on whole pixels
    bw = row_w + 2 * (hpad + lw)
    bh = 3 * key + 2 * gap + 2 * (vpad + lw)
    bx, by = round(cx - bw / 2), round(cy - bh / 2)
    cr.set_source_rgba(*color)
    _rrect(cr, bx + lw / 2, by + lw / 2, bw - lw, bh - lw, 2 * u)
    cr.set_line_width(lw)
    cr.stroke()
    kx, ky = bx + lw + hpad, by + lw + vpad
    for row in range(2):
        for i in range(5):
            cr.rectangle(kx + i * (key + gap), ky + row * (key + gap), key, key)
    cr.rectangle(kx + (row_w - space_w) // 2, ky + 2 * (key + gap), space_w, key)
    cr.fill()
    cr.restore()


def draw_output_pills(cr, keys, size):
    """The output pill row for `keys`, centred on (0, 0)."""
    from renderer_split import _draw_click_icon   # Breeze mouse glyphs (B-16)
    t = theme.current()
    icon = round(size * ICON_RATIO)

    def click(k):
        return lambda cr, cx, cy: _draw_click_icon(cr, k, cx, cy, "center", t.pill_fg, size=icon)

    def kbd(cr, x, y):
        _draw_kbd_icon(cr, x, y, t.pill_fg, icon)

    _pill_row(cr, 0, 0, [output_label(k) for k in keys], sep="+", size=size,
              glass=t.glass, fg=t.pill_fg, border=t.pill_border,
              sep_rgba=(0.5, 0.5, 0.52, 0.9), ha="center",
              icons=[click(k) if k in _CLICKS else None for k in keys],
              prefix_icons=[None if k in _CLICKS or k in _MOD_LABEL else kbd for k in keys],
              icon_size=icon)


def pills_sprite(keys, style, dev_scale=1.0, size=None):
    """The active-outputs pill row for the output keys `keys`, centred on
    (0, 0), with its shadow."""
    t = theme.current()
    size = size or pill_size()

    def build():
        rec, cap = _record(lambda cr: draw_output_pills(cr, list(keys), size))

        def compose(cr):
            pill_shadow.paint(cr, cap.glass_boxes, rgb=neutral_rgb(style), strength=t.pill_shadow)
            cr.set_source_surface(rec, 0, 0)
            cr.paint()
        return _sprite(compose, dev_scale)
    return _cached(("pills", tuple(keys), size, style, dev_scale, t), build)


def paint(cr, sprite, cx, cy, scale=1.0, alpha=1.0, dev_scale=1.0):
    """Paint `sprite` with its centre at (cx, cy), scaled around that centre.
    The centre is snapped to the device pixel grid, so at rest (scale 1) the
    bitmap lands 1:1 and stays as sharp as it was built."""
    if alpha <= 0 or scale <= 0:
        return
    cx = round(cx * dev_scale) / dev_scale
    cy = round(cy * dev_scale) / dev_scale
    cr.save()
    cr.translate(cx, cy)
    if scale != 1.0:
        cr.scale(scale, scale)
    cr.set_source_surface(sprite.surface, sprite.x, sprite.y)
    cr.get_source().set_filter(cairo.FILTER_BILINEAR if scale != 1.0 else cairo.FILTER_NEAREST)
    cr.paint_with_alpha(alpha)
    cr.restore()
