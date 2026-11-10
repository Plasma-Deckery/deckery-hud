"""B-15 × B-12: one RevealSettings, and changed settings reaching the reveal
model live without resetting what is running. Pure logic, fake clock."""

import reveal
import settings
from reveal import Reveal, GroupAnim, RevealSettings, Want, FULL
from test_reveal import _state


def test_one_reveal_settings_class():
    assert reveal.RevealSettings is settings.RevealSettings
    assert settings.Settings().reveal == RevealSettings()


def test_set_settings_shortens_a_running_hold():
    r = Reveal(RevealSettings())
    assert r.update(_state(lpad=True), 0.0) == {}
    r.set_settings(RevealSettings(hold_ms=500))
    # The touch that began at 0.0 keeps counting: not restarted at the change.
    assert r.update(_state(lpad=True), 0.5) == {"LPad": Want(FULL, "detector")}


def test_set_settings_switches_a_detector_off():
    r = Reveal(RevealSettings())
    r.update(_state(lpad=True), 0.0)
    assert r.update(_state(lpad=True), 1.5) == {"LPad": Want(FULL, "detector")}
    r.set_settings(RevealSettings(pad_enabled=False))
    # Like lifting the finger: the pad stays release_ms, then goes.
    assert r.update(_state(lpad=True), 1.6) == {"LPad": Want(FULL, "detector")}
    assert r.update(_state(lpad=True), 2.1) == {}


def test_set_settings_gesture_and_release():
    r = Reveal(RevealSettings())
    r.set_settings(RevealSettings(gesture_hold_ms=800, release_ms=200))
    assert all(h.release == 0.2 for h in r._holds())
    assert r._gesture.hold == 0.8
    assert r._modifier.hold == 1.5


def test_group_anim_uses_new_durations():
    a = GroupAnim(RevealSettings())
    a.settings = RevealSettings(fade_in_ms=100)
    a.set_target(True, "detector", 0.0)
    assert a.tick(0.09)
    assert not a.tick(0.1)
