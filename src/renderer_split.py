"""
renderer_split.py — Experimental split-screen HUD renderer (issue #21).

Right half of the screen, top → bottom: R1/R2 → Y/X/B/A+Start+RStick →
RPad+QAM(BTN_BASE) → R4/R5. Mirrored on the left. Each cluster is built from
individual controls extracted from the source SVGs as standalone vector
shapes (see parts.py) — not a cropped piece of the full artwork — blown up
large and pinned toward its screen edge; callout lines run inward into the
centre column, which carries the legend text, breadcrumb and
title-bar-equivalent controls.

Classification of "what to show" per button comes from viewmodel.py, shared
with the classic renderer (renderer.py) — only the geometry differs here.
"""

import math
import time
from dataclasses import dataclass, replace

import cairo

from helpers import (_rrect, _filled_button, _txt, _txt_icon, _icon_indent, _txt_smooth, _txt_size, _pill_row,
                     capture_text_boxes, _breeze_icon, _THEMED_PAD)
from viewmodel import classify_all, pad_legend_vm, PadLegendVM
from callouts import _BTNS, _callouts, _Callout, _btn_short, _SHOW_ALL
from trackpads import _draw_pad, _draw_stick, _LPAD, _RPAD, _LSTICK, _RSTICK
from clusters import CLUSTERS, CLUSTER_BUTTONS, LEFT_STACK, RIGHT_STACK
from layout_split import (compute_layout, center_badge_rect, center_close_rect, center_classic_rect,
                          center_theme_rect, theme_panel_rect)
from parts import draw_part, part_bbox, clip_to_part, part_subpaths, stroke_outline, idle_fill
from shadow import (GroupShadowSpec, group_shadow_layers, ink_colours, paint_bleed, paint_scaled,
                    merges_plates, paint_plates, plate_layer,
                    style_from_env)
import theme
from reveal import FULL, crumb_names
from elements import ELEMENTS, ELEMENT_IDS, side_of
from settings import dbg, debug_enabled

_BG = (0.031, 0.031, 0.071)

# Which parts (see parts.py's _REGISTRY) make up each cluster. Every part's
# subpaths carry their original absolute SVG-space coordinates, and a
# cluster's (ox, oy, scale) transform maps *any* point in that SVG's
# coordinate space to screen space (not just points inside the cluster's own
# crop box) — so a part lands correctly as long as it comes from the same
# source SVG (front/back) as the cluster it's listed under.
_CLUSTER_PARTS = {
    "l_shoulder": ["shoulder_l", "shoulder_l_split"],
    "l_face":     ["dpad", "stick_l_fixed", "pill_view"],
    "l_pad":      ["trackpad_l", "pill_mode"],
    "l_paddles":  ["paddle_l4", "paddle_l5"],

    "r_shoulder": ["shoulder_r", "shoulder_r_split"],
    "r_face":     ["btn_y", "btn_x", "btn_b", "btn_a", "stick_r_fixed", "pill_start"],
    "r_pad":      ["trackpad_r", "pill_base"],
    "r_paddles":  ["paddle_r4", "paddle_r5"],
}

# Which _BTNS key lights up each part — drives the active-state fill wash.
# Parts not listed here (stick rings, trackpad bezel, shoulder swoop) are
# either handled separately (trackpad/stick, via trackpads.py) or have no
# single button of their own (the shoulder swoop — see SHOULDER_MARKS below).
_PART_BTN = {
    "btn_y": "BTN_NORTH", "btn_x": "BTN_WEST", "btn_b": "BTN_EAST", "btn_a": "BTN_SOUTH",
    "pill_view": "BTN_SELECT", "pill_start": "BTN_START",
    "pill_mode": "BTN_MODE", "pill_base": "BTN_BASE",
    "paddle_l4": "BTN_GRIPL", "paddle_l5": "BTN_GRIPL2",
    "paddle_r4": "BTN_GRIPR", "paddle_r5": "BTN_GRIPR2",
}


# Buttons that now carry their own in-shape label (see _draw_in_shape_labels)
# — when there's nothing beyond the name to show for one of these (unbound,
# no hint, no sub-label, nothing pending), its legend row is dropped outright
# instead of sitting there as a bare "X: —" the shape already said for free.
# Every row's "Name:" prefix is dropped regardless of this set (see
# show_name below) — this set only controls whether the *row itself*
# survives being empty, not the prefix.
_INSHAPE_LABELED = {
    "BTN_NORTH", "BTN_WEST", "BTN_EAST", "BTN_SOUTH",
    "BTN_THUMBL", "BTN_THUMBR",
    "BTN_MODE", "BTN_BASE", "BTN_START",
}

# L1/L2/R1/R2, the paddles, and the pill buttons don't get a legend row at
# all — no dot, no line to the centre column, full stop. The distance to
# that column was the actual complaint (the button's identity is already on
# the shape; running a line across half the screen just to say what it's
# bound to was the clutter). See _draw_adjacent_bindings and
# _draw_scale_button_live's own adjacent-text block: when one of these is
# bound, its action text is drawn directly beside the button instead — once
# that exists, the far-away legend row is pure duplication, not just
# declutter-able but *wrong* to keep (two different answers to "what does
# this do" for the same button, deliberately not just hidden-until-bound).
_ADJACENT_LABELED = {
    "BTN_TL", "BTN_TL2", "BTN_TR", "BTN_TR2",
    "BTN_GRIPL", "BTN_GRIPL2", "BTN_GRIPR", "BTN_GRIPR2",
    "BTN_SELECT", "BTN_START",
    "BTN_THUMBL", "BTN_THUMBR",
    # BTN_MODE/BTN_BASE (Steam/QAM) deliberately NOT here even though they
    # also got adjacent text: BTN_BASE's legend row is how its Gaming Mode
    # sub_label hint shows up at all, including while unbound — being in
    # this set skips row-construction unconditionally (see
    # _draw_cluster_callouts), which would delete that hint along with the
    # redundant binding text. Scoped to exactly what was asked (View/Start)
    # rather than guessing the other two pills into the same bucket.
}

# In-shape label sizes. One shared size for every "normal" button label
# (ABXY, L1/L2/R1/R2, L3/R3) — matches the external legend's own font size
# (_callouts() is called with size=13 in this renderer) rather than scaling
# each one off its own button's screen size, which visibly produced a
# different size per button instead of a consistent label scale. Paddles get
# their own, smaller size on request — their buttons are small and square,
# and the full unified size crowded them.
_LABEL_SIZE = 13.0
_PADDLE_LABEL_SIZE = 11.0

# Every standalone single-shape button (one outline, one button, unlike the
# shoulders' shared wedge split by a half-plane — see _draw_shoulder_fills)
# gets the plain "press = scale down toward centre" feedback, drawn live
# every frame right alongside draw_dpad_live, for the same reason: an
# animation can't be baked into a bitmap that only rebuilds on a vms/pv
# change. L1/L2/R1/R2 are deliberately not here — scaling "half" of a
# shape two buttons share isn't the same kind of operation, and doing it
# well needs its own pass, not a bolt-on to this one.
# btn_key -> (part_name, cluster_name) — cluster_name is which of
# cluster_tx's entries carries this button's (ox, oy, scale).
_SCALE_ANIM_PARTS = {
    "BTN_NORTH": ("btn_y", "r_face"), "BTN_WEST": ("btn_x", "r_face"),
    "BTN_EAST":  ("btn_b", "r_face"), "BTN_SOUTH": ("btn_a", "r_face"),
    # L3/R3 (BTN_THUMBL/BTN_THUMBR) are deliberately NOT here — see
    # trackpads.py's _draw_stick and _STICK_SCALE_MAX just below instead.
    # "stick_l_fixed"/"stick_r_fixed" (what this dict would point them at)
    # is the *decorative outer bezel ring*, which never moves on a real
    # stick; scaling it down on a click press was scaling the wrong ring.
    # The actual moving part — the two inner rings that make up the stick
    # cap — isn't a parts.py SVG shape at all; trackpads.py draws it
    # procedurally every frame already (for analog deflection), so the
    # press-scale lives there instead, applied to those two radii directly.
    "BTN_SELECT": ("pill_view", "l_face"), "BTN_START": ("pill_start", "r_face"),
    "BTN_MODE": ("pill_mode", "l_pad"), "BTN_BASE": ("pill_base", "r_pad"),
    "BTN_GRIPL": ("paddle_l4", "l_paddles"), "BTN_GRIPL2": ("paddle_l5", "l_paddles"),
    "BTN_GRIPR": ("paddle_r4", "r_paddles"), "BTN_GRIPR2": ("paddle_r5", "r_paddles"),
}
_SCALE_ANIM_MAX = 0.08   # fraction scaled down at full press
_SCALE_ANIM_PART_NAMES = {part_name for part_name, _cluster in _SCALE_ANIM_PARTS.values()}
_SCALE_ANIM_BTN_BY_PART = {part_name: btn_key for btn_key, (part_name, _cluster) in _SCALE_ANIM_PARTS.items()}

# Parts whose own outline is not one closed loop but several small closed
# fragments authored separately (paddles: 4 straight edges + 4 corner arcs,
# each with its own M...Z — see parts.py). Filling that outline directly
# fills each fragment's own tiny auto-closed sliver instead of the one
# rounded-rect area they outline together, which is invisible in practice.
# These get a plain rounded-rect fill from their bounding box instead.
_FRAGMENTED_FILL_PARTS = {"paddle_l4", "paddle_l5", "paddle_r4", "paddle_r5"}
# Measured from the actual corner-arc fragments' bounding boxes (12.13x12.13
# — a quarter-circle's bbox is exactly its own radius, not its diameter) —
# not a guess, so the fill's rounded corners actually match the stroked
# outline's instead of visibly disagreeing with it.
_PADDLE_CORNER_R = 12.13

# Legibility nudge: the d-pad and View/Start pill sit close enough to the
# stick in the source art that, once blown up, their callout lines cross
# right over the stick circle. Pushed away from the stick by a small,
# deliberately-not-faithful-to-the-original screen-pixel offset — applied to
# both the drawn part and its callout dot, via _part_offset()/_btn_offset()
# below, so the line still starts exactly on the shape it labels.
#
# pill_view/pill_start's own offset also does double duty as the "give this
# column more vertical breathing room" request — pushed further up (from the
# original -9) on top of the legibility nudge, paired with _STICK_Y_NUDGE
# pushing the stick down, so there's real separation between the d-pad/ABXY
# row and *both* neighbours instead of all three sitting close together.
#
# _STICK_Y_NUDGE: how far the stick (both its static outer-bezel part and
# the live analog-deflection rings drawn by trackpads.py) is pushed down
# from its source position, screen px — the other half of that same request.
_STICK_Y_NUDGE = 60
# dpad/ABXY's shared vertical nudge — same magnitude for both so the two
# sides stay symmetric (dpad's own -9 x is unrelated, see the legibility
# note above; ABXY needs no x-nudge, nothing for it to dodge there).
_FOUR_BTN_Y_NUDGE = -22
_PART_OFFSET = {
    "dpad": (-9, _FOUR_BTN_Y_NUDGE), "pill_view": (0, -55), "pill_start": (0, -55),
    "stick_l_fixed": (0, _STICK_Y_NUDGE), "stick_r_fixed": (0, _STICK_Y_NUDGE),
    "btn_y": (0, _FOUR_BTN_Y_NUDGE), "btn_x": (0, _FOUR_BTN_Y_NUDGE),
    "btn_b": (0, _FOUR_BTN_Y_NUDGE), "btn_a": (0, _FOUR_BTN_Y_NUDGE),
}
_BTN_OFFSET = {
    "BTN_DPAD_UP": (-9, _FOUR_BTN_Y_NUDGE), "BTN_DPAD_DOWN": (-9, _FOUR_BTN_Y_NUDGE),
    "BTN_DPAD_LEFT": (-9, _FOUR_BTN_Y_NUDGE), "BTN_DPAD_RIGHT": (-9, _FOUR_BTN_Y_NUDGE),
    "BTN_SELECT": (0, -55), "BTN_START": (0, -55),
    "BTN_THUMBL": (0, _STICK_Y_NUDGE), "BTN_THUMBR": (0, _STICK_Y_NUDGE),
    "BTN_NORTH": (0, _FOUR_BTN_Y_NUDGE), "BTN_WEST": (0, _FOUR_BTN_Y_NUDGE),
    "BTN_EAST": (0, _FOUR_BTN_Y_NUDGE), "BTN_SOUTH": (0, _FOUR_BTN_Y_NUDGE),
}

# l_pad/r_pad (trackpad + Steam/QAM pill, as one block) pushed down a bit —
# the other side of the same vertical-spacing request: more gap above them,
# under the (now higher) stick.
_PAD_Y_NUDGE = 14

