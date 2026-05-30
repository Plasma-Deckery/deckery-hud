"""
toast.py — Fire-and-forget action toast overlay.

Animation: appears in the lower third of the screen, rises upward, fades out.
           Rise starts immediately (progress=0). Fade starts after HOLD_FRAC.
Signature: draw_toast(cr, sw, sh, toasts)  — works in screen coordinates.
"""

import time

from helpers import _pill_row, _fmt

_TOAST_TTL    = 1.5    # total display time in seconds
_HOLD_FRAC    = 0.35   # full opacity until this fraction of TTL, then (1-t)³ fade
_START_Y_FRAC = 0.78   # starting y as fraction of screen height
_RISE_PX      = 48     # total upward travel in screen pixels over TTL

_C_KEYS = (0.72, 0.55, 1.0)    # lavender — key tap
_C_CMD  = (0.55, 0.90, 0.55)   # green    — command / exec


def draw_toast(cr, sw, sh, toasts):
    """Draw all in-flight toasts in screen coordinates."""
    for la in toasts:
        _draw_one(cr, sw, sh, la)


def _draw_one(cr, sw, sh, la):
    ts  = la.get("ts", 0)
    age = time.time() - ts
    if age < 0 or age > _TOAST_TTL:
        return

    progress = age / _TOAST_TTL

    # ── Alpha: hold, then (1-t)³ drop ────────────────────────────────────────
    if progress < _HOLD_FRAC:
        alpha = 1.0
    else:
        fade_t = (progress - _HOLD_FRAC) / (1.0 - _HOLD_FRAC)
        alpha  = (1.0 - fade_t) ** 3
    if alpha <= 0:
        return

    # ── Position: rise starts immediately ────────────────────────────────────
    cy = sh * _START_Y_FRAC - 73 - _RISE_PX * progress
    cx = sw / 2

    # ── Label ─────────────────────────────────────────────────────────────────
    t     = la.get("type", "keys")
    value = la.get("value", [])

    explicit_label = la.get("label")

    if t == "keys":
        label = explicit_label or _fmt(value)
        col   = _C_KEYS
    elif t in ("command", "exec"):
        label = explicit_label or (value if isinstance(value, str) else " ".join(str(v) for v in value))
        col   = _C_CMD
    else:
        label = explicit_label or (str(value) if value else "—")
        col   = _C_KEYS

    # ── Draw outlined pill (screen coords — no HUD translate active) ──────────
    _pill_row(
        cr, cx, cy, [label],
        size=10,
        bg=(*col, alpha * 0.15),
        fg=(*col, alpha),
        border=(*col, alpha * 0.85),
        sep_rgba=(0, 0, 0, 0),
        ha="center",
    )
