"""
reveal.py — Which split-HUD groups are shown, with what content, and why
(B-12). Pure logic: no GTK, no Cairo, so it can be tested with a fake clock.
"""

from dataclasses import dataclass

from clusters import CLUSTER_BUTTONS, LEFT_STACK, RIGHT_STACK


@dataclass(frozen=True)
class Content:
    """What a visible group shows.

    legends:   button keys whose legends are drawn; None = all of them.
    pad_label: draw the pad's mode-label row (pad groups only).
    art:       "all" = the group's whole artwork, "pad" = only the trackpad.
    """
    legends: frozenset | None
    pad_label: bool
    art: str

    def union(self, other):
        if self.legends is None or other.legends is None:
            legends = None
        else:
            legends = self.legends | other.legends
        art = "all" if "all" in (self.art, other.art) else self.art
        return Content(legends, self.pad_label or other.pad_label, art)


FULL = Content(None, True, "all")
PAD_ONLY = Content(frozenset(), True, "pad")


GROUPS = LEFT_STACK + RIGHT_STACK + ("center",)


@dataclass(frozen=True)
class RevealSettings:
    """When single groups appear on their own, and how they animate. Every
    field maps 1:1 onto the [reveal] section of the HUD's settings file
    (B-15); the comment on each is its help text."""
    enabled: bool = True          # Show single groups without opening the HUD
    pad_enabled: bool = True      # Show a trackpad while it is used for a while
    gesture_enabled: bool = True  # Show both trackpads during a two-finger gesture
    modifier_enabled: bool = True  # Show what a held modifier unlocks
    hold_ms: int = 1500           # How long a pad or modifier is held before it shows
    gesture_hold_ms: int = 1500   # How long a gesture is held before the pads show
    release_ms: int = 500         # How long a group stays after letting go
    slide_ms: int = 260           # Duration of the slide when the full HUD opens or closes
    fade_in_ms: int = 200         # Duration of a single group fading in
    fade_out_ms: int = 300        # Duration of a single group fading out
    crossfade_ms: int = 120       # Duration of a shown group switching what it shows


@dataclass(frozen=True)
class Want:
    """A group is wanted, with this content, because of this cause:
    "full" (the full HUD) or "detector" (a single-group reveal)."""
    content: Content
    cause: str


class Hold:
    """Debounced "held for a while". raw is the live signal; drops shorter
    than release_ms count as still held. Fires once held (bridged) for
    hold_ms, and stays fired until raw has been off for release_ms."""

    def __init__(self, hold_ms, release_ms):
        self.hold = hold_ms / 1000
        self.release = release_ms / 1000
        self._since = None      # when the bridged hold began
        self._off_since = None  # when raw last went off, while still bridged

    def update(self, raw, now):
        if raw:
            self._off_since = None
            if self._since is None:
                self._since = now
        elif self._since is not None:
            if self._off_since is None:
                self._off_since = now
            if now - self._off_since >= self.release:
                self._since = self._off_since = None
        return self._since is not None and now - self._since >= self.hold

    def next_change(self, now):
        """When update() would answer differently without a new raw value."""
        if self._since is None:
            return None
        if self._off_since is not None:
            return self._off_since + self.release
        fire = self._since + self.hold
        return fire if fire > now else None

    def reset(self):
        self._since = self._off_since = None


class Reveal:
    """Which groups are wanted right now, from the full-HUD flag and the
    detectors, given makima's state. The app sets `full`; update() is fed
    every state and whenever next_deadline() comes due."""

    def __init__(self, settings):
        self.settings = settings
        self.full = False
        self._pad = {"l_pad": Hold(settings.hold_ms, settings.release_ms),
                     "r_pad": Hold(settings.hold_ms, settings.release_ms)}
        self._gesture = Hold(settings.gesture_hold_ms, settings.release_ms)
        self._modifier = Hold(settings.hold_ms, settings.release_ms)
        self._mod_contents = {}   # last non-empty modifier reveal, kept while bridged
        self._now = 0.0

    def _holds(self):
        return (*self._pad.values(), self._gesture, self._modifier)

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
            self._mod_contents = {}
        else:
            pads = state.get("trackpads") or {}
            for name, side in (("l_pad", "left"), ("r_pad", "right")):
                touching = bool((pads.get(side) or {}).get("touching"))
                if self._pad[name].update(touching and s.pad_enabled, now):
                    want(name, PAD_ONLY)
            gesture = bool((pads.get("gesture") or {}).get("touching"))
            if self._gesture.update(gesture and s.gesture_enabled, now):
                want("l_pad", PAD_ONLY)
                want("r_pad", PAD_ONLY)
            for name, content in self._modifier_reveal(state, ctx, now).items():
                want(name, content)

        wants = {name: Want(content, "detector") for name, content in found.items()}
        if self.full:
            wants = {name: Want(FULL, "full") for name in GROUPS}
        return wants

    def _modifier_reveal(self, state, ctx, now):
        """Groups for the held modifier layer, each narrowed to exactly what
        that layer is about: its combos, the held modifier itself, and the
        modifiers that could be added next. Triggered by held_modifiers or
        by combos alone (virtual hint modifiers never appear in
        held_modifiers). The clock runs from the first modifier held, so a
        layer change once shown takes effect at once."""
        held = list(ctx.get("held_modifiers") or ())
        combos = list((state.get("modifier_active") or {}).keys())
        raw = bool(held or combos) and self.settings.modifier_enabled
        if not self._modifier.update(raw, now):
            self._mod_contents = {}
            return {}
        if raw:
            buttons = set(held) | set(combos) | set((ctx.get("available_modifiers") or {}).keys())
            contents = {}
            for name in LEFT_STACK + RIGHT_STACK:
                own = buttons & set(CLUSTER_BUTTONS.get(name, ()))
                if own:
                    contents[name] = Content(frozenset(own), False, "all")
            self._mod_contents = contents
        return self._mod_contents

    def next_deadline(self):
        """Next time update() would change its answer with no new state."""
        times = [t for t in (h.next_change(self._now) for h in self._holds()) if t is not None]
        return min(times) if times else None


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

    def restart_clock(self, now):
        """Re-anchor a running transition at `now`, from where it began —
        for a stall it shouldn't have spent its time on (the first frame of
        a freshly mapped window)."""
        if self.running:
            self._v = self._from
            self._start = now

    @property
    def value(self):
        return self._v
