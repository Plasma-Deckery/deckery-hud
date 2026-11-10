"""
layout_choice.py — which HUD design (classic or split) is selected.

The one place the mode is read (win.py, at import) and written (the in-HUD
switch buttons, via App.switch_layout). Kept out of win.py on purpose:
switching rebuilds the window by reloading win.py, so the choice has to live
in a module that is not reloaded with it.

For now the in-HUD choice only lasts until the service restarts. Persisting
it comes with the HUD settings file (backlog B-15): these two functions then
become settings.load().layout.design and settings.remember("layout.design",
mode), and DECKERY_HUD_LAYOUT is no longer read at all.
"""

import os

_MODES = ("classic", "split")
_chosen = None   # set by remember(); None = nothing chosen in this run


def current():
    """The design to use: the in-HUD choice, else DECKERY_HUD_LAYOUT, else classic."""
    if _chosen is not None:
        return _chosen
    mode = os.environ.get("DECKERY_HUD_LAYOUT", "classic")
    return mode if mode in _MODES else "classic"


def remember(mode):
    global _chosen
    if mode not in _MODES:
        raise ValueError(f"unknown HUD layout {mode!r}")
    _chosen = mode
