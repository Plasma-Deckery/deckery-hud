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
import time

from ipc import makima_pause, makima_resume, _FRONT_SVG, _BACK_SVG
from layout import HUD_W, HUD_H, _TITLE_H, _PAUSE_X, _PAUSE_Y, _PAUSE_W, _PAUSE_H
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
        self._state          = {}
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

        # Window starts hidden — App.show_hud() will present() and pause makima.

    # ── Hit-rect helpers ──────────────────────────────────────────────────

    def _badge_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        return hx + _PAUSE_X, hy + _PAUSE_Y, _PAUSE_W, _PAUSE_H

    def _close_btn_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        return hx + HUD_W - 44, hy, 44, _TITLE_H

    # ── Input handlers ────────────────────────────────────────────────────

    def _osd_btn_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        # OSD toggle button: 44×20px, left of close area
        bw, bh = 48, 20
        bx = hx + HUD_W - 28 - 8 - bw    # 8px gap = close circle right margin
        by = hy + (_TITLE_H - bh) / 2
        return bx, by, bw, bh

    def _close_btn_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        return hx + HUD_W - 44, hy, 44, _TITLE_H

    def _on_click(self, _gesture, _n, x, y):
        bx, by, bw, bh = self._badge_screen_rect()
        mx, my, mw, mh = self._osd_btn_screen_rect()
        cx, cy, cw, ch = self._close_btn_screen_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            paused = self._state.get("context", {}).get("paused", False)
            if paused:
                makima_resume()
                self._state.setdefault("context", {})["paused"] = False
            else:
                makima_pause()
                self._state.setdefault("context", {})["paused"] = True
            self._da.queue_draw()
        elif mx <= x <= mx + mw and my <= y <= my + mh:
            self.get_application().toggle_osd()
        elif cx <= x <= cx + cw and cy <= y <= cy + ch:
            self.get_application().hide_hud()
        # else: dead zone — ignore

    def _on_motion(self, _ctrl, x, y):
        bx, by, bw, bh = self._badge_screen_rect()
        self._pause_anim.set(bx <= x <= bx + bw and by <= y <= by + bh)

    def _on_motion_leave(self, _ctrl):
        self._pause_anim.set(False)

    # ── State update (called by App on file change) ───────────────────────

    def on_state(self, state):
        self._state = state
        self._da.queue_draw()
        self._schedule_toast_animation()

    def queue_draw_title(self):
        self._da.queue_draw()

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
        try:
            self._draw_inner(cr, sw, sh)
        except Exception:
            import traceback
            traceback.print_exc()
            cr.set_operator(cairo.Operator.CLEAR)
            cr.paint()

    def _draw_inner(self, cr, sw, sh):
        # Set Wayland input region once per show cycle (close button + pause badge).
        # _region_set is reset to False by App.hide_hud() before each new present().
        if not self._region_set:
            self._region_set = True
            hx = (sw - HUD_W) // 2
            hy = (sh - HUD_H) // 2
            close_btn  = cairo.RectangleInt(hx + HUD_W - 44, hy, 44, _TITLE_H)
            badge      = cairo.RectangleInt(
                int(hx + _PAUSE_X), int(hy + _PAUSE_Y),
                int(_PAUSE_W), int(_PAUSE_H))
            mx, my, mw, mh = self._osd_btn_screen_rect()
            mini_btn   = cairo.RectangleInt(int(mx), int(my), int(mw), int(mh))
            region = cairo.Region(close_btn)
            region.union(cairo.Region(badge))
            region.union(cairo.Region(mini_btn))
            self.get_surface().set_input_region(region)

        cr.set_operator(cairo.Operator.CLEAR)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        cr.save()
        cr.translate((sw - HUD_W) / 2, (sh - HUD_H) / 2)
        draw_hud(cr, self._front, self._back, self._state,
                 hover_t=self._pause_anim.value,
                 osd_enabled=self.get_application()._osd_enabled)
        cr.restore()

        draw_toast(cr, sw, sh, self._active_toasts)