# L1/L2/R1/R2 callout dots: _BTNS's coordinates for these four are in the
# *back*-SVG coordinate space (that's still what the classic renderer draws
# them on), but the shoulder cluster's art now comes from steamdeckTop.svg
# instead (see parts.py) — an unrelated coordinate space. Mapping back-SVG
# (78, 22) through the top-cluster's transform doesn't land anywhere near
# the drawn trigger, which is exactly the "labels shifted way up" bug.
# These are full replacement positions (top-SVG space, inside the trigger
# wedge, above/below its L1/L2 divider line) — not deltas like _BTN_OFFSET.
_BTN_POS_OVERRIDE = {
    "BTN_TL":  (76, 132), "BTN_TL2": (61, 185),
    "BTN_TR":  (984, 132), "BTN_TR2": (999, 185),
}

# ABXY's own callout dot sits at the circle's left edge instead of its centre
# (on request) — radius measured off btn_y/btn_x/btn_b/btn_a's own bbox
# (part_bbox), all four ~30.14 SVG units wide, so one shared radius covers
# all of them.
_ABXY_BTNS = {"BTN_NORTH", "BTN_WEST", "BTN_EAST", "BTN_SOUTH"}
_ABXY_RADIUS = 15.07

# Legibility shadows (see shadow.py): each element casts its own, following
# its shape — the trackpad's rounded rect, a pill's oval, a stick's circle,
# one shoulder half, each legend line — built from exactly what that element
# draws, so it looks the same shown alone or with others, and slides/fades
# with it. Their wide soft clouds (the bleed) merge into each other instead
# of stacking. A real blur-behind would need compositor support this stack
# doesn't have (gtk4-layer-shell doesn't expose KDE's blur protocol).
def shadow_style():
    """The active theme's shadow style (B-20)."""
    return theme.current().shadow_style()


def element_box(element, tx):
    """(x, y, w, h) in screen px of an element's own shape(s) at rest —
    the union of its parts' boxes under its cluster transform tx."""
    ox, oy, scale = tx
    xs, ys = [], []
    for part in element.parts:
        x0, y0, x1, y1 = part_bbox(part)
        dx, dy = _PART_OFFSET.get(part, (0, 0))
        if element.kind in ("upper", "lower"):
            dx = dy = 0
        xs += [ox + dx + x0 * scale, ox + dx + x1 * scale]
        ys += [oy + dy + y0 * scale, oy + dy + y1 * scale]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _element_shadow_spec(element, tx, text_boxes, ink, text_colours=(), shapes=()):
    """shapes: filled buttons (cap.shapes), shadowed as the shapes they are."""
    parts, rrects = [], [tuple(round(v, 1) for v in r) for r in shapes]
    if element.kind != "center":
        ox, oy, scale = tx
        halves = (shoulder_half_polys(element.cluster)
                  if element.kind in ("upper", "lower") else {})
        for part in element.parts:
            if part in _FRAGMENTED_FILL_PARTS:
                # Drawn as a rounded rect from its bbox (see _render_part_cluster).
                dx, dy = _PART_OFFSET.get(part, (0, 0))
                x0, y0, x1, y1 = part_bbox(part)
                rrects.append((ox + dx + x0 * scale, oy + dy + y0 * scale, (x1 - x0) * scale,
                               (y1 - y0) * scale, _PADDLE_CORNER_R * scale))
                continue
            if halves:
                # One half of the shared shoulder wedge: no part offset (see
                # element_box), cut by its own half-plane.
                clip = tuple(halves[element.buttons[0]])
                parts.append((part, ox, oy, scale, clip))
                continue
            dx, dy = _PART_OFFSET.get(part, (0, 0))
            parts.append((part, ox + dx, oy + dy, scale, None))
    # Sub-pixel jitter in a recorded box shouldn't count as a geometry change.
    boxes = tuple(tuple(round(v) for v in b) for b in text_boxes)
    colours = tuple(c and tuple(round(v, 2) for v in c) for c in text_colours)
    return GroupShadowSpec(tuple(parts), tuple(rrects), boxes, tuple(round(v) for v in ink),
                           colours)


# Keyed on the shadow's geometry and the legend strings and colours, not on
# the element's bitmap: a press rebuilds the element's layer but leaves its
# shadow (and its GPU texture) alone; a legend changing colour retints it. The edge shadow is
# traced from the bitmap of the build that missed — the same strokes and
# glyphs, since nothing in the key changed. That holds only for what the key
# sees: a filled button's label has no plate, so its text and fill are keyed
# as cap.looks (the badge's Paused <-> Active, B-14), and the theme is, for
# its fonts.
_shadow_layer_cache = {}


def _element_shadows(element, tx, cap, surf, rect, dev_scale, pressing=False, words=()):
    """(shadow, bleed, plate) slots of a GroupLayer — see shadow.group_shadow_layers
    and shadow.plate_layer.
    words: what the element's legends say, to tell whether a press changed it."""
    hit = _shadow_layer_cache.get(element.id)
    if pressing and hit is not None and hit[2] == words:
        # A mid-press button is drawn live, not into this bitmap — its label
        # and adjacent text are missing from it. Keep the at-rest shadow
        # rather than letting the legend's shadow blink out for the press —
        # unless the press changed what the legends say (··· held as a
        # modifier drops its Gaming Mode line): that shadow is of text gone.
        return hit[1]
    # An empty bitmap (everything drawn live) has a 1-px rect at the origin,
    # not ink: counted, it stretched the shadow from the screen's corner.
    ink = rect if surf.get_width() > 1 or surf.get_height() > 1 else ()
    spec = _element_shadow_spec(element, tx, cap.boxes, ink, cap.colours, cap.shapes)
    style = shadow_style()
    if style.tint or style.rim_alpha > 0:
        # The tint follows the colours actually drawn (see shadow._local_tint).
        spec = replace(spec, ink_colours=ink_colours(surf, rect))
    key = (spec, tuple(cap.texts), tuple(cap.looks), theme.current(), shadow_style(), dev_scale)
    if hit is not None and hit[0] == key:
        return hit[1]
    merged = merges_plates(style)
    layers = (*group_shadow_layers(spec, style, surf, rect, dev_scale, plate=not merged),
              plate_layer(spec, style) if merged else None)
    _shadow_layer_cache[element.id] = (key, layers, words)
    return layers


def _legend_words(element, vms):
    """The text an element's buttons put in their legends."""
    return tuple((k, vms[k].action, vms[k].sub_label, vms[k].note)
                 for k in element.buttons if k in vms)


def _side_slide_offset(side, sw, open_t):
    """How far a side's groups (cached bitmap and live overlay alike) are
    shifted from their resting position. One offset per side, the same for
    every group on it, so a legend moves exactly with the art it labels
    instead of its callout lines re-angling every frame."""
    travel = sw * 0.5
    return -travel * (1 - open_t) if side == "left" else travel * (1 - open_t)


