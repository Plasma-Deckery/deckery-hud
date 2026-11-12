#!/usr/bin/env python3
"""
theme_pages.py — One page per B-20 theme: the full HUD on four backgrounds
(2 × 2, half size) and, below, close-ups at 1:1. Run inside the `deckery`
distrobox; to draw with the Deck's own fonts (Lato, Fira Code, URW Gothic,
Noto Sans Condensed — the distrobox lacks them), point fontconfig at the
host's fonts:

    distrobox enter deckery -- env FONTCONFIG_FILE=<fonts.conf> python3 \\
        tools/theme_pages.py <out_dir> <state.json> <bg.png,…> [theme,…] [held]

fonts.conf: <fontconfig><include>/etc/fonts/fonts.conf</include>
            <dir>/run/host/usr/share/fonts</dir></fontconfig>
held:       modifiers to show held ("BTN_TL", "BTN_TL+BTN_TR"), "-" for none;
            a leading "G" shows the pad gesture ("G-", "GBTN_TL").
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cairo

import helpers
import theme
from renderer_split import draw_hud_split
from theme_sheet import with_held

W, H = 1280, 800
# Close-up regions (x, y, w, h): face buttons with their legends, the left
# column (shoulder, d-pad, stick), the centre title block.
CLOSEUPS = ((780, 60, 500, 230), (0, 0, 340, 300), (380, 0, 520, 130))


def _state(base, held):
    gesture = held.startswith("G")
    keys = held[1:] if gesture else held
    st = with_held(base, () if keys in ("-", "") else tuple(keys.split("+")))
    if gesture:
        pads = st.setdefault("trackpads", {})
        pads.setdefault("gesture", {})["touching"] = True
        pads.setdefault("left", {}).update(touching=True, x=0.3, y=-0.2)
        pads.setdefault("right", {}).update(touching=True, x=-0.2, y=0.3)
    return st


def _render(bg, state):
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(img)
    cr.set_source_surface(bg, 0, 0)
    cr.paint()
    draw_hud_split(cr, None, None, state, W, H)
    return img


def _label(cr, x, y, text, name):
    theme.activate(theme.BASE)      # captions in one font
    cr.set_source_rgb(1, 1, 1)
    helpers._txt(cr, x, y, text, size=13, bold=True)
    theme.activate(name)


def page(name, state, bgs, bg_names):
    theme.activate(name)
    imgs = [_render(bg, state) for bg in bgs]
    sc, pad, lab = 0.5, 10, 24
    tw, th = int(W * sc), int(H * sc)
    rows = (len(imgs) + 1) // 2
    # close-ups: each region on the first (white) and last (game) background
    picks = (0, len(imgs) - 1)
    cw = pad + sum(r[2] + pad for r in CLOSEUPS)
    width = max(pad + 2 * (tw + pad), cw)
    height = 40 + rows * (th + lab + pad) + len(picks) * (max(r[3] for r in CLOSEUPS) + lab + pad)
    out = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    cr = cairo.Context(out)
    cr.set_source_rgb(0.12, 0.12, 0.14)
    cr.paint()
    _label(cr, pad, 10, theme.load(name).label, name)
    for i, img in enumerate(imgs):
        x, y = pad + (i % 2) * (tw + pad), 40 + (i // 2) * (th + lab + pad)
        _label(cr, x, y, bg_names[i], name)
        cr.save()
        cr.translate(x, y + lab)
        cr.scale(sc, sc)
        cr.set_source_surface(img, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()
    y = 40 + rows * (th + lab + pad)
    for p in picks:
        x = pad
        _label(cr, x, y, f"1:1 · {bg_names[p]}", name)
        for rx, ry, rw, rh in CLOSEUPS:
            cr.set_source_surface(imgs[p], x - rx, y + lab - ry)
            cr.rectangle(x, y + lab, rw, rh)
            cr.fill()
            x += rw + pad
        y += max(r[3] for r in CLOSEUPS) + lab + pad
    return out


def main():
    out_dir, state_path, bg_arg = sys.argv[1:4]
    names = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else theme.names()
    held = sys.argv[5] if len(sys.argv) > 5 else "-"
    os.makedirs(out_dir, exist_ok=True)
    paths = bg_arg.split(",")
    bgs = [cairo.ImageSurface.create_from_png(p) for p in paths]
    bg_names = [os.path.basename(p).rsplit(".", 1)[0] for p in paths]
    state = _state(json.load(open(state_path)), held)
    for i, name in enumerate(names):
        path = os.path.join(out_dir, f"{i + 1:02d}_{name}.png")
        page(name, state, bgs, bg_names).write_to_png(path)
        print(path)
    theme.activate(theme.BASE)


if __name__ == "__main__":
    main()
