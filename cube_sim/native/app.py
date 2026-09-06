"""
Cube FX Simulator - native front end.

    python -m native.app

Phase 2. Same engine and the same numbers as the headless tool; this adds the
window, the controls and live audio driving the effects in real time.

Two things here are deliberate and easy to undo by accident:

  * The clock advances in a FIXED 23 ms step, paced against the wall clock. It
    does not take the real frame interval. The browser build tied the step to
    the frame and so ran 1.38x fast on a 60 Hz monitor and 3.3x on a 144 Hz one,
    which made every timing judgement wrong by a factor that depended on the
    machine. Fixed steps also keep runs reproducible, which is what lets the
    measurement numbers mean anything.

  * The palette comes from the selector, never from an effect's metadata
    default. The simulator carries six palettes where WLED has seventy-odd, so
    a default like pal=11 lands on something unrelated.
"""
import os
import tempfile
import time

import numpy as np
import dearpygui.dearpygui as dpg

from native.engine import Engine, stats
from native.synth import Synth
from native import render

STEP = 23
CUBE_MAX = 620          # cube render cost is quadratic in this, so it is capped
                        # and the image is scaled up if the pane is larger
VIEW_MIN = 180
SIDE_W = 340            # control column


def apply_theme():
    """A dark theme close to the browser build's, so switching between the two
    is not jarring. Default Dear PyGui is grey-blue and tightly packed; the
    views want to sit on near-black or the LED colours read wrong against it."""
    bg      = (17, 19, 24)
    panel   = (24, 27, 34)
    line    = (42, 47, 58)
    text    = (215, 219, 227)
    dim     = (139, 147, 163)
    accent  = (90, 169, 230)
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvAll):
            for t, c in ((dpg.mvThemeCol_WindowBg, bg),
                         (dpg.mvThemeCol_ChildBg, panel),
                         (dpg.mvThemeCol_PopupBg, panel),
                         (dpg.mvThemeCol_Border, line),
                         (dpg.mvThemeCol_Text, text),
                         (dpg.mvThemeCol_TextDisabled, dim),
                         (dpg.mvThemeCol_FrameBg, (32, 36, 45)),
                         (dpg.mvThemeCol_FrameBgHovered, (44, 50, 62)),
                         (dpg.mvThemeCol_FrameBgActive, (52, 60, 74)),
                         (dpg.mvThemeCol_Button, (38, 43, 54)),
                         (dpg.mvThemeCol_ButtonHovered, (52, 62, 78)),
                         (dpg.mvThemeCol_ButtonActive, accent),
                         (dpg.mvThemeCol_SliderGrab, accent),
                         (dpg.mvThemeCol_SliderGrabActive, (130, 195, 245)),
                         (dpg.mvThemeCol_CheckMark, accent),
                         (dpg.mvThemeCol_Header, (40, 48, 60)),
                         (dpg.mvThemeCol_HeaderHovered, (52, 62, 78)),
                         (dpg.mvThemeCol_TitleBg, panel),
                         (dpg.mvThemeCol_TitleBgActive, panel),
                         (dpg.mvThemeCol_ScrollbarBg, panel),
                         (dpg.mvThemeCol_ScrollbarGrab, line),
                         (dpg.mvThemeCol_Separator, line),
                         (dpg.mvThemeCol_PlotHistogram, accent)):
                dpg.add_theme_color(t, c, category=dpg.mvThemeCat_Core)
            for t, v in ((dpg.mvStyleVar_FrameRounding, 4),
                         (dpg.mvStyleVar_ChildRounding, 6),
                         (dpg.mvStyleVar_GrabRounding, 4),
                         (dpg.mvStyleVar_WindowRounding, 6),
                         (dpg.mvStyleVar_ScrollbarRounding, 6)):
                dpg.add_theme_style(t, v, category=dpg.mvThemeCat_Core)
            for t, a, b in ((dpg.mvStyleVar_WindowPadding, 10, 10),
                            (dpg.mvStyleVar_FramePadding, 7, 4),
                            (dpg.mvStyleVar_ItemSpacing, 8, 6),
                            (dpg.mvStyleVar_CellPadding, 6, 3)):
                dpg.add_theme_style(t, a, b, category=dpg.mvThemeCat_Core)
    dpg.bind_theme(th)
    return th


