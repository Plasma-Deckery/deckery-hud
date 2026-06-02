"""
trackpads.py — Analog overlay: trackpads, sticks, triggers.
All position values from state are already normalized to -1.0…+1.0 (trackpads/sticks)
or 0.0…1.0 (triggers). No raw-value conversion needed.
"""

import math
from layout import _FX, _FY, _FS

# ── Trackpad bounds — front SVG viewBox 0 0 1024 414 ─────────────────────────
# Derived from the rounded-rect paths in steamdeckFront.svg
_LPAD = {"x": 98.86,  "y": 149.31, "w": 107.5, "h": 107.6}
_RPAD = {"x": 818.07, "y": 149.31, "w": 107.5, "h": 107.6}

# ── Stick centres — front SVG ─────────────────────────────────────────────────
# Three concentric circles per stick in steamdeckFront.svg:
#   r_fixed  ≈ 47.2  opacity=0.3  decorative outer ring — stays fixed
#   r_outer  ≈ 34.2              outer moving ring      ╮ move together;
#   r_inner  ≈ 23.6              inner moving disk      ╯ travel = r_fixed - r_outer ≈ 13
_LSTICK = {"cx": 163.669, "cy": 90.009, "r_fixed": 47.223, "r_outer": 34.167, "r_inner": 23.637}
_RSTICK = {"cx": 859.776, "cy": 90.559, "r_fixed": 47.223, "r_outer": 34.167, "r_inner": 23.637}

# Colours
_C_ACTIVE = (1.0, 0.78, 0.2)    # amber — stick active / trigger pressed


def draw_trackpads(cr, state):
    """Entry point called from renderer."""
    pads     = state.get("trackpads") or {}
    sticks   = state.get("sticks")   or {}
    _draw_pad(cr, pads.get("lpad", {}), _LPAD)
    _draw_pad(cr, pads.get("rpad", {}), _RPAD)
    _draw_stick(cr, sticks.get("lstick", {}), _LSTICK)
    _draw_stick(cr, sticks.get("rstick", {}), _RSTICK)


# ── Trackpad ──────────────────────────────────────────────────────────────────

def _draw_pad(cr, pad, bounds):
    touching = pad.get("touching", False)
    pressed  = pad.get("pressed", False)

    if not touching and not pressed:
        return

    rx = pad.get("x", 0.0)   # already -1.0…+1.0
    ry = pad.get("y", 0.0)

    # SVG → screen
    sx = _FX + bounds["x"] * _FS
    sy = _FY + bounds["y"] * _FS
    sw = bounds["w"] * _FS
    sh = bounds["h"] * _FS

    # Touch dot — maps ±1.0 to half the pad's pixel width/height
    cx = sx + sw / 2 + rx * (sw / 2)
    cy = sy + sh / 2 - ry * (sh / 2)   # y inverted: +1 = top

    dot_r = 5.0 if pressed else 3.5
    dot_a = 1.0 if pressed else 0.75
    cr.set_source_rgba(1, 1, 1, dot_a)
    cr.arc(cx, cy, dot_r, 0, math.tau)
    cr.fill()


# HUD background colour — used to erase the SVG's static inner circle
_BG = (0.031, 0.031, 0.071)

# ── Stick ─────────────────────────────────────────────────────────────────────

def _draw_stick(cr, stick, geom):
    x        = stick.get("x", 0.0)
    y        = stick.get("y", 0.0)
    deadzone = stick.get("deadzone", 0.0)
    active   = stick.get("active", False)

    # SVG → screen
    cx      = _FX + geom["cx"] * _FS
    cy      = _FY + geom["cy"] * _FS
    r_fixed = geom["r_fixed"] * _FS   # outer fixed ring — stays put
    r_outer = geom["r_outer"] * _FS   # outer moving ring
    r_inner = geom["r_inner"] * _FS   # inner moving disk

    # Parallax travel:
    #   r_inner travels fully — its edge reaches r_fixed at ±1.0
    #   r_outer (middle) travels less — at ±1.0 the gap between them shrinks to 1/3 of rest gap
    #   gap_rest = r_outer - r_inner
    #   gap_at_1 = gap_rest / 3
    #   → centre offset difference at ±1 = gap_rest * 2/3
    #   r_outer (middle) travels fully — its edge reaches r_fixed at ±1.0
    #   r_inner travels more — parallax (inner is "closer"), gap shrinks to half at ±1.0
    t_outer = r_fixed - r_outer
    t_inner = t_outer + (r_outer - r_inner) * 0.5

    new_outer_cx = cx + x * t_outer
    new_outer_cy = cy - y * t_outer   # +y = up on hardware
    new_inner_cx = cx + x * t_inner
    new_inner_cy = cy - y * t_inner

    # ── Erase both SVG static circles (r_outer covers r_inner) ───────────────
    cr.set_source_rgb(*_BG)
    cr.arc(cx, cy, r_outer + 2.0, 0, math.tau)
    cr.fill()

    # ── Deadzone ring (subtle, centred on stick origin, stays fixed) ─────────
    if deadzone > 0:
        dz_r = deadzone * r_fixed
        cr.set_source_rgba(1, 1, 1, 0.20)
        cr.set_line_width(0.8)
        cr.arc(cx, cy, dz_r, 0, math.tau)
        cr.stroke()

    # ── Redraw both moving circles at their parallax positions ───────────────
    if active:
        stroke_rgba = (1, 1, 1, 1.0)
        lw = 1.5
    else:
        stroke_rgba = (1, 1, 1, 0.75)
        lw = 1.0

    # r_outer ring (moves further)
    cr.set_source_rgb(*_BG)
    cr.arc(new_outer_cx, new_outer_cy, r_outer, 0, math.tau)
    cr.fill()
    cr.set_source_rgba(*stroke_rgba)
    cr.set_line_width(lw)
    cr.arc(new_outer_cx, new_outer_cy, r_outer, 0, math.tau)
    cr.stroke()

    # r_inner disk (moves less — parallax)
    cr.set_source_rgb(*_BG)
    cr.arc(new_inner_cx, new_inner_cy, r_inner, 0, math.tau)
    cr.fill()
    cr.set_source_rgba(*stroke_rgba)
    cr.set_line_width(lw)
    cr.arc(new_inner_cx, new_inner_cy, r_inner, 0, math.tau)
    cr.stroke()
