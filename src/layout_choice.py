"""
layout_choice.py — which HUD design (classic or split) is selected.

The one place the mode is read (win.py, at import) and written (the in-HUD
switch buttons, via App.switch_layout). Kept out of win.py on purpose:
switching rebuilds the window by reloading win.py, so the choice has to live
in a module that is not reloaded with it.

The stored choice is `layout.design` in the HUD settings file (settings.py);
DECKERY_HUD_LAYOUT is not read any more.
"""

from contextlib import contextmanager

import settings

_building = None   # the design a switch is rebuilding win.py for, see building()


def current():
    """The design win.py sets itself up for."""
    if _building is not None:
        return _building
    return settings.load().layout.design


def remember(mode):
    """Store the choice for the next start. False if it could not be saved
    (settings.remember has already warned); the switch happens anyway."""
    return settings.remember("layout.design", mode)


@contextmanager
def building(mode):
    """Make current() return `mode` while win.py is reloaded for a switch —
    so the switch happens even when the choice could not be saved, or the
    file says something else by the time it is read."""
    global _building
    _building = mode
    try:
        yield
    finally:
        _building = None