def present_theme():
    """Everything black, nothing framed.

    Presentation mode is not the normal layout with the controls hidden - it is
    a different thing entirely. The panel backgrounds, the rounded corners, the
    borders and the padding all exist to separate a view from the controls
    beside it, and with the controls gone they are just furniture around a
    picture. A visualiser has no furniture.

    Bound globally while presenting and unbound after, so the working layout
    keeps its own look.
    """
    black = (0, 0, 0)
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvAll):
            for t in (dpg.mvThemeCol_WindowBg, dpg.mvThemeCol_ChildBg,
                      dpg.mvThemeCol_Border, dpg.mvThemeCol_BorderShadow,
                      dpg.mvThemeCol_PopupBg):
                dpg.add_theme_color(t, black, category=dpg.mvThemeCat_Core)
            for t, v in ((dpg.mvStyleVar_WindowBorderSize, 0),
                         (dpg.mvStyleVar_ChildBorderSize, 0),
                         (dpg.mvStyleVar_ChildRounding, 0),
                         (dpg.mvStyleVar_WindowRounding, 0)):
                dpg.add_theme_style(t, v, category=dpg.mvThemeCat_Core)
            for t, a, b in ((dpg.mvStyleVar_WindowPadding, 0, 0),
                            (dpg.mvStyleVar_FramePadding, 0, 0),
                            (dpg.mvStyleVar_ItemSpacing, 0, 0),
                            (dpg.mvStyleVar_CellPadding, 0, 0)):
                dpg.add_theme_style(t, a, b, category=dpg.mvThemeCat_Core)
    return th


PALETTES = [("Rainbow", 1), ("Fire", 2), ("Ocean", 3), ("Party", 4),
            ("Mono", 5), ("Sunset", 6), ("Default (segment colour)", 0)]


