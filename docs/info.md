# Technical Notes

## Dependencies

Runs inside a [distrobox](https://github.com/containers/distrobox) container (`deckery`) because `gtk4-layer-shell` is not available as a GObject Typelib on the Bazzite host.

Required inside the container (declared in `distrobox.ini`):
- Python 3
- `gtk4-layer-shell` (shared library + GObject Typelib)
- `python-gobject` (GTK4 bindings)
- `librsvg` (SVG rendering)
- `pango` / `pangocairo` (text layout)

## File watch

The `/tmp/` directory is watched rather than the state file itself because makima writes atomically via rename — which creates a new inode. A direct file watch would miss the update.

## Scripts

**`deckery-hud-launch`** — starts the service inside distrobox:
```bash
REPO="$(dirname "$(readlink -f "$0")")"
exec distrobox enter deckery -- bash -c \
  "LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so python3 '$REPO/src/deckery-hud.py'"
```

**`deckery-hud-toggle`** — toggles HUD visibility via D-Bus:
```bash
gdbus call --session \
  --dest de.plasma_deckery.hud \
  --object-path /de/plasma_deckery/hud \
  --method de.plasma_deckery.hud.Toggle
```

## Systemd

The service unit lives in `systemd/deckery-hud.service`. `install.sh` symlinks it into `~/.config/systemd/user/` and enables it. To manage it manually:

```bash
systemctl --user enable --now deckery-hud.service
systemctl --user restart deckery-hud.service
systemctl --user status deckery-hud.service
```

## Trigger

In your makima config, bind a button to the toggle command:
```toml
BTN_THUMBL = { run = ["deckery-hud-toggle"], no_pause = true, label = "Toggle HUD" }
```
