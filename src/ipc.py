"""
ipc.py — Makima IPC and state loading.

Path constants are derived from this file's location so the project is
relocatable and no personal paths are hardcoded.
"""

import json
import os
import socket
import shutil
import time

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


# ── deckery-auth ──────────────────────────────────────────────────────────────

# The daemon's own sockets are all closed to us: auth.sock is root-only, and
# display.sock and polkit.sock are exe-verified against fixed paths. So the
# presence of the socket file is the only thing we can observe from here. It
# says the daemon created its sockets at some point — not that it is alive.
# That is enough to decide whether to offer the button.
# Two candidate roots, tried in order. Inside the `deckery` distrobox the host
# filesystem also appears under /run/host, and distrobox binds the individual
# deckery sockets at container start — so a socket the daemon created later is
# only reachable via the /run/host path until the container is restarted. Both
# are checked so neither a fresh socket nor a fresh container breaks this.
_SOCK_ROOTS = ("/run/deckery", "/run/host/run/deckery")


def _sock(name: str):
    """First existing path for a daemon socket, or None."""
    for root in _SOCK_ROOTS:
        p = os.path.join(root, name)
        try:
            if os.path.exists(p):
                return p
        except OSError:
            continue
    return None


def auth_daemon_present() -> bool:
    """Is deckery-auth installed and has it set up its sockets?"""
    return _sock("auth.sock") is not None


def start_pin_change() -> None:
    """Ask the daemon to run the PIN change.

    One line on a socket, no sudo. The daemon itself demands the PIN currently
    in force before it writes anything, so knowing the old PIN is the
    permission — which is why this socket needs no privilege at all.

    The previous version shelled out to `sudo deckery-pin-set`, which put the
    old-PIN check in sudoers rather than in the daemon. A NOPASSWD line for
    that binary then removed the check entirely and the change went straight
    through. A rule that can be configured away was never the rule.

    Fire and forget: the daemon drives the overlay from here on, and the reply
    only says how it ended.
    """
    _control("CHANGE_PIN")


def _control(cmd: str) -> None:
    """Send one command to the daemon's control socket. Errors are not fatal."""
    path = _sock("control.sock")
    if path is None:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s_:
            s_.settimeout(2.0)
            s_.connect(path)
            s_.sendall(cmd.encode() + b"\n")
    except OSError:
        pass


def start_auth_session() -> None:
    """Ask the daemon to show the overlay as a demonstration.

    Same socket as the PIN change, and for the same reason: neither needs a
    privilege. The demo verifies nothing and stores nothing, so there is no
    authority to protect.

    This used to run `sudo true` and leave a marker file for the overlay to
    notice. That worked, but the marking could go stale or be missed — and a
    demo that fails to announce itself is indistinguishable from a real prompt.
    Now the daemon knows what it started and says so itself.
    """
    _control("DEMO")