class App:
    def __init__(self):
        self.eng = Engine()
        self.syn = Synth()
        self.live = None
        self.playing = True
        self.acc = 0.0
        self.last = time.perf_counter()
        self.yaw, self.pitch, self.dist = -0.6, 0.75, 4.6
        self.beat_flash = 0
        self.layout = "both"        # both | net | cube
        # Set by anything that needs the panes resized; acted on at the TOP of
        # the next loop pass, never inside a callback. See request_layout().
        self._need_layout = True
        self.ui = True              # control column and pane captions
        self._themes = {}           # normal / present, built once in build()
        self._bufs = {}
        self._inputs = set()
        self._dragging = False
        self._yaw0, self._pitch0 = self.yaw, self.pitch
        self.eng.select(0)

    # --- textures ------------------------------------------------------------
    def _rgba(self, key, img):
        """uint8 (h,w,3) -> flat float32 RGBA, which is what DPG wants.

        Into a buffer kept per view. Allocating a fresh (h,w,4) float32 array
        every frame for both views cost 6 ms between them - a fifth of the frame
        - and the alpha column never changes, so it is written once when the
        buffer is made and left alone thereafter.
        """
        h, w, _ = img.shape
        buf = self._bufs.get(key)
        if buf is None or buf.shape[:2] != (h, w):
            buf = np.ones((h, w, 4), np.float32)
            self._bufs[key] = buf
        np.multiply(img, np.float32(1.0 / 255.0), out=buf[..., :3], casting="unsafe")
        return buf.reshape(-1)

    def net_image(self):
        rgb = self.eng.rgb().copy()
        if not self.eng.fx.get("o3"):
            # Cube mode: the gap corners are not pixels and effects skip them,
            # so without this they keep whatever flat mode last left there.
            rgb[~self.eng.lit_mask()] = 0
        return rgb

    # --- audio ---------------------------------------------------------------
    def audio_push(self):
        src = self.live if self.live else self.syn
        try:
            hit = src.push(self.eng)
        except Exception as e:                     # a device can vanish mid-run
            dpg.set_value("live_msg", f"live audio stopped: {e}")
            self.stop_live()
            hit = 0
        if hit:
            self.beat_flash = 6
        return hit

    def start_live(self):
        try:
            from native.audio import LiveAudio
            # pair() names its widgets sld_/inp_, so read the box.
            self.live = LiveAudio(gain=float(dpg.get_value("inp_live_gain")))
            dpg.set_value("live_msg", f"capturing: {self.live.name}")
            dpg.configure_item("live_btn", label="stop live audio")
        except Exception as e:
            dpg.set_value("live_msg", f"could not start: {e}")

    def stop_live(self):
        if self.live:
            try:
                self.live.close()
            except Exception:
                pass
        self.live = None
        dpg.configure_item("live_btn", label="use live audio")

    def toggle_live(self):
        self.stop_live() if self.live else self.start_live()

    # --- callbacks -----------------------------------------------------------
    def on_effect(self, s, val):
        self.eng.select(self.eng.names.index(val))
        self.rebuild_params()

    def on_palette(self, s, val):
        self.eng.pal = dict(PALETTES)[val]
        self.eng.push()

    def on_faceB(self, s, val):
        self.eng.resize(int(val))
        # resize() re-selects the effect, which resets every parameter to the
        # metadata defaults - so the sliders have to be rebuilt or they show
        # values the engine no longer holds.
        self.rebuild_params()
        self.request_layout()

    def on_color(self, sender, val):
        r, g, b = (int(c * 255) if c <= 1.0 else int(c) for c in val[:3])
        self.eng.colors((r << 16) | (g << 8) | b)

    def _set_param(self, k, v):
        self.eng.fx[k] = int(v)
        self.eng.push()

    def on_check(self, sender, val):
        self.eng.fx[dpg.get_item_user_data(sender)] = 1 if val else 0
        self.eng.push()

    # --- the one slider shape used everywhere ---------------------------------
    def pair(self, parent, key, label, value, lo, hi, setter, is_float=False):
        """A slider carrying no number, and the typed box that shows it.

        The slider used to print its own value as well, so the same number
        appeared twice a few pixels apart and disagreed with itself for a frame
        whenever one was dragged. The box is the readout; the slider is the
        handle. format="" is what stops Dear PyGui drawing the value on the
        track.
        """
        st, it = f"sld_{key}", f"inp_{key}"
        self._inputs.add(it)

        def from_slider(s, v):
            dpg.set_value(it, v)
            setter(v)

        def from_box(s, v):
            v = max(lo, min(hi, v))
            dpg.set_value(st, v)
            setter(v)

        with dpg.group(horizontal=True, parent=parent):
            if is_float:
                dpg.add_slider_float(tag=st, width=142, min_value=lo, max_value=hi,
                                     default_value=value, format="", callback=from_slider)
                dpg.add_input_float(tag=it, width=68, step=0, format="%.1f",
                                    min_value=lo, max_value=hi, min_clamped=True,
                                    max_clamped=True, default_value=value,
                                    callback=from_box)
            else:
                dpg.add_slider_int(tag=st, width=142, min_value=lo, max_value=hi,
                                   default_value=value, format="", callback=from_slider)
                dpg.add_input_int(tag=it, width=68, step=0, min_value=lo, max_value=hi,
                                  min_clamped=True, max_clamped=True,
                                  default_value=value, callback=from_box)
            dpg.add_text(label, color=(139, 147, 163))

    def rebuild_params(self):
        """Sliders are labelled from the effect's own metadata, as the web UI is."""
        dpg.delete_item("params", children_only=True)
        m = self.eng.meta[self.eng.idx]
        generic = {"sx": "Speed", "ix": "Intensity", "c1": "Custom 1",
                   "c2": "Custom 2", "c3": "Custom 3"}
        for i, k in enumerate(("sx", "ix", "c1", "c2", "c3")):
            lab = (m["labels"][i] if i < len(m["labels"]) else "").strip()
            if not lab or lab == "!":
                lab = generic[k]
            # custom3 is a five-bit field in the firmware and the API clamps it
            # to 0..31, so the slider must stop there. Letting it run to 255
            # offers settings the cube cannot hold - which is exactly how
            # fourteen effects came to be tuned against values they never got.
            hi = 31 if k == "c3" else 255
            self.pair("params", k, lab, self.eng.fx[k], 0, hi,
                      lambda v, k=k: self._set_param(k, v))
        for i, k in enumerate(("o1", "o2", "o3")):
            lab = (m["labels"][5 + i] if 5 + i < len(m["labels"]) else "").strip()
            if not lab:
                continue
            dpg.add_checkbox(label=lab, parent="params",
                             default_value=bool(self.eng.fx[k]),
                             user_data=k, callback=self.on_check)

    # --- layout --------------------------------------------------------------
    def request_layout(self):
        """Ask for a relayout; do not perform one here.

        relayout() deletes the net and cube textures and builds new ones. Dear
        PyGui callbacks run INSIDE render_dearpygui_frame(), while those very
        textures are bound to the image widgets being drawn - and deleting an
        item that the renderer is walking is a native crash, not an exception.
        It survives often enough to look fine, which is worse.

        Changing face size is the case that trips it: on_faceB resizes the
        engine, which changes the net from 48x48 to 96x96, so the textures MUST
        be rebuilt and cannot simply be reused. Deferring to the top of the next
        pass costs one frame and takes the deletion out of the render entirely.
        """
        self._need_layout = True

    def relayout(self):
        """Size both views to whatever the window currently is.

        The panes were fixed pixel sizes, so maximising the window left two
        small pictures in the corner of a large expanse of panel. Both views are
        square, so each gets the largest square that fits its half of the space.
        """
        vw = max(640, dpg.get_viewport_client_width())
        vh = max(420, dpg.get_viewport_client_height())

        # What is on screen decides what there is room for. With the control
        # column hidden its 340 px come back, with one view hidden the other
        # gets the whole width, and the pane captions stop reserving a line.
        nview = 2 if self.layout == "both" else 1
        if self.ui:
            pane_h = max(VIEW_MIN, vh - 108)
            avail  = vw - SIDE_W - (22 * nview + 24)
        else:
            # Presenting: no control column, no captions, no borders and no
            # padding, so none of it gets an allowance. The picture takes the
            # whole frame less the gap between two of them.
            pane_h = max(VIEW_MIN, vh)
            avail  = vw - (16 if nview == 2 else 0)
        per = max(VIEW_MIN, avail // nview)
        side = max(VIEW_MIN, min(per, pane_h))

        dpg.configure_item("net_win",  show=self.layout in ("both", "net"))
        dpg.configure_item("cube_win", show=self.layout in ("both", "cube"))
        dpg.configure_item("side_win", show=self.ui)

        th = self._themes.get("present" if not self.ui else "normal")
        if th:
            dpg.bind_theme(th)
        dpg.set_viewport_clear_color([0, 0, 0, 255] if not self.ui
                                     else [17, 19, 24, 255])
        for tag in ("net_win", "cube_win", "side_win"):
            dpg.configure_item(tag, border=self.ui)
        # The captions, the readout and the key hints are UI too - a clean
        # picture means nothing left over the top of it.
        for tag in ("net_cap", "cube_cap", "stat_txt", "hint1", "hint2"):
            dpg.configure_item(tag, show=self.ui)

        # The net is upscaled by a WHOLE number so the LED grid stays hard;
        # bilinear scaling of a 48-pixel image looks like a photograph of a cube
        # rather than a cube.
        self.net_scale = max(1, side // self.eng.cols)
        # The cube render is capped whatever the pane size, and the image is
        # scaled up to fill. Measured, the renderer costs 28 ms a frame at 620
        # and 64 ms at 900 - it is quadratic in the size, and it is already the
        # single most expensive thing the app does. Rendering a fullscreen cube
        # at its true size would take the whole app from 35 fps to 15, so
        # fullscreen makes the picture BIGGER, not sharper. Raising this is not
        # a free win; measure before touching it.
        self.cube_px = min(CUBE_MAX, side)
        self.view_side = side

        if self.ui:
            for tag in ("net_win", "cube_win"):
                dpg.configure_item(tag, width=side + 22, height=pane_h + 34)
            dpg.configure_item("side_win", height=pane_h + 34)
        # Centre what is left, rather than letting it sit against the corner.
        # In presentation mode the panes are exactly the size of their pictures
        # and are positioned by hand; the black around them is the viewport
        # showing through, which is why the clear colour matters as much as the
        # theme does.
        if not self.ui:
            gap = 16 if nview == 2 else 0
            total = side * nview + gap
            x0 = max(0, (vw - total) // 2)
            y0 = max(0, (vh - side) // 2)
            if self.layout in ("both", "net"):
                dpg.configure_item("net_win", width=side, height=side)
                dpg.set_item_pos("net_win", [x0, y0])
                x0 += side + gap
            if self.layout in ("both", "cube"):
                dpg.configure_item("cube_win", width=side, height=side)
                dpg.set_item_pos("cube_win", [x0, y0])

        # Only the visible views get textures. A hidden one would otherwise
        # allocate at full pane size and never be written to - 7.7 MB of
        # float32 for a net nobody is looking at. Switching back runs this
        # again, so the texture is there by the time anything draws into it.
        if self.layout in ("both", "net"):
            self.remake_net_texture()
        if self.layout in ("both", "cube"):
            self.remake_cube_texture()

    def remake_net_texture(self):
        w = self.eng.cols * self.net_scale
        h = self.eng.rows * self.net_scale
        if dpg.does_item_exist("net_img"):
            dpg.delete_item("net_img")
        if dpg.does_item_exist("net_tex"):
            dpg.delete_item("net_tex")
        with dpg.texture_registry():
            dpg.add_raw_texture(w, h, np.zeros(w * h * 4, np.float32),
                                format=dpg.mvFormat_Float_rgba, tag="net_tex")
        dpg.add_image("net_tex", tag="net_img", parent="net_win")
        self._bufs.pop("net", None)

    def remake_cube_texture(self):
        p = self.cube_px
        if dpg.does_item_exist("cube_img"):
            dpg.delete_item("cube_img")
        if dpg.does_item_exist("cube_tex"):
            dpg.delete_item("cube_tex")
        with dpg.texture_registry():
            dpg.add_raw_texture(p, p, np.zeros(p * p * 4, np.float32),
                                format=dpg.mvFormat_Float_rgba, tag="cube_tex")
        # Drawn at view_side even when rendered smaller, so capping the render
        # cost does not also shrink the picture.
        dpg.add_image("cube_tex", tag="cube_img", parent="cube_win",
                      width=self.view_side, height=self.view_side)
        self._bufs.pop("cube", None)

    # --- interaction ---------------------------------------------------------
    # --- grab and turn --------------------------------------------------------
    # The angle at the start of a drag is captured ONCE, on the press, and every
    # later position is that angle plus the total drag delta. That is what makes
    # it feel like holding the object: let go of the mouse without moving and
    # the cube does not drift.
    #
    # It used to capture on mvMouseDownHandler, which fires every frame the
    # button is held rather than once when it goes down. So the "starting" angle
    # was re-taken continuously and the drag delta was added to it again each
    # frame - the cube span at a rate proportional to how far the pointer had
    # moved from where the drag began. A spin control, not a grab, exactly as it
    # felt.
    def on_mouse_click(self, sender, app_data):
        if dpg.is_item_hovered("cube_img"):
            self._dragging = True
            self._yaw0, self._pitch0 = self.yaw, self.pitch

    def on_mouse_release(self, sender, app_data):
        self._dragging = False

    def on_drag(self, sender, app_data):
        # Keyed to whether the drag STARTED on the cube, not to what is under
        # the pointer now, so running off the edge mid-turn does not drop it.
        if not self._dragging:
            return
        _, dx, dy = app_data
        # Scaled to the view, so dragging the full width is half a turn whatever
        # size the window is. A fixed radians-per-pixel means the same hand
        # movement does something different after you resize.
        k = 3.14159265 / max(120, self.view_side)
        self.yaw = self._yaw0 + dx * k
        self.pitch = max(-1.45, min(1.45, self._pitch0 + dy * k))

    def on_wheel(self, sender, app_data):
        if not dpg.is_item_hovered("cube_img"):
            return
        # Multiplicative, so a notch moves the same proportion at every range.
        self.dist = max(1.9, min(14.0, self.dist * np.exp(-app_data * 0.06)))

    def on_key(self, sender, app_data):
        # Presentation keys sit under the left hand so the right stays on the
        # mouse for rotating the cube: Q and E either side of W, which is the
        # pair together.
        # Not while a value is being typed. The handler is global, so without
        # this, typing into a box would also be driving the layout.
        if any(dpg.does_item_exist(t) and dpg.is_item_active(t) for t in self._inputs):
            return
        if app_data == dpg.mvKey_F11:
            dpg.toggle_viewport_fullscreen()
        elif app_data == dpg.mvKey_Spacebar:
            self.playing = not self.playing
        elif app_data == dpg.mvKey_Q:
            self.set_layout("net")
        elif app_data == dpg.mvKey_E:
            self.set_layout("cube")
        elif app_data == dpg.mvKey_W:
            self.set_layout("both")
        elif app_data == dpg.mvKey_H:
            self.ui = not self.ui
            self.request_layout()

    def set_layout(self, which):
        """Q, E and W go straight to a full-frame picture, every time.

        These are not layout choices with a separate "and now hide the
        controls" step - they ARE the presentation mode, and the view is what
        you wanted to look at. Requiring a second press to clear the chrome
        made the first press produce something nobody asked for: the same
        cluttered window with one view missing.

        H brings the controls back without leaving the layout, for adjusting a
        slider while watching, and takes them away again.
        """
        self.layout = which
        self.ui = False
        self.request_layout()

    # --- the loop ------------------------------------------------------------
    def step_sim(self):
        now = time.perf_counter()
        dt = min(0.25, now - self.last)      # a stalled window must not sprint
        self.last = now
        if not self.playing:
            self.acc = 0.0
            return
        self.acc += dt * 1000.0
        n = 0
        while self.acc >= STEP and n < 6:
            self.audio_push()
            self.eng.frame(STEP)
            self.acc -= STEP
            n += 1

    def draw(self):
        net = self.net_image()
        if self.layout in ("both", "net"):
            big = net.repeat(self.net_scale, 0).repeat(self.net_scale, 1)
            dpg.set_value("net_tex", self._rgba("net", big))
        if self.layout in ("both", "cube"):
            img = render.render(net, self.eng.B, self.cube_px,
                                self.yaw, self.pitch, self.dist)
            dpg.set_value("cube_tex", self._rgba("cube", img))

        s = stats(net, self.eng.lit_mask(flat=bool(self.eng.fx.get("o3"))))
        dpg.set_value("stat_txt",
                      f"mean {s['mean']:5.1f}   sigma {s['sigma']:5.1f}   "
                      f"dark {s['dark']:4.1f}%   sat {s['sat']:3d}")
        lvl = self.live.level if self.live else 0.0
        dpg.set_value("lvl_bar", min(1.0, lvl / 220.0))
        if self.beat_flash:
            self.beat_flash -= 1
        dpg.configure_item("beat_led", default_value=(90, 169, 230, 255)
                           if self.beat_flash else (42, 47, 58, 255))


def build(app):
    dpg.create_context()
    dpg.create_viewport(title="Cube FX Simulator (native)", width=1180, height=780)

    with dpg.handler_registry():
        dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, callback=app.on_drag)
        # click = once on press; down = every frame while held. The
        # difference is the whole bug this replaced.
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Left, callback=app.on_mouse_click)
        dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=app.on_mouse_release)
        dpg.add_mouse_wheel_handler(callback=app.on_wheel)
        dpg.add_key_press_handler(callback=app.on_key)

    with dpg.window(tag="root"):
        with dpg.group(horizontal=True):
            with dpg.child_window(tag="net_win", width=420, height=470):
                dpg.add_text("Unfolded net", tag="net_cap", color=(139, 147, 163))
            with dpg.child_window(tag="cube_win", width=420, height=470):
                dpg.add_text("Cube - drag to rotate, wheel to zoom",
                             tag="cube_cap", color=(139, 147, 163))
            with dpg.child_window(tag="side_win", width=SIDE_W - 10, height=470):
                dpg.add_combo(app.eng.names, label="effect",
                              default_value=app.eng.names[0], width=200,
                              callback=app.on_effect)
                dpg.add_combo([p[0] for p in PALETTES], label="palette",
                              default_value="Rainbow", width=200,
                              callback=app.on_palette)
                dpg.add_combo(["4", "8", "16", "32"], label="face B", default_value="16",
                              width=80, callback=app.on_faceB)
                # Several effects paint with SEGCOLOR(0). WLED's DEFAULT_COLOR
                # is amber, so without this those effects could only ever be
                # seen in one colour here.
                dpg.add_color_edit((255, 160, 0, 255), label="primary",
                                   width=170, no_alpha=True,
                                   callback=app.on_color)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="play/pause",
                                   callback=lambda: setattr(app, "playing", not app.playing))
                    dpg.add_button(label="step",
                                   callback=lambda: (app.audio_push(), app.eng.frame(STEP)))
                    dpg.add_button(label="restart fx",
                                   callback=lambda: app.eng.select(app.eng.idx))
                dpg.add_separator()
                dpg.add_text("Parameters")
                dpg.add_group(tag="params")
                dpg.add_separator()
                dpg.add_text("Audio")
                dpg.add_group(tag="audio_rows")
                for key, lab, val, lo, hi, attr in (
                        ("vol",  "volume", 90,  0,  255, "vol"),
                        ("bass", "bass",   45,  0,  255, "bass"),
                        ("mid",  "mid",    50,  0,  255, "mid"),
                        ("treb", "treble", 35,  0,  255, "treb"),
                        ("bpm",  "bpm",    120, 30, 200, "bpm")):
                    app.pair("audio_rows", key, lab, val, lo, hi,
                             lambda v, a=attr: setattr(app.syn, a, int(v)))
                dpg.add_checkbox(label="auto beat", default_value=True,
                                 callback=lambda s, v: setattr(app.syn, "auto_beat", v))
                # Gate a band and it goes silent between beats, jumping to its
                # slider level on one. Only the bass ever had a transient
                # otherwise, so mid and treble could not be judged on how an
                # effect answers a hit.
                dpg.add_text("gate to beat", color=(139, 147, 163))
                with dpg.group(horizontal=True):
                    for attr, lab in (("gate_bass", "bass"), ("gate_mid", "mid"),
                                      ("gate_treb", "treble")):
                        dpg.add_checkbox(label=lab, tag=f"chk_{attr}",
                                         callback=lambda s, v, a=attr:
                                             setattr(app.syn, a, bool(v)))
                dpg.add_checkbox(label="silence (mute all bands)",
                                 callback=lambda s, v: setattr(app.syn, "muted", v))
                dpg.add_color_button(tag="beat_led", default_value=(42, 47, 58, 255),
                                     width=280, height=6, no_border=True)
                dpg.add_separator()
                dpg.add_button(label="use live audio", tag="live_btn",
                               callback=lambda: app.toggle_live())
                dpg.add_group(tag="gain_row")
                app.pair("gain_row", "live_gain", "live gain", 3.0, 0.2, 12.0,
                         lambda v: setattr(app.live, "gain", float(v)) if app.live else None,
                         is_float=True)
                dpg.add_progress_bar(tag="lvl_bar", default_value=0.0, width=280)
                dpg.add_text("", tag="live_msg", wrap=300)
        dpg.add_text("", tag="stat_txt")
        dpg.add_text("Q net    E cube    W both    H hide UI", tag="hint1",
                     color=(130, 140, 155))
        dpg.add_text("space = play/pause    F11 = fullscreen window", tag="hint2",
                     color=(130, 140, 155))

    app._themes['normal'] = apply_theme()
    app._themes['present'] = present_theme()
    app.rebuild_params()
    dpg.set_primary_window("root", True)
    dpg.setup_dearpygui()
    app.relayout()
    # Both views follow the window from here on. Without this, maximising left
    # two small pictures marooned in the corner of a large empty panel.
    dpg.set_viewport_resize_callback(lambda s, d: app.request_layout())


