"""
clusters.py — Per-cluster crop rectangles into the existing front/back SVGs,
for the split renderer (issue #21). Pure data: no GTK, no Cairo.

Each rectangle is in the source SVG's own coordinate space (front viewBox
0 0 1024 414, back viewBox 0 0 1060 429) and was derived from the button/pad/
stick coordinates callouts.py and trackpads.py already carry, padded out to
contain the group with a little breathing room. These are a starting point —
nudge the numbers and re-render tools/render_sample.py's "split" output to
check, rather than reasoning about them in the abstract.

Layout, top → bottom, mirrored left/right:
  shoulder  (back)  — L1/L2 or R1/R2
  face      (front) — D-pad+View+LStick, or Y/X/B/A+Start+RStick
  pad       (front) — trackpad + Steam/Mode or trackpad + QAM(BTN_BASE)
  paddles   (back)  — L4/L5 or R4/R5

Button keys belonging to each cluster (used by the split renderer to decide
which callouts attach to which cluster's inward edge):
"""

CLUSTER_ORDER = ("shoulder", "face", "pad", "paddles")

CLUSTER_BUTTONS = {
    "l_shoulder": ("BTN_TL", "BTN_TL2"),
    "l_face":     ("BTN_DPAD_UP", "BTN_DPAD_LEFT", "BTN_DPAD_DOWN", "BTN_DPAD_RIGHT",
                    "BTN_THUMBL", "BTN_SELECT"),
    "l_pad":      ("BTN_MODE",),   # + synthetic "LPad" legend row
    "l_paddles":  ("BTN_GRIPL", "BTN_GRIPL2"),

    "r_shoulder": ("BTN_TR", "BTN_TR2"),
    "r_face":     ("BTN_NORTH", "BTN_WEST", "BTN_EAST", "BTN_SOUTH",
                    "BTN_THUMBR", "BTN_START"),
    "r_pad":      ("BTN_BASE",),   # + synthetic "RPad" legend row
    "r_paddles":  ("BTN_GRIPR", "BTN_GRIPR2"),
}

# (svg, (x0, y0, x1, y1)) — svg is "front" (viewBox 1024x414) or "back" (1060x429)
#
# Tuned against a standalone render of each SVG (tools/render_sample.py
# doesn't do this — see the session notes): the body/case outline is not a
# separate shape from the buttons in these files (one monolithic compound
# path per fill layer, see clusters.py's own module docstring), so every box
# below is deliberately cut to fall *inside* the case edge rather than
# merely "around" the control — a box that reaches the case's outer stroke
# at y≈0 (top edge) or the hand-grip curve near the pad clusters pulls that
# line in too. Front SVG also carries the speaker-grille dot row directly
# below the Mode/Steam button (y≈316-343) — pad cluster boxes stop above it
# on purpose, it's not a control.
CLUSTERS = {
    "l_shoulder": ("top",   (10, 108, 165, 212)),
    "l_face":     ("front", (20,  16, 222, 155)),
    "l_pad":      ("front", (88, 140, 212, 306)),
    "l_paddles":  ("back",  (85, 175, 215, 350)),

    "r_shoulder": ("top",   (895, 108, 1050, 212)),
    "r_face":     ("front", (802,  16, 1004, 155)),
    "r_pad":      ("front", (812, 140, 936, 306)),
    "r_paddles":  ("back",  (845, 175, 975, 350)),
}

# Which clusters stack on which screen edge, top to bottom.
LEFT_STACK  = ("l_shoulder", "l_face", "l_pad", "l_paddles")
RIGHT_STACK = ("r_shoulder", "r_face", "r_pad", "r_paddles")


def cluster_rect(name):
    """(svg_name, (x0, y0, x1, y1)) for one cluster."""
    return CLUSTERS[name]


def cluster_size(name):
    svg, (x0, y0, x1, y1) = CLUSTERS[name]
    return x1 - x0, y1 - y0
