"""B-20: theme files, tokens and the active theme."""

import dataclasses

import pytest

import helpers
import parts  # noqa: F401  (imports theme the way the renderers do)
import settings
import shadow
import theme


@pytest.fixture
def user_themes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = tmp_path / "deckery-hud" / "themes"
    d.mkdir(parents=True)
    yield d
    theme.activate(theme.DEFAULT)


def test_default_is_the_old_constants():
    # Neon keeps every token the drawing code had as a constant; only its
    # shadow is its own (the design pass: "aura").
    t = theme.load(theme.DEFAULT)
    assert t == dataclasses.replace(theme.Theme(), label="Neon", shadow="aura",
                                    text=(1.0, 1.0, 1.0), text_dim=0.0,
                                    shadow_tweaks=t.shadow_tweaks)
    assert t.modifier == helpers.C_MOD
    assert t.layer == helpers.C_LAYER
    assert t.game == helpers.C_GAME
    assert t.glass == helpers.GLASS_PILL
    assert t.pill_fg == helpers.GLASS_PILL_FG
    assert t.shadow_style() == dataclasses.replace(
        shadow.PRESETS["aura"], tint=True, tint_value=0.17, tint_saturation=0.85,
        glow_alpha=0.75, glow_radius=4, glow_neutral=1.0, glow_text=True,
        glow_text_alpha=0.9)
    assert theme.Theme().shadow_style() == shadow.style_from_env()


def test_builtins_in_order():
    names = theme.names()
    assert names[:7] == ["neon", "glass", "paper", "wireframe", "arcade", "terminal", "contrast"]
    for n in names:
        assert theme.load(n) is not None


def test_builtin_presets_parse_cleanly(capsys):
    for n in theme.names():
        theme.load(n)
    assert capsys.readouterr().err == ""


def test_colours_and_modifiers(user_themes):
    (user_themes / "mine.toml").write_text(
        'label = "Meins"\n[colors]\nmodifier = "#ff0000"\noutline = [1, 1, 1, 0.25]\n'
        '[modifiers]\nL1 = "#0000ff"\n"L1+R1" = "#00ff00"\n')
    t = theme.load("mine")
    assert t.label == "Meins"
    assert t.modifier == (1.0, 0.0, 0.0)
    assert t.outline == (1.0, 1.0, 1.0, 0.25)
    assert t.mod_rgb(("BTN_TL",)) == (0.0, 0.0, 1.0)
    assert t.mod_rgb(("BTN_TL", "BTN_TR")) == (0.0, 1.0, 0.0)
    assert t.mod_rgb(("BTN_TR",)) == (1.0, 0.0, 0.0)          # no entry: modifier
    assert t.mod_rgb(("BTN_TR", "BTN_TL")) == (0.0, 1.0, 0.0)  # exact set, any order
    assert t.mod_rgb(("BTN_TR", "BTN_BASE", "BTN_TL")) == (0.0, 0.0, 1.0)
    assert t.mod_rgb() == (1.0, 0.0, 0.0)


def test_extends_and_user_override(user_themes):
    (user_themes / "glass.toml").write_text('label = "My Glass"\n')
    (user_themes / "kind.toml").write_text('extends = "arcade"\n[pill]\nsheen = 0\n')
    assert theme.load("glass").label == "My Glass"
    kind = theme.load("kind")
    base = theme.load("arcade")
    assert kind.pill_sheen == 0.0
    assert kind.layer == base.layer
    assert kind.shadow_style() == base.shadow_style()
    assert kind.order == 1000   # sorts after the built-ins


def test_shadow_tweaks(user_themes):
    (user_themes / "s.toml").write_text(
        '[shadow]\npreset = "dezent"\nglow_alpha = 0.5\ntint = true\n')
    st = theme.load("s").shadow_style()
    assert st == dataclasses.replace(shadow.PRESETS["dezent"], glow_alpha=0.5, tint=True)


def test_bad_values_cost_only_their_key(user_themes, capsys):
    (user_themes / "bad.toml").write_text(
        '[colors]\nmodifier = "red"\nlayer = "#102030"\nnope = "#ffffff"\n'
        '[modifiers]\nZZ = "#ffffff"\n[shadow]\npreset = "gibtsnicht"\nrim_alpha = "x"\n')
    t = theme.load("bad")
    assert t.modifier == theme.Theme().modifier
    assert t.layer == pytest.approx((0x10 / 255, 0x20 / 255, 0x30 / 255))
    assert t.modifiers == ()
    assert t.shadow_style() == theme.load(theme.DEFAULT).shadow_style()
    err = capsys.readouterr().err
    assert "modifier" in err and "nope" in err and "ZZ" in err and "gibtsnicht" in err


