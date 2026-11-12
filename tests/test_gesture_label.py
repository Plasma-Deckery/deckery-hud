"""The two-pad connector's label says what two fingers do (B-12), not
makima's mode name "gestures"."""
from viewmodel import pad_legend_vm


def _state(gesture=None, touching=True):
    g = {"enabled": True, "touching": touching}
    g.update(gesture or {})
    mode = "gestures" if touching else "mt-trackpad"
    return {"trackpads": {"left": {"mode": mode}, "right": {"mode": mode},
                          "gesture": g}}


def test_gesture_names_scroll_and_zoom():
    pv = pad_legend_vm(_state())
    assert pv.gesture
    assert pv.lpad_label == pv.rpad_label == "Scroll · Zoom"


def test_gesture_label_follows_reported_actions():
    # Should makima report what the gesture pad does (tap-to-click on
    # adds a two-finger right-click), the label lists that instead.
    pv = pad_legend_vm(_state({"actions": ["scroll", "zoom", "right-click"]}))
    assert pv.lpad_label == "Scroll · Zoom · Right Click"


def test_empty_actions_fall_back():
    pv = pad_legend_vm(_state({"actions": []}))
    assert pv.lpad_label == "Scroll · Zoom"


def test_single_pad_keeps_its_mode():
    pv = pad_legend_vm(_state(touching=False))
    assert not pv.gesture
    assert pv.lpad_label == "Mt Trackpad"
