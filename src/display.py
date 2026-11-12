"""
display.py — which screen the HUD and the OSD go to, and how large they are
there (B-31). Pure arithmetic and name matching — no GTK: app.py, win.py and
osd_win.py apply it.

Size: everything the renderers draw is in "Deck px" — the Deck's own panel,
1164×728 logical (1280×800 at KDE's 1.1). On any other screen the windows
draw a *view* of that many Deck px and scale it up by `zoom`, so the HUD
covers the same share of the screen's height everywhere: a 4K TV at scale 1
(2160 logical px high) gets zoom ~3, its view 1294×728. A wider screen
only gives the view more width (16:9 → wider centre column), never smaller
elements. Textures are still rendered at device scale × zoom, so text and
lines stay pixel-sharp.

Output: layer-shell surfaces land wherever they are told to; "auto" follows
KWin's active output (the screen of the focused window — the game), which
App asks KWin for over D-Bus.
"""

# The Deck's own logical height — the size the HUD is designed at. 800 px
# at KDE's default 1.1 for the Deck panel.
DECK_H = 728

# Below this view width the centre column runs out of room (two columns of
# clusters take ~450), so a big `size` on a narrow screen stops growing here.
MIN_VIEW_W = 960

# Screens within this of the Deck's height draw exactly at 1: a scale off by
# a percent or two would only blur the textures for no visible gain.
_SNAP = 0.03

OUTPUTS = ("auto", "internal", "external")


def zoom(sw, sh, size=1.0):
    """Deck px → logical px of a sw×sh window; `size` is `[display] size`."""
    if sw <= 0 or sh <= 0:
        return 1.0
    base = sh / DECK_H
    if abs(base - 1.0) < _SNAP:
        base = 1.0
    k = min(base * size, sw / MIN_VIEW_W)
    return max(0.25, k)


def view(sw, sh, size=1.0):
    """(view width, view height, zoom) of a sw×sh window: the Deck px the
    renderers lay out in, and the factor that maps them back."""
    k = zoom(sw, sh, size)
    return sw / k, sh / k, k


def is_internal(connector):
    """The Deck's own panel (or a laptop's): eDP, LVDS or DSI."""
    return bool(connector) and connector.startswith(("eDP", "LVDS", "DSI"))


def pick(connectors, policy, active=None):
    """The connector name the windows go to, or None to let the compositor
    choose. connectors: the screens in GDK's order (a newly plugged one is
    last); active: KWin's active output, if known."""
    connectors = [c for c in connectors if c]
    if not connectors:
        return None
    internal = [c for c in connectors if is_internal(c)]
    external = [c for c in connectors if not is_internal(c)]
    fallback = active if active in connectors else None
    if policy == "internal":
        return internal[0] if internal else fallback or connectors[0]
    if policy == "external":
        return external[-1] if external else fallback or connectors[0]
    return fallback
