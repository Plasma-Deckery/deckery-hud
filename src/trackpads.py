"""
trackpads.py — Analog overlay: trackpads, sticks, triggers.
All position values from state are already normalized to -1.0…+1.0 (trackpads/sticks)
or 0.0…1.0 (triggers). No raw-value conversion needed.
"""

import math
import cairo
from layout import _FX, _FY, _FS
from helpers import _txt_smooth

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


def draw_trackpads(cr, state, left_tx=None, right_tx=None,
                    left_stick_tx=None, right_stick_tx=None, erase_mode="panel", dim=False,
                    left_stick_press=0.0, right_stick_press=0.0, fill_rings=False):
    """Entry point called from renderer.

    fill_rings: give the two moving stick rings an actual fill (split
    renderer only, default off — classic's sticks stay the plain outlined
    circles they've always been). See _draw_stick for what the fill looks
    like and why.

    left_tx/right_tx: optional (ox, oy, scale) overriding where the front SVG's
    (0,0) lands on screen and its scale, for a renderer that places the left
    and right clusters at different screen positions (e.g. the split layout).
    Defaults to the classic renderer's single front-SVG placement for both.

    left_stick_tx/right_stick_tx: separate transform for the sticks. In the
    classic renderer the trackpad and the stick sit in the same single front
    SVG render, so they share one transform (left_tx/right_tx) and these can
    be left as None. In the split renderer the trackpad and the stick are in
    *different* clusters (trackpad is in the "pad" cluster, the stick is in
    the "face" cluster, each with its own crop and scale) — passing the pad
    cluster's transform for the stick positions it using the wrong cluster's
    geometry entirely, so the two need to be kept distinct.

    erase_mode: the stick drawing used to need to erase the SVG's static
    circle before redrawing it at its deflected position:
      "panel" — paint over with the panel colour (classic default, on an
                opaque panel).
      "clear" — cut a real transparent hole with the CLEAR operator (for a
                renderer with a transparent backdrop and no vector fixed-ring
                part of its own — paint-over would show as a solid blob).
      "none"  — don't erase at all. The split renderer's fixed ring is now
                drawn by parts.py as a plain stroke, not cropped from the
                SVG raster, so there's no pre-existing pixels under the
                moving rings that need clearing — and CLEAR would erase
                through anything painted earlier in the same frame,
                including the renderer's own backdrop blobs, not just the
                stick (that was the "stick cuts a hole in the backdrop" bug).

    dim: the pad's touch/gesture fill is a *white* wash (0.10-0.18 alpha)
    tuned against the classic renderer's own opaque dark panel. Without that
    panel behind it (split renderer), the same white fill reads as a bright
    smudge over whatever's actually on screen — pass True to scale it down.

    left_stick_press/right_stick_press: 0..1 eased L3/R3 click-press amount
    (split renderer only — classic's default 0.0 means "no effect", same as
    not passing it at all). Shrinks the two *moving* stick rings slightly,
    not the static outer bezel — see _draw_stick's own note on why.
    """
    pads    = state.get("trackpads") or {}
    sticks  = state.get("sticks")   or {}
    gesture = (pads.get("gesture") or {}).get("touching", False)
    ltx  = left_tx  or (_FX, _FY, _FS)
    rtx  = right_tx or (_FX, _FY, _FS)
    lstx = left_stick_tx  or ltx
    rstx = right_stick_tx or rtx
    _draw_pad(cr, pads.get("left")  or {}, _LPAD, gesture, tx=ltx, dim=dim)
    _draw_pad(cr, pads.get("right") or {}, _RPAD, gesture, tx=rtx, dim=dim)
    _draw_stick(cr, sticks.get("lstick", {}), _LSTICK, tx=lstx, erase_mode=erase_mode,
                press=left_stick_press, fill_rings=fill_rings)
    _draw_stick(cr, sticks.get("rstick", {}), _RSTICK, tx=rstx, erase_mode=erase_mode,
                press=right_stick_press, fill_rings=fill_rings)


# ── Trackpad ──────────────────────────────────────────────────────────────────

def _rrect(cr, x, y, w, h, r):
    """Rounded rectangle path (reused from renderer concept)."""
    cr.new_sub_path()
    cr.arc(x + r,     y + r,     r, math.pi,       3 * math.pi / 2)
    cr.arc(x + w - r, y + r,     r, 3 * math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0,              math.pi / 2)
    cr.arc(x + r,     y + h - r, r, math.pi / 2,   math.pi)
    cr.close_path()


_AMBER = (1.0, 0.78, 0.2)


