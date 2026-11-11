"""B-18: a binding's `note` (makima `note = "…"`) shows as a dimmed second
line under its action in the split design. Needs cairo/numpy — run in the
`deckery` distrobox."""

import copy

import cairo
import numpy as np

from render_sample import SAMPLES, _svg
from renderer_split import draw_hud_split
from reveal import FULL
from viewmodel import classify_button

SW, SH = 1280, 800


def _combo(label, note=None):
    b = {"action": ["KEY_LEFTCTRL"], "kind": "remap", "label": label, "origin": "Voice Control"}
    if note:
        b["note"] = note
    return b


def _l1_state(**combos):
    state = copy.deepcopy(SAMPLES["held_modifier"])
    state["modifier_active"] = dict(combos)
    return state


def test_note_comes_from_the_binding_in_effect():
    state = _l1_state(BTN_GRIPR2=_combo("Text to Speech", "halten"))
    assert classify_button("BTN_GRIPR2", state).note == "halten"
    # The base binding's note does not leak onto a combo that replaces it.
    state["bindings"]["BTN_SOUTH"] = dict(_combo("Enter", "halten"), origin="Steam Deck")
    state["modifier_active"]["BTN_SOUTH"] = _combo("Redo")
    assert classify_button("BTN_SOUTH", state).note is None


def test_no_note_without_a_binding():
    state = _l1_state()
    state["bindings"]["BTN_GRIPR2"] = {"action": [], "kind": "remap", "label": None, "note": "halten"}
    assert classify_button("BTN_GRIPR2", state).note is None


def _render(state, elements):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, SW, SH)
    cr = cairo.Context(surf)
    draw_hud_split(cr, _svg("steamdeckFront.svg"), _svg("steamdeckBack.svg"), state, SW, SH,
                   groups={e: (1.0, 0.0, FULL) for e in elements})
    surf.flush()
    return np.ndarray((SH, surf.get_stride() // 4, 4), np.uint8, surf.get_data())[:, :SW].copy()


def _note_pixels(button, element):
    """Pixels that change when `button`'s combo gains a note."""
    plain = _render(_l1_state(**{button: _combo("Text to Speech")}), ["L1", element])
    noted = _render(_l1_state(**{button: _combo("Text to Speech", "halten")}), ["L1", element])
    return np.argwhere((plain != noted).any(axis=2))


def test_paddle_note_draws_a_second_line():
    changed = _note_pixels("BTN_GRIPR2", "R5")
    assert len(changed), "the note drew nothing"
    # Beside the paddle (bottom right), toward the centre — the text sits left
    # of the paddle; its ink-following shadow may reach a little further.
    assert changed[:, 0].min() > SH // 2
    assert (changed[:, 1] < 1080).any()


def test_callout_note_draws_a_second_line():
    assert len(_note_pixels("BTN_SOUTH", "A")), "the note drew nothing"
