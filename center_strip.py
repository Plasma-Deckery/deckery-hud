"""
center_strip.py — Center-strip rendering (the gap between the two SVGs).
Left  (amber): held Deckery modifiers
Right (cyan):  active_outputs — keys currently held by the system
"""

from layout import HUD_W, _PAD, _STRIP_Y, _STRIP_H
from helpers import _txt, _pill_row, _K
from callouts import _btn_short

# ── Display colours ───────────────────────────────────────────────────────────
_C_MOD = (1.0, 0.792, 0.2)    # internal Deckery modifier — amber #FFCA33
_C_ACT = (0.333, 0.867, 1.0)  # system actuator / active output — cyan #55DDFF


def draw_center_strip(cr, state):
    ctx       = state.get("context", {})
    held_mods = ctx.get("held_modifiers", [])
    outputs   = ctx.get("active_outputs", [])

    mids_y   = _STRIP_Y + _STRIP_H / 2
    cx_left  = HUD_W / 2 - 24
    cx_right = HUD_W / 2 + 24

    # Dezente Trennlinie (immer sichtbar)
    cr.set_source_rgba(1, 1, 1, 0.07)
    cr.set_line_width(0.5)
    cr.move_to(_PAD * 2, mids_y)
    cr.line_to(HUD_W - _PAD * 2, mids_y)
    cr.stroke()

    # ── Linker Block: Deckery-Modifier als amber Pillen ──────────────────────
    if held_mods:
        _pill_row(
            cr, cx_left, mids_y,
            [_btn_short(m) for m in held_mods],
            sep="›", size=9,
            bg=(*_C_MOD, 1.0), fg=(0, 0, 0, 1),
            border=None, sep_rgba=(0.55, 0.55, 0.55, 0.8),
            ha="right",
        )

    # Trennpunkt
    right_labels = [_K.get(k, k.replace("KEY_", "").replace("BTN_", ""))
                    for k in outputs]
    if held_mods or right_labels:
        cr.set_source_rgba(0.4, 0.4, 0.4, 0.6)
        _txt(cr, HUD_W / 2, mids_y, "·", 10, ha="center", va="mid")

    # ── Rechter Block: active_outputs als cyan Pillen ────────────────────────
    if right_labels:
        _pill_row(
            cr, cx_right, mids_y, right_labels,
            sep="+", size=9,
            bg=(*_C_ACT, 1.0), fg=(0, 0, 0, 1),
            border=None, sep_rgba=(0.3, 0.3, 0.3, 0.8),
            ha="left",
        )
