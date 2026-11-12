"""OSD animation presets and sprites (B-21). osd_look needs cairo/numpy —
run in the `deckery` distrobox."""

import pytest

import osd_anim
from osd_anim import PRESETS, envelope, resolve


def test_auto_is_pop_in_split_and_slide_in_classic():
    assert resolve("auto", split=True) is PRESETS["pop"]
    assert resolve("auto", split=False) is PRESETS["slide"]
    assert resolve("bubble-soft", split=False) is PRESETS["bubble-soft"]


def test_settings_offer_every_preset():
    import settings
    f = {f.name: f for f in settings.dataclasses.fields(settings.OsdSettings)}["animation"]
    assert f.default == "auto"
    assert set(f.metadata["choices"]) == {"auto", *PRESETS}


@pytest.mark.parametrize("name", ["pop", "bubble-soft"])
def test_pop_envelope_starts_small_and_settles(name):
    a = PRESETS[name]
    scale, alpha = envelope(a, 0.0)
    assert scale == pytest.approx(a.scale_from) and alpha == 0.0
    assert envelope(a, a.in_ms / 1000) == pytest.approx((1.0, 1.0))
    assert envelope(a, 5.0) == pytest.approx((1.0, 1.0))


def test_only_pop_overshoots():
    peak = lambda a: max(envelope(a, i / 1000)[0] for i in range(a.in_ms + 1))
    assert peak(PRESETS["pop"]) > 1.01
    assert peak(PRESETS["bubble-soft"]) <= 1.0 + 1e-9


@pytest.mark.parametrize("name", ["pop", "bubble-soft"])
def test_bubble_out_is_continuous_and_ends(name):
    a = PRESETS[name]
    assert envelope(a, 5.0, 0.0) == pytest.approx((1.0, 1.0))
    scale, alpha = envelope(a, 5.0, a.out_ms / 2000)
    assert a.scale_to < scale < 1.0 and 0.0 < alpha < 1.0
    assert envelope(a, 5.0, a.out_ms / 1000) is None


def test_leaving_mid_pop_starts_where_the_pop_got_to():
    a = PRESETS["pop"]
    half = envelope(a, a.in_ms / 2000)
    assert envelope(a, a.in_ms / 2000, 0.0) == pytest.approx(half)


def test_animating_only_while_moving():
    a = PRESETS["pop"]
    assert osd_anim.animating(a, 0.05)
    assert not osd_anim.animating(a, 1.0)
    assert osd_anim.animating(a, 1.0, 0.05)


# ── sprites ─────────────────────────────────────────────────────────────────

_KEYS = {"type": "keys", "value": ["KEY_LEFTCTRL", "KEY_C"], "ts": 1.0}


@pytest.mark.parametrize("split", [True, False])
def test_toast_sprite_is_built_once(split):
    import osd_look
    from shadow import style_from_env
    style = style_from_env()
    s1 = osd_look.toast_sprite(_KEYS, split, style, 1.1)
    s2 = osd_look.toast_sprite(dict(_KEYS, ts=2.0), split, style, 1.1)
    assert s1 is s2
    # Its top-left sits on the device pixel grid, so at rest it lands 1:1.
    assert (s1.x * 1.1) == pytest.approx(round(s1.x * 1.1))
    assert s1.surface.get_device_scale() == (1.1, 1.1)


