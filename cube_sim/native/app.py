"""
WLED Effect Studio - the native front end.

    python -m native.app

Started life as the Cube FX Simulator's window: the same engine and the same
numbers as the headless tool, plus controls and live audio. It is now an
editor as well - a project holds a geometry and the effects being written for
it, the code pane compiles an effect into the engine in about a second and
swaps it in without leaving the window, and the views draw whatever the
geometry is: a strip, a matrix, the cube, a sphere, a coordinate list.

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
import re
import tempfile
import time

import numpy as np
import dearpygui.dearpygui as dpg

import queue
import threading

from native.engine import Engine, stats
from native.synth import Synth
from native.geometry import Geometry, KINDS
from native.project import default_project, Project, list_projects, project_path, remember_project, PROJECTS
from native.graph_ui import GraphPanel, build_panel
from native import render, gif
from native.apiref import API
import shutil
import subprocess

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


# Built from the engine at start-up rather than listed here: the fixed set comes
# from the firmware's own JSON_palette_names, and the usermod-registered ones
# (the audio-reactive gradients) are queried from the DLL, so anything a usermod
# adds appears without this file knowing about it.
PALETTES = []


class App:
    def __init__(self):
        self.project = default_project()
        self.eng = Engine()
        self.eng.set_geometry(self.project.geometry)
        # --- the editor ------------------------------------------------------
        self.edit_file = None       # file name in the project's effects/
        self.edit_dirty = False
        self.build_q = queue.Queue()  # worker -> main thread: BuildReport
        self.building = False
        self._watch_mtime = None     # the edit file's mtime when last read, for the watcher
        self._watch_at = 0.0
        self.build_msg = ""
        self.gp = GraphPanel(self)    # the node editor
        global PALETTES
        if not PALETTES:
            PALETTES = self.eng.palette_list()
        self.syn = Synth()
        self.live = None
        self.playing = True
        self.acc = 0.0
        self.last = time.perf_counter()
        self.yaw, self.pitch, self.dist = -0.6, 0.75, 4.6
        self.beat_flash = 0
        # WLED's segment defaults: primary amber, secondary and tertiary BLACK.
        # Faithful rather than convenient - "* Colors 1&2" fading to black is
        # what the device does before you have set a secondary, and the
        # simulator should show that rather than a prettier lie.
        self.seg_cols = [0xFFA000, 0x000000, 0x000000]
        self.layout = "both"        # both | net | cube
        # Set by anything that needs the panes resized; acted on at the TOP of
        # the next loop pass, never inside a callback. See request_layout().
        self._need_layout = True
        self.ui = True              # control column and pane captions
        self._themes = {}           # normal / present, built once in build()
        # --- recording ---------------------------------------------------
        # Frames are taken from the LIVE run rather than re-simulated. What
        # comes out is what was on the screen, including live audio and any
        # slider you moved while it ran - a re-simulation would quietly give
        # you the synthetic generator and today's defaults instead.
        self.rec = None             # list of frames while recording
        self.rec_next = 0.0         # wall-clock time of the next frame
        self.rec_left = 0.0         # seconds still to capture
        self.rec_msg = ""           # what to show under the button
        self.shot_req = False       # a PNG of the 3-D view into the project, next frame
        self._bufs = {}
        self._inputs = set()
        self._dragging = False
        self._yaw0, self._pitch0 = self.yaw, self.pitch
        # the project remembers the last effect by NAME - indices move
        idx = self.eng.names.index(self.project.selected) if self.project.selected in self.eng.names else 0
        self.eng.select(idx)

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
        """The logical view: the segment as the effect sees it. A 1-D strip is
        one row, drawn tall enough to look at."""
        rgb = self.eng.rgb().copy()
        if not self.eng.fx.get("o3"):
            # Cube mode: the gap corners are not pixels and effects skip them,
            # so without this they keep whatever flat mode last left there.
            mask = self.eng.lit_mask()
            if mask.shape != rgb.shape[:2]:
                # the geometry changed under us between the two reads (a
                # callback on another thread): one black frame, not a crash
                return np.zeros(rgb.shape, np.uint8)
            rgb[~mask] = 0
        if rgb.shape[0] == 1:
            rows = max(4, rgb.shape[1] // 12)
            rgb = np.repeat(rgb, rows, axis=0)
        return rgb

    def view_image(self, net, px):
        """The 3-D view: the face-warp renderer for the cube (faster, and
        exact for flat faces), the point cloud for everything else."""
        g = self.eng.geom
        if g is not None and g.kind == "cube" and not self.eng.fx.get("o3"):
            return render.render(net if net.shape[0] == self.eng.rows else self.eng.rgb(),
                                 self.eng.B, px, self.yaw, self.pitch, self.dist)
        rgb = self.eng.rgb().reshape(-1, 3)
        if g is None:
            return np.zeros((px, px, 3), np.uint8)
        return render.render_points(g.pos, rgb, px, self.yaw, self.pitch, self.dist)

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
            from native.audio import open_live
            # pair() names its widgets sld_/inp_, so read the box.
            dev = dpg.get_value("live_dev") if dpg.does_item_exist("live_dev") else "system output"
            index = None
            if dev and dev != "system output":
                from native.audio import list_inputs
                for i, n in list_inputs():
                    if n == dev:
                        index = i
            self.live = open_live(gain=float(dpg.get_value("inp_live_gain")), device=index)
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

    # --- recording ------------------------------------------------------------
    REC_FPS = 15

    def start_rec(self, secs=15.0):
        if self.rec is not None:
            return
        self.rec = []
        self.rec_left = secs
        self.rec_next = time.perf_counter()
        self.rec_msg = f"recording {secs:.0f} s..."

    def _encode(self, frames, path):
        """Runs on a worker thread: encoding 225 frames takes several seconds
        and the window must keep drawing while it does."""
        try:
            n = gif.write(path, frames, fps=self.REC_FPS)
            self.rec_msg = f"{os.path.basename(path)}  {n/1024:.0f} KB"
        except Exception as e:
            self.rec_msg = f"gif failed: {e}"

    def rec_frame(self, net_img, cube_img):
        """Offered every drawn frame; takes one only when the clock says so."""
        if self.shot_req:
            self.shot_req = False
            img = cube_img if cube_img is not None else net_img
            if img is not None:
                try:
                    from PIL import Image
                    d = os.path.join(self.project.path, "export", "shots")
                    os.makedirs(d, exist_ok=True)
                    name = "".join(c if c.isalnum() else "_" for c in self.eng.names[self.eng.idx])
                    path = os.path.join(d, f"{name}_{int(time.time())}.png")
                    Image.fromarray(np.ascontiguousarray(img)).save(path)
                    self.rec_msg = f"saved {os.path.relpath(path, self.project.path)}"
                except Exception as e:
                    self.rec_msg = f"screenshot failed: {e}"
        if self.rec is None:
            return
        now = time.perf_counter()
        if now < self.rec_next:
            return
        self.rec_next += 1.0 / self.REC_FPS
        parts = [p for p in (net_img, cube_img) if p is not None]
        if not parts:
            return
        if len(parts) == 1:
            frame = parts[0]
        else:
            h = max(p.shape[0] for p in parts)
            frame = np.zeros((h, sum(p.shape[1] for p in parts) + 8, 3), np.uint8)
            x = 0
            for p in parts:
                y = (h - p.shape[0]) // 2
                frame[y:y + p.shape[0], x:x + p.shape[1]] = p
                x += p.shape[1] + 8
        self.rec.append(frame.copy())
        self.rec_left -= 1.0 / self.REC_FPS
        if self.rec_left > 0:
            self.rec_msg = f"recording {self.rec_left:4.1f} s..."
            return
        frames, self.rec = self.rec, None
        name = "".join(c if c.isalnum() else "_" for c in self.eng.names[self.eng.idx])
        os.makedirs(GIF_DIR, exist_ok=True)
        path = os.path.join(GIF_DIR, f"{name}_{int(time.time())}.gif")
        self.rec_msg = f"encoding {len(frames)} frames..."
        import threading
        threading.Thread(target=self._encode, args=(frames, path), daemon=True).start()

    def toggle_live(self):
        self.stop_live() if self.live else self.start_live()

    # --- callbacks -----------------------------------------------------------
    def on_effect(self, s, val):
        self.eng.select(self.eng.names.index(val))
        self.rebuild_params()
        self.sync_palette_combo()
        self.project.selected = val
        self.project.save()

    def on_palette(self, s, val):
        self.eng.pal = dict(PALETTES)[val]
        self.eng.push()

    def on_pal_source(self, s, val):
        self.eng.pal_source = dict(PALETTES)[val]

    def palette_name_for(self, pid):
        for n, i in PALETTES:
            if i == pid:
                return n
        return PALETTES[0][0] if PALETTES else ""

    def sync_palette_combo(self):
        """Selecting an effect now loads ITS palette default, so the combo has
        to follow - otherwise it shows one palette while the cube renders
        another."""
        try:
            dpg.set_value("pal_combo", self.palette_name_for(self.eng.pal))
        except Exception:
            pass

    # --- geometry --------------------------------------------------------------
    GEOM_FIELDS = {
        "strip":    [("n", "LEDs", 1, 2000), ("ring", "ring", None, None)],
        "matrix":   [("w", "width", 1, 256), ("h", "height", 1, 256),
                     ("serpentine", "serpentine", None, None), ("vertical", "vertical", None, None),
                     ("start_right", "start right", None, None), ("start_bottom", "start bottom", None, None)],
        "cube":     [("B", "pixels per face", 4, 85)],
        "cylinder": [("w", "around", 3, 256), ("h", "tall", 1, 256)],
        "sphere":   [("w", "around", 3, 256), ("h", "rows", 2, 128)],
        "torus":    [("w", "around", 3, 256), ("h", "tube", 3, 64)],
        "xyz":      [],
    }

    def apply_geometry(self, geom):
        """A new geometry: into the engine, into the project, views resized.
        The effect restarts, so its sliders are rebuilt from the engine."""
        try:
            self.eng.set_geometry(geom)
        except Exception as e:
            # the engine said no (too many pixels): keep what was there
            self.eng.set_geometry(self.project.geometry)
            dpg.set_value("geom_desc", f"cannot use that geometry: {e}")
            return
        self.project.geometry = geom
        self.project.save()
        self.rebuild_params()
        self.request_layout()
        try:
            dpg.set_value("geom_desc", geom.describe())
            dpg.configure_item("map1d2d", show=geom.is2d)
        except Exception:
            pass

    def on_geom_kind(self, s, val):
        if val == "xyz":
            dpg.show_item("xyz_dialog")
            return
        params = dict(self.project.geometry.params) if self.project.geometry.kind == val else {}
        self.apply_geometry(Geometry(val, **params))
        self.rebuild_geom_fields()

    def on_geom_field(self, sender, val):
        key = dpg.get_item_user_data(sender)
        g = self.project.geometry
        params = dict(g.params); params[key] = val
        self.apply_geometry(Geometry(g.kind, **params))

    def on_xyz_file(self, s, app_data):
        path = app_data.get("file_path_name") if isinstance(app_data, dict) else None
        if not path:
            return
        try:
            g = Geometry.from_xyz_file(path)
        except Exception as e:
            dpg.set_value("geom_desc", f"could not read {os.path.basename(path)}: {e}")
            return
        self.apply_geometry(g)
        dpg.set_value("geom_kind", "xyz")
        self.rebuild_geom_fields()

    def rebuild_geom_fields(self):
        if not dpg.does_item_exist("geom_fields"):
            return
        dpg.delete_item("geom_fields", children_only=True)
        g = self.project.geometry
        for key, label, lo, hi in self.GEOM_FIELDS.get(g.kind, []):
            if lo is None:
                dpg.add_checkbox(label=label, parent="geom_fields", user_data=key,
                                 default_value=bool(g.params.get(key, key == "serpentine")),
                                 callback=self.on_geom_field)
            else:
                dpg.add_input_int(label=label, parent="geom_fields", user_data=key, width=90,
                                  default_value=int(g.params.get(key, {"n": 60, "w": 16, "h": 16, "B": 16}.get(key, 16))),
                                  min_value=lo, max_value=hi, min_clamped=True, max_clamped=True,
                                  on_enter=True, callback=self.on_geom_field)
        if g.kind == "xyz":
            dpg.add_text(f"{g.count} points from {g.params.get('source', 'file')}",
                         parent="geom_fields", color=(139, 147, 163))

    def on_map1d2d(self, s, val):
        self.eng.set_map1d2d(["strip", "bars", "arcs", "corner"].index(val))

    # --- the editor ------------------------------------------------------------
    def edit_open(self, fname):
        if not fname:
            return
        self.edit_file = fname
        self.edit_dirty = False
        self._watch_mtime = self._mtime(fname)
        dpg.set_value("code", self.project.read_effect(fname))
        if dpg.does_item_exist("meta_name"):
            self.meta_read()
        dpg.set_value("edit_status", f"{fname}")
        dpg.configure_item("edit_file", items=self.project.effect_files())
        dpg.set_value("edit_file", fname)
        self.refresh_import_buttons()

    # --- projects ---------------------------------------------------------------------
    # One folder per project under cube_sim/projects/ (or anywhere, by path).
    # Switching swaps the project object, applies its geometry, re-lists its
    # effects and graphs, and rebuilds the engine for its effects list.
    def switch_project(self, path, create=False):
        path = project_path(path)
        if not create and not os.path.isdir(path):
            dpg.set_value("edit_status", f"no project at {path}"); return
        if self.edit_dirty:
            self.edit_save()
        if self.gp.graph:
            self.gp.save()
        self.project = Project(path)
        remember_project(path)
        self.edit_file = None
        self.gp.graph = None; self.gp.file = None; self.gp.stack.clear()
        self.apply_geometry(self.project.geometry)
        dpg.set_value("geom_kind", self.project.geometry.kind)
        self.rebuild_geom_fields()
        dpg.configure_item("edit_file", items=self.project.effect_files()); dpg.set_value("edit_file", "")
        dpg.set_value("code", "")
        self.gp.refresh_lib()
        dpg.configure_item("graph_file", items=self.gp.files()); dpg.set_value("graph_file", "")
        self.gp.rebuild()
        self.refresh_import_buttons()
        self.refresh_project_list()
        dpg.set_value("device_host", self.project.options.get("device", ""))
        name = os.path.basename(path)
        dpg.set_value("edit_status", f"project {name}"); self.gp.status(f"project {name}")
        # the engine holds the previous project's drafts: build this one's list
        self.edit_build()

    def send_ledmap(self):
        host = dpg.get_value("device_host")
        self.project.options["device"] = host
        self.project.save()
        msg = self.project.send_ledmap(host)
        dpg.set_value("edit_status", msg); self.gp.status(msg)

    def new_project(self, name):
        name = (name or "").strip()
        if not name:
            dpg.set_value("edit_status", "type a project name first"); return
        path = project_path(name)
        if os.path.isdir(path):
            self.switch_project(path); return
        self.switch_project(path, create=True)
        dpg.set_value("project_name", "")

    def refresh_project_list(self):
        if dpg.does_item_exist("project_combo"):
            names = list_projects()
            cur = os.path.basename(self.project.path)
            if os.path.dirname(self.project.path) != PROJECTS and cur not in names:
                names.append(self.project.path)
                cur = self.project.path
            dpg.configure_item("project_combo", items=names)
            dpg.set_value("project_combo", cur)

    # --- the external editor and the file watcher -------------------------------------
    # The in-app box is for quick fixes. For real editing the file opens in
    # whatever editor the system has - VS Code if it is on the path, else the
    # .cpp association - and the watcher reloads the pane (and rebuilds, when
    # "watch" is ticked) each time the file is saved there. Click-to-line
    # goes to the same editor, since the in-app box cannot move its cursor.
    def _mtime(self, fname):
        try:
            return os.path.getmtime(self.project.effect_path(fname))
        except OSError:
            return None

    def editor_command(self):
        """The command that opens a file at a line, as a list with {file} and
        {line} holes; from project options, else VS Code, else none."""
        cmd = self.project.options.get("editor")
        if cmd:
            return cmd if isinstance(cmd, list) else cmd.split()
        code = shutil.which("code") or shutil.which("code.cmd")
        if code:
            return [code, "-g", "{file}:{line}"]
        return None

    def open_external(self, line=1):
        if not self.edit_file:
            return
        if self.edit_dirty:
            self.edit_save()
        path = self.project.effect_path(self.edit_file)
        cmd = self.editor_command()
        try:
            if cmd:
                subprocess.Popen([c.replace("{file}", path).replace("{line}", str(line)) for c in cmd])
                dpg.set_value("edit_status", f"opened in {os.path.basename(cmd[0])} - saves there reload here")
            elif hasattr(os, "startfile"):
                os.startfile(path)
                dpg.set_value("edit_status", "opened in the system's .cpp editor - saves there reload here")
            else:
                opener = shutil.which("xdg-open") or shutil.which("open")
                if opener:
                    subprocess.Popen([opener, path])
                dpg.set_value("edit_status", "opened externally - saves there reload here")
        except Exception as e:
            dpg.set_value("edit_status", f"could not open an editor: {e}")
        if dpg.does_item_exist("edit_watch"):
            dpg.set_value("edit_watch", True)

    def poll_watch(self):
        """Twice a second: has the file been saved outside? Then the pane
        takes the new text, unless it has unsaved edits of its own, and a
        watched file rebuilds."""
        now = time.time()
        if now - self._watch_at < 0.5 or not self.edit_file:
            return
        self._watch_at = now
        m = self._mtime(self.edit_file)
        if m is None or m == self._watch_mtime:
            return
        self._watch_mtime = m
        if self.edit_dirty:
            dpg.set_value("edit_status", f"{self.edit_file} changed on disk - unsaved edits here, not reloaded")
            return
        dpg.set_value("code", self.project.read_effect(self.edit_file))
        dpg.set_value("edit_status", f"{self.edit_file} reloaded from disk")
        if dpg.does_item_exist("edit_watch") and dpg.get_value("edit_watch") and not self.building:
            self.edit_build()

    def goto_line(self, line):
        """An error row was clicked: the external editor at that line, and
        the line's text in the status either way."""
        text = dpg.get_value("code").split("\n")
        if 1 <= line <= len(text):
            dpg.set_value("edit_status", f"line {line}: {text[line - 1].strip()[:90]}")
        if self.editor_command() or dpg.get_value("edit_watch"):
            self.open_external(line)

    # --- find and replace ----------------------------------------------------------------
    def find(self):
        """Every line holding the find text, as rows that go to the line."""
        needle = dpg.get_value("find_text")
        dpg.delete_item("edit_errors", children_only=True)
        if not needle:
            return
        lines = dpg.get_value("code").split("\n")
        hits = [(i + 1, l) for i, l in enumerate(lines) if needle.lower() in l.lower()]
        dpg.set_value("edit_status", f"{len(hits)} line(s) match")
        for ln, l in hits[:40]:
            dpg.add_selectable(label=f"{ln}: {l.strip()[:100]}", parent="edit_errors", user_data=ln,
                               callback=lambda s, a, u: self.goto_line(u))

    def replace_all(self):
        needle = dpg.get_value("find_text"); repl = dpg.get_value("replace_text")
        if not needle:
            return
        text = dpg.get_value("code")
        n = text.count(needle)
        if n:
            dpg.set_value("code", text.replace(needle, repl))
            self.edit_dirty = True
        dpg.set_value("edit_status", f"replaced {n} occurrence(s)")
        self.find()

    # --- the metadata string, as a form ----------------------------------------------
    # Name@slider labels;colour labels;palette;flags;defaults - a line most
    # people get wrong once. The form reads it out of the pane and writes it
    # back, so the fields are edited by name.
    META_FIELDS = ("meta_name", "meta_labels", "meta_colours", "meta_flags", "meta_defaults")

    def meta_read(self):
        m = re.search(r'PROGMEM\s*=\s*"([^"]*)"', dpg.get_value("code"))
        if not m:
            dpg.set_value("edit_status", "no metadata string in this file"); return
        text = m.group(1)
        name, _, rest = text.partition("@")
        parts = (rest.split(";") + ["", "", "", "", ""])[:5]
        for tag, v in zip(self.META_FIELDS, [name, parts[0], parts[1], parts[3], parts[4]]):
            dpg.set_value(tag, v)
        dpg.set_value("edit_status", "metadata read from the file")

    def meta_write(self):
        code = dpg.get_value("code")
        m = re.search(r'(PROGMEM\s*=\s*")([^"]*)(")', code)
        if not m:
            dpg.set_value("edit_status", "no metadata string in this file"); return
        name, labels, colours, flags, defaults = (dpg.get_value(t).replace('"', "'").replace(";", " ") if t == "meta_name"
                                                  else dpg.get_value(t).replace('"', "'") for t in self.META_FIELDS)
        new = f"{name}@{labels};{colours};!;{flags};{defaults}"
        dpg.set_value("code", code[:m.start(2)] + new + code[m.end(2):])
        self.edit_dirty = True
        dpg.set_value("edit_status", f"metadata: {new[:100]}")

    def api_pick(self, snippet, label):
        dpg.set_clipboard_text(snippet)
        dpg.set_value("edit_status", f"copied: {label} - Ctrl+V to paste at the cursor")

    def refresh_import_buttons(self):
        """The import buttons say what pressing them does to the current file."""
        for tag, fname in (("edit_import", self.edit_file), ("graph_import", self.gp.effect_file())):
            if dpg.does_item_exist(tag):
                on = bool(fname) and self.project.is_imported(fname)
                dpg.configure_item(tag, label="remove from list" if on else "import to list",
                                   enabled=bool(fname))

    def toggle_import(self, fname):
        """A draft joins the effects list, or leaves it. Either way the engine
        is rebuilt so the roster shows the list as it now is."""
        if not fname or fname not in self.project.effect_files():
            return
        on = not self.project.is_imported(fname)
        self.project.set_imported(fname, on)
        self.refresh_import_buttons()
        title = self.project.effect_title(fname)
        msg = f"{title} added to the effects list" if on else f"{title} removed from the effects list"
        dpg.set_value("edit_status", msg); self.gp.status(msg)
        self.edit_build()

    def ensure_built(self):
        """The file just opened for editing is previewed: if the engine does
        not have it - a draft that was not the last one built - build now."""
        if self.edit_file and self.project.effect_title(self.edit_file) not in self.eng.names:
            self.edit_build()

    def edit_rename(self):
        """The current effect takes the name typed in the new-name box."""
        title = (dpg.get_value("new_name") or "").strip()
        if not title or not self.edit_file:
            dpg.set_value("edit_status", "type the new name in the box first")
            return
        if self.edit_dirty:
            self.edit_save()
        new = self.project.rename_effect(self.edit_file, title)
        dpg.set_value("new_name", "")
        self.edit_open(new)
        dpg.set_value("edit_status", f"renamed to {title} ({new})")
        self.edit_build()

    def edit_new(self):
        title = (dpg.get_value("new_name") or "").strip() or "New Effect"
        fname = self.project.new_effect(title)
        self.edit_open(fname)
        dpg.set_value("new_name", "")

    def edit_save(self):
        if not self.edit_file:
            return
        self.project.write_effect(self.edit_file, dpg.get_value("code"))
        self.edit_dirty = False
        dpg.set_value("edit_status", f"{self.edit_file} saved")

    def on_code_edit(self, s, v):
        self.edit_dirty = True

    def open_graph_code(self):
        """Generate the graph's C++ and show it in the code pane - the hand-off
        for the cases the nodes cannot reach. From here it is a code effect."""
        fname = self.gp.compile(and_build=False)
        if fname:
            self.layout = "edit"; self.ui = True; self.request_layout()
            self.edit_open(fname)

    def edit_build(self):
        """Save, then compile on a worker; the result is applied on the main
        thread by poll_build(), because reloading the engine while a frame is
        being drawn from it is not something to do from another thread."""
        if self.building:
            return
        self.edit_save()
        self.building = True
        self.build_msg = "compiling..."
        dpg.set_value("edit_status", self.build_msg)
        dpg.delete_item("edit_errors", children_only=True)

        def work():
            import build as B
            from native.toolchain import build_engine
            import contextlib, io as _io
            buf = _io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    srcs = B.engine_sources([self.project.effect_path(f)
                                             for f in self.project.build_files(self.edit_file)])
                inc = [os.path.join(B.HERE, "shim"), os.path.join(B.ROOT, "usermods", "cube_fx"), B.GEN]
                rep = build_engine(srcs, inc, log=lambda *a: None)
            except Exception as e:
                rep = None
                self.build_q.put(("exception", str(e)))
                return
            self.build_q.put(("report", rep))
        threading.Thread(target=work, daemon=True).start()

    def poll_build(self):
        try:
            kind, payload = self.build_q.get_nowait()
        except queue.Empty:
            return
        self.building = False
        if kind == "exception":
            dpg.set_value("edit_status", f"build failed: {payload}")
            return
        rep = payload
        if not rep.ok:
            # Errors first; warnings only from the project's own files - a
            # warning inside a shared header is not the user's to fix.
            mine = set(self.project.effect_files())
            errs = [e for e in rep.error_lines()
                    if e[2].startswith("error") or os.path.basename(e[0]) in mine]
            errs.sort(key=lambda e: 0 if e[2].startswith("error") else 1)
            dpg.set_value("edit_status", f"{len(errs)} problem(s)")
            for path, line, msg in errs[:30]:
                fn = os.path.basename(path)
                mine_file = fn == self.edit_file
                row = dpg.add_selectable(label=f"{fn}:{line}  {msg}"[:140], parent="edit_errors",
                                         user_data=int(line) if mine_file else None,
                                         callback=lambda s, a, u: self.goto_line(u) if u else None)
                with dpg.theme() as th:
                    with dpg.theme_component(dpg.mvSelectable):
                        dpg.add_theme_color(dpg.mvThemeCol_Text,
                                            (235, 120, 110) if msg.startswith("error") else (200, 190, 120))
                dpg.bind_item_theme(row, th)
            if not errs and rep.link_output:
                dpg.add_text(rep.link_output[-600:], parent="edit_errors", color=(235, 120, 110), wrap=0)
            return
        # success: swap the engine, keep everything the user had
        want = self.project.effect_title(self.edit_file) if self.edit_file else self.project.selected
        self.eng.reload(rep.library)
        dpg.configure_item("fx_combo", items=self.eng.names)
        if want in self.eng.names:
            self.eng.select(self.eng.names.index(want))
        dpg.set_value("fx_combo", self.eng.names[self.eng.idx])
        self.rebuild_params()
        self.sync_palette_combo()
        dpg.set_value("edit_status", f"loaded {os.path.basename(rep.library)}  ({self.eng.count} effects)")

    def on_color(self, sender, val):
        r, g, b = (int(c * 255) if c <= 1.0 else int(c) for c in val[:3])
        self.seg_cols[int(dpg.get_item_user_data(sender))] = (r << 16) | (g << 8) | b
        self.eng.colors(*self.seg_cols)

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
        # Presenting (H) shows pictures only: the code and graph panes are
        # chrome too, so in those layouts the 3-D view stands alone.
        show_net = self.layout in ("both", "net")
        show_cube = self.layout in ("both", "cube", "edit", "graph")
        show_edit = self.layout == "edit" and self.ui
        show_graph = self.layout == "graph" and self.ui
        nview = (show_net + show_cube + show_edit + show_graph) if self.ui else (show_net + show_cube)
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
        # In the graph layout the 3-D view gives up room to the nodes: it is
        # a monitor there, not the subject.
        if self.layout == "graph":
            side = max(VIEW_MIN, min(side, 360))

        dpg.configure_item("net_win",  show=show_net)
        dpg.configure_item("cube_win", show=show_cube)
        dpg.configure_item("edit_win", show=show_edit)
        dpg.configure_item("graph_win", show=show_graph)
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
        for tag in ("net_cap", "cube_cap", "stat_txt", "hint1", "hint2",
                    "rec_btn", "shot_btn", "rec_msg"):
            dpg.configure_item(tag, show=self.ui)

        # The net is upscaled by a WHOLE number so the LED grid stays hard;
        # bilinear scaling of a 48-pixel image looks like a photograph of a cube
        # rather than a cube.
        self.net_scale = max(1, side // max(self.eng.cols, self.net_image().shape[0]))
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
            # Presenting placed the panes by hand; a pane once placed no longer
            # flows in its row, so it would sit where it was left, under
            # whatever now shares the row. Back to flowing before sizing.
            for tag in ("net_win", "cube_win", "edit_win", "graph_win", "side_win"):
                dpg.reset_pos(tag)
            for tag in ("net_win", "cube_win"):
                dpg.configure_item(tag, width=side + 22, height=pane_h + 34)
            dpg.configure_item("edit_win", width=side + 22, height=pane_h + 34)
            dpg.configure_item("code", width=side + 4, height=pane_h - 240)
            # the graph pane takes the room the logical view would - and more,
            # when the window is wide: nodes want space, the 3-D view does not
            gw = max(side + 22, vw - SIDE_W - side - 60) if self.layout == "graph" else side + 22
            dpg.configure_item("graph_win", width=gw, height=pane_h + 34)
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
            if show_net:
                dpg.configure_item("net_win", width=side, height=side)
                dpg.set_item_pos("net_win", [x0, y0])
                x0 += side + gap
            if show_cube:
                dpg.configure_item("cube_win", width=side, height=side)
                dpg.set_item_pos("cube_win", [x0, y0])

        # Only the visible views get textures. A hidden one would otherwise
        # allocate at full pane size and never be written to - 7.7 MB of
        # float32 for a net nobody is looking at. Switching back runs this
        # again, so the texture is there by the time anything draws into it.
        if show_net:
            self.remake_net_texture()
        if show_cube:
            self.remake_cube_texture()

    def remake_net_texture(self):
        img = self.net_image()
        w = img.shape[1] * self.net_scale
        h = img.shape[0] * self.net_scale
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
        if self.layout == "graph":
            self.gp.on_press()

    def on_mouse_release(self, sender, app_data):
        self._dragging = False
        if self.layout == "graph":
            self.gp.on_release()

    def on_right_click(self, sender, app_data):
        if self.layout == "graph":
            self.gp.open_menu()

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
        if any(dpg.does_item_exist(t) and dpg.is_item_active(t)
               for t in ("find_text", "replace_text", "project_name", "device_host") + self.META_FIELDS):
            return
        if self.layout == "graph" and self.gp.typing():
            if app_data == dpg.mvKey_Return and dpg.does_item_exist("graph_search") and dpg.is_item_active("graph_search"):
                self.gp._search_enter(None, dpg.get_value("graph_search"))
            elif app_data == dpg.mvKey_Escape:
                self.gp._hide_menus()
            return
        ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
        if ctrl and self.layout == "graph":
            if app_data == dpg.mvKey_Z:
                self.gp.undo()
            elif app_data == dpg.mvKey_Y:
                self.gp.redo()
            elif app_data == dpg.mvKey_C:
                self.gp.copy()
            elif app_data == dpg.mvKey_X:
                self.gp.cut()
            elif app_data == dpg.mvKey_V:
                self.gp.paste()
            return
        if ctrl:
            return
        if self.layout == "graph":
            shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
            step = 1 if shift else 10
            arrows = {dpg.mvKey_Left: (-step, 0), dpg.mvKey_Right: (step, 0),
                      dpg.mvKey_Up: (0, -step), dpg.mvKey_Down: (0, step)}
            if app_data in arrows:
                self.gp.nudge(*arrows[app_data]); return
            if app_data == dpg.mvKey_Home:
                self.gp.home(); return
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
        elif app_data == dpg.mvKey_C:
            self.layout = "both" if self.layout == "edit" else "edit"
            self.ui = True
            self.request_layout()
        elif app_data == dpg.mvKey_G:
            self.layout = "both" if self.layout == "graph" else "graph"
            self.ui = True
            self.request_layout()
        elif app_data == dpg.mvKey_Delete and self.layout == "graph":
            self.gp.delete_selected()

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
        big = img = None
        if self.layout in ("both", "net"):
            big = net.repeat(self.net_scale, 0).repeat(self.net_scale, 1)
            dpg.set_value("net_tex", self._rgba("net", big))
        if self.layout in ("both", "cube", "edit", "graph"):
            img = self.view_image(net, self.cube_px)
            dpg.set_value("cube_tex", self._rgba("cube", img))
        # Records whatever is being SHOWN, so Q, E and W frame the clip too.
        self.rec_frame(big, img)
        if self.rec_msg:
            dpg.set_value("rec_msg", self.rec_msg)

        raw = self.eng.rgb()
        s = stats(raw, self.eng.lit_mask(flat=bool(self.eng.fx.get("o3"))))
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
    dpg.create_viewport(title="WLED Effect Studio", width=1280, height=800)

    with dpg.handler_registry():
        dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, callback=app.on_drag)
        # click = once on press; down = every frame while held. The
        # difference is the whole bug this replaced.
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Left, callback=app.on_mouse_click)
        dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=app.on_mouse_release)
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Right, callback=app.on_right_click)
        dpg.add_mouse_wheel_handler(callback=app.on_wheel)
        dpg.add_key_press_handler(callback=app.on_key)

    with dpg.window(tag="root"):
        with dpg.group(horizontal=True):
            with dpg.child_window(tag="net_win", width=420, height=470):
                dpg.add_text("Logical view - what the effect draws", tag="net_cap", color=(139, 147, 163))
            with dpg.child_window(tag="edit_win", width=420, height=470, show=False):
                with dpg.group(horizontal=True):
                    dpg.add_combo(app.project.effect_files(), tag="edit_file", width=180,
                                  default_value=app.edit_file or "",
                                  callback=lambda s, v: (app.edit_open(v), app.ensure_built()))
                    dpg.add_button(label="save", callback=lambda: app.edit_save())
                    dpg.add_button(label="compile + reload", callback=lambda: app.edit_build())
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="new_name", hint="new / renamed effect name", width=180,
                                       on_enter=True, callback=lambda s, v: app.edit_new())
                    dpg.add_button(label="new", callback=lambda: app.edit_new())
                    dpg.add_button(label="rename", callback=lambda: app.edit_rename())
                    dpg.add_button(label="import to list", tag="edit_import",
                                   callback=lambda: app.toggle_import(app.edit_file))
                with dpg.group(horizontal=True):
                    dpg.add_button(label="open in editor", callback=lambda: app.open_external())
                    dpg.add_checkbox(label="watch: rebuild when saved outside", tag="edit_watch", default_value=False)
                    dpg.add_button(label="export", callback=lambda: dpg.set_value(
                        "edit_status", "exported to " + app.project.export()))
                dpg.add_text("", tag="edit_status", color=(139, 147, 163))
                dpg.add_input_text(tag="code", multiline=True, width=400, height=300,
                                   tab_input=True, callback=app.on_code_edit)
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="find_text", hint="find", width=130, on_enter=True,
                                       callback=lambda: app.find())
                    dpg.add_button(label="find", callback=lambda: app.find())
                    dpg.add_input_text(tag="replace_text", hint="replace with", width=130)
                    dpg.add_button(label="replace all", callback=lambda: app.replace_all())
                with dpg.collapsing_header(label="Metadata - name, labels, palette, flags, defaults", default_open=False):
                    dpg.add_input_text(tag="meta_name", label="name", width=220)
                    dpg.add_input_text(tag="meta_labels", label="slider labels (8, comma)", width=220)
                    dpg.add_input_text(tag="meta_colours", label="colour labels (3, comma)", width=220)
                    dpg.add_input_text(tag="meta_flags", label="flags: 1 2 12 + v/f", width=220)
                    dpg.add_input_text(tag="meta_defaults", label="defaults sx=,ix=,c1=,pal=", width=220)
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="read from file", callback=lambda: app.meta_read())
                        dpg.add_button(label="apply to file", callback=lambda: app.meta_write())
                with dpg.collapsing_header(label="API reference - click copies, Ctrl+V pastes", default_open=False):
                    for group, items in API:
                        with dpg.tree_node(label=group):
                            for label, snippet, doc in items:
                                dpg.add_selectable(label=f"{label:34s} {doc}"[:110], user_data=(snippet, label),
                                                   callback=lambda s, a, u: app.api_pick(*u))
                dpg.add_group(tag="edit_errors")
            with dpg.child_window(tag="graph_win", width=420, height=470, show=False):
                build_panel(app, app.gp)
            with dpg.child_window(tag="cube_win", width=420, height=470):
                dpg.add_text("3-D - drag to rotate, wheel to zoom",
                             tag="cube_cap", color=(139, 147, 163))
            with dpg.child_window(tag="side_win", width=SIDE_W - 10, height=470):
                with dpg.group(horizontal=True):
                    dpg.add_combo(list_projects(), label="project", tag="project_combo", width=200,
                                  default_value=os.path.basename(app.project.path),
                                  callback=lambda s, v: app.switch_project(v))
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="project_name", hint="new project name or a folder", width=200,
                                       on_enter=True, callback=lambda s, v: app.new_project(v))
                    dpg.add_button(label="new / open", callback=lambda: app.new_project(dpg.get_value("project_name")))
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="device_host", hint="device address, e.g. 192.168.1.50", width=200,
                                       default_value=app.project.options.get("device", ""))
                    dpg.add_button(label="send ledmap", callback=lambda: app.send_ledmap())
                dpg.add_separator()
                dpg.add_combo(app.eng.names, label="effect", tag="fx_combo",
                              default_value=app.eng.names[app.eng.idx], width=200,
                              callback=app.on_effect)
                dpg.add_combo([p[0] for p in PALETTES], label="palette",
                              default_value=app.palette_name_for(app.eng.pal),
                              width=200, tag="pal_combo",
                              callback=app.on_palette)
                # Only meaningful while a CubeFX audio palette is selected -
                # it is where those four take their colours from.
                dpg.add_combo([p[0] for p in PALETTES if p[1] < 201],
                              label="pal source", width=200, tag="pal_src",
                              default_value=app.palette_name_for(app.eng.pal_source),
                              callback=app.on_pal_source)
                dpg.add_separator()
                dpg.add_text("Geometry")
                dpg.add_combo(list(KINDS), label="shape", tag="geom_kind", width=120,
                              default_value=app.project.geometry.kind, callback=app.on_geom_kind)
                dpg.add_group(tag="geom_fields")
                dpg.add_combo(["strip", "bars", "arcs", "corner"], label="1-D effects as",
                              tag="map1d2d", width=100, default_value="strip",
                              show=app.project.geometry.is2d, callback=app.on_map1d2d)
                dpg.add_text(app.project.geometry.describe(), tag="geom_desc",
                             color=(139, 147, 163), wrap=300)
                with dpg.file_dialog(directory_selector=False, show=False, tag="xyz_dialog",
                                     width=620, height=420, callback=app.on_xyz_file,
                                     cancel_callback=lambda s, a: dpg.set_value("geom_kind", app.project.geometry.kind)):
                    dpg.add_file_extension(".csv", color=(120, 200, 120))
                    dpg.add_file_extension(".txt", color=(120, 200, 120))
                    dpg.add_file_extension(".json", color=(120, 200, 120))
                    dpg.add_file_extension(".*")
                dpg.add_separator()
                # Several effects paint with SEGCOLOR(0), and the CubeFX audio
                # palettes read all THREE when their source is one of WLED's
                # segment-colour palettes - "* Color 1" takes the primary,
                # "* Colors 1&2" the first two, "* Color Gradient" and
                # "* Colors Only" all three. Without these the only way to
                # choose the colours those palettes draw from was to edit them
                # in code. WLED's DEFAULT_COLOR is amber; 2 and 3 start black,
                # as they do on the device.
                for _ci, (_lbl, _rgb) in enumerate((("primary",   (255, 160, 0, 255)),
                                                    ("secondary", (0, 0, 0, 255)),
                                                    ("tertiary",  (0, 0, 0, 255)))):
                    dpg.add_color_edit(_rgb, label=_lbl, width=170, no_alpha=True,
                                       user_data=_ci, callback=app.on_color)
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
                try:
                    from native.audio import list_inputs
                    _devs = ["system output"] + [n for _, n in list_inputs()]
                except Exception:
                    _devs = ["system output"]
                dpg.add_combo(_devs, label="source", tag="live_dev", width=200,
                              default_value=_devs[0])
                dpg.add_button(label="use live audio", tag="live_btn",
                               callback=lambda: app.toggle_live())
                dpg.add_group(tag="gain_row")
                app.pair("gain_row", "live_gain", "live gain", 3.0, 0.2, 12.0,
                         lambda v: setattr(app.live, "gain", float(v)) if app.live else None,
                         is_float=True)
                dpg.add_progress_bar(tag="lvl_bar", default_value=0.0, width=280)
                dpg.add_text("", tag="live_msg", wrap=300)
        with dpg.group(horizontal=True):
            dpg.add_button(label="record 15 s GIF", tag="rec_btn",
                           callback=lambda: app.start_rec(15.0))
            dpg.add_button(label="screenshot", tag="shot_btn", callback=lambda: setattr(app, "shot_req", True))
            dpg.add_text("", tag="rec_msg", color=(139, 147, 163))
        dpg.add_text("", tag="stat_txt")
        dpg.add_text("Q net    E 3-D    W both    C code    G graph    H hide UI", tag="hint1",
                     color=(130, 140, 155))
        dpg.add_text("space = play/pause    F11 = fullscreen window", tag="hint2",
                     color=(130, 140, 155))

    app._themes['normal'] = apply_theme()
    app._themes['present'] = present_theme()
    app.rebuild_params()
    app.rebuild_geom_fields()
    files = app.project.effect_files()
    if files:
        app.edit_open(files[0])
    gfiles = app.gp.files()
    if gfiles:
        app.gp.open(gfiles[0])
    dpg.set_primary_window("root", True)
    # Callbacks are taken off Dear PyGui's own schedule and run at the top of
    # each pass of the loop below, before the frame is drawn. Otherwise they
    # run inside render_dearpygui_frame() - a callback that changes the
    # geometry while draw() is halfway through reading the engine gave a
    # mismatched mask once - and a widget deleted from a callback can be the
    # very one the renderer is walking.
    dpg.configure_app(manual_callback_management=True)
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
CMD_FILE = os.path.join(SHOT_DIR, "command.json")


