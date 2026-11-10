"""
reveal.py — Which split-HUD groups are shown, with what content, and why
(B-12). Pure logic: no GTK, no Cairo, so it can be tested with a fake clock.
"""

from dataclasses import dataclass


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
