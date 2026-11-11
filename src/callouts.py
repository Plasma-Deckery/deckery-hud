"""
callouts.py — Button registry and callout rendering.
Owns _BTNS, _SORT_Y, _SHOW_ALL, and all callout drawing logic.
"""

import math
from dataclasses import dataclass

from layout import _FX, _FY, _FS, _BX, _BY, _BS, _AX_L, _AX_R
from helpers import _K, _fmt, _txt, _txt_size, C_MOD, C_LAYER, C_GAME
from viewmodel import classify_all, pad_legend_vm


@dataclass
class _Callout:
    """One annotated row. Everything past `action` has a default, so the
    trackpad legends can be built from the handful of fields they actually
    carry."""
    sort_y: float
    dot_x: float
    dot_y: float
    name: str
    action: str
    layer_override: bool = False
    bound: bool = False
    active: bool = False
    active_mod: bool = False
    is_combo: bool = False
    is_avail_mod: bool = False
    show_dot: bool = True
    sub_label: str = None
    sub_active: bool = False
    is_avail_app_mod: bool = False
    is_hint: bool = False
    is_avail_virt_mod: bool = False
    show_name: bool = True
    grow_on_active: bool = True
    note: str = None       # B-18: dimmed second line, how the action is used ("halten")
    hidden: bool = False   # laid out like any row, but not drawn — keeps the
                           # rows that are drawn exactly where they'd be with it

# ── Display option ────────────────────────────────────────────────────────────
# True  → show all buttons, unbound = dimmed with "—"
# False → only show buttons with an active binding
_SHOW_ALL = True

# ── Button registry ───────────────────────────────────────────────────────────
# key: (svg_x, svg_y, side, short_name, view)
#
# L1/L2/R1/R2 are annotated on the back SVG (shoulder area visible from back),
# balancing the annotation count between front (busier) and back (sparser).
_BTNS = {
    # Front — left side
    "BTN_DPAD_UP":    ( 68,  55, "left",  "↑",    "front"),
    "BTN_DPAD_LEFT":  ( 47,  75, "left",  "←",    "front"),
    "BTN_DPAD_DOWN":  ( 68,  94, "left",  "↓",    "front"),
    "BTN_DPAD_RIGHT": ( 89,  75, "left",  "→",    "front"),
    "BTN_THUMBL":     (164,  90, "left",  "L3",   "front"),
    "BTN_SELECT":     (121,  33, "left",  "View", "front"),
    "BTN_BASE":       (845, 289, "right", "...",  "front"),
    # Front — right side
    "BTN_NORTH":      (959,  44, "right", "Y",    "front"),
    "BTN_WEST":       (929,  74, "right", "X",    "front"),
    "BTN_EAST":       (989,  74, "right", "B",    "front"),
    "BTN_SOUTH":      (959, 104, "right", "A",    "front"),
    "BTN_THUMBR":     (860,  90, "right", "R3",   "front"),
    "BTN_START":      (902,  33, "right", "☰",    "front"),
    "BTN_MODE":       (177, 289, "left",  "Steam","front"),
    # Back — left side: L1/L2 shoulder area (top of back SVG) + paddles
    "BTN_TL2":        ( 52,  58, "left",  "L2",   "back"),
    "BTN_TL":         ( 78,  22, "left",  "L1",   "back"),
    "BTN_GRIPL":      (143, 217, "left",  "L4",   "back"),
    "BTN_GRIPL2":     (143, 298, "left",  "L5",   "back"),
    # Back — right side: R1/R2 + paddles
    "BTN_TR":         (982,  22, "right", "R1",   "back"),
    "BTN_TR2":        (1008, 58, "right", "R2",   "back"),
    "BTN_GRIPR":      (916, 217, "right", "R4",   "back"),
    "BTN_GRIPR2":     (916, 298, "right", "R5",   "back"),
}

# Sort-key overrides (SVG units) for legend ordering.
# Dot position unchanged; only the vertical order in the legend is affected.
_SORT_Y = {
    "BTN_THUMBL": 96,    # below BTN_DPAD_DOWN (y=94) in the legend
    "BTN_THUMBR": 106,   # below BTN_SOUTH/A   (y=104) in the legend
}


# ── Label helpers ─────────────────────────────────────────────────────────────

def _btn_short(key):
    """BTN_TL → 'L1'. Falls back to _K for KEY_* codes, then a readable form."""
    entry = _BTNS.get(key)
    if entry:
        return entry[3]
    if key in _K:
        return _K[key]
    for pfx in ("BTN_", "KEY_"):
        if key.startswith(pfx):
            s = key[len(pfx):]
            return " ".join(w.capitalize() for w in s.replace("_", " ").split()) or key
    return key


