"""
renderer.py — Drawing orchestrator: HUD frame, title bar, SVG layers.
Delegates to callouts and center_strip for the data-driven parts.
"""

import gi
gi.require_version('Rsvg', '2.0')
from gi.repository import Rsvg
import math

from layout import (HUD_W, HUD_H, _TITLE_H, _PAD, _FX, _FY, _FDW, _SVG_H, _BX, _BY, _BDW,
                    _PAUSE_W, _PAUSE_H, _PAUSE_X, _PAUSE_Y)
from helpers import _rrect, _txt, _pill_row, C_MOD, C_LAYER
from callouts import draw_callouts, _btn_short
from center_strip import draw_center_strip


def draw_hud(cr, front_svg, back_svg, state, hover_t=0.0):
    # Background
    cr.set_source_rgba(0.031, 0.031, 0.071, 0.88)
    _rrect(cr, 0, 0, HUD_W, HUD_H, 18)
    cr.fill()

    # Border
    cr.set_source_rgba(1, 1, 1, 0.12)
    cr.set_line_width(1.0)
    _rrect(cr, 0, 0, HUD_W, HUD_H, 18)
    cr.stroke()

    _draw_title(cr, state, hover_t)
    _draw_breadcrumbs(cr, state)
    _draw_svgs(cr, front_svg, back_svg)
    draw_center_strip(cr, state)
    draw_callouts(cr, state)


def _draw_title(cr, state, hover_t=0.0):
    ctx    = state.get("context", {})
    stack  = ctx.get("config_stack") or ["—"]
    paused = ctx.get("paused", False)

    cr.set_source_rgba(1, 1, 1, 1.0)
    _txt(cr, _PAD, _TITLE_H / 2, "Deckery", 13, va="mid")

    cr.set_source_rgba(1, 1, 1, 0.4)
    _txt(cr, _PAD + 80, _TITLE_H / 2, "HUD", 11, va="mid")

    # Pause / Resume badge — centred in the title bar
    if paused:
        r, g, b = 1.0, 0.78, 0.2    # amber
        label   = "⏸  Controls Paused"
    else:
        r, g, b = 0.27, 0.87, 0.44  # green
        label   = "⏵  Controls Active"

    # t=0: faint fill, no border   t=1: stronger fill + border
    t     = hover_t
    bg_a  = 0.05 + 0.17 * t
    bdr_a = 0.70 * t
    txt_a = 0.60 + 0.35 * t

    cr.set_source_rgba(r, g, b, bg_a)
    _rrect(cr, _PAUSE_X, _PAUSE_Y, _PAUSE_W, _PAUSE_H, 6)
    cr.fill()
    # if bdr_a > 0.01:
    #     cr.set_source_rgba(r, g, b, bdr_a)
    #     cr.set_line_width(1.0)
    #     _rrect(cr, _PAUSE_X, _PAUSE_Y, _PAUSE_W, _PAUSE_H, 6)
    #     cr.stroke()
    cr.set_source_rgba(r, g, b, txt_a)
    _txt(cr, HUD_W / 2, _TITLE_H / 2, label, 10, ha="center", va="mid")

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


def _draw_breadcrumbs(cr, state):
    """
    Pill row centred between title bar and front SVG.
    All pills share the same visual style: subtle coloured fill + coloured text.
    Stack[0] = base config → neutral white.
    Stack[1+] = context layers → teal.
    Modifiers → amber.
    """
    ctx   = state.get("context", {})
    stack = ctx.get("config_stack") or ["—"]
    mods  = [_btn_short(m) for m in ctx.get("held_modifiers", [])]

    labels = stack + mods
    styles = (
        [((1, 1, 1, 0.06),        (1, 1, 1,    0.80))]                      +  # stack[0]: base, zurückhaltend
        [((*C_LAYER, 1.0),        (0, 0, 0,    1.0 ))] * max(0, len(stack) - 1) +  # stack[1+]: teal, solid
        [((*C_MOD,   1.0),        (0, 0, 0,    1.0 ))] * len(mods)              # mods: amber, solid
    )
    # "›" between stack entries and into first mod; no glyph between mod pills
    n_gaps = max(0, len(labels) - 1)
    seps   = ["›" if i < len(stack) else "" for i in range(n_gaps)]

    cx = HUD_W / 2
    cy = (_TITLE_H + _FY) / 2
    _pill_row(
        cr, cx, cy, labels,
        sep=seps, size=9,
        border=None,
        sep_rgba=(1.0, 1.0, 1.0, 0.55),
        ha="center",
        styles=styles,
    )


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
