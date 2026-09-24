"""
ipc.py — Makima IPC and state loading.

Path constants are derived from this file's location so the project is
relocatable and no personal paths are hardcoded.
"""

import json
import os
import socket

# ── Paths ─────────────────────────────────────────────────────────────────────
# _DIR is the project root (one level above src/).
# This works for both dev checkouts (src/ subdirectory) and RPM installs
# (/usr/lib/deckery-hud/src/ subdirectory) — the structure is identical.
_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# makima writes its state into $XDG_RUNTIME_DIR (= /run/user/<uid>) — a
# per-user tmpfs, mode 0700, the same directory the control socket below lives
# in, and for the same reason: /tmp is mode 1777, so anything able to create
# the path first decides what this overlay draws.
#
# No /tmp fallback, deliberately. It would downgrade to the squattable path in
# exactly the situation where something is already unusual, and it is the same
# derivation makima itself makes, so the two cannot disagree.
_STATE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}",
    "makima-state.json")

_FRONT_SVG = os.path.join(_DIR, "assets", "steamdeckFront.svg")
_BACK_SVG  = os.path.join(_DIR, "assets", "steamdeckBack.svg")

# Makima binds its control socket in $XDG_RUNTIME_DIR (/run/user/<uid>), not in
# /tmp: /tmp is mode 1777, and this socket accepts "pause". No /tmp fallback —
# it could only ever find a socket someone else squatted.
_MAKIMA_SOCK = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}",
    "makima-control.sock",
)

# ── Makima IPC ────────────────────────────────────────────────────────────────

def makima_ipc(cmd: str) -> None:
    """Send a command to makima's Unix control socket. Silently ignores errors."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(_MAKIMA_SOCK)
            s.sendall((cmd + "\n").encode())
    except Exception:
        pass


def makima_pause() -> None:
    makima_ipc("pause")


def makima_resume() -> None:
    makima_ipc("resume")


def makima_analog_on() -> None:
    makima_ipc("analog-state-export on")


def makima_analog_off() -> None:
    makima_ipc("analog-state-export off")


# ── State loading ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    """makima's current state, or a state that says it could not be read.

    The `unreadable` marker is the point. Without it a missing or unparsable
    file was indistinguishable from a controller with nothing bound: the
    overlay drew its full chrome with every button blank and no way to say
    why. Now the renderer has something to show instead of a working-looking
    HUD that happens to be empty.
    """
    try:
        with open(_STATE) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"unreadable": _STATE,
            "context": {"config_stack": ["—"]}, "bindings": {}, "modifier_active": {}}
