"""
reveal.py — Which split-HUD elements are shown, with what content, and why
(B-12). Pure logic: no GTK, no Cairo, so it can be tested with a fake clock.
An element is one button with its shape, legend and shadow (elements.py).
"""

from dataclasses import dataclass

from elements import ELEMENTS, ELEMENT_IDS
import settings


@dataclass(frozen=True)
class Content:
    """What a visible element shows. legends: the button keys whose legend
    rows are drawn, None = all of the element's. Only the d-pad ever has
    more than one (it shows the whole cross, with just the arrows that do
    something on a modifier layer labelled)."""
    legends: frozenset | None

    def union(self, other):
        if self.legends is None or other.legends is None:
            return FULL
        return Content(self.legends | other.legends)


FULL = Content(None)

# Every element, in draw order. Named GROUPS for the window, which treats
# them all alike.
GROUPS = ELEMENT_IDS


# The thresholds and durations live with the HUD's other settings (B-15):
# one description there gives the [reveal] section of settings.toml, its
# help text and its validation. Re-exported here for the window and tests.
RevealSettings = settings.RevealSettings


@dataclass(frozen=True)
class Want:
    """A group is wanted, with this content, because of this cause:
    "full" (the full HUD) or "detector" (a single-group reveal)."""
    content: Content
    cause: str


class Hold:
    """Debounced "held for a while". raw is the live signal. Fires once
    held for hold_ms, and only while raw is on: letting go hides at once.
    Drops shorter than release_ms bridge the clock, so coming back within
    them fires again at once instead of needing a new hold (an accidental
    lift, or L1 -> R1). A threshold that passes during a drop doesn't fire
    on its own: otherwise an unrelated state write landing in that drop
    would flash the group up just after the finger lifted."""

    def __init__(self, hold_ms, release_ms):
        self.hold = hold_ms / 1000
        self.release = release_ms / 1000
        self._since = None      # when the bridged hold began
        self._off_since = None  # when raw last went off, while still bridged

    def update(self, raw, now):
        if raw:
            if self._off_since is not None and now - self._off_since >= self.release:
                self._since = None
            self._off_since = None
            if self._since is None:
                self._since = now
            return now - self._since >= self.hold
        if self._since is not None and self._off_since is None:
            self._off_since = now
        return False

    def next_change(self, now):
        """When update() would answer differently without a new raw value."""
        if self._since is None or self._off_since is not None:
            return None
        fire = self._since + self.hold
        return fire if fire > now else None

    def reset(self):
        self._since = self._off_since = None

    def restart(self, now):
        """Start the hold over from now, if one is running."""
        if self._since is not None:
            self._since = now
            self._off_since = None

    def force(self, now):
        """Fired from now on, as if held all along."""
        self._since = now - self.hold
        self._off_since = None


_UNSEEN = object()


