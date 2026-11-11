"""
osd_anim.py — How the OSD's toasts and active-output pills come and go (B-21).

Named presets, picked with `[osd] animation` (settings.py) and meant to move
into themes later (B-20). Two kinds:

  slide — the original: a toast rises from below the screen edge and fades;
          the pill row just appears and disappears. Toasts are drawn by
          toast.draw_toast exactly as before.
  pop   — at a fixed spot bottom centre: a finished sprite (osd_look.py)
          scales up around its own centre while fading in, with an optional
          overshoot, and shrinks while fading out. Only the sprite is scaled,
          never re-laid-out text, so letters can't jitter between frames.

Pure Python, no GTK.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OsdAnimation:
    kind: str             # "slide" or "pop"
    toast_bottom: float   # pop: px from the screen's bottom edge to a toast's centre
    in_ms: int            # pop-in
    out_ms: int           # bubble-out
    scale_from: float     # scale a pop-in starts at
    scale_to: float       # scale a bubble-out ends at
    overshoot: float      # back-easing strength on the way in; 0 = none
    fade_in_frac: float = 0.6   # share of in_ms the fade-in takes


PRESETS = {
    "pop": OsdAnimation("pop", toast_bottom=74, in_ms=240, out_ms=220,
                        scale_from=0.55, scale_to=0.8, overshoot=1.7),
    "bubble-soft": OsdAnimation("pop", toast_bottom=74, in_ms=420, out_ms=380,
                                scale_from=0.85, scale_to=0.92, overshoot=0.0,
                                fade_in_frac=1.0),
    "slide": OsdAnimation("slide", toast_bottom=0, in_ms=0, out_ms=0,
                          scale_from=1.0, scale_to=1.0, overshoot=0.0),
}
CHOICES = ("auto",) + tuple(PRESETS)


def resolve(name, split):
    """The preset for setting value `name`; "auto" is pop in the split
    design and slide in classic."""
    if name == "auto" or name not in PRESETS:
        return PRESETS["pop" if split else "slide"]
    return PRESETS[name]


def _ease_out_back(t, s):
    t -= 1.0
    return 1.0 + (s + 1.0) * t * t * t + s * t * t


def envelope(anim, since_in, since_out=None):
    """(scale, alpha) of a pop sprite `since_in` seconds after it appeared
    and, once it is leaving, `since_out` seconds after that; None when it is
    gone. A leave cut short by an unfinished pop-in starts from wherever the
    pop-in had got to."""
    t_in = min(1.0, max(0.0, since_in * 1000 / anim.in_ms))
    scale = anim.scale_from + (1.0 - anim.scale_from) * _ease_out_back(t_in, anim.overshoot)
    alpha = min(1.0, t_in / anim.fade_in_frac)
    if since_out is None:
        return scale, alpha
    t = since_out * 1000 / anim.out_ms
    if t >= 1.0:
        return None
    t = max(0.0, t)
    k = t * t                     # ease-in: leaves gently, then goes
    return scale + (anim.scale_to - scale) * k, alpha * (1.0 - t ** 1.6)


def animating(anim, since_in, since_out=None):
    """True while the pop sprite is moving (needs frames), False while it
    just sits there."""
    if since_out is not None:
        return since_out * 1000 < anim.out_ms
    return since_in * 1000 < anim.in_ms
