#!/bin/bash
# install.sh — one-shot setup for deckery-hud.
# Run once after cloning. Re-running is idempotent.

set -e
REPO="$(dirname "$(readlink -f "$0")")"
echo "Repo: $REPO"

# ── 1. Distrobox container ────────────────────────────────────────────────────
if distrobox list | grep -q '^| deckery '; then
    echo "Container 'deckery' already exists — skipping"
else
    echo "Creating distrobox container 'deckery'..."
    distrobox assemble create --file "$REPO/distrobox.ini"
fi

# ── 2. Symlink scripts into ~/.local/bin ──────────────────────────────────────
mkdir -p "$HOME/.local/bin"
ln -sf "$REPO/deckery-hud-launch"  "$HOME/.local/bin/deckery-hud"
ln -sf "$REPO/deckery-hud-toggle"  "$HOME/.local/bin/deckery-hud-toggle"
echo "Linked scripts to ~/.local/bin"

# ── 3. Symlink systemd service ────────────────────────────────────────────────
mkdir -p "$HOME/.config/systemd/user"
ln -sf "$REPO/systemd/deckery-hud.service" "$HOME/.config/systemd/user/deckery-hud.service"
echo "Linked systemd service"

# ── 4. Enable and start ───────────────────────────────────────────────────────
systemctl --user daemon-reload
systemctl --user enable --now deckery-hud.service
echo "Service enabled and started"
