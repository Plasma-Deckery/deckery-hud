# Makima State Contract — HUD-seitige Erwartungen

Datei: `/tmp/makima-state.json`

---

## Gesamtstruktur (Ist-Stand)

```json
{
  "context": { ... },
  "bindings":        { "BTN_X": { "action": [], "kind": "remap", "label": null, "origin": "Steam Deck" } },
  "modifier_active": { "BTN_X": { "action": [], ... } },
  "last_action":     { "type": "keys", "value": [], "ts": 0.0 }
}
```

---

## `context`

| Feld                  | Typ            | Beschreibung |
|-----------------------|----------------|--------------|
| `config_stack`        | `string[]`     | Aktive Config-Ebenen, z.B. `["Steam Deck", "Firefox"]` |
| `held_modifiers`      | `string[]`     | Gerade gehaltene Modifier-Buttons, z.B. `["BTN_TL"]` |
| `active_buttons`      | `string[]`     | Alle gerade physisch gedrückten Buttons |
| `active_outputs`      | `string[]`     | Aggregierte evdev-Codes die gerade gehalten werden |
| `available_modifiers` | `string[]`     | Modifier-Buttons die im aktuellen Zustand als nächster Schritt sinnvoll wären (d.h. Combo-Bindings freischalten würden). Leer wenn keine weiteren Modifier existieren. |
| `paused`              | `bool`         | Makima pausiert (HUD übernimmt Input) |
| `layout`              | `int`          | Intern; HUD ignoriert dieses Feld |

---

## `bindings[key]`

| Feld       | Typ            | Beschreibung |
|------------|----------------|--------------|
| `action`   | `string[]`     | evdev-Codes oder Shell-Befehle der Aktion |
| `kind`     | `string`       | `"remap"` · `"command"` · `"movement"` |
| `label`    | `string\|null` | Optionaler Freitext-Label (HUD nutzt ihn statt `_fmt(action)` wenn gesetzt) |
| `origin`   | `string`       | Name der Config-Ebene, aus der die Binding stammt |
| `no_pause` | `bool`         | `true` wenn die Binding auch im Pause-Modus ausgeführt wird (nur bei `kind: "command"`) |

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
| `type`  | `string` | `"keys"` · `"command"` · `"exec"` |
| `value` | `string\|string[]` | Keys-Liste, Shell-String, oder argv |
| `label` | `string\|null` | **Neu, optional.** Lesbarer Name; HUD bevorzugt ihn über `_fmt(value)` |
| `ts`    | `float` | Unix-Timestamp (Sekunden) des Press-Events |

---

## `context.available_modifiers`

Liste der Modifier-Buttons, die im aktuellen Zustand als nächster Schritt
mindestens eine Combo-Binding freischalten würden.

```json
"context": {
  "available_modifiers": ["BTN_TL", "BTN_TR"]
}
```

**Verhalten:**
- Kein Modifier gehalten → alle Modifier die in irgendeiner Combo vorkommen
  (auch wenn sie einen weiteren Modifier benötigen — für Discoverability)
- L1 gehalten → Modifier die zusammen mit L1 eine Combo freischalten (z.B. BTN_TR wenn L1+R1+* existiert)
- Leer (`[]`) wenn im aktuellen Zustand keine weiteren Modifier sinnvoll sind

**HUD-Nutzung:** Buttons aus dieser Liste, die *nicht* in `held_modifiers` sind,
bekommen in der Callout-Legende einen kleinen amber Punkt als Discoverable-Indikator.
Der Punkt verschwindet sobald der Modifier gehalten wird (dann wird die ganze Zeile amber).

---

## `modifier_active`

Wird von makima befüllt, wenn mindestens ein Modifier gehalten wird.
Enthält die resultierenden Bindings für den aktuellen Modifier-State.
Schema identisch zu `bindings`.