def _dev_surface(sw, sh, dev_scale):
    """A screen-sized ARGB surface at *device* resolution (logical sw×sh ×
    the fractional scale factor), drawn into in logical coordinates through
    cairo's device scale. As a GPU texture placed 1:1 on the device pixel
    grid (see win.py) it stays as crisp as drawing straight into GTK's own
    cairo node did, instead of being upscaled from logical resolution."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                              int(math.ceil(sw * dev_scale)), int(math.ceil(sh * dev_scale)))
    surf.set_device_scale(dev_scale, dev_scale)
    return surf


def _render_cropped(draw, sw, sh, dev_scale, pad=2):
    """Run draw(cr) once into a recording surface, then replay it onto a
    device-resolution surface cut to its ink, aligned to whole device
    pixels so the texture still lands 1:1 on the pixel grid. Returns
    (surface, (x, y, w, h)) with the rect in logical screen px."""
    rec = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
    draw(cairo.Context(rec))
    ix, iy, iw, ih = rec.ink_extents()
    s = dev_scale
    if iw <= 0 or ih <= 0:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        surf.set_device_scale(s, s)
        return surf, (0.0, 0.0, 1 / s, 1 / s)
    dx0 = max(0, math.floor((ix - pad) * s))
    dy0 = max(0, math.floor((iy - pad) * s))
    dx1 = min(math.ceil(sw * s), math.ceil((ix + iw + pad) * s))
    dy1 = min(math.ceil(sh * s), math.ceil((iy + ih + pad) * s))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, dx1 - dx0, dy1 - dy0)
    surf.set_device_scale(s, s)
    cr = cairo.Context(surf)
    cr.translate(-dx0 / s, -dy0 / s)
    cr.set_source_surface(rec, 0, 0)
    cr.paint()
    return surf, (dx0 / s, dy0 / s, (dx1 - dx0) / s, (dy1 - dy0) / s)


@dataclass
class GroupLayer:
    """One element's cached layers, at rest (an element is one button with
    its shape, legend and shadow — see elements.py). win.py places them
    with the element's own translate/opacity; draw_hud_split does the same
    in cairo."""
    name: str            # element id
    side: str            # "left" | "right" | None (center)
    surface: object      # cairo.ImageSurface, device resolution, cut to its ink
    rect: tuple          # (x, y, w, h) logical px — where surface goes
    tx: tuple            # (ox, oy, scale) of its cluster; None for center
    shadow: tuple        # (surface, x, y, w, h): core + edge shadow, final alpha; or None
    bleed: tuple         # (surface, x, y, w, h): pre-curve field, merged across elements; or None
    vms: dict            # the ButtonVMs this element draws with (masked)
    look: tuple = None   # what it shows, minus mid-press: equal looks = same picture
    plate: tuple = None  # (surface, x, y, w, h): its plate's field for the merged
                         # plate pass (shadow.plate_layer); None: the plate is in `shadow`


def _cluster_tx(name, sw, sh):
    clusters, _anchor_x, _center = compute_layout(sw, sh)
    x, y, w, h, scale = clusters[name]
    _svg, (x0, y0, x1, y1) = CLUSTERS[name]
    ox, oy = x - x0 * scale, y - y0 * scale
    if name in ("l_pad", "r_pad"):
        oy += _PAD_Y_NUDGE
    return ox, oy, scale


def _mask_vms(vms, shown):
    """The buttons an element doesn't show keep their art state but lose
    what they're bound to — which is what every adjacent/in-shape action
    text keys off, so their texts stay out of this element."""
    masked = dict(vms)
    for k, vm in vms.items():
        if k not in shown:
            masked[k] = replace(vm, bound=False, action="—", layer_override=False,
                                is_combo=False, is_hint=False, sub_label=None)
    return masked


def _shown_buttons(element, content):
    if content.legends is None:
        return set(element.buttons)
    return set(element.buttons) & set(content.legends)


# Per-element bitmap cache. Keyed on what its cluster lays out — every
# button of the cluster, since rows an element hides still take part in
# the legend layout — plus its own presses, its pad and its content.
# Per element, its last few builds, most recent first: L1 on/off/on in the
# full HUD otherwise rebuilt every changed element each time (~110 ms).
_group_cache = {}
_LOOKS_KEPT = 4


def _look(content, vms_key, pv_key):
    """What an element shows, for win.py to tell a new picture from the same
    one: a press doesn't count — it is feedback, not a change of meaning, and
    crossfading it would lag the press."""
    return (content, {k: replace(v, is_active=False) for k, v in vms_key.items()}, pv_key)


def _get_group_layer(element, content, vms, pv, anchor_x_val, sw, sh, active_press, dev_scale):
    name = element.id
    cluster = element.cluster
    side = side_of(name)
    shown = _shown_buttons(element, content)
    gvms = _mask_vms(vms, shown)
    vms_key = {k: v for k, v in vms.items() if k in CLUSTER_BUTTONS.get(cluster, ())}
    pv_key = ((pv.lpad_label, pv.lpad_active, pv.gesture) if cluster == "l_pad" else
              (pv.rpad_label, pv.rpad_active, pv.gesture) if cluster == "r_pad" else None)
    key = (content, frozenset(k for k in active_press if k in element.buttons), pv_key,
           sw, sh, dev_scale, theme.current())
    entries = _group_cache.setdefault(name, [])
    for i, c in enumerate(entries):
        if c["key"] == key and c["vms"] == vms_key:
            entries.insert(0, entries.pop(i))
            # A press builds from the at-rest shadow of the look on screen.
            _shadow_layer_cache[name] = c["shadow"]
            return c["layer"]
    c = entries[0] if entries else None

    tx = _cluster_tx(cluster, sw, sh)

    def draw(cr):
        _render_part_cluster(cr, cluster, *tx, gvms, active_press=active_press, pv=pv,
                             element=element)
        _draw_cluster_callouts(cr, side, cluster, tx, vms, pv, anchor_x_val,
                               shown=shown, pad_row=element.kind == "pad")

    _t0 = time.perf_counter()
    with capture_text_boxes() as cap:
        surf, rect = _render_cropped(draw, sw, sh, dev_scale)
    _t1 = time.perf_counter()
    shadow, bleed, plate = _element_shadows(element, tx, cap, surf, rect, dev_scale,
                                     pressing=bool(set(element.buttons) & active_press),
                                     words=_legend_words(element, gvms))
    dbg(f"{name} element surface REBUILT: "
        f"{(_t1 - _t0) * 1000:.1f}ms + shadow {(time.perf_counter() - _t1) * 1000:.1f}ms "
        f"({sw}x{sh}@{dev_scale:.3g})")
    if c is not None and debug_enabled():
        _diff_vms(name, c["vms"], vms_key)
    layer = GroupLayer(name=name, side=side, surface=surf, rect=rect, tx=tx,
                       shadow=shadow, bleed=bleed, vms=gvms, look=_look(content, vms_key, pv_key),
                       plate=plate)
    entries.insert(0, {"key": key, "vms": vms_key, "layer": layer,
                       "shadow": _shadow_layer_cache.get(name)})
    del entries[_LOOKS_KEPT:]
    return layer


def _diff_vms(side, old, new):
    if old is None:
        return
    changed = [k for k in new if old.get(k) != new[k]]
    if changed:
        detail = []
        for k in changed[:3]:
            o, n = old.get(k), new[k]
            if o is None:
                continue
            fields = [f for f in n.__dataclass_fields__ if getattr(o, f) != getattr(n, f)]
            detail.append(f"{k}:" + ",".join(f"{f}={getattr(o, f)!r}->{getattr(n, f)!r}" for f in fields))
        dbg(f"{side} vms changed: {changed} {' '.join(detail)}")


# Centre column (title, status badge, breadcrumb, close affordance) — the
# ninth group. Cached like the clusters, drawn at full opacity; its
# visibility fades it as a whole at blit time. Keyed only on the state it
# actually reads. The active outputs are not part of it: the OSD shows them,
# over the open HUD too (osd_win.py).
_center_cache = []   # [(key, layer)], most recent first, like _group_cache


def _get_center_layer(state, center, sw, sh, dev_scale=1.0, content=FULL):
    """content: FULL, or reveal.crumbs(...) for the breadcrumb row alone."""
    ctx = state.get("context") or {}
    names = crumb_names(content)
    crumbs_only = names is not None
    key = (sw, sh, dev_scale, theme.current(), tuple(ctx.get("config_stack") or ()),
           tuple(ctx.get("held_modifiers") or ()),
           None if crumbs_only else bool(ctx.get("paused", False)), names)
    for i, (k, layer) in enumerate(_center_cache):
        if k == key:
            _center_cache.insert(0, _center_cache.pop(i))
            return layer
    with capture_text_boxes() as cap:
        surf, rect = _render_cropped(lambda cr: _draw_center(cr, state, center, 1.0, names),
                                     sw, sh, dev_scale)
    shadow, bleed, plate = _element_shadows(ELEMENTS["center"], None, cap, surf, rect, dev_scale)
    layer = GroupLayer(name="center", side=None, surface=surf, rect=rect, tx=None,
                       shadow=shadow, bleed=bleed, vms={}, look=key, plate=plate)
    _center_cache.insert(0, (key, layer))
    del _center_cache[_LOOKS_KEPT:]
    return layer


# The pad *mode* labels only exist while makima's analog export is on, which
# the app switches on/off with the HUD's visibility — so at every open there
# are a few frames with no trackpad data before it arrives. Treating that
# gap as "mode changed to —" forced a full re-render of both sides right as
# the open animation started, and again when the data arrived mid-slide.
# The mode is a config setting, not live input: while no data is present,
# keep the last known labels (touch state dropped, it really is unknown).
_last_pad_vm = None


def _sticky_pad_vm(state):
    global _last_pad_vm
    pads = state.get("trackpads") or {}
    has_modes = any((pads.get(s) or {}).get("mode") for s in ("left", "right"))
    if not has_modes and _last_pad_vm is not None:
        last = _last_pad_vm
        return PadLegendVM(lpad_label=last.lpad_label, lpad_active=False,
                           rpad_label=last.rpad_label, rpad_active=False, gesture=False)
    pv = pad_legend_vm(state)
    if has_modes:
        _last_pad_vm = pv
    return pv


def group_layers(state, sw, sh, contents, press_t=None, dev_scale=1.0):
    """Everything for one frame that doesn't depend on any element's
    visibility: the cached layers of every element in `contents` (element
    id -> reveal.Content) plus what the live overlays need. Shared by
    draw_hud_split (pure-cairo path: fixtures) and win.py's GPU path,
    which turns the same bitmaps into textures and does each element's
    slide/fade as snapshot transforms."""
    _clusters, anchor_x, center = compute_layout(sw, sh)
    vms = classify_all(state, _BTNS.keys())
    pv = _sticky_pad_vm(state)
    pt = press_t or {}
    # Which _SCALE_ANIM_PARTS buttons are mid-press right now (above the
    # threshold — not the continuous value). Decides which buttons the
    # cached bitmap must leave out (see _render_part_cluster) and which the
    # live overlay draws. A plain hold keeps this set unchanged for the
    # whole hold, so the cache only misses at the start and end of a press.
    active_press = frozenset(k for k in _SCALE_ANIM_PARTS if pt.get(k, 0.0) > 0.001)
    groups = {}
    for name, content in contents.items():
        element = ELEMENTS[name]
        if element.kind == "center":
            groups[name] = _get_center_layer(state, center, sw, sh, dev_scale, content)
        else:
            groups[name] = _get_group_layer(element, content, vms, pv, anchor_x[side_of(name)],
                                            sw, sh, active_press, dev_scale)
    connector = (_get_connector_layer(groups, pv, sw, sh, dev_scale)
                 if pv.gesture and "LPad" in groups and "RPad" in groups else None)
    return {
        "groups": groups,
        "connector": connector,
        "contents": dict(contents),
        "center": center,
        "vms": vms,
        "pv": pv,
        "active_press": active_press,
    }


def drop_caches():
    """Forget every cached layer — for win.py when the screen's size or
    scale changed (B-31): none of them can hit again, and at 4K a full look
    set is tens of MB."""
    _group_cache.clear()
    _shadow_layer_cache.clear()
    _center_cache.clear()
    _connector_cache.clear()


def warm_all(state, sw, sh, dev_scale=1.0):
    """Every cached surface the full HUD needs, by the texture name win.py
    gives it — so a prewarm can build them all up front without knowing
    how the HUD is cut."""
    layers = group_layers(state, sw, sh, {e: FULL for e in ELEMENT_IDS}, dev_scale=dev_scale)
    out = {}
    for name, layer in layers["groups"].items():
        out[name] = layer.surface
        if layer.shadow is not None:
            out["shadow_" + name] = layer.shadow[0]
        if layer.bleed is not None:
            out["bleed_" + name] = layer.bleed[0]
        if layer.plate is not None:
            out["plate_" + name] = layer.plate[0]
    return out


def live_rect(name, layers, sw, sh):
    """The strip one element's live overlay is drawn into, at rest: its
    own shape and ink plus a margin (the stick ring and pad dot move
    within it), and room toward the centre for a pressed button's adjacent
    action text. The shape matters on its own: a pressed button is left
    out of the cached bitmap, so the ink alone can shrink right past it."""
    layer = layers["groups"][name]
    element = ELEMENTS[name]
    bx, by, bw, bh = element_box(element, layer.tx)
    x, y, w, h = layer.rect
    if layer.surface.get_width() <= 1 and layer.surface.get_height() <= 1:
        x, y, w, h = bx, by, bw, bh   # nothing cached (all of it live)
    x0, y0 = min(x, bx) - 24, max(0, min(y, by) - 24)
    x1, y1 = max(x + w, bx + bw) + 24, min(sh, max(y + h, by + bh) + 24)
    if any(k in element.buttons for k in layers["active_press"]):
        if side_of(name) == "left":
            x1 += sw * 0.3
        else:
            x0 -= sw * 0.3
    x0, x1 = max(0, x0), min(sw, x1)
    return x0, y0, x1 - x0, y1 - y0


def draw_group_live(cr, name, state, layers, dx, press_t=None, draw_dpad=True):
    """One element's per-frame overlay that can't be cached — its trackpad
    dot, its moving stick rings, its button mid-press — shifted by the
    element's current slide offset dx, so it moves with the cached bitmap
    it sits on instead of detaching from it."""
    layer = layers["groups"][name]
    if layer.tx is None:
        return
    element = ELEMENTS[name]
    pt = press_t or {}
    ox, oy, scale = layer.tx
    ox += dx
    pads = state.get("trackpads") or {}
    gesture = (pads.get("gesture") or {}).get("touching", False)
    sticks = state.get("sticks") or {}

    if element.kind == "pad":
        left = name == "LPad"
        _draw_pad(cr, pads.get("left" if left else "right") or {}, _LPAD if left else _RPAD,
                  gesture, tx=(ox, oy, scale), dim=True)
    elif element.kind == "stick":
        # Stick tx gets its own y-nudge on top of the face cluster's
        # transform — these live-drawn rings aren't a parts.py shape, so
        # they don't pick up _PART_OFFSET the way the static bezel does.
        left = name == "L3"
        _draw_stick(cr, sticks.get("lstick" if left else "rstick", {}), _LSTICK if left else _RSTICK,
                    tx=(ox, oy + _STICK_Y_NUDGE, scale), erase_mode="none",
                    press=pt.get(element.buttons[0], 0.0), fill_rings=True,
                    label=_BTNS[element.buttons[0]][3])
    elif element.kind == "dpad" and draw_dpad:
        # draw_dpad=False when win.py drives a real 3D perspective
        # transform for the d-pad instead (win.py:_draw_dpad_3d) — that
        # needs its own snapshot block, which a flat cairo.Context has no
        # access to.
        draw_dpad_live(cr, ox, oy, scale, layer.vms, press_t)

    for btn_key in element.buttons:
        if btn_key in layers["active_press"]:
            part_name, _cluster = _SCALE_ANIM_PARTS[btn_key]
            _draw_scale_button_live(cr, btn_key, part_name, ox, oy, scale,
                                     layer.vms[btn_key], pt.get(btn_key, 0.0))


def draw_gesture_connector_live(cr, layers, sw, dx_left, dx_right):
    """The two-pads-touching-at-once connector (see _draw_gesture_connector)
    — deliberately its *own* entry point, not part of draw_group_live:
    win.py draws each element's live overlay through its own narrow strip,
    and a connector spanning screen centre needs a full-width, unclipped
    pass or each strip only ever shows the sliver of it that happens to
    fall inside that one strip. Draws only while both pads are present;
    each end follows its own side's offset."""
    pv = layers.get("pv")
    groups = layers["groups"]
    if pv is None or not pv.gesture or "LPad" not in groups or "RPad" not in groups:
        return
    lox, loy, ls = groups["LPad"].tx
    rox, roy, rs = groups["RPad"].tx
    _draw_gesture_connector(cr, (lox + dx_left, loy, ls), (rox + dx_right, roy, rs), pv, sw)


def _draw_gesture_connector(cr, l_tx, r_tx, pv, sw):
    """Both pads touching at once (a two-finger gesture) is one shared
    event, not two independent per-pad ones — on request, the two pads'
    legend lines now run all the way in to the screen's own centre and
    share one label there (_draw_cluster_callouts skips each side's own
    row for this case), instead of each pad showing its own separate
    'Gestures' text on its own side.

    l_tx/r_tx: that pad's (ox, oy, scale) at its *current* (slid) position
    — the same ones the live overlays use — so this lines up
    with the cached art at every point in the open/close animation, not
    just at rest. dot_y is computed exactly like the normal per-pad legend
    row's own dot_y (_draw_cluster_callouts) so the row sits at the same
    height it always has."""
    lox, loy, lscale = l_tx
    rox, roy, rscale = r_tx
    lx = lox + (_LPAD["x"] + _LPAD["w"]) * lscale
    ly = loy + (_LPAD["y"] + _LPAD["h"] / 2) * lscale
    rx = rox + _RPAD["x"] * rscale
    ry = roy + (_RPAD["y"] + _RPAD["h"] / 2) * rscale
    cy = (ly + ry) / 2   # the two should already coincide; average absorbs any drift
    cx = sw / 2

    # The theme's connector tokens (B-12): an amber power line in neon —
    # theme.modifier, the colour the old per-pad row had while a gesture
    # was active. Its glow and shadow come with the cached layer
    # (_get_connector_layer), not from here.
    t = theme.current()
    line_col = (*t.connector_line_rgb(), t.connector_alpha)
    text_col = (*t.connector_label_rgb(), 1.0)
    lw = t.connector_width or t.callout_width
    size = t.connector_label_size
    label = pv.lpad_label     # == pv.rpad_label (viewmodel.gesture_label) while gesturing

    tw, _th = _txt_size(cr, label, size)
    gap = tw / 2 + 6   # stop the lines short of the text, same convention _callouts() uses

    cr.move_to(lx, ly)
    cr.line_to(cx - gap, cy)
    stroke_outline(cr, line_col, lw, t.connector_style)
    cr.move_to(rx, ry)
    cr.line_to(cx + gap, cy)
    stroke_outline(cr, line_col, lw, t.connector_style)

    cr.set_source_rgba(*text_col)
    _txt(cr, cx, cy, label, size=size, ha="center", va="mid")
    # The two lines as (x, y, w, h, r) bands, for the shadow to lay a
    # plate under them as under any shape.
    return ((lx, cy - lw / 2, cx - gap - lx, lw, lw / 2),
            (cx + gap, cy - lw / 2, rx - cx - gap, lw, lw / 2))