def test_broken_file_and_cycle(user_themes):
    (user_themes / "kaputt.toml").write_text("[colors\n")
    (user_themes / "a.toml").write_text('extends = "b"\n')
    (user_themes / "b.toml").write_text('extends = "a"\n')
    assert theme.load("kaputt") is None
    assert theme.load("a").modifier == theme.Theme().modifier   # cycle → default base
    assert "kaputt" not in theme.names()


def test_activate(user_themes):
    assert theme.activate("glass")
    assert theme.current().name == "glass"
    assert not theme.activate("glass")
    theme.activate("gibtsnicht")
    assert theme.current().name == theme.DEFAULT


def test_classic_draws_with_the_builtin_tokens():
    theme.activate("glass")
    assert theme.activate(None)
    assert theme.current() == theme.Theme()
    theme.activate(theme.DEFAULT)


def test_emphasis():
    t = theme.Theme()
    assert t.emph(0.75) == 0.75                     # as the drawing code says
    full = dataclasses.replace(t, text_dim=0.0)
    assert full.emph(0.4) == 1.0 and full.emph(0.9) == 1.0


def test_setting():
    assert settings.Settings().layout.theme == "neon"
    assert "theme = " in settings.template()


def test_osd_tokens(user_themes, capsys):
    import toast
    (user_themes / "o.toml").write_text(
        '[osd]\nanimation = "slide"\ntoast_command = "#00ff00"\nwackel = 1\n')
    t = theme.load("o")
    assert t.osd_animation == "slide"
    assert t.toast_command == (0.0, 1.0, 0.0)
    assert "wackel" in capsys.readouterr().err
    assert theme.load("glass").osd_animation == "bubble-soft"
    theme.activate("o")
    assert toast.toast_label({"type": "command", "value": ["x"]})[1] == (0.0, 1.0, 0.0)


def test_osd_sprites_key_on_theme(user_themes):
    import osd_look
    style = theme.current().shadow_style()
    a = osd_look.pills_sprite(("Ctrl",), style)
    theme.activate("arcade")
    b = osd_look.pills_sprite(("Ctrl",), style)
    assert a is not b


def test_component_sections(user_themes, capsys):
    (user_themes / "c.toml").write_text(
        '[shape]\nstyle = "double"\nwidth = 2\nfill = "#10203040"\nwobble = 1\n'
        '[stick]\ncap = "#ffffff"\n[callout]\ndot = 4\n'
        '[text]\ntransform = "upper"\nweight = "Light"\nscale = 1.1\n'
        '[pill]\nborder = "#ffffff80"\n[shadow]\nshadow_rgb = "#102030"\noffset_y = 3\n')
    t = theme.load("c")
    assert t.outline_style == "double" and t.outline_width == 2.0
    assert t.shape_fill[3] == pytest.approx(0x40 / 255)
    assert t.stick_cap == (1.0, 1.0, 1.0, 1.0)
    assert t.dot_radius == 4.0
    assert (t.text_transform, t.text_weight, t.text_scale) == ("upper", "Light", 1.1)
    assert t.pill_border[3] == pytest.approx(0x80 / 255)
    st = t.shadow_style()
    assert st.offset_y == 3.0 and st.shadow_rgb == pytest.approx((0x10 / 255, 0x20 / 255, 0x30 / 255))
    assert "wobble" in capsys.readouterr().err


def test_bad_choice_in_section(user_themes, capsys):
    (user_themes / "d.toml").write_text('[shape]\nstyle = "zickzack"\n')
    assert theme.load("d").outline_style == "solid"
    assert "zickzack" in capsys.readouterr().err


