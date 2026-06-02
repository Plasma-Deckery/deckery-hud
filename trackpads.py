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
# Circles derived from the two concentric path arcs in steamdeckFront.svg:
#   outer circle r ≈ 34.2, inner (travel) circle r ≈ 23.6
_LSTICK = {"cx": 163.669, "cy": 90.009, "r_inner": 23.6, "r_outer": 34.2}
_RSTICK = {"cx": 859.776, "cy": 90.559, "r_inner": 23.6, "r_outer": 34.2}

# Colours
_C_ACTIVE = (1.0, 0.78, 0.2)    # amber — stick active / trigger pressed


def draw_trackpads(cr, state):
    """Entry point called from renderer."""
    pads     = state.get("trackpads", {})
    sticks   = state.get("sticks", {})
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


# ── Stick ─────────────────────────────────────────────────────────────────────

def _draw_stick(cr, stick, geom):
    x        = stick.get("x", 0.0)
    y        = stick.get("y", 0.0)
    deadzone = stick.get("deadzone", 0.0)
    active   = stick.get("active", False)

    # Convert SVG units to screen pixels
    cx      = _FX + geom["cx"] * _FS
    cy      = _FY + geom["cy"] * _FS
    r_inner = geom["r_inner"] * _FS   # full travel radius in px

    # ── Deadzone circle ───────────────────────────────────────────────────────
    if deadzone > 0:
        dz_r = deadzone * r_inner
        cr.set_source_rgba(1, 1, 1, 0.18)
        cr.set_line_width(0.8)
        cr.arc(cx, cy, dz_r, 0, math.tau)
        cr.stroke()

    # ── Position dot — only when active (outside deadzone) ───────────────────
    if active:
        dot_x = cx + x * r_inner
        dot_y = cy - y * r_inner    # +y = up on hardware → up on screen

        cr.set_source_rgba(*_C_ACTIVE, 1.0)
        cr.arc(dot_x, dot_y, 3.0, 0, math.tau)
        cr.fill()

        cr.set_source_rgba(*_C_ACTIVE, 0.5)
        cr.set_line_width(1.0)
        cr.move_to(cx, cy)
        cr.line_to(dot_x, dot_y)
        cr.stroke()
