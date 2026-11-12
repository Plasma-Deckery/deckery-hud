#!/bin/bash
# redeploy-hud.sh — push the working tree's HUD code into the installed copy
# and restart it. No sudo required.
#
# The counterpart to deckery-main's redeploy-tray.sh, and it exists for the
# same reason: the HUD is installed as a *copy* under
# ~/.local/share/deckery/deckery-hud, so editing this repo changes nothing
# until the copy is refreshed. Restarting the service alone silently keeps
# running the old code — which looks exactly like a deploy that worked.
#
# Note that the repo's own install.sh symlinks ~/.local/bin/deckery-hud
# straight at the working tree. That is not how this machine is set up; here
# the launcher points into the installed copy, which is why this script is
# needed at all.
#
# Only src/ is copied. assets/ rarely changes and systemd/ needs a
# daemon-reload, so unit changes are not something to do behind your back.
#
# This deploys the *working tree*, uncommitted changes included. That is the
# point, but it means `git status` is worth a glance first.

set -e
REPO="$(dirname "$(readlink -f "$0")")"
DEST="$HOME/.local/share/deckery/deckery-hud"

if [ ! -d "$DEST" ]; then
    echo "Not installed: $DEST does not exist." >&2
    echo "Run deckery-main's get.sh first." >&2
    exit 1
fi

echo "Copying src/ → $DEST/src/"
cp -a "$REPO/src/." "$DEST/src/"

# Files deleted from the repo must go from the copy too: a theme TOML left
# behind still shows up in the theme mode, a module left behind still imports.
(cd "$DEST/src" && find . -type f ! -path '*/__pycache__/*' | while read -r f; do
    [ -e "$REPO/src/$f" ] || { echo "Removing stale $f"; rm -f "$f"; }
done)

# Stale bytecode from the previous version shadows fresh sources often enough
# to be worth removing outright.
find "$DEST/src" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

systemctl --user restart deckery-hud.service
echo "Done — deckery-hud restarted from the working tree."
