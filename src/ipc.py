"""
ipc.py — Makima IPC and state loading.

Path constants are derived from this file's location so the project is
relocatable and no personal paths are hardcoded.
"""

import json
import os
import os
import socket
import subprocess
import time

# ── Paths ─────────────────────────────────────────────────────────────────────
# _DIR is the project root (one level above src/).
# This works for both dev checkouts (src/ subdirectory) and RPM installs
# (/usr/lib/deckery-hud/src/ subdirectory) — the structure is identical.
_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATE = "/tmp/makima-state.json"

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
    try:
        with open(_STATE) as f:
            return json.load(f)
    except Exception:
        pass
    return {"context": {"config_stack": ["—"]}, "bindings": {}, "modifier_active": {}}


# ── deckery-auth ──────────────────────────────────────────────────────────────

# The daemon's own sockets are all closed to us: auth.sock is root-only, and
# display.sock and polkit.sock are exe-verified against fixed paths. So the
# presence of the socket file is the only thing we can observe from here. It
# says the daemon created its sockets at some point — not that it is alive.
# That is enough to decide whether to offer the button.
_AUTH_SOCK = "/run/deckery/auth.sock"


def auth_daemon_present() -> bool:
    """Is deckery-auth installed and has it set up its sockets?"""
    try:
        return os.path.exists(_AUTH_SOCK)
    except OSError:
        return False


# Marker the auth overlay looks for. In $XDG_RUNTIME_DIR, which is 0700 — only
# this user can write it. It carries a timestamp and is treated as valid for a
# few seconds, so it needs no cleanup and cannot leak into a later real prompt.
#
# Note the direction it fails in: the marker can only ever ADD the "do not type
# your real PIN" warning. Forging it gains an attacker nothing — the worst it
# achieves is talking someone out of entering their PIN.
def _demo_marker_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "deckery-auth-demo")


def mark_demo_session() -> None:
    """Tell the auth overlay that the next prompt is a demonstration."""
    try:
        with open(_demo_marker_path(), "w") as f:
            f.write(str(int(time.time() * 1000)))
    except OSError:
        pass


def start_auth_session() -> None:
    """Bring up the real PIN overlay by asking for a harmless privilege.

    Deliberately `sudo true` rather than a "demo" command on the daemon. A
    dedicated entry point would have to be reachable by an unprivileged session
    process, and that is a prompt anyone could conjure up — the overlay is a
    full-screen PIN dialog, so being able to summon it on demand is worth
    something to an attacker. Going through sudo means there is nothing to fake:
    this IS the genuine prompt, and `true` grants nothing once it succeeds.

    Detached into its own session so it outlives the HUD and needs no terminal
    (pam_deckery talks to the daemon, not to a tty).
    """
    try:
        subprocess.Popen(
            ["sudo", "true"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass
