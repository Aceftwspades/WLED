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

TEXT   = (215, 219, 227, 255)
DIM    = (139, 147, 163, 255)
ACCENT = (90, 169, 230, 255)
ICON   = 16

LAYOUTS = (("net", "Logical net", "Q"), ("cube", "3-D view", "E"), ("both", "Net and 3-D", "W"),
           ("edit", "Code", "C"), ("graph", "Graph", "G"))

SHORTCUTS = [
    ("Views", [("Q / E / W", "logical net / 3-D / both, full frame; again returns to the panels"), ("C", "code pane"), ("G", "graph pane"),
               ("H", "presentation: hide every control"), ("F11", "fullscreen window"),
               ("drag the bars between panes", "resize them")]),
    ("Playback", [("space", "play / pause"), ("F5", "compile + reload the current effect")]),
    ("Files", [("Ctrl+N", "new effect"), ("Ctrl+S", "save"), ("F2", "rename")]),
    ("Graph", [("right-click", "add a node (type to search)"), ("drag a wire to empty space", "add a node wired to it"),
               ("Ctrl+Z / Ctrl+Y", "undo / redo"), ("Ctrl+C / X / V", "copy / cut / paste"), ("Shift+D", "duplicate with its inputs"),
               ("Delete", "delete the selection"), ("F", "connect two selected nodes"), ("M", "mute"),
               ("Ctrl+H", "hide unwired pins"), ("Ctrl+L", "arrange"), ("arrows / Shift+arrows", "nudge 10 / 1"),
               ("Ctrl+= / Ctrl+- / Ctrl+0", "zoom in / out / 100%"), ("wheel", "zoom about the pointer"),
               ("middle-drag", "pan"), ("Home", "frame the whole graph"), ("Alt+click a node", "detach it from its wires"),
               ("double-click a sub-graph", "enter it"), ("click a pin", "preview that pin's value on the cube")]),
]


