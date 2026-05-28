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
import cairo, json, os, socket, signal

from layout import HUD_W, HUD_H
from renderer import draw_hud
# from kde_osd import kde_osd_setup

# ── Paths ─────────────────────────────────────────────────────────────────────
_DIR       = os.path.expanduser("~/Programming/deckery-hud")
_STATE     = "/tmp/makima-state.json"
_FALLBACK  = f"{_DIR}/state.json"
_FRONT_SVG = f"{_DIR}/assets/steamdeckFront.svg"
_BACK_SVG  = f"{_DIR}/assets/steamdeckBack.svg"

_MAKIMA_SOCK = "/tmp/makima-control.sock"
_PID_FILE    = "/tmp/deckery-hud.pid"

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
        self._state = _load_state()
        self._region_set = False

        # ── Drawing area ──────────────────────────────────────────────────
        da = Gtk.DrawingArea()
        da.set_draw_func(self._draw, None)
        self.set_child(da)
        self._da = da

        # Click handler — fires only in the Wayland input region (close btn)
        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_close_click)
        da.add_controller(click)

        # ── Makima: pause on open ─────────────────────────────────────────
        _makima_pause()
        # Reflect paused state immediately — don't wait for the JSON to be
        # rewritten by makima's async socket handler.
        self._state.setdefault("context", {})["paused"] = True

        # ── Gio FileMonitor on /tmp/ (atomic rename → watch dir, not file) ─
        _tmp = Gio.File.new_for_path("/tmp")
        self._monitor = _tmp.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_file_changed)

        # ── KDE OSD role (deferred so layer-shell setup is committed first) ─
        # self.connect("realize", lambda w: GLib.idle_add(kde_osd_setup, w))

    def _on_close_click(self, *_):
        self.get_application().quit()

    def _on_file_changed(self, _monitor, file, _other, _event_type):
        if file.get_basename() == "makima-state.json":
            self._state = _load_state()
            self._da.queue_draw()

    def _draw(self, _da, cr, sw, sh, _):
        # Set Wayland input region once (close button only)
        if not self._region_set:
            self._region_set = True
            hx = (sw - HUD_W) // 2
            hy = (sh - HUD_H) // 2
            btn = cairo.RectangleInt(hx + HUD_W - 36, hy, 36, 36)
            self.get_surface().set_input_region(cairo.Region(btn))

        cr.set_operator(cairo.Operator.CLEAR)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        cr.save()
        cr.translate((sw - HUD_W) / 2, (sh - HUD_H) / 2)
        draw_hud(cr, self._front, self._back, self._state)
        cr.restore()