class Reveal:
    """Which groups are wanted right now, from the full-HUD flag and the
    detectors, given makima's state. The app sets `full`; update() is fed
    every state and whenever next_deadline() comes due."""

    def __init__(self, settings):
        self.settings = settings
        self.full = False
        self._pad = {"LPad": Hold(settings.hold_ms, settings.release_ms),
                     "RPad": Hold(settings.hold_ms, settings.release_ms)}
        self._gesture = Hold(settings.gesture_hold_ms, settings.release_ms)
        self._modifier = Hold(settings.hold_ms, settings.release_ms)
        self._gesture_raw = False  # gesture touching at the last update
        self._gesture_shown = False  # the gesture is showing both pads
        self._mod_shown = False      # the modifier reveal is on screen
        self._pressed = None         # buttons down at the last update
        self._action_ts = _UNSEEN    # last_action.ts at the last update
        self._now = 0.0

    def _holds(self):
        return (*self._pad.values(), self._gesture, self._modifier)

    def set_settings(self, settings):
        """New thresholds from the settings file, taking effect on running
        holds: a touch already under way keeps its start time."""
        self.settings = settings
        for h in (*self._pad.values(), self._modifier):
            h.hold = settings.hold_ms / 1000
        self._gesture.hold = settings.gesture_hold_ms / 1000
        for h in self._holds():
            h.release = settings.release_ms / 1000

    def update(self, state, now):
        self._now = now
        s = self.settings
        found = {}

        def want(name, content):
            found[name] = found[name].union(content) if name in found else content

        ctx = state.get("context") or {}
        if not s.enabled or state.get("unreadable") or ctx.get("gaming_mode"):
            # Partial reveals are off in gaming mode: makima's bindings
            # aren't active there, so the legends would be wrong.
            for h in self._holds():
                h.reset()
            self._gesture_raw = self._gesture_shown = self._mod_shown = False
        else:
            pads = state.get("trackpads") or {}
            gesture = bool((pads.get("gesture") or {}).get("touching")) and s.gesture_enabled
            own = {name: bool((pads.get(side) or {}).get("touching"))
                   for name, side in (("LPad", "left"), ("RPad", "right"))}
            if self._gesture_raw and not gesture:
                # The gesture ends at once, no release delay: the pad whose
                # finger lifted goes right away, and the one still touched
                # stays if the gesture was showing it.
                self._gesture.reset()
                for name, touching in own.items():
                    if not touching:
                        self._pad[name].reset()
                    elif self._gesture_shown:
                        self._pad[name].force(now)
            self._gesture_raw = gesture
            fired = {}
            for name, touching in own.items():
                # makima reports a pad's own touching as False while a
                # gesture is on. Counting the gesture as touching both keeps
                # each pad's clock running through it.
                fired[name] = self._pad[name].update((touching or gesture) and s.pad_enabled, now)
                if fired[name]:
                    want(name, FULL)
            # A gesture shows both pads once held long enough — or at once
            # when a pad is already shown: waiting there would be nonsense.
            self._gesture_shown = gesture and (self._gesture.update(True, now) or any(fired.values()))
            if not gesture:
                self._gesture.update(False, now)
            if self._gesture_shown:
                want("LPad", FULL)
                want("RPad", FULL)
            for name, content in self._modifier_reveal(state, ctx, now).items():
                want(name, content)

        wants = {name: Want(content, "detector") for name, content in found.items()}
        if self.full:
            wants = {name: Want(FULL, "full") for name in GROUPS}
        return wants

    def _modifier_reveal(self, state, ctx, now):
        """Elements for the held modifier layer — exactly the buttons that
        layer is about: its combos, the held modifier itself, and the
        modifiers that could be added next (they keep their amber outline).
        Triggered by held_modifiers or by combos alone (virtual hint modifiers never appear in
        held_modifiers). The clock runs from the first modifier held, so a
        layer change once shown takes effect at once."""
        held = list(ctx.get("held_modifiers") or ())
        combos = list((state.get("modifier_active") or {}).keys())
        raw = bool(held or combos) and self.settings.modifier_enabled
        if self._activity(state, ctx, held) and not self._mod_shown:
            # The reveal is for a hold left idle — someone unsure what to
            # press. A keystroke or a fired action (L1+A Copy) means they
            # know: the hold starts over. Once shown, it stays.
            self._modifier.restart(now)
        self._mod_shown = self._modifier.update(raw, now)
        if not self._mod_shown:
            return {}
        buttons = set(held) | set(combos) | set((ctx.get("available_modifiers") or {}).keys())
        contents = {}
        for el in ELEMENTS.values():
            own = buttons & set(el.buttons)
            if own:
                contents[el.id] = Content(frozenset(own)) if el.kind == "dpad" else FULL
        return contents

    def _activity(self, state, ctx, held):
        """A button newly pressed or an action newly fired since the last
        update. Adding a modifier doesn't count: that picks a layer."""
        pressed = frozenset(ctx.get("active_buttons") or ())
        last = state.get("last_action")
        ts = last.get("ts") if isinstance(last, dict) else None
        new_press = self._pressed is not None and bool(pressed - self._pressed - set(held))
        new_action = self._action_ts is not _UNSEEN and ts is not None and ts != self._action_ts
        self._pressed, self._action_ts = pressed, ts
        return new_press or new_action

    def next_deadline(self):
        """Next time update() would change its answer with no new state."""
        times = [t for t in (h.next_change(self._now) for h in self._holds()) if t is not None]
        return min(times) if times else None


