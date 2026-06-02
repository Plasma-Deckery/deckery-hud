"""
app.py — GTK Application: D-Bus service lifecycle and show/hide/toggle logic.

Persistent service (de.plasma_deckery.hud).  Window starts hidden;
Toggle/Show/Hide D-Bus methods control visibility.
"""

import signal
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib

from ipc import makima_pause, makima_resume, makima_analog_on, makima_analog_off
from win import Win

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
        self._win    = None
        self._reg_id = 0

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
        """GTK is ready here — create the hidden window."""
        Gtk.Application.do_startup(self)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)
        self._win = Win(application=self)

    def do_activate(self):
        """Called by `dbus-send … Activate` or when a second instance is launched."""
        if self._win is not None and not self._win.is_visible():
            self.show_hud()

    def do_shutdown(self):
        """Always resume makima and disable analog writes on exit."""
        makima_analog_off()
        makima_resume()
        Gtk.Application.do_shutdown(self)

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
        makima_pause()
        makima_analog_on()
        self._win.present()

    def hide_hud(self):
        if self._win is None:
            return
        # Reset input-region flag — layer shell recreates the surface on next present()
        self._win._region_set = False
        self._win.set_visible(False)
        makima_analog_off()
        makima_resume()

    def toggle_hud(self):
        if self._win is None:
            return
        if self._win.is_visible():
            self.hide_hud()
        else:
            self.show_hud()
