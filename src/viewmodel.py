"""
viewmodel.py — Turn makima's raw state into a plain, renderer-agnostic
description: what each button's state is, what it's bound to, whether a
modifier unlocks something. No Cairo, no coordinates, no colour — those are
drawing decisions and stay in the renderer that consumes this.

Extracted out of callouts.py (issue #22): this is the "work out what to show"
half, so a second renderer can reuse it instead of recomputing the same
classification inline.
"""

import unicodedata
from dataclasses import dataclass

# Gaming Mode trigger is always BTN_BASE (QAM / three-dot button) — hardcoded,
# not matched against gaming_mode_trigger.key, per explicit product decision.
_GAMING_MODE_BTN = "BTN_BASE"


@dataclass
class ButtonVM:
    """Semantic state of one button, independent of where/how it's drawn."""
    key: str
    bound: bool            # has a resolved binding (base or combo) with an action/label
    action: str             # display text for the action, "—" if unbound
    layer_override: bool    # the binding in effect comes from a non-base config
    is_active: bool         # physically pressed right now
    active_mod: bool        # this button is itself a currently-held modifier
    is_combo: bool          # overridden by an active modifier combo (modifier_active)
    is_hint: bool            # the combo entry is kind == "hint" (label only, no binding)
    is_avail_mod: bool       # could be held next to unlock something (not already held)
    is_avail_app_mod: bool   # ...and what it unlocks includes an app-layer binding
    is_avail_virt_mod: bool  # ...and it's a virtual (hint-only) modifier
    sub_label: str = None     # second-line label (Gaming Mode trigger only, today)
    sub_active: bool = False
    note: str = None          # how the action is used ("halten"), from makima's note = "…"


def classify_button(btn_key, state, *, gaming_mode_btn=_GAMING_MODE_BTN):
    """Pure function: button key + full makima state → ButtonVM.

    Mirrors the per-button classification that used to live inline in
    callouts.py::draw_callouts — same rules, same priority order, just with
    no geometry or colour attached.
    """
    ctx = state.get("context") or {}
    held_mods = ctx.get("held_modifiers", [])
    mod_active = state.get("modifier_active") or {}
    active_btns = set(ctx.get("active_buttons", []))
    config_stack = ctx.get("config_stack") or [""]
    base_layer = config_stack[0]
    active_mods = set(held_mods)
    avail_mods_raw = ctx.get("available_modifiers") or {}
    avail_mods = set(avail_mods_raw)
    avail_app_mods = {k for k, v in avail_mods_raw.items() if v.get("has_app_combos")}
    avail_virt_mods = {k for k, v in avail_mods_raw.items() if v.get("virtual")}

    gm_trigger = state.get("gaming_mode_trigger")
    gm_sub_label = f"(dbl-click) {gm_trigger['label']}" if gm_trigger else None

    all_bindings = state.get("bindings") or {}

    combo_b = mod_active.get(btn_key)
    base_b = all_bindings.get(btn_key)

    is_combo = combo_b is not None
    b = combo_b if is_combo else base_b
    has_action = bool(b and (b.get("action") or b.get("label")))
    is_active = btn_key in active_btns
    is_mod = btn_key in active_mods
    is_avail_mod = btn_key in avail_mods and not is_mod
    is_avail_app_mod = btn_key in avail_app_mods and not is_mod
    is_avail_virt_mod = btn_key in avail_virt_mods and not is_mod
    # Only combo hints need this: they arrive through modifier_active and
    # would otherwise inherit the "a binding fires here" signal. Deliberately
    # not read from base_b — a modifier-less hint can sit on a button that is
    # itself a modifier, and stripping that button's signal while it's held
    # would hide a real one.
    is_hint = is_combo and b.get("kind") == "hint"

    if has_action:
        # layer_override: binding (base OR combo) comes from a non-base
        # config. modifier_active entries carry "origin" just like base
        # bindings, so this applies uniformly.
        layer_override = b.get("origin", base_layer) != base_layer
        action = b.get("label") or _fmt(b["action"])
        note = b.get("note")
    else:
        layer_override = False
        action = "—"
        note = None

    sub_label = gm_sub_label if btn_key == gaming_mode_btn else None
    sub_active = is_active if btn_key == gaming_mode_btn else False

    return ButtonVM(
        key=btn_key, bound=has_action, action=action,
        layer_override=layer_override, is_active=is_active, active_mod=is_mod,
        is_combo=is_combo, is_hint=is_hint, is_avail_mod=is_avail_mod,
        is_avail_app_mod=is_avail_app_mod, is_avail_virt_mod=is_avail_virt_mod,
        sub_label=sub_label, sub_active=sub_active, note=note,
    )


