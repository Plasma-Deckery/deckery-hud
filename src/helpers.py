"""
helpers.py — Cairo/Pango drawing primitives and key-label utilities.
No GTK, no state, no layout — pure reusable tooling.
"""

# ── Shared HUD colours ────────────────────────────────────────────────────────
C_MOD   = (1.0,  0.792, 0.2)    # amber  — modifier buttons / held keys
C_LAYER = (0.45, 0.90,  0.82)   # teal   — per-app / context stack layers

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
    """['KEY_LEFTCTRL', 'KEY_PAGEDOWN'] → 'Ctrl+PgDn'
    For command strings (qdbus, ydotool, …) the last word is used as label."""
    if not keys:
        return "—"
    parts = []
    for k in keys:
        if k in _K:
            parts.append(_K[k])
        elif k.startswith("KEY_") or k.startswith("BTN_"):
            parts.append(k.replace("KEY_", "").replace("BTN_", "").capitalize())
        else:
            # Command string — use last token (e.g. "previousDesktop")
            parts.append(k.split()[-1] if k.strip() else "⌘")
    return "+".join(parts)


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


def _txt_size(cr, text, size=12, bold=False):
    """Return (pixel_width, pixel_height) of text without drawing."""
    lo = PangoCairo.create_layout(cr)
    weight = "Bold" if bold else ""
    lo.set_font_description(
        Pango.FontDescription.from_string(f"Noto Sans {weight} {size}"))
    lo.set_text(text, -1)
    return lo.get_pixel_size()


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


def _pill_row(cr, cx, cy, labels, sep="›", size=9,
              bg=(1, 1, 1, 0.10), fg=(1, 1, 1, 0.9),
              border=None, sep_rgba=(0.55, 0.55, 0.55, 0.7),
              ha="center", styles=None):
    """
    Draw a horizontal row of pill-shaped labels joined by a separator glyph.

    cx, cy     — anchor point; ha controls which edge cx refers to
    labels     — list of plain-text strings, one per pill
    sep        — separator glyph between pills (e.g. '›')
    size       — font size in pt
    bg         — RGBA fill for pill background (default for all pills)
    fg         — RGBA for pill text (default for all pills)
    border     — RGBA for pill border, or None to skip
    sep_rgba   — RGBA for separator glyph
    ha         — 'left' | 'center' | 'right'  (horizontal anchor)
    styles     — optional list of (bg, fg) per pill; overrides global bg/fg
    """
    if not labels:
        return

    PX, PY    = 7, 2   # horizontal / vertical padding inside pill
    SEP_GAP   = 4      # space on each side of a separator glyph
    PILL_GAP  = 5      # gap between adjacent pills when sep is empty string
    font_str  = f"Noto Sans Bold {size}"
    sep_font  = f"Noto Sans {size}"

    def _lo(text, markup_font):
        lo = PangoCairo.create_layout(cr)
        lo.set_font_description(Pango.FontDescription.from_string(markup_font))
        lo.set_text(text, -1)
        return lo, lo.get_pixel_size()

    # sep may be a single string (applied to all gaps) or a list (one per gap)
    n_gaps   = max(0, len(labels) - 1)
    sep_list = (list(sep) if isinstance(sep, (list, tuple))
                else [sep] * n_gaps)

    # Measure every unique non-empty separator glyph
    sep_cache = {}
    for s in set(sep_list):
        if s:
            sep_cache[s] = _lo(s, sep_font)

    # Measure all pill labels up front
    pill_los = [_lo(lbl, font_str) for lbl in labels]

    # Pill height is uniform (driven by the shared font size)
    _, (_, txt_h) = pill_los[0]
    ph = txt_h + 2 * PY
    r  = ph / 2

    # Total row width
    total_w = sum(pw + 2 * PX for (_, (pw, _)) in pill_los)
    for s in sep_list:
        if s and s in sep_cache:
            _, (sw, _) = sep_cache[s]
            total_w += sw + 2 * SEP_GAP
        else:
            total_w += PILL_GAP

    # Starting x
    if ha == "right":
        x = cx - total_w
    elif ha == "center":
        x = cx - total_w / 2
    else:
        x = cx

    for i, (lo_lbl, (pw_lbl, ph_lbl)) in enumerate(pill_los):
        pill_w = pw_lbl + 2 * PX
        pill_y = cy - ph / 2

        p_bg, p_fg = (styles[i] if styles and i < len(styles) else (bg, fg))

        # Background
        cr.set_source_rgba(*p_bg)
        _rrect(cr, x, pill_y, pill_w, ph, r)
        cr.fill()

        # Border
        if border is not None:
            cr.set_source_rgba(*border)
            cr.set_line_width(0.8)
            _rrect(cr, x, pill_y, pill_w, ph, r)
            cr.stroke()

        # Text
        cr.set_source_rgba(*p_fg)
        cr.move_to(x + PX, cy - ph_lbl / 2)
        PangoCairo.show_layout(cr, lo_lbl)
        x += pill_w

        # Separator between pills
        if i < n_gaps:
            s = sep_list[i]
            if s and s in sep_cache:
                lo_sep, (sw, sh_s) = sep_cache[s]
                x += SEP_GAP
                cr.set_source_rgba(*sep_rgba)
                cr.move_to(x, cy - sh_s / 2)
                PangoCairo.show_layout(cr, lo_sep)
                x += sw + SEP_GAP
            else:
                x += PILL_GAP
