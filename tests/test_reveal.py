"""reveal.py — detectors, content, per-group animation (B-12). Pure logic,
fake clock, no GTK."""

import dataclasses

import pytest

from reveal import (Content, FULL, GROUPS, Hold, Reveal, RevealSettings, Want, GroupAnim)

# The logic tests below are written against these numbers, not whatever
# the defaults are at the moment.
S = RevealSettings(hold_ms=1500, gesture_hold_ms=1500, release_ms=500)


def _s(**changes):
    return dataclasses.replace(S, **changes)


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


def test_hold_release_is_immediate_but_bridged():
    """Live round 2: letting go hides at once. Coming back within
    release_ms shows again at once, without a new hold."""
    h = Hold(1500, 500)
    h.update(True, 0.0)
    assert h.update(True, 1.5)
    assert not h.update(False, 2.0)
    assert h.next_change(2.0) is None
    assert h.update(True, 2.4)
    assert not h.update(False, 3.0)
    assert not h.update(True, 3.6)   # gap longer than release_ms: hold again
    assert h.update(True, 5.2)


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
    assert r.update(_state(lpad=True), 1.5) == {"LPad": Want(FULL, "detector")}


def test_gesture_wants_both_pads():
    r = Reveal(_s(gesture_hold_ms=800))
    r.update(_state(gesture=True), 0.0)
    assert r.update(_state(gesture=True), 0.8) == {"LPad": Want(FULL, "detector"),
                                                   "RPad": Want(FULL, "detector")}


def test_modifier_reveal_filters():
    r = Reveal(S)
    st = _state(held=["BTN_TL"], combos=["BTN_DPAD_UP", "BTN_SOUTH"], avail=["BTN_TR"])
    r.update(st, 0.0)
    wants = r.update(st, 1.5)
    # only the buttons that do something on this layer — not L2, not the
    # sticks, not the rest of the d-pad's cluster
    assert wants == {
        "DPad": Want(Content(frozenset({"BTN_DPAD_UP"})), "detector"),
        "A": Want(FULL, "detector"),
        "L1": Want(FULL, "detector"),
        "R1": Want(FULL, "detector"),
    }


def test_modifier_layer_switch_is_immediate():
    r = Reveal(S)
    r.update(_state(held=["BTN_TL"], combos=["BTN_DPAD_UP"]), 0.0)
    r.update(_state(held=["BTN_TL"], combos=["BTN_DPAD_UP"]), 1.5)
    wants = r.update(_state(held=["BTN_TL", "BTN_TR"], combos=["BTN_NORTH"]), 1.6)
    assert set(wants) == {"L1", "R1", "Y"}


def test_modifier_release_hides_at_once():
    r = Reveal(S)
    st = _state(held=["BTN_TL"], combos=["BTN_DPAD_UP"])
    r.update(st, 0.0)
    shown = r.update(st, 1.5)
    assert r.update(_state(), 2.0) == {}
    # L1 -> R1 within release_ms: the next layer shows without a new hold
    st_r1 = _state(held=["BTN_TR"], combos=["BTN_NORTH"])
    assert set(r.update(st_r1, 2.2)) == {"R1", "Y"}
    assert shown


def test_virtual_modifier_triggers():
    r = Reveal(S)
    st = _state(combos=["BTN_SOUTH"])
    r.update(st, 0.0)
    assert set(r.update(st, 1.5)) == {"A"}


def test_full_overrides_filter():
    r = Reveal(S)
    st = _state(held=["BTN_TL"], combos=["BTN_DPAD_UP"])
    r.update(st, 0.0)
    r.full = True
    assert r.update(st, 1.5)["DPad"] == Want(FULL, "full")


def test_pad_and_pill_are_separate_elements():
    r = Reveal(S)
    st = _state(held=["BTN_TL"], combos=["BTN_BASE"], rpad=True)
    r.update(st, 0.0)
    wants = r.update(st, 1.5)
    assert wants["RPad"] == Want(FULL, "detector")
    assert wants["QAM"] == Want(FULL, "detector")


