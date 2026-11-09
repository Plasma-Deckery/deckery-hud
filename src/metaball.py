"""
metaball.py — Per-pixel scalar-field "metaball" backdrop.

Each blob contributes a smooth, bounded field; fields *sum* before being
thresholded into a final alpha mask — which is what makes two nearby blobs
grow a connecting "neck" and read as one continuous shape instead of two
independently-darkened shapes stacking their alpha (plain alpha-over
compositing can only ever make an overlap *darker*, never reshape the
silhouette).

Needs numpy — a plain per-pixel Python loop over a screen's worth of
pixels times several blobs would be far too slow. No GTK, no Cairo drawing
calls beyond building the one output surface — pure array math.
"""

import numpy as np
import cairo


def render_field(sw, sh, blobs, *, low, high, max_alpha, power=2.0, downscale=1):
    """blobs: iterable of (cx, cy, r) or (cx, cy, rx, ry, weight), screen px.

    Each blob contributes weight * (1 - d²)^power inside its own ellipse
    (d² = ((x-cx)/rx)² + ((y-cy)/ry)²), zero outside — bounded and smooth,
    unlike a literal metaball kernel's r²/d², which is singular at the
    centre. The summed field goes through a smoothstep between `low` and
    `high` to become alpha (0 below `low`, `max_alpha` above `high`). The
    "neck" between two close blobs is exactly where neither one's own
    field would cross `low` but their sum does — so this has to be one
    combined field over every blob at once. A weight below 1 gives a blob
    a lighter peak of its own while still merging with its neighbours.

    downscale: compute at (sw/downscale, sh/downscale). The field is very
    low-frequency, so drawing the small result scaled up with a bilinear
    filter (see paint_scaled) is visually indistinguishable from full
    resolution, at ~1/downscale² of the cost.

    Returns a black (R=G=B=0) cairo.ImageSurface whose alpha channel is the
    field — pure black at every alpha, so already in premultiplied form.
    """
    w = max(1, int(round(sw / downscale)))
    h = max(1, int(round(sh / downscale)))
    # Sample at pixel centres of the small grid, expressed in screen px, so
    # blob coordinates stay in screen space whatever the downscale.
    xs = ((np.arange(w, dtype=np.float32) + 0.5) * (sw / w))[None, :]
    ys = ((np.arange(h, dtype=np.float32) + 0.5) * (sh / h))[:, None]
    field = np.zeros((h, w), dtype=np.float32)
    for b in blobs:
        if len(b) == 3:
            cx, cy, r = b
            rx = ry = r
            weight = 1.0
        else:
            cx, cy, rx, ry, weight = b
        if rx <= 0 or ry <= 0 or weight <= 0:
            continue
        d2 = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2
        t = np.clip(1.0 - d2, 0.0, None)
        field += weight * (t * t if power == 2.0 else t ** power)

    span = max(high - low, 1e-6)
    s = np.clip((field - low) / span, 0.0, 1.0)
    s = s * s * (3.0 - 2.0 * s)
    alpha = (s * max_alpha * 255.0).astype(np.uint8)

    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    stride = surf.get_stride()
    buf = np.ndarray(shape=(h, stride // 4, 4), dtype=np.uint8, buffer=surf.get_data())
    buf[:, :w, 0:3] = 0
    buf[:, :w, 3] = alpha
    surf.mark_dirty()
    return surf


def paint_scaled(cr, surf, sw, sh, alpha=1.0):
    """Paint a (possibly downscaled) field surface stretched over (sw, sh)
    with bilinear filtering and padded edges, so the screen border doesn't
    fade toward transparent where the filter would otherwise sample outside
    the small source."""
    w, h = surf.get_width(), surf.get_height()
    cr.save()
    cr.scale(sw / w, sh / h)
    cr.set_source_surface(surf, 0, 0)
    pat = cr.get_source()
    pat.set_filter(cairo.FILTER_BILINEAR)
    pat.set_extend(cairo.EXTEND_PAD)
    cr.rectangle(0, 0, w, h)
    cr.clip()
    cr.paint_with_alpha(alpha)
    cr.restore()
