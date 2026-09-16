"""The window chrome: the menu bar, the toolbar and the small dialogs.

Every action the app has is reachable from a menu, with its shortcut beside
it, and the ones used all day are on the toolbar as icons. The panes keep
only what is about the thing in them (which file, find/replace, the graph's
status line); everything that used to be a button in a pane lives here.

    build_menus(app)      # inside the root window, first
    build_toolbar(app)    # a row of icon buttons under the menus
    build_dialogs(app)    # the name box, device, editor command, shortcuts, about
    refresh(app)          # menu checks, toolbar tints and labels, the file lists
    poll(app)             # per frame: refresh() when something it shows changed
"""
import os
import sys
import subprocess
import dearpygui.dearpygui as dpg

from native.icons import texture
from native.keys import ACTIONS, FIXED
from native import glow

TEXT   = (215, 219, 227, 255)
DIM    = (139, 147, 163, 255)
ACCENT = (90, 169, 230, 255)
AMBER  = (255, 184, 70, 255)
RED    = (255, 96, 96, 255)
GREEN  = (110, 220, 150, 255)
ICON   = 16

LAYOUTS = (("net", "Logical net", "view_net"), ("cube", "3-D view", "view_cube"), ("both", "Net and 3-D", "view_both"),
           ("edit", "Code", "pane_code"), ("graph", "Graph", "pane_graph"))

# --- the menu bar -------------------------------------------------------------------
def _mi(app, label, action=None, **kw):
    """A menu item; with an action, its shortcut shows the keymap's key and
    the item is tagged so a rebind updates it."""
    if action:
        kw.setdefault("tag", f"mi_{action}")
        kw["shortcut"] = app.keys.label(action)
    return dpg.add_menu_item(label=label, **kw)


