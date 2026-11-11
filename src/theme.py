"""
theme.py — Themes for the split HUD (B-20): one named set of style tokens.

Everything the split renderer, the OSD and the shadows draw in comes from
the active theme instead of a constant in the drawing code: the legend
colour coding, text and outline colours, the glass pill, the shadow preset
with its tint and glow, the font. Tokens are named by role (modifier,
layer, outline, …), not by colour, so a theme can recolour a role without
knowing where it is drawn. Alphas stay in the drawing code — they encode
emphasis (active vs idle), which is design, not theme.

Themes are TOML files. The built-in ones ship in src/themes/; a file of the
same name in ~/.config/deckery-hud/themes/ replaces one, any other name adds
one. A theme names another with `extends` and changes only what it lists.
The default, "neon", is the HUD as it was before themes existed: every
default below is the constant that used to sit in the drawing code, so
its renders are pixel-identical.

    label = "Neon kräftig"          # shown in the theme mode
    extends = "neon"
    order = 20                      # position when cycling (built-ins)

    [colors]                        # "#rrggbb", "#rrggbbaa" or [r, g, b(, a)] in 0..1
    modifier = "#ffca33"

    [modifiers]                     # colour by modifier: L1, R1, "···", Steam, "L1+R1", …
    L1 = "#6aa8ff"

    [pill]
    top = "#ffffffb8"

    [shadow]                        # preset + any shadow.ShadowStyle field
    preset = "hauch-dicht"
    glow_alpha = 0.5

    [font]
    family = "Adwaita Sans"

    [osd]
    animation = "bubble-soft"       # used while [osd] animation = "auto"
    toast_keys = "#b88cff"          # toast colours: keys, command, error

The classic design always draws with the default theme (App pins it).

Pure Python, no GTK.
"""

import dataclasses
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT = "neon"

_BUILTIN_DIR = Path(__file__).resolve().parent / "themes"


def user_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / "deckery-hud" / "themes"


def _warn(msg):
    print(f"deckery-hud theme: {msg}", file=sys.stderr)


@dataclass(frozen=True)
class Theme:
    name: str = DEFAULT
    label: str = "Neon"
    order: int = 0

    # ── Legend colour coding (rgb) ──
    modifier: tuple = (1.0, 0.792, 0.2)    # held modifier, combos it unlocks — amber
    layer: tuple = (0.45, 0.90, 0.82)      # bindings from an app layer — teal
    game: tuple = (0.95, 0.35, 0.78)       # Gaming Mode trigger hint — magenta
    ink: tuple = (1.0, 1.0, 1.0)           # plain legends, button letters, lines
    text: tuple = (0.88, 0.88, 0.88)       # a bound legend at rest
    unbound: tuple = (0.55, 0.55, 0.55)    # "—"
    stick: tuple = (1.0, 0.78, 0.2)        # pad gesture / stick feedback
    status_active: tuple = (0.27, 0.87, 0.44)   # "Controls Active" badge
    status_paused: tuple = (1.0, 0.78, 0.2)     # "Controls Paused" badge
    # Colour by modifier: ((frozenset of modifier keys, rgb), …). Empty: every
    # modifier draws in `modifier`.
    modifiers: tuple = ()

    # ── Shapes (rgba) ──
    outline: tuple = (1.0, 1.0, 1.0, 0.5)
    outline_width: float = 1.3 * 1.5
    active_fill: tuple = (1.0, 1.0, 1.0, 0.58)   # a plain press

    # ── Glass pill (active outputs, OSD) ──
    pill_top: tuple = (1, 1, 1, 0.72)
    pill_bottom: tuple = (0.955, 0.96, 0.975, 0.61)
    pill_sheen: float = 0.13
    pill_fg: tuple = (0.08, 0.08, 0.10, 0.92)
    pill_shadow: float = 1.0       # strength of the pill's own shadow

    # ── Shadow ──
    shadow: str = ""               # shadow.PRESETS name; "" = the default preset
    shadow_tweaks: tuple = ()      # ((ShadowStyle field, value), …) on top

    font: str = "Adwaita Sans"

    # ── OSD ──
    toast_keys: tuple = (0.72, 0.55, 1.0)       # a key tap — lavender
    toast_command: tuple = (0.55, 0.90, 0.55)   # a command — green
    toast_error: tuple = (1.00, 0.45, 0.42)     # a command that did not run — red
    osd_animation: str = ""        # osd_anim.PRESETS name when [osd] animation is "auto"

    # ── derived ──

    @property
    def glass(self):
        """The pill material as helpers._glass_pill takes it."""
        return dict(top=self.pill_top, bottom=self.pill_bottom, sheen=self.pill_sheen)

    def mod_rgb(self, keys=()):
        """Colour for something a modifier did: `keys` are the modifier(s)
        involved — the held set for a combo, the button itself for a
        modifier button. An exact entry wins ("L1+R1"), then the first key
        with an entry of its own, then `modifier`."""
        if self.modifiers and keys:
            ks = frozenset(keys)
            for mk, rgb in self.modifiers:
                if mk == ks:
                    return rgb
            for k in keys:
                for mk, rgb in self.modifiers:
                    if mk == {k}:
                        return rgb
        return self.modifier

    def shadow_style(self):
        return _shadow_style(self.shadow, self.shadow_tweaks)


