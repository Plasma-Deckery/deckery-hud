"""
settings.py — the HUD's settings file: description, loading, template, writing.

Lives at $XDG_CONFIG_HOME/deckery-hud/settings.toml (~/.config/deckery-hud/).
Not in ~/.config/deckery/: makima loads every *.toml there as a binding config,
and preferences.toml there is makima's own and rewritten by it.

The file is shared between the user and the HUD. The user edits it by hand;
the HUD writes single keys into it when a button makes a choice (remember()),
keeping the user's comments and order. Nothing else decides a setting — no
environment variable, no second state file. A key missing from the file means
its default from the dataclasses below.

Pure Python, no GTK: app.py does the watching and applies changes.

── Adding a feature's settings ─────────────────────────────────────────────────
1. A frozen dataclass with flat fields (bool / int / float / str). Each field
   gets a default and `metadata=_meta("<one line of help>")`, plus
   `choices=(...)` for a fixed set of strings or `minimum=` for a lower bound.
   The class docstring is the section's help line.
2. A field for it in `Settings` — its name is the [section] in the file.
3. Its reaction to a change in App._apply_settings.
Validation, the template and the file watching need nothing else.
"""

import dataclasses
import json
import os
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import osd_anim


def _meta(help, choices=None, minimum=None):
    return {"help": help, "choices": choices, "minimum": minimum}


# ── Description ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LayoutSettings:
    """Aussehen des HUD."""
    design: str = field(default="classic", metadata=_meta(
        'Welches Design: "split" (neu) oder "classic".',
        choices=("classic", "split")))
    theme: str = field(default="neon", metadata=_meta(
        'Farben und Effekte im Split-Design: "neon", "neon-kraeftig", "ruhig", '
        '"modifier" oder eigene aus ~/.config/deckery-hud/themes/.'))


@dataclass(frozen=True)
class OsdSettings:
    """Anzeige am Bildschirmrand."""
    enabled: bool = field(default=True, metadata=_meta(
        "Kleine Anzeige am Bildschirmrand, solange das HUD zu ist."))
    animation: str = field(default="auto", metadata=_meta(
        'Wie Meldungen und Ausgabe-Pillen kommen und gehen: "pop" (ploppt unten '
        'in der Mitte auf), "bubble-soft" (weicher, ohne Überschwingen), "slide" '
        '(gleitet nach oben) oder "auto" (pop im Split-Design, slide in Classic).',
        choices=osd_anim.CHOICES))


@dataclass(frozen=True)
class RevealSettings:
    """Gruppen einzeln einblenden, ohne das volle HUD zu öffnen."""
    enabled: bool = field(default=True, metadata=_meta(
        "Hauptschalter für das einzelne Einblenden."))
    pad_enabled: bool = field(default=True, metadata=_meta(
        "Ein länger benutztes Trackpad blendet sich mit Label ein."))
    gesture_enabled: bool = field(default=True, metadata=_meta(
        "Beide Pads gleichzeitig berührt (Geste) blendet beide ein."))
    modifier_enabled: bool = field(default=True, metadata=_meta(
        "Ein länger gehaltener Modifier zeigt die Belegungen seiner Ebene."))
    breadcrumbs: bool = field(default=True, metadata=_meta(
        "Mit jedem einzeln eingeblendeten Element auch die Brotkrumen-Zeile der "
        "Mitte zeigen: in welcher Anwendung du bist, und was die Farben heißen."))
    hold_ms: int = field(default=750, metadata=_meta(
        "Wie lange Pad oder Modifier benutzt werden, bis sie erscheinen (ms).",
        minimum=1))
    gesture_hold_ms: int = field(default=750, metadata=_meta(
        "Wie lange die Geste gehalten wird, bis beide Pads erscheinen (ms).",
        minimum=1))
    release_ms: int = field(default=250, metadata=_meta(
        "Loslassen blendet sofort aus; wer innerhalb dieser Zeit wieder drückt oder "
        "berührt, sieht die Gruppe gleich wieder, ohne neue Haltezeit. War sie schon "
        "zu sehen, gilt das noch bis Ausblenden plus Haltezeit (ms).",
        minimum=1))
    slide_ms: int = field(default=260, metadata=_meta(
        "Dauer des Hereinfahrens, wenn das volle HUD auf- oder zugeht (ms).",
        minimum=1))
    fade_in_ms: int = field(default=200, metadata=_meta(
        "Dauer des Einblendens (ms).", minimum=1))
    fade_out_ms: int = field(default=300, metadata=_meta(
        "Dauer des Ausblendens (ms).", minimum=1))
    crossfade_ms: int = field(default=200, metadata=_meta(
        "Überblenden, wenn eine sichtbare Gruppe ihren Inhalt wechselt (ms).",
        minimum=1))


