"""
helpers.py — Cairo/Pango drawing primitives and key-label utilities.
No GTK, no state, no layout — pure reusable tooling.
"""

# ── Shared HUD colours ────────────────────────────────────────────────────────
C_MOD   = (1.0,  0.792, 0.2)    # amber   — modifier buttons / held keys
C_LAYER = (0.45, 0.90,  0.82)   # teal    — per-app / context stack layers
C_GAME  = (0.95, 0.35,  0.78)   # magenta — Gaming Mode trigger callout

import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo
import cairo
import math

# ── Key → human label ────────────────────────────────────────────────────────
# Canonical source is viewmodel.py (state classification, no GTK dependency);
# re-exported here so existing call sites (`from helpers import _K, _fmt`)
# don't need to change.
from viewmodel import _K, _fmt


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
        Pango.FontDescription.from_string(f"Adwaita Sans {weight} {size}"))
    lo.set_text(text, -1)
    pw, ph = lo.get_pixel_size()
    tx = x - (pw if ha == "right" else pw / 2 if ha == "center" else 0)
    ty = y - (ph if va == "bottom" else ph / 2 if va == "mid" else 0)
    cr.move_to(tx, ty)
    PangoCairo.show_layout(cr, lo)


_UNHINTED = cairo.FontOptions()
_UNHINTED.set_hint_style(cairo.HINT_STYLE_NONE)
_UNHINTED.set_hint_metrics(cairo.HINT_METRICS_OFF)


def _txt_smooth(cr, x, y, text, size=12, bold=False, ha="center", va="mid"):
    """Text that has to scale continuously with a vector shape under an
    animated transform (the split renderer's press-scale). _txt can't: it
    centres on get_pixel_size() (whole-pixel extents) and Pango's default
    hint metrics snap glyph positions to the device grid, so while the
    shape shrinks smoothly the glyph moves in pixel steps — measured as a
    ~0.5px jump between adjacent frames, i.e. the letter "dancing" inside
    its circle. Unhinted metrics and float extents keep both on the same
    continuous transform. Drawn as a filled path, not show_layout: Cairo's
    glyph cache places glyph bitmaps at quantized sub-pixel offsets (whole
    pixels vertically), which left ~0.35px of vertical jitter even with
    hinting off — a path rasterizes under exactly the shape's transform.

    Centres on the ink rect rather than the logical one, so a glyph sits
    optically centred in its button instead of offset by the font's own
    ascent/descent (most visible on "···", whose ink sits on the baseline)."""
    lo = PangoCairo.create_layout(cr)
    PangoCairo.context_set_font_options(lo.get_context(), _UNHINTED)
    lo.context_changed()
    weight = "Bold" if bold else ""
    lo.set_font_description(
        Pango.FontDescription.from_string(f"Adwaita Sans {weight} {size}"))
    lo.set_text(text, -1)
    ink, _logical = lo.get_extents()
    ix, iy = ink.x / Pango.SCALE, ink.y / Pango.SCALE
    iw, ih = ink.width / Pango.SCALE, ink.height / Pango.SCALE
    tx = x - ix - (iw if ha == "right" else iw / 2 if ha == "center" else 0)
    ty = y - iy - (ih if va == "bottom" else ih / 2 if va == "mid" else 0)
    cr.new_path()
    cr.move_to(tx, ty)
    PangoCairo.layout_path(cr, lo)
    cr.fill()


def _txt_size(cr, text, size=12, bold=False):
    """Return (pixel_width, pixel_height) of text without drawing."""
    lo = PangoCairo.create_layout(cr)
    weight = "Bold" if bold else ""
    lo.set_font_description(
        Pango.FontDescription.from_string(f"Adwaita Sans {weight} {size}"))
    lo.set_text(text, -1)
    return lo.get_pixel_size()


