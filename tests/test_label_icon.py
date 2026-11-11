"""B-17: a label may start with a Unicode symbol ("☀ Brightness Up") —
the split renderer pulls it out and draws it in its own slot on the button
side. The icon comes from the config label; the HUD only splits it off."""

import cairo

from helpers import capture_text_boxes
from viewmodel import split_icon


def test_leading_symbol_is_split_off():
    assert split_icon("☀ Brightness Up") == ("☀", "Brightness Up")
    assert split_icon("⏯ Play / Pause") == ("⏯", "Play / Pause")
    assert split_icon("🔇 Mute") == ("🔇", "Mute")


def test_variation_selector_stays_with_the_icon():
    assert split_icon("🔇︎ Mute") == ("🔇︎", "Mute")


def test_plain_labels_have_no_icon():
    for text in ("Brightness Up", "(Steam Keyboard)", "Ctrl+PgDn", "—", "", "F10"):
        assert split_icon(text) == (None, text)


def test_a_glyph_on_its_own_is_the_label_not_an_icon():
    # _fmt turns KEY_BACKSPACE into a bare "⌫", KEY_UP into "↑" — that is
    # the whole label, nothing to set beside it.
    assert split_icon("⌫") == (None, "⌫")
    assert split_icon("☀") == (None, "☀")


def test_symbol_glued_to_text_is_not_an_icon():
    assert split_icon("☀Brightness") == (None, "☀Brightness")


# ── Drawing: split sets the icon apart on the button side, classic drops it ──


def _texts_drawn(draw, *args, **kw):
    cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 100))
    with capture_text_boxes() as cap:
        draw(cr, *args, **kw)
    return list(zip(cap.texts, cap.boxes))


def test_txt_icon_puts_the_icon_at_the_anchor_end():
    from helpers import _txt_icon
    # Left-anchored (left half of the HUD): icon left of the text.
    (i_t, i_box), (t_t, t_box) = _texts_drawn(_txt_icon, 50, 50, "☀ Brightness Up",
                                               size=13, ha="left", va="mid")
    assert (i_t, t_t) == ("☀", "Brightness Up")
    assert i_box[0] + i_box[2] <= t_box[0]
    # Right-anchored (right half): mirrored, icon right of the text, still
    # ending at the anchor.
    (i_t, i_box), (t_t, t_box) = _texts_drawn(_txt_icon, 350, 50, "📷 Screenshot",
                                               size=13, ha="right", va="mid")
    assert t_box[0] + t_box[2] <= i_box[0]
    assert i_box[0] + i_box[2] <= 350 + 0.5


def test_txt_icon_keeps_text_flush_whatever_the_glyph_width():
    from helpers import _txt_icon
    xs = [_texts_drawn(_txt_icon, 50, 50, f"{g} Label", size=13, ha="left")[1][1][0]
          for g in ("☀", "⏮", "🔇", "⏻")]
    assert max(xs) - min(xs) < 0.5


def test_plain_label_draws_as_before():
    from helpers import _txt_icon
    assert [t for t, _ in _texts_drawn(_txt_icon, 50, 50, "Toggle HUD", ha="left")] == ["Toggle HUD"]


def _row(action):
    from callouts import _Callout
    return _Callout(sort_y=50, dot_x=10, dot_y=50, name="L4", action=action, bound=True)


def test_classic_callouts_show_the_label_without_its_icon():
    from callouts import _callouts
    texts = [t for t, _ in _texts_drawn(_callouts, [_row("⏯ Play / Pause")], "right", 100)]
    assert texts == ["L4: Play / Pause"]


def test_split_callouts_draw_the_icon():
    from callouts import _callouts
    e = _row("⏯ Play / Pause")
    e.show_name = False
    texts = [t for t, _ in _texts_drawn(_callouts, [e], "right", 100, size=13, icons=True)]
    assert texts == ["⏯", "Play / Pause"]


def test_note_lines_up_with_the_text_not_the_icon():
    from callouts import _callouts
    e = _row("⏯ Play / Pause")
    e.show_name, e.note = False, "halten"
    drawn = dict(_texts_drawn(_callouts, [e], "right", 100, size=13, icons=True))
    assert abs(drawn["halten"][0] - drawn["Play / Pause"][0]) < 0.5
