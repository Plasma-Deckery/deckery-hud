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


class _FakeOsd:
    def __init__(self):
        self.visible, self.over_hud = False, None

    def set_over_hud(self, over):
        self.over_hud = over

    def is_visible(self):
        return self.visible

    def on_state(self, _state):
        pass

    def present(self):
        self.visible = True

    def set_visible(self, v):
        self.visible = v


def _osd_after(monkeypatch, split, full, osd=True, remap=True, theme_mode=None):
    import types
    import app
    monkeypatch.setattr(app, "_split_mode", lambda: split)
    fake = types.SimpleNamespace(_full=full, _osd_enabled=osd, _remapping_enabled=remap,
                                 _theme_mode=theme_mode, _state={}, _osd_win=_FakeOsd())
    app.App._sync_osd(fake)
    return fake._osd_win


def test_osd_stays_up_over_the_open_split_hud(monkeypatch):
    """The open split HUD draws no toasts or output pills of its own: the
    OSD shows them, the same as with it closed — even with the OSD switched
    off, since the HUD's own toasts used to show regardless."""
    for osd in (True, False):
        o = _osd_after(monkeypatch, split=True, full=True, osd=osd)
        assert o.visible and o.over_hud


def test_osd_hides_under_classic_and_the_theme_panel(monkeypatch):
    assert not _osd_after(monkeypatch, split=False, full=True).visible
    assert not _osd_after(monkeypatch, split=True, full=True, theme_mode=object()).visible


def test_osd_with_the_hud_closed_follows_its_switches(monkeypatch):
    for split in (True, False):
        o = _osd_after(monkeypatch, split=split, full=False)
        assert o.visible and o.over_hud is False
        assert not _osd_after(monkeypatch, split=split, full=False, osd=False).visible
        assert not _osd_after(monkeypatch, split=split, full=False, remap=False).visible
