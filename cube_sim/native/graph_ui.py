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


class GraphPanel:
    def __init__(self, app):
        self.app = app
        self.lib = library(self._user_nodes())
        self.graph = None
        self.file = None
        self.links = {}          # dpg link id -> (b, inp)
        self._pins = {}          # (node, "in"/"out", name) -> attribute tag
        self._add_count = 0

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
    def rebuild(self):
        dpg.delete_item("node_editor", children_only=True)
        self.links.clear(); self._pins.clear()
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
        with dpg.node(label=n["type"], parent="node_editor", pos=n.get("pos", [0, 0]), tag=f"gnode_{nid}",
                      user_data=nid):
            for i in d["inputs"]:
                tag = f"gin_{nid}_{i['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Input, tag=tag,
                                        user_data=(nid, i["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    dpg.add_text(i["name"], color=PIN_COL.get(i["type"], DIM))
                self._pins[(nid, "in", i["name"])] = tag
            for p in d["params"]:
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                    self._param_widget(nid, n, p)
            for o in d["outputs"]:
                tag = f"gout_{nid}_{o['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Output, tag=tag,
                                        user_data=(nid, o["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    dpg.add_text(o["name"], color=PIN_COL.get(o["type"], DIM))
                self._pins[(nid, "out", o["name"])] = tag

    def _param_widget(self, nid, n, p):
        v = n["params"].get(p["name"], p["default"])
        ud = (nid, p["name"])
        cb = self._on_param
        if p["type"] == "float":
            dpg.add_input_float(label=p["name"], width=90, default_value=float(v), step=0,
                                format="%.3f", user_data=ud, callback=cb)
        elif p["type"] == "int":
            dpg.add_input_int(label=p["name"], width=90, default_value=int(v), step=0,
                              min_value=int(p.get("min", -1 << 30)), max_value=int(p.get("max", 1 << 30)),
                              min_clamped="min" in p, max_clamped="max" in p, user_data=ud, callback=cb)
        elif p["type"] == "bool":
            dpg.add_checkbox(label=p["name"], default_value=bool(v), user_data=ud, callback=cb)
        elif p["type"] == "choice":
            dpg.add_combo(p["choices"], label=p["name"], width=100, default_value=str(v), user_data=ud, callback=cb)
        elif p["type"] == "color":
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [255, 255, 255]
            dpg.add_color_edit([int(c) for c in rgb] + [255], label=p["name"], width=110, no_alpha=True,
                               user_data=ud, callback=cb)
        elif p["type"] == "text":
            dpg.add_input_text(label=p["name"], width=110, default_value=str(v), user_data=ud, callback=cb)

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
        self.links[lid] = (b, inp)

    # --- editing callbacks ------------------------------------------------------------
    def on_link(self, sender, app_data):
        out_attr, in_attr = app_data
        a, out = dpg.get_item_user_data(out_attr)
        b, inp = dpg.get_item_user_data(in_attr)
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
        dpg.delete_item(lid)

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
