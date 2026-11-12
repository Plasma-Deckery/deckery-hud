"""B-33: an application with its own commands gets focus — a partial
reveal shows them for a moment: its own base-level bindings, the modifiers
with its combos, and its breadcrumb pill. Pure logic, fake clock."""

import dataclasses

import pytest

from reveal import Content, crumbs, FULL, Reveal, RevealSettings, Want

S = RevealSettings(hold_ms=1500, gesture_hold_ms=1500, release_ms=500, fade_out_ms=300,
                   breadcrumbs=True, app_focus=True, app_focus_ms=3000)

BASE, APP, OTHER = "Steam Deck Base", "Claude Desktop", "Firefox"


def _s(**changes):
    return dataclasses.replace(S, **changes)


def _b(origin):
    return {"action": ["KEY_A"], "kind": "remap", "label": None, "origin": origin,
            "silent": False}


def _state(app=APP, own=("BTN_SOUTH", "BTN_DPAD_UP"), app_mods=("BTN_TL",), gaming=False,
           pressed=(), held=(), action_ts=None):
    """Focused on `app`, which binds `own` itself and has combos on
    `app_mods`. Everything else is the base config's."""
    stack = [BASE] if app is None else [BASE, app]
    origin = APP if app is None else app
    bindings = {k: _b(BASE) for k in ("BTN_SOUTH", "BTN_EAST", "BTN_DPAD_UP", "BTN_DPAD_DOWN",
                                       "BTN_TL", "BTN_TR")}
    bindings.update({k: _b(origin) for k in own if app is not None})
    for m in app_mods if app is not None else ():
        bindings[f"{m}-BTN_NORTH"] = _b(origin)
    bindings["BTN_TR-BTN_WEST"] = _b(BASE)
    return {
        "context": {"active_app": app or "default", "config_stack": stack,
                    "held_modifiers": list(held), "active_buttons": list(held) + list(pressed),
                    "available_modifiers": {
                        "BTN_TL": {"has_app_combos": app is not None and "BTN_TL" in app_mods},
                        "BTN_TR": {"has_app_combos": app is not None and "BTN_TR" in app_mods},
                        "BTN_GRIPR2": {"has_app_combos": app is not None and "BTN_GRIPR2" in app_mods,
                                       "virtual": True}},
                    "gaming_mode": gaming},
        "bindings": bindings,
        "modifier_active": {},
        "last_action": None if action_ts is None else {"label": "Copy", "ts": action_ts},
        "trackpads": {"left": {}, "right": {}, "gesture": {}},
    }


def _focus(r, now=1.0, **kw):
    """The HUD saw the desktop first, then `app` got focus at `now`."""
    r.update(_state(app=None), 0.0)
    return r.update(_state(**kw), now)


def test_focus_shows_the_apps_own_commands():
    r = Reveal(S)
    wants = _focus(r)
    assert wants == {
        "A": Want(FULL, "detector"),
        "DPad": Want(Content(frozenset({"BTN_DPAD_UP"})), "detector"),
        "L1": Want(FULL, "detector"),
        "center": Want(crumbs({APP}), "detector"),
    }


def test_virtual_modifier_with_app_hints_is_shown():
    r = Reveal(S)
    wants = _focus(r, app_mods=("BTN_GRIPR2",))
    assert "R5" in wants and "L1" not in wants and "R1" not in wants


def test_preview_stays_for_its_time_then_goes():
    r = Reveal(S)
    _focus(r, now=1.0)
    assert r.next_deadline() == pytest.approx(4.0)
    assert "A" in r.update(_state(), 3.99)
    assert r.update(_state(), 4.0) == {}
    assert r.next_deadline() is None


def test_no_preview_for_an_app_without_own_commands():
    r = Reveal(S)
    assert _focus(r, own=(), app_mods=()) == {}
    assert r.next_deadline() is None


def test_no_preview_for_the_default_config():
    r = Reveal(S)
    r.update(_state(), 0.0)
    assert r.update(_state(app=None), 1.0) == {}


def test_no_preview_on_the_first_state():
    """Starting the HUD isn't a focus change."""
    r = Reveal(S)
    assert r.update(_state(), 0.0) == {}


def test_same_app_again_does_not_restart():
    r = Reveal(S)
    _focus(r, now=1.0)
    r.update(_state(), 2.0)
    assert r.update(_state(), 4.0) == {}


def test_switching_to_another_app_with_commands_shows_that_one():
    r = Reveal(S)
    _focus(r, now=1.0)
    wants = r.update(_state(app=OTHER, own=("BTN_EAST",), app_mods=()), 2.0)
    assert set(wants) == {"B", "center"}
    assert wants["center"] == Want(crumbs({OTHER}), "detector")
    assert r.next_deadline() == pytest.approx(5.0)


def test_switching_to_an_app_without_commands_ends_it():
    r = Reveal(S)
    _focus(r, now=1.0)
    assert r.update(_state(app=None), 2.0) == {}


def test_a_keystroke_ends_it():
    """Pressing something means they know what to do: out of the way."""
    r = Reveal(S)
    _focus(r, now=1.0)
    assert r.update(_state(pressed=["BTN_SOUTH"]), 1.5) == {}
    assert r.update(_state(), 2.0) == {}


def test_a_fired_action_ends_it():
    r = Reveal(S)
    r.update(_state(app=None, action_ts=1.0), 0.0)
    r.update(_state(action_ts=1.0), 1.0)
    assert r.update(_state(action_ts=2.0), 1.5) == {}


def test_a_press_arriving_with_the_focus_change_does_not_end_it():
    """A click that focused the window lands in the same state write."""
    r = Reveal(S)
    r.update(_state(app=None), 0.0)
    assert "A" in r.update(_state(pressed=["BTN_TR2"]), 1.0)


def test_holding_a_modifier_keeps_it():
    """L1 held to look at the app's L1 commands: picking a layer, not acting."""
    r = Reveal(S)
    _focus(r, now=1.0)
    assert "A" in r.update(_state(held=["BTN_TL"]), 1.5)


def test_not_while_the_full_hud_is_open():
    r = Reveal(S)
    r.full = True
    _focus(r, now=1.0)
    r.full = False
    assert r.update(_state(), 1.5) == {}


def test_opening_the_full_hud_ends_it():
    r = Reveal(S)
    _focus(r, now=1.0)
    r.full = True
    r.update(_state(), 1.5)
    r.full = False
    assert r.update(_state(), 2.0) == {}


def test_not_in_gaming_mode():
    r = Reveal(S)
    assert _focus(r, gaming=True) == {}
    assert r.next_deadline() is None


def test_leaving_gaming_mode_into_the_same_app_is_no_focus_change():
    r = Reveal(S)
    r.update(_state(gaming=True), 0.0)
    assert r.update(_state(), 1.0) == {}


@pytest.mark.parametrize("off", [{"app_focus": False}, {"enabled": False}])
def test_can_be_switched_off(off):
    r = Reveal(_s(**off))
    assert _focus(r) == {}
    assert r.next_deadline() is None


def test_breadcrumbs_off_leaves_out_the_pill():
    r = Reveal(_s(breadcrumbs=False))
    assert "center" not in _focus(r)


def test_with_the_modifier_reveal_the_contents_join():
    r = Reveal(S)
    _focus(r, now=1.0)
    st = _state(held=["BTN_TR"])
    st["modifier_active"] = {"BTN_WEST": _b(BASE)}
    r.update(st, 1.0)
    wants = r.update(st, 2.5)
    assert {"A", "L1", "R1", "X"} <= set(wants)


def test_default_is_on():
    assert RevealSettings().app_focus is True
