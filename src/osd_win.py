"""
osd_win.py — OSD (On-Screen Display): active outputs (bottom-center) + toast.

Persistent full-screen transparent overlay, fully input-transparent (no events captured).
No pause, no analog export. Shown when OSD is enabled and the main HUD is hidden.
State updates arrive via on_state() called by App.

How toasts and pills come and go is an osd_anim preset (`[osd] animation`):
"slide" draws as it always has; "pop" paints finished sprites (osd_look.py)
at fixed spots — in the split design in the HUD's own look.
"""

import time
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gtk, Gtk4LayerShell as LayerShell, GLib
import cairo

from helpers import _pill_row, _K, capture_text_boxes
import pill_shadow
from shadow import neutral_rgb
import theme
from toast import draw_toast
import osd_anim
import osd_look

_TOAST_TTL_MS   = 1500
_TOAST_FRAME_MS = 33
_SUPPRESS_S     = 0.4   # how long to hide pills that are covered by the toast
_POP_FRAME_MS   = 16    # frames while a pop sprite moves; none while it sits still


def _drawn_fields(state):
    """The parts of the state `_draw_inner` reads, for change detection."""
    ctx = state.get("context", {})
    return (ctx.get("paused", False), repr(ctx.get("active_outputs")),
            repr(state.get("last_action")))


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
        self._drawn          = None
        self._anim           = osd_anim.PRESETS["slide"]
        self._split          = False
        # Pop mode: the pill row on screen, when it popped in, and — while it
        # bubbles out — when that started and what it showed.
        self._pills          = ()
        self._pills_in       = 0.0
        self._pills_out      = None
        self._pills_leaving  = ()

        # ── Drawing area ─────────────────────────────────────────────────
        da = Gtk.DrawingArea()
        da.set_draw_func(self._draw, None)
        self.set_child(da)
        self._da = da

    # ── Settings (called by App) ─────────────────────────────────────────

    def configure(self, animation, split):
        """`[osd] animation` and whether the split design is running."""
        self._anim = osd_anim.resolve(animation, split)
        self._split = split
        self._da.queue_draw()

    # ── State update (called by App) ─────────────────────────────────────

    def on_state(self, state):
        self._state = state
        # With the analog export on, the state is rewritten up to 90 times a
        # second for stick and pad positions, none of which this draws, and
        # each full-screen repaint cost ~4 ms. Repaint only when what
        # _draw_inner reads has changed; the toast animates on its own timer.
        drawn = _drawn_fields(state)
        if drawn != self._drawn:
            self._drawn = drawn
            self._da.queue_draw()
            # Pills a fresh toast covers come back after _SUPPRESS_S; that
            # used to ride on whatever update came next.
            GLib.timeout_add(int(_SUPPRESS_S * 1000) + 20, self._redraw_once)
        self._schedule_toast()

    def _redraw_once(self):
        self._da.queue_draw()
        return GLib.SOURCE_REMOVE

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
        self._kick()

    def _kick(self):
        """(Re)start the frame timer right away."""
        if self._toast_source is not None:
            GLib.source_remove(self._toast_source)
        self._toast_source = GLib.timeout_add(
            _POP_FRAME_MS if self._anim.kind == "pop" else _TOAST_FRAME_MS, self._on_toast_frame)

    def _on_toast_frame(self):
        self._toast_source = None
        now = time.time()
        if self._anim.kind == "pop":
            self._active_toasts = [t for t in self._active_toasts
                                   if self._toast_phase(t, now) is not None]
        else:
            cutoff = now - _TOAST_TTL_MS / 1000
            self._active_toasts = [t for t in self._active_toasts
                                   if t.get("ts", 0) > cutoff]
        self._da.queue_draw()
        delay = self._next_frame_ms(now)
        if delay is not None:
            self._toast_source = GLib.timeout_add(delay, self._on_toast_frame)
        return GLib.SOURCE_REMOVE

    def _next_frame_ms(self, now):
        """When the next frame is due: every _TOAST_FRAME_MS while slide
        toasts are up; for pop, every _POP_FRAME_MS while something moves,
        else at the next toast's leave; None when nothing is left."""
        if self._anim.kind != "pop":
            return _TOAST_FRAME_MS if self._active_toasts else None
        a = self._anim
        moving = (self._pills_out is not None
                  and osd_anim.animating(a, now - self._pills_in, now - self._pills_out)
                  or bool(self._pills) and osd_anim.animating(a, now - self._pills_in))
        waits = []
        for t in self._active_toasts:
            since_in, since_out = self._toast_phase(t, now)
            if osd_anim.animating(a, since_in, since_out):
                moving = True
            elif since_out is None:
                waits.append(self._toast_leave_at(t) - now)
        if moving:
            return _POP_FRAME_MS
        if waits:
            return max(_POP_FRAME_MS, int(min(waits) * 1000) + 1)
        return None

    def _toast_leave_at(self, t):
        """Pop: when toast `t` starts bubbling out — at the end of its time,
        or as soon as a newer toast takes its spot."""
        ts = t.get("ts", 0)
        leave = ts + (_TOAST_TTL_MS - self._anim.out_ms) / 1000
        newer = [o.get("ts", 0) for o in self._active_toasts if o.get("ts", 0) > ts]
        return min([leave] + newer)

    def _toast_phase(self, t, now):
        """(since_in, since_out) for osd_anim.envelope, None once gone."""
        since_in = now - t.get("ts", 0)
        leave = self._toast_leave_at(t)
        since_out = now - leave if now >= leave else None
        if since_out is not None and since_out * 1000 >= self._anim.out_ms:
            return None
        return since_in, since_out

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

        # While makima is paused, nothing is actually executed — don't render
        # ANY OSD content (pill row, toast, ...). Single gate up front so no
        # future addition below can accidentally bypass it.
        if self._state.get("context", {}).get("paused", False):
            return

        ctx = self._state.get("context", {})
        raw = ctx.get("active_outputs", []) or []

        # active_outputs entries are either plain strings or {key, silent, ...} dicts.
        def _key(e):   return e.get("key", "") if isinstance(e, dict) else e
        def _silent(e): return e.get("silent", False) if isinstance(e, dict) else False

        if self._anim.kind == "pop":
            # The toast pops in above the pills, never over them, so nothing
            # needs hiding while a toast is up.
            self._draw_pop(cr, sw, sh, [_key(e) for e in raw if not _silent(e)])
            return

        # Filter: drop silent outputs, drop keys shown by a recent toast.
        la     = self._state.get("last_action") or {}
        la_age = time.time() - la.get("ts", 0.0)
        toasted = set(la["value"]) if la_age < _SUPPRESS_S and isinstance(la.get("value"), list) else set()

        outputs = [_key(e) for e in raw if not _silent(e) and _key(e) not in toasted]

        # ── Active outputs — same as center strip, bottom-center ──────────
        if outputs:
            labels = [_K.get(k, k.replace("KEY_", "").replace("BTN_", ""))
                      for k in outputs]
            # The pills' shadow goes underneath, but where they sit is only
            # known once they're laid out: draw them into a group first.
            with capture_text_boxes() as cap:
                cr.push_group()
                _pill_row(
                    cr,
                    sw / 2, sh - 28,
                    labels,
                    sep="+", size=9,
                    glass=theme.current().glass, fg=theme.current().pill_fg,
                    sep_rgba=(0.5, 0.5, 0.52, 0.9),
                    ha="center",
                )
                pills = cr.pop_group()
            cr.save()
            cr.identity_matrix()   # boxes are in device space
            t = theme.current()
            pill_shadow.paint(cr, cap.glass_boxes, rgb=neutral_rgb(t.shadow_style()),
                              strength=t.pill_shadow)
            cr.restore()
            cr.set_source(pills)
            cr.paint()

        # ── Toast — rises from bottom-center ─────────────────────────────
        if self._active_toasts:
            draw_toast(cr, sw, sh, self._active_toasts, start_y=sh + 30)

    def _draw_pop(self, cr, sw, sh, outputs):
        """Pop preset: the pill row at its spot, toasts above it, each a
        sprite scaled and faded by osd_anim.envelope."""
        a, now = self._anim, time.time()
        surf = self.get_surface()
        scale = surf.get_scale() if surf is not None else 1.0
        style = theme.current().shadow_style()

        labels = tuple(_K.get(k, k.replace("KEY_", "").replace("BTN_", "")) for k in outputs)
        if labels != self._pills:
            if labels and not self._pills:      # pops in (again, if it was leaving)
                self._pills_in, self._pills_out = now, None
            elif not labels:                    # bubbles out, still showing what it showed
                self._pills_out, self._pills_leaving = now, self._pills
            self._pills = labels
            self._kick()
        shown = self._pills or self._pills_leaving
        if shown:
            env = osd_anim.envelope(a, now - self._pills_in,
                                    None if self._pills else now - self._pills_out)
            if env is not None:
                osd_look.paint(cr, osd_look.pills_sprite(shown, style, scale),
                               sw / 2, sh - 28, *env, dev_scale=scale)
            elif not self._pills:
                self._pills_leaving, self._pills_out = (), None

        for t in self._active_toasts:
            phase = self._toast_phase(t, now)
            env = osd_anim.envelope(a, *phase) if phase is not None else None
            if env is not None:
                osd_look.paint(cr, osd_look.toast_sprite(t, self._split, style, scale),
                               sw / 2, sh - a.toast_bottom, *env, dev_scale=scale)