def _fmt_combo_key(combo_key):
    """'BTN_TL-BTN_DPAD_UP' → 'L1+↑'"""
    parts = combo_key.split("-")
    return "+".join(_BTNS[p][3] if p in _BTNS else p for p in parts)


# ── Rendering ─────────────────────────────────────────────────────────────────

def draw_callouts(cr, state):
    # "What to show" per button is resolved once, the same way for every
    # renderer (viewmodel.classify_all) — this function only adds geometry.
    vms = classify_all(state, _BTNS.keys())

    lf, lb = [], []   # left-front, left-back
    rf, rb = [], []   # right-front, right-back

    for btn_key, (sx, sy, side, name, view) in _BTNS.items():
        vm = vms[btn_key]

        if not vm.bound and not _SHOW_ALL and not vm.is_active:
            continue

        if view == "front":
            sc_x      = _FX + sx * _FS
            sc_y      = _FY + sy * _FS
            sort_sc_y = _FY + _SORT_Y.get(btn_key, sy) * _FS
        else:
            sc_x      = _BX + sx * _BS
            sc_y      = _BY + sy * _BS
            sort_sc_y = _BY + _SORT_Y.get(btn_key, sy) * _BS

        entry = _Callout(
            sort_y=sort_sc_y, dot_x=sc_x, dot_y=sc_y, name=name, action=vm.action,
            layer_override=vm.layer_override, bound=vm.bound, active=vm.is_active,
            active_mod=vm.active_mod, is_combo=vm.is_combo, is_avail_mod=vm.is_avail_mod,
            sub_label=vm.sub_label, sub_active=vm.sub_active,
            is_avail_app_mod=vm.is_avail_app_mod,
            is_hint=vm.is_hint, is_avail_virt_mod=vm.is_avail_virt_mod,
        )

        if side == "left":
            (lf if view == "front" else lb).append(entry)
        else:
            (rf if view == "front" else rb).append(entry)

    for group in (lf, lb, rf, rb):
        group.sort(key=lambda e: (e.sort_y, e.dot_x, e.dot_y))

    # ── Trackpad mode entries — appended AFTER sort so they don't skew centering ─
    pv = pad_legend_vm(state)
    _lpad_dot = (_FX + (98.86  + 107.5 / 2) * _FS, _FY + (149.31 + 107.6) * _FS)
    _rpad_dot = (_FX + (818.07 + 107.5 / 2) * _FS, _FY + (149.31 + 107.6) * _FS)
    _ROW = 22
    # active_mod=gesture → amber legend; active → white legend; no dot, the pad
    # is not a point on the shell.
    lf.append(_Callout((lf[-1].sort_y if lf else _FY) + _ROW, *_lpad_dot, "LPad", pv.lpad_label,
                       bound=True, active=pv.lpad_active, active_mod=pv.gesture, show_dot=False))
    rf.append(_Callout((rf[-1].sort_y if rf else _FY) + _ROW, *_rpad_dot, "RPad", pv.rpad_label,
                       bound=True, active=pv.rpad_active, active_mod=pv.gesture, show_dot=False))

    _callouts(cr, lf, "left",  _AX_L)
    _callouts(cr, lb, "left",  _AX_L)
    _callouts(cr, rf, "right", _AX_R)
    _callouts(cr, rb, "right", _AX_R)


