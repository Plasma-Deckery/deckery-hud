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
    t = theme.load(theme.DEFAULT)
    assert t == dataclasses.replace(theme.Theme(), label="Neon")
    assert t.modifier == helpers.C_MOD
    assert t.layer == helpers.C_LAYER
    assert t.game == helpers.C_GAME
    assert t.glass == helpers.GLASS_PILL
    assert t.pill_fg == helpers.GLASS_PILL_FG
    assert t.shadow_style() == shadow.style_from_env()


def test_builtins_in_order():
    names = theme.names()
    assert names[:4] == ["neon", "neon-kraeftig", "ruhig", "modifier"]
    for n in names:
        assert theme.load(n) is not None


def test_builtin_presets_parse_cleanly(capsys):
    for n in ("neon-kraeftig", "ruhig", "modifier"):
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
    (user_themes / "ruhig.toml").write_text('label = "Mein Ruhig"\n')
    (user_themes / "kind.toml").write_text('extends = "neon-kraeftig"\n[pill]\nsheen = 0\n')
    assert theme.load("ruhig").label == "Mein Ruhig"
    kind = theme.load("kind")
    base = theme.load("neon-kraeftig")
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
    assert t.shadow_style() == theme.Theme().shadow_style()
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
    assert theme.activate("ruhig")
    assert theme.current().name == "ruhig"
    assert not theme.activate("ruhig")
    theme.activate("gibtsnicht")
    assert theme.current().name == theme.DEFAULT


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
    assert theme.load("ruhig").osd_animation == "bubble-soft"
    theme.activate("o")
    assert toast.toast_label({"type": "command", "value": ["x"]})[1] == (0.0, 1.0, 0.0)


def test_osd_sprites_key_on_theme(user_themes):
    import osd_look
    style = theme.current().shadow_style()
    a = osd_look.pills_sprite(("Ctrl",), style)
    theme.activate("neon-kraeftig")
    b = osd_look.pills_sprite(("Ctrl",), style)
    assert a is not b
