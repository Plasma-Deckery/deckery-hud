#!/usr/bin/env python3
"""
poc_osd.py — Proof of concept: regular GTK window + plasma-shell OSD role.
Tests whether a non-layer-shell window with ON_SCREEN_DISPLAY role stays
visible above KDE Overview / Desktop-Grid.

Run:  python3 poc_osd.py
Close: Ctrl+C in terminal, or wait — window has no close button.
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import ctypes, datetime

LOG = "/tmp/poc-osd.log"

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{datetime.datetime.now().strftime('%H:%M:%S')}  {msg}\n")


def apply_osd_role(win):
    log("apply_osd_role called")
    try:
        gi.require_version('GdkWayland', '4.0')
        from gi.repository import GdkWayland  # noqa

        libwl  = ctypes.CDLL("libwayland-client.so.0")
        libgtk = ctypes.CDLL("libgtk-4.so.1")

        gdk_disp = win.get_display()
        gdk_surf = win.get_surface()
        if not gdk_surf:
            log("no surface yet"); return

        libgtk.gdk_wayland_display_get_wl_display.restype  = ctypes.c_void_p
        libgtk.gdk_wayland_display_get_wl_display.argtypes = [ctypes.c_void_p]
        wl_dpy = libgtk.gdk_wayland_display_get_wl_display(hash(gdk_disp))

        libgtk.gdk_wayland_surface_get_wl_surface.restype  = ctypes.c_void_p
        libgtk.gdk_wayland_surface_get_wl_surface.argtypes = [ctypes.c_void_p]
        wl_sf = libgtk.gdk_wayland_surface_get_wl_surface(hash(gdk_surf))

        log(f"wl_display={wl_dpy}  wl_surface={wl_sf}")
        if not wl_dpy or not wl_sf: return

        # ── ctypes structs ────────────────────────────────────────────────────
        class _I(ctypes.Structure):
            _fields_ = [("name", ctypes.c_char_p), ("version", ctypes.c_int),
                        ("mc",   ctypes.c_int),     ("ms",     ctypes.c_void_p),
                        ("ec",   ctypes.c_int),     ("es",     ctypes.c_void_p)]

        class _WlMsg(ctypes.Structure):
            _fields_ = [("name", ctypes.c_char_p), ("sig",   ctypes.c_char_p),
                        ("types", ctypes.c_void_p)]

        class _A(ctypes.Union):
            _fields_ = [("i", ctypes.c_int32), ("u", ctypes.c_uint32),
                        ("s", ctypes.c_char_p), ("o", ctypes.c_void_p),
                        ("n", ctypes.c_uint32)]

        _GF  = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32)
        _GRF = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32)

        class _RL(ctypes.Structure):
            _fields_ = [("global_", _GF), ("global_remove", _GRF)]

        # ── interfaces ────────────────────────────────────────────────────────
        reg_methods = (_WlMsg * 1)(_WlMsg(b"bind", b"usun", None))
        reg_events  = (_WlMsg * 2)(_WlMsg(b"global", b"usu", None),
                                    _WlMsg(b"global_remove", b"u", None))
        i_reg = _I(b"wl_registry", 1, 1, ctypes.addressof(reg_methods),
                                        2, ctypes.addressof(reg_events))

        shell_methods = (_WlMsg * 1)(_WlMsg(b"get_surface", b"no", None))
        i_shell = _I(b"org_kde_plasma_shell", 8,
                     1, ctypes.addressof(shell_methods), 0, None)

        surf_methods = (_WlMsg * 4)(
            _WlMsg(b"destroy",      b"",   None),
            _WlMsg(b"set_output",   b"o",  None),
            _WlMsg(b"set_position", b"ii", None),
            _WlMsg(b"set_role",     b"u",  None),
        )
        i_surf = _I(b"org_kde_plasma_surface", 8,
                    4, ctypes.addressof(surf_methods), 0, None)

        # ── libwayland helpers ────────────────────────────────────────────────
        _mac_nv = libwl.wl_proxy_marshal_array_constructor
        _mac_nv.restype  = ctypes.c_void_p
        _mac_nv.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                            ctypes.c_void_p, ctypes.c_void_p]

        _macc = libwl.wl_proxy_marshal_array_constructor_versioned
        _macc.restype  = ctypes.c_void_p
        _macc.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_uint32]

        _ma = libwl.wl_proxy_marshal_array
        _ma.restype  = None
        _ma.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]

        libwl.wl_display_flush.restype  = ctypes.c_int
        libwl.wl_display_flush.argtypes = [ctypes.c_void_p]

        # ── registry ──────────────────────────────────────────────────────────
        ga = (_A * 1)(); ga[0].n = 0
        reg = _mac_nv(wl_dpy, 1, ctypes.cast(ga, ctypes.c_void_p),
                      ctypes.addressof(i_reg))
        log(f"registry={reg}")
        if not reg: return

        # ── bind + set role ───────────────────────────────────────────────────
        def _do_bind(name, ver):
            try:
                ba = (_A * 4)()
                ba[0].u = name; ba[1].s = b"org_kde_plasma_shell"
                ba[2].u = ver;  ba[3].n = 0
                shell = _macc(reg, 0, ctypes.cast(ba, ctypes.c_void_p),
                              ctypes.addressof(i_shell), ver)
                log(f"shell={shell}")
                if not shell: return

                ga2 = (_A * 2)(); ga2[0].n = 0; ga2[1].o = wl_sf
                psurf = _macc(shell, 0, ctypes.cast(ga2, ctypes.c_void_p),
                              ctypes.addressof(i_surf), ver)
                log(f"psurf={psurf}")
                if not psurf: return

                # set_position (opcode 2): center on screen
                mon = win.get_display().get_monitors().get_item(0)
                g   = mon.get_geometry()
                px  = g.x + (g.width  - 400) // 2
                py  = g.y + (g.height - 120) // 2
                pa = (_A * 2)(); pa[0].i = px; pa[1].i = py
                _ma(psurf, 2, ctypes.cast(pa, ctypes.c_void_p))
                log(f"set_position({px}, {py})")

                # set_role (opcode 3): ON_SCREEN_DISPLAY = 3
                ra = (_A * 1)(); ra[0].u = 3
                _ma(psurf, 3, ctypes.cast(ra, ctypes.c_void_p))
                libwl.wl_display_flush(wl_dpy)
                log("OSD role set — done")

            except Exception as e:
                import traceback
                log(f"_do_bind EXCEPTION: {e}\n{traceback.format_exc()}")

        @_GF
        def _on_glob(data, registry, name, iface, ver):
            if iface == b"org_kde_plasma_shell":
                log(f"found plasma_shell name={name} ver={ver}")
                _do_bind(name, min(ver, 8))

        @_GRF
        def _on_rm(data, registry, name): pass

        rl = _RL(_on_glob, _on_rm)
        libwl.wl_proxy_add_listener.restype  = ctypes.c_int
        libwl.wl_proxy_add_listener.argtypes = [ctypes.c_void_p,
                                                 ctypes.c_void_p, ctypes.c_void_p]
        libwl.wl_proxy_add_listener(reg, ctypes.byref(rl), None)
        libwl.wl_display_flush(wl_dpy)
        log("flushed — waiting for globals")

        # keep alive
        win._poc_ctx = dict(
            reg_methods=reg_methods, reg_events=reg_events,
            shell_methods=shell_methods, surf_methods=surf_methods,
            i_reg=i_reg, i_shell=i_shell, i_surf=i_surf,
            ga=ga, reg=reg, rl=rl,
            _on_glob=_on_glob, _on_rm=_on_rm, _do_bind=_do_bind,
        )

    except Exception as e:
        import traceback
        log(f"EXCEPTION: {e}\n{traceback.format_exc()}")


class PocApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="de.poc.osd-test")

    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self)
        win.set_title("POC OSD")
        win.set_decorated(False)
        win.set_default_size(260, 40)
        win.set_resizable(False)

        css = Gtk.CssProvider()
        css.load_from_string("""
            window { background: rgba(20, 20, 60, 0.92);
                     border-radius: 8px; border: 1px solid rgba(255,255,255,0.3); }
            label  { color: white; font-size: 11px; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER)

        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda *_: self.quit())
        win.add_controller(click)

        lbl = Gtk.Label(label="🧪 POC OSD — klicken zum Schließen")
        win.set_child(lbl)
        win.present()

        win.connect("realize", lambda w: GLib.idle_add(apply_osd_role, w))


PocApp().run(None)
