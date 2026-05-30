"""
anim.py — Reusable animation helpers for the HUD.
"""

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
    """

    def __init__(self, redraw_fn, step=0.06):
        self._redraw = redraw_fn
        self._step   = step
        self._t      = 0.0   # linear progress 0–1
        self._target = 0.0
        self._src    = None  # GLib timer handle

    def set(self, hovering: bool):
        self._target = 1.0 if hovering else 0.0
        if self._src is None:
            self._src = GLib.timeout_add(_FRAME_MS, self._tick)

    def _tick(self):
        self._t += self._step if self._target > 0.5 else -self._step
        self._t  = max(0.0, min(1.0, self._t))
        self._redraw()
        if abs(self._t - self._target) < 0.01:
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