# The connector at rest, as a layer of its own like an element's: built
# once per geometry, label and theme, with the theme's shadow under it and
# its own neon glow — both far too slow to make per frame.
_connector_cache = []


def _get_connector_layer(groups, pv, sw, sh, dev_scale):
    l_tx, r_tx = groups["LPad"].tx, groups["RPad"].tx
    t = theme.current()
    key = (l_tx, r_tx, pv.lpad_label, sw, sh, dev_scale, t)
    for i, (k, layer) in enumerate(_connector_cache):
        if k == key:
            _connector_cache.insert(0, _connector_cache.pop(i))
            return layer
    runs = []
    with capture_text_boxes() as cap:
        surf, rect = _render_cropped(
            lambda cr: runs.extend(_draw_gesture_connector(cr, l_tx, r_tx, pv, sw)),
            sw, sh, dev_scale)
    style = replace(shadow_style(), glow_alpha=t.connector_glow,
                    glow_radius=t.connector_glow_radius, glow_text=t.connector_label_glow)
    if not t.connector_shadow:
        # The halo alone: no plate, edge or rim, and no cloud in the merge.
        style = replace(style, core_alpha=0.0, edge_alpha=0.0, rim_alpha=0.0,
                        legend="line")
    shadow = bleed = plate = None
    if t.connector_shadow or t.connector_glow > 0:
        spec = GroupShadowSpec(rrects=tuple(tuple(round(v, 1) for v in r) for r in runs),
                               text_boxes=tuple(tuple(round(v) for v in b) for b in cap.boxes),
                               ink=tuple(round(v) for v in rect),
                               text_colours=tuple(c and tuple(round(v, 2) for v in c)
                                                  for c in cap.colours))
        merged = merges_plates(style)
        shadow, bleed = group_shadow_layers(spec, style, surf, rect, dev_scale, plate=not merged)
        plate = plate_layer(spec, style) if merged else None
        if not t.connector_shadow:
            bleed = None
    layer = GroupLayer(name="connector", side=None, surface=surf, rect=rect, tx=None,
                       shadow=shadow, bleed=bleed, vms={}, look=key, plate=plate)
    _connector_cache.insert(0, (key, layer))
    del _connector_cache[_LOOKS_KEPT:]
    return layer


def backdrop_stops(t):
    """The theme's backdrop (Theme.backdrop_*) as an elliptical gradient over
    the screen: ((centre alpha, edge alpha), rgb), or None for none. The
    ellipse's rim, where the edge alpha is reached, lies at _BACKDROP_R of
    the screen's half-size — the HUD's columns sit beyond it."""
    if t.backdrop_opacity <= 0:
        return None
    v = min(max(t.backdrop_vignette, 0.0), 1.0)
    return (t.backdrop_opacity * (1.0 - v), t.backdrop_opacity), tuple(t.backdrop_color)


_BACKDROP_R = 1.15


def draw_backdrop(cr, sw, sh, alpha):
    """Cairo twin of win.py's backdrop: the theme's dim, at `alpha` (the full
    HUD's open fade)."""
    stops = backdrop_stops(theme.current())
    if stops is None or alpha <= 0:
        return
    (centre, edge), rgb = stops
    cr.save()
    cr.translate(sw / 2, sh / 2)
    cr.scale(sw / 2 * _BACKDROP_R, sh / 2 * _BACKDROP_R)
    grad = cairo.RadialGradient(0, 0, 0, 0, 0, 1)
    grad.add_color_stop_rgba(0, *rgb, centre * alpha)
    grad.add_color_stop_rgba(1, *rgb, edge * alpha)
    grad.set_extend(cairo.EXTEND_PAD)
    cr.set_source(grad)
    cr.paint()
    cr.restore()


def draw_hud_split(cr, front_svg, back_svg, state, sw, sh, open_t=1.0, press_t=None,
                   draw_dpad=True, groups=None):
    """Pure-cairo path. The live HUD uses win.py's GPU path instead (same
    layers, see group_layers); this one stays for fixtures and as the
    reference for what a frame should look like.

    groups: {name: (opacity, dx, Content)} — None means the full HUD, every
    group FULL, faded by open_t and slid by its side's offset."""
    # No full-screen fill here, deliberately: this spans the whole screen,
    # and an opaque background would black out the desktop/game underneath.
    if state.get("unreadable"):
        _draw_unreadable(cr, sw, sh, state["unreadable"])
        return

    if groups is None:
        groups = {name: (open_t, _side_slide_offset(side_of(name), sw, open_t)
                         if side_of(name) else 0.0, FULL)
                  for name in ELEMENT_IDS}
        # The full HUD only — a partial reveal leaves the screen as it is.
        draw_backdrop(cr, sw, sh, open_t)
    t0 = time.perf_counter()
    layers = group_layers(state, sw, sh, {n: g[2] for n, g in groups.items()}, press_t)
    t1 = time.perf_counter()

    # Every shadow first, as one pass, *then* every group's content on top —
    # never one group's shadow and text interleaved, or the next group's
    # shadow spillover lands on the first group's finished text and dims it.
    # The bleed goes first and as one merged pass (see shadow.paint_bleed).
    # The gesture connector is a layer like these at rest (see
    # _get_connector_layer); mid-slide it is drawn live, bare.
    conn = layers["connector"]
    if conn is not None:
        conn_op = min(groups["LPad"][0], groups["RPad"][0])
        if groups["LPad"][1] or groups["RPad"][1]:
            conn = None
    shown = [(layers["groups"][n], dx, opacity) for n, (opacity, dx, _c) in groups.items()]
    if conn is not None:
        # First, so the pads' own plates lie over the line running into them.
        shown.insert(0, (conn, 0.0, conn_op))
    paint_bleed(cr, [(layer.bleed, dx, opacity) for layer, dx, opacity in shown if layer.bleed],
                sw, sh, shadow_style())
    # Then the plates, merged the same way (themes that merge them).
    paint_plates(cr, [(layer.plate, dx, opacity) for layer, dx, opacity in shown if layer.plate],
                 sw, sh, shadow_style())
    for layer, dx, opacity in shown:
        if layer.shadow is None:
            continue
        surf, x, y, w, h = layer.shadow
        cr.save()
        cr.translate(x + dx, y)
        paint_scaled(cr, surf, w, h, opacity)
        cr.restore()
    for name, (opacity, dx, _c) in groups.items():
        layer = layers["groups"][name]
        cr.save()
        cr.translate(dx, 0)
        cr.set_source_surface(layer.surface, layer.rect[0], layer.rect[1])
        cr.paint_with_alpha(opacity)
        cr.restore()
    for name, (opacity, dx, _c) in groups.items():
        cr.push_group()
        draw_group_live(cr, name, state, layers, dx, press_t, draw_dpad)
        cr.pop_group_to_source()
        cr.paint_with_alpha(opacity)
    if conn is not None:
        cr.set_source_surface(conn.surface, conn.rect[0], conn.rect[1])
        cr.paint_with_alpha(conn_op)
    elif layers["connector"] is not None:
        cr.push_group()
        draw_gesture_connector_live(cr, layers, sw, groups["LPad"][1], groups["RPad"][1])
        cr.pop_group_to_source()
        cr.paint_with_alpha(min(groups["LPad"][0], groups["RPad"][0]))
    t2 = time.perf_counter()

    if (t2 - t0) * 1000 > 5.0:
        dbg(f"draw_hud_split: layers+{(t1 - t0) * 1000:.1f}ms "
            f"paint+{(t2 - t1) * 1000:.1f}ms")


def _draw_unreadable(cr, sw, sh, path):
    """No state from makima: the classic HUD's three lines, on a dark plate
    of their own — this overlay has no background, and bare white text is
    lost on a light page."""
    t = theme.current()
    lines = (("No state from makima", 16, True, 0.92), (f"Cannot read {path}", 12, False, 0.6),
             ("Is makima.service running?", 12, False, 0.6))
    w = max(_txt_size(cr, text, size, bold)[0] for text, size, bold, _a in lines) + 64
    h = 100
    x, y = (sw - w) / 2, (sh - h) / 2
    cr.set_source_rgba(0.04, 0.04, 0.06, 0.82)
    _rrect(cr, x, y, w, h, 18)
    cr.fill_preserve()
    cr.set_source_rgba(*t.ink, 0.18)
    cr.set_line_width(1.0)
    cr.stroke()
    for (text, size, bold, alpha), ly in zip(lines, (y + 30, y + 58, y + 78)):
        cr.set_source_rgba(*t.ink, alpha)
        _txt(cr, sw / 2, ly, text, size=size, bold=bold, ha="center", va="mid")


def _avail_mod_color(vm):
    """Outline colour for "could be held next to unlock something" — replaces
    the legend's old diamond marker, which lost its home once most buttons'
    legend rows disappeared entirely (declutter pass + L1/R1/paddles' own
    dot-and-line removal). Same three-way colour split the diamond always
    used (see callouts.py's own diamond-drawing comment) — amber for a real,
    non-virtual modifier; white for a virtual (hint-only) one whose hints are
    all base-config; teal for a virtual one with at least one app-specific
    hint. Collapsing these to one colour would say "real modifier" for
    buttons that are only ever a hint, e.g. the paddles' own virtual
    combos — not the same thing, and not what the diamond ever claimed.
    Deliberately *not* set for active_mod (currently held) — that already has
    its own distinct treatment (the white active-fill wash), so this is only
    the "available, not yet held" case."""
    if not vm:
        return None
    # Alpha kept close to the outline's own 0.5 (not the 0.9 the diamond
    # used) — the diamond was a small separate mark, where higher contrast
    # against its background made sense; this colours the button's own
    # outline, already drawn at the outline width, and 0.9 there reads as a bolder
    # stroke, not just a different hue, next to every default-coloured
    # outline sitting at 0.5 right beside it.
    t = theme.current()
    if vm.is_avail_virt_mod and vm.is_avail_app_mod:
        return (*t.layer, 0.6)
    if vm.is_avail_virt_mod:
        return (*t.ink, 0.6)
    if vm.is_avail_mod:
        return (*t.mod_rgb(vm.mod_keys), 0.6)
    return None


def _active_fill_color(vm):
    """Active-press fill colour — same priority order and hues as the
    external legend's own colour coding (callouts.py's _callouts: amber for
    a modifier-driven press — held modifier or a firing combo — teal for an
    app-layer override, white for a plain press with neither) instead of
    the flat white theme.active_fill always used before. Conflict (both at once)
    follows the legend's own call there too: teal wins, amber is secondary
    (shown as an underline in the legend; there's no equivalent secondary
    mark on a filled shape, so it's just teal here). Same alpha as
    theme.active_fill in every case — only the hue changes."""
    if not vm or not vm.is_active:
        return None
    amber = vm.active_mod or (vm.is_combo and not vm.is_hint)
    t = theme.current()
    if vm.layer_override:
        return (*t.layer, t.active_fill[3])
    if amber:
        return (*t.mod_rgb(vm.mod_keys), t.active_fill[3])
    return t.active_fill


def _action_text_color(vm):
    """Colour for a button's own adjacent action text (L1/L2/R1/R2's and
    the paddles'/pills' — see _draw_adjacent_bindings and
    _draw_scale_button_live) — same priority and hues as
    _active_fill_color/the external legend's text colour, but always
    returns a colour rather than None: this text is drawn whenever the
    button is *bound*, not only while it's actively pressed, so "not
    active" isn't "nothing to draw" here the way it is for the fill."""
    t = theme.current()
    if not vm:
        return (*t.text, t.emph(0.9))
    amber = vm.active_mod or (vm.is_combo and not vm.is_hint)
    if vm.layer_override:
        return (*t.layer, 1.0)
    if amber:
        return (*t.mod_rgb(vm.mod_keys), 1.0)
    # the bound-legend colour, as the callouts' (B-20: one brightness)
    return (*t.text, t.emph(0.9))


