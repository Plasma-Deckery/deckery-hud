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
