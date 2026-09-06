# Makima State Contract — HUD-seitige Erwartungen

Datei: `/tmp/makima-state.json`

---

## Gesamtstruktur (Ist-Stand)

```json
{
  "lifecycle":           "ready",
  "errors":              {},
  "configs":             [ { "name": "Steam Deck", "kind": "base", ... } ],
  "context":             { ... },
  "bindings":            { "BTN_X": { "action": [], "kind": "remap", "label": null, "origin": "Steam Deck", "silent": false } },
  "modifier_active":     { "BTN_X": { "action": [], ... } },
  "last_action":         { "type": "keys", "value": [], "ts": 0.0 },
  "gaming_mode_trigger": { "key": "BTN_BASE", "label": "Gaming Mode" },
  "trackpads":           { "left": { ... }, "right": { ... }, "gesture": { ... } },
  "sticks":              { "lstick": { ... }, "rstick": { ... } },
  "imu":                 { "x": 0.0, "y": 0.0 }
}
```

Die Datei entsteht aus zwei Quellen, was erklärt, warum manche Felder immer da
sind und andere nicht:

- **`state_writer.rs`** besitzt die Datei und schreibt `lifecycle`, `errors` und
  `configs` — **immer**, auch wenn gar kein Gerät verbunden ist.
- **`state_export.rs`** (via `event_reader.rs`) liefert den Event-Snapshot:
  `context`, `bindings`, `modifier_active`, `last_action`, `gaming_mode_trigger`,
  `trackpads`, `sticks`, `imu`. Der Writer merged ihn flach auf oberster Ebene
  ein. Ohne aktives Gerät fehlen diese Felder komplett.

**Ein HUD muss also damit rechnen, dass alles außer `lifecycle`, `errors` und
`configs` fehlen kann.**

Geschrieben wird bei *jedem* Event, atomar über `rename()` — deshalb wird
`/tmp/` überwacht und nicht die Datei selbst (siehe `info.md`).

---

## `context`

| Feld                  | Typ            | Beschreibung |
|-----------------------|----------------|--------------|
| `config_stack`        | `string[]`     | Aktive Config-Ebenen, z.B. `["Steam Deck", "Firefox"]`. Index 0 ist immer die Base-Config |
| `active_app`          | `string`       | `config_stack[1]`, oder `"default"` wenn keine App-Config aktiv ist. Reine Bequemlichkeit — steht schon im Stack |
| `held_modifiers`      | `string[]`     | Gerade gehaltene Modifier-Buttons, z.B. `["BTN_TL"]`. **Nur makimas eigene Input-Modifier** — virtuelle (Hint-)Modifier tauchen hier nie auf |
| `active_buttons`      | `string[]`     | Alle gerade physisch gedrückten Buttons |
| `active_outputs`      | `object[]`     | Aggregierte evdev-Codes die gerade gehalten werden, als `{ "key": "KEY_LEFTCTRL", "silent": false }`. Sortiert nach Modifier-Rang, dann alphabetisch |
| `available_modifiers` | `object`       | Modifier-Buttons die im aktuellen Zustand als nächster Schritt sinnvoll wären. Key = Button, Value = Objekt (siehe unten). Leer (`{}`) wenn keine weiteren Modifier existieren |
| `paused`              | `bool`         | Makima pausiert (HUD übernimmt Input) |
| `gaming_mode`         | `bool`         | Gaming Mode aktiv — Remapping komplett abgeschaltet, damit Deckery und Spiel-Input nicht kollidieren |
| `analog_state_export` | `bool`         | Ob makima gerade Analog-Daten mitschreibt (siehe `sticks` / `trackpads` / `imu`) |
| `layout`              | `int`          | Intern; HUD ignoriert dieses Feld |

`silent` in `active_outputs` bedeutet: der Backend liefert den Key trotzdem mit,
markiert ihn aber als „nicht anzeigenswert" — das HUD entscheidet, ob es ihn
ausblendet oder nur dimmt. Weggelassen wird er vom Backend nie.

---

## `bindings[key]`

| Feld       | Typ            | Beschreibung |
|------------|----------------|--------------|
| `action`   | `string[]`     | evdev-Codes oder Shell-Befehle der Aktion |
| `kind`     | `string`       | `"remap"` · `"command"` · `"movement"` · `"hint"` |
| `label`    | `string\|null` | Optionaler Freitext-Label (HUD nutzt ihn statt `_fmt(action)` wenn gesetzt) |
| `origin`   | `string`       | Name der Config-Ebene, aus der die Binding stammt |
| `silent`   | `bool`         | `true` wenn die Aktion nicht als OSD-Toast gemeldet werden soll |
| `no_pause` | `bool`         | `true` wenn die Binding auch im Pause-Modus ausgeführt wird (nur bei `kind: "command"`) |