def build_menus(app):
    with dpg.menu_bar(tag="menubar"):
        with dpg.menu(label="File"):
            _mi(app, "New graph effect...", "new", callback=lambda: app.new_effect("graph"))
            dpg.add_menu_item(label="New code effect...", callback=lambda: app.new_effect("code"))
            with dpg.menu(label="Open graph", tag="menu_open_graph"):
                pass
            with dpg.menu(label="Open code effect", tag="menu_open_code"):
                pass
            _mi(app, "Save", "save", callback=lambda: app.save_current())
            _mi(app, "Rename...", "rename", callback=lambda: app.rename_current())
            dpg.add_separator()
            _mi(app, "Add to the effects list", "import", tag="menu_import", callback=lambda: app.toggle_import_current())
            dpg.add_menu_item(label="Open graph as code", callback=lambda: app.open_graph_code())
            dpg.add_separator()
            with dpg.menu(label="Project"):
                dpg.add_menu_item(label="New project...", callback=lambda: ask(
                    app, "New project", "a name, or a folder path", "", lambda v: app.new_project(v)))
                with dpg.menu(label="Open", tag="menu_open_project"):
                    pass
                dpg.add_menu_item(label="Open folder...", callback=lambda: dpg.show_item("project_dialog"))
                dpg.add_separator()
                dpg.add_menu_item(label="Device address...", callback=lambda: show_device(app))
                dpg.add_menu_item(label="Send ledmap to device", callback=lambda: app.send_ledmap())
                dpg.add_menu_item(label="Export usermod (folder + zip)", callback=lambda: app.export_usermod())
            dpg.add_menu_item(label="Import graph bundle...", callback=lambda: dpg.show_item("graph_import_dialog"))
            dpg.add_menu_item(label="Export graph bundle", callback=lambda: app.gp.export_bundle())
            dpg.add_separator()
            _mi(app, "Screenshot of the 3-D view", "screenshot", callback=lambda: setattr(app, "shot_req", True))
            _mi(app, "Record 15 s GIF", "record", callback=lambda: app.start_rec(15.0))
            dpg.add_separator()
            dpg.add_menu_item(label="Quit", callback=lambda: dpg.stop_dearpygui())
        with dpg.menu(label="Edit"):
            _mi(app, "Undo", "undo", callback=lambda: app.gp.undo())
            _mi(app, "Redo", "redo", callback=lambda: app.gp.redo())
            dpg.add_separator()
            _mi(app, "Cut", "cut", callback=lambda: app.gp.cut())
            _mi(app, "Copy", "copy", callback=lambda: app.gp.copy())
            _mi(app, "Paste", "paste", callback=lambda: app.gp.paste())
            _mi(app, "Duplicate with inputs", "duplicate", callback=lambda: app.duplicate_selected())
            _mi(app, "Delete", "delete", callback=lambda: app.gp.delete_selected())
            dpg.add_separator()
            _mi(app, "Connect selected", "connect", callback=lambda: app.gp.connect_selected())
            _mi(app, "Mute", "mute", callback=lambda: app.gp.toggle_selected("muted"))
            _mi(app, "Collapse", "collapse", callback=lambda: app.gp.toggle_selected("collapsed"))
            _mi(app, "Hide unwired pins", "hide_pins", callback=lambda: app.gp.toggle_selected("hide_pins"))
            _mi(app, "Fold into sub-graph...", "fold", callback=lambda: ask(
                app, "Sub-graph", "a name for the new node type", "", lambda v: app.gp.make_sub_from_selection(v)))
            _mi(app, "Arrange", "arrange", callback=lambda: app.gp.arrange())
            dpg.add_separator()
            _mi(app, "Find / replace in code", "find", callback=lambda: app.focus_find())
            _mi(app, "Open code in external editor", "external", callback=lambda: app.open_external())
        with dpg.menu(label="View"):
            for key, label, act in LAYOUTS:
                _mi(app, label, act, check=True, tag=f"menu_view_{key}",
                    callback=lambda s, a, u: app.show_layout(u), user_data=key)
            dpg.add_separator()
            _mi(app, "Presentation (hide controls)", "presentation", check=True, tag="menu_present",
                callback=lambda: app.toggle_ui())
            dpg.add_menu_item(label="Side panel", check=True, default_value=True, tag="menu_side",
                              callback=lambda: app.toggle_side())
            _mi(app, "Fullscreen", "fullscreen", callback=lambda: dpg.toggle_viewport_fullscreen())
            dpg.add_separator()
            _mi(app, "Zoom in", "zoom_in", callback=lambda: app.gp.zoom_step(1))
            _mi(app, "Zoom out", "zoom_out", callback=lambda: app.gp.zoom_step(-1))
            _mi(app, "Zoom 100%", "zoom_reset", callback=lambda: app.gp.set_zoom(1.0))
            _mi(app, "Frame all", "frame_all", callback=lambda: app.gp.home())
            dpg.add_separator()
            dpg.add_menu_item(label="Minimap", check=True, default_value=True, tag="menu_minimap",
                              callback=lambda s, a: dpg.configure_item("node_editor", minimap=bool(a)))
            dpg.add_menu_item(label="Reset pane sizes", callback=lambda: app.reset_layout())
        with dpg.menu(label="Node"):
            _mi(app, "Add node...  (or right-click the graph)", "add_node", callback=lambda: app.search_nodes())
            with dpg.menu(label="Add", tag="menu_add"):
                pass
            dpg.add_separator()
            _mi(app, "Enter sub-graph", "enter_sub", callback=lambda: app.enter_selected_sub())
            dpg.add_menu_item(label="Back to parent graph", callback=lambda: app.gp.back())
            dpg.add_separator()
            _mi(app, "Stop pin preview", "stop_preview", callback=lambda: app.gp.set_preview(None))
        with dpg.menu(label="Playback"):
            _mi(app, "Play / pause", "play_pause", callback=lambda: app.toggle_play())
            _mi(app, "Step one frame", "step", callback=lambda: app.step_once())
            _mi(app, "Restart effect", "restart", callback=lambda: app.eng.select(app.eng.idx))
            dpg.add_separator()
            _mi(app, "Compile + reload", "build", callback=lambda: app.build_current())
            _mi(app, "Live: rebuild the graph as it changes", "live", check=True, tag="menu_live",
                              default_value=app.gp.auto, callback=lambda s, a: app.gp.set_auto(bool(a)))
            dpg.add_menu_item(label="Watch: rebuild when the code is saved outside", check=True, tag="edit_watch",
                              default_value=False)
        with dpg.menu(label="Settings"):
            dpg.add_menu_item(label="Keyboard shortcuts...", callback=lambda: show_keys(app))
            dpg.add_menu_item(label="Selection frames...", callback=lambda: show_frames(app))
            dpg.add_menu_item(label="Device address...", callback=lambda: show_device(app))
            dpg.add_menu_item(label="External editor command...", callback=lambda: show_editor(app))
            dpg.add_separator()
            dpg.add_menu_item(label="Open the project folder", callback=lambda: app.reveal(app.project.path))
            dpg.add_menu_item(label="Open the build folder", callback=lambda: app.reveal(app.build_dir()))
        with dpg.menu(label="Help"):
            _mi(app, "Keyboard shortcuts", "shortcuts", callback=lambda: show_keys(app))
            dpg.add_menu_item(label="Node reference (NODES.md)", callback=lambda: app.reveal(app.doc_path("NODES.md")))
            dpg.add_menu_item(label="Studio guide (STUDIO.md)", callback=lambda: app.reveal(app.doc_path("STUDIO.md")))
            dpg.add_menu_item(label="Effect API reference", callback=lambda: app.show_api())
            dpg.add_separator()
            dpg.add_menu_item(label="About", callback=lambda: dpg.show_item("about_win"))


