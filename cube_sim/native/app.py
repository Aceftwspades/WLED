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
        self.layout = "both"
        self._bufs = {}
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
            self.live = LiveAudio(gain=dpg.get_value("live_gain"))
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
        self.relayout()

    def on_color(self, sender, val):
        r, g, b = (int(c * 255) if c <= 1.0 else int(c) for c in val[:3])
        self.eng.colors((r << 16) | (g << 8) | b)

    def on_param(self, sender, val):
        k = dpg.get_item_user_data(sender)
        self.eng.fx[k] = int(val)
        if dpg.does_item_exist(f"inp_{k}"):
            dpg.set_value(f"inp_{k}", int(val))       # keep the typed box in step
        self.eng.push()

    def on_param_typed(self, sender, val):
        k = dpg.get_item_user_data(sender)
        self.eng.fx[k] = int(val)
        if dpg.does_item_exist(f"sld_{k}"):
            dpg.set_value(f"sld_{k}", int(val))
        self.eng.push()

    def on_check(self, sender, val):
        self.eng.fx[dpg.get_item_user_data(sender)] = 1 if val else 0
        self.eng.push()

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
            with dpg.group(horizontal=True, parent="params"):
                dpg.add_slider_int(tag=f"sld_{k}", width=150, min_value=0,
                                   max_value=hi, default_value=self.eng.fx[k],
                                   user_data=k, callback=self.on_param)
                # A typed box beside every slider. Dear PyGui does support
                # ctrl-click to type into a slider, but it is undiscoverable and
                # awkward when you want an exact value to compare two runs.
                dpg.add_input_int(tag=f"inp_{k}", width=62, step=0,
                                  min_value=0, max_value=hi,
                                  min_clamped=True, max_clamped=True,
                                  default_value=self.eng.fx[k], user_data=k,
                                  callback=self.on_param_typed)
                dpg.add_text(lab, color=(139, 147, 163))
        for i, k in enumerate(("o1", "o2", "o3")):
            lab = (m["labels"][5 + i] if 5 + i < len(m["labels"]) else "").strip()
            if not lab:
                continue
            dpg.add_checkbox(label=lab, parent="params",
                             default_value=bool(self.eng.fx[k]),
                             user_data=k, callback=self.on_check)

    # --- layout --------------------------------------------------------------
    def relayout(self):
        """Size both views to whatever the window currently is.

        The panes were fixed pixel sizes, so maximising the window left two
        small pictures in the corner of a large expanse of panel. Both views are
        square, so each gets the largest square that fits its half of the space.
        """
        vw = max(640, dpg.get_viewport_client_width())
        vh = max(420, dpg.get_viewport_client_height())
        pane_h = max(VIEW_MIN, vh - 108)
        half = max(VIEW_MIN, (vw - SIDE_W - 46) // 2)
        side = max(VIEW_MIN, min(half, pane_h))

        # The net is upscaled by a WHOLE number so the LED grid stays hard;
        # bilinear scaling of a 48-pixel image looks like a photograph of a cube
        # rather than a cube.
        self.net_scale = max(1, side // self.eng.cols)
        self.cube_px = min(CUBE_MAX, side)
        self.view_side = side

        for tag in ("net_win", "cube_win"):
            dpg.configure_item(tag, width=side + 22, height=pane_h + 34)
        dpg.configure_item("side_win", height=pane_h + 34)
        self.remake_net_texture()
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
    def on_drag(self, sender, app_data):
        if not dpg.is_item_hovered("cube_img"):
            return
        # Halved from 0.01. At the old rate a small hand movement spun the cube
        # most of a turn, which made it hard to settle on a face.
        _, dx, dy = app_data
        self.yaw = self._yaw0 + dx * 0.005
        self.pitch = max(-1.45, min(1.45, self._pitch0 + dy * 0.005))

    def on_mouse_down(self, sender, app_data):
        self._yaw0, self._pitch0 = self.yaw, self.pitch

    def on_wheel(self, sender, app_data):
        if not dpg.is_item_hovered("cube_img"):
            return
        # Multiplicative, so a notch moves the same proportion at every range.
        self.dist = max(1.9, min(14.0, self.dist * np.exp(-app_data * 0.06)))

    def on_key(self, sender, app_data):
        if app_data == dpg.mvKey_F11:
            dpg.toggle_viewport_fullscreen()
        elif app_data == dpg.mvKey_Spacebar:
            self.playing = not self.playing

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
        dpg.add_mouse_down_handler(button=dpg.mvMouseButton_Left, callback=app.on_mouse_down)
        dpg.add_mouse_wheel_handler(callback=app.on_wheel)
        dpg.add_key_press_handler(callback=app.on_key)

    with dpg.window(tag="root"):
        with dpg.group(horizontal=True):
            with dpg.child_window(tag="net_win", width=420, height=470):
                dpg.add_text("Unfolded net", color=(139, 147, 163))
            with dpg.child_window(tag="cube_win", width=420, height=470):
                dpg.add_text("Cube - drag to rotate, wheel to zoom",
                             color=(139, 147, 163))
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
                dpg.add_slider_int(label="volume", default_value=90, max_value=255,
                                   width=140, callback=lambda s, v: setattr(app.syn, "vol", v))
                dpg.add_slider_int(label="bass", default_value=45, max_value=255,
                                   width=140, callback=lambda s, v: setattr(app.syn, "bass", v))
                dpg.add_slider_int(label="mid", default_value=50, max_value=255,
                                   width=140, callback=lambda s, v: setattr(app.syn, "mid", v))
                dpg.add_slider_int(label="treble", default_value=35, max_value=255,
                                   width=140, callback=lambda s, v: setattr(app.syn, "treb", v))
                dpg.add_slider_int(label="bpm", default_value=120, min_value=30,
                                   max_value=200, width=140,
                                   callback=lambda s, v: setattr(app.syn, "bpm", v))
                dpg.add_checkbox(label="auto beat", default_value=True,
                                 callback=lambda s, v: setattr(app.syn, "auto_beat", v))
                dpg.add_checkbox(label="silence (mute all bands)",
                                 callback=lambda s, v: setattr(app.syn, "muted", v))
                dpg.add_color_button(tag="beat_led", default_value=(42, 47, 58, 255),
                                     width=280, height=6, no_border=True)
                dpg.add_separator()
                dpg.add_button(label="use live audio", tag="live_btn",
                               callback=lambda: app.toggle_live())
                dpg.add_slider_float(label="live gain", tag="live_gain", width=140,
                                     default_value=3.0, min_value=0.2, max_value=12.0,
                                     callback=lambda s, v: setattr(app.live, "gain", v)
                                     if app.live else None)
                dpg.add_progress_bar(tag="lvl_bar", default_value=0.0, width=280)
                dpg.add_text("", tag="live_msg", wrap=300)
        dpg.add_text("", tag="stat_txt")
        dpg.add_text("space = play/pause    F11 = fullscreen", color=(130, 140, 155))

    apply_theme()
    app.rebuild_params()
    dpg.set_primary_window("root", True)
    dpg.setup_dearpygui()
    app.relayout()
    # Both views follow the window from here on. Without this, maximising left
    # two small pictures marooned in the corner of a large empty panel.
    dpg.set_viewport_resize_callback(lambda s, d: app.relayout())


def main():
    app = App()
    build(app)
    dpg.show_viewport()
    try:
        while dpg.is_dearpygui_running():
            app.step_sim()
            app.draw()
            dpg.render_dearpygui_frame()
    finally:
        app.stop_live()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