# Text that _K (viewmodel.py) produces for a plain BTN_LEFT/BTN_RIGHT
# binding — used to recognise that case wherever an adjacent-action text is
# drawn (_draw_adjacent_bindings, the paddles', the pills') so it can switch
# to the same mouse-click glyph the active-outputs strip itself uses,
# instead of the literal word. A combo ("Ctrl+LClick") won't match, so it
# still falls back to plain text — a glyph standing in for a whole combo
# string isn't the thing being asked for here.
_CLICK_ACTION_TEXT = {"LClick": "BTN_LEFT", "RClick": "BTN_RIGHT"}


def _place_action_text(cr, cx, cy, ha, text, color, note=None):
    """Draw one button's adjacent action text — or, for a plain LClick/
    RClick binding, the matching mouse-click glyph instead. A binding's
    note (B-18) goes underneath as a dimmed, smaller second line; the pair
    stays centred on cy so it still reads as beside the button."""
    if note:
        cy -= _NOTE_SHIFT
    which = _CLICK_ACTION_TEXT.get(text)
    if which:
        _draw_click_icon(cr, which, cx, cy, ha, color)
    else:
        cr.set_source_rgba(*color)
        _txt_icon(cr, cx, cy, text, size=_LABEL_SIZE, ha=ha, va="mid")
    if note:
        cr.set_source_rgba(*theme.current().ink, _NOTE_ALPHA)
        ind = _icon_indent(cr, text, _LABEL_SIZE) * (1 if ha == "left" else -1)
        _txt(cr, cx + ind, cy + 2 * _NOTE_SHIFT, note, size=_NOTE_SIZE, ha=ha, va="mid")


# B-18 note line: smaller and dimmer than the action, so it reads as a
# remark on how to use it rather than a second action.
_NOTE_SHIFT = 9
_NOTE_SIZE = _LABEL_SIZE - 3
_NOTE_ALPHA = 0.5


_PAD_DISABLED_ALPHA = 0.26   # dimmer than the outline's own 0.5 alpha —
                                                # a disabled pad's own border reads as such
                                                # on the shape itself, not just via its
                                                # (now-hidden) legend text


def _render_part_cluster(cr, name, ox, oy, scale, vms, active_press=frozenset(), pv=None,
                         element=None):
    """Draw every part belonging to this cluster, with an active-state fill
    wash under any part whose button is currently pressed. ox, oy, scale:
    the same per-cluster transform used everywhere else (dot positions,
    trackpad/stick overlays), so parts land exactly where their callout
    dots do.

    active_press: the set of _SCALE_ANIM_PARTS button keys currently mid
    press-animation (t > 0.001), i.e. actually needing a live, per-frame
    transform right now. Everything else in _SCALE_ANIM_PARTS draws here as
    normal and sits in the cached bitmap like any other part — only the
    handful of buttons actually mid-press get excluded, not all twelve of
    them unconditionally. That used to cost 6-9ms *every single frame*
    (measured live) redrawing all twelve from scratch — Pango label layout
    included — regardless of whether anything was actually being pressed;
    this way the live path only ever does real work while a press is
    actually in flight, which is rare compared to idle frames.

    element: draw only that element's shapes and labels (elements.py);
    None draws the whole cluster."""
    for part_name in _CLUSTER_PARTS[name]:
        if part_name == "dpad":
            continue
        if element is not None and part_name not in element.parts:
            # Only this element's own shape(s) — see elements.py.
            continue
        if part_name in _SCALE_ANIM_PART_NAMES and _SCALE_ANIM_BTN_BY_PART[part_name] in active_press:
            # Mid-press right now — drawn live every frame instead (see
            # _draw_scale_button_live), since its press animation (scale
            # toward centre) can't be baked into this cluster's cached
            # bitmap, which only rebuilds on a vms/pv/active_press change,
            # not every animation frame.
            continue
        if part_name in ("shoulder_l", "shoulder_r", "shoulder_l_split", "shoulder_r_split"):
            # Drawn entirely by _draw_shoulder_fills instead — fill and
            # border need to be one fill-then-stroke pass per half on the
            # same clipped region (see its docstring), not a border pass
            # here and a separate fill pass later; drawing either one here
            # would just recreate the ordering bug that caused.
            continue
        if part_name in _SCALE_ANIM_PART_NAMES:
            # Not currently mid-press (the active_press case already
            # `continue`d above) — reuse _draw_scale_button_live itself at
            # t=0.0 rather than duplicating its outline/fill/label/adjacent-
            # text logic here a second time. At t=0.0 it applies no
            # transform at all, so this renders byte-identical to the live
            # path's own at-rest frame — it just happens to land in the
            # cached bitmap instead of being redrawn every frame for no
            # reason.
            sa_btn_key = _SCALE_ANIM_BTN_BY_PART[part_name]
            _draw_scale_button_live(cr, sa_btn_key, part_name, ox, oy, scale, vms[sa_btn_key], 0.0)
            continue
        btn_key = _PART_BTN.get(part_name)
        vm = vms[btn_key] if btn_key else None
        fill_color = _active_fill_color(vm) or idle_fill()
        outline_color = _avail_mod_color(vm) or theme.current().outline
        if pv is not None and (
            (part_name == "trackpad_l" and pv.lpad_label == "Disabled") or
            (part_name == "trackpad_r" and pv.rpad_label == "Disabled")
        ):
            outline_color = (*theme.current().outline[:3], _PAD_DISABLED_ALPHA)
        pox, poy = ox, oy
        if part_name in _PART_OFFSET:
            dx, dy = _PART_OFFSET[part_name]
            pox, poy = ox + dx, oy + dy
        if part_name in _FRAGMENTED_FILL_PARTS:
            # Paddle fragments aren't zero-width boundary paths like every
            # other part here — they're pre-widened filled slivers in the
            # source SVG (measured: ~1.16 SVG units of baked-in width on
            # their own). Stroking them the normal way (draw_part) adds a
            # *second* width on top of that baked-in one, which is exactly
            # why paddle borders measured visibly thicker than e.g. the
            # trackpad's (2px vs 3px at identical scale, identical lw — the
            # trackpad outline has no baked-in width to begin with). A clean
            # rounded-rect from the same bbox+corner-radius already used for
            # the active-fill wash gives one width, matching everywhere else.
            x0, y0, x1, y1 = part_bbox(part_name)
            rx, ry = pox + x0 * scale, poy + y0 * scale
            rw, rh = (x1 - x0) * scale, (y1 - y0) * scale
            if fill_color:
                cr.set_source_rgba(*fill_color)
                _rrect(cr, rx, ry, rw, rh, _PADDLE_CORNER_R * scale)
                cr.fill()
            _rrect(cr, rx, ry, rw, rh, _PADDLE_CORNER_R * scale)
            stroke_outline(cr, outline_color)
        else:
            draw_part(cr, part_name, pox, poy, scale, color=outline_color,
                      fill_color=fill_color)

    kind = element.kind if element is not None else None
    if name in ("l_shoulder", "r_shoulder") and kind in (None, "upper", "lower"):
        _draw_shoulder_fills(cr, name, ox, oy, scale, vms,
                             only=element.buttons[0] if element is not None else None)

    _draw_in_shape_labels(cr, name, ox, oy, scale, vms,
                          stick=kind in (None, "stick"), pad=kind in (None, "pad"))
    _draw_adjacent_bindings(cr, name, ox, oy, scale, vms)


def _draw_in_shape_labels(cr, name, ox, oy, scale, vms, stick=True, pad=True):
    """LPad/RPad's own corner label, plus L3/R3's bound action — the only in-shape labels
    that aren't attached to a button in _SCALE_ANIM_PARTS (see that dict /
    _draw_scale_button_live, which draws every other in-shape label live,
    together with its button, so the two share one press transform instead
    of the label floating in place while the shape under it scales). L3/R3
    specifically used to be scale-animated the same way, via the stick's
    static outer bezel ring — wrong ring (it never moves on a real stick);
    the actual press feedback now lives in trackpads.py instead (the two
    *inner* rings, which are already drawn fresh every frame for analog
    deflection), and since B-07 the "L3"/"R3" text is drawn there too, on
    the moving cap — only the bound-action text beside it stays static here.
    Deliberately excluded here as everywhere before:
    the d-pad (its arrow shape already reads as up/down/left/right, a label
    would be redundant) and View, which wasn't part of the original
    in-shape-label request and stays legend-only."""
    if name in ("l_face", "r_face") and stick:
        # To the side of the ring, not below it (on request — "doesn't need
        # to be below at all"), and specifically not *inside* the ring:
        # that's where the live analog-deflection dot moves, so text
        # sitting there would get run over by it.
        #
        # The bound-action text stays on the *inward* side (toward the
        # centre column), on request.
        stick_part, stick_key = (("stick_l_fixed", "BTN_THUMBL") if name == "l_face"
                                  else ("stick_r_fixed", "BTN_THUMBR"))
        rx0, ry0, rx1, ry1 = part_bbox(stick_part)
        sdx, sdy = _PART_OFFSET.get(stick_part, (0, 0))
        cy = oy + sdy + (ry0 + ry1) / 2 * scale
        gap = 14
        inward_is_right = name == "l_face"   # l_face's centre column is to its right
        if inward_is_right:
            inward_x, inward_ha = ox + sdx + rx1 * scale + gap, "left"
        else:
            inward_x, inward_ha = ox + sdx + rx0 * scale - gap, "right"

        # The identity label itself ("L3"/"R3") is drawn live on the moving
        # cap now (draw_group_live → trackpads._draw_stick), so it follows
        # deflection and press; only the bound action stays here, static.
        vm = vms[stick_key]
        if vm.bound:
            _place_action_text(cr, inward_x, cy, inward_ha, vm.action, _action_text_color(vm), vm.note)

    if name in ("l_pad", "r_pad") and pad:
        pad_part = "trackpad_l" if name == "l_pad" else "trackpad_r"
        pad_label = "LPad" if name == "l_pad" else "RPad"
        px0, py0, px1, py1 = part_bbox(pad_part)
        margin = 9 * scale
        if name == "l_pad":
            cx, ha = ox + px0 * scale + margin, "left"
        else:
            cx, ha = ox + px1 * scale - margin, "right"
        cy = oy + py0 * scale + margin
        cr.set_source_rgba(*theme.current().ink, theme.current().emph(0.75))
        _txt(cr, cx, cy, pad_label, size=9, ha=ha, va="top")


def _draw_adjacent_bindings(cr, name, ox, oy, scale, vms):
    """Bound-action text for L1/L2/R1/R2 — drawn right next to the button,
    no dot, no connecting line, no centre-column row at all (see
    _ADJACENT_LABELED). Unbound buttons in this set draw nothing here; the
    shape's own identity label is already the whole story for them. The
    paddles used to get the same treatment here too, but now that they're
    scale-animated on press (_draw_scale_button_live), their adjacent text
    moved there with them, so it scales together with the button instead of
    sitting fixed in place while the shape under it moves."""

    def place(cx, cy, ha, text, vm):
        _place_action_text(cr, cx, cy, ha, text, _action_text_color(vm), vm.note)

    if name in ("l_shoulder", "r_shoulder"):
        inward = name == "l_shoulder"
        gap = 60
        btn_keys = ("BTN_TL", "BTN_TL2") if inward else ("BTN_TR", "BTN_TR2")
        for btn_key in btn_keys:
            vm = vms[btn_key]
            if not vm.bound:
                continue
            px, py = _BTN_POS_OVERRIDE[btn_key]
            cy = oy + py * scale
            if inward:
                place(ox + px * scale + gap, cy, "left", vm.action, vm)
            else:
                place(ox + px * scale - gap, cy, "right", vm.action, vm)


def shoulder_half_polys(name):
    """{button key: half-plane polygon in source-SVG space} for the two
    halves of a shoulder wedge (see _draw_shoulder_fills). Intersect with
    the wedge itself (clip_to_part) to get one half — L1 and L2 are
    separate elements sharing that one shape."""
    split_part = "shoulder_l_split" if name == "l_shoulder" else "shoulder_r_split"
    btn_upper = "BTN_TL" if name == "l_shoulder" else "BTN_TR"
    btn_lower = "BTN_TL2" if name == "l_shoulder" else "BTN_TR2"

    line = part_subpaths(split_part)[0]
    _, ax, ay = line[0]
    _, bx, by = line[1]

    dx, dy = ax - bx, ay - by
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length   # unit vector along the divider

    FAR = 2000.0   # SVG-space units — just needs to clear the wedge's own
                   # extent (viewBox is ~1060 wide), not match it exactly
    a_ext = (ax + ux * FAR, ay + uy * FAR)
    b_ext = (bx - ux * FAR, by - uy * FAR)

    nx, ny = -uy, ux   # perpendicular to the divider
    if ny > 0:         # make (nx, ny) point "up" (toward the top edge)
        nx, ny = -nx, -ny
    up   = [(x + nx * FAR, y + ny * FAR) for x, y in (a_ext, b_ext)]
    down = [(x - nx * FAR, y - ny * FAR) for x, y in (a_ext, b_ext)]

    polys = {
        btn_upper: [b_ext, a_ext, up[0], up[1]],
        btn_lower: [a_ext, b_ext, down[1], down[0]],
    }
    return polys