def _clamp_to_rrect(cx, cy, sx, sy, sw, sh, r):
    """Pull (cx, cy) back onto the rounded rect's real silhouette, not just
    its bounding box. A plain bbox clamp still lets a corner-ish reading
    land in one of the four triangular slivers the rounding cuts off —
    small in absolute pixels, but exactly the "dot sits visibly outside the
    pad" complaint once the pad is drawn large enough (see the split
    renderer, where the bbox-only version of this was still clamping to a
    sharp corner the drawn shape doesn't actually have)."""
    cx = max(sx, min(sx + sw, cx))
    cy = max(sy, min(sy + sh, cy))
    ccx = sx + r if cx < sx + r else (sx + sw - r if cx > sx + sw - r else None)
    ccy = sy + r if cy < sy + r else (sy + sh - r if cy > sy + sh - r else None)
    if ccx is None or ccy is None:
        return cx, cy   # on a flat edge or interior — no corner to worry about
    dx, dy = cx - ccx, cy - ccy
    dist = math.hypot(dx, dy)
    if dist <= r:
        return cx, cy
    k = r / dist
    return ccx + dx * k, ccy + dy * k


def _draw_pad(cr, pad, bounds, gesture=False, tx=None, dim=False):
    touching = pad.get("touching", False)
    pressed  = pad.get("pressed", False)

    # SVG → screen
    ox, oy, scale = tx or (_FX, _FY, _FS)
    sx = ox + bounds["x"] * scale
    sy = oy + bounds["y"] * scale
    sw = bounds["w"] * scale
    sh = bounds["h"] * scale
    r  = 6 * scale   # corner radius matching the SVG shape

    fade = 0.55 if dim else 1.0

    # ── Fill overlay — sits inside the existing SVG shape, no new border ────────
    # gesture → amber glow; individual touch/press → white glow; idle → nothing
    if gesture:
        cr.set_source_rgba(*_AMBER, 0.18 * fade)
        _rrect(cr, sx, sy, sw, sh, r)
        cr.fill()
    elif touching or pressed:
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.10 * fade)
        _rrect(cr, sx, sy, sw, sh, r)
        cr.fill()

    # ── Position dot ─────────────────────────────────────────────────────────
    # gesture=True  → amber dot at pad coords (touching=False but coords valid)
    # touching/press → white dot at pad coords
    if not touching and not pressed and not gesture:
        return

    rx = pad.get("x", 0.0)   # nominally -1.0…+1.0, but see the clamp below
    ry = pad.get("y", 0.0)
    # Clamped defensively, not just trusted as already in range: the source
    # data isn't guaranteed to be perfectly calibrated to exactly ±1.0 at the
    # pad's physical edges, and at the classic renderer's small pad size that
    # slack was invisible — blown up to the split renderer's size, a reading
    # even slightly past 1.0 visibly pokes the dot outside the drawn pad
    # entirely. This can only ever pull an out-of-range reading back onto the
    # pad, never move an in-range one.
    rx = max(-1.0, min(1.0, rx))
    ry = max(-1.0, min(1.0, ry))

    cx = sx + sw / 2 + rx * (sw / 2)
    cy = sy + sh / 2 - ry * (sh / 2)   # y inverted: +1 = top
    cx, cy = _clamp_to_rrect(cx, cy, sx, sy, sw, sh, r)

    if gesture:
        cr.set_source_rgba(*_AMBER, 0.9)
        dot_r = 3.5
    elif pressed:
        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
        dot_r = 5.0
    else:
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.85)
        dot_r = 3.5
    cr.arc(cx, cy, dot_r, 0, math.tau)
    cr.fill()


# HUD background colour — used to erase the SVG's static inner circle
_BG = (0.031, 0.031, 0.071)

# ── Stick ─────────────────────────────────────────────────────────────────────

def _erase_circle(cr, cx, cy, r, mode):
    """'Erase' a circle — see draw_trackpads' erase_mode docstring for when
    each mode applies."""
    if mode == "none":
        return
    if mode == "clear":
        cr.save()
        cr.set_operator(cairo.Operator.CLEAR)
        cr.arc(cx, cy, r, 0, math.tau)
        cr.fill()
        cr.restore()
    else:
        cr.set_source_rgb(*_BG)
        cr.arc(cx, cy, r, 0, math.tau)
        cr.fill()


# L3/R3 click-press feedback: shrink the two *moving* rings (r_outer,
# r_inner) toward the stick's own centre, not the static outer bezel
# (r_fixed never moves on a real stick, so scaling it doesn't read as a
# press — see renderer_split._SCALE_ANIM_PARTS's own note on this).
# Bumped up from an initial 0.045 (itself subtler than the standalone
# buttons' own _SCALE_ANIM_MAX of 0.08, reasoning that these two thin rings
# read as "gone" faster than a solid shape does at the same shrink fraction)
# — too subtle in practice, on request.
_STICK_PRESS_SCALE_MAX = 0.11