def _callouts(cr, entries, side, ax, size=10, row=22, straight=False, y_nudge=0, anchor_row=None):
    """straight=True skips the usual auto-stacked vertical centering and
    routes each entry's row at its own dot's y instead — the dot→text line
    degenerates to one straight horizontal segment (no diagonal-then-elbow)
    since the line's own midpoint bend sits at the same y as both ends.
    Only meant for small, already well-separated entry groups (e.g. a
    cluster's own paddle pair) — it does no collision spacing at all.

    y_nudge: shifts the whole auto-centred block up (negative) or down
    (positive) by a flat px amount, on top of the entries' own dot-span
    centring — e.g. "centred, but a little above middle" instead of exactly
    centred on the entries' own min/max y. No effect under straight=True
    (there's no shared centred block to shift — each row already sits at
    its own dot).

    anchor_row: compute the block's vertical anchor (where row 0 lands) as
    if `row` were this value instead, while still spacing the actual rows
    by `row` itself. Lets a later `row` change compress/expand the gaps
    between rows without moving the top row's own position — pass the
    *previous* row value here when tightening row spacing after the fact,
    so only the entries below the first one shift."""
    if not entries:
        return

    ROW       = row
    SUB_EXTRA = row   # extra row height reserved for an entry's sub_label line
    DOT = 3

    # Row heights vary: an entry with a sub_label (Gaming Mode's second line
    # under BTN_BASE) reserves an extra ROW so the following entries don't
    # overlap it. Precompute cumulative offsets instead of a uniform i * ROW.
    heights = [ROW + (SUB_EXTRA if e.sub_label or e.note else 0) for e in entries]
    total   = sum(heights)
    offsets = []
    acc     = 0
    for h in heights:
        offsets.append(acc)
        acc += h

    ys  = [e.sort_y for e in entries]
    mid = (ys[0] + ys[-1]) / 2
    if anchor_row is not None:
        anchor_heights = [anchor_row + (anchor_row if e.sub_label or e.note else 0) for e in entries]
        anchor_total = sum(anchor_heights)
        t0 = mid - anchor_total / 2 + y_nudge
    else:
        t0 = mid - total / 2 + y_nudge

    for i, e in enumerate(entries):
        bx, by, name, action = e.dot_x, e.dot_y, e.name, e.action
        layer_override, bound, active = e.layer_override, e.bound, e.active
        active_mod, is_combo, is_hint = e.active_mod, e.is_combo, e.is_hint
        is_avail_mod, is_avail_app_mod = e.is_avail_mod, e.is_avail_app_mod
        is_avail_virt_mod = e.is_avail_virt_mod
        show_dot, sub_label, sub_active = e.show_dot, e.sub_label, e.sub_active
        ly = by if straight else t0 + offsets[i] + ROW / 2
        if e.hidden:
            continue

        # ── Derive rendering state once ───────────────────────────────────────
        # Priority: modifier-held/combo > layer-override > active > bound > unbound.
        # Exception: when a binding is BOTH modifier-activated AND an app-specific
        # override, colour stays teal (origin wins) and modifier-activation is
        # shown as a yellow underline instead of overriding the colour outright
        # (issue #1) — this is the only place the two dimensions actually conflict.
        # Hints are excluded from the *combo* half of the amber tier on purpose.
        # They follow the modifier logic mechanically — a held button reveals
        # them — but there is no binding behind them, so the amber "a combo
        # fires here" signal would be a lie. They stay teal (app-provided label)
        # with no underline. active_mod deliberately stays outside the
        # exclusion: a button that is itself a held modifier keeps its amber
        # even when a hint happens to sit on it.
        amber     = active_mod or (is_combo and not is_hint)
        conflict  = amber and layer_override
        # Shared alpha for the modifier-driven tiers (conflict + pure amber) —
        # full when the modifier itself is held or a pressed combo, dimmer when
        # just "available". Computed once so both branches below (and the
        # underline accent further down) can't drift out of sync.
        mod_alpha = 1.0 if (active_mod or (is_combo and active)) else 0.75

        if conflict:
            dot_col  = (*C_LAYER, 1.0)
            dot_r    = DOT + 2 if (active or active_mod) else DOT
            line_col = (*C_LAYER, 0.85 if (active or active_mod) else 0.55)
            text_col = (*C_LAYER, mod_alpha)
        elif amber:
            dot_col  = (*C_MOD, 1.0)
            dot_r    = DOT + 2 if (active or active_mod) else DOT
            line_col = (*C_MOD, 0.85 if (active or active_mod) else 0.5)
            text_col = (*C_MOD, mod_alpha)
        elif layer_override:
            dot_col  = (*C_LAYER, 1.0)
            dot_r    = DOT + 2 if active else DOT
            line_col = (*C_LAYER, 0.85 if active else 0.55)
            text_col = (*C_LAYER, 1.0 if active else 0.75)
        elif active:
            dot_col  = (1.0, 1.0, 1.0, 1.0)
            dot_r    = DOT + 2
            line_col = (1.0, 1.0, 1.0, 0.85)
            text_col = (1.0, 1.0, 1.0, 1.0)
        elif bound:
            dot_col  = (1.0, 1.0, 1.0, 0.6)
            dot_r    = DOT
            line_col = (1.0, 1.0, 1.0, 0.55)
            text_col = (0.88, 0.88, 0.88, 1.0)
        else:                                  # unbound
            dot_col  = (1.0, 1.0, 1.0, 0.2)
            dot_r    = DOT
            line_col = (1.0, 1.0, 1.0, 0.15)
            text_col = (0.55, 0.55, 0.55, 0.4)

        if not e.grow_on_active:
            # ABXY's own dot (on their circle's left edge) — on request, it
            # shouldn't grow on press the way every other dot here does; the
            # button's own fill wash + letter already carry that signal.
            dot_r = DOT

        # ── Dot ──────────────────────────────────────────────────────────────
        if show_dot:
            cr.set_source_rgba(*dot_col)
            cr.arc(bx, by, dot_r, 0, math.tau)
            cr.fill()

        # ── Callout line ─────────────────────────────────────────────────────
        cr.set_source_rgba(*line_col)
        cr.set_line_width(1.4)
        ex = (bx + ax) / 2
        cr.move_to(bx, by)
        cr.line_to(ex, ly)
        cr.line_to(ax, ly)
        cr.stroke()

        # ── Label ─────────────────────────────────────────────────────────────
        cr.set_source_rgba(*text_col)
        label = f"{name}: {action}" if e.show_name else action
        # When the main row has nothing real to say ("—") and there's a
        # sub_label waiting to take its place, skip the "—" entirely and let
        # the sub_label sit flush with the dot (same ly) instead of being
        # pushed to a second line below an empty row — e.g. BTN_BASE with no
        # binding still has its Gaming Mode hint, and that hint should read
        # flush with the QAM pill, not dangling under a blank "—" line.
        show_main = not (sub_label and action == "—")
        if show_main:
            if side == "left":
                _txt(cr, ax - 6, ly, label, size, ha="right", va="mid")
            else:
                _txt(cr, ax + 6, ly, label, size, ha="left",  va="mid")

        # ── Gaming Mode sub-label — second line below BTN_BASE's normal
        # callout, unless that callout was skipped above, in which case this
        # takes its place at ly directly. Magenta signal colour; full opacity
        # when Gaming Mode is active, dimmed when inactive — mirrors the
        # on/off state of the mode itself.
        if sub_label:
            sy2 = ly + _txt_size(cr, label, size)[1] + 3 if show_main else ly
            cr.set_source_rgba(*C_GAME, 1.0 if sub_active else 0.4)
            if side == "left":
                _txt(cr, ax - 6, sy2, sub_label, size, ha="right", va="mid")
            else:
                _txt(cr, ax + 6, sy2, sub_label, size, ha="left",  va="mid")

        # ── Binding note (B-18) — smaller, dimmed line under the action:
        # a remark on how to use it, not a second action. Only the split
        # renderer sets it; classic never does.
        elif e.note and show_main:
            ny = ly + _txt_size(cr, label, size)[1] + 1
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.5)
            if side == "left":
                _txt(cr, ax - 6, ny, e.note, size - 3, ha="right", va="mid")
            else:
                _txt(cr, ax + 6, ny, e.note, size - 3, ha="left",  va="mid")

        # ── Conflict accent: yellow underline beneath a teal label that is also
        # modifier-activated (app-specific override unlocked by a held modifier) ──
        if conflict:
            pw, _  = _txt_size(cr, label, size)
            _, ph  = _txt_size(cr, "Ag", size)   # stable reference — avoids ☰ metric quirks
            uy = ly + ph / 2 - 1.0
            if side == "left":
                ux0, ux1 = ax - 6 - pw, ax - 6
            else:
                ux0, ux1 = ax + 6, ax + 6 + pw
            cr.set_source_rgba(*C_MOD, mod_alpha)
            cr.set_line_width(1.3)
            cr.move_to(ux0, uy)
            cr.line_to(ux1, uy)
            cr.stroke()

        # ── Available-modifier diamond ────────────────────────────────────────
        # Amber fill = modifier has combos to unlock.
        # White fill = virtual modifier whose hints are all from the base config
        #              (no app-layer signal needed).
        # Teal fill  = virtual modifier that has at least one app-specific hint
        #              — same colour as app-override labels so the diamond and
        #              what it opens read as one thing.
        # Cyan stroke = at least one of those combos is app-specific (layer
        # override) — same signal language as the teal label + amber underline
        # used for conflict bindings. Redundant under a teal fill, so skipped.
        if is_avail_mod:
            pw, _ = _txt_size(cr, label, size)
            r = 3
            if side == "left":
                dot_x = ax - 6 - pw - 8
            else:
                dot_x = ax + 6 + pw + 8
            def _diamond():
                cr.move_to(dot_x,     ly - r)
                cr.line_to(dot_x + r, ly)
                cr.line_to(dot_x,     ly + r)
                cr.line_to(dot_x - r, ly)
                cr.close_path()
            # Virtual modifier with only base-config hints → white diamond
            # (no app-layer signal needed; teal is reserved for when an app
            # override is actually present). Non-virtual modifier → amber.
            if is_avail_virt_mod and is_avail_app_mod:
                _diam_col = C_LAYER
            elif is_avail_virt_mod:
                _diam_col = (1.0, 1.0, 1.0)
            else:
                _diam_col = C_MOD
            cr.set_source_rgba(*_diam_col, 0.85)
            _diamond()
            cr.fill()
            if is_avail_app_mod and not is_avail_virt_mod:
                cr.set_source_rgba(*C_LAYER, 0.9)
                cr.set_line_width(1.0)
                cr.move_to(dot_x - r, ly + r + 2)
                cr.line_to(dot_x + r, ly + r + 2)
                cr.stroke()