Schema identisch für `modifier_active`.

### `kind: "hint"`

Ein Hint ist ein reines Anzeige-Label aus dem `[hints]`-Block einer Config. Er
erzeugt **keine** Binding und ändert nichts am Event-Pfad — die Tastenkombination
funktionierte schon vorher, war nur unsichtbar.

Zwei Formen, die sich darin unterscheiden, wo sie landen:

- **Mit Modifier** (`KEY_LEFTCTRL-KEY_UP`) → `modifier_active`, mit `"action": []`.
  Nur wenn dort keine echte Binding steht: eine echte Binding gewinnt immer.
- **Ohne Modifier** (`KEY_ENTER`) → `bindings`. Überschreibt `label`, `origin` und
  `kind` eines bestehenden Eintrags und **lässt `action` unangetastet** — die
  Aktion bleibt der Fallback-Text des HUD und hält `active_outputs` ehrlich. Auf
  einem Button ganz ohne Binding entsteht ein neuer Eintrag mit `"action": []`.

`origin` bezeichnet bei einem Hint die Herkunft des **Labels**, nicht die der
Aktion. Bei der modifierlosen Form kann `action` also weiter aus der Base-Config
stammen, während `origin` die App-Config nennt.

**HUD-Nutzung:** `kind == "hint"` wird von der Amber-Stufe ausgenommen. Hints
folgen zwar der Modifier-Mechanik — ein gehaltener Button deckt sie auf — aber es
liegt keine Binding dahinter, das Amber-Signal „hier feuert eine Combo" wäre
gelogen. Sie bleiben teal ohne Unterstreichung. Ausnahme: ist der Button selbst
ein gehaltener Modifier, bleibt sein Amber bestehen.

---

## `last_action`

Fire-and-Forget. Vom Backend beim Press-Event geschrieben, nie gelöscht —
HUD blendet anhand von `ts` nach 1,5 s aus.

```json
"last_action": {
  "type":  "keys",
  "value": ["KEY_LEFTCTRL", "KEY_PAGEDOWN"],
  "label": "Ctrl+PgDn",
  "ts":    1748476800.123
}
```

| Feld    | Typ     | Beschreibung |
|---------|---------|--------------|
| `type`   | `string` | `"keys"` · `"command"` · `"exec"` |
| `value`  | `string\|string[]` | Keys-Liste, Shell-String, oder argv |
| `label`  | `string\|null` | Optional. Lesbarer Name; HUD bevorzugt ihn über `_fmt(value)` |
| `ts`     | `float` | Unix-Timestamp (Sekunden) des Press-Events |
| `silent` | `bool`  | `true` → Toast unterdrücken. Der Eintrag wird trotzdem geschrieben, damit ein Consumer die Aktion sieht, ohne sie anzeigen zu müssen |

Hints erzeugen derzeit **kein** `last_action`. Wer R5+Up drückt, löst das
Base-Remap aus; der Hint selbst ist nur ein Label und taucht hier nicht auf.

---

## `context.available_modifiers`

Modifier-Buttons, die im aktuellen Zustand als nächster Schritt mindestens eine
Combo-Binding freischalten **oder** mindestens einen Hint aufdecken würden.

```json
"context": {
  "available_modifiers": {
    "BTN_TL":      { "has_app_combos": true },
    "BTN_MODE":    { "has_app_combos": false },
    "BTN_GRIPR2":  { "has_app_combos": true, "virtual": true }
  }
}
```

| Feld             | Typ    | Beschreibung |
|------------------|--------|--------------|
| `has_app_combos` | `bool` | Mindestens eines der Dinge hinter diesem Button stammt aus einer App-Config, nicht aus der Base |
| `virtual`        | `bool` | Nur vorhanden und `true` bei Hint-Modifiern: hinter dem Button liegen ausschließlich Labels, keine Bindings |

**Verhalten:**
- Kein Modifier gehalten → alle Modifier die in irgendeiner Combo vorkommen
  (auch wenn sie einen weiteren Modifier benötigen — für Discoverability)
- L1 gehalten → Modifier die zusammen mit L1 eine Combo freischalten (z.B. BTN_TR wenn L1+R1+* existiert)
- Leer (`{}`) wenn im aktuellen Zustand keine weiteren Modifier sinnvoll sind

