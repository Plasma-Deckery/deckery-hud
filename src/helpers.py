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

import theme

# ── Key → human label ────────────────────────────────────────────────────────
# Canonical source is viewmodel.py (state classification, no GTK dependency);
# re-exported here so existing call sites (`from helpers import _K, _fmt`)
# don't need to change.
from viewmodel import _K, _fmt, split_icon


# ── Text-box capture ─────────────────────────────────────────────────────────
# While a list is installed here, every text line and label pill drawn
# through these helpers appends its box — in device space, i.e. screen px for
# the HUD's own layers — and its colour, so shadow.py can lay a shadow under
# each legend line, tinted to match, without re-deriving the layout that
# placed it.
_text_sink = None


class capture_text_boxes:
    """with capture_text_boxes() as cap: ... — cap.boxes fills with
    (x, y, w, h), cap.texts with the matching strings, cap.colours with
    their (r, g, b) or None when it isn't a plain colour. Glass pills (see
    _glass_pill) go to cap.glass_boxes instead: they get a shadow of their
    own (pill_shadow.py), not a legend plate."""

    def __enter__(self):
        global _text_sink
        self._prev, self.boxes, self.texts, self.colours, self.glass_boxes = \
            _text_sink, [], [], [], []
        _text_sink = self
        return self

    def __exit__(self, *exc):
        global _text_sink
        _text_sink = self._prev


def _note_box(cr, x, y, w, h, text, glass=False, colour=None):
    if _text_sink is None:
        return
    if colour is None:
        src = cr.get_source()
        if isinstance(src, cairo.SolidPattern):
            colour = src.get_rgba()[:3]
    pts = [cr.user_to_device(x + dx, y + dy) for dx in (0, w) for dy in (0, h)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    if glass:
        _text_sink.glass_boxes.append(box)
        return
    _text_sink.boxes.append(box)
    _text_sink.texts.append(text)
    _text_sink.colours.append(tuple(colour[:3]) if colour else None)


def _font(size, bold=False):
    """The theme's font at `size` (scaled by text_scale), bold or in the
    theme's text_weight (B-20)."""
    t = theme.current()
    weight = t.text_bold if bold else t.text_weight
    if t.text_scale != 1.0:
        size = size * t.text_scale
    return Pango.FontDescription.from_string(f"{t.font} {weight} {size}")


def _case(text):
    """`text` in the theme's text_transform."""
    tr = theme.current().text_transform
    return text.upper() if tr == "upper" else text.lower() if tr == "lower" else text


def _set_text(lo, text):
    """Put `text` into a layout in the theme's case and letter spacing."""
    lo.set_text(_case(text), -1)
    sp = theme.current().text_spacing
    if sp:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_letter_spacing_new(int(sp * Pango.SCALE)))
        lo.set_attributes(attrs)


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


# Active-outputs pill material — the split centre strip and the OSD draw the
# same frosted glass (see _glass_pill), so it lives here once. Picked from
# in-context renders over real wallpapers and a desktop screenshot: dense
# enough that busy content behind it (text) stays calm, light enough that
# the background still shows through. No shadow or outline — on request,
# those read as a different design language than the HUD's soft backdrop.
GLASS_PILL    = dict(top=(1, 1, 1, 0.72), bottom=(0.955, 0.96, 0.975, 0.61), sheen=0.13)
GLASS_PILL_FG = (0.08, 0.08, 0.10, 0.92)


def _fade_glass(g, alpha):
    """Copy of a _glass_pill spec with every alpha scaled by `alpha`."""
    return {"top":    g["top"][:3] + (g["top"][3] * alpha,),
            "bottom": g["bottom"][:3] + (g["bottom"][3] * alpha,),
            "sheen":  g.get("sheen", 0) * alpha}


def _glass_pill(cr, x, y, w, h, r, g):
    """
    Faked frosted-glass pill — real backdrop blur isn't available to a
    layer-shell surface, so the material is a translucent milky fill that
    lightens whatever is behind it, plus a faint highlight on top:

      top    — RGBA fill at the top edge    } vertical gradient body
      bottom — RGBA fill at the bottom edge }
      sheen  — alpha of a white highlight fading out over the upper half
    """
    body = cairo.LinearGradient(0, y, 0, y + h)
    body.add_color_stop_rgba(0, *g["top"])
    body.add_color_stop_rgba(1, *g["bottom"])
    cr.set_source(body)
    _rrect(cr, x, y, w, h, r)
    cr.fill()

    sheen = g.get("sheen", 0)
    if sheen:
        cr.save()
        _rrect(cr, x, y, w, h, r)
        cr.clip()
        hl = cairo.LinearGradient(0, y, 0, y + h * 0.55)
        hl.add_color_stop_rgba(0, 1, 1, 1, sheen)
        hl.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.set_source(hl)
        cr.rectangle(x, y, w, h * 0.55)
        cr.fill()
        cr.restore()


