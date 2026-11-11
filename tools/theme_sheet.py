#!/usr/bin/env python3
"""
theme_sheet.py — Compare B-20 themes side by side: one sheet per state, a
row per theme, a column per background. Run inside the `deckery` distrobox:

    distrobox enter deckery -- python3 tools/theme_sheet.py <out_dir> <state.json> \
        <bg.png,...> [theme,...] [held,...]

state.json: a makima state snapshot (e.g. a copy of makima-state.json).
bg.png:     1280x800 backgrounds (screenshots, wallpapers, a white page).
held:       modifier sets to show, "-" for none, "+" joins: "-,BTN_TL,BTN_BASE".
            For each, the state's own combos for exactly that set become
            modifier_active — what makima reports while it is held.
"""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import cairo
import gi
gi.require_version('Rsvg', '2.0')
from gi.repository import Rsvg

import helpers
import theme
from renderer_split import draw_hud_split

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
W, H = 1280, 800


def with_held(state, held):
    """`state` as makima reports it while exactly `held` is held."""
    s = copy.deepcopy(state)
    ctx = s.setdefault("context", {})
    ctx["held_modifiers"] = list(held)
    ctx["active_buttons"] = list(held)
    avail = {}
    active = {}
    for key, b in (s.get("bindings") or {}).items():
        parts = key.split("-")
        if len(parts) < 2:
            continue
        mods, btn = parts[:-1], parts[-1]
        if set(mods) == set(held) and held:
            active[btn] = b
        if not held and len(mods) == 1:
            avail.setdefault(mods[0], {"has_app_combos": False})
    s["modifier_active"] = active
    ctx["available_modifiers"] = avail
    ctx["paused"] = True
    if held:
        ctx["active_outputs"] = [{"key": "KEY_LEFTCTRL", "silent": False}]
    return s


def main():
    out, state_path, bgs = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
    themes = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else theme.names()
    helds = sys.argv[5].split(",") if len(sys.argv) > 5 else ["-"]
    os.makedirs(out, exist_ok=True)
    front = Rsvg.Handle.new_from_file(os.path.join(_ASSETS, "steamdeckFront.svg"))
    back = Rsvg.Handle.new_from_file(os.path.join(_ASSETS, "steamdeckBack.svg"))
    base = json.load(open(state_path))
    bg_surfs = [cairo.ImageSurface.create_from_png(p) for p in bgs]

    sc, pad, lab = 0.5, 10, 26
    tw, th = int(W * sc), int(H * sc)
    for held in helds:
        keys = () if held == "-" else tuple(held.split("+"))
        state = with_held(base, keys)
        sheet = cairo.ImageSurface(cairo.FORMAT_ARGB32, pad + len(bgs) * (tw + pad),
                                   pad + len(themes) * (th + lab + pad))
        scr = cairo.Context(sheet)
        scr.set_source_rgb(0.13, 0.13, 0.15)
        scr.paint()
        for r, name in enumerate(themes):
            theme.activate(name)
            for c, bg in enumerate(bg_surfs):
                img = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
                cr = cairo.Context(img)
                cr.set_source_surface(bg, 0, 0)
                cr.paint()
                draw_hud_split(cr, front, back, state, W, H)
                x, y = pad + c * (tw + pad), pad + r * (th + lab + pad)
                scr.save()
                scr.translate(x, y + lab)
                scr.scale(sc, sc)
                scr.set_source_surface(img, 0, 0)
                scr.get_source().set_filter(cairo.FILTER_GOOD)
                scr.paint()
                scr.restore()
                theme.activate(theme.DEFAULT)   # titles in one font
                scr.set_source_rgb(1, 1, 1)
                helpers._txt(scr, x, y + 4, f"{theme.load(name).label}  ·  "
                             f"{os.path.basename(bgs[c]).split('.')[0]}", size=12, bold=True)
                theme.activate(name)
        tag = "none" if held == "-" else held.replace("BTN_", "").replace("+", "_")
        path = os.path.join(out, f"themes_{tag}.png")
        sheet.write_to_png(path)
        print(path)


if __name__ == "__main__":
    main()
