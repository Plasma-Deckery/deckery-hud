"""
kde_osd.py — KDE plasma-shell OSD/keep-above role via libwayland ctypes

Keeps the deckery-hud layer-shell surface visible above KDE Overview /
Desktop-Grid compositor effects by applying org_kde_plasma_shell::set_role.

Role values (org_kde_plasma_surface::role enum):
  NORMAL            = 0
  DESKTOP           = 1
  PANEL             = 2
  ON_SCREEN_DISPLAY = 3   ← KWin auto-dismisses after ~1-2 s (volume OSD)
  NOTIFICATION      = 4
  TOOLTIP           = 5
  CRITIC_NOTIFICATION = 6
  APP_MENU          = 7   ← used as "keep_above" workaround (no auto-dismiss)

We use role 7 (APP_MENU / keep_above) so KWin keeps us on top without
the OSD auto-dismiss timeout.

All communication uses low-level libwayland primitives because the high-level
helpers (wl_display_get_registry, wl_registry_add_listener, wl_display_sync)
are compiled as static-inline in this libwayland build and not exported.

Async flow:
  1. wl_proxy_marshal_array_constructor  → create wl_registry (opcode 1 of wl_display)
  2. wl_proxy_add_listener               → attach global/global_remove callbacks
  3. wl_display_flush                    → send get_registry to compositor
  4. GTK's GLib-Wayland GSource dispatches incoming events from the default queue
     → _on_glob fires when compositor sends global announcements
  5. _do_bind: wl_registry::bind → get_surface → set_role(7)
"""

import gi

_OSD_LOG = "/tmp/deckery-hud-osd.log"
_OSD_CTX = {}   # keeps ctypes callbacks / structs alive across async dispatch


def _osd_log(msg):
    import datetime
    with open(_OSD_LOG, "a") as f:
        f.write(f"{datetime.datetime.now().strftime('%H:%M:%S')}  {msg}\n")


