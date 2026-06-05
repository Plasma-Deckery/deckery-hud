# deckery-hud

A Wayland overlay for the Steam Deck that shows what every button does right now. Part of [Plasma Deckery](https://github.com/Plasma-Deckery/deckery).

Hold a modifier and the full combo layer appears instantly. The idea is simple: controls should be discoverable and explain themselves — for easier onboarding and faster recall.

<video src="https://github.com/user-attachments/assets/657c990d-051e-4870-b3bc-a9059dd5fad0" controls autoplay loop muted></video>

<video src="https://github.com/user-attachments/assets/728cf2dc-443e-446e-8714-4931174684ad" controls autoplay loop muted></video>

---

## What it does

### HUD overlay
Toggle open (default: L3) to pause remapping and inspect your full button layout:

- Renders two Steam Deck silhouettes (front + back) with callout lines to button labels
- Updates live from `/tmp/makima-state.json` — written atomically by [makima-deckery](https://github.com/Plasma-Deckery/makima-deckery) on every input event
- Pauses makima remapping while open (dry-run mode: see what buttons do without triggering anything)
- Center strip shows the active modifier state and the currently held output keys
- Trackpad and stick positions rendered as analog overlays on the silhouette
- Dot colours: **amber** = modifier held, **white** = button active, **gray** = unbound
- Small amber dot on buttons that would unlock a combo if held next (discoverable modifiers)

### OSD (On-Screen Display)
Always-on transparent overlay — active even when the HUD is closed:

- Shows currently held output keys as cyan pills at the bottom of the screen
- Fires a toast notification on every action (key combo, command, exec)
- Fully input-transparent — no clicks, no interference with anything underneath
- `silent = true` bindings (e.g. mouse clicks) are suppressed from the OSD but still visible in the HUD center strip

---

## Setup

Requires [distrobox](https://github.com/containers/distrobox).

```bash
git clone https://github.com/Plasma-Deckery/deckery-hud
cd deckery-hud
bash install.sh
```

`install.sh` sets up the distrobox container, symlinks the scripts and systemd unit, and starts the service.

---

## Architecture

```
makima-deckery ──► /tmp/makima-state.json
                           │
                      deckery-hud
                    (GTK4, Layer Shell)
                  persistent D-Bus service
                           │
               ┌───────────┴───────────┐
             HUD window             OSD window
          (shown on toggle)      (always visible)
               └───────────┬───────────┘
                            │
                     renderer.py          makima IPC
                   (SVG + Cairo/Pango)   pause / resume
```

---

## State format

The HUD reads `/tmp/makima-state.json`. See [docs/STATE_SPEC.md](docs/STATE_SPEC.md) for the full contract between makima-deckery and the HUD.