def _txt_markup(cr, x, y, markup, size=12, ha="left", va="top"):
    """Like _txt but accepts Pango markup (inline colours via <span foreground=…>)."""
    lo = PangoCairo.create_layout(cr)
    lo.set_font_description(Pango.FontDescription.from_string(f"Adwaita Sans {size}"))
    lo.set_markup(markup, -1)
    pw, ph = lo.get_pixel_size()
    tx = x - (pw if ha == "right" else pw / 2 if ha == "center" else 0)
    ty = y - (ph if va == "bottom" else ph / 2 if va == "mid" else 0)
    cr.move_to(tx, ty)
    PangoCairo.show_layout(cr, lo)


def _pill_row(cr, cx, cy, labels, sep="›", size=9,
              bg=(1, 1, 1, 0.10), fg=(1, 1, 1, 0.9),
              border=None, sep_rgba=(0.55, 0.55, 0.55, 0.7),
              ha="center", styles=None, icons=None, prefix_icons=None, icon_size=None):
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
    icons      — optional list, one per pill: None for a normal text pill, or
                 a callable `draw(cr, cx, cy)` that paints a fixed-size glyph
                 centred at (cx, cy) instead of that pill's label text — the
                 pill background/border are still drawn as usual, and the
                 corresponding `labels[i]` entry only drives the pill's
                 height (pass "" — Pango still reports a real line height
                 for an empty string, so sizing stays consistent with the
                 text pills around it).
    prefix_icons — optional list, one per pill: None, or a callable
                 `draw(cr, x, y)` that paints a fixed-size glyph with its
                 left edge at x, vertically centred on y — drawn *before*
                 that pill's own label text, inside the same pill (the pill
                 widens to fit both). Independent of `icons`; a pill with
                 both set uses `icons` and ignores its prefix.
    icon_size  — the actual pixel size `icons`/`prefix_icons` callables draw
                 at (they all share one size in practice). Pill height grows
                 to fit it when it's taller than the row's own text, instead
                 of the icon box being capped to text height regardless of
                 what the caller actually draws into it — a shorter pill
                 with an icon overflowing its background was exactly that
                 mismatch. Defaults to the text-driven box from before.
    """
    if not labels:
        return
    icons = icons or [None] * len(labels)
    prefix_icons = prefix_icons or [None] * len(labels)

    PX, PY    = 7, 2   # horizontal / vertical padding inside pill
    SEP_GAP   = 4      # space on each side of a separator glyph
    PILL_GAP  = 5      # gap between adjacent pills when sep is empty string
    font_str  = f"Adwaita Sans Bold {size}"
    sep_font  = f"Adwaita Sans {size}"

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

    # Pill height is uniform (driven by the shared font size, or by
    # icon_size when that needs more room than the text does).
    _, (_, txt_h) = pill_los[0]
    ph = max(txt_h + 2 * PY, (icon_size + 2 * PY) if icon_size else 0)
    r  = ph / 2
    icon_w = icon_size if icon_size is not None else max(ph - 4, 10)
    PREFIX_GAP = 4             # gap between a prefix icon and its pill's own text

    def _content_w(i, pw):
        if icons[i]:
            return icon_w
        if prefix_icons[i]:
            return icon_w + PREFIX_GAP + pw
        return pw

    # Total row width
    total_w = sum(_content_w(i, pw) + 2 * PX
                  for i, (_, (pw, _)) in enumerate(pill_los))
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
        icon = icons[i]
        prefix = None if icon else prefix_icons[i]
        pill_w = _content_w(i, pw_lbl) + 2 * PX
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

        # Text — or, for an icon pill, the caller's glyph instead; a prefix
        # pill gets both, glyph first, then the label shifted over to clear it.
        cr.set_source_rgba(*p_fg)
        if icon:
            icon(cr, x + pill_w / 2, cy)
        elif prefix:
            prefix(cr, x + PX, cy)
            cr.move_to(x + PX + icon_w + PREFIX_GAP, cy - ph_lbl / 2)
            PangoCairo.show_layout(cr, lo_lbl)
        else:
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
