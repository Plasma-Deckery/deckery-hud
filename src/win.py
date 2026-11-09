"""
win.py — Deckery HUD window (GTK4, layer-shell, Cairo drawing).

Created hidden by App; shown/hidden via App.show_hud() / App.hide_hud().
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
gi.require_version('Rsvg', '2.0')
gi.require_version('Graphene', '1.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gsk', '4.0')
from gi.repository import Gtk, Gio, Gtk4LayerShell as LayerShell, Rsvg, GLib, Graphene, Gdk, Gsk
import cairo
import os
import time

from ipc import makima_pause, makima_resume, _FRONT_SVG, _BACK_SVG
from layout import (HUD_W, HUD_H, _TITLE_H, _PAUSE_X, _PAUSE_Y, _PAUSE_W, _PAUSE_H,
                    _AUTH_W, _AUTH_H, _AUTH_Y, _SHOW_X, _CHG_X)
from renderer import draw_hud
from toast import draw_toast
from anim import HoverAnim

# Experimental split-screen layout (issue #21), opt-in only — the shipping
# default stays the classic centred renderer. See docs/SPLIT_LAYOUT.md.
# Imported only when selected, so a bug in the experimental path can't affect
# anyone who hasn't opted in.
_LAYOUT_MODE = os.environ.get("DECKERY_HUD_LAYOUT", "classic")
if _LAYOUT_MODE == "split":
    from renderer_split import (draw_hud_split, get_dpad_geometry, draw_dpad_live, _SCALE_ANIM_PARTS,
                                split_layers, draw_split_live, _side_slide_offset,
                                draw_gesture_connector_live)
    from layout_split import compute_layout, center_badge_rect, center_close_rect
    from viewmodel import classify_all
    from callouts import _BTNS


class _HudArea(Gtk.Widget):
    """Gtk.DrawingArea replacement — same role (the one widget everything
    draws into), but a plain Gtk.Widget so do_snapshot() is overridable
    directly. Needed for the split renderer's d-pad tilt: a real 3D/
    perspective transform only exists on Gtk.Snapshot itself
    (perspective()/rotate_3d()) — DrawingArea's set_draw_func() callback
    never gets access to the snapshot, only a flat cairo.Context already
    wrapped around one non-3D append_cairo() call GTK makes internally, so
    there's no way to reach those methods through it. Classic mode draws
    through this exactly the same way DrawingArea's draw_func did (one
    append_cairo() call, nothing 3D) — only split mode's extra d-pad block
    needs the widget-level access this provides.
    """

    def __init__(self, snapshot_fn):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._snapshot_fn = snapshot_fn   # (widget, snapshot, width, height) -> None

    def do_snapshot(self, snapshot):
        self._snapshot_fn(self, snapshot, self.get_width(), self.get_height())

    def do_measure(self, orientation, for_size):
        return (0, 0, -1, -1)

_TOAST_TTL_MS   = 1500   # toast display duration in milliseconds
_TOAST_FRAME_MS = 33     # ~30 fps during fade animation

# Buttons whose in-shape press feedback is animated (tilt, scale, ...) rather
# than the instant colour-swap every other button gets — the d-pad (see
# renderer_split.draw_dpad_live and this file's _draw_dpad_3d), every
# standalone-shape button (renderer_split._SCALE_ANIM_PARTS /
# _draw_scale_button_live — ABXY, the paddles, and the pill buttons), and
# L3/R3 (trackpads.py's _draw_stick — not in _SCALE_ANIM_PARTS, since their
# press feedback is the stick's own two *moving* rings shrinking, not a
# generic shape scale). Short duration on purpose: press feedback needs to
# feel immediate, not like the 260ms open/close slide — this is closer to
# "snappy" than "smooth".
_PRESS_ANIM_KEYS = (("BTN_DPAD_UP", "BTN_DPAD_DOWN", "BTN_DPAD_LEFT", "BTN_DPAD_RIGHT",
                      "BTN_THUMBL", "BTN_THUMBR")
                     + tuple(_SCALE_ANIM_PARTS.keys())) if _LAYOUT_MODE == "split" else ()
_PRESS_ANIM_MS = 90

# Real 3D perspective tilt for the d-pad (split mode only — see
# _draw_dpad_3d).
# - _DPAD_3D_MAX_ANGLE: rotation at full press, degrees.
# - _DPAD_3D_DEPTH: Gtk.Snapshot.perspective()'s depth in pixels — smaller
#   means a more dramatic/exaggerated foreshortening, larger is subtler.
# Direction confirmed correct live (vertical and horizontal signs each
# verified independently). 14°/500 (first guess) read as too subtle to
# judge; 40°/150 (cranked up purely to evaluate the concept) confirmed the
# direction/concept is right but was itself too extreme, and the lower
# depth read as more interesting than the original regardless of angle —
# this is the midpoint between the two, biased toward keeping that more
# dramatic perspective while pulling the angle back down.
_DPAD_3D_MAX_ANGLE = 24.0
_DPAD_3D_DEPTH = 260.0


class Win(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        self.set_title("Deckery HUD")
        self.set_decorated(False)

        # ── Layer shell — full-screen transparent overlay ─────────────────
        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_namespace(self, "deckery-hud")
        for edge in (LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT,
                     LayerShell.Edge.TOP,  LayerShell.Edge.BOTTOM):
            LayerShell.set_anchor(self, edge, True)

        # Transparent window background
        css = Gtk.CssProvider()
        css.load_from_string("window { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER)

        # ── SVGs ──────────────────────────────────────────────────────────
        self._front = Rsvg.Handle.new_from_file(_FRONT_SVG)
        self._back  = Rsvg.Handle.new_from_file(_BACK_SVG)

        # ── State ─────────────────────────────────────────────────────────
        self._state          = {}
        self._toast_source   = None
        self._last_action_ts = 0.0
        self._active_toasts  = []
        self._pause_anim     = HoverAnim(lambda: self._da.queue_draw())
        self._show_anim      = HoverAnim(lambda: self._da.queue_draw())
        self._change_anim    = HoverAnim(lambda: self._da.queue_draw())
        self._last_tick      = None   # see _on_open_tick's timing instrumentation
        self._tex_cache      = {}     # split mode: layer name -> (cairo surface, Gdk.Texture)
        self._on_closed      = None   # see set_open
        self._open_ticks     = None   # see set_open / _on_open_tick

        # ── Drawing area ──────────────────────────────────────────────────
        da = _HudArea(self._snapshot)
        self.set_child(da)
        self._da = da

        # Open/close transition — split mode only. Reuses HoverAnim exactly
        # as-is (same eased 0->1 tween already used for the hover badges)
        # instead of a new animation class; the only addition is that
        # closing has to finish the animation before the window actually
        # disappears, which the wrapped redraw callback below handles.
        # Driven by the drawing area's own frame clock (widget=da), not a
        # generic timer — see anim.py's note on why that matters here.
        self._open_anim = HoverAnim(self._on_open_tick, duration_ms=260, widget=da) if _LAYOUT_MODE == "split" else None

        # Per-button press animations (see _PRESS_ANIM_KEYS) — one HoverAnim
        # each, all ticking off the same drawing area's frame clock. Built
        # once up front rather than lazily per key: there are only a handful
        # of them and it keeps on_state()'s per-update loop simple (no
        # dict.setdefault dance on every state push).
        self._press_anims = ({k: HoverAnim(lambda: self._da.queue_draw(), duration_ms=_PRESS_ANIM_MS, widget=da)
                               for k in _PRESS_ANIM_KEYS} if _LAYOUT_MODE == "split" else {})

        # Click handler — fires only in the Wayland input region
        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_click)
        da.add_controller(click)

        # Hover detection for the pause/resume badge
        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        motion.connect("leave",  self._on_motion_leave)
        da.add_controller(motion)

        # Window starts hidden — App.show_hud() will present() and pause makima.

    # ── Hit-rect helpers ──────────────────────────────────────────────────

    def _badge_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        return hx + _PAUSE_X, hy + _PAUSE_Y, _PAUSE_W, _PAUSE_H

    # ── Input handlers ────────────────────────────────────────────────────

    def _osd_btn_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        bw, bh = 48, 20
        bx = hx + HUD_W - 28 - 16 - bw
        by = hy + (_TITLE_H - bh) / 2
        return bx, by, bw, bh

    def _remap_btn_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        bw, bh = 48, 20
        osd_bx = hx + HUD_W - 28 - 16 - bw
        bx = osd_bx - 8 - bw
        by = hy + (_TITLE_H - bh) / 2
        return bx, by, bw, bh

    def _auth_btn_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx, hy = (sw - HUD_W) / 2, (sh - HUD_H) / 2
        return hx + _SHOW_X, hy + _AUTH_Y, _AUTH_W, _AUTH_H

    def _change_btn_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx, hy = (sw - HUD_W) / 2, (sh - HUD_H) / 2
        return hx + _CHG_X, hy + _AUTH_Y, _AUTH_W, _AUTH_H

    def _close_btn_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx = (sw - HUD_W) / 2
        hy = (sh - HUD_H) / 2
        return hx + HUD_W - 44, hy, 44, _TITLE_H

    def _on_click(self, _gesture, _n, x, y):
        if _LAYOUT_MODE == "split":
            self._on_click_split(x, y)
            return
        bx, by, bw, bh = self._badge_screen_rect()
        mx, my, mw, mh = self._osd_btn_screen_rect()
        rx, ry, rw, rh = self._remap_btn_screen_rect()
        ax, ay, aw, ah = self._auth_btn_screen_rect()
        gx, gy, gw, gh = self._change_btn_screen_rect()
        cx, cy, cw, ch = self._close_btn_screen_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            paused = self._state.get("context", {}).get("paused", False)
            if paused:
                makima_resume()
                self._state.setdefault("context", {})["paused"] = False
            else:
                makima_pause()
                self._state.setdefault("context", {})["paused"] = True
            self._da.queue_draw()
        elif rx <= x <= rx + rw and ry <= y <= ry + rh:
            self.get_application().toggle_remapping()
        elif mx <= x <= mx + mw and my <= y <= my + mh:
            self.get_application().toggle_osd()
        elif (self.get_application()._auth_available
              and ax <= x <= ax + aw and ay <= y <= ay + ah):
            self.get_application().show_auth()
        elif (self.get_application()._auth_available
              and gx <= x <= gx + gw and gy <= y <= gy + gh):
            self.get_application().change_auth()
        elif cx <= x <= cx + cw and cy <= y <= cy + ch:
            self.get_application().hide_hud()
        # else: dead zone — ignore

    def _on_motion(self, _ctrl, x, y):
        if _LAYOUT_MODE == "split":
            return
        bx, by, bw, bh = self._badge_screen_rect()
        self._pause_anim.set(bx <= x <= bx + bw and by <= y <= by + bh)
        ax, ay, aw, ah = self._auth_btn_screen_rect()
        gx, gy, gw, gh = self._change_btn_screen_rect()
        self._show_anim.set(ax <= x <= ax + aw and ay <= y <= ay + ah)
        self._change_anim.set(gx <= x <= gx + gw and gy <= y <= gy + gh)

    # ── Split-layout hit testing ────────────────────────────────────────────
    # Minimal for now: close and pause/resume only. The split renderer doesn't
    # draw the OSD/remap/auth controls yet (centre column is legend-focused),
    # so there's nothing else to hit-test.

    def _split_rects(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        _clusters, _anchor_x, center = compute_layout(sw, sh)
        return center_badge_rect(center), center_close_rect(center)

    def _on_click_split(self, x, y):
        badge, close = self._split_rects()
        bx, by, bw, bh = badge
        cx, cy, cw, ch = close
        if bx <= x <= bx + bw and by <= y <= by + bh:
            paused = self._state.get("context", {}).get("paused", False)
            if paused:
                makima_resume()
                self._state.setdefault("context", {})["paused"] = False
            else:
                makima_pause()
                self._state.setdefault("context", {})["paused"] = True
            self._da.queue_draw()
        elif cx <= x <= cx + cw and cy <= y <= cy + ch:
            self.get_application().hide_hud()

    def _on_motion_leave(self, _ctrl):
        self._pause_anim.set(False)
        self._show_anim.set(False)
        self._change_anim.set(False)

    # ── Open/close transition (split mode) ──────────────────────────────────

    def set_open(self, opening: bool, on_closed=None):
        """Called by App.show_hud()/hide_hud() instead of present()/
        set_visible(False) directly. Outside split mode this *is*
        present()/set_visible(False) — classic keeps its original instant
        show/hide, nothing about it changes.

        on_closed: run once the window is actually gone — immediately in
        classic, after the close animation in split. Dropped if the HUD is
        reopened before that."""
        if self._open_anim is None:
            if opening:
                self.present()
            else:
                self.set_visible(False)
                if on_closed:
                    on_closed()
            return
        if opening:
            self._on_closed = None
            # Freshly mapping the window costs one long first frame (~165ms
            # measured: compositor map + GPU setup). The duration-based
            # animation would spend nearly its whole 260ms on that and show
            # two frames of slide; _on_open_tick restarts its clock once the
            # first frame is actually on screen instead.
            self._open_ticks = 0 if not self.get_visible() else None
            self.present()
            self._open_anim.set(True)
        else:
            self._on_closed = on_closed
            self._open_anim.set(False)

    def _on_open_tick(self):
        # Timing instrumentation for the "animation is laggy" reports —
        # printed (systemd/journald captures the service's stdout) only
        # during the brief open/close window itself, not continuously, so
        # it's a handful of lines per toggle, not log spam. Measures the
        # actual tick-to-tick interval (is GLib's timer firing on schedule?)
        # separately from draw cost (is drawing itself slow?), since those
        # point at different causes.
        now = time.monotonic()
        if self._last_tick is not None:
            print(f"[deckery-hud] open_anim tick +{(now - self._last_tick) * 1000:.1f}ms "
                  f"(target 33ms)", flush=True)
        self._last_tick = now

        # Second tick after mapping = the first frame has been presented
        # (the frame clock only ticks again once it has), so the stall is
        # behind us: restart the slide from where it began.
        if self._open_ticks is not None and self._open_anim._target > 0.5:
            self._open_ticks += 1
            if self._open_ticks == 2:
                self._open_anim.restart_clock()
                self._open_ticks = None

        self._da.queue_draw()
        # HoverAnim has no "finished closing" signal of its own — it just
        # eases toward whatever target was last set. Checking the eased
        # value here is enough: once it's back at ~0 *and* we're still
        # closing (not mid-open), the window can actually disappear.
        if self._open_anim.value <= 0.001 and self._open_anim._target < 0.5:
            self.set_visible(False)
            self._last_tick = None
            on_closed, self._on_closed = self._on_closed, None
            if on_closed:
                on_closed()

    # ── State update (called by App on file change) ───────────────────────

    def on_state(self, state):
        self._state = state
        if self._press_anims:
            active = set((state.get("context") or {}).get("active_buttons", []))
            for key, anim in self._press_anims.items():
                anim.set(key in active)
        self._da.queue_draw()
        self._schedule_toast_animation()

    def queue_draw_title(self):
        self._da.queue_draw()

    # ── Toast animation ───────────────────────────────────────────────────

    def _schedule_toast_animation(self):
        la = self._state.get("last_action") or {}
        ts = la.get("ts", 0.0)
        if ts <= self._last_action_ts:
            return
        self._last_action_ts = ts
        self._active_toasts.append(dict(la))
        if self._toast_source is None:
            self._toast_source = GLib.timeout_add(_TOAST_FRAME_MS, self._on_toast_frame)

    def _on_toast_frame(self):
        cutoff = time.time() - _TOAST_TTL_MS / 1000
        self._active_toasts = [t for t in self._active_toasts
                               if t.get("ts", 0) > cutoff]
        self._da.queue_draw()
        if not self._active_toasts:
            self._toast_source = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    # ── Drawing ───────────────────────────────────────────────────────────

    def _snapshot(self, _widget, snapshot, sw, sh):
        if _LAYOUT_MODE == "split" and not self._state.get("unreadable"):
            try:
                self._snapshot_split(snapshot, sw, sh)
            except Exception:
                import traceback
                traceback.print_exc()
            return
        bounds = Graphene.Rect().init(0, 0, sw, sh)
        cr = snapshot.append_cairo(bounds)
        try:
            self._draw_inner(cr, sw, sh)
        except Exception:
            import traceback
            traceback.print_exc()
            cr.set_operator(cairo.Operator.CLEAR)
            cr.paint()
            return
        if _LAYOUT_MODE == "split":
            try:
                self._draw_dpad_3d(snapshot, sw, sh)
            except Exception:
                import traceback
                traceback.print_exc()

    def _draw_inner(self, cr, sw, sh):
        if _LAYOUT_MODE == "split":
            self._draw_inner_split(cr, sw, sh)
            return

        # Set Wayland input region on every draw — recalculated so it stays
        # correct even if the surface is recreated by the layer shell after
        # present(), or if the first draw fires before the compositor has
        # sized the window to full screen.
        hx = (sw - HUD_W) // 2
        hy = (sh - HUD_H) // 2
        close_btn  = cairo.RectangleInt(hx + HUD_W - 44, hy, 44, _TITLE_H)
        badge      = cairo.RectangleInt(
            int(hx + _PAUSE_X), int(hy + _PAUSE_Y),
            int(_PAUSE_W), int(_PAUSE_H))
        mx, my, mw, mh = self._osd_btn_screen_rect()
        rx, ry, rw, rh = self._remap_btn_screen_rect()
        osd_btn   = cairo.RectangleInt(int(mx), int(my), int(mw), int(mh))
        remap_btn = cairo.RectangleInt(int(rx), int(ry), int(rw), int(rh))
        region = cairo.Region(close_btn)
        region.union(cairo.Region(badge))
        region.union(cairo.Region(osd_btn))
        region.union(cairo.Region(remap_btn))
        # Without these two the auth pills draw but cannot be clicked at all:
        # a Wayland surface receives no pointer events outside its input
        # region, so the handler is never even consulted.
        if self.get_application()._auth_available:
            ax, ay, aw, ah = self._auth_btn_screen_rect()
            gx, gy, gw, gh = self._change_btn_screen_rect()
            region.union(cairo.Region(
                cairo.RectangleInt(int(ax), int(ay), int(aw), int(ah))))
            region.union(cairo.Region(
                cairo.RectangleInt(int(gx), int(gy), int(gw), int(gh))))
        self.get_surface().set_input_region(region)

        cr.set_operator(cairo.Operator.CLEAR)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        cr.save()
        cr.translate((sw - HUD_W) / 2, (sh - HUD_H) / 2)
        app = self.get_application()
        draw_hud(cr, self._front, self._back, self._state,
                 hover_t=self._pause_anim.value,
                 osd_enabled=app._osd_enabled,
                 remapping_enabled=app._remapping_enabled,
                 auth_available=app._auth_available,
                 show_t=self._show_anim.value,
                 change_t=self._change_anim.value)
        cr.restore()

        # Toast origin: bottom edge of the HUD panel, shifted up by 40 px.
        # This keeps the toast in the same visual spot on every screen size.
        hud_bottom = (sh - HUD_H) / 2 + HUD_H - 40
        draw_toast(cr, sw, sh, self._active_toasts, start_y=hud_bottom)

    def _set_split_input_region(self):
        badge, close = self._split_rects()
        bx, by, bw, bh = badge
        cx, cy, cw, ch = close
        region = cairo.Region(cairo.RectangleInt(int(bx), int(by), int(bw), int(bh)))
        region.union(cairo.Region(cairo.RectangleInt(int(cx), int(cy), int(cw), int(ch))))
        self.get_surface().set_input_region(region)

    def _texture(self, name, surf):
        """The Gdk.Texture for a cached cairo layer, re-uploaded only when
        the renderer hands back a different surface object (its own caches
        only rebuild on a real content change) — not every frame."""
        cached = self._tex_cache.get(name)
        if cached is not None and cached[0] is surf:
            return cached[1]
        surf.flush()
        data = GLib.Bytes.new(bytes(surf.get_data()))
        # cairo's ARGB32 is native-endian premultiplied: B,G,R,A in memory here.
        tex = Gdk.MemoryTexture.new(surf.get_width(), surf.get_height(),
                                    Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, data, surf.get_stride())
        self._tex_cache[name] = (surf, tex)
        return tex

    def _snapshot_split(self, snapshot, sw, sh):
        """Split mode as GPU layers instead of one full-screen cairo node.

        Drawing everything through a single full-screen append_cairo() meant
        GTK re-rasterized the whole screen in software and uploaded it as a
        fresh texture on every frame open_t changed — measured at 22-33ms
        per frame during the slide on a 90Hz panel (~30-45fps). Here the
        cached layers (backdrop halves, both sides, centre column) are
        textures uploaded only when their content changes, and the slide
        and fade are snapshot translate/opacity — composited on the GPU.
        Only the genuinely live bits (trackpad dots, moving stick rings,
        mid-press buttons) stay cairo, in two narrow strips over the
        cluster columns rather than a full-screen node."""
        mid_anim = 0.0 < self._open_anim.value < 1.0
        t0 = time.perf_counter() if mid_anim else None
        self._set_split_input_region()

        open_t = self._open_anim.value
        press_t = {k: a.value for k, a in self._press_anims.items()}
        surface = self.get_surface()
        scale = surface.get_scale() if surface is not None else 1.0
        layers = split_layers(self._state, sw, sh, press_t, dev_scale=scale)
        dx = {side: _side_slide_offset(side, sw, open_t) for side in ("left", "right")}

        def rect(x, y, w, h):
            return Graphene.Rect().init(x, y, w, h)

        def full(surf):
            # Exactly the texture's own device size in logical px, so it maps
            # 1:1 onto the device pixel grid at rest — no resampling blur.
            return rect(0, 0, surf.get_width() / scale, surf.get_height() / scale)

        for (bx, bw, half), side in zip(layers["backdrop"], ("left", "right")):
            snapshot.save()
            snapshot.translate(Graphene.Point().init(dx[side], 0))
            snapshot.push_opacity(open_t)
            snapshot.append_scaled_texture(self._texture("backdrop_" + side, half),
                                           Gsk.ScalingFilter.LINEAR, rect(bx, 0, bw, sh))
            snapshot.pop()
            snapshot.restore()

        for side in ("left", "right"):
            surf = layers["sides"][side]
            snapshot.save()
            snapshot.translate(Graphene.Point().init(dx[side], 0))
            snapshot.push_opacity(open_t)
            snapshot.append_texture(self._texture(side, surf), full(surf))
            snapshot.pop()
            snapshot.restore()

        # Live overlays: each strip covers its side's cluster column, plus
        # room for a pressed button's adjacent action text while one is down.
        col_left, _y0, col_right, _y1 = layers["center"]
        for side in ("left", "right"):
            prefix = "l_" if side == "left" else "r_"
            pressed = any(_SCALE_ANIM_PARTS[k][1].startswith(prefix) for k in layers["active_press"])
            extra = sw * 0.3 if pressed else 16
            if side == "left":
                x0, w = dx[side], col_left + extra
            else:
                x0, w = col_right - extra + dx[side], sw - col_right + extra
            snapshot.push_opacity(open_t)
            cr = snapshot.append_cairo(rect(x0, 0, w, sh))
            draw_split_live(cr, self._state, layers, sw, sh, open_t, press_t, draw_dpad=False)
            snapshot.pop()

        # Two pads touching at once connects across screen centre — needs
        # its own full-width, unclipped pass; the two strips just above
        # each stop well short of centre (see draw_gesture_connector_live's
        # own docstring for what went wrong trying to fold this into them).
        pv = layers.get("pv")
        if pv is not None and pv.gesture:
            snapshot.push_opacity(open_t)
            cr = snapshot.append_cairo(rect(0, 0, sw, sh))
            draw_gesture_connector_live(cr, layers, sw, open_t)
            snapshot.pop()

        center_surf = layers["center_surf"]
        snapshot.push_opacity(open_t)
        snapshot.append_texture(self._texture("center", center_surf), full(center_surf))
        snapshot.pop()

        self._draw_dpad_3d(snapshot, sw, sh)

        if self._active_toasts:
            cr = snapshot.append_cairo(rect(0, 0, sw, sh))
            draw_toast(cr, sw, sh, self._active_toasts, start_y=sh - 40)

        if t0 is not None:
            print(f"[deckery-hud] snapshot_split: {(time.perf_counter() - t0) * 1000:.1f}ms "
                  f"(open_t={open_t:.2f}, screen={sw}x{sh}@{scale:.3g})", flush=True)

    def _draw_inner_split(self, cr, sw, sh):
        self._set_split_input_region()

        cr.set_operator(cairo.Operator.CLEAR)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        mid_anim = 0.0 < self._open_anim.value < 1.0
        t0 = time.perf_counter() if mid_anim else None
        press_t = {k: a.value for k, a in self._press_anims.items()}
        draw_hud_split(cr, self._front, self._back, self._state, sw, sh,
                       open_t=self._open_anim.value, press_t=press_t, draw_dpad=False)
        if t0 is not None:
            print(f"[deckery-hud] draw_hud_split: {(time.perf_counter() - t0) * 1000:.1f}ms "
                  f"(open_t={self._open_anim.value:.2f}, screen={sw}x{sh})", flush=True)

        draw_toast(cr, sw, sh, self._active_toasts, start_y=sh - 40)

    def _draw_dpad_3d(self, snapshot, sw, sh):
        """The d-pad's real 3D tilt — a genuine Gtk.Snapshot perspective/
        rotate_3d transform, not a 2D stand-in (see draw_dpad_live's own
        non-3D hinge-scale fallback, used when draw_dpad=True instead — not
        the case here, _draw_inner_split always passes draw_dpad=False).
        Drawn as its own append_cairo() block, separate from the one
        _snapshot() already made for everything else, since the perspective
        transform must be active on the snapshot stack *before* this block's
        cairo content is appended — it can't be retrofitted onto content
        that's already been appended through a different (non-transformed)
        block."""
        ox, oy, scale, cx, cy = get_dpad_geometry(sw, sh, self._open_anim.value)
        vms = classify_all(self._state, _BTNS.keys())
        press_t = {k: a.value for k, a in self._press_anims.items()}

        up    = press_t.get("BTN_DPAD_UP", 0.0)
        down  = press_t.get("BTN_DPAD_DOWN", 0.0)
        left  = press_t.get("BTN_DPAD_LEFT", 0.0)
        right = press_t.get("BTN_DPAD_RIGHT", 0.0)
        # Net signed amount per axis, not four independent rotations — if
        # both directions on one axis are briefly nonzero (noisy analog
        # input can do that), the dominant one simply wins rather than the
        # two fighting over the same axis.
        vert  = up - down      # positive -> UP is winning
        horiz = right - left   # positive -> RIGHT is winning

        # Signs confirmed live, each independently (X and Y aren't
        # necessarily mirrored the same way under GSK's rotate_3d, and
        # indeed weren't: X needed flipping from the first guess, Y needed
        # flipping back to it).
        angle_x = _DPAD_3D_MAX_ANGLE * vert     # UP press -> top tilts away
        angle_y = _DPAD_3D_MAX_ANGLE * horiz    # RIGHT press -> right tilts away

        size = 90.0
        bounds = Graphene.Rect().init(cx - size, cy - size, size * 2, size * 2)
        snapshot.save()
        snapshot.translate(Graphene.Point().init(cx, cy))
        if abs(angle_x) > 0.01 or abs(angle_y) > 0.01:
            snapshot.perspective(_DPAD_3D_DEPTH)
            if abs(angle_x) > 0.01:
                snapshot.rotate_3d(angle_x, Graphene.Vec3().init(1, 0, 0))
            if abs(angle_y) > 0.01:
                snapshot.rotate_3d(angle_y, Graphene.Vec3().init(0, 1, 0))
        snapshot.translate(Graphene.Point().init(-cx, -cy))
        cr2 = snapshot.append_cairo(bounds)
        # press_t={} deliberately: the 2D hinge-scale fallback inside
        # draw_dpad_live must not also apply on top of this real rotation.
        draw_dpad_live(cr2, ox, oy, scale, vms, {})
        snapshot.restore()