def _draw_shoulder_fills(cr, name, ox, oy, scale, vms, only=None):
    """L1/L2 split along the divider's real diagonal. Each half is (wedge
    outline) ∩ (half-plane of the divider line) — the wedge's real outline
    (rounded corners included) comes from clip_to_part() against the actual
    part, unmodified; the only thing this function invents is which side of
    the divider counts as "upper"/"lower".

    That half-plane is built by extending the divider line's own two
    endpoints far past the wedge in every direction (FAR), not by boxing it
    in with the part's own bbox corners. An earlier version used the bbox
    corners as the far boundary, which quietly under-covered the wedge: the
    real outline's rounded tip curves out further, in both x and y, than a
    straight line from the divider's endpoint to the bbox corner reaches —
    so that curved sliver fell outside the hand-built polygon and never got
    filled, even though it's inside the true wedge ∩ the correct half. A
    half-plane that reaches arbitrarily far can't under-cover like that: the
    only boundary doing any real cutting is clip_to_part's true silhouette,
    so whatever rounding exists there is included automatically.

    only: draw just this button's half (its divider share and label too)."""
    part = "shoulder_l" if name == "l_shoulder" else "shoulder_r"
    split_part = "shoulder_l_split" if name == "l_shoulder" else "shoulder_r_split"
    btn_upper = "BTN_TL" if name == "l_shoulder" else "BTN_TR"
    btn_lower = "BTN_TL2" if name == "l_shoulder" else "BTN_TR2"
    polys = shoulder_half_polys(name)
    if only is not None:
        # One element's half only (L1 or L2 on its own).
        polys = {only: polys[only]}

    # Fill then border, in one pass per half, both against the exact same
    # doubly-clipped region (true outline ∩ this half's half-plane) — not a
    # border pass drawn once up front and a fill pass layered on top of it
    # later (the previous shape of this code, and of _render_part_cluster's
    # old unconditional border stroke for "shoulder_l"/"shoulder_r"): that
    # ordering meant the active-fill wash was always painted *after* the
    # border already existed, so it visibly ate into the border's inward
    # half instead of staying inside it. Filling and tracing the same clip
    # region back to back, in that order, is what draw_part() itself does
    # for every other part — this just does it per half instead of for the
    # whole shape at once, since two different buttons share one shape here.
    half_colors = {}
    for btn_key, poly in polys.items():
        vm = vms[btn_key]
        color = _avail_mod_color(vm) or theme.current().outline
        half_colors[btn_key] = color

        def _clip_to_poly():
            cr.new_path()
            for i, (px, py) in enumerate(poly):
                sx, sy = ox + px * scale, oy + py * scale
                (cr.move_to if i == 0 else cr.line_to)(sx, sy)
            cr.close_path()
            cr.clip()

        # Fill: needs *both* clips (true shape ∩ half-plane) to stay inside
        # the real silhouette instead of the half-plane's own straight,
        # infinitely-extended edges.
        fill_color = _active_fill_color(vm) or idle_fill()
        if fill_color:
            cr.save()
            clip_to_part(cr, part, ox, oy, scale)
            _clip_to_poly()
            cr.set_source_rgba(*fill_color)
            cr.paint()
            cr.restore()

        # Border: half-plane clip *only* — picks which portion of the true
        # path to draw (upper vs lower), without also self-clipping against
        # that same path's own silhouette. Doing both (as a previous version
        # of this did) chops off the outward-facing half of the stroke,
        # since clip_to_part only allows painting *inside* the shape and a
        # centred stroke straddles its path evenly on both sides — measured
        # live: a perpendicular cross-section of this stroke peaked at ~92,
        # against ~120 for the divider line a few lines down, which gets no
        # such self-clip and keeps its full width. Half-plane-only clip
        # still correctly restricts the curve to this half (the cut only
        # matters right at the two points where it meets the real outline),
        # just without also trimming the stroke's own width there.
        cr.save()
        _clip_to_poly()
        draw_part(cr, part, ox, oy, scale, color=color)
        cr.restore()

    # The divider line is visually part of each half's own border too (it's
    # the one edge *not* covered by either half's clipped trace of the real
    # outline above, since it's its own separate part, not a piece of
    # "shoulder_l"/"shoulder_r"'s path) — coloured to match whichever half
    # isn't just the default, so it reads as belonging to that half's
    # highlight instead of looking like a leftover plain line across it.
    outline = theme.current().outline
    divider_color = next((c for c in half_colors.values() if c != outline), outline)
    if only is None:
        draw_part(cr, split_part, ox, oy, scale, color=divider_color)
    else:
        # Each half draws its own side of the divider's stroke, so the two
        # elements together make exactly the one full-width line.
        cr.save()
        cr.new_path()
        for n, (px, py) in enumerate(polys[only]):
            (cr.move_to if n == 0 else cr.line_to)(ox + px * scale, oy + py * scale)
        cr.close_path()
        cr.clip()
        draw_part(cr, split_part, ox, oy, scale, color=half_colors[only])
        cr.restore()

    # Labels — unlike the fill, always drawn (not gated on is_active).
    # Positioned at the same point as the button's own callout dot
    # (_BTN_POS_OVERRIDE, the top-SVG-space point already used for L1/L2/
    # R1/R2's legend line origin) rather than any computed centroid — on
    # request, so the in-shape label and the point the legend line starts
    # from read as the same spot instead of two different ones nearby.
    for btn_key in polys:
        px, py = _BTN_POS_OVERRIDE[btn_key]
        label_cx = ox + px * scale
        label_cy = oy + py * scale
        cr.set_source_rgba(*theme.current().ink, theme.current().emph(0.9))
        _txt(cr, label_cx, label_cy, _BTNS[btn_key][3], size=_LABEL_SIZE, ha="center", va="mid")


def _draw_dpad_fills(cr, ox, oy, scale, vms):
    """The d-pad is one continuous outline (no per-direction shape to fill
    individually), so a direction's active fill is drawn as its own shape —
    a rectangle matching the arm's width for most of its length, tapering to
    a point at the d-pad's centre for the last stretch.

    The taper has to stop at exactly half the arm's own width out from
    centre, not some arbitrary fraction of the arm's length: picture the
    half×half square sitting at the hub, with both diagonals drawn — that
    cuts it into 4 triangles, each with one edge of the square as its base
    and the centre point as its apex. That's exactly the two taper points
    used below. Two adjacent directions' triangles then share only that
    diagonal edge, so pressing e.g. UP+LEFT at once tiles cleanly with no
    overlap and no gap at the centre, instead of both wedges independently
    reaching all the way to the same centre point and overlapping near it."""
    x0, y0, x1, y1 = part_bbox("dpad")
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = 16.0
    ty0, ty1 = cy - half, cy + half
    tx0, tx1 = cx - half, cx + half
    slices = {
        "BTN_DPAD_UP":    [(cx - half, y0), (cx + half, y0), (cx + half, ty0), (cx, cy), (cx - half, ty0)],
        "BTN_DPAD_DOWN":  [(cx - half, y1), (cx + half, y1), (cx + half, ty1), (cx, cy), (cx - half, ty1)],
        "BTN_DPAD_LEFT":  [(x0, cy - half), (x0, cy + half), (tx0, cy + half), (cx, cy), (tx0, cy - half)],
        "BTN_DPAD_RIGHT": [(x1, cy - half), (x1, cy + half), (tx1, cy + half), (cx, cy), (tx1, cy - half)],
    }
    for btn_key, pts in slices.items():
        fill_color = _active_fill_color(vms[btn_key])
        if not fill_color:
            continue
        cr.save()
        clip_to_part(cr, "dpad", ox, oy, scale)
        cr.set_source_rgba(*fill_color)
        cr.new_path()
        for i, (px, py) in enumerate(pts):
            sx, sy = ox + px * scale, oy + py * scale
            (cr.move_to if i == 0 else cr.line_to)(sx, sy)
        cr.close_path()
        cr.fill()
        cr.restore()


def get_dpad_geometry(sw, sh, open_t):
    """(ox, oy, scale, cx, cy) for the d-pad at the given screen size and
    open_t — ox/oy/scale is the l_face cluster's own transform (what
    draw_dpad_live expects), cx/cy is the d-pad's own screen-space centre
    point (what win.py needs as the pivot for a real Gtk.Snapshot
    perspective/rotate_3d transform, which only it has access to — see
    win.py:_draw_dpad_3d). Pure geometry, no Pango/cached-bitmap work, so
    it's cheap enough to call every frame independent of the heavy
    per-side surface cache."""
    clusters, _anchor_x, _center = compute_layout(sw, sh)
    x, y, w, h, scale = clusters["l_face"]
    svg_name, (x0c, y0c, x1c, y1c) = CLUSTERS["l_face"]
    ox = x - x0c * scale + _side_slide_offset("left", sw, open_t)
    oy = y - y0c * scale
    ddx, ddy = _PART_OFFSET.get("dpad", (0, 0))
    pox, poy = ox + ddx, oy + ddy
    bx0, by0, bx1, by1 = part_bbox("dpad")
    cx = pox + (bx0 + bx1) / 2 * scale
    cy = poy + (by0 + by1) / 2 * scale
    return ox, oy, scale, cx, cy


# How far the pressed edge compresses toward its opposite (hinged) edge, as
# a fraction of the d-pad's own size, at full press (press_t == 1.0). Unused
# when win.py's real 3D perspective path is active (draw_dpad=False, see
# draw_hud_split) — kept as the non-split-widget fallback (render_sample.py's
# fixtures, or draw_dpad=True callers) since a 3D Gtk.Snapshot transform
# isn't available outside an actual GTK window.
_DPAD_TILT_MAX = 0.12


def draw_dpad_live(cr, ox, oy, scale, vms, press_t):
    """The d-pad outline + its active-fill wash, redrawn fresh every frame
    (not baked into the cluster's cached bitmap — see _render_part_cluster)
    so a press can animate smoothly instead of snapping instantly between
    "flat" and "lit".

    The "tilt" is a 2D stand-in for the real thing: Cairo has no actual
    perspective transform, so a true 3D rock isn't available cheaply. What
    reads convincingly instead is a hinge — the edge *opposite* the pressed
    direction stays fixed, and the whole d-pad compresses toward it, as if
    pivoting away from the viewer on that far edge. Compare to a rotation
    around the centre: a plain spin doesn't mean anything for a symmetric
    cross (all four arms are equivalent under it), but a hinge pointing
    away from the pressed arm reads immediately as "that side got pushed
    in". Multiple directions (a diagonal) just compose their hinges in
    sequence, each applied to whatever the previous one already produced.
    """
    dx_off, dy_off = _PART_OFFSET.get("dpad", (0, 0))
    pox, poy = ox + dx_off, oy + dy_off
    x0, y0, x1, y1 = part_bbox("dpad")
    sx0, sy0 = pox + x0 * scale, poy + y0 * scale
    sx1, sy1 = pox + x1 * scale, poy + y1 * scale

    pt = press_t or {}
    # Pick the *dominant* press per axis (max t), not every direction that
    # happens to have any nonzero t, and apply each axis's hinge exactly
    # once. The previous version applied one translate/scale/translate per
    # direction unconditionally, and — critically — accumulated them: a
    # second transform's hinge coordinate (computed for the original,
    # untransformed space) gets applied inside the space the first
    # transform already warped, so two opposing directions both reporting
    # some t at once (noisy analog data can genuinely do this — confirmed
    # live: BTN_DPAD_UP and BTN_DPAD_LEFT toggling together in rapid
    # succession) compound into a wildly wrong transform instead of two
    # sensible ones, up to scaling/translating the whole d-pad out of its
    # own visible bounds. Resolving to one transform per axis, computed
    # once against the real hinge points, can't do that.
    up, down = pt.get("BTN_DPAD_UP", 0.0), pt.get("BTN_DPAD_DOWN", 0.0)
    left, right = pt.get("BTN_DPAD_LEFT", 0.0), pt.get("BTN_DPAD_RIGHT", 0.0)
    ty, hinge_y = (up, sy1) if up >= down else (down, sy0)
    tx, hinge_x = (left, sx1) if left >= right else (right, sx0)

    cr.save()
    if ty > 0.001:
        sy = 1.0 - _DPAD_TILT_MAX * ty
        cr.translate(0, hinge_y)
        cr.scale(1.0, sy)
        cr.translate(0, -hinge_y)
    if tx > 0.001:
        sx = 1.0 - _DPAD_TILT_MAX * tx
        cr.translate(hinge_x, 0)
        cr.scale(sx, 1.0)
        cr.translate(-hinge_x, 0)

    draw_part(cr, "dpad", pox, poy, scale, fill_color=idle_fill())
    _draw_dpad_fills(cr, pox, poy, scale, vms)
    cr.restore()