@pytest.mark.parametrize("style", ["solid", "dashed", "double", "none"])
def test_outline_styles_draw(user_themes, style):
    import cairo
    import parts
    (user_themes / "o.toml").write_text(f'[shape]\nstyle = "{style}"\nwidth = 3\n')
    theme.activate("o")
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 60)
    cr = cairo.Context(surf)
    cr.set_source_rgb(0, 0, 1)
    cr.paint()
    cr.rectangle(15, 15, 30, 30)
    parts.stroke_outline(cr)
    surf.flush()
    px = bytes(surf.get_data())
    stride = surf.get_stride()
    at = lambda x, y: px[y * stride + x * 4: y * stride + x * 4 + 4]
    assert at(5, 5) == bytes((255, 0, 0, 255))          # outside: untouched
    if style == "none":
        assert at(15, 30) == bytes((255, 0, 0, 255))
    elif style == "double":
        assert at(15, 30) == bytes((255, 0, 0, 255))     # the gap shows what is under it
        assert at(18, 30) != bytes((255, 0, 0, 255))
    else:
        assert at(19, 15) != bytes((255, 0, 0, 255))     # the start of the top edge


def test_shadow_offset_moves_the_layers():
    import cairo
    spec = shadow.GroupShadowSpec(rrects=((40, 40, 60, 30, 8),), ink=(40, 40, 60, 30))
    base = dataclasses.replace(shadow.PRESETS["dezent"])
    off = dataclasses.replace(base, offset_x=3.0, offset_y=4.0)
    a, ab = shadow.group_shadow_layers(spec, base, None, None)
    b, bb = shadow.group_shadow_layers(spec, off, None, None)
    assert (b[1] - a[1], b[2] - a[2]) == (3.0, 4.0)
    assert (bb[1] - ab[1], bb[2] - ab[2]) == (3.0, 4.0)


def test_text_spacing_case_and_dim(user_themes):
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
    cr = cairo.Context(surf)
    w0, _ = helpers._txt_size(cr, "abc", 12)
    (user_themes / "t.toml").write_text(
        '[text]\ntransform = "lower"\nspacing = 3\ndim = 0.2\nbold = "Heavy"\n')
    theme.activate("t")
    t = theme.current()
    assert (t.text_dim, t.text_bold) == (0.2, "Heavy")
    assert helpers._case("ABC") == "abc"
    assert helpers._txt_size(cr, "abc", 12)[0] >= w0 + 6
    assert "Heavy" in helpers._font(12, True).to_string()


def test_text_tokens():
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
    cr = cairo.Context(surf)
    w0, h0 = helpers._txt_size(cr, "abc", 12)
    try:
        theme._active = dataclasses.replace(theme.Theme(), text_transform="upper", text_scale=1.5)
        w1, h1 = helpers._txt_size(cr, "abc", 12)
        assert helpers._case("abc") == "ABC"
        assert h1 > h0 and w1 > w0
    finally:
        theme.activate(theme.DEFAULT)


# ── The gesture connector (B-12) ──────────────────────────────────────────

def test_connector_tokens(user_themes):
    (user_themes / "kabel.toml").write_text(
        '[connector]\ncolor = "#00ff00"\nalpha = 0.5\nwidth = 3\nstyle = "dashed"\n'
        'glow = 0.4\nglow_radius = 9\nshadow = false\n'
        'label_color = "#0000ff"\nlabel_size = 15\nlabel_glow = true\n')
    t = theme.load("kabel")
    assert (t.connector_color, t.connector_alpha, t.connector_width) == ((0.0, 1.0, 0.0), 0.5, 3.0)
    assert (t.connector_style, t.connector_glow, t.connector_glow_radius) == ("dashed", 0.4, 9.0)
    assert t.connector_shadow is False and t.connector_label_glow is True
    assert (t.connector_label_color, t.connector_label_size) == ((0.0, 0.0, 1.0), 15.0)


def test_connector_bad_values_cost_only_their_key(user_themes, capsys):
    (user_themes / "kaputt.toml").write_text(
        '[connector]\nshadow = 1\nstyle = "zickzack"\nwidth = "dick"\nglow = 0.3\n')
    t = theme.load("kaputt")
    d = theme.Theme()
    assert (t.connector_shadow, t.connector_style, t.connector_width) == \
        (d.connector_shadow, d.connector_style, d.connector_width)
    assert t.connector_glow == 0.3
    assert len(capsys.readouterr().err.strip().splitlines()) == 3


def test_neon_connector_is_an_amber_power_line():
    """Live round 3: "power connection line" — amber, glowing, on a shadow."""
    t = theme.Theme()
    assert t.connector_line_rgb() == t.modifier
    assert t.connector_glow > 0 and t.connector_shadow
    assert t.connector_label_rgb() == t.modifier


# ── Output pill tokens (B-26) ───────────────────────────────────────────────

