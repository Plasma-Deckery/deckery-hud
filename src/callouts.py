"""
callouts.py — Button registry and callout rendering.
Owns _BTNS, _SORT_Y, _SHOW_ALL, and all callout drawing logic.
"""

import math

from layout import _FX, _FY, _FS, _BX, _BY, _BS, _AX_L, _AX_R
from helpers import _K, _fmt, _txt, _txt_size, C_MOD, C_LAYER

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
    "BTN_WEST":       (959,  44, "right", "Y",    "front"),
    "BTN_NORTH":      (929,  74, "right", "X",    "front"),
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
    ctx          = state.get("context") or {}
    held_mods    = ctx.get("held_modifiers", [])
    mod_active   = state.get("modifier_active") or {}
    active_btns  = set(ctx.get("active_buttons", []))
    config_stack = ctx.get("config_stack") or [""]
    base_layer   = config_stack[0]
    active_mods  = set(held_mods)
    avail_mods   = set(ctx.get("available_modifiers", []))

    # bindings is always the display base — modifier_active overlays on top.
    # We never fully switch views; instead each button is classified into one
    # of three tiers:
    #   is_combo      → button overridden by an active modifier combo   (amber)
    #   layer_override → binding comes from a non-base config layer      (blue)
    #   regular        → normal base binding                             (white)
    all_bindings = state.get("bindings") or {}

    lf, lb = [], []   # left-front, left-back
    rf, rb = [], []   # right-front, right-back

    for btn_key, (sx, sy, side, name, view) in _BTNS.items():
        combo_b  = mod_active.get(btn_key)   # set only when modifier held + combo exists
        base_b   = all_bindings.get(btn_key) # regular binding (if any)

        is_combo  = combo_b is not None
        b         = combo_b if is_combo else base_b
        has_action = bool(b and (b.get("action") or b.get("label")))
        is_active  = btn_key in active_btns
        is_mod      = btn_key in active_mods
        is_avail_mod = btn_key in avail_mods and not is_mod

        if not has_action and not _SHOW_ALL and not is_active:
            continue

        if view == "front":
            sc_x      = _FX + sx * _FS
            sc_y      = _FY + sy * _FS
            sort_sc_y = _FY + _SORT_Y.get(btn_key, sy) * _FS
        else:
            sc_x      = _BX + sx * _BS
            sc_y      = _BY + sy * _BS
            sort_sc_y = _BY + _SORT_Y.get(btn_key, sy) * _BS

        if has_action:
            # layer_override: binding (base OR combo) comes from a non-base config
            # (e.g. Firefox, Konsole). modifier_active entries carry "origin" just
            # like base bindings, so this applies uniformly — a combo that's also
            # app-specific must be flagged too, or the app-specific signal is lost
            # for every combo (issue #1).
            layer_override = b.get("origin", base_layer) != base_layer
            action = b.get("label") or _fmt(b["action"])
        else:
            layer_override = False
            action = "—"

        # entry: (sort_y, dot_x, dot_y, name, action,
        #         layer_override, bound, active, is_mod, is_combo, is_avail_mod, show_dot)
        entry = (sort_sc_y, sc_x, sc_y, name, action,
                 layer_override, has_action, is_active, is_mod, is_combo, is_avail_mod, True)

        if side == "left":
            (lf if view == "front" else lb).append(entry)
        else:
            (rf if view == "front" else rb).append(entry)

    for group in (lf, lb, rf, rb):
        group.sort()

    # ── Trackpad mode entries — appended AFTER sort so they don't skew centering ─
    pads    = state.get("trackpads") or {}
    lpad    = pads.get("left")  or {}
    rpad    = pads.get("right") or {}
    gesture = (pads.get("gesture") or {}).get("touching", False)
    lpad_mode  = (lpad.get("mode") or "—").replace("-", " ").title()
    rpad_mode  = (rpad.get("mode") or "—").replace("-", " ").title()
    lpad_touch = lpad.get("touching", False)
    rpad_touch = rpad.get("touching", False)
    # gesture → amber (active_mod=True) for both; individual touch → white (active=True)
    lpad_active = lpad_touch or gesture
    rpad_active = rpad_touch or gesture
    _lpad_dot = (_FX + (98.86  + 107.5 / 2) * _FS, _FY + (149.31 + 107.6) * _FS)
    _rpad_dot = (_FX + (818.07 + 107.5 / 2) * _FS, _FY + (149.31 + 107.6) * _FS)
    _ROW = 22
    # active_mod=gesture → amber legend; active → white legend; show_dot=False always
    lf.append(((lf[-1][0] if lf else _FY) + _ROW, *_lpad_dot, "LPad", lpad_mode, False, True, lpad_active, gesture, False, False, False))
    rf.append(((rf[-1][0] if rf else _FY) + _ROW, *_rpad_dot, "RPad", rpad_mode, False, True, rpad_active, gesture, False, False, False))

    _callouts(cr, lf, "left",  _AX_L)
    _callouts(cr, lb, "left",  _AX_L)
    _callouts(cr, rf, "right", _AX_R)
    _callouts(cr, rb, "right", _AX_R)


def _callouts(cr, entries, side, ax):
    if not entries:
        return

    ROW = 22
    DOT = 3

    ys  = [e[0] for e in entries]
    mid = (ys[0] + ys[-1]) / 2
    t0  = mid - len(entries) * ROW / 2

    for i, (_, bx, by, name, action,
            layer_override, bound, active, active_mod, is_combo, is_avail_mod, *rest) in enumerate(entries):
        show_dot = rest[0] if rest else True
        ly = t0 + i * ROW + ROW / 2

        # ── Derive rendering state once ───────────────────────────────────────
        # Priority: modifier-held/combo > layer-override > active > bound > unbound.
        # Exception: when a binding is BOTH modifier-activated AND an app-specific
        # override, colour stays teal (origin wins) and modifier-activation is
        # shown as a yellow underline instead of overriding the colour outright
        # (issue #1) — this is the only place the two dimensions actually conflict.
        amber     = active_mod or is_combo
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
        label = f"{name}: {action}"
        if side == "left":
            _txt(cr, ax - 6, ly, label, 10, ha="right", va="mid")
        else:
            _txt(cr, ax + 6, ly, label, 10, ha="left",  va="mid")

        # ── Conflict accent: yellow underline beneath a teal label that is also
        # modifier-activated (app-specific override unlocked by a held modifier) ──
        if conflict:
            pw, ph = _txt_size(cr, label, 10)
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
        if is_avail_mod:
            pw, _ = _txt_size(cr, label, 10)
            r = 3
            if side == "left":
                dot_x = ax - 6 - pw - 8
            else:
                dot_x = ax + 6 + pw + 8
            cr.set_source_rgba(*C_MOD, 0.85)
            cr.move_to(dot_x,     ly - r)
            cr.line_to(dot_x + r, ly)
            cr.line_to(dot_x,     ly + r)
            cr.line_to(dot_x - r, ly)
            cr.close_path()
            cr.fill()
