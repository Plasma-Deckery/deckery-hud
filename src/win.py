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
import time

from ipc import makima_pause, makima_resume, _FRONT_SVG, _BACK_SVG
from layout import (HUD_W, HUD_H, _TITLE_H, _PAUSE_X, _PAUSE_Y, _PAUSE_W, _PAUSE_H,
                    _AUTH_W, _AUTH_H, _AUTH_Y, _SHOW_X, _CHG_X,
                    _SPLIT_BTN_X, _OSD_BTN_W)
from renderer import draw_hud
from toast import draw_toast
from anim import HoverAnim
from reveal import GROUPS, GroupAnim, RevealSettings
import layout_choice

# Experimental split-screen layout (issue #21), opt-in only — the shipping
# default stays the classic centred renderer. See docs/SPLIT_LAYOUT.md.
# Imported only when selected, so a bug in the experimental path can't affect
# anyone who hasn't opted in. Read once per import: switching designs from
# the HUD (App.switch_layout) reloads this module and builds a fresh Win.
_LAYOUT_MODE = layout_choice.current()
if _LAYOUT_MODE == "split":
    from renderer_split import (draw_hud_split, get_dpad_geometry, draw_dpad_live, _SCALE_ANIM_PARTS,
                                group_layers, live_rect, draw_group_live, _side_slide_offset,
                                draw_gesture_connector_live, SHADOW_STYLE, warm_all)
    from shadow import bleed_transfer
    from layout_split import compute_layout, center_badge_rect, center_close_rect, center_classic_rect


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

# Group animations: a tick gap longer than _STALL_S counts as a stall and
# is taken out of the running transitions, minus one ordinary frame.
_STALL_S = 0.05
_FRAME_S = 1 / 90
_DPAD_3D_DEPTH = 260.0


