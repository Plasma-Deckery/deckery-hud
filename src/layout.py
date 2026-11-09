"""
layout.py — HUD geometry constants.
Pure arithmetic — no GTK, no Cairo, no imports.
"""

HUD_W, HUD_H = 980, 526
_TITLE_H = 30
_GAP     = 36    # gap between front and back SVG — used for center strip
_PAD     = 14    # bottom padding (below back SVG)
_CRUMB_H = 40    # breadcrumb pill row area (between title and front SVG)

_SVG_H = (HUD_H - _TITLE_H - _GAP - _CRUMB_H - _PAD) / 2   # height per SVG

# Front SVG: viewBox 0 0 1024 414
_FVW, _FVH = 1024.0, 414.0
_FS  = _SVG_H / _FVH
_FDW = _FVW * _FS
_FX  = (HUD_W - _FDW) / 2
_FY  = _TITLE_H + _CRUMB_H

# Back SVG: viewBox 0 0 1060 429
_BVW, _BVH = 1060.0, 429.0
_BS  = _SVG_H / _BVH
_BDW = _BVW * _BS
_BX  = (HUD_W - _BDW) / 2
_BY  = _FY + _SVG_H + _GAP

# Center strip Y range (sits in the gap between the two SVGs)
_STRIP_Y = _FY + _SVG_H
_STRIP_H = _GAP

# Pause/Resume badge in title bar (HUD-local coordinates)
_PAUSE_W = 156   # badge width — fits "⏸ Controls Paused" at 11 px
_PAUSE_H = 22
_PAUSE_X = (HUD_W - _PAUSE_W) / 2
_PAUSE_Y = (_TITLE_H - _PAUSE_H) / 2

# Auth buttons in the title bar (HUD-local coordinates).
#
# Centred in the gap between the Controls badge and the right-hand pill
# cluster, so they read as their own pair rather than as two more toggles
# tacked onto On/OSD.
#
# Defined here, not in the renderer, because three places have to agree on
# them: what is drawn, what the click handler hit-tests, and — the one that
# actually decides whether a click arrives at all — the Wayland input region.
# Having them computed separately is how the first version ended up looking
# right and being dead.
_AUTH_W   = 76
_AUTH_H   = 20
_AUTH_GAP = 8
_AUTH_Y   = (_TITLE_H - _AUTH_H) / 2

_OSD_BTN_W = 48
_OSD_BTN_X = HUD_W - 28 - 16 - _OSD_BTN_W
_RMP_BTN_X = _OSD_BTN_X - 8 - _OSD_BTN_W

_AUTH_PAIR_W = 2 * _AUTH_W + _AUTH_GAP
_AUTH_GAP_L  = _PAUSE_X + _PAUSE_W        # right edge of the Controls badge
_AUTH_GAP_R  = _RMP_BTN_X                 # left edge of the On pill
_SHOW_X = _AUTH_GAP_L + (_AUTH_GAP_R - _AUTH_GAP_L - _AUTH_PAIR_W) / 2
_CHG_X  = _SHOW_X + _AUTH_W + _AUTH_GAP

# Callout anchor X: where the horizontal run terminates on each side
_AX_L = _FX - 30
_AX_R = _FX + _FDW + 30
