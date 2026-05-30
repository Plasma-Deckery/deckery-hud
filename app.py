"""
app.py — GTK application, window, file monitor, state loading, IPC.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
gi.require_version('Rsvg', '2.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, GLib, Gio, Gtk4LayerShell as LayerShell, Rsvg
import cairo, json, os, socket, signal, time

from layout import HUD_W, HUD_H, _PAUSE_X, _PAUSE_Y, _PAUSE_W, _PAUSE_H
from renderer import draw_hud
from toast import draw_toast
from anim import HoverAnim
# from kde_osd import kde_osd_setup

# ── Paths ─────────────────────────────────────────────────────────────────────
_DIR       = os.path.expanduser("~/Programming/deckery-hud")
_STATE     = "/tmp/makima-state.json"
_FALLBACK  = f"{_DIR}/state.json"
_FRONT_SVG = f"{_DIR}/assets/steamdeckFront.svg"
_BACK_SVG  = f"{_DIR}/assets/steamdeckBack.svg"

_MAKIMA_SOCK = "/tmp/makima-control.sock"
_PID_FILE    = "/tmp/deckery-hud.pid"

_TOAST_TTL_MS   = 1500   # toast display duration in milliseconds
_TOAST_FRAME_MS = 33     # ~30 fps during fade animation

# ── Makima IPC ────────────────────────────────────────────────────────────────

def _makima_ipc(cmd: str) -> None:
    """Send a command to makima's Unix control socket. Silently ignores errors."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(_MAKIMA_SOCK)
            s.sendall((cmd + "\n").encode())
    except Exception:
        pass


def _makima_pause():
    _makima_ipc("pause")


def _makima_resume():
    _makima_ipc("resume")


# ── State loading ─────────────────────────────────────────────────────────────

def _load_state():
    for path in (_STATE, _FALLBACK):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {"context": {"config_stack": ["—"]}, "bindings": {}, "modifier_active": {}}


# ── GTK app ───────────────────────────────────────────────────────────────────

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="de.plasma-deckery.hud")

    def do_activate(self):
        # Write PID so deckery-hud-toggle can kill the right process.
        try:
            with open(_PID_FILE, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            pass
        # SIGTERM (sent by deckery-hud-toggle) must go through GLib so that
        # do_shutdown is called and makima gets resumed.
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)
        Win(application=self).present()

    def do_shutdown(self):
        # Called on every exit path — close button, toggle kill, crash.
        # Ensures makima is always resumed when the HUD goes away.
        _makima_resume()
        try:
            os.unlink(_PID_FILE)
        except Exception:
            pass
        Gtk.Application.do_shutdown(self)


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

        # ── Load SVGs ─────────────────────────────────────────────────────
        self._front = Rsvg.Handle.new_from_file(_FRONT_SVG)
        self._back  = Rsvg.Handle.new_from_file(_BACK_SVG)

        # ── State ─────────────────────────────────────────────────────────
        self._state          = _load_state()
        self._region_set     = False
        self._toast_source   = None    # GLib timer handle for toast animation
        self._last_action_ts = 0.0    # ts of last known last_action
        self._active_toasts  = []     # list of in-flight last_action snapshots
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

        # ── Gio FileMonitor on /tmp/ (atomic rename → watch dir, not file) ─
        # Subscribe BEFORE sending pause so we don't miss makima's state update.
        _tmp = Gio.File.new_for_path("/tmp")
        self._monitor = _tmp.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_file_changed)

        # ── Makima: pause on open ─────────────────────────────────────────
        _makima_pause()

        # ── KDE OSD role (deferred so layer-shell setup is committed first) ─
        # self.connect("realize", lambda w: GLib.idle_add(kde_osd_setup, w))

    def _badge_screen_rect(self):
        """Pause badge position in screen (drawing-area) coordinates."""
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        return hx + _PAUSE_X, hy + _PAUSE_Y, _PAUSE_W, _PAUSE_H

    def _on_click(self, _gesture, _n, x, y):
        bx, by, bw, bh = self._badge_screen_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            paused = self._state.get("context", {}).get("paused", False)
            if paused:
                _makima_resume()
                self._state.setdefault("context", {})["paused"] = False
            else:
                _makima_pause()
                self._state.setdefault("context", {})["paused"] = True
            self._da.queue_draw()
        else:
            # Treat everything outside the badge as a close-button click
            # (the input region is limited to badge + close btn anyway)
            self.get_application().quit()

    def _on_motion(self, _ctrl, x, y):
        bx, by, bw, bh = self._badge_screen_rect()
        self._pause_anim.set(bx <= x <= bx + bw and by <= y <= by + bh)

    def _on_motion_leave(self, _ctrl):
        self._pause_anim.set(False)

    def _on_file_changed(self, _monitor, file, _other, _event_type):
        if file.get_basename() == os.path.basename(_STATE):
            self._state = _load_state()
            self._da.queue_draw()
            self._schedule_toast_animation()

    def _schedule_toast_animation(self):
        """Append new last_action to the live list and ensure the frame timer runs."""
        la = self._state.get("last_action") or {}
        ts = la.get("ts", 0.0)
        if ts <= self._last_action_ts:
            return   # same or older action — nothing to do

        self._last_action_ts = ts
        self._active_toasts.append(dict(la))   # snapshot — survives next state reload

        # Start frame loop if not already running
        if self._toast_source is None:
            self._toast_source = GLib.timeout_add(_TOAST_FRAME_MS, self._on_toast_frame)

    def _on_toast_frame(self):
        # Drop expired toasts
        cutoff = time.time() - _TOAST_TTL_MS / 1000
        self._active_toasts = [t for t in self._active_toasts
                               if t.get("ts", 0) > cutoff]
        self._da.queue_draw()
        if not self._active_toasts:
            self._toast_source = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _draw(self, _da, cr, sw, sh, _):
        # Set Wayland input region once (close button + pause badge)
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

        # Toast in screen coordinates (outside HUD translate)
        draw_toast(cr, sw, sh, self._active_toasts)
