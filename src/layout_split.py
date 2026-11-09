"""
layout_split.py — Split-renderer geometry. Pure arithmetic — no GTK, no
Cairo — same spirit as layout.py, but computed from the actual screen size
instead of a fixed virtual canvas: the split layout is meant to use the
whole screen, not a panel centred in it.
"""

from clusters import CLUSTERS, LEFT_STACK, RIGHT_STACK

# A cluster's (x0,x1) are pixel coordinates in its *own* source SVG's
# viewBox — front is 1024 wide, back/top are 1060. _stack_rects compares
# coordinates across clusters from different source SVGs within one stack
# (e.g. l_face is "front", l_shoulder is "top"), so those raw pixel values
# have to be normalized into a common unit first or the comparison is
# comparing two different rulers — confirmed live: this produced a ~17%
# max_reach difference between the left and right stacks (212 vs 248) even
# though every individual cluster's own crop is a true mirror, which is
# exactly why the two sides were rendering at visibly different sizes.
_VIEWBOX_W = {"front": 1024.0, "back": 1060.0, "top": 1060.0}

# Fraction of screen width each side's column of clusters occupies at rest.
# The rest (1 - 2*COL_FRAC) is the centre legend/chrome column.
COL_FRAC    = 0.17
MAX_COL_W   = 190    # px — hard cap so a tall/large screen doesn't blow these up further

MARGIN_Y   = 0.012  # fraction of screen height, top/bottom margin — small on purpose,
                     # see _stack_rects: leftover vertical space becomes gap, not margin
MARGIN_X   = 34      # px gap kept clear between the true screen edge and the clusters
INSET      = 30     # px past the column's inner edge where callout lines anchor —
                     # pulled in further still on request (130 -> 80 -> 50 -> 30), so
                     # legend text keeps sitting further out toward the edge/
                     # cluster, away from the centre column


def _stack_rects(stack, side, sw, sh):
    """[(cluster_name, x, y, w, h, scale), ...] stacked top→bottom, at rest
    (open_t=1, no transition offset).

    All clusters in a stack share one scale factor — picked once for the
    whole stack, not recomputed per cluster — so a narrow cluster (e.g. the
    shoulder) renders narrower than a wide one (e.g. the trackpad) exactly as
    on the real device, instead of every cluster being independently
    stretched to fill the same column width.

    Clusters also keep their relative X position from the source art instead
    of all being flushed to the screen edge: on the real device the trackpad
    sits inset from the edge (between the d-pad and the stick, roughly), and
    the paddles are inset too — only the shoulder cluster actually reaches
    the true edge. The cluster whose source edge is closest to the device's
    own edge renders flush to the screen edge; every other cluster is offset
    inward by exactly its source-space distance from that one, scaled.

    The gap between clusters isn't a fixed fraction either — the column
    width cap (COL_FRAC/MAX_COL_W) is almost always the binding constraint
    on scale, not the available height, which used to leave a lot of unused
    vertical space sitting as dead margin above the first cluster and below
    the last. Instead, the margin stays small and fixed, and whatever
    vertical space is left over after scaling is spent as extra gap between
    clusters — so the stack actually spans from just past the top edge to
    just short of the bottom one, shoulder near the top, paddles near the
    bottom, instead of floating in the middle of the screen with air on
    both ends.
    """
    margin_y = sh * MARGIN_Y
    avail_h  = sh - 2 * margin_y

    specs = []   # (name, vbw, nx0, nx1, nh) — n* normalized by *that cluster's own* viewBox width,
                 # so every cluster's coordinates are expressed as a fraction of its own source image
                 # before any cross-cluster arithmetic touches them
    for name in stack:
        svg, (x0, y0, x1, y1) = CLUSTERS[name]
        vbw = _VIEWBOX_W[svg]
        specs.append((name, vbw, x0 / vbw, x1 / vbw, (y1 - y0) / vbw))

    # The flush point: the outermost source edge across the whole stack, now
    # comparable because every x is a fraction of its own image's width.
    # Left stack renders flush-left from its smallest x0; right stack renders
    # flush-right from its largest x1 (mirrored, since "outer" is the other
    # direction there).
    if side == "left":
        ref_edge  = min(nx0 for _, _vbw, nx0, _nx1, _nh in specs)
        max_reach = max(nx1 - ref_edge for _, _vbw, _nx0, nx1, _nh in specs)
    else:
        ref_edge  = max(nx1 for _, _vbw, _nx0, nx1, _nh in specs)
        max_reach = max(ref_edge - nx0 for _, _vbw, nx0, _nx1, _nh in specs)

    total_src_h = sum(nh for *_, nh in specs)

    scale_w = min(sw * COL_FRAC, MAX_COL_W) / max_reach
    scale_h = avail_h / total_src_h if total_src_h > 0 else scale_w
    nscale  = min(scale_w, scale_h)   # pixels per normalized unit

    col_w   = max_reach * nscale
    total_h = total_src_h * nscale
    gap = (avail_h - total_h) / (len(stack) - 1) if len(stack) > 1 else 0.0
    y = margin_y

    rects = []
    for name, vbw, nx0, nx1, nh in specs:
        scale = nscale / vbw   # back to this cluster's own SVG-pixel-to-screen-pixel factor
        w, h = (nx1 - nx0) * nscale, nh * nscale
        if side == "left":
            x = MARGIN_X + (nx0 - ref_edge) * nscale
        else:
            x = sw - MARGIN_X - w - (ref_edge - nx1) * nscale
        rects.append((name, x, y, w, h, scale))
        y += h + gap
    # col_w here means "how far this stack reaches from the true screen edge"
    # — used downstream for the centre column's bounds and the callout
    # anchor, both of which need to start past MARGIN_X too.
    return rects, col_w + MARGIN_X


def compute_layout(sw, sh):
    """Everything the split renderer needs for one frame, at rest.

    Returns:
      clusters: {name: (x, y, w, h, scale)}  — target screen rect + src→screen scale
      anchor_x: {"left": x, "right": x}       — where inward callout lines terminate
      center:   (x0, y0, x1, y1)              — legend/chrome column bounds
    """
    left_rects,  lcol_w = _stack_rects(LEFT_STACK,  "left",  sw, sh)
    right_rects, rcol_w = _stack_rects(RIGHT_STACK, "right", sw, sh)

    clusters = {}
    for name, x, y, w, h, scale in left_rects + right_rects:
        clusters[name] = (x, y, w, h, scale)

    anchor_x = {"left": lcol_w + INSET, "right": sw - rcol_w - INSET}
    center = (lcol_w, 0.0, sw - rcol_w, sh)
    return clusters, anchor_x, center


def center_badge_rect(center):
    """Pause/Resume badge rect in the centre column — shared by the renderer
    (drawing) and win.py (hit-testing), so they can't drift apart (see
    layout.py's own note on this for the classic renderer)."""
    x0, y0, x1, y1 = center
    cw = x1 - x0
    cx = (x0 + x1) / 2
    badge_w, badge_h = min(220, cw - 20), 26
    bx, by = cx - badge_w / 2, y0 + 50
    return bx, by, badge_w, badge_h


def center_close_rect(center):
    """Close-button hit rect (and the circle it's drawn as) in the centre column."""
    x0, y0, x1, y1 = center
    ccx, ccy, r = x1 - 26, y0 + 26, 11
    return ccx - r, ccy - r, 2 * r, 2 * r
