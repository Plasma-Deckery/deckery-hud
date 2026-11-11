"""
app.py — GTK Application: D-Bus service lifecycle and show/hide/toggle logic.

Persistent service (de.plasma_deckery.hud).  Window starts hidden;
Toggle/Show/Hide D-Bus methods control visibility.
"""

import dataclasses
import signal
import os
import time
import atexit
import importlib
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib

from ipc import (makima_pause, makima_resume, makima_analog_on, makima_analog_off,
                 load_state, _STATE, auth_daemon_present, start_auth_session,
                 start_pin_change)
import win
import layout_choice
from osd_win import OsdWin
from reveal import Reveal, deadline_delay_ms
from elements import PAD_ELEMENTS
import settings
from settings import Settings
import theme

def _split_mode():
    """Read at call time, not import: the layout can be switched while
    running (win.py gets reloaded)."""
    return win._LAYOUT_MODE == "split"


# ── D-Bus ─────────────────────────────────────────────────────────────────────
_DBUS_NAME = "de.plasma_deckery.hud"
_DBUS_PATH = "/de/plasma_deckery/hud"
_DBUS_XML  = """
<node>
  <interface name="de.plasma_deckery.hud">
    <method name="Toggle"/>
    <method name="Show"/>
    <method name="Hide"/>
    <method name="ToggleOsd"/>
  </interface>
</node>
"""