def _txt(cr, x, y, text, size=12, bold=False, ha="left", va="top"):
    lo = PangoCairo.create_layout(cr)
    lo.set_font_description(_font(size, bold))
    _set_text(lo, text)
    pw, ph = lo.get_pixel_size()
    tx = x - (pw if ha == "right" else pw / 2 if ha == "center" else 0)
    ty = y - (ph if va == "bottom" else ph / 2 if va == "mid" else 0)
    _note_box(cr, tx, ty, pw, ph, text)
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
    lo.set_font_description(_font(size, bold))
    _set_text(lo, text)
    ink, _logical = lo.get_extents()
    ix, iy = ink.x / Pango.SCALE, ink.y / Pango.SCALE
    iw, ih = ink.width / Pango.SCALE, ink.height / Pango.SCALE
    tx = x - ix - (iw if ha == "right" else iw / 2 if ha == "center" else 0)
    ty = y - iy - (ih if va == "bottom" else ih / 2 if va == "mid" else 0)
    _note_box(cr, tx + ix, ty + iy, iw, ih, text)
    cr.new_path()
    cr.move_to(tx, ty)
    PangoCairo.layout_path(cr, lo)
    cr.fill()


def _txt_size(cr, text, size=12, bold=False):
    """Return (pixel_width, pixel_height) of text without drawing."""
    lo = PangoCairo.create_layout(cr)
    lo.set_font_description(_font(size, bold))
    _set_text(lo, text)
    return lo.get_pixel_size()


def _icon_slot(cr, icon, size):
    """(slot width, gap) for a label icon — fixed per size so the text of a
    column of labels stays flush whatever each glyph's own width."""
    return max(_txt_size(cr, icon, size)[0], round(size * 1.5)), round(size * 0.4)


def _txt_icon(cr, x, y, text, size=12, ha="left", va="top"):
    """_txt for a label that may carry a leading icon ("☀ Brightness Up",
    B-17). The icon sits at the anchor end — the side x is on, which in the
    split renderer is always the button's side — centred in a fixed slot,
    the text after it. So the icon reads left of the text on the left half
    and right of it on the right half, mirrored like the layout. Plain
    labels and ha="center" draw exactly as _txt."""
    icon, rest = split_icon(text)
    if icon is None or ha == "center":
        _txt(cr, x, y, text, size, ha=ha, va=va)
        return
    slot, gap = _icon_slot(cr, icon, size)
    sign = 1 if ha == "left" else -1
    _txt(cr, x + sign * slot / 2, y, icon, size, ha="center", va=va)
    _txt(cr, x + sign * (slot + gap), y, rest, size, ha=ha, va=va)


def _icon_indent(cr, text, size=12):
    """How far _txt_icon pushes the text of `text` past its anchor — 0
    without an icon. Lets a line under it (a B-18 note) align with the
    text rather than the icon."""
    icon, _rest = split_icon(text)
    if icon is None:
        return 0
    slot, gap = _icon_slot(cr, icon, size)
    return slot + gap


def _txt_icon_size(cr, text, size=12):
    """_txt_size of what _txt_icon draws for `text`."""
    icon, rest = split_icon(text)
    if icon is None:
        return _txt_size(cr, text, size)
    slot, gap = _icon_slot(cr, icon, size)
    w, h = _txt_size(cr, rest, size)
    return slot + gap + w, max(h, _txt_size(cr, icon, size)[1])


def _txt_markup(cr, x, y, markup, size=12, ha="left", va="top"):
    """Like _txt but accepts Pango markup (inline colours via <span foreground=…>)."""
    lo = PangoCairo.create_layout(cr)
    lo.set_font_description(_font(size))
    lo.set_markup(markup, -1)
    pw, ph = lo.get_pixel_size()
    tx = x - (pw if ha == "right" else pw / 2 if ha == "center" else 0)
    ty = y - (ph if va == "bottom" else ph / 2 if va == "mid" else 0)
    _note_box(cr, tx, ty, pw, ph, markup)
    cr.move_to(tx, ty)
    PangoCairo.show_layout(cr, lo)


def _pill_row(cr, cx, cy, labels, sep="›", size=9,
              bg=(1, 1, 1, 0.10), fg=(1, 1, 1, 0.9),
              border=None, sep_rgba=(0.55, 0.55, 0.55, 0.7),
              ha="center", styles=None, icons=None, prefix_icons=None, icon_size=None,
              glass=None):
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
    glass      — optional dict (see _glass_pill) that replaces the flat `bg`
                 fill with a faked glass material; `border` still applies.
    """
    if not labels:
        return
    icons = icons or [None] * len(labels)
    prefix_icons = prefix_icons or [None] * len(labels)

    PX, PY    = 7, 2   # horizontal / vertical padding inside pill
    SEP_GAP   = 4      # space on each side of a separator glyph
    PILL_GAP  = 5      # gap between adjacent pills when sep is empty string
    font_str  = _font(size, True)
    sep_font  = _font(size)

    def _lo(text, markup_font):
        lo = PangoCairo.create_layout(cr)
        lo.set_font_description(markup_font)
        _set_text(lo, text)
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
        # A filled pill reads as its fill colour, a faint one as its text.
        _note_box(cr, x, pill_y, pill_w, ph, labels[i], glass=glass is not None,
                  colour=p_bg if len(p_bg) > 3 and p_bg[3] >= 0.5 else p_fg)

        # Background
        if glass is not None:
            _glass_pill(cr, x, pill_y, pill_w, ph, r, glass)
        else:
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
