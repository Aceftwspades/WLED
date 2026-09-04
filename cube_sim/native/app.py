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
NET_SCALE = 8
CUBE_PX = 360
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
        self.eng.select(0)

    # --- textures ------------------------------------------------------------
    @staticmethod
    def _rgba(img):
        """uint8 (h,w,3) -> flat float32 RGBA, which is what DPG wants."""
        h, w, _ = img.shape
        out = np.ones((h, w, 4), np.float32)
        out[..., :3] = img.astype(np.float32) / 255.0
        return out.reshape(-1)

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
        dpg.configure_item("net_img", width=self.eng.cols * NET_SCALE,
                           height=self.eng.rows * NET_SCALE)
        self.remake_net_texture()

    def on_param(self, sender, val):
        self.eng.fx[dpg.get_item_user_data(sender)] = int(val)
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
            dpg.add_slider_int(label=lab, parent="params", width=150,
                               min_value=0, max_value=31 if k == "c3" and
                               m["defs"].get(k, 0) <= 31 and False else 255,
                               default_value=self.eng.fx[k], user_data=k,
                               callback=self.on_param)
        for i, k in enumerate(("o1", "o2", "o3")):
            lab = (m["labels"][5 + i] if 5 + i < len(m["labels"]) else "").strip()
            if not lab:
                continue
            dpg.add_checkbox(label=lab, parent="params",
                             default_value=bool(self.eng.fx[k]),
                             user_data=k, callback=self.on_check)

    def remake_net_texture(self):
        w = self.eng.cols * NET_SCALE
        h = self.eng.rows * NET_SCALE
        if dpg.does_item_exist("net_tex"):
            dpg.delete_item("net_img")
            dpg.delete_item("net_tex")
        with dpg.texture_registry():
            dpg.add_raw_texture(w, h, np.zeros(w * h * 4, np.float32),
                                format=dpg.mvFormat_Float_rgba, tag="net_tex")
        dpg.add_image("net_tex", tag="net_img", parent="net_win")

    # --- interaction ---------------------------------------------------------
    def on_drag(self, sender, app_data):
        if not dpg.is_item_hovered("cube_img"):
            return
        _, dx, dy = app_data
        self.yaw = self._yaw0 + dx * 0.01
        self.pitch = max(-1.45, min(1.45, self._pitch0 + dy * 0.01))

    def on_mouse_down(self, sender, app_data):
        self._yaw0, self._pitch0 = self.yaw, self.pitch

    def on_wheel(self, sender, app_data):
        if not dpg.is_item_hovered("cube_img"):
            return
        # Multiplicative, so a notch moves the same proportion at every range.
        self.dist = max(1.9, min(14.0, self.dist * np.exp(-app_data * 0.12)))

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
            big = net.repeat(NET_SCALE, 0).repeat(NET_SCALE, 1)
            dpg.set_value("net_tex", self._rgba(big))
        if self.layout in ("both", "cube"):
            img = render.render(net, self.eng.B, CUBE_PX,
                                self.yaw, self.pitch, self.dist)
            dpg.set_value("cube_tex", self._rgba(img))

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

    with dpg.texture_registry():
        dpg.add_raw_texture(CUBE_PX, CUBE_PX, np.zeros(CUBE_PX * CUBE_PX * 4, np.float32),
                            format=dpg.mvFormat_Float_rgba, tag="cube_tex")

    with dpg.handler_registry():
        dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, callback=app.on_drag)
        dpg.add_mouse_down_handler(button=dpg.mvMouseButton_Left, callback=app.on_mouse_down)
        dpg.add_mouse_wheel_handler(callback=app.on_wheel)
        dpg.add_key_press_handler(callback=app.on_key)

    with dpg.window(tag="root"):
        with dpg.group(horizontal=True):
            with dpg.child_window(tag="net_win", width=420, height=470):
                dpg.add_text("Unfolded net")
            with dpg.child_window(tag="cube_win", width=CUBE_PX + 20, height=470):
                dpg.add_text("Cube - drag to rotate, wheel to zoom")
                dpg.add_image("cube_tex", tag="cube_img")
            with dpg.child_window(width=330, height=470):
                dpg.add_combo(app.eng.names, label="effect",
                              default_value=app.eng.names[0], width=200,
                              callback=app.on_effect)
                dpg.add_combo([p[0] for p in PALETTES], label="palette",
                              default_value="Rainbow", width=200,
                              callback=app.on_palette)
                dpg.add_combo(["4", "8", "16"], label="face B", default_value="16",
                              width=80, callback=app.on_faceB)
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

    app.remake_net_texture()
    app.rebuild_params()
    dpg.set_primary_window("root", True)
    dpg.setup_dearpygui()


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
