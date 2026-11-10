"""reveal.py — detectors, content, per-group animation (B-12). Pure logic,
fake clock, no GTK."""

import pytest

from reveal import (Content, FULL, PAD_ONLY, GROUPS, Hold, Reveal, RevealSettings, Want,
                    GroupAnim)

S = RevealSettings()


def _state(held=(), combos=(), avail=(), lpad=False, rpad=False, gesture=False, gaming=False):
    entry = {"action": ["KEY_A"], "kind": "remap", "label": None, "origin": "Steam Deck",
             "silent": False}
    return {
        "context": {"held_modifiers": list(held), "available_modifiers": {k: {} for k in avail},
                    "gaming_mode": gaming},
        "modifier_active": {k: dict(entry) for k in combos},
        "trackpads": {"left": {"touching": lpad}, "right": {"touching": rpad},
                      "gesture": {"touching": gesture}},
    }


# ── Hold ──────────────────────────────────────────────────────────────────

def test_hold_fires_after_hold_ms():
    h = Hold(1500, 500)
    assert not h.update(True, 0.0)
    assert not h.update(True, 1.49)
    assert h.update(True, 1.5)


def test_hold_bridges_short_gap():
    h = Hold(1500, 500)
    h.update(True, 0.0)
    h.update(False, 1.0)
    h.update(True, 1.3)
    assert h.update(True, 1.5)


def test_hold_gap_longer_than_release_restarts():
    h = Hold(1500, 500)
    h.update(True, 0.0)
    h.update(False, 1.0)
    h.update(False, 1.6)
    h.update(True, 1.7)
    assert not h.update(True, 3.1)
    assert h.update(True, 3.2)


def test_hold_release_delay():
    h = Hold(1500, 500)
    h.update(True, 0.0)
    assert h.update(True, 1.5)
    assert h.update(False, 2.0)
    assert h.next_change(2.0) == 2.5
    assert h.update(False, 2.49)
    assert not h.update(False, 2.5)


# ── Reveal ────────────────────────────────────────────────────────────────

def test_full_wants_all_groups_full():
    r = Reveal(S)
    r.full = True
    wants = r.update(_state(), 0.0)
    assert set(wants) == set(GROUPS)
    assert all(w == Want(FULL, "full") for w in wants.values())


def test_pad_detector_wants_pad_only():
    r = Reveal(S)
    assert r.update(_state(lpad=True), 0.0) == {}
    assert r.update(_state(lpad=True), 1.5) == {"l_pad": Want(PAD_ONLY, "detector")}


def test_gesture_wants_both_pads():
    r = Reveal(RevealSettings(gesture_hold_ms=800))
    r.update(_state(gesture=True), 0.0)
    assert r.update(_state(gesture=True), 0.8) == {"l_pad": Want(PAD_ONLY, "detector"),
                                                   "r_pad": Want(PAD_ONLY, "detector")}


def test_modifier_reveal_filters():
    r = Reveal(S)
    st = _state(held=["BTN_TL"], combos=["BTN_DPAD_UP", "BTN_SOUTH"], avail=["BTN_TR"])
    r.update(st, 0.0)
    wants = r.update(st, 1.5)
    assert wants == {
        "l_face": Want(Content(frozenset({"BTN_DPAD_UP"}), False, "all"), "detector"),
        "r_face": Want(Content(frozenset({"BTN_SOUTH"}), False, "all"), "detector"),
        "l_shoulder": Want(Content(frozenset({"BTN_TL"}), False, "all"), "detector"),
        "r_shoulder": Want(Content(frozenset({"BTN_TR"}), False, "all"), "detector"),
    }


def test_modifier_layer_switch_is_immediate():
    r = Reveal(S)
    r.update(_state(held=["BTN_TL"], combos=["BTN_DPAD_UP"]), 0.0)
    r.update(_state(held=["BTN_TL"], combos=["BTN_DPAD_UP"]), 1.5)
    wants = r.update(_state(held=["BTN_TL", "BTN_TR"], combos=["BTN_NORTH"]), 1.6)
    assert set(wants) == {"l_shoulder", "r_shoulder", "r_face"}
    assert wants["r_face"].content.legends == frozenset({"BTN_NORTH"})


def test_modifier_release_keeps_last_groups():
    r = Reveal(S)
    st = _state(held=["BTN_TL"], combos=["BTN_DPAD_UP"])
    r.update(st, 0.0)
    shown = r.update(st, 1.5)
    assert r.update(_state(), 2.0) == shown
    assert r.update(_state(), 2.5) == {}


def test_virtual_modifier_triggers():
    r = Reveal(S)
    st = _state(combos=["BTN_SOUTH"])
    r.update(st, 0.0)
    assert set(r.update(st, 1.5)) == {"r_face"}


def test_full_overrides_filter():
    r = Reveal(S)
    st = _state(held=["BTN_TL"], combos=["BTN_DPAD_UP"])
    r.update(st, 0.0)
    r.full = True
    assert r.update(st, 1.5)["l_face"] == Want(FULL, "full")


def test_union_of_filters():
    r = Reveal(S)
    st = _state(held=["BTN_TL"], combos=["BTN_BASE"], rpad=True)
    r.update(st, 0.0)
    want = r.update(st, 1.5)["r_pad"]
    assert want == Want(Content(frozenset({"BTN_BASE"}), True, "all"), "detector")


