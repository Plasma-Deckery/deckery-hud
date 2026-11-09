#!/usr/bin/env python3
"""
tune_backdrop.py — Live tool for tuning the split renderer's per-group
metaball backdrop (see src/metaball.py) against the *real* desktop instead
of a plain floating preview window.

Two separate windows, one process:
  - a normal desktop window with the sliders/checkboxes (ControlWin)
  - a full-screen, click-through, layer-shell OVERLAY window that draws
    *only* the live backdrop, transparent everywhere else (OverlayWin) —
    same Gtk4LayerShell setup as the real HUD (src/win.py), so what you see
    is in the actual compositor layer the HUD itself runs in, over your
    real screen content, not a desktop window pretending to be one.

Must be launched exactly like the real HUD service (LD_PRELOAD is what
makes Gtk4LayerShell available at all):

    distrobox enter deckery -- \\
      env LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so python3 tools/tune_backdrop.py

Every slider/checkbox change re-renders the overlay and writes the current
parameters to tools/backdrop_tuned.json, so the chosen values can be read
back and wired into renderer_split.py afterwards without transcribing
numbers by hand.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, GLib, Gtk4LayerShell as LayerShell

import cairo
from metaball import render_field
from layout_split import compute_layout
from clusters import LEFT_STACK, RIGHT_STACK

_OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backdrop_tuned.json")

_ALL_GROUPS = list(LEFT_STACK) + list(RIGHT_STACK)

_DEFAULTS = {
    "radius_mult": 1.6,
    "low": 0.5,
    "high": 1.3,
    "max_alpha": 0.6,
    "power": 2.0,
}


class OverlayWin(Gtk.ApplicationWindow):
    """Full-screen, click-through, transparent — draws only the backdrop."""

    def __init__(self, application):
        super().__init__(application=application)
        self.set_title("Backdrop tuning (overlay)")
        self.set_decorated(False)

        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_namespace(self, "deckery-hud-tune-backdrop")
        for edge in (LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT,
                     LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM):
            LayerShell.set_anchor(self, edge, True)

        css = Gtk.CssProvider()
        css.load_from_string("window { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER)

        da = Gtk.DrawingArea()
        da.set_draw_func(self._on_draw)
        self.set_child(da)
        self.da = da

        self.params = dict(_DEFAULTS)
        self.visible_groups = {g: True for g in _ALL_GROUPS}
        self._surface = None
        self._surface_wh = None

        self.connect("realize", self._on_realize)

    def _on_realize(self, *_a):
        # Fully click-through — nothing in this window should ever intercept
        # input, the point is to sit over the real desktop/game untouched.
        self.get_surface().set_input_region(cairo.Region())

    def set_params(self, params, visible_groups):
        self.params = params
        self.visible_groups = visible_groups
        self._surface = None  # force rebuild at next draw
        self.da.queue_draw()

    def _on_draw(self, da, cr, width, height):
        if self._surface is None or self._surface_wh != (width, height):
            clusters, _anchor_x, _center = compute_layout(width, height)
            groups = []
            for name in _ALL_GROUPS:
                if not self.visible_groups.get(name, True):
                    continue
                x, y, w, h, _scale = clusters[name]
                cx, cy = x + w / 2, y + h / 2
                r = max(w, h) / 2 * self.params["radius_mult"]
                groups.append((cx, cy, r))
            self._surface = render_field(
                width, height, groups,
                low=self.params["low"], high=self.params["high"],
                max_alpha=self.params["max_alpha"], power=self.params["power"],
            )
            self._surface_wh = (width, height)
        cr.set_source_surface(self._surface, 0, 0)
        cr.paint()


class ControlWin(Gtk.ApplicationWindow):
    """Ordinary desktop window — sliders and checkboxes only, no preview of
    its own. Drive the real OverlayWin instead of rendering a stand-in."""

    def __init__(self, application, overlay):
        super().__init__(application=application, title="Backdrop tuning — controls",
                          default_width=320, default_height=560)
        self.overlay = overlay
        self.params = dict(_DEFAULTS)
        self.visible_groups = {g: True for g in _ALL_GROUPS}
        self._redraw_src = None

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        self.set_child(box)

        self._add_slider(box, "radius_mult", "Group radius ×", 0.3, 4.0, 0.01)
        self._add_slider(box, "low", "Field low (visible from)", 0.0, 2.0, 0.01)
        self._add_slider(box, "high", "Field high (saturates at)", 0.1, 3.0, 0.01)
        self._add_slider(box, "max_alpha", "Max darkness", 0.0, 1.0, 0.01)
        self._add_slider(box, "power", "Falloff power", 0.5, 6.0, 0.1)

        box.append(Gtk.Separator())
        box.append(Gtk.Label(label="Visible groups", xalign=0))
        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        for i, name in enumerate(LEFT_STACK):
            grid.attach(self._group_check(name), 0, i, 1, 1)
        for i, name in enumerate(RIGHT_STACK):
            grid.attach(self._group_check(name), 1, i, 1, 1)
        box.append(grid)

        box.append(Gtk.Separator())
        self.status = Gtk.Label(label="", xalign=0, wrap=True)
        box.append(self.status)

        self._push()

    def _group_check(self, name):
        cb = Gtk.CheckButton(label=name, active=True)
        cb.connect("toggled", self._on_group_toggled, name)
        return cb

    def _on_group_toggled(self, cb, name):
        self.visible_groups[name] = cb.get_active()
        self._schedule_push()

    def _add_slider(self, box, key, label, lo, hi, step):
        box.append(Gtk.Label(label=label, xalign=0))
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL)
        scale.set_range(lo, hi)
        scale.set_value(self.params[key])
        scale.set_digits(3)
        scale.set_draw_value(True)
        scale.connect("value-changed", self._on_slider, key)
        box.append(scale)

    def _on_slider(self, scale, key):
        self.params[key] = scale.get_value()
        self._schedule_push()

    def _schedule_push(self):
        if self._redraw_src is not None:
            GLib.source_remove(self._redraw_src)
        self._redraw_src = GLib.timeout_add(40, self._push)

    def _push(self):
        self._redraw_src = None
        self.overlay.set_params(dict(self.params), dict(self.visible_groups))
        n = sum(1 for v in self.visible_groups.values() if v)
        self.status.set_label(f"{n} groups visible")
        self._save_params()
        return GLib.SOURCE_REMOVE

    def _save_params(self):
        data = dict(self.params)
        data["visible_groups"] = sorted(n for n, v in self.visible_groups.items() if v)
        with open(_OUT_PATH, "w") as f:
            json.dump(data, f, indent=2)


class TuneApp(Gtk.Application):
    def do_activate(self):
        overlay = OverlayWin(self)
        overlay.present()
        control = ControlWin(self, overlay)
        control.present()


if __name__ == "__main__":
    TuneApp(application_id="de.plasma_deckery.hud.tunebackdrop").run([])
