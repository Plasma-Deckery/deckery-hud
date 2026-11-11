"""
toast.py — Fire-and-forget action toast overlay.

Animation: appears in the lower third of the screen, rises upward, fades out.
           Rise starts immediately (progress=0). Fade starts after HOLD_FRAC.
Signature: draw_toast(cr, sw, sh, toasts)  — works in screen coordinates.
"""

import time

from helpers import _pill_row, _fmt
import theme

_TOAST_TTL    = 1.5    # total display time in seconds
_HOLD_FRAC    = 0.35   # full opacity until this fraction of TTL, then (1-t)³ fade
# _START_Y_FRAC is no longer used — win.py passes start_y=hud_bottom explicitly.
# osd_win.py passes start_y=sh+30 (slides in from below screen edge).
# Kept as fallback only.
_START_Y_FRAC = 0.78
_RISE_PX      = 48     # total upward travel in screen pixels over TTL

# Colours: theme.toast_keys (lavender, key tap), theme.toast_command (green,
# command / exec), theme.toast_error (red, a command that did not run).


def draw_toast(cr, sw, sh, toasts, start_y=None):
    """Draw all in-flight toasts in screen coordinates.
    start_y: override the Y origin (default: sh * _START_Y_FRAC).
    """
    for la in toasts:
        _draw_one(cr, sw, sh, la, start_y=start_y)


def _draw_one(cr, sw, sh, la, start_y=None):
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
    base_y = start_y if start_y is not None else sh * _START_Y_FRAC
    cy = base_y - 73 - _RISE_PX * progress
    cx = sw / 2

    label, col = toast_label(la)

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


def toast_label(la):
    """(text, colour) a toast shows for last_action `la`."""
    t     = la.get("type", "keys")
    value = la.get("value", [])

    explicit_label = la.get("label")

    if t == "keys":
        label = explicit_label or _fmt(value)
        col   = theme.current().toast_keys
    elif t in ("command", "exec"):
        label = explicit_label or (value if isinstance(value, str) else " ".join(str(v) for v in value))
        col   = theme.current().toast_command
    elif t == "error":
        # A command binding that did not run. `label` names the binding the
        # user pressed, `value` says why — both, because neither alone is
        # enough to act on.
        reason = value if isinstance(value, str) else str(value)
        label  = f"{explicit_label}: {reason}" if explicit_label else reason
        col    = theme.current().toast_error
    else:
        label = explicit_label or (str(value) if value else "—")
        col   = theme.current().toast_keys
    return label, col
