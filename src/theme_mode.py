"""
theme_mode.py — Flipping through themes from the controller (B-20).

While the theme mode is on, the full HUD is open and makima is paused: a
paused makima forwards nothing (only no_pause bindings like L3's HUD toggle
and the L2/R2 clicks still fire), so these presses reach neither the app
nor the game — no capture mode of its own is needed. The HUD reads them
from makima's state like any other press:

  d-pad ←/↑, left stick left   previous theme (live preview)
  d-pad →/↓, left stick right  next theme
  A                            keep it
  B                            back to the theme from before

The list wraps around. A button already down when the mode starts (the
press that opened it) only counts once released and pressed again.

Pure Python, no GTK: App feeds it states and acts on what it returns.
"""

PREV = frozenset({"BTN_DPAD_LEFT", "BTN_DPAD_UP"})
NEXT = frozenset({"BTN_DPAD_RIGHT", "BTN_DPAD_DOWN"})
APPLY = "BTN_SOUTH"
CANCEL = "BTN_EAST"

STICK_ON = 0.6    # deflection that counts as a flick
STICK_OFF = 0.3   # back below this re-arms it


def _buttons(state):
    return set(((state or {}).get("context") or {}).get("active_buttons") or ())


def _stick_x(state):
    stick = ((state or {}).get("sticks") or {}).get("lstick") or {}
    x = stick.get("x", 0.0)
    return x if isinstance(x, (int, float)) else 0.0


class ThemeMode:
    def __init__(self, names, current, state=None):
        self.names = list(names) or [current]
        self.original = current
        self.index = self.names.index(current) if current in self.names else 0
        self._down = _buttons(state)
        self._stick = 0 if abs(_stick_x(state)) < STICK_OFF else None   # None: wait for rest

    @property
    def name(self):
        return self.names[self.index]

    def _step(self, d):
        self.index = (self.index + d) % len(self.names)
        return "preview"

    def feed(self, state):
        """One new makima state. Returns "preview" (self.name changed),
        "apply", "cancel" or None."""
        now = _buttons(state)
        pressed = now - self._down
        self._down = now
        if CANCEL in pressed:
            return "cancel"
        if APPLY in pressed:
            return "apply"
        step = (1 if pressed & NEXT else 0) - (1 if pressed & PREV else 0)

        x = _stick_x(state)
        if self._stick is None or self._stick != 0:
            if abs(x) < STICK_OFF:
                self._stick = 0
        elif abs(x) >= STICK_ON:
            self._stick = 1 if x > 0 else -1
            step += self._stick

        if step:
            return self._step(1 if step > 0 else -1)
        return None
