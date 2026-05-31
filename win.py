"""
win.py — Deckery HUD window (GTK4, layer-shell, Cairo drawing).

Created hidden by App; shown/hidden via App.show_hud() / App.hide_hud().
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
gi.require_version('Rsvg', '2.0')
from gi.repository import Gtk, Gio, Gtk4LayerShell as LayerShell, Rsvg, GLib
import cairo
import os
import time

from ipc import makima_pause, makima_resume, load_state, _STATE, _FRONT_SVG, _BACK_SVG
from layout import HUD_W, HUD_H, _PAUSE_X, _PAUSE_Y, _PAUSE_W, _PAUSE_H
from renderer import draw_hud
from toast import draw_toast
from anim import HoverAnim

_TOAST_TTL_MS   = 1500   # toast display duration in milliseconds
_TOAST_FRAME_MS = 33     # ~30 fps during fade animation


class Win(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        self.set_title("Deckery HUD")
        self.set_decorated(False)

        # ── Layer shell — full-screen transparent overlay ─────────────────
        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_namespace(self, "deckery-hud")
        for edge in (LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT,
                     LayerShell.Edge.TOP,  LayerShell.Edge.BOTTOM):
            LayerShell.set_anchor(self, edge, True)

        # Transparent window background
        css = Gtk.CssProvider()
        css.load_from_string("window { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER)

        # ── SVGs ──────────────────────────────────────────────────────────
        self._front = Rsvg.Handle.new_from_file(_FRONT_SVG)
        self._back  = Rsvg.Handle.new_from_file(_BACK_SVG)

        # ── State ─────────────────────────────────────────────────────────
        self._state          = load_state()
        self._region_set     = False
        self._toast_source   = None
        self._last_action_ts = 0.0
        self._active_toasts  = []
        self._pause_anim     = HoverAnim(lambda: self._da.queue_draw())

        # ── Drawing area ──────────────────────────────────────────────────
        da = Gtk.DrawingArea()
        da.set_draw_func(self._draw, None)
        self.set_child(da)
        self._da = da

        # Click handler — fires only in the Wayland input region
        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_click)
        da.add_controller(click)

        # Hover detection for the pause/resume badge
        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        motion.connect("leave",  self._on_motion_leave)
        da.add_controller(motion)

        # ── File monitor on /tmp/ (atomic rename → watch dir, not file) ───
        _tmp = Gio.File.new_for_path("/tmp")
        self._monitor = _tmp.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_file_changed)

        # Window starts hidden — App.show_hud() will present() and pause makima.

    # ── Badge helpers ─────────────────────────────────────────────────────

    def _badge_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        return hx + _PAUSE_X, hy + _PAUSE_Y, _PAUSE_W, _PAUSE_H

    # ── Input handlers ────────────────────────────────────────────────────

    def _on_click(self, _gesture, _n, x, y):
        bx, by, bw, bh = self._badge_screen_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            paused = self._state.get("context", {}).get("paused", False)
            if paused:
                makima_resume()
                self._state.setdefault("context", {})["paused"] = False
            else:
                makima_pause()
                self._state.setdefault("context", {})["paused"] = True
            self._da.queue_draw()
        else:
            # Click outside badge → hide (service stays alive)
            self.get_application().hide_hud()

    def _on_motion(self, _ctrl, x, y):
        bx, by, bw, bh = self._badge_screen_rect()
        self._pause_anim.set(bx <= x <= bx + bw and by <= y <= by + bh)

    def _on_motion_leave(self, _ctrl):
        self._pause_anim.set(False)

    # ── State file monitor ────────────────────────────────────────────────

    def _on_file_changed(self, _monitor, file, _other, _event_type):
        if file.get_basename() == os.path.basename(_STATE):
            self._state = load_state()
            self._da.queue_draw()
            self._schedule_toast_animation()

    # ── Toast animation ───────────────────────────────────────────────────

    def _schedule_toast_animation(self):
        la = self._state.get("last_action") or {}
        ts = la.get("ts", 0.0)
        if ts <= self._last_action_ts:
            return
        self._last_action_ts = ts
        self._active_toasts.append(dict(la))
        if self._toast_source is None:
            self._toast_source = GLib.timeout_add(_TOAST_FRAME_MS, self._on_toast_frame)

    def _on_toast_frame(self):
        cutoff = time.time() - _TOAST_TTL_MS / 1000
        self._active_toasts = [t for t in self._active_toasts
                               if t.get("ts", 0) > cutoff]
        self._da.queue_draw()
        if not self._active_toasts:
            self._toast_source = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    # ── Drawing ───────────────────────────────────────────────────────────

    def _draw(self, _da, cr, sw, sh, _):
        # Set Wayland input region once per show cycle (close button + pause badge).
        # _region_set is reset to False by App.hide_hud() before each new present().
        if not self._region_set:
            self._region_set = True
            hx = (sw - HUD_W) // 2
            hy = (sh - HUD_H) // 2
            close_btn = cairo.RectangleInt(hx + HUD_W - 36, hy, 36, 36)
            badge     = cairo.RectangleInt(
                int(hx + _PAUSE_X), int(hy + _PAUSE_Y),
                int(_PAUSE_W), int(_PAUSE_H))
            region = cairo.Region(close_btn)
            region.union(cairo.Region(badge))
            self.get_surface().set_input_region(region)

        cr.set_operator(cairo.Operator.CLEAR)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        cr.save()
        cr.translate((sw - HUD_W) / 2, (sh - HUD_H) / 2)
        draw_hud(cr, self._front, self._back, self._state,
                 hover_t=self._pause_anim.value)
        cr.restore()

        draw_toast(cr, sw, sh, self._active_toasts)