# Where a capture is asked for, and where the result is written.
#
# A file rather than a socket or a hotkey because it needs no port, no focus and
# no window manager: anything that can create a file can ask for a frame, and
# the app answers on its next tick.
SHOT_DIR = os.path.join(tempfile.gettempdir(), "cubefx")
SHOT_REQ = os.path.join(SHOT_DIR, "capture.request")
SHOT_PNG = os.path.join(SHOT_DIR, "capture.png")


def service_capture():
    """Write a PNG of THIS APP'S OWN window if one has been asked for.

    dpg.output_frame_buffer hands back the frame Dear PyGui just rendered, so
    what lands in the file is the viewport and nothing else - no other window,
    no desktop, no wallpaper, and nothing at all when the app is not running.
    That scoping is the whole reason it is done this way. The obvious
    alternative, a screen or window grab through the Windows API, photographs
    whatever happens to be in front of it: asked to check this app's theme it
    once returned a locked machine's lock screen instead, which is nobody's
    business and was never the thing being asked for. A frame buffer cannot
    make that mistake, because the app has nothing else to give.

    Must be called from inside the render loop - the buffer does not exist
    outside it.
    """
    try:
        if not os.path.exists(SHOT_REQ):
            return
        os.remove(SHOT_REQ)                 # first, so a failure cannot loop
        dpg.output_frame_buffer(SHOT_PNG)
    except Exception as e:                  # a capture must never kill the app
        print(f"capture failed: {e}")


def main():
    app = App()
    build(app)
    dpg.show_viewport()
    os.makedirs(SHOT_DIR, exist_ok=True)
    print(f"if a frame throws, the traceback lands in {os.path.join(SHOT_DIR, 'crash.txt')}")
    print(f"frame capture: create {SHOT_REQ} to get a PNG at {SHOT_PNG}")
    try:
        while dpg.is_dearpygui_running():
            if app._need_layout:
                app._need_layout = False
                app.relayout()
            try:
                app.step_sim()
                app.draw()
            except Exception:
                # One bad frame should not take the window down with it. The
                # traceback goes to the console AND to a file, because the
                # console scrolls away and the interesting one is always the
                # first, not the hundredth.
                import traceback
                traceback.print_exc()
                try:
                    with open(os.path.join(SHOT_DIR, "crash.txt"), "a") as fh:
                        fh.write(traceback.format_exc() + "\n")
                except Exception:
                    pass
                app.playing = False
            dpg.render_dearpygui_frame()
            service_capture()
    finally:
        app.stop_live()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
