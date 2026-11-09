"""
svgpath.py — Minimal SVG <path d="..."> parser.

The deckery-hud SVGs use only M/L/H/V/C/Z, all absolute (verified against
the actual files) — not a general SVG path engine, just enough to split a
compound path into its individual subpaths with absolute coordinates, which
is what the asset-splitting in parts.py needs.
"""

import re

_NUM = re.compile(r'[-+]?(?:\d+\.\d+|\.\d+|\d+)(?:[eE][-+]?\d+)?')


def _tokenize(d):
    tokens = []
    i, n = 0, len(d)
    while i < n:
        c = d[i]
        if c in 'MLHVCZ':
            tokens.append(('cmd', c))
            i += 1
        elif c in ' \t\r\n,':
            i += 1
        else:
            m = _NUM.match(d, i)
            if not m:
                raise ValueError(f"unexpected char {c!r} at {i}")
            tokens.append(('num', float(m.group())))
            i = m.end()
    return tokens


def parse_path(d):
    """'d' attribute string -> list of subpaths. Each subpath is a list of
    tuples: ('M', x, y) | ('L', x, y) | ('C', x1,y1,x2,y2,x,y) | ('Z',) —
    all coordinates absolute. A new subpath starts at each 'M'."""
    tokens = _tokenize(d)
    i, n = 0, len(tokens)
    subpaths, cur = [], None
    cx = cy = start_x = start_y = 0.0
    cmd = None

    def nums(k):
        nonlocal i
        vals = []
        for _ in range(k):
            vals.append(tokens[i][1])
            i += 1
        return vals

    while i < n:
        if tokens[i][0] == 'cmd':
            cmd = tokens[i][1]
            i += 1
        if cmd == 'M':
            x, y = nums(2)
            cur = [('M', x, y)]
            subpaths.append(cur)
            cx = cy = start_x = start_y = None
            cx, cy, start_x, start_y = x, y, x, y
            cmd = 'L'
        elif cmd == 'L':
            x, y = nums(2)
            cur.append(('L', x, y))
            cx, cy = x, y
        elif cmd == 'H':
            x, = nums(1)
            cur.append(('L', x, cy))
            cx = x
        elif cmd == 'V':
            y, = nums(1)
            cur.append(('L', cx, y))
            cy = y
        elif cmd == 'C':
            x1, y1, x2, y2, x, y = nums(6)
            cur.append(('C', x1, y1, x2, y2, x, y))
            cx, cy = x, y
        elif cmd == 'Z':
            cur.append(('Z',))
            cx, cy = start_x, start_y
        else:
            raise ValueError(f"unsupported command {cmd!r}")
    return subpaths


def subpath_bbox(subpath):
    xs, ys = [], []
    for seg in subpath:
        if seg[0] == 'Z':
            continue
        xs.extend(seg[1::2])
        ys.extend(seg[2::2])
    return min(xs), min(ys), max(xs), max(ys)


def parse_svg_paths(svg_text):
    """All <path d="..."> strings in document order -> list of (list of subpaths)."""
    ds = re.findall(r'<path[^>]*\bd="([^"]*)"', svg_text)
    return [parse_path(d) for d in ds]


def replay(cr, subpaths, ox, oy, scale):
    """Draw a list of subpaths (as returned by parse_path) with Cairo,
    translated by (ox, oy) and scaled — the same convention as every other
    SVG-space-to-screen-space transform in this codebase."""
    for sp in subpaths:
        for seg in sp:
            if seg[0] == 'M':
                cr.move_to(ox + seg[1] * scale, oy + seg[2] * scale)
            elif seg[0] == 'L':
                cr.line_to(ox + seg[1] * scale, oy + seg[2] * scale)
            elif seg[0] == 'C':
                cr.curve_to(ox + seg[1] * scale, oy + seg[2] * scale,
                            ox + seg[3] * scale, oy + seg[4] * scale,
                            ox + seg[5] * scale, oy + seg[6] * scale)
            elif seg[0] == 'Z':
                cr.close_path()
