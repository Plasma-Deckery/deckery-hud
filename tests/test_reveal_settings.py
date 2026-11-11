"""B-15 × B-12: one RevealSettings, and changed settings reaching the reveal
model live without resetting what is running. Pure logic, fake clock."""

import reveal
import settings
from reveal import Reveal, GroupAnim, RevealSettings, Want, FULL
from test_reveal import _state, _s


def test_one_reveal_settings_class():
    assert reveal.RevealSettings is settings.RevealSettings
    assert settings.Settings().reveal == RevealSettings()


def test_set_settings_shortens_a_running_hold():
    r = Reveal(_s())
    assert r.update(_state(lpad=True), 0.0) == {}
    r.set_settings(_s(hold_ms=500))
    # The touch that began at 0.0 keeps counting: not restarted at the change.
    assert r.update(_state(lpad=True), 0.5) == {"LPad": Want(FULL, "detector")}


def test_set_settings_switches_a_detector_off():
    r = Reveal(_s())
    r.update(_state(lpad=True), 0.0)
    assert r.update(_state(lpad=True), 1.5) == {"LPad": Want(FULL, "detector")}
    r.set_settings(_s(pad_enabled=False))
    # Like lifting the finger: the pad goes at once.
    assert r.update(_state(lpad=True), 1.6) == {}


def test_set_settings_gesture_and_release():
    r = Reveal(_s())
    r.set_settings(_s(gesture_hold_ms=800, release_ms=200))
    assert all(h.release == 0.2 for h in r._holds())
    assert r._gesture.hold == 0.8
    assert r._modifier.hold == 1.5


def test_group_anim_uses_new_durations():
    a = GroupAnim(RevealSettings())
    a.settings = RevealSettings(fade_in_ms=100)
    a.set_target(True, "detector", 0.0)
    assert a.tick(0.09)
    assert not a.tick(0.1)


def test_round_two_defaults():
    """Live round 2: the first reveal times felt far too long — halved."""
    s = RevealSettings()
    assert (s.hold_ms, s.gesture_hold_ms, s.release_ms) == (750, 750, 250)
