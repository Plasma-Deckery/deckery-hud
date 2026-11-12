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


# ── Themed stand-ins: ▦ desktop, ✣ activity, 🗔 window drawn as Breeze icons ──


def _fake_breeze(monkeypatch, found=True):
    import icons
    drawn = []

    def draw_icon(cr, name, cx, cy, size_px, color):
        drawn.append(name)
        return found
    monkeypatch.setattr(icons, "draw_icon", draw_icon)
    return drawn


def test_stand_ins_split_off_as_one_icon_head():
    assert split_icon("🗔▦⮝ Window to Previous Desktop") == ("🗔▦⮝", "Window to Previous Desktop")
    assert split_icon("✣⮜ Previous Activity") == ("✣⮜", "Previous Activity")


def test_stand_ins_draw_as_their_breeze_icons(monkeypatch):
    from helpers import _txt_icon
    drawn = _fake_breeze(monkeypatch)
    boxes = _texts_drawn(_txt_icon, 50, 50, "🗔▦⮝ Window to Previous Desktop", size=13, ha="left", va="mid")
    assert drawn == ["window", "virtual-desktops-symbolic"]
    # The icons are noted like glyphs (the legend shadow covers them), in
    # reading order, the arrow stays text.
    assert [t for t, _ in boxes] == ["🗔", "▦", "⮝", "Window to Previous Desktop"]
    xs = [b[0] for _t, b in boxes]
    assert xs == sorted(xs)


def test_stand_in_falls_back_to_its_glyph_without_breeze(monkeypatch):
    from helpers import _txt_icon
    _fake_breeze(monkeypatch, found=False)
    boxes = _texts_drawn(_txt_icon, 50, 50, "✣⮞ Next Activity", size=13, ha="left", va="mid")
    assert [t for t, _ in boxes] == ["✣", "⮞", "Next Activity"]


def test_heads_of_the_same_make_keep_text_flush(monkeypatch):
    from helpers import _txt_icon
    _fake_breeze(monkeypatch)
    for heads in (("▦⮝", "▦⮜", "✣⮞", "✣⮟"), ("🗔▦⮝", "🗔✣⮜", "🗔▦⮟")):
        for ha, x in (("left", 50), ("right", 350)):
            ends = []
            for h in heads:
                _t, box = _texts_drawn(_txt_icon, x, 50, f"{h} Label", size=13, ha=ha, va="mid")[-1]
                ends.append(box[0] if ha == "left" else box[0] + box[2])
            assert max(ends) - min(ends) < 0.5, (heads, ha)


def test_toast_centres_icon_and_text_as_one(monkeypatch):
    from helpers import _txt_icon
    _fake_breeze(monkeypatch)
    boxes = _texts_drawn(_txt_icon, 200, 50, "▦⮞ Next Desktop", size=11, ha="center", va="mid", bold=True)
    assert [t for t, _ in boxes] == ["▦", "⮞", "Next Desktop"]
    left, right = boxes[0][1][0], boxes[-1][1][0] + boxes[-1][1][2]
    assert abs((left + right) / 2 - 200) < 1


def test_toast_sets_any_icon_apart_from_its_text():
    from helpers import _txt_icon
    boxes = _texts_drawn(_txt_icon, 200, 50, "☀ Brightness Up", size=11, ha="center", va="mid")
    assert [t for t, _ in boxes] == ["☀", "Brightness Up"]
    left, right = boxes[0][1][0], boxes[-1][1][0] + boxes[-1][1][2]
    assert abs((left + right) / 2 - 200) < 2


# ── Vertical centring: a symbol's ink sits halfway up the capitals ──


def _ink_mid(box):
    return box[1] + box[3] / 2


def test_icons_centre_on_the_cap_height_whatever_their_font():
    # Fallback fonts (Noto Sans Symbols 2 for 🎮) bring their own ascent and
    # line height; centring the layout box put 🎮 high. The ink is centred.
    from helpers import _txt_icon, _cap_mid
    cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 100))
    for ha in ("left", "right", "center"):
        mid = _cap_mid(cr, 50, "Toggle HUD", 13, "mid")
        for g in ("🎮", "⚙", "⇄", "☀", "⏯", "🔇"):
            (_t, box), _rest = _texts_drawn(_txt_icon, 200, 50, f"{g} Toggle HUD", size=13, ha=ha, va="mid")
            assert abs(_ink_mid(box) - mid) <= 0.5, (g, ha)


def test_cap_mid_is_halfway_up_the_capitals():
    from helpers import _cap_mid, _txt
    boxes = _texts_drawn(_txt, 50, 50, "H", size=13, va="mid")
    cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 100))
    from helpers import _layout
    lo = _layout(cr, "H", 13)
    ink = lo.get_pixel_extents()[0]
    top = boxes[0][1][1]
    assert abs(_cap_mid(cr, 50, "H", 13, "mid") - (top + ink.y + ink.height / 2)) <= 0.5


# ── Mouse-click glyphs get the legend's shadow plate like any text ──


def test_click_icon_is_noted_for_the_shadow(monkeypatch):
    import renderer_split as R
    drawn = _fake_breeze(monkeypatch)
    boxes = _texts_drawn(R._draw_click_icon, "BTN_LEFT", 100, 50, "left", (1, 0.8, 0.2, 1))
    assert drawn == ["input-mouse-click-left-symbolic"]
    assert len(boxes) == 1
    _t, (x, y, w, h) = boxes[0]
    assert x >= 100 and abs(y + h / 2 - 50) < 0.5 and w == h > 0


def test_missing_click_icon_falls_back_to_the_noted_mouse(monkeypatch):
    import icons
    import renderer_split as R
    drawn = []

    def draw_icon(cr, name, cx, cy, size_px, color):
        drawn.append(name)
        return name == R._MOUSE_ICON_NAME
    monkeypatch.setattr(icons, "draw_icon", draw_icon)
    boxes = _texts_drawn(R._draw_click_icon, "BTN_RIGHT", 100, 50, "right", (1, 1, 1, 1))
    assert drawn == ["input-mouse-click-right-symbolic", R._MOUSE_ICON_NAME]
    assert len(boxes) == 1