# --- the toolbar --------------------------------------------------------------------
def _sep():
    dpg.add_spacer(width=1)
    with dpg.drawlist(width=1, height=22):
        dpg.draw_line((0, 3), (0, 19), color=(52, 58, 70, 255))
    dpg.add_spacer(width=1)


def _btn(app, icon, tip, cb, tag=None, action=None):
    """An icon button with a tooltip; with an action, the tooltip carries
    its key and follows a rebind (the text is tagged by the action)."""
    kw = {"tag": tag} if tag else {}
    b = dpg.add_image_button(texture(icon, ICON), width=ICON, height=ICON, tint_color=TEXT,
                             frame_padding=3, callback=cb, **kw)
    with dpg.tooltip(b):
        tt = f"tbtip_{action}"
        if action and not dpg.does_item_exist(tt):
            dpg.add_text("", tag=tt)
            app._tips[action] = tip
        else:
            dpg.add_text(tip + ("  " + app.keys.label(action) if action else ""))
    return b


def build_toolbar(app):
    app._tips = {"zoom_reset": "Zoom 100%"}
    with dpg.group(horizontal=True, tag="toolbar"):
        _btn(app, "new", "New effect", lambda: app.new_effect(), action="new")
        _btn(app, "open", "Open a graph or a code effect", lambda: show_open(app), tag="tb_open", action="open")
        _btn(app, "save", "Save", lambda: app.save_current(), action="save")
        _sep()
        _btn(app, "build", "Compile + reload", lambda: app.build_current(), tag="tb_build", action="build")
        _btn(app, "live", "Live: rebuild the graph as it changes", lambda: app.gp.set_auto(not app.gp.auto), tag="tb_live", action="live")
        _sep()
        _btn(app, "undo", "Undo", lambda: app.gp.undo(), action="undo")
        _btn(app, "redo", "Redo", lambda: app.gp.redo(), action="redo")
        _sep()
        _btn(app, "play", "Play", lambda: app.toggle_play(), tag="tb_play", action="play_pause")
        _btn(app, "pause", "Pause", lambda: app.toggle_play(), tag="tb_pause", action="play_pause")
        _btn(app, "step", "Step one frame", lambda: app.step_once(), action="step")
        _btn(app, "restart", "Restart the effect", lambda: app.eng.select(app.eng.idx), action="restart")
        _sep()
        for key, label, act in LAYOUTS:
            _btn(app, "code" if key == "edit" else key, label, lambda s, a, u: app.show_layout(u), tag=f"tb_view_{key}", action=act)
            dpg.configure_item(f"tb_view_{key}", user_data=key)
        _sep()
        _btn(app, "zoom_out", "Zoom out", lambda: app.gp.zoom_step(-1), action="zoom_out")
        z = dpg.add_button(label="100%", tag="tb_zoom", width=46, callback=lambda: app.gp.set_zoom(1.0))
        with dpg.tooltip(z):
            dpg.add_text("", tag="tbtip_zoom_reset")
        _btn(app, "zoom_in", "Zoom in", lambda: app.gp.zoom_step(1), action="zoom_in")
        _btn(app, "frame_all", "Frame the whole graph", lambda: app.gp.home(), action="frame_all")
        _sep()
        _btn(app, "search", "Add a node (or right-click the graph)", lambda: app.search_nodes(), action="add_node")
        _btn(app, "trash", "Delete the selection", lambda: app.gp.delete_selected(), action="delete")
        _btn(app, "arrange", "Arrange the graph", lambda: app.gp.arrange(), action="arrange")
        _btn(app, "fold", "Fold the selection into a sub-graph", lambda: app.run_action("fold"), action="fold")
        _sep()
        _btn(app, "external", "Open the code in an external editor", lambda: app.open_external(), action="external")
        _btn(app, "camera", "Screenshot of the 3-D view", lambda: setattr(app, "shot_req", True), tag="shot_btn", action="screenshot")
        _btn(app, "record", "Record a 15 s GIF", lambda: app.start_rec(15.0), tag="rec_btn", action="record")
        dpg.add_text("", tag="rec_msg", color=DIM)
    refresh_keys(app)