def classify_all(state, button_keys):
    """classify_button for every key in button_keys, as a dict."""
    return {k: classify_button(k, state) for k in button_keys}


@dataclass
class PadLegendVM:
    lpad_label: str
    lpad_active: bool
    rpad_label: str
    rpad_active: bool
    gesture: bool


def pad_legend_vm(state):
    """Trackpad mode-label row — same source data the LPad/RPad legend
    entries have always come from, pulled out so both renderers compute it
    the same way."""
    pads = state.get("trackpads") or {}
    lpad = pads.get("left") or {}
    rpad = pads.get("right") or {}
    gesture = (pads.get("gesture") or {}).get("touching", False)
    lpad_mode = (lpad.get("mode") or "—").replace("-", " ").title()
    rpad_mode = (rpad.get("mode") or "—").replace("-", " ").title()
    lpad_touch = lpad.get("touching", False)
    rpad_touch = rpad.get("touching", False)
    # gesture → amber (active_mod) for both; individual touch → white (active)
    return PadLegendVM(
        lpad_label=lpad_mode, lpad_active=lpad_touch or gesture,
        rpad_label=rpad_mode, rpad_active=rpad_touch or gesture,
        gesture=gesture,
    )


# ── Label helpers (moved here from helpers.py's neighbourhood — pure text,
# no drawing) ────────────────────────────────────────────────────────────────

_K = {
    "KEY_LEFTCTRL":  "Ctrl",   "KEY_LEFTALT":   "Alt",   "KEY_LEFTSHIFT": "Shift",
    "KEY_LEFTMETA":  "Super",  "KEY_ENTER":     "Enter", "KEY_ESC":       "Esc",
    "KEY_SPACE":     "Space",  "KEY_BACKSPACE": "⌫",     "KEY_TAB":       "Tab",
    "KEY_UP":        "↑",      "KEY_DOWN":      "↓",     "KEY_LEFT":      "←",
    "KEY_RIGHT":     "→",      "KEY_PAGEUP":    "PgUp",  "KEY_PAGEDOWN":  "PgDn",
    "BTN_LEFT":      "LClick", "BTN_RIGHT":     "RClick",
}


def split_icon(text):
    """'☀ Brightness Up' → ('☀', 'Brightness Up'); anything else → (None, text).

    B-17: icons live in the config label itself, as a leading Unicode symbol
    and a space. The HUD doesn't recognise actions — it only splits that
    prefix off so the split renderer can set it in its own slot. A symbol
    with no text after it ("⌫", "↑" from _fmt) is the label, not an icon."""
    head, sep, rest = text.partition(" ")
    if not sep or not rest.strip() or not head:
        return None, text
    # Category So = "other symbol" (☀ ⏯ 🔇 ⏻ ⎙ …); Mn/Cf after the first
    # character lets a variation selector (U+FE0E/FE0F) or ZWJ ride along.
    if unicodedata.category(head[0]) != "So":
        return None, text
    if any(unicodedata.category(c) not in ("So", "Mn", "Cf") for c in head[1:]):
        return None, text
    return head, rest.lstrip()


def _fmt(keys):
    """['KEY_LEFTCTRL', 'KEY_PAGEDOWN'] → 'Ctrl+PgDn'"""
    if not keys:
        return "—"
    parts = []
    for k in keys:
        if k in _K:
            parts.append(_K[k])
        elif k.startswith("KEY_") or k.startswith("BTN_"):
            parts.append(k.replace("KEY_", "").replace("BTN_", "").capitalize())
        else:
            parts.append(k.split()[-1] if k.strip() else "⌘")
    return "+".join(parts)
