"""
icons.py — System symbolic icons (mouse clicks, keyboard), rendered via Rsvg
and recoloured on the fly, instead of hand-drawn cairo glyphs. On request:
these already exist in the Breeze icon theme (the project's own native DE),
mounted into the distrobox at /run/host, so there's no reason to redraw a
mouse or a keyboard by hand when the real icon set already covers it —
including the thing a hand-drawn glyph can't cheaply replicate, which button
on the mouse icon is actually filled in vs. just outlined.

Icons are rendered once per (name, pixel size) into an ARGB32 surface, then
reused forever as a *mask* — draw_icon() paints the caller's own flat colour
through that surface's alpha channel (cr.mask_surface), so the icon's own
baked-in SVG colours (Breeze's blue highlight, black outline, â€¦) never show
up; only its shape does. That's also what makes recolouring for "dimmed
when inactive" trivial: same cached surface, any alpha the caller wants.
"""

import glob
import os

import cairo
import gi
gi.require_version('Rsvg', '2.0')
from gi.repository import Rsvg

# Breeze (this project's native DE) first, Adwaita as a fallback for a
# generic/idle glyph if Breeze isn't mounted (e.g. running outside the
# distrobox, or on a non-Plasma host) — Adwaita doesn't have the
# click-left/click-right variants, so on that fallback those two simply
# don't resolve and the caller's own fallback (see renderer_split.py) kicks
# in instead of a missing icon.
_ICON_ROOTS = [
    ("/run/host/usr/share/icons/breeze", ["devices", "actions"]),
    ("/usr/share/icons/breeze", ["devices", "actions"]),
    ("/usr/share/icons/Adwaita/symbolic", ["devices", "actions"]),
]

_path_cache = {}
_surface_cache = {}


def _find_icon_path(name):
    if name in _path_cache:
        return _path_cache[name]
    found = None
    for root, cats in _ICON_ROOTS:
        for cat in cats:
            flat = os.path.join(root, cat, f"{name}.svg")
            if os.path.isfile(flat):
                found = flat
                break
            matches = sorted(glob.glob(os.path.join(root, cat, "*", f"{name}.svg")))
            if matches:
                found = matches[-1]
                break
        if found:
            break
    _path_cache[name] = found
    return found


def _render_icon_surface(name, size_px):
    path = _find_icon_path(name)
    if path is None:
        return None
    handle = Rsvg.Handle.new_from_file(path)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size_px, size_px)
    cr = cairo.Context(surf)
    rect = Rsvg.Rectangle()
    rect.x, rect.y, rect.width, rect.height = 0, 0, size_px, size_px
    handle.render_document(cr, rect)
    return surf


def get_icon_surface(name, size_px):
    """The cached, pre-rendered (but not yet coloured) icon surface, or None
    if `name` doesn't resolve in any known theme."""
    key = (name, size_px)
    if key not in _surface_cache:
        _surface_cache[key] = _render_icon_surface(name, size_px)
    return _surface_cache[key]


def draw_icon(cr, name, cx, cy, size_px, color):
    """Paint `name` at `size_px`, centred at (cx, cy), in `color` (RGBA) —
    recoloured via mask_surface, see module docstring. Returns False (and
    draws nothing) if the icon doesn't resolve, so callers can fall back."""
    surf = get_icon_surface(name, size_px)
    if surf is None:
        return False
    cr.save()
    cr.set_source_rgba(*color)
    cr.mask_surface(surf, cx - size_px / 2, cy - size_px / 2)
    cr.restore()
    return True
