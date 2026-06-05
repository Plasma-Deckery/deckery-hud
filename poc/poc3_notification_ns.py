#!/usr/bin/env python3
"""
poc3_notification_ns.py — Layer-Shell OVERLAY mit namespace="notification".

KWin liest den Layer-Shell-Namespace als "scope" und mapped ihn auf WindowType:
  "notification"  → WindowType::Notification
  alles andere    → WindowType::Normal

Overview-Effekt filtert Notification-Fenster *aus dem Grid raus* (werden nicht
in die Kachelansicht aufgenommen). Gleichzeitig bleiben OVERLAY-Layer-Surfaces
auf ihrer normalen Z-Ebene → sollten über dem Overview-QML-Layer sichtbar sein.

Testet ob "notification" als Namespace das Fenster über der KDE Overview hält.

Run:   python3 poc3_notification_ns.py
Close: Klick auf Fenster
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gtk, Gtk4LayerShell as LayerShell


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="de.poc.layershell-notification")

    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self)
        win.set_title("POC notification-ns")
        win.set_decorated(False)
        win.set_default_size(320, 44)

        LayerShell.init_for_window(win)
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(win, -1)
        # "notification" → KWin WindowType::Notification
        # → aus Overview-Grid ausgeschlossen → sollte darüber sichtbar bleiben
        LayerShell.set_namespace(win, "notification")

        # Keine Anchors → Compositor platziert irgendwo; wir verankern oben-mitte
        for edge in (LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT,
                     LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM):
            LayerShell.set_anchor(win, edge, True)

        css = Gtk.CssProvider()
        css.load_from_string("""
            window { background: rgba(60, 20, 20, 0.92);
                     border-radius: 8px; border: 2px solid rgba(255, 100, 100, 0.8); }
            label  { color: white; font-size: 12px; font-weight: bold; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER)

        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda *_: self.quit())
        win.add_controller(click)

        lbl = Gtk.Label(label='🔴 POC ns="notification" — klicken zum Schließen')
        win.set_child(lbl)
        win.present()


App().run(None)
