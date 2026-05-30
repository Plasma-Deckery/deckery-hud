#!/usr/bin/env python3
"""
poc2_layershell.py — Layer-Shell ohne Edge-Anchoring, feste Größe 980×500.
Testet ob ein nicht-vollbild Layer-Shell-Overlay in der KDE Overview sichtbar bleibt.

Run:  python3 poc2_layershell.py
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gtk, Gtk4LayerShell as LayerShell

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="de.poc.layershell2")

    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self)
        win.set_title("POC LayerShell2")
        win.set_decorated(False)
        win.set_default_size(260, 40)

        LayerShell.init_for_window(win)
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)
        # Kein set_anchor → kein Edge-Anchoring → Compositor zentriert es
        LayerShell.set_namespace(win, "deckery-hud-poc")

        css = Gtk.CssProvider()
        css.load_from_string("""
            window { background: rgba(20, 20, 60, 0.92);
                     border-radius: 8px; border: 1px solid rgba(100, 200, 255, 0.6); }
            label  { color: white; font-size: 11px; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER)

        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda *_: self.quit())
        win.add_controller(click)

        lbl = Gtk.Label(label="🧪 POC — klicken zum Schließen")
        win.set_child(lbl)
        win.present()

App().run(None)