Ein *virtueller* Modifier ist ein Button, den makima gar nicht als Modifier kennt
— er wird aus `held_keys` erkannt, weil ein Hint ihn nennt. Er taucht deshalb
**nicht** in `held_modifiers` auf; das Feld bleibt makimas eigenen
Input-Modifiern vorbehalten.

**HUD-Nutzung:** Buttons aus dieser Liste, die *nicht* in `held_modifiers` sind,
bekommen in der Callout-Legende eine kleine Raute als Discoverable-Indikator.
Sie verschwindet sobald der Modifier gehalten wird (dann wird die ganze Zeile amber).

- Füllung amber = echter Modifier, teal = `virtual`
- Amber Umrandung bei `has_app_combos` — bei `virtual` übersprungen, unter teal
  Füllung trägt sie keine Information. Siehe
  [Issue #19](https://github.com/Plasma-Deckery/deckery-hud/issues/19): teal
  bedeutet sonst überall „App-Ebene", hier aber „virtuell".

---

## `modifier_active`

Wird von makima befüllt, wenn mindestens ein Modifier gehalten wird.
Enthält die resultierenden Bindings für den aktuellen Modifier-State.
Schema identisch zu `bindings`.

Eine Combo erscheint nur, wenn die gehaltene Menge *exakt* ihr Modifier-Set ist —
Längengleichheit plus Teilmenge. `KEY_LEFTCTRL-KEY_M` verschwindet also, sobald
zusätzlich Shift gehalten wird. Dieselbe Regel gilt für Hints, damit das HUD nie
etwas anzeigt, was nicht feuern würde.

---

## `lifecycle`

```json
"lifecycle": "ready"
```

| Wert               | Bedeutung |
|--------------------|-----------|
| `"starting"`       | Makima bootet. Wird geschrieben bevor irgendein Kommando eintrifft, damit ein Consumer nie eine veraltete Datei liest |
| `"reinitializing"` | Geräte werden neu eingelesen (Reconnect, Config-Reload) |
| `"ready"`          | Betriebsbereit. Sagt **nicht**, dass ein Gerät verbunden ist — dafür siehe `errors` |

---

## `errors`

Objekt, keyed nach Fehler-ID. Jedes Modul setzt und löscht seine eigenen Einträge
unabhängig; leer (`{}`) heißt fehlerfrei.

```json
"errors": {
  "no_device":   { "message": "No matching device found", "severity": "error" },
  "base_config": { "message": "TOML error at line 12",     "severity": "error" }
}
```

| Feld       | Typ      | Beschreibung |
|------------|----------|--------------|
| `message`  | `string` | Anzeigetext |
| `severity` | `string` | `"error"` · `"warning"` · `"info"` |

Bekannte IDs: `no_device`, `base_config`. Die Liste ist nicht abgeschlossen —
jedes Modul kann eigene vergeben, ein Consumer sollte also über das Objekt
iterieren statt auf bestimmte Keys zu prüfen.

---

## `configs`

Vollständiger Snapshot der Config-Registry. Wird neu geschrieben sobald sich an
der Registry etwas ändert — enthält **alle geladenen** Configs, nicht nur die
gerade aktiven. Für „was gilt jetzt gerade" ist `context.config_stack` zuständig.

```json
"configs": [
  { "name": "Steam Deck",    "kind": "base",   "parent": null,         "enabled": true, "status": "ok",    "errors": [] },
  { "name": "Firefox",       "kind": "app",    "parent": null,         "enabled": true, "status": "ok",    "errors": [] },
  { "name": "Voice Control", "kind": "module", "parent": "Steam Deck", "enabled": true, "status": "ok",    "errors": [] }
]
```

| Feld      | Typ              | Beschreibung |
|-----------|------------------|--------------|
| `name`    | `string`         | Anzeigename der Config — bei Base-Configs der deklarierte Gerätename, nicht der Dateiname |
| `kind`    | `string`         | `"base"` (deklariert ein Gerät) · `"app"` (hat `match_window_class`) · `"module"` (weder noch, nur über `include` erreichbar) · `"unknown"` (nicht parsebar) |
| `parent`  | `string \| null` | Bei Modulen: die Config, deren `[modules] include` es hereinholt. Sonst `null` |
| `enabled` | `bool`           | Ob die Config aktuell aktiv geschaltet ist |
| `status`  | `string`         | `"ok"` · `"warning"` · `"error"` — abgeleitet aus `errors`: `"error"` sobald ein Eintrag `severity: "error"` hat, sonst `"warning"` wenn überhaupt welche da sind |
| `errors`  | `object[]`       | `{ severity, message }`, gleiche Form wie oben |

---

## `gaming_mode_trigger`

Der Button, der Gaming Mode umschaltet — damit ein HUD ihn markieren kann, ohne
die Config zu parsen. `null` wenn kein Trigger konfiguriert ist.

```json
"gaming_mode_trigger": { "key": "BTN_BASE", "label": "Gaming Mode" }
```

---

## Analog-Daten: `trackpads` / `sticks` / `imu`

Diese drei Felder hängen zusammen. Sie werden nur befüllt, wenn der Analog-Export
per IPC eingeschaltet ist:

```bash
# über /tmp/makima-control.sock
analog-state-export on
analog-state-export off
```

Ist er aus, stehen `sticks` und `imu` auf `null` und `context.analog_state_export`
auf `false`. Grund für den Schalter: Analog-Events kommen mit ~60 Hz. Das HUD
schaltet ihn ein solange es sichtbar ist, und wieder aus wenn es verschwindet.

> Analog-Updates dürfen verworfen werden, wenn der Writer nicht hinterherkommt
> (`try_send`) — Button- und Modifier-Events dagegen nie. Ein Consumer darf also
> nicht annehmen, jede Fingerbewegung zu sehen.

### `sticks`

```json
"sticks": {
  "lstick": { "mode": "disabled", "x": 0.04, "y": -0.018, "deadzone": 0.092, "active": false },
  "rstick": { "mode": "cursor",   "x": 0.02, "y": -0.003, "deadzone": 0.092, "active": false }
}
```

| Feld       | Typ      | Beschreibung |
|------------|----------|--------------|
| `mode`     | `string` | Konfigurierte Funktion des Sticks, z.B. `"disabled"` · `"cursor"` · `"scroll"` |
| `x` / `y`  | `float`  | Normalisierte Position, −1.0 … +1.0 |
| `deadzone` | `float`  | Konfigurierte Deadzone im selben Maßstab |
| `active`   | `bool`   | Auslenkung liegt außerhalb der Deadzone. Vom Backend berechnet, damit das HUD die Regel nicht nachbaut |

### `imu`

```json
"imu": { "x": 0.0, "y": 0.0 }
```

Normalisiert auf 0.0 … 1.0 (aus dem vorzeichenlosen Rohbereich 0 … 32767).

### `trackpads`

Enthält den aktuellen Zustand beider Trackpads und des kombinierten Gesture-Devices.

```json
"trackpads": {
  "left": {
    "mode":     "disabled",
    "x":        0.0,
    "y":        0.0,
    "touching": false,
    "pressed":  false
  },
  "right": {
    "mode":     "trackball",
    "x":        0.42,
    "y":       -0.1,
    "touching": true,
    "pressed":  false
  },
  "gesture": {
    "enabled":  true,
    "touching": false
  }
}
```

### `trackpads.left` / `trackpads.right`

| Feld       | Typ     | Beschreibung |
|------------|---------|--------------|
| `mode`     | `string` | Aktueller Modus: `"disabled"` · `"mt-trackpad"` · `"trackball"` (aus Config) oder `"gestures"` wenn `gesture.touching = true` |
| `x`        | `float`  | Normalisierte X-Position, −1.0 … +1.0. Immer aktuell, auch während Gesture Session |
| `y`        | `float`  | Normalisierte Y-Position, −1.0 … +1.0 (oben = positiv). Immer aktuell |
| `touching` | `bool`   | Finger auf dem Pad **und** das individuelle Device sendet gerade. **`false` während `gesture.touching = true`** — auch wenn physisch ein Finger drauf ist |
| `pressed`  | `bool`   | Physischer Click (Pad gedrückt) |

### `trackpads.gesture`

| Feld       | Typ    | Beschreibung |
|------------|--------|--------------|
| `enabled`  | `bool` | `combined_gesture_device = true` in der Config — statisch |
| `touching` | `bool` | Gesture-Session aktiv: beide Pads waren gleichzeitig berührt, noch nicht beide geliftet |

### Gesture-Modus: Rendering-Logik

Wenn `gesture.touching = true`:
- `left.touching` und `right.touching` sind **beide `false`** (individuelle Devices senden nicht)
- Die aktuellen Fingerpositionen stehen weiterhin in `left.x/y` und `right.x/y`
- HUD rendert beide Finger als zusammengehörige Geste, keine unabhängigen Pad-Indikatoren

```
gesture.touching = false  →  left.touching / right.touching normal auswerten
gesture.touching = true   →  left.x/y und right.x/y für Zwei-Finger-Visualisierung nutzen
```
