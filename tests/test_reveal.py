"""reveal.py — detectors, content, per-group animation (B-12). Pure logic,
fake clock, no GTK."""

import dataclasses

import pytest

from reveal import (Content, crumbs, FULL, GROUPS, Hold, Reveal, RevealSettings, Want, GroupAnim)

# The logic tests below are written against these numbers, not whatever
# the defaults are at the moment.
S = RevealSettings(hold_ms=1500, gesture_hold_ms=1500, release_ms=500, fade_out_ms=300,
                   breadcrumbs=False)


def _s(**changes):
    return dataclasses.replace(S, **changes)


BASE, APP = "Steam Deck Base", "Claude Desktop"


def _state(held=(), combos=(), avail=(), lpad=False, rpad=False, gesture=False, gaming=False,
           pressed=(), action_ts=None, origins=None):
    entry = {"action": ["KEY_A"], "kind": "remap", "label": None, "origin": BASE,
             "silent": False}
    return {
        "context": {"held_modifiers": list(held), "available_modifiers": {k: {} for k in avail},
                    "gaming_mode": gaming, "active_buttons": list(held) + list(pressed),
                    "config_stack": [BASE, APP]},
        "last_action": None if action_ts is None else {"label": "Copy", "ts": action_ts},
        "modifier_active": {k: dict(entry, origin=(origins or {}).get(k, BASE)) for k in combos},
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
    assert h.update(True, 4.4)       # once shown, the grace is the hold itself
    assert not h.update(False, 5.0)
    assert not h.update(True, 6.6)   # gap longer than the grace: hold again
    assert h.update(True, 8.1)


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
    # No jump: one 10 ms step of a fade-out's quick start, as a fade-in's
    # own first step is (~0.1), not a cut.
    assert before - a.value < 0.15
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


def test_anim_jump_then_fade_out_from_there():
    """A frozen copy takes over an element's visibility where it was."""
    ghost = GroupAnim(S)
    ghost.jump(0.5, True)
    assert ghost.value == 0.5 and not ghost.running
    ghost.set_target(False, "detector", 0.0)
    assert ghost.style == "fade"
    assert ghost.tick(0.14)
    assert not ghost.tick(0.15)   # half the way: half of fade_out_ms
    assert ghost.value == 0.0
    el = GroupAnim(S)
    el.set_target(True, "full", 0.0)
    el.jump(0.0, False)
    assert el.value == 0.0 and not el.target and not el.running


# ── Live feedback: the modifier reveal is for an idle hold ────────────────

L1 = dict(held=["BTN_TL"], combos=["BTN_SOUTH"])


def test_a_keystroke_restarts_the_modifier_hold():
    """Holding L1 and firing L1+A knows what it does: no reveal until the
    hold has been idle for hold_ms."""
    r = Reveal(S)
    r.update(_state(**L1), 0.0)
    r.update(_state(**L1, pressed=["BTN_SOUTH"]), 1.0)
    r.update(_state(**L1), 1.1)
    assert r.update(_state(**L1), 1.6) == {}
    assert r.next_deadline() == 2.5
    assert "A" in r.update(_state(**L1), 2.5)


def test_a_fired_action_restarts_the_modifier_hold():
    r = Reveal(S)
    r.update(_state(**L1), 0.0)
    r.update(_state(**L1, action_ts=100.0), 1.0)
    assert r.update(_state(**L1, action_ts=100.0), 1.6) == {}
    assert "A" in r.update(_state(**L1, action_ts=100.0), 2.5)


def test_activity_keeps_a_shown_reveal():
    r = Reveal(S)
    r.update(_state(**L1), 0.0)
    assert "A" in r.update(_state(**L1), 1.5)
    assert "A" in r.update(_state(**L1, pressed=["BTN_SOUTH"], action_ts=5.0), 1.6)


def test_adding_a_modifier_is_not_activity():
    r = Reveal(S)
    r.update(_state(**L1), 0.0)
    r.update(_state(held=["BTN_TL", "BTN_TR"], combos=["BTN_NORTH"]), 1.0)
    assert "Y" in r.update(_state(held=["BTN_TL", "BTN_TR"], combos=["BTN_NORTH"]), 1.5)


def test_pad_reveal_ignores_keystrokes():
    r = Reveal(S)
    r.update(_state(lpad=True), 0.0)
    r.update(_state(lpad=True, pressed=["BTN_SOUTH"], action_ts=3.0), 1.0)
    assert "LPad" in r.update(_state(lpad=True), 1.5)


# ── Live regression: a layer change popped instead of crossfading ─────────

def test_crossfade_starts_after_the_frame_that_starts_it():
    """The frame that starts a layer crossfade rebuilds every changed
    element (~110 ms in the full HUD, measured): the crossfade must not
    spend its 200 ms on that one frame, or the new legend just pops. Its
    clock starts at the first tick after it, and a later stall is taken out
    like for GroupAnim."""
    from reveal import Crossfade
    x = Crossfade("old")
    assert x.progress(5.0, S) == 0.0 and x.running(5.0, S)
    x.begin(0.12)
    x.begin(0.13)   # only the first tick starts it
    assert x.progress(0.12, S) == 0.0
    assert abs(x.progress(0.22, S) - 0.5) < 1e-9
    x.delay(0.3)
    assert x.running(0.5, S)
    assert not x.running(0.62, S)


# ── Live round 3: a grace window after the fade-out ───────────────────────
# The test settings: hold 1.5 s, fade-out 0.3 s, so a shown element can be
# brought back at once for 1.8 s after its finger or button lifted.

def test_hold_grace_after_shown_lasts_fade_out_plus_hold():
    h = Hold(1500, 500, 300)
    h.update(True, 0.0)
    assert h.update(True, 1.5)
    h.update(False, 2.0)
    assert h.update(True, 3.79)
    h.update(False, 4.0)
    assert not h.update(True, 5.81)
    assert h.update(True, 7.31)


def test_hold_without_being_shown_keeps_the_short_bridge():
    h = Hold(1500, 500, 300)
    h.update(True, 0.0)
    h.update(False, 1.0)
    assert not h.update(True, 1.6)
    assert not h.update(True, 3.0)
    assert h.update(True, 3.1)


def test_pad_comes_back_at_once_within_the_grace():
    """Live round 3: "if I release it and it just disappeared, and I tap
    on it again, it should still come back for a moment"."""
    r = Reveal(S)
    r.update(_state(lpad=True), 0.0)
    assert "LPad" in r.update(_state(lpad=True), 1.5)
    assert r.update(_state(), 2.0) == {}
    assert "LPad" in r.update(_state(lpad=True), 3.7)
    r.update(_state(), 4.0)
    assert r.update(_state(lpad=True), 5.9) == {}


def test_gesture_comes_back_at_once_within_the_grace():
    r = Reveal(S)
    r.update(_makima_pads(True, True, True), 0.0)
    assert set(r.update(_makima_pads(True, True, True), 1.5)) == {"LPad", "RPad"}
    assert r.update(_makima_pads(False, False, False), 2.0) == {}
    assert set(r.update(_makima_pads(True, True, True), 3.7)) == {"LPad", "RPad"}


def test_gesture_grace_uses_the_gesture_hold():
    r = Reveal(_s(hold_ms=3000, gesture_hold_ms=1000))
    r.update(_makima_pads(True, True, True), 0.0)
    assert set(r.update(_makima_pads(True, True, True), 1.0)) == {"LPad", "RPad"}
    r.update(_makima_pads(False, False, False), 1.2)
    assert set(r.update(_makima_pads(True, True, True), 2.4)) == {"LPad", "RPad"}


def test_modifier_comes_back_at_once_within_the_grace():
    r = Reveal(S)
    r.update(_state(**L1), 0.0)
    assert "A" in r.update(_state(**L1), 1.5)
    assert r.update(_state(), 2.0) == {}
    assert "A" in r.update(_state(**L1), 3.7)


def test_a_keystroke_between_ends_the_modifier_grace():
    """Pressing something else after letting go means moving on: the next
    hold is a new one."""
    r = Reveal(S)
    r.update(_state(**L1), 0.0)
    assert "A" in r.update(_state(**L1), 1.5)
    r.update(_state(), 2.0)
    r.update(_state(pressed=["BTN_SOUTH"]), 2.3)
    r.update(_state(), 2.4)
    assert r.update(_state(**L1), 2.6) == {}


def test_set_settings_updates_the_grace():
    r = Reveal(S)
    r.set_settings(_s(fade_out_ms=100))
    assert all(h.fade_out == 0.1 for h in r._holds())


# ── Live round 3: the breadcrumb row comes along with a partial reveal ────
# Only what is relevant: the config layers that contribute a binding to what
# is shown, and the held modifiers. "Steam Deck Base" is hidden by default
# (theme crumbs.base).

@pytest.fixture
def base_crumb(monkeypatch):
    import theme
    monkeypatch.setattr(theme, "_active", dataclasses.replace(theme.Theme(), crumbs_base=True))


def test_modifier_reveal_shows_the_app_that_binds_the_combos():
    """L1 in Claude Desktop: Claude defines Undo/Redo — its pill and L1."""
    r = Reveal(_s(breadcrumbs=True))
    st = _state(**L1, origins={"BTN_SOUTH": APP})
    r.update(st, 0.0)
    assert r.update(st, 1.5)["center"] == Want(crumbs({APP}), "detector")


def test_modifier_reveal_without_app_combos_shows_only_the_modifiers():
    """L1+R1 with no Claude command: no Claude pill, just the modifiers."""
    r = Reveal(_s(breadcrumbs=True))
    st = _state(held=["BTN_TL", "BTN_TR"], combos=["BTN_NORTH"])
    r.update(st, 0.0)
    assert r.update(st, 1.5)["center"] == Want(crumbs(()), "detector")


def test_base_combos_show_the_base_when_it_is_shown(base_crumb):
    r = Reveal(_s(breadcrumbs=True))
    st = _state(held=["BTN_TL", "BTN_TR"], combos=["BTN_NORTH", "BTN_SOUTH"],
                origins={"BTN_SOUTH": APP})
    r.update(st, 0.0)
    assert r.update(st, 1.5)["center"] == Want(crumbs({BASE, APP}), "detector")


def test_pad_reveal_has_no_breadcrumbs_with_the_base_hidden():
    """A pad's mode always comes from the base config (makima's trackpad
    is device-level): with the base hidden, nothing is relevant."""
    r = Reveal(_s(breadcrumbs=True))
    r.update(_state(lpad=True), 0.0)
    assert r.update(_state(lpad=True), 1.5) == {"LPad": Want(FULL, "detector")}


def test_pad_reveal_shows_the_base_when_it_is_shown(base_crumb):
    r = Reveal(_s(breadcrumbs=True))
    r.update(_state(lpad=True), 0.0)
    assert r.update(_state(lpad=True), 1.5)["center"] == Want(crumbs({BASE}), "detector")


def test_gesture_has_no_breadcrumbs(base_crumb):
    r = Reveal(_s(breadcrumbs=True))
    r.update(_makima_pads(True, True, True), 0.0)
    assert "center" not in r.update(_makima_pads(True, True, True), 1.5)


def test_no_breadcrumbs_without_a_reveal():
    r = Reveal(_s(breadcrumbs=True))
    assert r.update(_state(**L1, origins={"BTN_SOUTH": APP}), 0.0) == {}


def test_full_hud_shows_the_whole_centre():
    r = Reveal(_s(breadcrumbs=True))
    r.full = True
    r.update(_state(lpad=True), 0.0)
    assert r.update(_state(lpad=True), 1.5)["center"] == Want(FULL, "full")


def test_breadcrumbs_can_be_switched_off():
    r = Reveal(_s(breadcrumbs=False))
    st = _state(**L1, origins={"BTN_SOUTH": APP})
    r.update(st, 0.0)
    assert "center" not in r.update(st, 1.5)


# ── Live round 3: transitions crawled under CPU load ──────────────────────

def test_a_late_tick_under_load_is_not_taken_out():
    """A tick that came late because the system is busy (measured under
    load: p99 138 ms, max 319 ms) is real time passing: the transition
    keeps to its duration. Taking every late tick out of it made a 200 ms
    fade take up to ~660 ms."""
    from reveal import stall_skip
    assert stall_skip(0.14, 0.004) == 0.0


def test_our_own_slow_frame_is_taken_out():
    """A frame we spent rebuilding (a cold layer: ~110-390 ms) still
    doesn't eat the transition — only that frame's own time comes out."""
    from reveal import stall_skip
    assert abs(stall_skip(0.40, 0.39) - (0.39 - 1 / 90)) < 1e-9
    assert abs(stall_skip(0.20, 0.39) - (0.20 - 1 / 90)) < 1e-9   # never more than the gap
    assert stall_skip(0.03, 0.02) == 0.0


# ── Live round 4: fade-out as quick as fade-in ────────────────────────────
# New states popped in, old ones lingered: the fade-in eased out (most of
# the change at the start), the fade-out eased in (most of it at the end),
# and lasted 300 ms against 200 ms.

def test_fade_out_mirrors_fade_in():
    s = RevealSettings()
    assert s.fade_out_ms == s.fade_in_ms
    a, b = GroupAnim(s), GroupAnim(s)
    a.set_target(True, "detector", 0.0)
    b.jump(1.0, True)
    b.set_target(False, "detector", 0.0)
    for t in (0.02, 0.05, 0.1, 0.15):
        a.tick(t), b.tick(t)
        assert abs(a.value - (1.0 - b.value)) < 1e-9


def test_fade_out_is_mostly_gone_early():
    b = GroupAnim(RevealSettings())
    b.jump(1.0, True)
    b.set_target(False, "detector", 0.0)
    b.tick(0.05)            # a quarter of the way
    assert b.value < 0.5


def test_slide_out_keeps_accelerating_away():
    """The full HUD closing slides off, gathering speed: unchanged."""
    b = GroupAnim(RevealSettings())
    b.jump(1.0, True)
    b.style = "slide"
    b.target = True
    b.set_target(False, "full", 0.0)
    b.tick(0.13)            # half of slide_ms
    assert b.value > 0.8


def test_crossfade_mix_drops_the_old_picture_early():
    from reveal import Crossfade
    x = Crossfade("old")
    x.begin(0.0)
    assert x.mix(0.0, S) == 0.0
    assert x.mix(0.05, S) > 0.5     # a quarter of crossfade_ms
    assert x.mix(0.2, S) == 1.0