def test_gaming_mode_resets_detectors():
    r = Reveal(S)
    r.update(_state(lpad=True), 0.0)
    assert r.update(_state(lpad=True), 1.5)
    assert r.update(_state(lpad=True, gaming=True), 2.0) == {}
    r.update(_state(lpad=True), 5.0)
    assert r.update(_state(lpad=True), 6.49) == {}
    assert set(r.update(_state(lpad=True), 6.5)) == {"LPad"}


@pytest.mark.parametrize("state", [{}, {"trackpads": None}, {"unreadable": "x"},
                                   {"context": None, "modifier_active": None}])
def test_reveal_tolerates_missing_fields(state):
    r = Reveal(S)
    assert r.update(state, 0.0) == {}
    assert r.update(state, 2.0) == {}


def test_disabled_settings():
    off = Reveal(_s(enabled=False))
    off.update(_state(lpad=True), 0.0)
    assert off.update(_state(lpad=True), 1.5) == {}
    off.full = True
    assert set(off.update(_state(), 2.0)) == set(GROUPS)
    no_pad = Reveal(_s(pad_enabled=False))
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


def test_anim_restart_after_stall_longer_than_duration():
    # A freshly mapped window's first frame can take longer than the whole
    # transition (B-02 measured 270ms against a 260ms slide). Win holds the
    # clocks at the start until that frame is on screen, so the transition
    # must then still run in full instead of having already finished.
    a = GroupAnim(S)
    a.set_target(True, "full", 0.0)
    a.tick(0.01)
    a.restart_clock(0.4)
    assert a.value == 0.0
    assert a.tick(0.4 + 0.13)
    assert 0.0 < a.value < 1.0
    assert not a.tick(0.4 + 0.26)


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
    assert set(r.update(_makima_pads(True, True, True), 2.0)) == {"LPad", "RPad"}
    # right finger lifts: gesture ends, left pad survives
    for t in (3.0, 3.2, 3.49, 3.5, 4.0, 4.6):
        assert "LPad" in r.update(_makima_pads(True, False, False), t), t
    assert set(r.update(_makima_pads(True, False, False), 3.6)) == {"LPad"}


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


# ── Live feedback: gesture escalation ─────────────────────────────────────

def test_gesture_escalates_immediately_when_a_pad_is_shown():
    r = Reveal(S)
    r.update(_makima_pads(False, True, False), 0.0)
    assert set(r.update(_makima_pads(False, True, False), 1.5)) == {"RPad"}
    assert set(r.update(_makima_pads(True, True, True), 2.0)) == {"LPad", "RPad"}


def test_gesture_end_hides_the_other_pad_immediately():
    r = Reveal(S)
    r.update(_makima_pads(False, True, False), 0.0)
    r.update(_makima_pads(False, True, False), 1.5)
    r.update(_makima_pads(True, True, True), 2.0)
    # left thumb lifts: back to the right pad alone, at once
    assert set(r.update(_makima_pads(False, True, False), 2.3)) == {"RPad"}


def test_gesture_end_keeps_the_survivor_even_after_a_short_gesture():
    r = Reveal(S)
    r.update(_makima_pads(False, True, False), 0.0)
    r.update(_makima_pads(False, True, False), 1.5)
    r.update(_makima_pads(True, True, True), 2.0)
    # right thumb lifts after 0.2 s of gesture: the left pad was shown and
    # is still touched, so it stays; the right one goes at once
    assert set(r.update(_makima_pads(True, False, False), 2.2)) == {"LPad"}
    assert set(r.update(_makima_pads(True, False, False), 2.5)) == {"LPad"}


def test_deadline_delay_is_clamped():
    """GLib.timeout_add takes a 32-bit interval; a huge hold_ms from the
    settings file must not overflow it."""
    from reveal import deadline_delay_ms
    assert deadline_delay_ms(1.5, 0.0) == 1501
    assert deadline_delay_ms(0.0, 1.0) == 1
    assert deadline_delay_ms(10 ** 9, 0.0) == 3_600_000