def _draw_scale_button_live(cr, btn_key, part_name, ox, oy, scale, vm, t):
    """One standalone-shape button (outline + active-fill + its own in-shape
    label, and for paddles, their adjacent bound-action text) redrawn live
    every frame with a "press = scale down toward centre" transform — the
    plain press feedback for every button in _SCALE_ANIM_PARTS. Everything
    this button used to draw into the cluster's cached bitmap (see
    _render_part_cluster/_draw_in_shape_labels/_draw_adjacent_bindings, all
    of which now skip these buttons) moved here, so the whole visual unit —
    shape, label, adjacent text — scales as one piece instead of the shape
    moving while its label stays fixed."""
    x0, y0, x1, y1 = part_bbox(part_name)
    pdx, pdy = _PART_OFFSET.get(part_name, (0, 0))
    pox, poy = ox + pdx, oy + pdy
    cx = pox + (x0 + x1) / 2 * scale
    cy = poy + (y0 + y1) / 2 * scale

    cr.save()
    if t > 0.001:
        s = 1.0 - _SCALE_ANIM_MAX * t
        cr.translate(cx, cy)
        cr.scale(s, s)
        cr.translate(-cx, -cy)

    fill_color = _active_fill_color(vm) or idle_fill()
    outline_color = _avail_mod_color(vm) or theme.current().outline

    if part_name in _FRAGMENTED_FILL_PARTS:
        rx, ry = pox + x0 * scale, poy + y0 * scale
        rw, rh = (x1 - x0) * scale, (y1 - y0) * scale
        if fill_color:
            cr.set_source_rgba(*fill_color)
            _rrect(cr, rx, ry, rw, rh, _PADDLE_CORNER_R * scale)
            cr.fill()
        _rrect(cr, rx, ry, rw, rh, _PADDLE_CORNER_R * scale)
        stroke_outline(cr, outline_color)
    else:
        draw_part(cr, part_name, pox, poy, scale, color=outline_color,
                  fill_color=fill_color)

    if part_name in ("btn_y", "btn_x", "btn_b", "btn_a"):
        cr.set_source_rgba(*theme.current().ink, theme.current().emph(0.9))
        _txt_smooth(cr, cx, cy, _BTNS[btn_key][3], size=_LABEL_SIZE)
    elif part_name in ("stick_l_fixed", "stick_r_fixed"):
        # Centred *under* the stick's own fixed outer ring, not on it — the
        # ring has no interior face to put text on like a flat button.
        cr.set_source_rgba(*theme.current().ink, 0.9)
        _txt(cr, cx, poy + y1 * scale + 10, _BTNS[btn_key][3], size=_LABEL_SIZE, ha="center", va="top")
    elif part_name.startswith("paddle_"):
        cr.set_source_rgba(*_action_text_color(vm))
        _txt_smooth(cr, cx, cy, _BTNS[btn_key][3], size=_PADDLE_LABEL_SIZE, bold=True)
        if vm.bound:
            inward = part_name.startswith("paddle_l")
            gap = 20
            if inward:
                _place_action_text(cr, pox + x1 * scale + gap, cy, "left", vm.action, _action_text_color(vm), vm.note)
            else:
                _place_action_text(cr, pox + x0 * scale - gap, cy, "right", vm.action, _action_text_color(vm), vm.note)
    elif part_name == "pill_mode":
        cr.set_source_rgba(*theme.current().ink, theme.current().emph(0.9))
        _txt_smooth(cr, cx, cy, "STEAM", size=8.0)
    elif part_name == "pill_base":
        cr.set_source_rgba(*theme.current().ink, 0.9)
        _txt_smooth(cr, cx, cy, "···", size=13.0, bold=True)
    elif part_name == "pill_start":
        # Drawn as actual bars, not the "☰" glyph — that pill is far
        # thinner than Steam/QAM's (13 SVG units tall vs. ~22), and the
        # glyph's own font metrics don't shrink to fit inside it cleanly at
        # any readable size. Geometry sized straight off the pill's own
        # bbox always fits exactly, regardless of font quirks.
        w, h = (x1 - x0) * scale, (y1 - y0) * scale
        half_w, gap, lw = w * 0.17, h * 0.26, max(1.0, h * 0.11)
        cr.set_source_rgba(*theme.current().ink, 0.9)
        cr.set_line_width(lw)
        cr.set_line_cap(cairo.LineCap.ROUND)
        for i in (-1, 0, 1):
            y = cy + i * gap
            cr.move_to(cx - half_w, y)
            cr.line_to(cx + half_w, y)
            cr.stroke()
    # pill_view (BTN_SELECT/View) draws no in-shape label of its own, same
    # as before this moved live — it was never part of the in-shape-label
    # request, only pulled into _SCALE_ANIM_PARTS for its own press-scale
    # feedback. It still gets the adjacent bound-action text below, though.

    # Adjacent bound-action text — same idea as the paddles' own (just
    # above): drawn right beside the pill, toward the centre column, only
    # when there's a real binding to show. pill_view/pill_mode sit on the
    # left (toward centre = pill's own right edge); pill_start/pill_base
    # sit on the right (toward centre = pill's own left edge).
    if part_name in ("pill_view", "pill_mode", "pill_base", "pill_start") and vm.bound:
        inward = part_name in ("pill_view", "pill_mode")
        gap = 18
        if inward:
            _place_action_text(cr, pox + x1 * scale + gap, cy, "left", vm.action, _action_text_color(vm), vm.note)
        else:
            _place_action_text(cr, pox + x0 * scale - gap, cy, "right", vm.action, _action_text_color(vm), vm.note)

    cr.restore()


# Mouse glyphs — the real Breeze symbolic icons (see icons.py), not
# hand-drawn: no reason to redraw a mouse by hand when the system already
# ships one, including the left/right-highlighted variants a hand-drawn
# glyph can't cheaply tell apart from a flat recolour.
_MOUSE_SIZE = 16     # idle (MT-Trackpad's legend glyph), doubled at its call site
_CLICK_SIZE = 30     # LClick/RClick beside L1/L2/R1/R2 etc. (_place_action_text) — picked
                     # from a side-by-side render, the largest of the candidates shown

_MOUSE_ICON_NAME = "input-mouse-symbolic"
_CLICK_ICON_NAME = {"BTN_LEFT": "input-mouse-click-left-symbolic",
                     "BTN_RIGHT": "input-mouse-click-right-symbolic"}


def _icon_cx(x, ha, size):
    """Shared ha convention for every glyph helper below, matching _txt's
    own: 'left' -> x is the glyph's left edge, 'right' -> its right edge,
    'center' -> x is already the glyph's own centre."""
    if ha == "left":
        return x + size / 2
    if ha == "right":
        return x - size / 2
    return x


def _draw_mouse_icon(cr, x, y, ha, color, size=_MOUSE_SIZE):
    """Idle mouse glyph. x, y: anchor point, vertically centred on y.
    `size` is the icon's canvas; like a legend's text it gets a shadow
    plate (helpers._breeze_icon)."""
    _breeze_icon(cr, _MOUSE_ICON_NAME, _icon_cx(x, ha, size), y, size / _THEMED_PAD, color)


def _draw_click_icon(cr, which, x, y, ha, color, size=_CLICK_SIZE):
    """which: 'BTN_LEFT' or 'BTN_RIGHT'. Same placement convention as
    _draw_mouse_icon. Falls back to the idle mouse glyph if the themed
    left/right-click variant isn't available (e.g. outside Breeze)."""
    cx = _icon_cx(x, ha, size)
    name = _CLICK_ICON_NAME.get(which, _MOUSE_ICON_NAME)
    if not _breeze_icon(cr, name, cx, y, size / _THEMED_PAD, color):
        _breeze_icon(cr, _MOUSE_ICON_NAME, cx, y, size / _THEMED_PAD, color)


# Pad legend labels with nothing useful to say as text — the shape itself
# already carries the signal (Disabled's dimmed border, see
# _PAD_DISABLED_COLOR) or gets a glyph instead (see _ICON_PAD_LEGEND below).
_HIDDEN_PAD_LEGEND = {"Disabled"}
# Pad legend labels shown as a small mouse glyph at the legend's own
# position instead of the word — on request, the text "Mt Trackpad" reads
# as noise once you know what the pad does; the glyph says it at a glance.
_ICON_PAD_LEGEND = {"Mt Trackpad"}