_PILL_FIELDS = ("pill_top", "pill_bottom", "pill_sheen", "pill_fg", "pill_icon", "pill_weight",
                "pill_radius", "pill_border", "pill_border_width", "pill_padx", "pill_gap",
                "pill_sep", "pill_shadow", "pill_shadow_color")


def test_pill_tokens(user_themes, capsys):
    (user_themes / "p.toml").write_text(
        '[pill]\nicon = "#ff0000"\nweight = "Heavy"\nradius = 3\nborder_width = 2\n'
        'padx = 9\ngap = 6\nsep = "#00ff0080"\nshadow_color = "#0000ff"\nwackel = 1\n'
        'gap_x = "breit"\n')
    t = theme.load("p")
    assert t.pill_icon == (1.0, 0.0, 0.0, 1.0)
    assert (t.pill_weight, t.pill_radius, t.pill_border_width) == ("Heavy", 3.0, 2.0)
    assert (t.pill_padx, t.pill_gap) == (9.0, 6.0)
    assert t.pill_sep[3] == pytest.approx(0x80 / 255)
    assert t.pill_shadow_color == (0.0, 0.0, 1.0)      # a tint: rgb
    err = capsys.readouterr().err
    assert "wackel" in err and "gap_x" in err


def test_every_builtin_has_its_own_pill_look():
    looks = {n: tuple(getattr(theme.load(n), f) for f in _PILL_FIELDS) for n in theme.names()[:7]}
    assert len(set(looks.values())) == 7
    # Neon keeps the pills the user signed off on: every pill token at its default.
    assert looks["neon"] == tuple(getattr(theme.Theme(), f) for f in _PILL_FIELDS)


@pytest.mark.parametrize("radius,corner_filled", [(-1, False), (0, True)])
def test_pill_radius_shapes_the_corners(user_themes, radius, corner_filled):
    import osd_look
    (user_themes / "r.toml").write_text(f'[pill]\nradius = {radius}\ntop = "#ffffff"\nbottom = "#ffffff"\n')
    theme.activate("r")
    _rec, cap = osd_look._record(lambda cr: osd_look.draw_output_pills(cr, ["KEY_C"], 11))
    x, y, w, h = cap.glass_boxes[0]
    rec, _cap = osd_look._record(lambda cr: osd_look.draw_output_pills(cr, ["KEY_C"], 11))
    surf, (sx, sy, _w, _h) = osd_look._raster(rec, 1.0)
    surf.flush()
    stride = surf.get_stride()
    alpha = surf.get_data()[int(y + 1 - sy) * stride + int(x + 1 - sx) * 4 + 3]
    assert (alpha > 128) is corner_filled


def test_pills_are_round_except_in_terminal():
    """The design language is round and colourful; only Terminal's square
    character cells are the deliberate exception."""
    for n in theme.names()[:7]:
        assert (theme.load(n).pill_radius < 0) is (n != "terminal"), n


def test_renamed_builtins_load_by_their_old_ids():
    """2.0.0~beta1 renamed glas/papier/kontrast; a saved old id still works."""
    for old, new in theme.RENAMED.items():
        assert theme.resolve(old) == new
        assert theme.load(old).name == new
    assert theme.resolve("neon") == "neon"


def test_a_user_theme_keeps_an_old_id(user_themes):
    (user_themes / "glas.toml").write_text('label = "Mine"\n')
    assert theme.resolve("glas") == "glas"
    assert theme.load("glas").label == "Mine"


def test_backdrop_section(user_themes):
    (user_themes / "dim.toml").write_text(
        '[backdrop]\ncolor = "#102030"\nopacity = 0.4\nvignette = 0.5\n')
    t = theme.load("dim")
    assert t.backdrop_color == (0x10 / 255, 0x20 / 255, 0x30 / 255)
    assert (t.backdrop_opacity, t.backdrop_vignette) == (0.4, 0.5)
    assert theme.load("wireframe").backdrop_opacity > 0
    assert theme.load("neon").backdrop_opacity == 0
    assert theme.load("contrast").backdrop_opacity == 0


def test_every_builtin_is_rounded_but_terminal():
    """The design language is round; Terminal alone keeps hard corners."""
    for name in theme.names()[:7]:
        style = theme.load(name).shadow_style()
        if name == "terminal":
            continue
        assert style.plate_shape == "round", name
        assert style.plate_radius < 0 or style.plate_radius >= 6, name