class App(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=_DBUS_NAME,
            flags=Gio.ApplicationFlags.IS_SERVICE,
        )
        self._win               = None
        self._osd_win           = None
        self._osd_enabled       = True
        self._remapping_enabled = True
        # Re-checked every time the HUD opens: deckery-auth may be installed or
        # stopped while we are running, and the button should follow.
        self._auth_available    = False
        self._state             = {}
        self._monitor           = None
        self._reg_id            = 0
        # The full HUD is open (paused, takes input). Split mode can also
        # show single groups with this False — see Reveal / _reveal_sync.
        self._full              = False
        self._settings          = Settings()
        self._settings_monitor  = None
        self._settings_reload   = 0   # pending debounce source id
        self._reveal            = Reveal(self._settings.reveal)
        self._deadline_src      = None
        self._analog_on         = False

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

        settings.ensure_file()
        self._settings    = settings.load()
        self._osd_enabled = self._settings.osd.enabled
        settings._set_debug(self._settings.debug.enabled)
        self._reveal   = Reveal(self._settings.reveal)
        self._apply_theme(redraw=False)

        self._state    = load_state()
        self._state_stamp = None
        self._win      = win.Win(application=self, settings=self._settings.reveal)
        self._osd_win = OsdWin(application=self)
        self._osd_win.configure(self._settings.osd.animation, _split_mode())
        self._osd_win.on_state(self._state)
        if self._osd_enabled:
            self._osd_win.present()
        if _split_mode():
            GLib.idle_add(self._win.prewarm, self._state)

        # Shared FileMonitor — dispatches state to both windows.
        # The directory comes from _STATE rather than being named here: makima
        # writes into $XDG_RUNTIME_DIR now, and a second hardcoded "/tmp" would
        # have left this watching a directory nothing writes to.
        _dir = Gio.File.new_for_path(os.path.dirname(_STATE))
        self._monitor = _dir.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_file_changed)

        # The directory rather than the file: editors that save by writing a
        # new file and renaming it over the old one (vim, Kate) would leave a
        # file monitor watching an inode that no longer exists.
        _settings_dir = settings.settings_path().parent
        try:
            _settings_dir.mkdir(parents=True, exist_ok=True)
            self._settings_monitor = Gio.File.new_for_path(str(_settings_dir)).monitor_directory(
                Gio.FileMonitorFlags.NONE, None)
            self._settings_monitor.connect("changed", self._on_settings_changed)
        except (OSError, GLib.Error) as e:
            print(f"deckery-hud settings: {_settings_dir} not watched ({e})")

    def do_activate(self):
        """Called by `dbus-send … Activate` or when a second instance is launched."""
        if self._win is not None and not self._full:
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
        # makima's atomic rename arrives as two events (created, then
        # changes-done-hint). Parsing on both doubled the cost of every update,
        # and with the analog export on there are up to 90 of them a second.
        try:
            st = os.stat(_STATE)
            stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = None
        if stamp is not None and stamp == self._state_stamp:
            return
        self._state_stamp = stamp
        self._state = load_state()
        if self._win.is_visible():
            self._win.on_state(self._state)
        if not self._full and self._osd_enabled and self._osd_win.is_visible():
            self._osd_win.on_state(self._state)
        if _split_mode():
            self._reveal_sync()

    # ── Single groups (split mode, B-12) ──────────────────────────────────

    def _reveal_sync(self):
        """Hand the window what each group should show right now, and wake
        up again when a detector's threshold comes due with no new state
        (holding still writes nothing)."""
        if self._deadline_src is not None:
            GLib.source_remove(self._deadline_src)
            self._deadline_src = None
        wants = self._reveal.update(self._state, time.monotonic())
        if wants and not self._win.is_visible():
            self._win.on_state(self._state)
        self._win.set_wants(wants)
        deadline = self._reveal.next_deadline()
        if deadline is not None:
            self._deadline_src = GLib.timeout_add(deadline_delay_ms(deadline, time.monotonic()),
                                                  self._on_reveal_deadline)

    def _on_reveal_deadline(self):
        self._deadline_src = None
        self._reveal_sync()
        return False   # one shot

    def _on_groups_changed(self):
        """Called by the window whenever the set of visible groups changes.
        Live trackpad positions only while a pad is on screen: the export
        costs makima and us a lot (B-13 measured 23-41 % of a core with the
        HUD closed). Switched off only once the pads are fully gone, not at
        the start of their exit — dropping the data mid-slide changed the
        pad legend and forced a re-render right in the middle of it."""
        want = self._full or bool(PAD_ELEMENTS & self._win.visible_groups())
        if want != self._analog_on:
            self._analog_on = want
            (makima_analog_on if want else makima_analog_off)()

    # ── Settings file ─────────────────────────────────────────────────────

    def _on_settings_changed(self, _monitor, file, _other, _event_type):
        if file.get_basename() != settings.settings_path().name:
            return
        # One save arrives as several events (Gio reports a rename twice, and
        # editors write in steps): wait until they stop, then read once.
        if self._settings_reload:
            GLib.source_remove(self._settings_reload)
        self._settings_reload = GLib.timeout_add(150, self._reload_settings)

    def _reload_settings(self):
        self._settings_reload = 0
        if not settings.settings_path().exists():
            # Deleted to start over: the defaults apply, and the template with
            # every setting explained comes back.
            settings.ensure_file()
        new = settings.load(previous=self._settings)
        old, self._settings = self._settings, new
        self._apply_settings(old, new)
        return False   # one shot

    def _apply_settings(self, old, new):
        """The one place where a changed setting takes effect. Only keys that
        actually changed get here — the HUD's own writes come back through the
        file monitor and find nothing to do."""
        changed = settings.diff(old, new)
        if "osd.enabled" in changed:
            self._set_osd_enabled(new.osd.enabled)
        if "osd.animation" in changed:
            self._osd_win.configure(new.osd.animation, _split_mode())
        if "debug.enabled" in changed:
            settings._set_debug(new.debug.enabled)
        if "layout.design" in changed and hasattr(self, "switch_layout"):
            # B-05: switches in process; persist=False because the file already says so.
            self.switch_layout(new.layout.design, persist=False)
        if "layout.theme" in changed:
            self._apply_theme()
        if any(k.startswith("reveal.") for k in changed):
            self._reveal.set_settings(new.reveal)
            self._win.set_settings(new.reveal)
            if _split_mode():
                self._reveal_sync()   # re-evaluate now, e.g. a detector switched off

    def _apply_theme(self, redraw=True):
        """Make the theme from the settings current (B-20). Classic always
        draws with the default theme — themes are a split-design thing."""
        name = self._settings.layout.theme if _split_mode() else theme.DEFAULT
        if theme.activate(name) and redraw:
            # The renderers' caches key on the theme; a redraw rebuilds them.
            self._win.queue_draw_title()
            self._osd_win.configure(self._settings.osd.animation, _split_mode())

    # ── D-Bus method dispatch ─────────────────────────────────────────────

    def _on_dbus_call(self, conn, sender, obj_path, iface, method, params, invocation):
        if   method == "Toggle":    self.toggle_hud()
        elif method == "Show":      self.show_hud()
        elif method == "Hide":      self.hide_hud()
        elif method == "ToggleOsd": self.toggle_osd()
        invocation.return_value(GLib.Variant("()", ()))

    # ── Public API ────────────────────────────────────────────────────────

    def show_hud(self):
        if self._win is None:
            return
        self._auth_available = auth_daemon_present()
        self._full = True
        self._osd_win.set_visible(False)
        makima_pause()
        self._win.on_state(self._state)
        if _split_mode():
            self._reveal.full = True
            self._reveal_sync()
        else:
            makima_analog_on()
            self._win.set_open(True)

    def hide_hud(self):
        if self._win is None:
            return
        self._full = False
        if _split_mode():
            # Groups a detector still wants stay; the rest slides out. The
            # analog export follows in _on_groups_changed.
            self._reveal.full = False
            self._reveal_sync()
        else:
            self._win.set_open(False, on_closed=makima_analog_off)
        if self._remapping_enabled:
            makima_resume()
        if self._osd_enabled and self._remapping_enabled:
            self._osd_win.present()

    def show_auth(self):
        """Close the HUD, then bring up the PIN overlay.

        In that order, and with a beat in between: the overlay is a layer-shell
        surface that covers everything, and starting it while the HUD is still
        on its way out leaves the two fighting over the screen.
        """
        self.hide_hud()
        GLib.timeout_add(150, self._start_auth_once)

    def _start_auth_once(self):
        start_auth_session()
        return False   # one shot

    def change_auth(self):
        """Close the HUD, then start the PIN change (old PIN, then new twice)."""
        self.hide_hud()
        GLib.timeout_add(150, self._start_pin_change_once)

    def _start_pin_change_once(self):
        start_pin_change()
        return False   # one shot

    def switch_layout(self, mode, persist=True):
        """Switch between the classic and split design (the in-HUD buttons).

        No-op if the window already runs `mode`. persist=False is for a
        switch that came *from* the stored choice (the settings file edited
        by hand): the file already holds `mode`, so it is not written back.
        If saving fails the switch still happens, it just won't survive a
        restart.

        win.py picks its design once at import and only sets up what that
        design needs, so the window is rebuilt rather than switched: reload
        win.py with the new choice, build a fresh Win, drop the old one.
        Deferred to idle because it is called from the old window's own
        click handler, which must not destroy its widget mid-dispatch.
        Everything that lives here (OSD/remap toggles, makima pause, the
        Reveal) is untouched; an open HUD stays open in the new design."""
        def _switch():
            if win._LAYOUT_MODE == mode:
                return False
            if persist:
                layout_choice.remember(mode)
            if self._deadline_src is not None:
                GLib.source_remove(self._deadline_src)
                self._deadline_src = None
            old = self._win
            with layout_choice.building(mode):
                importlib.reload(win)
            self._apply_theme(redraw=False)
            self._win = win.Win(application=self, settings=self._settings.reveal)
            old.retire()
            self._win.on_state(self._state)
            self._osd_win.configure(self._settings.osd.animation, _split_mode())
            if _split_mode():
                # Build the layers first, as at startup: without it the
                # first open does that inside its first frame and pops
                # instead of sliding (B-02). Opening while prewarm holds
                # the window is a case _need_surface already handles. The
                # full HUD and any group a detector wants come back
                # through the reveal path, which also drives analog.
                self._win.prewarm(self._state)
                self._reveal.full = self._full
                self._reveal_sync()
            else:
                # Classic shows the full HUD or nothing, and keeps analog
                # on exactly while it is open.
                self._analog_on = self._full
                (makima_analog_on if self._full else makima_analog_off)()
                if self._full:
                    self._win.set_open(True)
            return False   # one shot
        GLib.idle_add(_switch)

    def toggle_hud(self):
        if self._win is None:
            return
        if self._full:
            self.hide_hud()
        else:
            self.show_hud()

    def toggle_remapping(self):
        """Called from Win title bar toggle button.
        Disabling: pauses makima if not already paused, blocks resume on HUD close.
        Enabling: only removes the block — no resume, HUD close handles that."""
        self._remapping_enabled = not self._remapping_enabled
        if not self._remapping_enabled:
            paused = self._state.get("context", {}).get("paused", False)
            if not paused:
                makima_pause()
                self._state.setdefault("context", {})["paused"] = True
            self._osd_win.set_visible(False)
        self._win.queue_draw_title()

    def toggle_osd(self):
        """Called from Win title bar toggle button and the tray (D-Bus ToggleOsd).
        The choice is saved, so it survives a restart."""
        self._set_osd_enabled(not self._osd_enabled)
        # Taken over before the write comes back through the file monitor, so
        # that event finds nothing changed.
        self._settings = dataclasses.replace(
            self._settings,
            osd=dataclasses.replace(self._settings.osd, enabled=self._osd_enabled))
        settings.remember("osd.enabled", self._osd_enabled)

    def _set_osd_enabled(self, enabled):
        self._osd_enabled = enabled
        if not self._osd_enabled:
            self._osd_win.set_visible(False)
        elif not self._full:
            self._osd_win.on_state(self._state)
            self._osd_win.present()
        # Redraw Win title bar to reflect new toggle state
        self._win.queue_draw_title()
