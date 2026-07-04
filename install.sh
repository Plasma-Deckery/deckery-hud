#!/bin/bash
# install.sh — one-shot setup for deckery-hud.
# Run once after cloning. Re-running is idempotent.

set -e
REPO="$(dirname "$(readlink -f "$0")")"
PACKAGES="python python-gobject python-cairo gtk4-layer-shell librsvg pango noto-fonts noto-fonts-extra"

echo "Repo: $REPO"

# ── 1. Distrobox container + packages ────────────────────────────────────────
distrobox create --name deckery --image archlinux:latest || true
distrobox enter deckery -- sudo pacman -S --needed --noconfirm $PACKAGES

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
systemctl --user restart deckery-hud.service
echo "Service enabled and restarted"
