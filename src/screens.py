"""
screens.py — puts the HUD and the OSD on a screen (B-31): `[display] output`
(display.pick) applied through layer-shell's set_monitor, kept current as
screens come and go and as KWin's active output moves.

Rules:
- The HUD only moves while unmapped: an open HUD never jumps away under the
  user's hands; it goes to the right screen the next time it opens.
- The OSD goes where the HUD is while the HUD is mapped (its toasts and
  pills are the open HUD's), else to the chosen screen — moved at once.
- "auto" asks KWin for its active output (the focused window's screen):
  synchronously just before the HUD maps, every _POLL_MS otherwise — and
  only with two or more screens, so a lone Deck never makes the call.
- The HUD's screen changing while it is closed rebuilds its layers there
  ahead of time (Win.prewarm), as at startup: the first open on a new
  screen would otherwise build them inside its first frame.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gdk, Gio, GLib, Gtk4LayerShell as LayerShell

import display
import win
from settings import dbg

_POLL_MS = 1500
_SETTLE_MS = 600
# Focus going back and forth between screens would rebuild the HUD's layers
# (~0.6 s) on every switch: only a choice that held this long is prewarmed.
_REWARM_MS = 3000
_KWIN = ("org.kde.KWin", "/KWin", "org.kde.KWin", "activeOutputName")


class Screens:
    def __init__(self, app):
        self._app = app
        self._policy = "auto"
        self._active = None      # KWin's active output, connector name
        self._asking = False     # an async activeOutputName call is out
        self._warmed = None      # _key of the screen the HUD's layers are built for
        self._rewarm_src = 0
        self._monitors = Gdk.Display.get_default().get_monitors()
        self._monitors.connect("items-changed", self._on_monitors_changed)
        GLib.timeout_add(_POLL_MS, self._poll)

    def set_policy(self, policy):
        if policy != self._policy:
            self._policy = policy
            self.place()

    # ── KWin's active output ──────────────────────────────────────────────

    def _bus(self):
        return self._app.get_dbus_connection()

    def _ask_sync(self):
        bus = self._bus()
        if bus is None:
            return
        try:
            reply = bus.call_sync(*_KWIN, None, GLib.VariantType("(s)"),
                                  Gio.DBusCallFlags.NONE, 200, None)
            self._active = reply.unpack()[0] or None
        except GLib.Error:
            self._active = None   # not KWin, or it doesn't answer: the compositor decides

    def _poll(self):
        bus = self._bus()
        if (bus is not None and not self._asking and self._policy == "auto"
                and self._monitors.get_n_items() > 1):
            self._asking = True
            bus.call(*_KWIN, None, GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE,
                     500, None, self._on_active)
        return GLib.SOURCE_CONTINUE

    def _on_active(self, bus, result):
        self._asking = False
        try:
            active = bus.call_finish(result).unpack()[0] or None
        except GLib.Error:
            active = None
        if active != self._active:
            dbg(f"screens: active output {self._active} -> {active}")
            self._active = active
        # Every time, not only on a change: the HUD may have closed since,
        # and only now may it — and the OSD with it — follow.
        self.place()

    # ── Placing ───────────────────────────────────────────────────────────

    def _list(self):
        return [self._monitors.get_item(i) for i in range(self._monitors.get_n_items())]

    def _chosen(self):
        """The Gdk.Monitor `[display] output` names, or None (compositor's choice)."""
        mons = self._list()
        want = display.pick([m.get_connector() for m in mons], self._policy, self._active)
        return next((m for m in mons if m.get_connector() == want), None)

    @staticmethod
    def _on_screen(win):
        """The monitor a mapped window is on, else None."""
        surface = win.get_surface()
        if surface is None or not win.get_mapped():
            return None
        return Gdk.Display.get_default().get_monitor_at_surface(surface)

    @staticmethod
    def _set(win, mon):
        if LayerShell.get_monitor(win) != mon:
            LayerShell.set_monitor(win, mon)
            return True
        return False

    def before_hud_map(self, hud):
        """Win calls this right before it maps: the HUD's screen, chosen now.
        Whatever it then draws builds its layers for that screen."""
        if self._policy == "auto" and self._monitors.get_n_items() > 1:
            self._ask_sync()
        mon = self._chosen()
        self._set(hud, mon)
        self._warmed = _key(mon)
        dbg(f"screens: HUD maps on {self._warmed or 'the compositor choice'}")

    def place(self):
        """Apply the choice to whichever window may move now."""
        app = self._app
        hud, osd = app._win, app._osd_win
        if hud is None or osd is None:
            return
        mon = self._chosen()
        hud_on = self._on_screen(hud)
        if hud_on is None and self._set(hud, mon):
            dbg(f"screens: HUD -> {mon.get_connector() if mon else 'compositor'}")
            self._rewarm(hud, mon)
        target = hud_on or mon
        if self._set(osd, target):
            dbg(f"screens: OSD -> {target.get_connector() if target else 'compositor'}")

    def _rewarm(self, hud, mon):
        """Build the HUD's layers for its new screen while it is closed —
        only when that screen differs in size or scale from the last one."""
        if self._rewarm_src:
            GLib.source_remove(self._rewarm_src)
            self._rewarm_src = 0
        key = _key(mon)
        if key is None or self._warmed is None or key[1:] == self._warmed[1:]:
            return

        def fire():
            self._rewarm_src = 0
            if (win._LAYOUT_MODE == "split" and self._app._win is hud
                    and LayerShell.get_monitor(hud) == mon and not hud.get_mapped()):
                hud.prewarm(self._app._state)
            return GLib.SOURCE_REMOVE
        self._rewarm_src = GLib.timeout_add(_REWARM_MS, fire)

    def _on_monitors_changed(self, _model, _pos, removed, added):
        dbg(f"screens: monitors changed (-{removed} +{added}): "
            f"{[m.get_connector() for m in self._list()]}")
        app = self._app
        for w in (app._win, app._osd_win):
            # A window on a screen that went away: layer-shell keeps the
            # dead monitor otherwise.
            if w is not None and LayerShell.get_monitor(w) not in self._list() + [None]:
                LayerShell.set_monitor(w, None)
        if self._policy == "auto" and self._monitors.get_n_items() > 1:
            self._ask_sync()
        self.place()
        app._sync_osd()
        # A screen just plugged in has no connector name yet (GDK learns it
        # a moment later), so "external" can't pick it now: once more then.
        GLib.timeout_add(_SETTLE_MS, self._settled)

    def _settled(self):
        self.place()
        return GLib.SOURCE_REMOVE


def _key(mon):
    """What a screen's layers depend on: its logical size and scale."""
    if mon is None:
        return None
    r = mon.get_geometry()
    return (mon.get_connector(), r.width, r.height, mon.get_scale())
