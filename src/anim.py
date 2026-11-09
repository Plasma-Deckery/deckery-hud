"""
anim.py — Reusable animation helpers for the HUD.
"""

import time
from gi.repository import GLib

_FRAME_MS = 33   # ~30 fps


class HoverAnim:
    """
    Drives a 0.0 → 1.0 float with ease-out-cubic (in) / ease-in-cubic (out).

    Usage:
        anim = HoverAnim(widget.queue_draw)
        anim.set(True)   # hover entered
        anim.set(False)  # hover left
        eased = anim.value   # use in draw func

    Two timing modes, same public API either way:

    - step-based (default, duration_ms=None): advances by a fixed amount
      per tick. Simple, fine for short/cheap hover highlights — but the
      animation's *wall-clock* duration depends on how often ticks actually
      fire, which on a loaded system (dropped/delayed GLib timeouts) makes
      it visibly stretch out by an inconsistent amount each time.
    - duration-based (duration_ms set): progress is computed from elapsed
      wall-clock time against a fixed duration, so it always takes the same
      real time to finish regardless of how many ticks fired along the way.
      Use this for anything long/prominent enough that stretchy timing is
      noticeable — e.g. the split renderer's open/close transition.

    Separately, *how* a tick gets scheduled also matters: GLib.timeout_add
    is a generic low-priority timer with no relationship to the compositor's
    actual frame cadence, so under any main-loop contention it fires late
    and irregularly (measured live: a 33ms target tick landing anywhere from
    33ms to 350ms later) — while the draw work it triggers was independently
    measured at 1-3ms, nowhere near the bottleneck. Pass a widget to drive
    ticks via Gtk.Widget.add_tick_callback instead, which GTK schedules
    against the real frame clock the compositor is already presenting to.
    """

    def __init__(self, redraw_fn, step=0.06, duration_ms=None, widget=None):
        self._redraw     = redraw_fn
        self._step        = step
        self._duration    = duration_ms / 1000.0 if duration_ms else None
        self._widget      = widget
        self._t           = 0.0   # linear progress 0-1 toward _target
        self._target      = 0.0
        self._start_val   = 0.0
        self._start_time  = None
        self._src         = None  # GLib timer or tick-callback handle

    def set(self, hovering: bool):
        new_target = 1.0 if hovering else 0.0
        if self._duration is not None:
            if new_target == self._target and self._src is not None:
                return
            self._start_val  = self._t
            self._start_time = time.monotonic()
        self._target = new_target
        if self._src is None:
            if self._widget is not None:
                self._src = self._widget.add_tick_callback(self._tick_cb)
            else:
                self._src = GLib.timeout_add(_FRAME_MS, self._tick)

    def restart_clock(self):
        """Duration-based mode only: rewind to this run's start value and
        re-anchor its clock at "now" — for a stall the animation shouldn't
        have spent its time on (e.g. the first frame of a freshly mapped
        window, which otherwise eats most of a short open transition)."""
        if self._duration is None:
            return
        self._t = self._start_val
        self._start_time = time.monotonic()

    def _tick_cb(self, _widget, _frame_clock):
        return bool(self._tick())

    def _tick(self):
        if self._duration is not None:
            elapsed  = time.monotonic() - self._start_time
            progress = min(1.0, elapsed / self._duration) if self._duration > 0 else 1.0
            self._t  = self._start_val + (self._target - self._start_val) * progress
            done = progress >= 1.0
        else:
            self._t += self._step if self._target > 0.5 else -self._step
            self._t  = max(0.0, min(1.0, self._t))
            done = abs(self._t - self._target) < 0.01
        self._redraw()
        if done:
            self._t   = self._target
            self._src = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    @property
    def value(self) -> float:
        """Eased value: ease-out-cubic in, ease-in-cubic out."""
        t = self._t
        if self._target > 0.5:
            return 1 - (1 - t) ** 3   # ease-out: schnell rein, weich landen
        else:
            return t ** 3              # ease-in: langsam los, schnell weg