class Win(Gtk.ApplicationWindow):
    def __init__(self, application, settings=None):
        super().__init__(application=application)
        self.set_title("Deckery HUD")
        self.set_decorated(False)

        # ── Layer shell — full-screen transparent overlay ─────────────────
        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(self, -1)
        # KWin turns the namespace into a window type, and any name it doesn't
        # know ("deckery-hud") makes a normal window — which its Scale effect
        # zooms and fades on every map and unmap, on top of our own slide
        # (B-03). "dock" is one it knows that neither Scale nor Fading Popups
        # animates; the layer stays OVERLAY, KWin takes that from the layer
        # shell, not the type. Split only: classic keeps the KWin zoom as its
        # one transition.
        LayerShell.set_namespace(self, "dock" if _LAYOUT_MODE == "split" else "deckery-hud")
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
        self._last_tick      = None   # see _on_group_tick's timing instrumentation
        self._tex_cache      = {}     # split mode: layer name -> (cairo surface, Gdk.Texture)
        self._map_ticks      = None   # see _need_surface / _on_group_tick
        self._warm_state     = None   # see prewarm: set while its frame is pending
        self._warm_ticks     = 0

        # ── Drawing area ──────────────────────────────────────────────────
        da = _HudArea(self._snapshot)
        self.set_child(da)
        self._da = da

        # Split mode: every element (one button with its shape, legend and
        # shadow — see elements.py — plus the centre column) has its own
        # visibility (reveal.GroupAnim), so single elements can show on
        # their own while the full HUD is closed (B-12). All of them tick
        # off one callback on the drawing area's own frame clock, not a
        # generic timer — see anim.py's note on why that matters here.
        self._settings  = settings or RevealSettings()
        self._anims     = {g: GroupAnim(self._settings) for g in GROUPS} if _LAYOUT_MODE == "split" else {}
        self._contents  = {}      # group -> reveal.Content it shows (kept while fading out)
        self._causes    = {}      # group -> cause of its last Want, decides slide vs fade out
        self._full      = False   # the full HUD is open (input, centre, toasts)
        self._drawn     = {}      # group -> (Gdk.Texture, rect) last drawn, for a crossfade
        self._xfade     = {}      # group -> (texture, rect, start) fading out under new content
        self._tick_id   = None
        self._visible   = frozenset()
        self._gesture   = False   # last seen two-pad gesture, see on_state

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


    def set_settings(self, settings):
        """New reveal durations from the settings file. Running animations
        read them on their next tick; nothing restarts."""
        self._settings = settings
        for a in self._anims.values():
            a.settings = settings

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

    def _split_btn_screen_rect(self):
        sw, sh = self._da.get_width(), self._da.get_height()
        hx, hy = (sw - HUD_W) / 2, (sh - HUD_H) / 2
        bh = 20
        return hx + _SPLIT_BTN_X, hy + (_TITLE_H - bh) / 2, _OSD_BTN_W, bh

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
        sx, sy, sw_, sh_ = self._split_btn_screen_rect()
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
        elif sx <= x <= sx + sw_ and sy <= y <= sy + sh_:
            self.get_application().switch_layout("split")
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
        return center_badge_rect(center), center_close_rect(center), center_classic_rect(center)

    def _on_click_split(self, x, y):
        badge, close, classic = self._split_rects()
        bx, by, bw, bh = badge
        cx, cy, cw, ch = close
        kx, ky, kw, kh = classic
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
        elif kx <= x <= kx + kw and ky <= y <= ky + kh:
            self.get_application().switch_layout("classic")

    def _on_motion_leave(self, _ctrl):
        self._pause_anim.set(False)
        self._show_anim.set(False)
        self._change_anim.set(False)

    # ── Open/close transition (split mode) ──────────────────────────────────

    def set_open(self, opening: bool, on_closed=None):
        """Classic only: the original instant present()/set_visible(False).
        Split mode goes through set_wants instead.

        on_closed: run once the window is gone."""
        if opening:
            self.present()
        else:
            self.set_visible(False)
            if on_closed:
                on_closed()

    def retire(self):
        """Destroy this window for good — App.switch_layout replaces it with
        a Win of the other design. Instant, no close animation: the new
        window takes over the screen at once. Timer-driven redraws are
        stopped first so nothing keeps drawing into the dead widget."""
        if self._toast_source is not None:
            GLib.source_remove(self._toast_source)
            self._toast_source = None
        self.destroy()

    # ── Group visibility (split mode) ────────────────────────────────────────

    def set_wants(self, wants):
        """wants: {group: reveal.Want} — every group not in it goes away.
        A group keeps the content it had while it fades or slides out, and
        a group that stays visible but changes content crossfades."""
        now = time.monotonic()
        self._full = any(w.cause == "full" for w in wants.values())
        for g, anim in self._anims.items():
            w = wants.get(g)
            if w is None:
                anim.set_target(False, self._causes.get(g, "detector"), now)
                continue
            old = self._contents.get(g)
            if old is not None and old != w.content and anim.value > 0 and g in self._drawn:
                tex, rect = self._drawn[g]
                self._xfade[g] = (tex, rect, now)
            self._contents[g] = w.content
            self._causes[g] = w.cause
            anim.set_target(True, w.cause, now)
        if any(a.target for a in self._anims.values()):
            self._need_surface(True)
        self._start_ticking()
        self._da.queue_draw()
        self._check_visible()

    def visible_groups(self):
        """Groups on screen or on their way there."""
        return frozenset(g for g, a in self._anims.items() if a.target or a.value > 0)

    def is_full(self):
        return self._full

    def _check_visible(self):
        vis = self.visible_groups()
        if vis != self._visible:
            self._visible = vis
            self.get_application()._on_groups_changed()

    def _need_surface(self, needed):
        """The one place the split HUD's surface is mapped or unmapped
        (B-01/B-03 hook in here)."""
        if needed and not self.get_visible():
            # Freshly mapping the window costs one long first frame (~165ms
            # measured: compositor map + GPU setup). The duration-based
            # animations would spend nearly all of a fade on that and show
            # two frames of it; _on_group_tick restarts their clocks once the
            # first frame is actually on screen instead.
            self._map_ticks = 0
            self.present()
        elif needed and self._warm_state is not None and self._map_ticks is None:
            # Opened while prewarm still holds the window for its first
            # frame: the same stall, so the same restart.
            self._map_ticks = 0
        elif not needed and self.get_visible():
            self.set_visible(False)
            self._map_ticks = None

    def prewarm(self, state):
        """Build every cached layer once at startup, before anything
        is shown. The first open after a start otherwise does it inside its
        first frame — measured 234-275ms, long enough that the HUD popped
        open with no visible slide (B-02).

        Done mapped, for one empty frame: only the surface knows the size
        and fractional scale the layers are cached under (Gdk.Monitor's
        scale is wrong on the Deck's rotated panel — 1.76 for a real 1.1),
        and the first map's own setup cost is paid here too. Nothing shows:
        no group is visible, the input region is empty, and the "dock"
        namespace keeps KWin from animating it."""
        if self.get_visible():
            return False
        self._warm_state = state
        self._warm_ticks = 0
        self.present()
        self._da.add_tick_callback(self._on_prewarm_tick)
        return False   # one shot when run from GLib.idle_add

    def _on_prewarm_tick(self, _widget, _clock):
        # Second tick = the empty first frame is on screen (see _on_group_tick).
        self._warm_ticks += 1
        if self._warm_ticks < 2:
            return GLib.SOURCE_CONTINUE
        sw, sh = self._da.get_width(), self._da.get_height()
        scale = self.get_surface().get_scale()
        t0 = time.perf_counter()
        for name, surf in warm_all(self._warm_state, sw, sh, dev_scale=scale).items():
            self._texture(name, surf)
        print(f"[deckery-hud] prewarm: {(time.perf_counter() - t0) * 1000:.1f}ms "
              f"({sw}x{sh}@{scale:.3g})", flush=True)
        self._warm_state = None
        if not self.visible_groups():
            self._need_surface(False)
        return GLib.SOURCE_REMOVE

    def _start_ticking(self):
        if self._tick_id is None and (any(a.running for a in self._anims.values()) or self._xfade):
            self._tick_id = self._da.add_tick_callback(self._on_group_tick)

    def _on_group_tick(self, _widget, _clock):
        now = time.monotonic()
        # Timing instrumentation for the "animation is laggy" reports —
        # only while something animates, a handful of lines per transition.
        # Measures the tick-to-tick interval (is the frame clock on
        # schedule?) separately from draw cost (snapshot_split's own print).
        if self._last_tick is not None:
            gap = now - self._last_tick
            print(f"[deckery-hud] group_anim tick +{gap * 1000:.1f}ms", flush=True)
            # A frame that took far longer than a frame (a cold layer build
            # when the full HUD opens over an already visible group, measured
            # ~390ms) would otherwise eat the whole slide. Count it as one
            # ordinary frame instead.
            if gap > _STALL_S:
                for a in self._anims.values():
                    a.delay(gap - _FRAME_S)
        self._last_tick = now

        # Until the second tick after mapping — the first frame has been
        # presented then (the frame clock only ticks again once it has) —
        # hold every transition at its start. Merely restarting the clock at
        # that tick isn't enough: a first frame longer than a fade (cold or
        # after idle, measured up to ~275ms) would have finished it already.
        if self._map_ticks is not None:
            self._map_ticks += 1
            for a in self._anims.values():
                a.restart_clock(now)
            if self._map_ticks >= 2:
                self._map_ticks = None
            self._da.queue_draw()
            return GLib.SOURCE_CONTINUE

        running = False
        for a in self._anims.values():
            running = a.tick(now) or running
        xf = self._settings.crossfade_ms / 1000
        self._xfade = {g: x for g, x in self._xfade.items() if now - x[2] < xf}
        self._da.queue_draw()
        self._check_visible()
        if running or self._xfade:
            return GLib.SOURCE_CONTINUE
        self._tick_id = None
        self._last_tick = None
        if not self.visible_groups():
            self._need_surface(False)
        return GLib.SOURCE_REMOVE

    # ── State update (called by App on file change) ───────────────────────

    def on_state(self, state):
        self._state = state
        # A gesture swaps each visible pad's own mode label for the shared
        # connector (which fades with the pads) and back; crossfade that
        # swap instead of letting the label pop.
        gesture = bool(((state.get("trackpads") or {}).get("gesture") or {}).get("touching"))
        if gesture != self._gesture and self._anims:
            now = time.monotonic()
            for g in ("LPad", "RPad"):
                if self._anims[g].value > 0 and g in self._drawn:
                    tex, rect = self._drawn[g]
                    self._xfade[g] = (tex, rect, now)
            self._start_ticking()
        self._gesture = gesture
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
        sx, sy, sw_, sh_ = self._split_btn_screen_rect()
        region.union(cairo.Region(
            cairo.RectangleInt(int(sx), int(sy), int(sw_), int(sh_))))
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
        if not self._full:
            # Single groups never take input: clicks go to whatever is
            # underneath, and makima keeps running.
            self.get_surface().set_input_region(cairo.Region())
            return
        badge, close, classic = self._split_rects()
        bx, by, bw, bh = badge
        cx, cy, cw, ch = close
        kx, ky, kw, kh = classic
        region = cairo.Region(cairo.RectangleInt(int(bx), int(by), int(bw), int(bh)))
        region.union(cairo.Region(cairo.RectangleInt(int(cx), int(cy), int(cw), int(ch))))
        region.union(cairo.Region(cairo.RectangleInt(int(kx), int(ky), int(kw), int(kh))))
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

    def _bleed_transfer(self):
        """(ramp, curve) — see shadow.bleed_transfer; the ramp applies first."""
        if getattr(self, "_bleed_ct", None) is None:
            m, b, table = bleed_transfer(SHADOW_STYLE)
            self._bleed_ct = (Gsk.ComponentTransfer.new_linear(m, b),
                              Gsk.ComponentTransfer.new_table(table))
        return self._bleed_ct

    def _snapshot_split(self, snapshot, sw, sh):
        """Split mode as GPU layers instead of one full-screen cairo node.

        Drawing everything through a single full-screen append_cairo() meant
        GTK re-rasterized the whole screen in software and uploaded it as a
        fresh texture on every animation frame — measured at 22-33ms per
        frame during the slide on a 90Hz panel (~30-45fps). Here every group
        (the eight clusters and the centre column) is a cached texture
        uploaded only when its content changes, with its own shadow under
        it, and each group's slide and fade are snapshot translate/opacity
        from its own GroupAnim — composited on the GPU. Only the genuinely
        live bits (trackpad dots, moving stick rings, mid-press buttons)
        stay cairo, in one narrow strip per group."""
        now = time.monotonic()
        mid_anim = any(a.running for a in self._anims.values())
        t0 = time.perf_counter() if mid_anim else None
        self._set_split_input_region()

        shown = [g for g in GROUPS if g in self._contents
                 and (self._anims[g].value > 0 or self._anims[g].target)]
        if not shown:
            return
        press_t = {k: a.value for k, a in self._press_anims.items()}
        surface = self.get_surface()
        scale = surface.get_scale() if surface is not None else 1.0
        layers = group_layers(self._state, sw, sh, {g: self._contents[g] for g in shown},
                              press_t, dev_scale=scale)
        groups = layers["groups"]
        opacity = {g: self._anims[g].value for g in shown}
        # Only a sliding group moves, and only the clusters: the centre
        # column fades in place, and so does any group a detector shows.
        dx = {g: _side_slide_offset(groups[g].side, sw, opacity[g])
              if groups[g].side and self._anims[g].style == "slide" else 0.0
              for g in shown}

        def rect(x, y, w, h):
            return Graphene.Rect().init(x, y, w, h)

        def placed(g, append):
            snapshot.save()
            snapshot.translate(Graphene.Point().init(dx[g], 0))
            snapshot.push_opacity(opacity[g])
            append()
            snapshot.pop()
            snapshot.restore()

        # Every shadow before any content, so no element's shadow darkens a
        # neighbour's text. First the bleed: each element's soft field with
        # its own slide/fade, all in one pass that is only then mapped to
        # alpha — so neighbouring clouds fuse into one shape instead of
        # stacking (see shadow.py). Then each element's own core/edge shadow.
        bleeds = [g for g in shown if groups[g].bleed is not None]
        if bleeds:
            ident = Gsk.ComponentTransfer.new_identity()
            ramp, curve = self._bleed_transfer()
            snapshot.push_component_transfer(ident, ident, ident, curve)
            snapshot.push_component_transfer(ident, ident, ident, ramp)
            for g in bleeds:
                surf, x, y, w, h = groups[g].bleed
                placed(g, lambda: snapshot.append_scaled_texture(
                    self._texture("bleed_" + g, surf), Gsk.ScalingFilter.LINEAR, rect(x, y, w, h)))
            snapshot.pop()
            snapshot.pop()
        for g in shown:
            if groups[g].shadow is None:
                continue
            surf, x, y, w, h = groups[g].shadow
            placed(g, lambda: snapshot.append_scaled_texture(
                self._texture("shadow_" + g, surf), Gsk.ScalingFilter.LINEAR, rect(x, y, w, h)))
        xf = self._settings.crossfade_ms / 1000
        for g in shown:
            layer = groups[g]
            tex = self._texture(g, layer.surface)
            if g in self._xfade:
                # A real dissolve, not new-over-old: two plain alphas would
                # dim whatever both textures share (the art) mid-way.
                old_tex, old_rect, start = self._xfade[g]
                k = min(1.0, (now - start) / xf) if xf > 0 else 1.0
                def both():
                    snapshot.push_cross_fade(k)
                    snapshot.append_texture(old_tex, rect(*old_rect))
                    snapshot.pop()
                    snapshot.append_texture(tex, rect(*layer.rect))
                    snapshot.pop()
                placed(g, both)
            else:
                placed(g, lambda: snapshot.append_texture(tex, rect(*layer.rect)))
            self._drawn[g] = (tex, layer.rect)
        for g in shown:
            if groups[g].tx is None:
                continue
            def live():
                cr = snapshot.append_cairo(rect(*live_rect(g, layers, sw, sh)))
                draw_group_live(cr, g, self._state, layers, 0.0, press_t, draw_dpad=False)
            placed(g, live)

        # Two pads touching at once connects across screen centre — needs
        # its own full-width, unclipped pass; the per-group strips each stop
        # well short of centre (see draw_gesture_connector_live). It is as
        # visible as the fainter of the two pads.
        pv = layers.get("pv")
        if pv is not None and pv.gesture and "LPad" in groups and "RPad" in groups:
            snapshot.push_opacity(min(opacity["LPad"], opacity["RPad"]))
            cr = snapshot.append_cairo(rect(0, 0, sw, sh))
            draw_gesture_connector_live(cr, layers, sw, dx["LPad"], dx["RPad"])
            snapshot.pop()

        if "DPad" in groups:
            snapshot.push_opacity(opacity["DPad"])
            self._draw_dpad_3d(snapshot, sw, sh, dx["DPad"], groups["DPad"].vms)
            snapshot.pop()

        if self._full and self._active_toasts:
            cr = snapshot.append_cairo(rect(0, 0, sw, sh))
            draw_toast(cr, sw, sh, self._active_toasts, start_y=sh - 40)

        if t0 is not None:
            vals = " ".join(f"{g}={opacity[g]:.2f}" for g in shown)
            print(f"[deckery-hud] snapshot_split: {(time.perf_counter() - t0) * 1000:.1f}ms "
                  f"({vals}, screen={sw}x{sh}@{scale:.3g})", flush=True)

    def _draw_inner_split(self, cr, sw, sh):
        self._set_split_input_region()

        cr.set_operator(cairo.Operator.CLEAR)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        # Only reached for an unreadable state, which draw_hud_split turns
        # into a message; it fades with the centre column.
        press_t = {k: a.value for k, a in self._press_anims.items()}
        draw_hud_split(cr, self._front, self._back, self._state, sw, sh,
                       open_t=self._anims["center"].value, press_t=press_t, draw_dpad=False)

        draw_toast(cr, sw, sh, self._active_toasts, start_y=sh - 40)

    def _draw_dpad_3d(self, snapshot, sw, sh, dx, vms):
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
        ox, oy, scale, cx, cy = get_dpad_geometry(sw, sh, 1.0)
        ox, cx = ox + dx, cx + dx
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
