"""The layout mode can change at runtime (B-05 reloads win.py): window and
app must not depend on it being fixed at import."""

import importlib


def _reload_win(monkeypatch, mode):
    # The way App.switch_layout does it — and independent of whatever the
    # real settings.toml on this machine says.
    import layout_choice
    import win
    with layout_choice.building(mode):
        return importlib.reload(win)


def test_win_has_reveal_in_classic(monkeypatch):
    win = _reload_win(monkeypatch, "classic")
    assert win.RevealSettings and win.GroupAnim and win.GROUPS


def test_app_reads_layout_at_call_time(monkeypatch):
    import app
    _reload_win(monkeypatch, "split")
    assert app._split_mode()
    _reload_win(monkeypatch, "classic")
    assert not app._split_mode()


def test_layout_choice_reads_only_the_settings_file(monkeypatch, tmp_path):
    import layout_choice
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("DECKERY_HUD_LAYOUT", "split")
    assert layout_choice.current() == "classic"
    assert layout_choice.remember("split")
    assert layout_choice.current() == "split"
    with layout_choice.building("classic"):
        assert layout_choice.current() == "classic"
    assert layout_choice.current() == "split"


def test_analog_export_follows_a_single_pad(monkeypatch):
    """A pad shown on its own needs the live touch positions too, not only
    the full HUD (live round 2: the right pad's dot didn't follow)."""
    import types
    import app
    calls = []
    monkeypatch.setattr(app, "makima_analog_on", lambda: calls.append("on"))
    monkeypatch.setattr(app, "makima_analog_off", lambda: calls.append("off"))
    shown = set()
    fake = types.SimpleNamespace(_full=False, _analog_on=False,
                                 _win=types.SimpleNamespace(visible_groups=lambda: frozenset(shown)))
    shown.add("RPad")
    app.App._on_groups_changed(fake)
    assert calls == ["on"]
    shown.clear()
    shown.add("QAM")
    app.App._on_groups_changed(fake)
    assert calls == ["on", "off"]
