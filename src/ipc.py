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
_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATE    = "/tmp/makima-state.json"

_FRONT_SVG = os.path.join(_DIR, "assets", "steamdeckFront.svg")
_BACK_SVG  = os.path.join(_DIR, "assets", "steamdeckBack.svg")

_MAKIMA_SOCK = "/tmp/makima-control.sock"

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
