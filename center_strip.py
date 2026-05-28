"""
center_strip.py — Center-strip rendering (the gap between the two SVGs).
Owns the display colour constants and Pango-markup drawing logic.
"""

from layout import HUD_W, _PAD, _STRIP_Y, _STRIP_H
from helpers import _fmt, _pango_esc, _txt, _txt_markup
from callouts import _btn_short

# ── Display colours ───────────────────────────────────────────────────────────
_C_AMBER = "#FFCA33"   # internal state / modifier button
_C_CYAN  = "#55DDFF"   # system output / sent keys
_C_GRAY  = "#888888"   # separators / arrows


def draw_center_strip(cr, state):
    """
    Zwei Blöcke, getrennt durch einen Mittelpunkt:
      Links  (amber): aktive Deckery-Modifier — welche Layer-Buttons gerade gehalten werden
      Rechts (cyan):  tatsächlicher System-Output — was gerade gesendet wurde

    Beide Blöcke sind unabhängig: R1 (Alt-Direktmapping, kein Layer-Modifier) taucht
    nur rechts auf, L1 (Layer-Modifier) taucht links auf und sein Output rechts.
    """
    held_mods = state.get("context", {}).get("held_modifiers", [])
    last_ev   = state.get("last_event")

    mids_y       = _STRIP_Y + _STRIP_H / 2
    cx_left      = HUD_W / 2 - 24   # rechte Kante des linken Blocks
    cx_right     = HUD_W / 2 + 24   # linke  Kante des rechten Blocks

    # Dezente Trennlinie (immer sichtbar)
    cr.set_source_rgba(1, 1, 1, 0.07)
    cr.set_line_width(0.5)
    cr.move_to(_PAD * 2, mids_y)
    cr.line_to(HUD_W - _PAD * 2, mids_y)
    cr.stroke()

    # ── Linker Block: Deckery-Modifier-Namen (amber) ──────────────────────────
    if held_mods:
        plus = f'<span foreground="{_C_GRAY}">+</span>'
        parts = [
            f'<span foreground="{_C_AMBER}" font_weight="bold">'
            f'{_pango_esc(_btn_short(m))}</span>'
            for m in held_mods
        ]
        cr.set_source_rgba(1, 1, 1, 1)
        _txt_markup(cr, cx_left, mids_y, plus.join(parts), 10, ha="right", va="mid")

    # ── Trennpunkt (nur wenn mindestens ein Block aktiv) ─────────────────────
    last_is_press = last_ev and last_ev.get("value") == 1
    if held_mods or last_is_press:
        cr.set_source_rgba(0.4, 0.4, 0.4, 0.6)
        _txt(cr, HUD_W / 2, mids_y, "·", 10, ha="center", va="mid")

    # ── Rechter Block: System-Output (cyan) ───────────────────────────────────
    if last_is_press:
        out_s  = _pango_esc(_fmt(last_ev.get("action", [])))
        markup = f'<span foreground="{_C_CYAN}" font_weight="bold">{out_s}</span>'
        cr.set_source_rgba(1, 1, 1, 1)
        _txt_markup(cr, cx_right, mids_y, markup, 10, ha="left", va="mid")