def deadline_delay_ms(deadline, now):
    """Milliseconds until `deadline` for GLib.timeout_add: at least 1,
    rounded up, and at most an hour — its interval is 32-bit, and a huge
    threshold from the settings file would overflow it."""
    return max(1, min(3_600_000, int((deadline - now) * 1000) + 1))


class GroupAnim:
    """One group's visibility, 0..1, with its transition style.

    Starting from rest, the cause picks the style: the full HUD slides,
    a detector fades. A target flip mid-way reverses along the same path,
    from the current value — so a group already shown simply stays put
    when the full HUD opens, and one fading out fades back in place."""

    def __init__(self, settings):
        self.settings = settings
        self.target = False
        self.style = "slide"
        self.running = False
        self._v = 0.0          # current eased value
        self._from = 0.0
        self._start = 0.0
        self._dur = 0.0

    def _full_duration(self, on):
        s = self.settings
        if self.style == "slide":
            return s.slide_ms / 1000
        return (s.fade_in_ms if on else s.fade_out_ms) / 1000

    def set_target(self, on, cause, now):
        if on == self.target:
            return
        self.tick(now)
        if not self.running:
            self.style = "slide" if cause == "full" else "fade"
        self.target = on
        self._from = self._v
        self._start = now
        # Proportional to the distance left, so a reversal half-way takes
        # half as long instead of crawling back.
        self._dur = self._full_duration(on) * abs((1.0 if on else 0.0) - self._v)
        self.running = True

    def tick(self, now):
        """Advance to `now`; True while still running."""
        if not self.running:
            return False
        to = 1.0 if self.target else 0.0
        p = (now - self._start) / self._dur if self._dur > 0 else 1.0
        if p >= 1.0 - 1e-9:   # float slack: start + dur - start can land a hair short
            self._v = to
            self.running = False
            return False
        # ease-out-cubic in (fast in, soft landing), ease-in-cubic out
        e = 1 - (1 - p) ** 3 if self.target else p ** 3
        self._v = self._from + (to - self._from) * e
        return True

    def jump(self, value, target):
        """Stand still at `value`, heading nowhere — a frozen copy taking
        over an element where it was, or the element handing over to one."""
        self._v = self._from = value
        self.target = target
        self.running = False
        self.style = "fade"

    def restart_clock(self, now):
        """Re-anchor a running transition at `now`, from where it began —
        for a stall it shouldn't have spent its time on (the first frame of
        a freshly mapped window)."""
        if self.running:
            self._v = self._from
            self._start = now

    def delay(self, seconds):
        """Take a stall out of a running transition's time: it continues
        from where it was instead of jumping ahead by the stall."""
        if self.running:
            self._start += seconds

    @property
    def value(self):
        return self._v


class Crossfade:
    """An element's old picture dissolving into its new one in place, over
    crossfade_ms. `old` is whatever the window draws the old picture with.
    Its clock starts with begin() — the window's first tick after the frame
    that started it, which rebuilt every changed element and can take
    longer than the whole crossfade."""

    def __init__(self, old):
        self.old = old
        self._start = None

    def begin(self, now):
        if self._start is None:
            self._start = now

    def progress(self, now, settings):
        if self._start is None:
            return 0.0
        dur = settings.crossfade_ms / 1000
        return min(1.0, max(0.0, (now - self._start) / dur)) if dur > 0 else 1.0

    def running(self, now, settings):
        return self.progress(now, settings) < 1.0

    def delay(self, seconds):
        """Take a stall out of its time — see GroupAnim.delay."""
        if self._start is not None:
            self._start += seconds
