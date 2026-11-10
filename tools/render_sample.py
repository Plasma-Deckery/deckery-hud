#!/usr/bin/env python3
"""
render_sample.py — Render a handful of hand-built makima-state snapshots to
PNG, for the classic and/or split renderer, without a running GTK window or a
real makima.

Not a test suite — a fixture-rendering tool. Run inside the `deckery`
distrobox, where cairo/gi.Rsvg are installed (see docs/info.md):

    distrobox enter deckery -- python3 tools/render_sample.py <out_dir> [classic|split|split_groups]

Writes one PNG per sample state into <out_dir>.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import cairo
import gi
gi.require_version('Rsvg', '2.0')
from gi.repository import Rsvg

from layout import HUD_W, HUD_H

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")


def _svg(name):
    return Rsvg.Handle.new_from_file(os.path.join(_ASSETS, name))


SAMPLES = {
    "unreadable": {
        "unreadable": "/run/user/1000/makima-state.json",
    },
    "base_only": {
        "context": {
            "config_stack": ["Steam Deck"],
            "active_app": "default",
            "held_modifiers": [],
            "active_buttons": [],
            "active_outputs": [],
            "available_modifiers": {
                "BTN_TL": {"has_app_combos": False},
                "BTN_TR": {"has_app_combos": False},
            },
            "paused": False,
            "gaming_mode": False,
            "analog_state_export": False,
        },
        "bindings": {
            "BTN_SOUTH": {"action": ["KEY_ENTER"], "kind": "remap", "label": None, "origin": "Steam Deck", "silent": False},
            "BTN_EAST":  {"action": ["KEY_ESC"],   "kind": "remap", "label": None, "origin": "Steam Deck", "silent": False},
        },
        "modifier_active": {},
        "last_action": {"type": "keys", "value": [], "ts": 0.0},
        "gaming_mode_trigger": {"key": "BTN_BASE", "label": "Gaming Mode"},
        "trackpads": {"left": {}, "right": {}, "gesture": {}},
        "sticks": {},
    },
    "held_modifier": {
        "context": {
            "config_stack": ["Steam Deck"],
            "active_app": "default",
            "held_modifiers": ["BTN_TL"],
            "active_buttons": ["BTN_TL"],
            "active_outputs": [{"key": "KEY_LEFTCTRL", "silent": False}],
            "available_modifiers": {
                "BTN_TL": {"has_app_combos": False},
            },
            "paused": False,
            "gaming_mode": False,
            "analog_state_export": False,
        },
        "bindings": {
            "BTN_SOUTH": {"action": ["KEY_ENTER"], "kind": "remap", "label": None, "origin": "Steam Deck", "silent": False},
        },
        "modifier_active": {
            "BTN_DPAD_UP": {"action": ["KEY_PAGEUP"], "kind": "remap", "label": None, "origin": "Steam Deck", "silent": False},
        },
        "last_action": {"type": "keys", "value": [], "ts": 0.0},
        "gaming_mode_trigger": {"key": "BTN_BASE", "label": "Gaming Mode"},
        "trackpads": {"left": {}, "right": {}, "gesture": {}},
        "sticks": {},
    },
    "layer_override_and_combo": {
        "context": {
            "config_stack": ["Steam Deck", "Firefox"],
            "active_app": "Firefox",
            "held_modifiers": ["BTN_TL"],
            "active_buttons": ["BTN_TL"],
            "active_outputs": [{"key": "KEY_LEFTCTRL", "silent": False}],
            "available_modifiers": {
                "BTN_TL": {"has_app_combos": True},
                "BTN_TR": {"has_app_combos": True, "virtual": True},
            },
            "paused": False,
            "gaming_mode": False,
            "analog_state_export": False,
        },
        "bindings": {
            "BTN_SOUTH": {"action": ["KEY_ENTER"], "kind": "remap", "label": None, "origin": "Firefox", "silent": False},
        },
        "modifier_active": {
            "BTN_DPAD_LEFT": {"action": ["KEY_LEFTCTRL", "KEY_TAB"], "kind": "remap", "label": "Prev Tab", "origin": "Firefox", "silent": False},
        },
        "last_action": {"type": "keys", "value": ["KEY_ENTER"], "ts": 0.0},
        "gaming_mode_trigger": {"key": "BTN_BASE", "label": "Gaming Mode"},
        "trackpads": {"left": {}, "right": {}, "gesture": {}},
        "sticks": {},
    },
    "gaming_mode_and_analog": {
        "context": {
            "config_stack": ["Steam Deck"],
            "active_app": "default",
            "held_modifiers": [],
            "active_buttons": ["BTN_BASE"],
            "active_outputs": [],
            "available_modifiers": {},
            "paused": False,
            "gaming_mode": True,
            "analog_state_export": True,
        },
        "bindings": {},
        "modifier_active": {},
        "last_action": {"type": "keys", "value": [], "ts": 0.0},
        "gaming_mode_trigger": {"key": "BTN_BASE", "label": "Gaming Mode"},
        "trackpads": {
            "left":  {"mode": "mt-trackpad", "x": -0.3, "y": 0.2, "touching": True,  "pressed": False},
            "right": {"mode": "trackball",   "x": 0.5,  "y": -0.1, "touching": False, "pressed": True},
            "gesture": {"enabled": True, "touching": False},
        },
        "sticks": {
            "lstick": {"mode": "disabled", "x": 0.0,  "y": 0.0,  "deadzone": 0.092, "active": False},
            "rstick": {"mode": "cursor",   "x": 0.6,  "y": -0.4, "deadzone": 0.092, "active": True},
        },
    },
    "pad_modes": {
        "context": {
            "config_stack": ["Steam Deck"],
            "active_app": "default",
            "held_modifiers": [],
            "active_buttons": [],
            "active_outputs": ["BTN_LEFT", "KEY_LEFTCTRL"],
            "available_modifiers": {},
            "paused": False,
            "gaming_mode": False,
            "analog_state_export": True,
        },
        "bindings": {
            "BTN_TL2": {"action": ["BTN_LEFT"]},
            "BTN_TR2": {"action": ["BTN_RIGHT"]},
        },
        "modifier_active": {},
        "last_action": {"type": "keys", "value": [], "ts": 0.0},
        "gaming_mode_trigger": {"key": "BTN_BASE", "label": "Gaming Mode"},
        "trackpads": {
            "left":  {"mode": "disabled",   "x": 0.0, "y": 0.0, "touching": False, "pressed": False},
            "right": {"mode": "mt-trackpad", "x": 0.0, "y": 0.0, "touching": True,  "pressed": False},
            "gesture": {"enabled": True, "touching": False},
        },
        "sticks": {
            "lstick": {"mode": "disabled", "x": 0.0, "y": 0.0, "deadzone": 0.092, "active": False},
            "rstick": {"mode": "cursor",   "x": 0.0, "y": 0.0, "deadzone": 0.092, "active": False},
        },
    },
    "gesture_active": {
        "context": {
            "config_stack": ["Steam Deck"],
            "active_app": "default",
            "held_modifiers": [],
            "active_buttons": [],
            "active_outputs": [],
            "available_modifiers": {},
            "paused": False,
            "gaming_mode": False,
            "analog_state_export": True,
        },
        "bindings": {},
        "modifier_active": {},
        "last_action": {"type": "keys", "value": [], "ts": 0.0},
        "gaming_mode_trigger": {"key": "BTN_BASE", "label": "Gaming Mode"},
        "trackpads": {
            "left":  {"mode": "gestures", "x": 0.0, "y": 0.0, "touching": False, "pressed": False},
            "right": {"mode": "gestures", "x": 0.0, "y": 0.0, "touching": False, "pressed": False},
            "gesture": {"enabled": True, "touching": True},
        },
        "sticks": {
            "lstick": {"mode": "disabled", "x": 0.0, "y": 0.0, "deadzone": 0.092, "active": False},
            "rstick": {"mode": "disabled", "x": 0.0, "y": 0.0, "deadzone": 0.092, "active": False},
        },
    },
}


def _group_cases(sw):
    """B-12 partial-HUD cases for the split renderer: (state, elements) with
    elements as draw_hud_split takes them, {id: (opacity, dx, Content)}."""
    from reveal import Content, FULL
    from renderer_split import _side_slide_offset
    from elements import ELEMENT_IDS, side_of
    opening = {e: (0.5, _side_slide_offset(side_of(e), sw, 0.5) if side_of(e) else 0.0, FULL)
               for e in ELEMENT_IDS}
    opening["RPad"] = (1.0, 0.0, FULL)
    return {
        "mod_filter": (SAMPLES["held_modifier"], {
            "DPad": (1.0, 0.0, Content(frozenset({"BTN_DPAD_UP"}))),
            "L1": (1.0, 0.0, FULL),
        }),
        "pad_only_right": (SAMPLES["pad_modes"], {"RPad": (1.0, 0.0, FULL)}),
        "gesture_both": (SAMPLES["gesture_active"], {"LPad": (1.0, 0.0, FULL),
                                                      "RPad": (1.0, 0.0, FULL)}),
        "full_opening_with_pad": (SAMPLES["pad_modes"], opening),
    }


def render(renderer_name, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    front = _svg("steamdeckFront.svg")
    back = _svg("steamdeckBack.svg")

    if renderer_name == "classic":
        from renderer import draw_hud
        draw_fn = lambda cr, state: draw_hud(cr, front, back, state)
        w, h = HUD_W, HUD_H
    elif renderer_name == "split":
        from renderer_split import draw_hud_split
        w, h = 1280, 800
        draw_fn = lambda cr, state: draw_hud_split(cr, front, back, state, w, h)
    elif renderer_name == "split_groups":
        from renderer_split import draw_hud_split
        w, h = 1280, 800
        cases = _group_cases(w)
        draw_fn = lambda cr, case: draw_hud_split(cr, front, back, case[0], w, h, groups=case[1])
    else:
        raise ValueError(renderer_name)

    samples = cases if renderer_name == "split_groups" else SAMPLES
    for name, state in samples.items():
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        cr.set_source_rgb(0.1, 0.1, 0.12)
        cr.paint()
        draw_fn(cr, state)
        path = os.path.join(out_dir, f"{renderer_name}_{name}.png")
        surface.write_to_png(path)
        print(path)


if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/hud_renders"
    which = sys.argv[2] if len(sys.argv) > 2 else "classic"
    render(which, out_dir)