def test_gaming_mode_resets_detectors():
    r = Reveal(S)
    r.update(_state(lpad=True), 0.0)
    assert r.update(_state(lpad=True), 1.5)
    assert r.update(_state(lpad=True, gaming=True), 2.0) == {}
    r.update(_state(lpad=True), 5.0)
    assert r.update(_state(lpad=True), 6.49) == {}
    assert set(r.update(_state(lpad=True), 6.5)) == {"l_pad"}


@pytest.mark.parametrize("state", [{}, {"trackpads": None}, {"unreadable": "x"},
                                   {"context": None, "modifier_active": None}])
def test_reveal_tolerates_missing_fields(state):
    r = Reveal(S)
    assert r.update(state, 0.0) == {}
    assert r.update(state, 2.0) == {}


def test_disabled_settings():
    off = Reveal(RevealSettings(enabled=False))
    off.update(_state(lpad=True), 0.0)
    assert off.update(_state(lpad=True), 1.5) == {}
    off.full = True
    assert set(off.update(_state(), 2.0)) == set(GROUPS)
    no_pad = Reveal(RevealSettings(pad_enabled=False))
    no_pad.update(_state(lpad=True), 0.0)
    assert no_pad.update(_state(lpad=True), 1.5) == {}


def test_next_deadline():
    r = Reveal(S)
    r.update(_state(), 0.0)
    assert r.next_deadline() is None
    r.update(_state(lpad=True), 0.0)
    assert r.next_deadline() == 1.5


# ── GroupAnim ─────────────────────────────────────────────────────────────

def test_anim_style_from_cause():
    a = GroupAnim(S)
    a.set_target(True, "full", 0.0)
    assert a.style == "slide"
    b = GroupAnim(S)
    b.set_target(True, "detector", 0.0)
    assert b.style == "fade"


def test_anim_reverses_in_place():
    a = GroupAnim(S)
    a.set_target(True, "detector", 0.0)
    a.tick(0.1)
    before = a.value
    assert 0.0 < before < 1.0
    a.set_target(False, "full", 0.1)
    assert a.style == "fade"
    a.tick(0.11)
    assert a.value <= before
    assert before - a.value < 0.05
    a.tick(0.2)
    assert a.value < before


def test_anim_visible_group_stays_on_full_open():
    a = GroupAnim(S)
    a.set_target(True, "detector", 0.0)
    assert not a.tick(1.0)
    a.set_target(True, "full", 1.0)
    assert a.style == "fade"
    assert not a.tick(1.1)
    assert a.value == 1.0


@pytest.mark.parametrize("cause,on,dur", [("full", True, 0.26), ("detector", True, 0.2),
                                          ("detector", False, 0.3), ("full", False, 0.26)])
def test_anim_durations(cause, on, dur):
    a = GroupAnim(S)
    if not on:
        a.set_target(True, cause, 0.0)
        a.tick(1.0)
    start = 2.0
    a.set_target(on, cause, start)
    assert a.tick(start + dur - 0.01)
    assert not a.tick(start + dur)
    assert a.value == (1.0 if on else 0.0)


def test_anim_rapid_flips_end_consistent():
    a = GroupAnim(S)
    t = 0.0
    for i in range(20):
        a.set_target(i % 2 == 0, "full" if i % 3 else "detector", t)
        a.tick(t)
        t += 0.01
    a.set_target(False, "detector", t)
    end = t + 0.3 + 0.26
    assert not a.tick(end)
    assert a.value == 0.0
    assert not a.target


# ── Final-review fixes ────────────────────────────────────────────────────

def _makima_pads(l, r, gesture):
    # makima reports per-pad touching as False while a gesture is active
    # (lpad_touching = !gesture_touching && touching_hw).
    return _state(lpad=l and not gesture, rpad=r and not gesture, gesture=gesture)


def test_gesture_survivor_pad_stays():
    r = Reveal(S)
    r.update(_makima_pads(True, False, False), 0.0)
    r.update(_makima_pads(True, True, True), 0.1)
    assert set(r.update(_makima_pads(True, True, True), 2.0)) == {"l_pad", "r_pad"}
    # right finger lifts: gesture ends, left pad survives
    for t in (3.0, 3.2, 3.49, 3.5, 4.0, 4.6):
        assert "l_pad" in r.update(_makima_pads(True, False, False), t), t
    assert set(r.update(_makima_pads(True, False, False), 3.6)) == {"l_pad"}


def test_hold_does_not_fire_after_release():
    h = Hold(1500, 500)
    h.update(True, 0.0)
    h.update(False, 1.2)
    assert not h.update(False, 1.6)
    assert not h.update(False, 1.7)


def test_hold_fires_when_raw_returns_after_threshold():
    h = Hold(1500, 500)
    h.update(True, 0.0)
    h.update(False, 1.4)
    assert not h.update(False, 1.6)
    assert h.update(True, 1.7)


def test_anim_delay_shifts_running_transition():
    """A stalled frame (e.g. a cold layer build) is taken out of the
    animation's time instead of skipping most of it."""
    a = GroupAnim(S)
    a.set_target(True, "full", 0.0)
    a.tick(0.05)
    v = a.value
    a.delay(0.4)
    assert a.tick(0.45)
    assert abs(a.value - v) < 1e-9
    assert not a.tick(0.66)