_style_cache = {}


def _shadow_style(preset, tweaks):
    key = (preset, tweaks)
    hit = _style_cache.get(key)
    if hit is None:
        from shadow import PRESETS, style_from_env
        base = PRESETS[preset] if preset in PRESETS else style_from_env()
        hit = dataclasses.replace(base, **dict(tweaks)) if tweaks else base
        _style_cache[key] = hit
    return hit


# ── Active theme ──────────────────────────────────────────────────────────────

_active = Theme()


def current():
    return _active


def activate(name):
    """Make the theme `name` current (falling back to the default when it
    can't be loaded). Returns True if that changed what is drawn."""
    global _active
    t = load(name)
    if t is None:
        if name != DEFAULT:
            _warn(f"Theme '{name}' nicht gefunden; '{DEFAULT}' gilt")
        t = load(DEFAULT) or Theme()
    changed = t != _active
    _active = t
    return changed


# ── Files ─────────────────────────────────────────────────────────────────────

def _files():
    """name -> path, user files replacing built-ins of the same name."""
    found = {}
    for d in (_BUILTIN_DIR, user_dir()):
        try:
            for p in sorted(d.glob("*.toml")):
                found[p.stem] = p
        except OSError:
            pass
    return found


def names():
    """Every available theme, in cycling order: by `order`, then name."""
    out = []
    for name in _files():
        t = load(name)
        if t is not None:
            out.append(t)
    out.sort(key=lambda t: (t.order, t.name))
    return [t.name for t in out]


def _read(path):
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        _warn(f"{path} nicht lesbar ({e})")
        return None


def load(name, _seen=()):
    """The Theme called `name`, or None if there is no such file or it does
    not parse. A bad value only costs its own key."""
    if name == DEFAULT and DEFAULT not in _files():
        return Theme()
    path = _files().get(name)
    if path is None or name in _seen:
        return None
    data = _read(path)
    if data is None:
        return None
    parent = data.get("extends", DEFAULT if name != DEFAULT else None)
    base = Theme()
    if parent:
        base = load(parent, _seen + (name,))
        if base is None:
            _warn(f"{path.name}: extends '{parent}' nicht gefunden; Standard als Basis")
            base = Theme()
    # `order` belongs to a file, not to what it extends: a theme that doesn't
    # say sorts after the built-ins.
    vals = {"name": name, "label": name, "order": 1000}
    _apply(data, vals, path.name, base)
    return dataclasses.replace(base, **vals)


_COLOR_KEYS = {"modifier", "layer", "game", "ink", "text", "unbound", "stick",
               "status_active", "status_paused", "outline", "active_fill"}
_PILL_KEYS = {"top": "pill_top", "bottom": "pill_bottom", "sheen": "pill_sheen",
              "fg": "pill_fg", "shadow": "pill_shadow"}
_RGBA = {"outline", "active_fill", "pill_top", "pill_bottom", "pill_fg"}


def _apply(data, vals, where, base):
    for key, value in data.items():
        if key == "label" and isinstance(value, str):
            vals["label"] = value
        elif key == "order" and type(value) is int:
            vals["order"] = value
        elif key == "extends":
            pass
        elif key == "colors" and isinstance(value, dict):
            for k, v in value.items():
                if k == "outline_width":
                    _num(vals, "outline_width", v, where)
                elif k in _COLOR_KEYS:
                    _col(vals, k, v, where, k in _RGBA)
                else:
                    _warn(f"{where}: unbekannte Farbe '{k}', ignoriert")
        elif key == "modifiers" and isinstance(value, dict):
            mods = []
            for k, v in value.items():
                keys = _mod_keys(k)
                rgb = _color(v, False)
                if keys is None or rgb is None:
                    _warn(f"{where}: modifiers.{k} ungültig, ignoriert")
                    continue
                mods.append((keys, rgb))
            vals["modifiers"] = tuple(mods)
        elif key == "pill" and isinstance(value, dict):
            for k, v in value.items():
                f = _PILL_KEYS.get(k)
                if f is None:
                    _warn(f"{where}: unbekannter Schlüssel pill.{k}, ignoriert")
                elif f in ("pill_sheen", "pill_shadow"):
                    _num(vals, f, v, where)
                else:
                    _col(vals, f, v, where, True)
        elif key == "shadow" and isinstance(value, dict):
            _shadow(value, vals, where, base)
        elif key == "osd" and isinstance(value, dict):
            _osd(value, vals, where)
        elif key == "font" and isinstance(value, dict):
            fam = value.get("family")
            if isinstance(fam, str) and fam.strip():
                vals["font"] = fam.strip()
        else:
            _warn(f"{where}: unbekannter Schlüssel '{key}', ignoriert")