# --- the menu bar -------------------------------------------------------------------
def build_menus(app):
    with dpg.menu_bar(tag="menubar"):
        with dpg.menu(label="File"):
            dpg.add_menu_item(label="New graph effect...", shortcut="Ctrl+N", callback=lambda: app.new_effect("graph"))
            dpg.add_menu_item(label="New code effect...", callback=lambda: app.new_effect("code"))
            with dpg.menu(label="Open graph", tag="menu_open_graph"):
                pass
            with dpg.menu(label="Open code effect", tag="menu_open_code"):
                pass
            dpg.add_menu_item(label="Save", shortcut="Ctrl+S", callback=lambda: app.save_current())
            dpg.add_menu_item(label="Rename...", shortcut="F2", callback=lambda: app.rename_current())
            dpg.add_separator()
            dpg.add_menu_item(label="Add to the effects list", tag="menu_import", callback=lambda: app.toggle_import_current())
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
            dpg.add_menu_item(label="Screenshot of the 3-D view", callback=lambda: setattr(app, "shot_req", True))
            dpg.add_menu_item(label="Record 15 s GIF", callback=lambda: app.start_rec(15.0))
            dpg.add_separator()
            dpg.add_menu_item(label="Quit", callback=lambda: dpg.stop_dearpygui())
        with dpg.menu(label="Edit"):
            dpg.add_menu_item(label="Undo", shortcut="Ctrl+Z", callback=lambda: app.gp.undo())
            dpg.add_menu_item(label="Redo", shortcut="Ctrl+Y", callback=lambda: app.gp.redo())
            dpg.add_separator()
            dpg.add_menu_item(label="Cut", shortcut="Ctrl+X", callback=lambda: app.gp.cut())
            dpg.add_menu_item(label="Copy", shortcut="Ctrl+C", callback=lambda: app.gp.copy())
            dpg.add_menu_item(label="Paste", shortcut="Ctrl+V", callback=lambda: app.gp.paste())
            dpg.add_menu_item(label="Duplicate with inputs", shortcut="Shift+D", callback=lambda: app.duplicate_selected())
            dpg.add_menu_item(label="Delete", shortcut="Del", callback=lambda: app.gp.delete_selected())
            dpg.add_separator()
            dpg.add_menu_item(label="Connect selected", shortcut="F", callback=lambda: app.gp.connect_selected())
            dpg.add_menu_item(label="Mute", shortcut="M", callback=lambda: app.gp.toggle_selected("muted"))
            dpg.add_menu_item(label="Collapse", callback=lambda: app.gp.toggle_selected("collapsed"))
            dpg.add_menu_item(label="Hide unwired pins", shortcut="Ctrl+H", callback=lambda: app.gp.toggle_selected("hide_pins"))
            dpg.add_menu_item(label="Fold into sub-graph...", callback=lambda: ask(
                app, "Sub-graph", "a name for the new node type", "", lambda v: app.gp.make_sub_from_selection(v)))
            dpg.add_menu_item(label="Arrange", shortcut="Ctrl+L", callback=lambda: app.gp.arrange())
            dpg.add_separator()
            dpg.add_menu_item(label="Find / replace in code", shortcut="Ctrl+F", callback=lambda: app.focus_find())
            dpg.add_menu_item(label="Open code in external editor", callback=lambda: app.open_external())
        with dpg.menu(label="View"):
            for key, label, sc in LAYOUTS:
                dpg.add_menu_item(label=label, shortcut=sc, check=True, tag=f"menu_view_{key}",
                                  callback=lambda s, a, u: app.show_layout(u), user_data=key)
            dpg.add_separator()
            dpg.add_menu_item(label="Presentation (hide controls)", shortcut="H", check=True, tag="menu_present",
                              callback=lambda: app.toggle_ui())
            dpg.add_menu_item(label="Fullscreen", shortcut="F11", callback=lambda: dpg.toggle_viewport_fullscreen())
            dpg.add_separator()
            dpg.add_menu_item(label="Zoom in", shortcut="Ctrl+=", callback=lambda: app.gp.zoom_step(1))
            dpg.add_menu_item(label="Zoom out", shortcut="Ctrl+-", callback=lambda: app.gp.zoom_step(-1))
            dpg.add_menu_item(label="Zoom 100%", shortcut="Ctrl+0", callback=lambda: app.gp.set_zoom(1.0))
            dpg.add_menu_item(label="Frame all", shortcut="Home", callback=lambda: app.gp.home())
            dpg.add_separator()
            dpg.add_menu_item(label="Minimap", check=True, default_value=True, tag="menu_minimap",
                              callback=lambda s, a: dpg.configure_item("node_editor", minimap=bool(a)))
            dpg.add_menu_item(label="Reset pane sizes", callback=lambda: app.reset_layout())
        with dpg.menu(label="Node"):
            dpg.add_menu_item(label="Add node...  (or right-click the graph)", callback=lambda: app.search_nodes())
            with dpg.menu(label="Add", tag="menu_add"):
                pass
            dpg.add_separator()
            dpg.add_menu_item(label="Enter sub-graph", callback=lambda: app.enter_selected_sub())
            dpg.add_menu_item(label="Back to parent graph", callback=lambda: app.gp.back())
            dpg.add_separator()
            dpg.add_menu_item(label="Stop pin preview", callback=lambda: app.gp.set_preview(None))
        with dpg.menu(label="Playback"):
            dpg.add_menu_item(label="Play / pause", shortcut="space", callback=lambda: app.toggle_play())
            dpg.add_menu_item(label="Step one frame", callback=lambda: app.step_once())
            dpg.add_menu_item(label="Restart effect", callback=lambda: app.eng.select(app.eng.idx))
            dpg.add_separator()
            dpg.add_menu_item(label="Compile + reload", shortcut="F5", callback=lambda: app.build_current())
            dpg.add_menu_item(label="Live: rebuild the graph as it changes", check=True, tag="menu_live",
                              default_value=app.gp.auto, callback=lambda s, a: app.gp.set_auto(bool(a)))
            dpg.add_menu_item(label="Watch: rebuild when the code is saved outside", check=True, tag="edit_watch",
                              default_value=False)
        with dpg.menu(label="Settings"):
            dpg.add_menu_item(label="Device address...", callback=lambda: show_device(app))
            dpg.add_menu_item(label="External editor command...", callback=lambda: show_editor(app))
            dpg.add_separator()
            dpg.add_menu_item(label="Open the project folder", callback=lambda: app.reveal(app.project.path))
            dpg.add_menu_item(label="Open the build folder", callback=lambda: app.reveal(app.build_dir()))
        with dpg.menu(label="Help"):
            dpg.add_menu_item(label="Keyboard shortcuts", callback=lambda: dpg.show_item("shortcuts_win"))
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


def _btn(app, icon, tip, cb, tag=None):
    kw = {"tag": tag} if tag else {}
    b = dpg.add_image_button(texture(icon, ICON), width=ICON, height=ICON, tint_color=TEXT,
                             frame_padding=3, callback=cb, **kw)
    with dpg.tooltip(b):
        dpg.add_text(tip)
    return b


