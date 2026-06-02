"""
center_strip.py — Center-strip rendering (the gap between the two SVGs).
Left  (amber): held Deckery modifiers
Right (cyan):  active_outputs — keys currently held by the system
"""

from layout import HUD_W, _PAD, _STRIP_Y, _STRIP_H
from helpers import _txt, _pill_row, _K

# ── Display colours ───────────────────────────────────────────────────────────
_C_ACT = (0.333, 0.867, 1.0)  # system actuator / active output — cyan #55DDFF


def draw_center_strip(cr, state):
    ctx     = state.get("context") or {}
    outputs = ctx.get("active_outputs", [])

    mids_y = _STRIP_Y + _STRIP_H / 2

    # Dezente Trennlinie (immer sichtbar)
    cr.set_source_rgba(1, 1, 1, 0.07)
    cr.set_line_width(0.5)
    cr.move_to(_PAD * 2, mids_y)
    cr.line_to(HUD_W - _PAD * 2, mids_y)
    cr.stroke()

    # ── active_outputs als cyan Pillen, zentriert ────────────────────────────
    right_labels = [_K.get(k, k.replace("KEY_", "").replace("BTN_", ""))
                    for k in outputs]
    if right_labels:
        _pill_row(
            cr, HUD_W / 2, mids_y, right_labels,
            sep="+", size=9,
            bg=(*_C_ACT, 1.0), fg=(0, 0, 0, 1),
            border=None, sep_rgba=(1.0, 1.0, 1.0, 0.55),
            ha="center",
        )
