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
from trackpads import draw_trackpads


def draw_hud(cr, front_svg, back_svg, state, hover_t=0.0, osd_enabled=False, remapping_enabled=True):
    # Drop shadow — multi-pass approximation of Gaussian blur
    _shadow_steps = 12
    for i in range(_shadow_steps, 0, -1):
        t     = i / _shadow_steps          # 1.0 (outermost) → ~0.08 (innermost)
        spread = i * 3.5
        alpha  = 0.055 * (1.0 - t ** 0.6)
        cr.set_source_rgba(0, 0, 0, alpha)
        _rrect(cr, -spread, -spread + i * 1.2,
               HUD_W + spread * 2, HUD_H + spread * 2, 18 + spread)
        cr.fill()

    # Background
    cr.set_source_rgba(0.031, 0.031, 0.071, 0.88)
    _rrect(cr, 0, 0, HUD_W, HUD_H, 18)
    cr.fill()

    _draw_title(cr, state, hover_t, osd_enabled, remapping_enabled)
    _draw_breadcrumbs(cr, state)
    _draw_svgs(cr, front_svg, back_svg)
    draw_trackpads(cr, state)
    draw_center_strip(cr, state)
    draw_callouts(cr, state)


def _draw_title(cr, state, hover_t=0.0, osd_enabled=False, remapping_enabled=True):
    ctx    = state.get("context") or {}
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

    # Remapping toggle button — left of OSD button
    _RMP_W, _RMP_H = 48, 20
    _OSD_W, _OSD_H = 48, 20
    _OSD_X = HUD_W - 28 - 16 - _OSD_W
    _RMP_X = _OSD_X - 8 - _RMP_W
    _RMP_Y = (_TITLE_H - _RMP_H) / 2
    _OSD_Y = (_TITLE_H - _OSD_H) / 2   # vertically centred in title bar

    if remapping_enabled:
        rmp_pill  = (1, 1, 1, 0.08)
        rmp_label = (1, 1, 1, 0.35)
        rmp_text  = "On"
    else:
        rmp_pill  = (0.95, 0.25, 0.25, 0.25)
        rmp_label = (0.95, 0.25, 0.25, 0.9)
        rmp_text  = "Off"
    _rrect(cr, _RMP_X, _RMP_Y, _RMP_W, _RMP_H, 4)
    cr.set_source_rgba(*rmp_pill)
    cr.fill()
    cr.set_source_rgba(*rmp_label)
    _txt(cr, _RMP_X + 8, _TITLE_H / 2, rmp_text, 8, ha="left", va="mid")
    dot_r = 3.0
    rmp_dot_x = _RMP_X + _RMP_W - 8 - dot_r
    rmp_dot_y = _TITLE_H / 2
    if remapping_enabled:
        cr.set_source_rgba(*rmp_label)
        cr.set_line_width(1.0)
        cr.new_sub_path()
        cr.arc(rmp_dot_x, rmp_dot_y, dot_r, 0, math.tau)
        cr.stroke()
    else:
        cr.set_source_rgba(*rmp_label)
        cr.arc(rmp_dot_x, rmp_dot_y, dot_r, 0, math.tau)
        cr.fill()

    # OSD toggle button — left of close button
    # Gap to close circle left edge (HUD_W-28) matches close circle's right margin (8px)
    if osd_enabled:
        pill_col  = (0.27, 0.87, 0.44, 0.25)
        label_col = (0.27, 0.87, 0.44, 0.9)
    else:
        pill_col  = (1, 1, 1, 0.08)
        label_col = (1, 1, 1, 0.35)
    _rrect(cr, _OSD_X, _OSD_Y, _OSD_W, _OSD_H, 4)
    cr.set_source_rgba(*pill_col)
    cr.fill()
    # "OSD" text left-aligned with 8px padding
    cr.set_source_rgba(*label_col)
    _txt(cr, _OSD_X + 8, _TITLE_H / 2, "OSD", 8, ha="left", va="mid")
    # Indicator dot — separate Cairo circle so it's properly vertically centred
    dot_r = 3.0
    dot_x = _OSD_X + _OSD_W - 8 - dot_r
    dot_y = _TITLE_H / 2
    if osd_enabled:
        cr.set_source_rgba(*label_col)
        cr.arc(dot_x, dot_y, dot_r, 0, math.tau)
        cr.fill()
    else:
        cr.set_source_rgba(*label_col)
        cr.set_line_width(1.0)
        cr.new_sub_path()
        cr.arc(dot_x, dot_y, dot_r, 0, math.tau)
        cr.stroke()

    # Close button ✕ — inset from corner so it sits in the flat part of the title bar
    cx, cy = HUD_W - 22, _TITLE_H / 2
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
    ctx   = state.get("context") or {}
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