# fill_rings colours — checked against actual Steam Deck close-up photos,
# outside-in: dark bezel/socket (r_fixed, unchanged), a noticeably lighter
# base-collar ring (r_outer), then the cap itself, which reads darker still
# at its centre (r_inner) with a crisper, more defined edge than the thin
# white outline used everywhere else in this renderer — not literal photo
# colours, kept in the same "white at some alpha over the dark page
# background" language the rest of the split renderer already uses instead
# of introducing a new hue. Pushed to a harder light/dark split than the
# first pass (0.22/0.45 alpha) — that read as two close, muddy mid-greys
# instead of a light ring against a dark cap, on request.
_RING_OUTER_FILL   = (1.0, 1.0, 1.0, 0.38)
_RING_INNER_FILL   = (0.0, 0.0, 0.0, 0.72)
_RING_INNER_BORDER = (0.0, 0.0, 0.0, 0.95)


def _draw_stick(cr, stick, geom, tx=None, erase_mode="panel", press=0.0, fill_rings=False,
                label=None):
    x        = stick.get("x", 0.0)
    y        = stick.get("y", 0.0)
    deadzone = stick.get("deadzone", 0.0)
    active   = stick.get("active", False)

    # SVG → screen
    ox, oy, scale = tx or (_FX, _FY, _FS)
    cx      = ox + geom["cx"] * scale
    cy      = oy + geom["cy"] * scale
    r_fixed = geom["r_fixed"] * scale   # outer fixed ring — stays put
    press_s = 1.0 - _STICK_PRESS_SCALE_MAX * press
    r_outer = geom["r_outer"] * scale * press_s   # outer moving ring
    r_inner = geom["r_inner"] * scale * press_s   # inner moving disk

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
    _erase_circle(cr, cx, cy, r_outer + 2.0, erase_mode)

    # ── Deadzone ring (subtle, centred on stick origin, stays fixed) ─────────
    # Dropped for fill_rings: with the cap now drawn as a solid, deliberately
    # eye-catching dark disk, this thin threshold ring just sat inside it
    # reading as unexplained clutter rather than useful information — on
    # request.
    if deadzone > 0 and not fill_rings:
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

    # r_outer ring (moves further) — filled when fill_rings, standing in for
    # the lighter base-collar ring visible around a real stick cap (checked
    # against actual close-up photos). Fill then stroke, same order as the
    # shoulder wedge fix and for the same reason: a fill painted after its
    # own border eats into it instead of staying inside it.
    _erase_circle(cr, new_outer_cx, new_outer_cy, r_outer, erase_mode)
    if fill_rings:
        cr.set_source_rgba(*_RING_OUTER_FILL)
        cr.arc(new_outer_cx, new_outer_cy, r_outer, 0, math.tau)
        cr.fill()
    cr.set_source_rgba(*stroke_rgba)
    cr.set_line_width(lw)
    cr.arc(new_outer_cx, new_outer_cy, r_outer, 0, math.tau)
    cr.stroke()

    # r_inner disk (moves less — parallax) — darker fill with a crisper,
    # darker border than the thin white outline everything else here uses,
    # so the cap's own centre (which reads darker and slightly recessed in
    # every reference photo) stands out as a distinct disk inside the
    # lighter outer ring instead of just another identical circle.
    _erase_circle(cr, new_inner_cx, new_inner_cy, r_inner, erase_mode)
    if fill_rings:
        cr.set_source_rgba(*_RING_INNER_FILL)
        cr.arc(new_inner_cx, new_inner_cy, r_inner, 0, math.tau)
        cr.fill()
        cr.set_source_rgba(*_RING_INNER_BORDER)
        cr.set_line_width(lw)
        cr.arc(new_inner_cx, new_inner_cy, r_inner, 0, math.tau)
        cr.stroke()
    else:
        cr.set_source_rgba(*stroke_rgba)
        cr.set_line_width(lw)
        cr.arc(new_inner_cx, new_inner_cy, r_inner, 0, math.tau)
        cr.stroke()

    # Identity label ("L3"/"R3") rides on the cap (the inner disk, not the
    # middle ring — that one travels less, so the text would slide off-centre
    # of the cap at full deflection), on request. Used to sit static in the
    # cached side bitmap at the rest centre, underneath this cap's dark fill,
    # which left it barely visible. Press-scaled about the cap's own centre
    # together with the rings, hence _txt_smooth (see its docstring for the
    # "dancing" text it avoids).
    if label:
        cr.save()
        cr.translate(new_inner_cx, new_inner_cy)
        cr.scale(press_s, press_s)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.75)
        _txt_smooth(cr, 0, 0, label, size=9, ha="center", va="mid")
        cr.restore()
