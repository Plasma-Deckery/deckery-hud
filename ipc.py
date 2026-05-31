"""
ipc.py — Makima IPC and state loading.

Path constants are derived from this file's location so the project is
relocatable and no personal paths are hardcoded.
"""

import json
import os
import socket

# ── Paths ─────────────────────────────────────────────────────────────────────
# _DIR is the directory containing this file — works wherever the project lives.
_DIR      = os.path.dirname(os.path.abspath(__file__))
_STATE    = "/tmp/makima-state.json"
_FALLBACK = os.path.join(_DIR, "state.json")

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


# ── State loading ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    for path in (_STATE, _FALLBACK):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {"context": {"config_stack": ["—"]}, "bindings": {}, "modifier_active": {}}