def kde_osd_setup(win):
    """
    Apply org_kde_plasma_shell role so the HUD stays visible above KDE Overview.

    Called via:  self.connect("realize", lambda w: GLib.idle_add(kde_osd_setup, w))

    Logs to /tmp/deckery-hud-osd.log.
    """
    _osd_log("kde_osd_setup called")
    try:
        import ctypes

        gi.require_version('GdkWayland', '4.0')
        from gi.repository import GdkWayland  # noqa: F401

        libwl  = ctypes.CDLL("libwayland-client.so.0")
        libgtk = ctypes.CDLL("libgtk-4.so.1")

        gdk_disp = win.get_display()
        gdk_surf = win.get_surface()
        _osd_log(f"display={type(gdk_disp).__name__}  surface={'ok' if gdk_surf else 'None'}")
        if gdk_surf is None:
            return

        # gdk_wayland_*_get_wl_* is not exposed via GObject introspection.
        # hash(PyGObject) returns the raw GObject* pointer — use that with ctypes.
        libgtk.gdk_wayland_display_get_wl_display.restype  = ctypes.c_void_p
        libgtk.gdk_wayland_display_get_wl_display.argtypes = [ctypes.c_void_p]
        wl_dpy = libgtk.gdk_wayland_display_get_wl_display(hash(gdk_disp))

        libgtk.gdk_wayland_surface_get_wl_surface.restype  = ctypes.c_void_p
        libgtk.gdk_wayland_surface_get_wl_surface.argtypes = [ctypes.c_void_p]
        wl_sf = libgtk.gdk_wayland_surface_get_wl_surface(hash(gdk_surf))

        _osd_log(f"wl_display={wl_dpy}  wl_surface={wl_sf}")
        if not wl_dpy or not wl_sf:
            return

        # ── ctypes types ──────────────────────────────────────────────────────

        class _I(ctypes.Structure):
            """Minimal wl_interface layout (name, version, mc, ms, ec, es)."""
            _fields_ = [("name",    ctypes.c_char_p),
                        ("version", ctypes.c_int),
                        ("mc",      ctypes.c_int),
                        ("ms",      ctypes.c_void_p),
                        ("ec",      ctypes.c_int),
                        ("es",      ctypes.c_void_p)]

        class _WlMsg(ctypes.Structure):
            """wl_message: libwayland needs event signatures to decode arguments.
            Without this, dispatch fails with "interface has no event N"."""
            _fields_ = [("name",  ctypes.c_char_p),
                        ("sig",   ctypes.c_char_p),
                        ("types", ctypes.c_void_p)]

        class _A(ctypes.Union):
            """wl_argument union."""
            _fields_ = [("i", ctypes.c_int32),  ("u", ctypes.c_uint32),
                        ("f", ctypes.c_int32),  ("s", ctypes.c_char_p),
                        ("o", ctypes.c_void_p), ("n", ctypes.c_uint32),
                        ("a", ctypes.c_void_p), ("h", ctypes.c_int32)]

        # Callback types for wl_registry events
        _GF  = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32)
        _GRF = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32)

        class _RL(ctypes.Structure):
            """wl_registry_listener layout."""
            _fields_ = [("global_",       _GF),
                        ("global_remove", _GRF)]

        # wl_registry: 1 request (bind, opcode 0), 2 events (global, global_remove)
        # wl_proxy_marshal_array_* accesses proxy->interface->requests[opcode] to
        # read the argument signature — segfaults if methods/mc are NULL/0.
        reg_methods = (_WlMsg * 1)(
            # bind(name:u, interface:s, version:u, new_id:n)
            _WlMsg(b"bind", b"usun", None),
        )
        reg_events = (_WlMsg * 2)(
            _WlMsg(b"global",        b"usu", None),
            _WlMsg(b"global_remove", b"u",   None),
        )
        i_reg = _I(b"wl_registry", 1,
                   1, ctypes.addressof(reg_methods),
                   2, ctypes.addressof(reg_events))

        # org_kde_plasma_shell: opcode 0 = get_surface(new_id surface, object wl_surface)
        shell_methods = (_WlMsg * 1)(
            _WlMsg(b"get_surface", b"no", None),
        )
        i_shell = _I(b"org_kde_plasma_shell", 8,
                     1, ctypes.addressof(shell_methods),
                     0, None)

        # org_kde_plasma_surface: we call opcode 3 = set_role(role:u)
        # Need entries 0-3; only opcode 3 matters — the others are placeholders.
        surf_methods = (_WlMsg * 4)(
            _WlMsg(b"destroy",      b"",    None),  # opcode 0 (destructor)
            _WlMsg(b"set_output",   b"o",   None),  # opcode 1
            _WlMsg(b"set_position", b"ii",  None),  # opcode 2
            _WlMsg(b"set_role",     b"u",   None),  # opcode 3  ← we call this
        )
        i_surf = _I(b"org_kde_plasma_surface", 8,
                    4, ctypes.addressof(surf_methods),
                    0, None)

        # ── libwayland proxy helpers (always exported, not static-inline) ──────

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

        # ── Create wl_registry ────────────────────────────────────────────────
        # wl_display::get_registry is opcode 1 (wl_display_get_registry is inline)
        ga_reg = (_A * 1)()
        ga_reg[0].n = 0
        reg = _mac_nv(wl_dpy, 1,
                      ctypes.cast(ga_reg, ctypes.c_void_p),
                      ctypes.addressof(i_reg))
        _osd_log(f"registry = {reg}")
        if not reg:
            return

        # ── Bind plasma_shell + set role ──────────────────────────────────────
        def _do_bind(glob_name, ver):
            # NOTE: this runs inside a ctypes CFUNCTYPE callback — Python exceptions
            # are silently swallowed by ctypes (control must return to C).
            # Wrap everything in try/except so errors are visible in the log.
            try:
                _osd_log(f"_do_bind glob_name={glob_name} ver={ver}")

                # wl_registry::bind (opcode 0) — returns org_kde_plasma_shell proxy
                ba = (_A * 4)()
                ba[0].u = glob_name;  ba[1].s = b"org_kde_plasma_shell"
                ba[2].u = ver;        ba[3].n = 0
                shell = _macc(reg, 0,
                              ctypes.cast(ba, ctypes.c_void_p),
                              ctypes.addressof(i_shell), ver)
                _osd_log(f"plasma_shell = {shell}")
                if not shell:
                    _osd_log("plasma_shell is NULL — bind failed")
                    return

                # org_kde_plasma_shell::get_surface (opcode 0)
                ga = (_A * 2)()
                ga[0].n = 0;  ga[1].o = wl_sf
                psurf = _macc(shell, 0,
                              ctypes.cast(ga, ctypes.c_void_p),
                              ctypes.addressof(i_surf), ver)
                _osd_log(f"plasma_surface = {psurf}")
                if not psurf:
                    _osd_log("plasma_surface is NULL — get_surface failed")
                    return

                # org_kde_plasma_surface::set_role (opcode 3)
                # Role 3 = ON_SCREEN_DISPLAY — KWin keeps this above Overview/Desktop-Grid.
                # The earlier 1-2 s close was the segfault in _do_bind, not OSD auto-dismiss.
                # (Plasma's OSD auto-hide only fires for its own volume/brightness surfaces.)
                ra = (_A * 1)();  ra[0].u = 3
                _ma(psurf, 3, ctypes.cast(ra, ctypes.c_void_p))
                libwl.wl_display_flush(wl_dpy)
                _osd_log("keep_above role set and flushed — done")

            except Exception as exc:
                import traceback
                _osd_log(f"_do_bind EXCEPTION: {exc}\n{traceback.format_exc()}")

        # ── Registry listener — fires when GTK dispatches the global events ────
        @_GF
        def _on_glob(data, registry, name, iface, ver):
            if iface == b"org_kde_plasma_shell":
                _osd_log(f"global: plasma_shell name={name} ver={ver}")
                _do_bind(name, min(ver, 8))

        @_GRF
        def _on_rm(data, registry, name): pass

        rl = _RL(_on_glob, _on_rm)

        # wl_registry_add_listener is static-inline → wl_proxy_add_listener
        libwl.wl_proxy_add_listener.restype  = ctypes.c_int
        libwl.wl_proxy_add_listener.argtypes = [ctypes.c_void_p,
                                                 ctypes.c_void_p, ctypes.c_void_p]
        libwl.wl_proxy_add_listener(reg, ctypes.byref(rl), None)

        # Flush sends get_registry to compositor. GTK's GLib-Wayland GSource reads
        # the response (globals) and dispatches to the default queue → _on_glob fires.
        libwl.wl_display_flush(wl_dpy)
        _osd_log("flushed — waiting for GTK to dispatch globals")

        # Keep every ctypes object alive until the async callback has fired.
        _OSD_CTX.update(dict(
            libwl=libwl, libgtk=libgtk,
            _I=_I, _WlMsg=_WlMsg, _A=_A, _GF=_GF, _GRF=_GRF, _RL=_RL,
            reg_methods=reg_methods, reg_events=reg_events,
            shell_methods=shell_methods, surf_methods=surf_methods,
            i_reg=i_reg, i_shell=i_shell, i_surf=i_surf,
            _mac_nv=_mac_nv, _macc=_macc, _ma=_ma,
            ga_reg=ga_reg, reg=reg,
            _on_glob=_on_glob, _on_rm=_on_rm, rl=rl,
            _do_bind=_do_bind,
        ))

    except Exception as exc:
        import traceback
        _osd_log(f"EXCEPTION: {exc}\n{traceback.format_exc()}")
