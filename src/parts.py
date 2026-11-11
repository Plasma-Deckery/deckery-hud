"""
parts.py — Individual controls extracted from the source SVGs as standalone,
independently-positionable vector shapes.

The front/back SVGs looked monolithic (one giant compound path per fill
layer) at a glance, but they are not scrambled — splitting each path's `d`
string at its `M` (moveto) boundaries yields clean, individually-addressable
subpaths that line up exactly with real controls: the d-pad is one 26-segment
outline, each face button (Y/X/B/A) is its own circle, the trackpad bezels,
stick rings and mini-button pills are each their own shape too. The indices
below were identified by matching each subpath's bounding box against the
known button/pad/stick coordinates in callouts.py/trackpads.py, then
confirmed by rendering them in isolation.

The shoulder triggers (L1/L2, R1/R2) aren't a clean per-button shape in
either the front or back SVG — back has one continuous "trigger well"
outline shared by both buttons, no separate L1 vs L2 shape. The third asset,
steamdeckTop.svg (the top-edge view — headphone jack, USB-C, volume, and the
very tips of the triggers as seen from directly above), turned out to have
exactly that: a single wedge-shaped trigger silhouette per side with a
diagonal line already dividing it into an L1 region and an L2 region, both
as their own clean subpaths. SHOULDER_L/SHOULDER_R below use that, not the
back-SVG well.

This module only extracts and replays path data (via svgpath.py) — no GTK,
no Rsvg.
"""

import os
import cairo
from svgpath import parse_svg_paths, replay
import theme

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONT = os.path.join(_DIR, "assets", "steamdeckFront.svg")
_BACK  = os.path.join(_DIR, "assets", "steamdeckBack.svg")
_TOP   = os.path.join(_DIR, "assets", "steamdeckTop.svg")

_front_paths = parse_svg_paths(open(_FRONT).read())
_back_paths  = parse_svg_paths(open(_BACK).read())
_top_paths   = parse_svg_paths(open(_TOP).read())

# name -> (paths list, [(path_index, subpath_index), ...])
_REGISTRY = {
    "dpad":          (_front_paths, [(0, 40)]),
    "btn_y":         (_front_paths, [(0, 34)]),
    "btn_a":         (_front_paths, [(0, 35)]),
    "btn_b":         (_front_paths, [(0, 36)]),
    "btn_x":         (_front_paths, [(0, 37)]),
    "trackpad_l":    (_front_paths, [(0, 4)]),
    "trackpad_r":    (_front_paths, [(0, 19)]),
    "pill_view":     (_front_paths, [(0, 6)]),
    "pill_start":    (_front_paths, [(0, 21)]),
    "pill_mode":     (_front_paths, [(0, 5)]),
    "pill_base":     (_front_paths, [(0, 20)]),
    "stick_l_outer": (_front_paths, [(0, 7)]),
    "stick_l_inner": (_front_paths, [(0, 8)]),
    "stick_r_outer": (_front_paths, [(0, 22)]),
    "stick_r_inner": (_front_paths, [(0, 23)]),
    "stick_l_fixed": (_front_paths, [(2, 1)]),
    "stick_r_fixed": (_front_paths, [(2, 2)]),

    "paddle_l4":     (_back_paths, [(0, i) for i in range(74, 82)]),
    "paddle_l5":     (_back_paths, [(0, i) for i in range(82, 90)]),
    "paddle_r4":     (_back_paths, [(0, i) for i in range(90, 98)]),
    "paddle_r5":     (_back_paths, [(0, i) for i in range(98, 106)]),

    # Trigger wedge + its built-in L1/L2 divider line, from the top-edge
    # view (see the module docstring) — each a clean, self-contained
    # subpath, no clipping needed.
    "shoulder_l":       (_top_paths, [(0, 45)]),
    "shoulder_l_split": (_top_paths, [(0, 23)]),
    "shoulder_r":       (_top_paths, [(0, 44)]),
    "shoulder_r_split": (_top_paths, [(0, 22)]),
}


def part_subpaths(name):
    paths, refs = _REGISTRY[name]
    return [paths[pi][si] for pi, si in refs]


def part_bbox(name):
    xs0, ys0, xs1, ys1 = [], [], [], []
    for sp in part_subpaths(name):
        from svgpath import subpath_bbox
        x0, y0, x1, y1 = subpath_bbox(sp)
        xs0.append(x0); ys0.append(y0); xs1.append(x1); ys1.append(y1)
    return min(xs0), min(ys0), max(xs1), max(ys1)


# The outline's colour and width come from the active theme (theme.outline,
# theme.outline_width; B-20).


def part_outline_points(name):
    """The part's own outline, flattened to straight-line points in its
    original SVG-space coordinates — via Cairo's own curve flattening
    (on a throwaway recording surface) rather than hand-rolling bezier
    subdivision. Meant for rough geometry (e.g. a centroid estimate for
    label placement), not for drawing."""
    surf = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
    cr = cairo.Context(surf)
    replay(cr, part_subpaths(name), 0, 0, 1.0)
    pts = []
    for kind, coords in cr.copy_path_flat():
        if kind in (cairo.PATH_MOVE_TO, cairo.PATH_LINE_TO):
            pts.append(coords)
    return pts


def clip_to_part(cr, name, ox, oy, scale):
    """Intersect the current clip with this part's own outline — e.g. so an
    active-state fill takes the part's real rounded silhouette instead of a
    plain rectangle. Caller is responsible for cr.save()/cr.restore()."""
    cr.new_path()
    replay(cr, part_subpaths(name), ox, oy, scale)
    cr.clip()


def draw_part(cr, name, ox, oy, scale, color=None, lw=None, fill_color=None):
    """fill_color: an active-state wash under the part's own outline stroke
    (kept as a separate colour/alpha from the stroke — filling with the
    stroke colour itself would wash the outline out along with the fill).
    color/lw default to the theme's outline."""
    t = theme.current()
    cr.new_path()
    replay(cr, part_subpaths(name), ox, oy, scale)
    if fill_color is not None:
        cr.set_source_rgba(*fill_color)
        cr.fill_preserve()
    cr.set_source_rgba(*(color or t.outline))
    cr.set_line_width(lw if lw is not None else t.outline_width)
    cr.stroke()
