"""
app.py — GTK Application: D-Bus service lifecycle and show/hide/toggle logic.

Persistent service (de.plasma_deckery.hud).  Window starts hidden;
Toggle/Show/Hide D-Bus methods control visibility.
"""

import signal
import os
import atexit
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib

from ipc import makima_pause, makima_resume, makima_analog_on, makima_analog_off, load_state, _STATE
from win import Win
from osd_win import OsdWin

# ── D-Bus ─────────────────────────────────────────────────────────────────────
_DBUS_NAME = "de.plasma_deckery.hud"
_DBUS_PATH = "/de/plasma_deckery/hud"
_DBUS_XML  = """
<node>
  <interface name="de.plasma_deckery.hud">
    <method name="Toggle"/>
    <method name="Show"/>
    <method name="Hide"/>
  </interface>
</node>
"""


class App(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=_DBUS_NAME,
            flags=Gio.ApplicationFlags.IS_SERVICE,
        )
        self._win          = None
        self._osd_win     = None
        self._osd_enabled = True
        self._state        = {}
        self._monitor      = None
        self._reg_id       = 0

    # ── GApplication lifecycle ────────────────────────────────────────────

    def do_dbus_register(self, connection, object_path):
        """Called after D-Bus name is acquired, before startup.
        Register the custom interface here — no GTK calls allowed yet."""
        Gtk.Application.do_dbus_register(self, connection, object_path)
        info = Gio.DBusNodeInfo.new_for_xml(_DBUS_XML)
        self._reg_id = connection.register_object(
            _DBUS_PATH,
            info.interfaces[0],
            self._on_dbus_call,
            None, None,
        )
        return True

    def do_dbus_unregister(self, connection, object_path):
        if self._reg_id:
            connection.unregister_object(self._reg_id)
            self._reg_id = 0
        Gtk.Application.do_dbus_unregister(self, connection, object_path)

    def do_startup(self):
        """GTK is ready here — create windows and start file monitor."""
        Gtk.Application.do_startup(self)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)
        # Safety net: resume makima on any exit path (crash, SIGKILL aftermath, etc.)
        atexit.register(makima_analog_off)
        atexit.register(makima_resume)

        self._state    = load_state()
        self._win      = Win(application=self)
        self._osd_win = OsdWin(application=self)
        self._osd_win.on_state(self._state)
        self._osd_win.present()

        # Shared FileMonitor — dispatches state to both windows
        _tmp = Gio.File.new_for_path("/tmp")
        self._monitor = _tmp.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_file_changed)

    def do_activate(self):
        """Called by `dbus-send … Activate` or when a second instance is launched."""
        if self._win is not None and not self._win.is_visible():
            self.show_hud()

    def do_shutdown(self):
        """Always resume makima and disable analog writes on exit."""
        makima_analog_off()
        makima_resume()
        Gtk.Application.do_shutdown(self)

    # ── File monitor ──────────────────────────────────────────────────────

    def _on_file_changed(self, _monitor, file, _other, _event_type):
        if file.get_basename() != os.path.basename(_STATE):
            return
        self._state = load_state()
        if self._win.is_visible():
            self._win.on_state(self._state)
        elif self._osd_enabled and self._osd_win.is_visible():
            self._osd_win.on_state(self._state)

    # ── D-Bus method dispatch ─────────────────────────────────────────────

    def _on_dbus_call(self, conn, sender, obj_path, iface, method, params, invocation):
        if   method == "Toggle": self.toggle_hud()
        elif method == "Show":   self.show_hud()
        elif method == "Hide":   self.hide_hud()
        invocation.return_value(GLib.Variant("()", ()))

    # ── Public API ────────────────────────────────────────────────────────

    def show_hud(self):
        if self._win is None:
            return
        self._osd_win.set_visible(False)
        makima_pause()
        makima_analog_on()
        self._win.on_state(self._state)
        self._win.present()

    def hide_hud(self):
        if self._win is None:
            return
        # Reset input-region flag — layer shell recreates the surface on next present()
        self._win._region_set = False
        self._win.set_visible(False)
        makima_analog_off()
        makima_resume()
        if self._osd_enabled:
            self._osd_win.present()

    def toggle_hud(self):
        if self._win is None:
            return
        if self._win.is_visible():
            self.hide_hud()
        else:
            self.show_hud()

    def toggle_osd(self):
        """Called from Win title bar toggle button."""
        self._osd_enabled = not self._osd_enabled
        if not self._osd_enabled:
            self._osd_win.set_visible(False)
        elif not self._win.is_visible():
            self._osd_win.on_state(self._state)
            self._osd_win.present()
        # Redraw Win title bar to reflect new toggle state
        self._win.queue_draw_title()
