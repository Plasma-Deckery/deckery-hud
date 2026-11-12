"""B-20: the theme mode's input handling."""

from theme_mode import ThemeMode

NAMES = ["neon", "neon-kraeftig", "ruhig", "modifier"]


def st(*buttons, x=0.0):
    return {"context": {"active_buttons": list(buttons)}, "sticks": {"lstick": {"x": x}}}


def test_dpad_cycles_and_wraps():
    m = ThemeMode(NAMES, "neon", st())
    assert m.feed(st("BTN_DPAD_RIGHT")) == "preview" and m.name == "neon-kraeftig"
    assert m.feed(st("BTN_DPAD_RIGHT")) is None          # held, not a new press
    assert m.feed(st()) is None
    assert m.feed(st("BTN_DPAD_LEFT")) == "preview" and m.name == "neon"
    assert m.feed(st()) is None
    assert m.feed(st("BTN_DPAD_UP")) == "preview" and m.name == "modifier"   # wraps
    assert m.feed(st("BTN_DPAD_UP", "BTN_DPAD_DOWN")) == "preview"
    assert m.name == "neon"   # down pressed while up still held: one step forward


def test_stick_flicks_with_hysteresis():
    m = ThemeMode(NAMES, "ruhig", st())
    assert m.feed(st(x=0.7)) == "preview" and m.name == "modifier"
    assert m.feed(st(x=0.9)) is None
    assert m.feed(st(x=0.4)) is None                     # not back to rest yet
    assert m.feed(st(x=0.8)) is None
    assert m.feed(st(x=0.1)) is None
    assert m.feed(st(x=-0.65)) == "preview" and m.name == "ruhig"


def test_stick_deflected_at_start_waits_for_rest():
    m = ThemeMode(NAMES, "neon", st(x=0.9))
    assert m.feed(st(x=0.9)) is None
    assert m.feed(st(x=0.0)) is None
    assert m.feed(st(x=0.9)) == "preview"


def test_apply_and_cancel():
    m = ThemeMode(NAMES, "neon", st())
    m.feed(st("BTN_DPAD_RIGHT"))
    assert m.feed(st("BTN_SOUTH")) == "apply" and m.name == "neon-kraeftig"
    m = ThemeMode(NAMES, "neon", st())
    assert m.feed(st("BTN_EAST")) == "cancel" and m.original == "neon"


def test_button_down_at_start_needs_a_new_press():
    m = ThemeMode(NAMES, "neon", st("BTN_SOUTH"))
    assert m.feed(st("BTN_SOUTH")) is None
    assert m.feed(st()) is None
    assert m.feed(st("BTN_SOUTH")) == "apply"


def test_unknown_current_and_bad_state():
    m = ThemeMode(NAMES, "gibtsnicht", {})
    assert m.name == "neon"
    assert m.feed({"sticks": {"lstick": {"x": None}}}) is None


def test_panel_text_stands_out_in_every_builtin_theme():
    """The panel is drawn in the previewed theme; Paper's dark text once sat
    on the panel's fixed dark fill and vanished."""
    import cairo
    import numpy as np
    import theme
    from renderer_split import theme_panel
    for name in theme.names()[:7]:
        theme.activate(name)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1280, 800)
        x, y, w, h = theme_panel(cairo.Context(surf), 1280, 800, name, 0, 7)
        surf.flush()
        px = np.ndarray((800, surf.get_stride() // 4, 4), np.uint8, surf.get_data())[:, :1280]
        title = px[int(y + 36):int(y + 56), int(x + 20):int(x + w - 20)]
        luma = (title[..., :3].astype(float) @ (0.0722, 0.7152, 0.2126)) / 255
        assert luma.max() - luma.min() > 0.5, name
    theme.activate(theme.BASE)