@dataclass(frozen=True)
class DebugSettings:
    """Fehlersuche."""
    enabled: bool = field(default=False, metadata=_meta(
        "Zusätzliche Diagnose-Ausgaben im Log."))


@dataclass(frozen=True)
class Settings:
    layout: LayoutSettings = LayoutSettings()
    osd: OsdSettings = OsdSettings()
    reveal: RevealSettings = RevealSettings()
    debug: DebugSettings = DebugSettings()


_HEADER = """\
# Deckery HUD — Einstellungen.
# Zeilen mit # sind aus und zeigen den Standardwert. Zum Ändern das #
# entfernen und den Wert anpassen. Änderungen wirken sofort.
"""


# ── Paths ─────────────────────────────────────────────────────────────────────

def settings_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / "deckery-hud" / "settings.toml"


def _warn(msg):
    print(f"deckery-hud settings: {msg}", file=sys.stderr)


# debug.enabled, readable from anywhere without a handle on the App (diagnostic
# output sits deep in the renderers). App keeps it in step with the file.
_debug = False


def debug_enabled():
    return _debug


def dbg(msg):
    """Diagnostic line for the journal, only with [debug] enabled. Errors and
    tracebacks print unconditionally; this is for timing and cache chatter."""
    if _debug:
        print(f"[deckery-hud] {msg}", flush=True)


def _set_debug(on):
    global _debug
    _debug = on


# ── Validation ────────────────────────────────────────────────────────────────

def _problem(f, value):
    """Why `value` is not acceptable for dataclass field `f`, or None if it is."""
    # bool is a subclass of int; `enabled = 1` or `hold_ms = true` is a mistake,
    # not a value. An int for a float field is fine.
    if f.type is bool:
        ok = type(value) is bool
    elif f.type is int:
        ok = type(value) is int
    elif f.type is float:
        ok = type(value) in (int, float)
    else:
        ok = type(value) is str
    if not ok:
        return f"erwartet {f.type.__name__}, steht {value!r}"
    choices = f.metadata.get("choices")
    if choices and value not in choices:
        return f"erlaubt: {', '.join(choices)}; steht {value!r}"
    minimum = f.metadata.get("minimum")
    if minimum is not None and value < minimum:
        return f"mindestens {minimum}, steht {value!r}"
    return None


def _section_fields():
    """(section name, section class) for every section in Settings."""
    return [(s.name, s.default.__class__) for s in dataclasses.fields(Settings)]


# ── Loading ───────────────────────────────────────────────────────────────────

def load(path=None, previous=None):
    """Read the file and return a complete Settings, fresh on every call.

    A missing or empty file gives the defaults. A file that cannot be parsed
    gives `previous` (the values in force so far) or, without one, the
    defaults. A single bad value only costs its own key.
    """
    path = Path(path) if path else settings_path()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        kept = "bisherige Werte bleiben" if previous else "Standardwerte gelten"
        _warn(f"{path} nicht lesbar ({e}); {kept}")
        return previous if previous is not None else Settings()

    known = dict(_section_fields())
    for name in data:
        if name not in known:
            _warn(f"unbekannte Sektion oder Schlüssel '{name}', ignoriert")

    sections = {}
    for name, cls in known.items():
        given = data.get(name, {})
        if not isinstance(given, dict):
            _warn(f"'{name}' muss eine Sektion [{name}] sein, ignoriert")
            given = {}
        fields_by_name = {f.name: f for f in dataclasses.fields(cls)}
        values = {}
        for key, value in given.items():
            f = fields_by_name.get(key)
            if f is None:
                _warn(f"unbekannter Schlüssel '{name}.{key}', ignoriert")
                continue
            problem = _problem(f, value)
            if problem:
                _warn(f"'{name}.{key}': {problem}; Standard {f.default!r} gilt")
                continue
            values[key] = value
        sections[name] = cls(**values)
    return Settings(**sections)