def _draw_cluster_callouts(cr, side, name, tx, vms, pv, ax, shown=None, pad_row=True):
    """Legend rows for one cluster. shown narrows them to a set of button
    keys (None = all); pad_row decides whether the pad's mode row shows.
    Rows left out are still laid out (hidden=True), so the ones drawn sit
    exactly where the full HUD puts them — vms must be the unmasked ones
    for the same reason."""
    ox, oy, scale = tx
    entries = []
    pad_icon = None   # (dot_x, dot_y, active) for an _ICON_PAD_LEGEND mode, set below
    for btn_key, (sx, sy, btn_side, short, view) in _BTNS.items():
        if _cluster_of(btn_key, name) is None:
            continue
        vm = vms[btn_key]
        if not vm.bound and not _SHOW_ALL and not vm.is_active:
            continue
        if btn_key in _ADJACENT_LABELED:
            continue
        has_inshape = btn_key in _INSHAPE_LABELED
        # is_avail_mod/app/virt deliberately excluded from this check for
        # has_inshape buttons: that signal now lives on the shape itself
        # (see _avail_mod_color — the amber outline replaces the legend's
        # old diamond marker), so it no longer justifies keeping an
        # otherwise-empty row alive on its own.
        if has_inshape and not (vm.bound or vm.is_hint or
                                 vm.sub_label or vm.layer_override or vm.is_combo):
            # Nothing here the in-shape label didn't already say — an
            # unbound button with no hint/combo/pending-modifier content
            # is just "X: —", and the shape already drew the "X".
            continue
        if btn_key in _BTN_POS_OVERRIDE:
            psx, psy = _BTN_POS_OVERRIDE[btn_key]
            dot_x, dot_y = ox + psx * scale, oy + psy * scale
        else:
            odx, ody = _BTN_OFFSET.get(btn_key, (0, 0))
            # ABXY: dot sits at the button's own left edge instead of its
            # centre — on request, so the callout line starts at the
            # circle's rim rather than appearing to float inside it.
            bx = (sx - _ABXY_RADIUS) if btn_key in _ABXY_BTNS else sx
            dot_x = ox + bx * scale + odx
            dot_y = oy + sy * scale + ody
        entries.append(_Callout(
            sort_y=dot_y, dot_x=dot_x, dot_y=dot_y, name=short, action=vm.action,
            layer_override=vm.layer_override, bound=vm.bound, active=vm.is_active,
            active_mod=vm.active_mod, is_combo=vm.is_combo,
            # The diamond is the legend's way of saying "available
            # modifier" — for has_inshape buttons that's now the amber
            # outline instead (_avail_mod_color), so the diamond would
            # just be saying the same thing twice. Suppressed here only;
            # buttons with no in-shape twin (d-pad, View) still show it.
            is_avail_mod=False if has_inshape else vm.is_avail_mod,
            is_avail_app_mod=False if has_inshape else vm.is_avail_app_mod,
            is_avail_virt_mod=False if has_inshape else vm.is_avail_virt_mod,
            sub_label=vm.sub_label, sub_active=vm.sub_active, note=vm.note,
            is_hint=vm.is_hint, mod_rgb=theme.current().mod_rgb(vm.mod_keys),
            # QAM's own in-shape label is three small dots — about the
            # same size as this marker dot, so at BTN_BASE's position
            # (dead centre of the pill, same spot the label sits) the
            # two visually merge into one blob instead of reading as
            # either. Every other in-shape label is a letter/word, large
            # and solid enough that the marker dot sitting on top of it
            # doesn't cause the same confusion, so this is QAM-specific.
            show_dot=(btn_key != "BTN_BASE"),
            # Every split-renderer legend row drops its "Name:" prefix,
            # not just the in-shape-labeled ones — the callout line
            # already runs straight to the exact button it's labelling
            # (d-pad arrows and View included), so the name was never
            # doing identification work the line doesn't already do.
            show_name=False,
            # ABXY's dot sits right on the circle's own edge now (see
            # _ABXY_RADIUS) — growing it on press reads as the dot
            # itself reacting rather than the button, on top of the
            # button's own fill wash already doing that job.
            grow_on_active=(btn_key not in _ABXY_BTNS),
            hidden=shown is not None and btn_key not in shown,
        ))

    if name in ("l_pad", "r_pad"):
        pad_key = "l" if name == "l_pad" else "r"
        bounds = _LPAD if pad_key == "l" else _RPAD
        # Inner vertical edge at mid-height — left pad's right edge,
        # right pad's left edge — not the bottom edge (previous version):
        # both pads sit toward the screen edge, so their *inner* edge is
        # the one actually facing the centre column the legend text sits
        # in, which reads more directly than anchoring off the bottom.
        inner_x = bounds["x"] + bounds["w"] if pad_key == "l" else bounds["x"]
        dot_x = ox + inner_x * scale
        dot_y = oy + (bounds["y"] + bounds["h"] / 2) * scale
        label = pv.lpad_label if pad_key == "l" else pv.rpad_label
        active = pv.lpad_active if pad_key == "l" else pv.rpad_active
        # "—" means no real mode to report — same "nothing beyond the
        # name" case as an unbound button, and LPad/RPad's own corner
        # label already says which pad this is. _HIDDEN_PAD_LEGEND modes
        # (Disabled) have nothing worth a row either — the shape itself
        # already shows it (see _PAD_DISABLED_COLOR). _ICON_PAD_LEGEND
        # modes (Mt Trackpad) still get a row, just drawn as a glyph
        # after _callouts() below instead of as a normal text _Callout.
        if pv.gesture:
            # Both pads touching at once is one shared event, not two —
            # drawn as a single connector across the whole centre
            # column instead (see _draw_gesture_connector, called from
            # draw_gesture_connector_live once both pads' positions are known),
            # so neither side gets its own separate row here.
            pass
        elif label in _ICON_PAD_LEGEND:
            if pad_row:
                pad_icon = (dot_x, dot_y, active)
        elif label != "—" and label not in _HIDDEN_PAD_LEGEND:
            entries.append(_Callout(
                sort_y=dot_y, dot_x=dot_x, dot_y=dot_y,
                name="LPad" if pad_key == "l" else "RPad", action=label,
                bound=True, active=active, active_mod=pv.gesture, show_dot=False,
                show_name=False, hidden=not pad_row,
            ))

    entries.sort(key=lambda e: e.sort_y)
    # _callouts()'s `side` argument means "which side does the text sit
    # on relative to the anchor", not "which side of the screen is this".
    # In the classic renderer those are the same thing (controller
    # centred, text radiates outward to screen-left/right). Here the
    # clusters are pinned to the screen edges and text radiates inward
    # instead — opposite direction — so the flag has to be inverted or
    # the text ends up back-to-front, overlapping the cluster it
    # labels instead of extending into the centre column.
    text_side = "right" if side == "left" else "left"
    # Only l_face/r_face pack several close-together entries (d-pad arrows,
    # View/Start, the stick) that actually need the auto-stacked spacing
    # to avoid overlapping each other. Every other cluster has at most two
    # entries with plenty of natural vertical separation, so the stacking
    # math was only ever adding an unnecessary kink there.
    straight = name not in ("l_face", "r_face")
    # l_face/r_face's own four-item legend (d-pad arrows on the left,
    # ABXY on the right) — pushed *down* now (+18, having gone from -8
    # to 0 to this, per repeated feedback that it kept reading as too
    # high), and spaced tighter still (22, down from 29). anchor_row=38
    # keeps computing the block's own anchor as if row were still 38 —
    # this is about keeping the *compression* (row changes) from moving
    # the top row on its own; y_nudge on top of that is the actual
    # "move the whole block" control.
    is_four = name in ("l_face", "r_face")
    y_nudge = 32 if is_four else 0
    row = 22 if is_four else 26
    anchor_row = 38 if is_four else None
    _callouts(cr, entries, text_side, ax, size=13, row=row, straight=straight,
              y_nudge=y_nudge, anchor_row=anchor_row, icons=True)

    if pad_icon is not None:
        # No legend row at all here on request — no dot, no line out to
        # the centre column, just the glyph itself sitting right beside
        # the pad's own inner edge (same "inward" direction text_side
        # already encodes), twice the active-outputs strip's own icon
        # size since it's standing on its own instead of inline with text.
        bx, by, active = pad_icon
        gap = 10
        if text_side == "right":
            icon_x, icon_ha = bx + gap, "left"
        else:
            icon_x, icon_ha = bx - gap, "right"
        _draw_mouse_icon(cr, icon_x, by, icon_ha,
                          (*theme.current().ink, 1.0 if active else 0.6),
                          size=_MOUSE_SIZE * 2)


def _cluster_of(btn_key, cluster_name):
    from clusters import CLUSTER_BUTTONS
    return cluster_name if btn_key in CLUSTER_BUTTONS.get(cluster_name, ()) else None


def _draw_center(cr, state, center, open_t, crumbs=None):
    """crumbs: None for the whole column, else the breadcrumb row alone
    with only these config layers (see reveal.crumbs)."""
    x0, y0, x1, y1 = center
    cw = x1 - x0
    alpha = open_t

    ctx = state.get("context") or {}
    paused = ctx.get("paused", False)
    t = theme.current()

    cx = (x0 + x1) / 2
    bx, by, badge_w, badge_h = center_badge_rect(center)
    if crumbs is not None:
        _draw_crumbs(cr, state, cx, by + badge_h + 26, alpha, crumbs)
        return

    # Title
    cr.set_source_rgba(*t.ink, 1.0 * alpha)
    _txt(cr, cx, y0 + 28, "Deckery HUD", size=15, bold=True, ha="center", va="mid")

    # Pause/Resume badge
    label = "⏸  Controls Paused" if paused else "⏵  Controls Active"
    *_rect, radius, rgb = center_button(state, center, "badge")
    def badge_label():
        cr.set_source_rgba(*rgb, 0.9 * alpha)
        _txt(cr, cx, by + badge_h / 2, label, size=11, ha="center", va="mid")
    _filled_button(cr, bx, by, badge_w, badge_h, radius, (*rgb, 0.14 * alpha), badge_label)

    _draw_crumbs(cr, state, cx, by + badge_h + 26, alpha)

    # Close affordance
    crx, cry, crw, crh, cr_r, _rgb = center_button(state, center, "close")
    ccx, ccy = crx + crw / 2, cry + crh / 2

    def cross():
        cr.set_source_rgba(*t.ink, 0.7 * alpha)
        cr.set_line_width(1.5)
        for dx, dy in ((-4, -4), (4, 4)), ((-4, 4), (4, -4)):
            cr.move_to(ccx + dx[0], ccy + dx[1])
            cr.line_to(ccx + dy[0], ccy + dy[1])
        cr.stroke()
    _filled_button(cr, crx, cry, crw, crh, cr_r, (*t.ink, 0.18 * alpha), cross)

    # Switch to the classic design — mirrors the close button on the left.
    # Start the theme mode (B-20) — beside the close button.
    for name, text in (("classic", "Classic"), ("theme", "Theme")):
        kx, ky, kw, kh, kr, _rgb = center_button(state, center, name)
        def pill_label():
            cr.set_source_rgba(*t.ink, 0.7 * alpha)
            _txt(cr, kx + kw / 2, ky + kh / 2, text, size=10, ha="center", va="mid")
        _filled_button(cr, kx, ky, kw, kh, kr, (*t.ink, 0.12 * alpha), pill_label)


CENTER_BUTTONS = ("badge", "close", "classic", "theme")


def center_button(state, center, name):
    """(x, y, w, h, corner radius, rgb) of one of the centre's clickable
    buttons (CENTER_BUTTONS) — for drawing it and its hover alike."""
    t = theme.current()
    if name == "badge":
        paused = (state.get("context") or {}).get("paused", False)
        return (*center_badge_rect(center), 7, t.status_paused if paused else t.status_active)
    x, y, w, h = {"close": center_close_rect, "classic": center_classic_rect,
                  "theme": center_theme_rect}[name](center)
    return x, y, w, h, h / 2, t.ink


def draw_center_hover(cr, state, center, name, k):
    """A centre button's hover (B-04), drawn live over the cached column
    and faded in by k: its fill made stronger and a thin outline, both in
    the button's own colour — the classic badge's hover, kept to the
    button's own shape so it still reads as one piece."""
    x, y, w, h, r, rgb = center_button(state, center, name)
    cr.set_source_rgba(*rgb, 0.16 * k)
    _rrect(cr, x, y, w, h, r)
    cr.fill()
    cr.set_source_rgba(*rgb, 0.6 * k)
    cr.set_line_width(1.0)
    _rrect(cr, x + 0.5, y + 0.5, w - 1, h - 1, max(0.0, r - 0.5))
    cr.stroke()


def _draw_crumbs(cr, state, cx, y, alpha, names=None):
    """The breadcrumb row: the config stack (base, then app layers in their
    colour) and the held modifiers' pills in theirs. names: only these
    config layers (None: all). The base is left out unless the theme shows
    it (crumbs.base)."""
    ctx = state.get("context") or {}
    full = ctx.get("config_stack") or ["—"]
    held = ctx.get("held_modifiers", [])
    mods = [_btn_short(m) for m in held]
    t = theme.current()
    base_style = ((*t.ink, 0.06 * alpha), (*t.ink, 0.80 * alpha))
    app_style = ((*t.layer, alpha), (0, 0, 0, alpha))
    shown = [(n, base_style if i == 0 else app_style) for i, n in enumerate(full)
             if (names is None or n in names) and (i > 0 or t.crumbs_base)]
    stack = [n for n, _s in shown]
    labels = stack + mods
    if not labels:
        return
    styles = [st for _n, st in shown] + [((*t.mod_rgb((m,)), alpha), (0, 0, 0, alpha))
                                          for m in held]
    n_gaps = max(0, len(labels) - 1)
    seps = ["›" if i < len(stack) else "" for i in range(n_gaps)]
    _pill_row(cr, cx, y, labels, sep=seps, size=10,
              sep_rgba=(*t.ink, 0.55 * alpha), ha="center", styles=styles)


def _luma(rgb):
    r, g, b = rgb[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def theme_panel(cr, sw, sh, label, index, count):
    """The theme mode's panel (B-20): which theme is previewed, where it is
    in the list, and how to leave. Drawn in the previewed theme itself, as
    one of its plates: its shadow colour under its text — a light card in
    Paper, whose text is dark. Returns its rect, for the caller to clip a
    live layer to."""
    t = theme.current()
    style = shadow_style()
    bg = tuple(style.shadow_rgb)
    if abs(_luma(bg) - _luma(t.text)) < 0.45:
        # No plate colour of its own that the text stands out on.
        bg = (0.04, 0.04, 0.06) if _luma(t.text) > 0.5 else (0.98, 0.98, 0.99)
    name = f"‹   {label}   ›"
    # Browsing applies at once; B is the way back.
    hint = "‹ ›  switch   ·   A done   ·   B undo"
    tw, _th = _txt_size(cr, name, 18, bold=True)
    hw, _hh = _txt_size(cr, hint, 10)
    x, y, w, h = theme_panel_rect(sw, sh, max(300, tw + 80, hw + 48))
    cr.set_source_rgba(*bg, 0.9)
    _rrect(cr, x, y, w, h, 18)
    cr.fill_preserve()
    if style.plate_border[3] > 0:
        cr.set_source_rgba(*style.plate_border)
        cr.set_line_width(max(1.0, style.plate_border_width))
    else:
        cr.set_source_rgba(*t.text, 0.18)
        cr.set_line_width(1.0)
    cr.stroke()
    cx = x + w / 2
    cr.set_source_rgba(*t.text, 0.55)
    _txt(cr, cx, y + 18, "THEME", size=9, bold=True, ha="center", va="mid")
    cr.set_source_rgba(*t.text, 1.0)
    _txt(cr, cx, y + 46, name, size=18, bold=True, ha="center", va="mid")
    gap = 14
    for i in range(count):
        cr.set_source_rgba(*t.text, 1.0 if i == index else 0.3)
        cr.arc(cx + (i - (count - 1) / 2) * gap, y + 72, 3.5 if i == index else 2.5, 0, math.tau)
        cr.fill()
    cr.set_source_rgba(*t.text, 0.6)
    _txt(cr, cx, y + 93, hint, size=10, ha="center", va="mid")
    return x, y, w, h