def _shadow(value, vals, where, base):
    from shadow import PRESETS, ShadowStyle
    fields = {f.name: f for f in dataclasses.fields(ShadowStyle)}
    tweaks = dict(base.shadow_tweaks)
    for k, v in value.items():
        if k == "preset":
            if v in PRESETS or v == "":
                vals["shadow"] = v
                # A new preset starts from its own values, not the parent's tweaks.
                tweaks = {}
            else:
                _warn(f"{where}: Schatten-Preset '{v}' unbekannt, ignoriert")
            continue
        f = fields.get(k)
        if f is None:
            _warn(f"{where}: unbekannter Schlüssel shadow.{k}, ignoriert")
        elif f.type in (bool, "bool"):
            if type(v) is bool:
                tweaks[k] = v
            else:
                _warn(f"{where}: shadow.{k} braucht true/false")
        elif f.type in (str, "str"):
            if isinstance(v, str):
                tweaks[k] = v
        elif type(v) in (int, float):
            tweaks[k] = float(v)
        else:
            _warn(f"{where}: shadow.{k} braucht eine Zahl")
    vals["shadow_tweaks"] = tuple(sorted(tweaks.items()))


def _osd(value, vals, where):
    import osd_anim
    for k, v in value.items():
        if k == "animation":
            if v in osd_anim.PRESETS or v == "":
                vals["osd_animation"] = v
            else:
                _warn(f"{where}: OSD-Animation '{v}' unbekannt, ignoriert")
        elif k in ("toast_keys", "toast_command", "toast_error"):
            _col(vals, k, v, where, False)
        else:
            _warn(f"{where}: unbekannter Schlüssel osd.{k}, ignoriert")


def _num(vals, f, v, where):
    if type(v) in (int, float):
        vals[f] = float(v)
    else:
        _warn(f"{where}: {f} braucht eine Zahl, steht {v!r}")


def _col(vals, f, v, where, rgba):
    c = _color(v, rgba)
    if c is None:
        _warn(f"{where}: Farbe {f} ungültig ({v!r}), ignoriert")
    else:
        vals[f] = c


def _color(v, rgba):
    """'#rrggbb' / '#rrggbbaa' / [r, g, b(, a)] -> a tuple of 3 (or 4 with
    rgba; alpha 1 when not given) floats in 0..1, or None."""
    if isinstance(v, str):
        s = v.strip().lstrip("#")
        if len(s) not in (6, 8):
            return None
        try:
            c = [int(s[i:i + 2], 16) / 255 for i in range(0, len(s), 2)]
        except ValueError:
            return None
    elif isinstance(v, list) and len(v) in (3, 4) and all(type(x) in (int, float) for x in v):
        c = [float(x) for x in v]
        if not all(0 <= x <= 1 for x in c):
            return None
    else:
        return None
    if rgba:
        return tuple(c) if len(c) == 4 else tuple(c) + (1.0,)
    return tuple(c[:3])


# Short names the theme files use for modifier buttons.
_MOD_NAMES = {
    "L1": "BTN_TL", "R1": "BTN_TR", "L2": "BTN_TL2", "R2": "BTN_TR2",
    "L4": "BTN_GRIPL", "L5": "BTN_GRIPL2", "R4": "BTN_GRIPR", "R5": "BTN_GRIPR2",
    "···": "BTN_BASE", "...": "BTN_BASE", "QAM": "BTN_BASE", "Steam": "BTN_MODE",
    "View": "BTN_SELECT", "Menu": "BTN_START", "L3": "BTN_THUMBL", "R3": "BTN_THUMBR",
}


def _mod_keys(name):
    """'L1+R1' -> frozenset({'BTN_TL', 'BTN_TR'}); raw BTN_ names pass."""
    keys = []
    for part in name.split("+"):
        part = part.strip()
        k = _MOD_NAMES.get(part, part if part.startswith(("BTN_", "KEY_")) else None)
        if k is None:
            return None
        keys.append(k)
    return frozenset(keys) if keys else None