def build_toolbar(app):
    with dpg.group(horizontal=True, tag="toolbar"):
        _btn(app, "new", "New effect  Ctrl+N", lambda: app.new_effect())
        _btn(app, "open", "Open a graph or a code effect", lambda: show_open(app), tag="tb_open")
        _btn(app, "save", "Save  Ctrl+S", lambda: app.save_current())
        _sep()
        _btn(app, "build", "Compile + reload  F5", lambda: app.build_current())
        _btn(app, "live", "Live: rebuild the graph as it changes", lambda: app.gp.set_auto(not app.gp.auto), tag="tb_live")
        _sep()
        _btn(app, "undo", "Undo  Ctrl+Z", lambda: app.gp.undo())
        _btn(app, "redo", "Redo  Ctrl+Y", lambda: app.gp.redo())
        _sep()
        _btn(app, "play", "Play  space", lambda: app.toggle_play(), tag="tb_play")
        _btn(app, "pause", "Pause  space", lambda: app.toggle_play(), tag="tb_pause")
        _btn(app, "step", "Step one frame", lambda: app.step_once())
        _btn(app, "restart", "Restart the effect", lambda: app.eng.select(app.eng.idx))
        _sep()
        for key, label, sc in LAYOUTS:
            _btn(app, "code" if key == "edit" else key, f"{label}  {sc}", lambda s, a, u: app.show_layout(u), tag=f"tb_view_{key}")
            dpg.configure_item(f"tb_view_{key}", user_data=key)
        _sep()
        _btn(app, "zoom_out", "Zoom out  Ctrl+-", lambda: app.gp.zoom_step(-1))
        z = dpg.add_button(label="100%", tag="tb_zoom", width=46, callback=lambda: app.gp.set_zoom(1.0))
        with dpg.tooltip(z):
            dpg.add_text("Zoom 100%  Ctrl+0")
        _btn(app, "zoom_in", "Zoom in  Ctrl+=", lambda: app.gp.zoom_step(1))
        _btn(app, "frame_all", "Frame the whole graph  Home", lambda: app.gp.home())
        _sep()
        _btn(app, "search", "Add a node  (right-click the graph)", lambda: app.search_nodes())
        _btn(app, "trash", "Delete the selection  Del", lambda: app.gp.delete_selected())
        _btn(app, "arrange", "Arrange the graph  Ctrl+L", lambda: app.gp.arrange())
        _btn(app, "fold", "Fold the selection into a sub-graph", lambda: ask(
            app, "Sub-graph", "a name for the new node type", "", lambda v: app.gp.make_sub_from_selection(v)))
        _sep()
        _btn(app, "external", "Open the code in an external editor", lambda: app.open_external())
        _btn(app, "camera", "Screenshot of the 3-D view", lambda: setattr(app, "shot_req", True), tag="shot_btn")
        _btn(app, "record", "Record a 15 s GIF", lambda: app.start_rec(15.0), tag="rec_btn")
        dpg.add_text("", tag="rec_msg", color=DIM)


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
    with dpg.window(tag="shortcuts_win", label="Keyboard shortcuts", show=False, width=560, height=520, no_collapse=True):
        for group, rows in SHORTCUTS:
            dpg.add_text(group, color=ACCENT)
            for key, what in rows:
                dpg.add_text(f"  {key:34s} {what}")
            dpg.add_spacer(height=4)
    with dpg.window(tag="about_win", label="About", show=False, width=460, height=200, no_collapse=True):
        dpg.add_text("WLED Effect Studio")
        dpg.add_text("Node graphs and C++ compiled into WLED effects, previewed on a\n"
                     "simulated cube, sphere, matrix or strip with synthetic or live audio.", color=DIM)
        dpg.add_spacer(height=6)
        dpg.add_text("", tag="about_paths", color=DIM)
    with dpg.window(tag="open_menu", show=False, no_title_bar=True, no_resize=True, no_move=True, autosize=True, popup=True):
        pass


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


def show_device(app):
    dpg.set_value("device_host", app.project.options.get("device", ""))
    _centre("device_dialog", 380)
    dpg.show_item("device_dialog")


def show_editor(app):
    cmd = app.project.options.get("editor") or ""
    dpg.set_value("editor_cmd", " ".join(cmd) if isinstance(cmd, list) else cmd)
    _centre("editor_dialog", 460)
    dpg.show_item("editor_dialog")


def _centre(tag, w):
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    dpg.configure_item(tag, pos=(max(0, vw // 2 - w // 2), max(0, vh // 3)))


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
    return (app.layout, app.ui, app.playing, app.gp.auto, app.gp.zoom, bool(app.gp.stack), app.building)


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
    dpg.set_value("menu_live", app.gp.auto)
    dpg.configure_item("tb_live", tint_color=ACCENT if app.gp.auto else TEXT)
    dpg.configure_item("tb_play", show=not app.playing)
    dpg.configure_item("tb_pause", show=app.playing)
    dpg.configure_item("tb_zoom", label=f"{int(app.gp.zoom * 100)}%")


def poll(app):
    if getattr(app, "_chrome_sig", None) != _signature(app):
        refresh(app)
