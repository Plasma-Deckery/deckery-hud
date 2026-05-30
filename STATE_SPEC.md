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

| Feld               | Typ            | Beschreibung |
|--------------------|----------------|--------------|
| `config_stack`     | `string[]`     | Aktive Config-Ebenen, z.B. `["Steam Deck", "Firefox"]` |
| `held_modifiers`   | `string[]`     | Gerade gehaltene Modifier-Buttons, z.B. `["BTN_TL"]` |
| `active_buttons`   | `string[]`     | Alle gerade physisch gedrückten Buttons |
| `active_outputs`   | `string[]`     | Aggregierte evdev-Codes die gerade gehalten werden |
| `paused`           | `bool`         | Makima pausiert (HUD übernimmt Input) |
| `layout`           | `int`          | Intern; HUD ignoriert dieses Feld |

---

## `bindings[key]`

| Feld     | Typ          | Beschreibung |
|----------|--------------|--------------|
| `action` | `string[]`   | evdev-Codes der Aktion |
| `kind`   | `string`     | `"remap"` o.ä.; HUD ignoriert aktuell |
| `label`  | `string\|null` | Optionaler Freitext-Label für die Aktion (HUD nutzt ihn statt `_fmt(action)` wenn gesetzt) |
| `origin` | `string`     | Name der Config-Ebene, aus der die Binding stammt |

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

## `context.available_modifiers` — NEU (noch nicht implementiert)

Liste der Button-Codes, die im aktuellen Modifier-Zustand als *nächster* Modifier
drückbar wären und dabei Combo-Bindings freischalten würden.

```json
"context": {
  "available_modifiers": ["BTN_TL", "BTN_TL2"]
}
```

**Verhalten:**
- Kein Modifier gehalten → zeigt alle Top-Level-Modifier-Buttons
- L1 gehalten → zeigt Buttons die L1+X-Combos haben (z.B. R1 wenn L1+R1 existiert)
- Leer (`[]`) wenn im aktuellen Zustand keine weiteren Modifier sinnvoll sind

**HUD-Nutzung:** Buttons aus dieser Liste, die *nicht* in `held_modifiers` sind,
bekommen in der Callout-Legende einen kleinen amber Punkt als Discoverable-Indikator.

---

## `modifier_active`

Wird von makima befüllt, wenn mindestens ein Modifier gehalten wird.
Enthält die resultierenden Bindings für den aktuellen Modifier-State.
Schema identisch zu `bindings`.