def test_neon_toast_sits_on_a_plate_of_its_own_hue():
    """The split toast is a legend on a dark plate tinted like its colour
    (lavender keys: blue over green), with nothing like that in classic."""
    import numpy as np
    import osd_look
    from shadow import style_from_env
    style = style_from_env()

    def px(split):
        s = osd_look.toast_sprite(_KEYS, split, style)
        s.surface.flush()
        w, h = s.surface.get_width(), s.surface.get_height()
        a = np.ndarray((h, s.surface.get_stride() // 4, 4), np.uint8,
                       s.surface.get_data())[:, :w]
        return a, -s.x, -s.y

    a, cx, cy = px(True)
    # A point on the plate just below the text, off the glyphs.
    b, g, r, al = (int(v) for v in a[int(cy) + 14, int(cx)])
    assert al > 100 and b > g
    c, _cx, _cy = px(False)
    assert c.shape[0] < a.shape[0]   # classic: just the pill, no halo


# ── output pills (B-26) ─────────────────────────────────────────────────────

_RAW = ["KEY_LEFTCTRL", {"key": "KEY_C", "silent": True}, {"key": "KEY_V", "silent": False},
        {"key": "", "silent": False}]


def test_silent_outputs_stay_hidden_with_the_hud_closed():
    import osd_look
    assert osd_look.output_keys(_RAW) == ("KEY_LEFTCTRL", "KEY_V")
    assert osd_look.output_keys(None) == ()


def test_silent_outputs_get_pills_over_the_open_hud():
    import osd_look
    assert osd_look.output_keys(_RAW, with_silent=True) == ("KEY_LEFTCTRL", "KEY_C", "KEY_V")


@pytest.mark.parametrize("over_hud,paused,shown", [
    (False, False, False),   # HUD closed: silent stays quiet
    (True, False, True),     # over the open HUD
    (False, True, True),     # makima paused
    (True, True, True),
])
def test_osd_pill_row_shows_silent_only_with_the_hud_open(over_hud, paused, shown):
    import osd_look
    keys = osd_look.pill_keys({"active_outputs": _RAW, "paused": paused}, over_hud)
    assert ("KEY_C" in keys) is shown
    assert "KEY_LEFTCTRL" in keys and "KEY_V" in keys


def test_pills_say_what_is_held_with_symbols_and_glyphs():
    """Modifiers read as symbol and name, a mouse button is its glyph alone,
    any other key gets the keyboard glyph before its name."""
    import osd_look
    keys = ["KEY_LEFTSHIFT", "KEY_LEFTMETA", "KEY_LEFTALT", "KEY_RIGHTCTRL", "BTN_LEFT", "KEY_C"]
    assert [osd_look.output_label(k) for k in keys] == ["⇧ Shift", "❖ Super", "⌥ Alt", "⌃ Ctrl", "", "C"]

    def pills(keys):
        _rec, cap = osd_look._record(lambda cr: osd_look.draw_output_pills(cr, keys, 11))
        return cap
    cap = pills(keys)
    assert len(cap.glass_boxes) == len(keys)
    assert set(cap.texts) <= {"input-mouse-click-left-symbolic", "input-mouse-symbolic"}
    assert cap.texts                                   # the mouse glyph, not "LClick"
    # The keyboard glyph sits in the C pill, before its letter.
    from helpers import _pill_row
    import theme
    _rec, bare = osd_look._record(lambda cr: _pill_row(cr, 0, 0, ["C"], size=11, glass=theme.current().glass))
    assert cap.glass_boxes[-1][2] > bare.glass_boxes[0][2] + 15


def test_pill_size_comes_from_theme_and_setting():
    import dataclasses
    import osd_look
    import settings
    import theme
    from shadow import style_from_env
    f = {f.name: f for f in dataclasses.fields(settings.OsdSettings)}["pill_scale"]
    assert f.default == 1.0 and f.metadata["minimum"] > 0
    assert theme.current().osd_pill_size > 9          # a bit larger than before B-26
    assert osd_look.pill_size(1.5) == pytest.approx(theme.current().osd_pill_size * 1.5)
    style = style_from_env()
    small = osd_look.pills_sprite(("KEY_C",), style, 1.0, 9)
    big = osd_look.pills_sprite(("KEY_C",), style, 1.0, 13)
    assert big.surface.get_height() > small.surface.get_height()


def test_theme_sets_the_pill_size():
    import theme
    vals = {}
    theme._osd({"pill_size": 13}, vals, "t.toml")
    assert vals["osd_pill_size"] == 13.0


@pytest.mark.parametrize("theme_name", ["neon", "glass", "contrast"])
@pytest.mark.parametrize("size", [11, 15.4])
def test_pill_symbol_and_text_share_one_centre_line(theme_name, size, monkeypatch):
    """⌃ comes from a fallback font with its own ascent; in the pill its ink
    centres on the text's cap height, like a B-17 label icon, not high up."""
    import dataclasses
    import numpy as np
    import osd_look
    import theme
    # Without the pill's contour (contrast has one), the glyphs stand alone,
    # all in the text's colour.
    monkeypatch.setattr(theme, "_active", dataclasses.replace(
        theme.load(theme_name), pill_border=None, pill_icon=None))
    rec, _cap = osd_look._record(lambda cr: osd_look.draw_output_pills(cr, ["KEY_LEFTCTRL"], size))
    surf, _rect = osd_look._raster(rec, 4.0)   # 4x for sub-pixel precision
    surf.flush()
    w, h = surf.get_width(), surf.get_height()
    px = np.ndarray((h, surf.get_stride() // 4, 4), np.uint8, surf.get_data())[:, :w]
    fg = np.array(theme.load(theme_name).pill_fg[:3]) * 255
    ink = (np.abs(px[..., [2, 1, 0]].astype(float) - fg).sum(axis=2) < 120) & (px[..., 3] > 200)
    cols = np.flatnonzero(ink.any(axis=0))
    # Glyph clusters left to right: the first is ⌃, the next is "C".
    breaks = np.flatnonzero(np.diff(cols) > 2)
    sym = cols[:breaks[0] + 1]
    c = cols[breaks[0] + 1:breaks[1] + 1]

    def mid(span):
        rows = np.flatnonzero(ink[:, span].any(axis=1))
        return (rows[0] + rows[-1]) / 2
    assert abs(mid(sym) - mid(c)) <= 4 * 1.0   # within one logical px