def diff(old, new):
    """Keys ("section.field") whose value differs between two Settings."""
    changed = set()
    for name, cls in _section_fields():
        a, b = getattr(old, name), getattr(new, name)
        for f in dataclasses.fields(cls):
            if getattr(a, f.name) != getattr(b, f.name):
                changed.add(f"{name}.{f.name}")
    return changed


# ── Template ──────────────────────────────────────────────────────────────────

def _toml_literal(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def template():
    """The file written on first start: every setting commented out at its default."""
    lines = [_HEADER]
    for name, cls in _section_fields():
        lines.append(f"[{name}]")
        lines.append(f"# {cls.__doc__}")
        for f in dataclasses.fields(cls):
            lines.append(f"# {f.metadata['help']}")
            lines.append(f"# {f.name} = {_toml_literal(f.default)}")
        lines.append("")
    return "\n".join(lines)


def ensure_file(path=None):
    """Write the template if the file does not exist. Never touches an existing one."""
    path = Path(path) if path else settings_path()
    if path.exists():
        return
    if path.is_symlink():
        # A link whose target is not there yet (a dotfiles checkout still
        # missing): writing a template over it would cut it loose for good.
        _warn(f"{path} zeigt auf eine fehlende Datei; keine Vorlage angelegt")
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, template())
    except OSError as e:
        _warn(f"Vorlage {path} nicht angelegt ({e}); Standardwerte gelten")


# ── Writing ───────────────────────────────────────────────────────────────────

def remember(key, value, path=None):
    """Set one key ("section.field") in the file, keeping everything else in it.

    Raises ValueError for a key or value load() would reject — that is a bug
    in the caller, not something the user did. Returns False (with a warning)
    when the choice could not be saved: the file does not parse, tomlkit is
    missing, or writing failed. The running HUD keeps the choice either way;
    it just does not survive a restart.
    """
    section, _, name = key.partition(".")
    cls = dict(_section_fields()).get(section)
    f = {f.name: f for f in dataclasses.fields(cls)}.get(name) if cls else None
    if f is None:
        raise ValueError(f"unbekannte Einstellung {key!r}")
    problem = _problem(f, value)
    if problem:
        raise ValueError(f"{key}: {problem}")

    path = Path(path) if path else settings_path()
    if path.is_symlink() and not path.exists():
        _warn(f"{path} zeigt auf eine fehlende Datei; {key} nicht gespeichert")
        return False
    # Write the link's target, not the link: replacing the link with a regular
    # file would silently take the file out of the user's dotfiles.
    path = Path(os.path.realpath(path))
    try:
        # Only needed here: loading works without it, so a missing package
        # costs saving a choice, never starting the HUD.
        import tomlkit
    except ImportError:
        _warn(f"tomlkit fehlt, {key} nicht gespeichert")
        return False
    try:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = template()
        doc = tomlkit.parse(text)
        table = doc.get(section)
        if table is None:
            table = tomlkit.table()
            doc.add(section, table)
        elif not isinstance(table, dict):
            _warn(f"'{section}' ist keine Sektion, {key} nicht gespeichert")
            return False
        table[name] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, tomlkit.dumps(doc))
    except tomlkit.exceptions.TOMLKitError as e:
        _warn(f"{path} nicht lesbar ({e}); {key} nicht gespeichert")
        return False
    except (OSError, UnicodeDecodeError) as e:
        _warn(f"{path} nicht geschrieben ({e}); {key} nicht gespeichert")
        return False
    return True


def _write_atomic(path, text):
    """Write via a temporary file in the same directory and rename, so a reader
    (the file monitor, an editor) never sees a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
    try:
        # mkstemp makes 0600; keep the existing file's mode, or give a new one
        # what any other file the user creates would get.
        try:
            mode = os.stat(path).st_mode & 0o777
        except FileNotFoundError:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
