"""
helpers.py — Cairo/Pango drawing primitives and key-label utilities.
No GTK, no state, no layout — pure reusable tooling.
"""

import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo
import math

# ── Key → human label ────────────────────────────────────────────────────────
_K = {
    "KEY_LEFTCTRL":  "Ctrl",   "KEY_LEFTALT":   "Alt",   "KEY_LEFTSHIFT": "Shift",
    "KEY_LEFTMETA":  "Super",  "KEY_ENTER":     "Enter", "KEY_ESC":       "Esc",
    "KEY_SPACE":     "Space",  "KEY_BACKSPACE": "⌫",     "KEY_TAB":       "Tab",
    "KEY_UP":        "↑",      "KEY_DOWN":      "↓",     "KEY_LEFT":      "←",
    "KEY_RIGHT":     "→",      "KEY_PAGEUP":    "PgUp",  "KEY_PAGEDOWN":  "PgDn",
    "BTN_LEFT":      "LClick", "BTN_RIGHT":     "RClick",
}


def _fmt(keys):
    """['KEY_LEFTCTRL', 'KEY_PAGEDOWN'] → 'Ctrl+PgDn'"""
    if not keys:
        return "—"
    return "+".join(_K.get(k, k.replace("KEY_", "").replace("BTN_", "")) for k in keys)


def _pango_esc(s):
    """Escape special characters for Pango markup."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Cairo primitives ─────────────────────────────────────────────────────────

def _rrect(cr, x, y, w, h, r):
    """Rounded rectangle path (must be filled/stroked by caller)."""
    cr.new_sub_path()
    cr.arc(x + r,     y + r,     r, math.pi,         3 * math.pi / 2)
    cr.arc(x + w - r, y + r,     r, 3 * math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0,               math.pi / 2)
    cr.arc(x + r,     y + h - r, r, math.pi / 2,     math.pi)
    cr.close_path()


def _txt(cr, x, y, text, size=12, bold=False, ha="left", va="top"):
    lo = PangoCairo.create_layout(cr)
    weight = "Bold" if bold else ""
    lo.set_font_description(
        Pango.FontDescription.from_string(f"Noto Sans {weight} {size}"))
    lo.set_text(text, -1)
    pw, ph = lo.get_pixel_size()
    tx = x - (pw if ha == "right" else pw / 2 if ha == "center" else 0)
    ty = y - (ph if va == "bottom" else ph / 2 if va == "mid" else 0)
    cr.move_to(tx, ty)
    PangoCairo.show_layout(cr, lo)


def _txt_markup(cr, x, y, markup, size=12, ha="left", va="top"):
    """Like _txt but accepts Pango markup (inline colours via <span foreground=…>)."""
    lo = PangoCairo.create_layout(cr)
    lo.set_font_description(Pango.FontDescription.from_string(f"Noto Sans {size}"))
    lo.set_markup(markup, -1)
    pw, ph = lo.get_pixel_size()
    tx = x - (pw if ha == "right" else pw / 2 if ha == "center" else 0)
    ty = y - (ph if va == "bottom" else ph / 2 if va == "mid" else 0)
    cr.move_to(tx, ty)
    PangoCairo.show_layout(cr, lo)
