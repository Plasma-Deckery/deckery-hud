"""B-18: while the Gaming Mode trigger (···) is held as a modifier, its own
"(dbl-click) Gaming Mode" line goes — the hold is picking a combo layer."""

import copy

from render_sample import SAMPLES
from viewmodel import classify_button


def _state(held):
    state = copy.deepcopy(SAMPLES["held_modifier"])
    state["context"]["held_modifiers"] = held
    state["context"]["active_buttons"] = held
    return state


def test_gaming_line_shows_when_the_trigger_is_not_held():
    vm = classify_button("BTN_BASE", _state([]))
    assert vm.sub_label == "(dbl-click) Gaming Mode"


def test_gaming_line_goes_while_the_trigger_is_held_as_a_modifier():
    vm = classify_button("BTN_BASE", _state(["BTN_BASE"]))
    assert vm.active_mod
    assert vm.sub_label is None and not vm.sub_active


def test_gaming_line_stays_while_another_modifier_is_held():
    assert classify_button("BTN_BASE", _state(["BTN_TL"])).sub_label == "(dbl-click) Gaming Mode"