def service_command(app):
    """Drive the running app from outside, the same way a capture is asked
    for: a JSON file of commands, applied on the next tick and removed.

        [{"geometry": {"kind": "sphere", "params": {"w": 32, "h": 16}}},
         {"effect": "Rainbow"}, {"layout": "edit"}, {"open": "my_effect.cpp"},
         {"code": "...whole file..."}, {"build": true}, {"param": ["sx", 200]}]

    It exists so the app can be tested without a hand on the mouse - every
    panel here was checked by writing this file and reading the capture.
    """
    try:
        if not os.path.exists(CMD_FILE):
            return
        import json
        cmds = json.load(open(CMD_FILE, encoding="utf-8"))
        os.remove(CMD_FILE)
    except Exception as e:
        print(f"command file: {e}")
        try:
            os.remove(CMD_FILE)
        except OSError:
            pass
        return
    for c in cmds if isinstance(cmds, list) else [cmds]:
        try:
            if "geometry" in c:
                g = Geometry.from_json(c["geometry"])
                app.apply_geometry(g)
                dpg.set_value("geom_kind", g.kind)
                app.rebuild_geom_fields()
            if "effect" in c:
                app.on_effect(None, c["effect"])
                dpg.set_value("fx_combo", c["effect"])
            if "viewport" in c:                         # test hook: resize the window (fires the resize callback)
                dpg.set_viewport_width(int(c["viewport"][0])); dpg.set_viewport_height(int(c["viewport"][1]))
            if "ui" in c:                               # test hook: H, the presentation toggle
                app.ui = bool(c["ui"]); app.request_layout()
            if "layout" in c:
                app.layout = c["layout"]; app.ui = bool(c.get("with_ui", True)); app.request_layout()
            if "open" in c:
                app.edit_open(c["open"])
            if "new" in c:
                dpg.set_value("new_name", c["new"]); app.edit_new()
            if "code" in c:
                dpg.set_value("code", c["code"]); app.edit_dirty = True
            if c.get("build"):
                app.edit_build()
            if "param" in c:
                k, v = c["param"]
                app.eng.fx[k] = int(v); app.eng.push()
                app.rebuild_params()
            if "map1d2d" in c:
                app.on_map1d2d(None, c["map1d2d"]); dpg.set_value("map1d2d", c["map1d2d"])
            if "view" in c:
                app.yaw, app.pitch, app.dist = c["view"]
            if "graph_open" in c:
                app.gp.open(c["graph_open"])
            if "graph_new" in c:
                app.gp.new(c["graph_new"])
            if "graph_add" in c:
                app.gp.add_node(c["graph_add"])
            if "graph_link" in c:
                a, out, b, inp = c["graph_link"]
                app.gp.snapshot(); app.gp.graph.link(a, out, b, inp); app.gp.rebuild()
            if "graph_param" in c:
                nid, name, val = c["graph_param"]
                app.gp.snapshot(); app.gp.graph.nodes[int(nid)]["params"][name] = val; app.gp.rebuild()
            if c.get("graph_build"):
                app.gp.compile()
            if "import" in c:                           # test hook: toggle the current file's import
                app.toggle_import(c["import"] or app.edit_file)
            if "rename" in c:
                dpg.set_value("new_name", c["rename"]); app.edit_rename()
            if "graph_rename" in c:
                app.gp.rename(c["graph_rename"])
            if "project" in c:
                app.new_project(c["project"])
            if c.get("screenshot"):
                app.shot_req = True
            if "graph_export" in c:
                app.gp.export_bundle()
            if "graph_import" in c:
                app.gp.import_bundle(c["graph_import"])
            if "meta" in c:
                for k, v in c["meta"].items():
                    dpg.set_value(k, v)
                app.meta_write()
            if "find" in c:
                dpg.set_value("find_text", c["find"]); app.find()
            if "replace" in c:
                dpg.set_value("replace_text", c["replace"]); app.replace_all()
            if "graph_preview" in c:
                if c["graph_preview"]:
                    nid, name = c["graph_preview"]; app.gp.preview_pin(int(nid), name)
                else:
                    app.gp.stop_preview()
            if "graph_collapse" in c:
                app.gp._collapse(int(c["graph_collapse"]))
            if "graph_colour" in c:
                nid, col = c["graph_colour"]; app.gp._set_colour(int(nid), col)
            if "graph_insert" in c:
                nid, name, t = c["graph_insert"]; app.gp._insert_before(int(nid), name, t)
            if "graph_move" in c:                       # test hook: move a node (as a drag would)
                nid, x, y = c["graph_move"]; dpg.set_item_pos(f"gnode_{int(nid)}", [x, y])
            if "graph_undo" in c:
                app.gp.undo()
            if "graph_redo" in c:
                app.gp.redo()
            if "graph_copy" in c:
                sel = [int(x) for x in c["graph_copy"]]
                import dearpygui.dearpygui as _d
                _orig = _d.get_selected_nodes
                _d.get_selected_nodes = lambda ed: [f"gnode_{i}" for i in sel if _d.does_item_exist(f"gnode_{i}")]
                try:
                    app.gp.copy()
                finally:
                    _d.get_selected_nodes = _orig
            if "graph_paste" in c:
                app.gp.paste()
            if "graph_auto" in c:
                app.gp.set_auto(c["graph_auto"]); dpg.set_value("graph_auto", bool(c["graph_auto"]))
            if "graph_menu" in c:                       # test hook: the right-click menu at x, y
                app.gp._menu_pos = tuple(c["graph_menu"])
                app.gp._pending = None
                app.gp.show_add_menu(tuple(c["graph_menu"]), focus=False)   # a focused box keeps its own text
            if "graph_search" in c:                     # test hook: type in the add menu's search box
                dpg.set_value("graph_search", c["graph_search"]); app.gp._search(None, c["graph_search"])
            if c.get("graph_search_enter"):
                app.gp._search_enter(None, dpg.get_value("graph_search"))
            if "graph_drop" in c:                       # test hook: a wire from (node, out) dropped at x, y
                nid, out, x, y = c["graph_drop"]
                t = app.gp._ptype.get(app.gp._pins[(int(nid), "out", out)])
                app.gp._menu_pos = (x, y); app.gp._pending = (int(nid), out, t)
                app.gp.show_add_menu((x + 40, y + 120), only=app.gp._consumers(t, limit=60))
            if c.get("graph_menu_hide"):
                dpg.configure_item("graph_menu", show=False); dpg.configure_item("graph_ctx", show=False)
            if "graph_ctx" in c:                        # test hook: context menu for a pin or node
                kind, nid, name, x, y = c["graph_ctx"]
                app.gp._ctx = (kind, int(nid), name); app.gp._fill_ctx_menu()
                dpg.configure_item("graph_ctx", show=True); dpg.set_item_pos("graph_ctx", [x, y])
            if "graph_select" in c:                     # test hook: select nodes by id
                app.gp._test_selection = [int(x) for x in c["graph_select"]]
            if "graph_fold" in c:
                sel = getattr(app.gp, "_test_selection", [])
                import dearpygui.dearpygui as _d
                _orig = _d.get_selected_nodes
                _d.get_selected_nodes = lambda ed: [f"gnode_{i}" for i in sel if _d.does_item_exist(f"gnode_{i}")]
                try:
                    app.gp.make_sub_from_selection(c["graph_fold"])
                finally:
                    _d.get_selected_nodes = _orig
            if "graph_enter" in c:
                app.gp.enter_sub(int(c["graph_enter"]))
            if c.get("graph_back"):
                app.gp.back()
            if "graph_wire" in c:                       # test hook: colour the wire into (node, input)
                nid, name, col = c["graph_wire"]
                app.gp._set_wire([(int(nid), name)], tuple(col) if col else None)
            if c.get("graph_release"):
                app.gp.on_release()
            if "graph_press" in c:                      # test hook: a drag from an output pin type
                app.gp._drag_type = c["graph_press"]
                th = app.gp.themes()
                from native.graph_ui import compatible
                for (nid, kind, name), tag in app.gp._pins.items():
                    if kind == "in":
                        t = app.gp._ptype.get(tag)
                        dpg.bind_item_theme(tag, th.pin[t] if compatible(app.gp._drag_type, t) else th.grey[t])
        except Exception as e:
            print(f"command {c}: {e}")

# Recordings go in the REPO, not in the temp directory the IPC lives in. The two
# are different kinds of file: capture.request and crash.txt are scratch that
# nobody minds losing, whereas a recording is a thing you made and meant to
# keep, and Windows is entitled to empty %TEMP% whenever it likes. Gitignored,
# so keeping them here does not mean committing them.
GIF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "captures")


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
    os.makedirs(GIF_DIR, exist_ok=True)
    print(f"if a frame throws, the traceback lands in {os.path.join(SHOT_DIR, 'crash.txt')}")
    print(f"frame capture: create {SHOT_REQ} to get a PNG at {SHOT_PNG}")
    print(f"remote control: write a JSON list of commands to {CMD_FILE}")
    try:
        while dpg.is_dearpygui_running():
            try:
                jobs = dpg.get_callback_queue()
                if jobs:
                    dpg.run_callbacks(jobs)
            except Exception:
                import traceback
                traceback.print_exc()
            if app._need_layout:
                app._need_layout = False
                app.relayout()
            try:
                app.poll_build()
                app.gp.poll()
                app.poll_watch()
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
            service_command(app)
    finally:
        app.stop_live()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
