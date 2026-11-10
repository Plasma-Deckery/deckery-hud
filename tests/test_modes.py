"""The layout mode can change at runtime (B-05 reloads win.py): window and
app must not depend on it being fixed at import."""

import importlib


def _reload_win(monkeypatch, mode):
    monkeypatch.setenv("DECKERY_HUD_LAYOUT", mode)
    import win
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