# --- dialogs ------------------------------------------------------------------------
def build_dialogs(app):
    with dpg.window(tag="name_dialog", label="Name", modal=True, show=False, no_resize=True, width=360, height=118, no_collapse=True):
        dpg.add_text("", tag="name_prompt", color=DIM)
        dpg.add_input_text(tag="name_input", width=-1, on_enter=True, callback=lambda: _name_ok(app))
        with dpg.group(horizontal=True):
            dpg.add_button(label="OK", width=80, callback=lambda: _name_ok(app))
            dpg.add_button(label="Cancel", width=80, callback=lambda: dpg.hide_item("name_dialog"))
    with dpg.window(tag="device_dialog", label="Device", modal=True, show=False, no_resize=True, width=380, height=140, no_collapse=True):
        dpg.add_text("the WLED device's address, for sending the ledmap", color=DIM)
        dpg.add_input_text(tag="device_host", hint="e.g. 192.168.1.50", width=-1,
                           default_value=app.project.options.get("device", ""))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Save", width=80, callback=lambda: (app.save_device(), dpg.hide_item("device_dialog")))
            dpg.add_button(label="Send ledmap", callback=lambda: (app.send_ledmap(), dpg.hide_item("device_dialog")))
            dpg.add_button(label="Cancel", width=80, callback=lambda: dpg.hide_item("device_dialog"))
    with dpg.window(tag="editor_dialog", label="External editor", modal=True, show=False, no_resize=True, width=460, height=150, no_collapse=True):
        dpg.add_text("the command that opens a file at a line; {file} and {line} are filled in.\n"
                     "Empty uses VS Code if it is on the path.", color=DIM)
        dpg.add_input_text(tag="editor_cmd", hint="code -g {file}:{line}", width=-1)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Save", width=80, callback=lambda: (app.save_editor_cmd(dpg.get_value("editor_cmd")),
                                                                   dpg.hide_item("editor_dialog")))
            dpg.add_button(label="Cancel", width=80, callback=lambda: dpg.hide_item("editor_dialog"))
    with dpg.file_dialog(directory_selector=True, show=False, tag="project_dialog", width=620, height=420,
                         callback=lambda s, a: app.new_project(a.get("file_path_name", ""))):
        pass
    with dpg.window(tag="keys_win", label="Keyboard shortcuts", show=False, width=640, height=600, no_collapse=True,
                    on_close=lambda: setattr(app, "_capture", None)):
        dpg.add_text("Click a key to change it, then press the new one (Escape keeps the old). "
                     "A key taken from another action leaves that one unbound.", color=DIM, wrap=600)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Reset all to defaults", callback=lambda: (app.keys.reset(), refresh_keys(app)))
        with dpg.child_window(tag="keys_rows", height=-1, border=False):
            pass
    with dpg.window(tag="about_win", label="About", show=False, width=460, height=200, no_collapse=True):
        dpg.add_text("WLED Effect Studio")
        dpg.add_text("Node graphs and C++ compiled into WLED effects, previewed on a\n"
                     "simulated cube, sphere, matrix or strip with synthetic or live audio.", color=DIM)
        dpg.add_spacer(height=6)
        dpg.add_text("", tag="about_paths", color=DIM)
    with dpg.window(tag="open_menu", show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        pass
    build_frames_dialog(app)


def ask(app, title, prompt, default, cb):
    """A one-line name box; cb(value) on OK or Enter."""
    app._ask_cb = cb
    dpg.configure_item("name_dialog", label=title)
    dpg.set_value("name_prompt", prompt)
    dpg.set_value("name_input", default or "")
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    dpg.configure_item("name_dialog", pos=(max(0, vw // 2 - 180), max(0, vh // 3)))
    dpg.show_item("name_dialog")
    dpg.focus_item("name_input")


def _name_ok(app):
    v = dpg.get_value("name_input")
    dpg.hide_item("name_dialog")
    cb, app._ask_cb = getattr(app, "_ask_cb", None), None
    if cb:
        cb(v)


def show_keys(app):
    refresh_keys(app)
    _centre("keys_win", 640, 600)
    dpg.show_item("keys_win")


def refresh_keys(app):
    """The keymap dialog's rows, and every menu item's shortcut label."""
    for action, _, _, _ in ACTIONS:
        tag = f"mi_{action}"
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, shortcut=app.keys.label(action))
        tt = f"tbtip_{action}"
        if dpg.does_item_exist(tt):
            b = app.keys.label(action)
            dpg.set_value(tt, app._tips.get(action, "") + (f"  {b}" if b else ""))
    if not dpg.does_item_exist("keys_rows"):
        return
    dpg.delete_item("keys_rows", children_only=True)
    last = None
    for action, label, default, ctx in ACTIONS:
        if ctx != last:
            dpg.add_text("anywhere" if ctx == "global" else "in the graph", parent="keys_rows", color=ACCENT)
            last = ctx
        with dpg.group(horizontal=True, parent="keys_rows"):
            b = app.keys.label(action)
            waiting = app._capture == action
            dpg.add_button(label="press a key..." if waiting else (b or "-"), width=130, user_data=action,
                           callback=lambda s, a, u: (setattr(app, "_capture", u), refresh_keys(app)))
            dpg.add_button(label="x", small=True, user_data=action, enabled=bool(b),
                           callback=lambda s, a, u: (app.keys.set(u, ""), refresh_keys(app)))
            dpg.add_text(label, color=TEXT if b else DIM)
            if b != default:
                dpg.add_text(f"(default {default or '-'})", color=DIM)
    dpg.add_spacer(height=6, parent="keys_rows")
    dpg.add_text("always", parent="keys_rows", color=ACCENT)
    for key, what in FIXED:
        dpg.add_text(f"  {key:30s} {what}", parent="keys_rows", color=DIM)


def show_device(app):
    dpg.set_value("device_host", app.project.options.get("device", ""))
    _centre("device_dialog", 380)
    dpg.show_item("device_dialog")


def show_editor(app):
    cmd = app.project.options.get("editor") or ""
    dpg.set_value("editor_cmd", " ".join(cmd) if isinstance(cmd, list) else cmd)
    _centre("editor_dialog", 460)
    dpg.show_item("editor_dialog")


def _centre(tag, w, h=None):
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    y = max(0, vh // 3) if h is None else max(10, (vh - h) // 2)
    dpg.configure_item(tag, pos=(max(0, vw // 2 - w // 2), y))


def show_open(app):
    """The open button's list: every graph and every code effect, two
    scrolling columns so the popup fits under the button whatever the count."""
    dpg.delete_item("open_menu", children_only=True)
    graphs, codes = app.gp.files(), app.project.effect_files()
    with dpg.group(horizontal=True, parent="open_menu"):
        with dpg.child_window(width=210, height=360, border=False):
            dpg.add_text("graphs", color=DIM)
            for f in graphs:
                dpg.add_selectable(label=f[:-5], width=190, user_data=f,
                                   callback=lambda s, a, u: (dpg.hide_item("open_menu"), app.open_graph(u)))
            if not graphs:
                dpg.add_text("  none yet", color=DIM)
        with dpg.child_window(width=230, height=360, border=False):
            dpg.add_text("code effects", color=DIM)
            for f in codes:
                dpg.add_selectable(label=app.project.effect_title(f), width=210, user_data=f,
                                   callback=lambda s, a, u: (dpg.hide_item("open_menu"), app.open_code(u)))
            if not codes:
                dpg.add_text("  none yet", color=DIM)
    x, y = dpg.get_item_rect_min("tb_open")
    dpg.configure_item("open_menu", show=True)
    dpg.set_item_pos("open_menu", [x, y + 26])


# --- the selection frames: which gradient, and a creator ---------------------------------
# A gradient key is "studio", "wled:<palette name>" or "custom:<name>". The
# choice per frame kind lives in prefs["frames"]; custom gradients in
# prefs["gradients"] as {name: {"stops": [[pos, r, g, b], ...], "mirror": bool}}.
FRAME_KINDS = (("sel", "Selected nodes"), ("focus", "Pane last clicked in"))


def _palettes(app):
    """(name, id) for every WLED palette the engine has, asked once."""
    if not hasattr(app, "_pal_list"):
        app._pal_list = app.eng.palette_list()
    return app._pal_list


def gradient_keys(app):
    return ["studio"] + [f"wled:{n}" for n, _ in _palettes(app)] + \
           [f"custom:{n}" for n in sorted(app.prefs.get("gradients") or {})]


def gradient_label(key):
    return {"studio": "Studio"}.get(key) or key.replace("wled:", "WLED: ").replace("custom:", "Custom: ")


def resolve_gradient(app, key):
    """(stops, mirror) for a key; the studio's own when it names nothing."""
    if key and key.startswith("wled:"):
        pid = dict(_palettes(app)).get(key[5:])
        if pid is not None:
            sw = app.eng.palette_swatch(pid, 16)
            return [[k / 15.0, r, g, b] for k, (r, g, b) in enumerate(sw)], True
    if key and key.startswith("custom:"):
        g = (app.prefs.get("gradients") or {}).get(key[7:])
        if g and g.get("stops"):
            return [list(st) for st in g["stops"]], bool(g.get("mirror"))
    return [list(st) for st in glow.DEFAULT_STOPS], False


def apply_frames(app):
    """The frames take their gradients from the prefs."""
    if not app.frames:
        return
    choice = app.prefs.get("frames") or {}
    for kind, _ in FRAME_KINDS:
        stops, mirror = resolve_gradient(app, choice.get(kind, "studio"))
        app.frames.set_gradient(kind, stops, mirror)


def _strip(stops, mirror, width=260, height=14, parent=None):
    """A gradient drawn across a strip, as it goes round the frame."""
    kw = {"parent": parent} if parent else {}
    with dpg.drawlist(width=width, height=height, **kw):
        for x in range(0, width, 2):
            r, g, b = glow.sample(stops, x / max(1, width - 1), mirror)
            dpg.draw_rectangle((x, 0), (x + 2, height), color=(r, g, b, 255), fill=(r, g, b, 255))


def build_frames_dialog(app):
    app._gc = {"name": "", "stops": [list(st) for st in glow.DEFAULT_STOPS], "mirror": False}
    with dpg.window(tag="frames_win", label="Selection frames", show=False, width=560, height=620, no_collapse=True):
        dpg.add_text("The turning gradient frame around the selected nodes, and the one around the pane\n"
                     "last clicked in. Pick a WLED palette, the studio's own, or one you made below.", color=DIM, wrap=530)
        dpg.add_group(tag="frames_choice")
        dpg.add_separator()
        dpg.add_text("GRADIENT CREATOR", color=ACCENT)
        with dpg.group(horizontal=True):
            dpg.add_combo([], tag="gc_from", width=220, callback=lambda s, v: _gc_load(app, v))
            dpg.add_text("start from", color=DIM)
        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="gc_name", hint="a name for this gradient", width=220,
                               callback=lambda s, v: app._gc.__setitem__("name", v))
            dpg.add_checkbox(label="mirror (seamless: 0 to 1 and back)", tag="gc_mirror",
                             callback=lambda s, v: (app._gc.__setitem__("mirror", bool(v)), refresh_frames(app)))
        dpg.add_group(tag="gc_rows")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Save", callback=lambda: _gc_save(app))
            dpg.add_button(label="Save + use for nodes", callback=lambda: _gc_save(app, "sel"))
            dpg.add_button(label="Save + use for pane", callback=lambda: _gc_save(app, "focus"))
            dpg.add_button(label="Delete", tag="gc_delete", callback=lambda: _gc_delete(app))
        dpg.add_text("", tag="gc_status", color=DIM)


def show_frames(app):
    refresh_frames(app)
    _centre("frames_win", 560, 620)
    dpg.show_item("frames_win")


def refresh_frames(app):
    if not dpg.does_item_exist("frames_choice"):
        return
    keys = gradient_keys(app)
    labels = [gradient_label(k) for k in keys]
    choice = app.prefs.get("frames") or {}
    dpg.delete_item("frames_choice", children_only=True)
    for kind, label in FRAME_KINDS:
        cur = choice.get(kind, "studio")
        if cur not in keys:
            cur = "studio"
        with dpg.group(parent="frames_choice"):
            dpg.add_text(label, color=TEXT)
            with dpg.group(horizontal=True):
                dpg.add_combo(labels, width=260, default_value=gradient_label(cur), user_data=kind,
                              callback=lambda s, v, u: _choose(app, u, keys[labels.index(v)]))
                stops, mirror = resolve_gradient(app, cur)
                _strip(stops, mirror)
    dpg.configure_item("gc_from", items=labels)
    gc = app._gc
    dpg.set_value("gc_name", gc["name"])
    dpg.set_value("gc_mirror", gc["mirror"])
    dpg.configure_item("gc_delete", enabled=gc["name"] in (app.prefs.get("gradients") or {}))
    dpg.delete_item("gc_rows", children_only=True)
    _strip(gc["stops"], gc["mirror"], parent="gc_rows")
    for k, st in enumerate(sorted(gc["stops"], key=lambda q: q[0])):
        with dpg.group(horizontal=True, parent="gc_rows"):
            dpg.add_input_float(width=64, default_value=float(st[0]), step=0, format="%.2f",
                                user_data=(k, "pos"), callback=lambda s, v, u: _gc_edit(app, u, v))
            dpg.add_color_edit([int(st[1]), int(st[2]), int(st[3]), 255], width=90, no_alpha=True, no_inputs=True,
                               user_data=(k, "col"), callback=lambda s, v, u: _gc_edit(app, u, v))
            if len(gc["stops"]) > 2:
                dpg.add_button(label="-", small=True, user_data=(k, "del"), callback=lambda s, a, u: _gc_edit(app, u, None))
    dpg.add_button(label="+ stop", small=True, parent="gc_rows", user_data=(-1, "add"),
                   callback=lambda s, a, u: _gc_edit(app, u, None))


def _choose(app, kind, key):
    app.prefs.setdefault("frames", {})[kind] = key
    from native.project import save_prefs
    save_prefs(app.prefs)
    apply_frames(app)
    refresh_frames(app)


def _gc_load(app, label):
    keys = gradient_keys(app)
    labels = [gradient_label(k) for k in keys]
    if label not in labels:
        return
    key = keys[labels.index(label)]
    stops, mirror = resolve_gradient(app, key)
    app._gc = {"name": key[7:] if key.startswith("custom:") else "", "stops": stops, "mirror": mirror}
    refresh_frames(app)


def _gc_edit(app, ud, val):
    k, what = ud
    gc = app._gc
    gc["stops"] = sorted(gc["stops"], key=lambda q: q[0])
    if what == "pos":
        gc["stops"][k][0] = max(0.0, min(1.0, float(val)))
    elif what == "col":
        gc["stops"][k][1:4] = [int(round(c * 255)) if c <= 1.0 else int(c) for c in val[:3]]
    elif what == "del":
        gc["stops"].pop(k)
    elif what == "add":
        gc["stops"].append([1.0, 255, 255, 255])
    refresh_frames(app)


def _gc_save(app, use=None):
    gc = app._gc
    name = (dpg.get_value("gc_name") or gc["name"] or "").strip()
    if not name:
        dpg.set_value("gc_status", "give it a name first"); return
    gc["name"] = name
    app.prefs.setdefault("gradients", {})[name] = {"stops": [list(st) for st in gc["stops"]], "mirror": bool(gc["mirror"])}
    if use:
        app.prefs.setdefault("frames", {})[use] = f"custom:{name}"
    from native.project import save_prefs
    save_prefs(app.prefs)
    apply_frames(app)
    refresh_frames(app)
    dpg.set_value("gc_status", f"saved {name}" + (f" - in use for the {dict(FRAME_KINDS)[use].lower()}" if use else ""))


def _gc_save_named(app, name, use=None):
    dpg.set_value("gc_name", name)
    app._gc["name"] = name
    _gc_save(app, use)


def _gc_delete(app):
    name = app._gc.get("name")
    grads = app.prefs.get("gradients") or {}
    if name not in grads:
        return
    grads.pop(name)
    for kind, key in list((app.prefs.get("frames") or {}).items()):
        if key == f"custom:{name}":
            app.prefs["frames"][kind] = "studio"
    from native.project import save_prefs
    save_prefs(app.prefs)
    app._gc["name"] = ""
    apply_frames(app)
    refresh_frames(app)
    dpg.set_value("gc_status", f"deleted {name}")


# --- state -> chrome ------------------------------------------------------------------
def refresh_files(app):
    """The Open submenus and the Add submenu follow the project."""
    if not dpg.does_item_exist("menu_open_graph"):
        return
    dpg.delete_item("menu_open_graph", children_only=True)
    for f in app.gp.files():
        dpg.add_menu_item(label=f[:-5], parent="menu_open_graph", user_data=f, callback=lambda s, a, u: app.open_graph(u))
    dpg.delete_item("menu_open_code", children_only=True)
    for f in app.project.effect_files():
        dpg.add_menu_item(label=app.project.effect_title(f), parent="menu_open_code", user_data=f,
                          callback=lambda s, a, u: app.open_code(u))
    dpg.delete_item("menu_open_project", children_only=True)
    from native.project import list_projects
    for p in list_projects():
        dpg.add_menu_item(label=p, parent="menu_open_project", user_data=p, callback=lambda s, a, u: app.switch_project(u))
    dpg.delete_item("menu_add", children_only=True)
    cats = {}
    for name, d in app.gp.lib.items():
        cats.setdefault(d["cat"], []).append(name)
    order = ["controls", "signals", "coords", "generate", "maths", "colour", "graph", "subgraphs", "custom", "output"]
    for c in order + sorted(k for k in cats if k not in order):
        names = cats.get(c)
        if not names:
            continue
        with dpg.menu(label=c, parent="menu_add"):
            for n in sorted(names):
                dpg.add_menu_item(label=app.gp.lib[n].get("label") or n, user_data=n,
                                  callback=lambda s, a, u: app.add_node_from_menu(u))
    f = app.current_file()
    on = bool(f) and app.project.is_imported(f)
    dpg.configure_item("menu_import", label="Remove from the effects list" if on else "Add to the effects list",
                       enabled=bool(f))
    dpg.set_value("about_paths", f"project  {app.project.path}\nbuild    {app.build_dir()}")


def _signature(app):
    return (app.layout, app.ui, app.side, app.playing, app.gp.auto, app.gp.zoom, bool(app.gp.stack), app.building)


def refresh(app):
    """Toolbar tints and labels and the View menu's checks, from the app's state."""
    if not dpg.does_item_exist("toolbar"):
        return
    app._chrome_sig = _signature(app)
    for key, _, _ in LAYOUTS:
        on = app.layout == key and app.ui
        dpg.set_value(f"menu_view_{key}", on)
        dpg.configure_item(f"tb_view_{key}", tint_color=ACCENT if on else TEXT)
    dpg.set_value("menu_present", not app.ui)
    dpg.set_value("menu_side", app.side)
    dpg.set_value("menu_live", app.gp.auto)
    dpg.configure_item("tb_live", tint_color=AMBER if app.gp.auto else TEXT)
    dpg.configure_item("tb_build", tint_color=AMBER if app.building else TEXT)
    dpg.configure_item("tb_play", show=not app.playing, tint_color=GREEN)
    dpg.configure_item("tb_pause", show=app.playing)
    dpg.configure_item("rec_btn", tint_color=RED)
    dpg.configure_item("tb_zoom", label=f"{int(app.gp.zoom * 100)}%")


def poll(app):
    if getattr(app, "_chrome_sig", None) != _signature(app):
        refresh(app)
