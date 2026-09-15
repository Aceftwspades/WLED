"""
The node editor panel: Dear PyGui's node editor over native/graph.py.

Every widget carries user_data naming what it is - (node id, pin name) on a
pin, (node id, param name) on a param - so the callbacks never have to parse
tags. The Graph object is the truth; the widgets are a view of it, rebuilt
whole on open and edited in place otherwise. Positions are read back from the
editor on save.
"""
import os

import dearpygui.dearpygui as dpg

from native import graph as G
from native.nodedefs import library

DIM = (139, 147, 163)
PIN_COL = {"float": (110, 190, 250), "color": (250, 170, 90), "bool": (170, 230, 120)}
GREY = (70, 74, 84)
NODE_W = 150            # inner width every node is laid out to
CHAR_W = 7.2            # the default font at 13 px, near enough to right-align by


def _right(text):
    """Indent that puts `text` against the node's right edge, so an output's
    name sits beside its pin on the right the way an input's sits beside its
    pin on the left. Inputs left, outputs right, on every node."""
    return max(0, int(NODE_W - len(text) * CHAR_W))


def compatible(a, b):
    """Can a pin of type a feed a pin of type b? float and bool coerce both
    ways; colour is colour."""
    return a == b or {a, b} == {"float", "bool"}


class PinThemes:
    """One theme per pin type, lit and greyed, and one per link type. Built
    once; bound to attributes and links so the wires are the colour of what
    flows through them and a pin that cannot take the drag goes grey."""
    def __init__(self):
        self.pin, self.grey, self.link = {}, {}, {}
        for t, col in PIN_COL.items():
            self.pin[t] = self._attr_theme(col, col)
            self.grey[t] = self._attr_theme(GREY, GREY)
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNodeLink):
                    dpg.add_theme_color(dpg.mvNodeCol_Link, col, category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkHovered, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkSelected, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
            self.link[t] = th

    @staticmethod
    def _attr_theme(pin, text):
        with dpg.theme() as th:
            with dpg.theme_component(dpg.mvNodeAttribute):
                dpg.add_theme_color(dpg.mvNodeCol_Pin, pin, category=dpg.mvThemeCat_Nodes)
                dpg.add_theme_color(dpg.mvNodeCol_PinHovered, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
            with dpg.theme_component(dpg.mvText):
                dpg.add_theme_color(dpg.mvThemeCol_Text, text, category=dpg.mvThemeCat_Core)
        return th


class GraphPanel:
    def __init__(self, app):
        self.app = app
        self.lib = library(self._user_nodes())
        self.graph = None
        self.file = None
        self.links = {}          # dpg link id -> (b, inp)
        self._pins = {}          # (node, "in"/"out", name) -> attribute tag
        self._ptype = {}         # attribute tag -> pin type
        self._add_count = 0
        self._themes = None      # PinThemes, built lazily (needs a context)
        self._drag_type = None   # type of the output being dragged, if any
        self._menu_pos = (60, 60)

    # --- files -------------------------------------------------------------------
    @property
    def dir(self):
        d = os.path.join(self.app.project.path, "graphs")
        os.makedirs(d, exist_ok=True)
        return d

    def _user_nodes(self):
        out = []
        d = os.path.join(self.app.project.path, "nodes")
        if os.path.isdir(d):
            import json
            for f in sorted(os.listdir(d)):
                if f.endswith(".json"):
                    try:
                        out.append(json.load(open(os.path.join(d, f), encoding="utf-8")))
                    except Exception as e:
                        print(f"user node {f}: {e}")
        return out

    def files(self):
        return sorted(f for f in os.listdir(self.dir) if f.endswith(".json"))

    def new(self, name):
        name = (name or "").strip() or "New Graph"
        fname = G._ident(name) + ".json"
        n = 2
        while os.path.exists(os.path.join(self.dir, fname)):
            fname = f"{G._ident(name)}_{n}.json"; n += 1
        g = G.starter(name, lib=self.lib)
        G.save(g, os.path.join(self.dir, fname))
        self.open(fname)

    def open(self, fname):
        if not fname:
            return
        self.graph = G.load(os.path.join(self.dir, fname), lib=self.lib)
        self.file = fname
        self.rebuild()
        dpg.configure_item("graph_file", items=self.files())
        dpg.set_value("graph_file", fname)
        self.status(f"{fname}")

    def save(self):
        if not self.graph:
            return
        for nid, n in self.graph.nodes.items():
            tag = f"gnode_{nid}"
            if dpg.does_item_exist(tag):
                n["pos"] = list(dpg.get_item_pos(tag))
        G.save(self.graph, os.path.join(self.dir, self.file))
        self.status(f"{self.file} saved")

    def status(self, msg):
        if dpg.does_item_exist("graph_status"):
            dpg.set_value("graph_status", msg)

    # --- build the widgets from the graph -----------------------------------------
    def themes(self):
        if self._themes is None:
            self._themes = PinThemes()
        return self._themes

    def rebuild(self):
        dpg.delete_item("node_editor", children_only=True)
        self.links.clear(); self._pins.clear(); self._ptype.clear()
        if not self.graph:
            return
        for nid, n in self.graph.nodes.items():
            self._make_node(nid, n)
        for a, out, b, inp in self.graph.links:
            self._make_link(a, out, b, inp)

    def _make_node(self, nid, n):
        d = self.lib.get(n["type"])
        if d is None:
            return
        th = self.themes()
        linked = {(b, inp) for _, _, b, inp in self.graph.links}
        n.setdefault("inputs", {})
        with dpg.node(label=n["type"], parent="node_editor", pos=n.get("pos", [0, 0]), tag=f"gnode_{nid}",
                      user_data=nid):
            with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_spacer(width=NODE_W, height=1)
            for i in d["inputs"]:
                tag = f"gin_{nid}_{i['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Input, tag=tag,
                                        user_data=(nid, i["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    # An unconnected input is EDITABLE on the node: the value
                    # it takes stands in for the wire. Connected, the widget
                    # hides and the name stays.
                    is_linked = (nid, i["name"]) in linked
                    dpg.add_text(i["name"], tag=tag + "_t", show=is_linked)
                    self._input_widget(nid, n, i, tag + "_w", show=not is_linked)
                dpg.bind_item_theme(tag, th.pin[i["type"]])
                self._pins[(nid, "in", i["name"])] = tag
                self._ptype[tag] = i["type"]
            for p in d["params"]:
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                    self._param_widget(nid, n, p)
            for o in d["outputs"]:
                tag = f"gout_{nid}_{o['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Output, tag=tag,
                                        user_data=(nid, o["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    dpg.add_text(o["name"], indent=_right(o["name"]))
                dpg.bind_item_theme(tag, th.pin[o["type"]])
                self._pins[(nid, "out", o["name"])] = tag
                self._ptype[tag] = o["type"]

    def _input_widget(self, nid, n, i, tag, show):
        """The editable stand-in for an unconnected input pin."""
        v = n["inputs"].get(i["name"], i.get("default", 0))
        ud = (nid, i["name"])
        if i["type"] == "float":
            dpg.add_input_float(label=i["name"], tag=tag, width=78, default_value=float(v), step=0,
                                format="%.3g", user_data=ud, callback=self._on_input, show=show)
        elif i["type"] == "bool":
            dpg.add_checkbox(label=i["name"], tag=tag, default_value=bool(v), user_data=ud,
                             callback=self._on_input, show=show)
        else:
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [0, 0, 0]
            dpg.add_color_edit([int(c) for c in rgb] + [255], label=i["name"], tag=tag, width=90,
                               no_alpha=True, no_inputs=True, user_data=ud, callback=self._on_input, show=show)

    def _on_input(self, sender, val):
        nid, name = dpg.get_item_user_data(sender)
        if isinstance(val, (list, tuple)) and len(val) >= 3 and all(isinstance(x, float) for x in val):
            val = [int(round(x * 255)) if x <= 1.0 else int(x) for x in val[:3]]
        self.graph.nodes[nid].setdefault("inputs", {})[name] = val

    def _show_input(self, b, inp, linked):
        tag = f"gin_{b}_{inp}"
        if dpg.does_item_exist(tag + "_t"):
            dpg.configure_item(tag + "_t", show=linked)
            dpg.configure_item(tag + "_w", show=not linked)

    def _param_widget(self, nid, n, p):
        v = n["params"].get(p["name"], p["default"])
        ud = (nid, p["name"])
        cb = self._on_param
        if p["type"] == "float":
            dpg.add_input_float(label=p["name"], width=78, default_value=float(v), step=0,
                                format="%.3f", user_data=ud, callback=cb)
        elif p["type"] == "int":
            dpg.add_input_int(label=p["name"], width=78, default_value=int(v), step=0,
                              min_value=int(p.get("min", -1 << 30)), max_value=int(p.get("max", 1 << 30)),
                              min_clamped="min" in p, max_clamped="max" in p, user_data=ud, callback=cb)
        elif p["type"] == "bool":
            dpg.add_checkbox(label=p["name"], default_value=bool(v), user_data=ud, callback=cb)
        elif p["type"] == "choice":
            dpg.add_combo(p["choices"], label=p["name"], width=90, default_value=str(v), user_data=ud, callback=cb)
        elif p["type"] == "color":
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [255, 255, 255]
            dpg.add_color_edit([int(c) for c in rgb] + [255], label=p["name"], width=110, no_alpha=True,
                               user_data=ud, callback=cb)
        elif p["type"] == "text":
            dpg.add_input_text(label=p["name"], width=100, default_value=str(v), user_data=ud, callback=cb)

    def _on_param(self, sender, val):
        nid, name = dpg.get_item_user_data(sender)
        if isinstance(val, (list, tuple)) and len(val) >= 3 and all(isinstance(x, float) for x in val):
            val = [int(round(x * 255)) if x <= 1.0 else int(x) for x in val[:3]]
        self.graph.nodes[nid]["params"][name] = val

    def _make_link(self, a, out, b, inp):
        ta, tb = self._pins.get((a, "out", out)), self._pins.get((b, "in", inp))
        if not ta or not tb:
            return
        lid = dpg.add_node_link(ta, tb, parent="node_editor")
        dpg.bind_item_theme(lid, self.themes().link[self._ptype.get(ta, "float")])
        self.links[lid] = (b, inp)
        self._show_input(b, inp, True)

    # --- editing callbacks ------------------------------------------------------------
    def on_link(self, sender, app_data):
        out_attr, in_attr = app_data
        a, out = dpg.get_item_user_data(out_attr)
        b, inp = dpg.get_item_user_data(in_attr)
        ta, tb = self._ptype.get(out_attr), self._ptype.get(in_attr)
        if ta and tb and not compatible(ta, tb):
            self.status(f"cannot connect {ta} to {tb}")
            return
        # replace whatever fed this input
        for lid, (bb, ii) in list(self.links.items()):
            if bb == b and ii == inp:
                dpg.delete_item(lid); self.links.pop(lid, None)
        self.graph.link(a, out, b, inp)
        self._make_link(a, out, b, inp)

    def on_delink(self, sender, app_data):
        lid = app_data
        b, inp = self.links.pop(lid, (None, None))
        if b is not None:
            self.graph.unlink(b, inp)
            self._show_input(b, inp, False)
        dpg.delete_item(lid)

    # --- greying out while a wire is dragged -----------------------------------------
    # Dear PyGui does not say when a link drag begins, but it does say what is
    # hovered: a press over an output pin is the start of a drag from it, and
    # every input that cannot take that type goes grey until the release.
    def on_press(self):
        if not self.graph or not dpg.does_item_exist("node_editor") or not dpg.is_item_shown("node_editor"):
            return
        for (nid, kind, name), tag in self._pins.items():
            if kind == "out" and dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                self._drag_type = self._ptype.get(tag)
                break
        else:
            return
        th = self.themes()
        for (nid, kind, name), tag in self._pins.items():
            if kind == "in" and dpg.does_item_exist(tag):
                t = self._ptype.get(tag)
                dpg.bind_item_theme(tag, th.pin[t] if compatible(self._drag_type, t) else th.grey[t])

    def on_release(self):
        if self._drag_type is None:
            return
        self._drag_type = None
        th = self.themes()
        for (nid, kind, name), tag in self._pins.items():
            if kind == "in" and dpg.does_item_exist(tag):
                dpg.bind_item_theme(tag, th.pin[self._ptype.get(tag, "float")])

    # --- the right-click menu -------------------------------------------------------------
    def open_menu(self):
        """Remember where the pointer is, so the node lands there."""
        if not dpg.does_item_exist("node_editor") or not dpg.is_item_hovered("node_editor"):
            return
        mx, my = dpg.get_mouse_pos(local=False)
        ex, ey = dpg.get_item_rect_min("node_editor")
        self._menu_pos = (max(0, mx - ex - 20), max(0, my - ey - 10))
        dpg.configure_item("graph_menu", show=True)
        dpg.set_item_pos("graph_menu", [mx, my])

    def add_node_at_menu(self, type_):
        dpg.configure_item("graph_menu", show=False)
        if not self.graph or type_ not in self.lib:
            return
        nid = self.graph.add(type_, self._menu_pos)
        self._make_node(nid, self.graph.nodes[nid])

    def add_node(self, type_):
        if not self.graph or type_ not in self.lib:
            return
        self._add_count += 1
        pos = (60 + 30 * (self._add_count % 8), 60 + 30 * (self._add_count % 8))
        nid = self.graph.add(type_, pos)
        self._make_node(nid, self.graph.nodes[nid])

    def delete_selected(self):
        if not self.graph:
            return
        for tag in dpg.get_selected_nodes("node_editor"):
            nid = dpg.get_item_user_data(tag)
            self.graph.remove(nid)
            for lid, (b, inp) in list(self.links.items()):
                if b == nid or not dpg.does_item_exist(lid):
                    self.links.pop(lid, None)
            dpg.delete_item(tag)
        # links from the removed node's outputs are gone with the node in DPG;
        # rebuild the link map from the editor's truth
        alive = set(dpg.get_item_children("node_editor", 0) or [])
        for lid in list(self.links):
            if lid not in alive:
                self.links.pop(lid, None)

    # --- compile -------------------------------------------------------------------------
    def compile(self, and_build=True):
        """Graph -> effects/<graph>.cpp -> the normal build and reload."""
        if not self.graph:
            return
        self.save()
        try:
            src = self.graph.compile()
        except G.GraphError as e:
            self.status(f"graph: {e}")
            return None
        fname = os.path.splitext(self.file)[0] + ".cpp"
        self.app.project.write_effect(fname, src)
        self.status(f"wrote {fname}")
        if and_build:
            self.app.edit_file = fname
            self.app.edit_build()
        return fname

    def type_names(self):
        cats = {}
        for n, d in self.lib.items():
            cats.setdefault(d["cat"], []).append(n)
        out = []
        for c in ("controls", "signals", "coords", "generate", "maths", "colour", "output"):
            out += [f"{c} / {n}" for n in sorted(cats.pop(c, []))]
        for c, ns in sorted(cats.items()):
            out += [f"{c} / {n}" for n in sorted(ns)]
        return out


def build_panel(app, panel):
    """The graph pane's widgets. Called once from build()."""
    with dpg.group(horizontal=True):
        dpg.add_combo(panel.files(), tag="graph_file", width=170, default_value=panel.file or "",
                      callback=lambda s, v: panel.open(v))
        dpg.add_button(label="save", callback=lambda: panel.save())
        dpg.add_button(label="compile + reload", callback=lambda: panel.compile())
        dpg.add_button(label="open as code", callback=lambda: app.open_graph_code())
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="graph_new_name", hint="new graph name", width=170,
                           on_enter=True, callback=lambda s, v: panel.new(v))
        dpg.add_button(label="new", callback=lambda: panel.new(dpg.get_value("graph_new_name")))
        dpg.add_combo(panel.type_names(), tag="graph_add_type", width=190, default_value="generate / Noise",
                      callback=lambda s, v: dpg.set_value("graph_status",
                                                          panel.lib.get(v.split(" / ", 1)[1], {}).get("doc", "")))
        dpg.add_button(label="add node", callback=lambda: panel.add_node(dpg.get_value("graph_add_type").split(" / ", 1)[1]))
        dpg.add_button(label="delete selected", callback=lambda: panel.delete_selected())
    dpg.add_text("", tag="graph_status", color=DIM)
    with dpg.node_editor(tag="node_editor", callback=panel.on_link, delink_callback=panel.on_delink,
                         minimap=True, minimap_location=dpg.mvNodeMiniMap_Location_BottomRight,
                         width=-1, height=-1):
        pass
    # The right-click menu: a small window shown at the pointer, categories as
    # collapsing headers, a node per line. A window rather than a popup so it
    # can be positioned exactly and dismissed by the click that adds.
    cats = {}
    for name in panel.type_names():
        c, n = name.split(" / ", 1)
        cats.setdefault(c, []).append(n)
    with dpg.window(tag="graph_menu", show=False, no_title_bar=True, no_resize=True, no_move=True,
                    autosize=True, popup=True):
        dpg.add_text("add node", color=DIM)
        for c, names in cats.items():
            with dpg.collapsing_header(label=c, default_open=(c in ("generate", "colour"))):
                for n in names:
                    dpg.add_selectable(label=n, user_data=n,
                                       callback=lambda s, a, u: panel.add_node_at_menu(u))
