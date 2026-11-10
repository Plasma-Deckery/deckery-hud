"""
elements.py — The split HUD's unit of visibility (B-12): one *element* per
button, with its shape, its legend, its live bits and its shadow. Clusters
(clusters.py) stay the unit of layout — where a group of buttons sits and
how its legend rows stack — but what appears, fades or slides is an
element. Pure data: no GTK, no Cairo.

kind:
  "button"  — one button with its own shape (ABXY, pills, paddles)
  "upper" / "lower" — one half of the shoulder wedge (L1/R1, L2/R2)
  "dpad"    — the whole cross, with a legend row per arrow
  "stick"   — stick bezel + L3/R3 label; the moving rings are live
  "pad"     — trackpad + its mode label; the touch dot is live
  "center"  — the centre column (title, badge, breadcrumb, outputs)
"""

from dataclasses import dataclass

from clusters import LEFT_STACK, RIGHT_STACK


@dataclass(frozen=True)
class Element:
    id: str
    cluster: str     # layout unit it belongs to; None for the centre column
    buttons: tuple   # button keys whose legends and art are this element's
    parts: tuple     # parts.py shapes drawn for it
    kind: str = "button"


_ALL = (
    Element("L1", "l_shoulder", ("BTN_TL",), ("shoulder_l",), "upper"),
    Element("L2", "l_shoulder", ("BTN_TL2",), ("shoulder_l",), "lower"),
    Element("View", "l_face", ("BTN_SELECT",), ("pill_view",)),
    Element("DPad", "l_face", ("BTN_DPAD_UP", "BTN_DPAD_LEFT", "BTN_DPAD_DOWN", "BTN_DPAD_RIGHT"),
            ("dpad",), "dpad"),
    Element("L3", "l_face", ("BTN_THUMBL",), ("stick_l_fixed",), "stick"),
    Element("LPad", "l_pad", (), ("trackpad_l",), "pad"),
    Element("Steam", "l_pad", ("BTN_MODE",), ("pill_mode",)),
    Element("L4", "l_paddles", ("BTN_GRIPL",), ("paddle_l4",)),
    Element("L5", "l_paddles", ("BTN_GRIPL2",), ("paddle_l5",)),

    Element("R1", "r_shoulder", ("BTN_TR",), ("shoulder_r",), "upper"),
    Element("R2", "r_shoulder", ("BTN_TR2",), ("shoulder_r",), "lower"),
    Element("Y", "r_face", ("BTN_NORTH",), ("btn_y",)),
    Element("X", "r_face", ("BTN_WEST",), ("btn_x",)),
    Element("B", "r_face", ("BTN_EAST",), ("btn_b",)),
    Element("A", "r_face", ("BTN_SOUTH",), ("btn_a",)),
    Element("Start", "r_face", ("BTN_START",), ("pill_start",)),
    Element("R3", "r_face", ("BTN_THUMBR",), ("stick_r_fixed",), "stick"),
    Element("RPad", "r_pad", (), ("trackpad_r",), "pad"),
    Element("QAM", "r_pad", ("BTN_BASE",), ("pill_base",)),
    Element("R4", "r_paddles", ("BTN_GRIPR",), ("paddle_r4",)),
    Element("R5", "r_paddles", ("BTN_GRIPR2",), ("paddle_r5",)),

    Element("center", None, (), (), "center"),
)

ELEMENTS = {e.id: e for e in _ALL}
ELEMENT_IDS = tuple(e.id for e in _ALL)

# Which element a button's legend and art belong to.
BUTTON_ELEMENT = {b: e.id for e in _ALL for b in e.buttons}


def side_of(element_id):
    """"left" | "right" for an element of a side cluster, None for center."""
    cluster = ELEMENTS[element_id].cluster
    if cluster in LEFT_STACK:
        return "left"
    if cluster in RIGHT_STACK:
        return "right"
    return None
