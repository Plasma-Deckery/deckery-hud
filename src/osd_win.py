"""
osd_win.py — OSD (On-Screen Display): active outputs (bottom-center) + toast.

Persistent full-screen transparent overlay, fully input-transparent (no events captured).
No pause, no analog export. Shown when OSD is enabled and the main HUD is hidden.
State updates arrive via on_state() called by App.
"""

import time
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gtk, Gtk4LayerShell as LayerShell, GLib
import cairo

from helpers import _pill_row, _K
from toast import draw_toast

_TOAST_TTL_MS   = 1500
_TOAST_FRAME_MS = 33
_SUPPRESS_S     = 0.4   # how long to hide pills that are covered by the toast

_C_ACT = (0.333, 0.867, 1.0)   # cyan — same as center strip


class OsdWin(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        self.set_title("Deckery OSD")
        self.set_decorated(False)

        # ── Layer shell — full-screen, zero input ────────────────────────
        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(self, 0)
        LayerShell.set_namespace(self, "deckery-osd")
        for edge in (LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT,
                     LayerShell.Edge.TOP,  LayerShell.Edge.BOTTOM):
            LayerShell.set_anchor(self, edge, True)

        # ── State ────────────────────────────────────────────────────────
        self._state          = {}
        self._active_toasts  = []
        self._last_action_ts = 0.0
        self._toast_source   = None

        # ── Drawing area ─────────────────────────────────────────────────
        da = Gtk.DrawingArea()
        da.set_draw_func(self._draw, None)
        self.set_child(da)
        self._da = da

    # ── State update (called by App) ─────────────────────────────────────

    def on_state(self, state):
        self._state = state
        self._da.queue_draw()
        self._schedule_toast()

    # ── Toast ─────────────────────────────────────────────────────────────

    def _schedule_toast(self):
        la = self._state.get("last_action") or {}
        ts = la.get("ts", 0.0)
        if ts <= self._last_action_ts:
            return
        self._last_action_ts = ts
        if la.get("silent"):
            return
        self._active_toasts.append(dict(la))
        if self._toast_source is None:
            self._toast_source = GLib.timeout_add(_TOAST_FRAME_MS, self._on_toast_frame)

    def _on_toast_frame(self):
        cutoff = time.time() - _TOAST_TTL_MS / 1000
        self._active_toasts = [t for t in self._active_toasts
                               if t.get("ts", 0) > cutoff]
        self._da.queue_draw()
        if not self._active_toasts:
            self._toast_source = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    # ── Drawing ───────────────────────────────────────────────────────────

    def _draw(self, _da, cr, sw, sh, _):
        try:
            self._draw_inner(cr, sw, sh)
        except Exception:
            import traceback
            traceback.print_exc()
            cr.set_operator(cairo.Operator.CLEAR)
            cr.paint()

    def _draw_inner(self, cr, sw, sh):
        # Always clear input region — surface may be recreated after present(),
        # e.g. when HUD hides and OSD is re-shown. set_input_region() is idempotent.
        surf = self.get_surface()
        if surf:
            surf.set_input_region(cairo.Region())

        cr.set_operator(cairo.Operator.CLEAR)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        ctx     = self._state.get("context", {})
        raw     = ctx.get("active_outputs", []) or []
        paused  = ctx.get("paused", False)

        # active_outputs entries are either plain strings or {key, silent, ...} dicts.
        def _key(e):   return e.get("key", "") if isinstance(e, dict) else e
        def _silent(e): return e.get("silent", False) if isinstance(e, dict) else False

        # Filter: drop silent outputs, drop keys shown by a recent toast.
        la     = self._state.get("last_action") or {}
        la_age = time.time() - la.get("ts", 0.0)
        toasted = set(la["value"]) if la_age < _SUPPRESS_S and isinstance(la.get("value"), list) else set()

        # active_outputs reflects what bindings *would* resolve to, regardless of
        # pause state — makima only gates the virtual-device write, not this field.
        # When paused, nothing is actually executed, so don't display it.
        outputs = [] if paused else [_key(e) for e in raw if not _silent(e) and _key(e) not in toasted]

        # ── Active outputs — same as center strip, bottom-center ──────────
        if outputs:
            labels = [_K.get(k, k.replace("KEY_", "").replace("BTN_", ""))
                      for k in outputs]
            _pill_row(
                cr,
                sw / 2, sh - 28,
                labels,
                sep="+", size=9,
                bg=(*_C_ACT, 1.0), fg=(0, 0, 0, 1),
                border=None, sep_rgba=(1.0, 1.0, 1.0, 0.55),
                ha="center",
            )

        # ── Toast — rises from bottom-center ─────────────────────────────
        if self._active_toasts:
            draw_toast(cr, sw, sh, self._active_toasts, start_y=sh + 30)
