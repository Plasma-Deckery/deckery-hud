"""
renderer.py — Drawing orchestrator: HUD frame, title bar, SVG layers.
Delegates to callouts and center_strip for the data-driven parts.
"""

import gi
gi.require_version('Rsvg', '2.0')
from gi.repository import Rsvg
import math

from layout import HUD_W, HUD_H, _TITLE_H, _PAD, _FX, _FY, _FDW, _SVG_H, _BX, _BY, _BDW
from helpers import _rrect, _txt
from callouts import draw_callouts
from center_strip import draw_center_strip


def draw_hud(cr, front_svg, back_svg, state):
    # Background
    cr.set_source_rgba(0.031, 0.031, 0.071, 0.88)
    _rrect(cr, 0, 0, HUD_W, HUD_H, 18)
    cr.fill()

    # Border
    cr.set_source_rgba(1, 1, 1, 0.12)
    cr.set_line_width(1.0)
    _rrect(cr, 0, 0, HUD_W, HUD_H, 18)
    cr.stroke()

    _draw_title(cr, state)
    _draw_svgs(cr, front_svg, back_svg)
    draw_center_strip(cr, state)
    draw_callouts(cr, state)


def _draw_title(cr, state):
    ctx    = state.get("context", {})
    stack  = ctx.get("config_stack") or ["—"]
    paused = ctx.get("paused", False)

    cr.set_source_rgba(1, 1, 1, 1.0)
    _txt(cr, _PAD, _TITLE_H / 2, "Deckery", 14, bold=True, va="mid")

    cr.set_source_rgba(1, 1, 1, 0.4)
    _txt(cr, _PAD + 80, _TITLE_H / 2, " → ".join(stack), 11, va="mid")

    # Paused indicator — centred in the title bar
    if paused:
        cr.set_source_rgba(1.0, 0.78, 0.2, 0.9)   # amber, matches modifier colour
        _txt(cr, HUD_W / 2, _TITLE_H / 2, "⏸ Controls Paused", 11, ha="center", va="mid")

    # Close button ✕
    cx, cy = HUD_W - 18, 15
    cr.set_source_rgba(1, 1, 1, 0.18)
    cr.arc(cx, cy, 10, 0, math.tau)
    cr.fill()
    cr.set_source_rgba(1, 1, 1, 0.7)
    cr.set_line_width(1.5)
    for dx, dy in ((-4, -4), (4, 4)), ((-4, 4), (4, -4)):
        cr.move_to(cx + dx[0], cy + dx[1])
        cr.line_to(cx + dy[0], cy + dy[1])
    cr.stroke()

    cr.set_source_rgba(1, 1, 1, 0.1)
    cr.set_line_width(0.5)
    cr.move_to(_PAD, _TITLE_H)
    cr.line_to(HUD_W - _PAD, _TITLE_H)
    cr.stroke()


def _draw_svgs(cr, front_svg, back_svg):
    for handle, x, y, w, h in (
        (front_svg, _FX, _FY, _FDW, _SVG_H),
        (back_svg,  _BX, _BY, _BDW, _SVG_H),
    ):
        vp = Rsvg.Rectangle()
        vp.x      = x
        vp.y      = y
        vp.width  = w
        vp.height = h
        handle.render_document(cr, vp)
