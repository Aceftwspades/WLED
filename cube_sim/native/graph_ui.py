"""
The node editor panel: Dear PyGui's node editor over native/graph.py.

Every widget carries user_data naming what it is - (node id, pin name) on a
pin, (node id, param name) on a param - so the callbacks never have to parse
tags. The Graph object is the truth; the widgets are a view of it, rebuilt
whole on open and edited in place otherwise. Positions are read back from the
editor on save.
"""
import json
import os
import time

import dearpygui.dearpygui as dpg

from native import graph as G
from native.nodedefs import library

DIM = (139, 147, 163)
PIN_COL = {"float": (110, 190, 250), "color": (250, 170, 90), "bool": (170, 230, 120)}
GREY = (70, 74, 84)
NODE_W = 150            # inner width every node is laid out to
WIRE_COLOURS = [("type colour", None), ("white", (235, 235, 235)), ("red", (235, 80, 70)),
                ("orange", (250, 160, 60)), ("yellow", (240, 220, 80)), ("green", (120, 220, 110)),
                ("cyan", (90, 220, 230)), ("blue", (100, 150, 250)), ("magenta", (230, 100, 220)),
                ("grey", (130, 135, 145))]
CHAR_W = 7.2            # the default font at 13 px, near enough to right-align by


NARROW_W = 46           # a knot: just wide enough for its two pin names


def _right(text, width=NODE_W):
    """Indent that puts `text` against the node's right edge, so an output's
    name sits beside its pin on the right the way an input's sits beside its
    pin on the left. Inputs left, outputs right, on every node."""
    return max(0, int(width - len(text) * CHAR_W))


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
        self.cur_dir = None      # graphs/ or subgraphs/ - where `file` lives
        self.stack = []          # (dir, file) to return to from a sub-graph
        self._subs = {}          # ident -> Graph, loaded on demand
        self.links = {}          # dpg link id -> (b, inp)
        self._pins = {}          # (node, "in"/"out", name) -> attribute tag
        self._ptype = {}         # attribute tag -> pin type
        self._add_count = 0
        self._themes = None      # PinThemes, built lazily (needs a context)
        self._wire_themes = {}   # (r,g,b) -> a link theme in that colour
        self._ctx = None         # what the context menu is about: ("in"|"out"|"node", ...)
        self._undo = []          # JSON snapshots of the graph before each edit
        self._redo = []
        self._last_snap = None   # (key, time) of the last snapshot, to coalesce slider drags
        self._widgets = set()    # every value widget on a node, so keys know when one is typed in
        self._node_themes = {}   # (r,g,b) -> a node theme with that title bar
        self._mark_themes = {}   # "error"/"warn" -> outline theme
        self.problems = {}       # node id -> message, from the last rebuild
        self.preview = None      # (node, output) routed to Output instead of the graph's own
        self._frame_last = {}    # frame node -> its position last poll
        self._frame_drag = {}    # frame node -> the nodes moving with it, while it moves
        self.auto = False        # live preview: rebuild after every edit
        self._dirty = 0.0        # time of the last edit not yet built, 0 when clean
        self._queued = False     # an edit landed while a build was running
        self._drag_type = None   # type of the output being dragged, if any
        self._drag_from = None   # (node, output) being dragged, for a drop on empty space
        self._press_at = (0, 0)
        self._pending = None     # (node, output, type): the new node gets wired from here
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

    @property
    def sub_dir(self):
        d = os.path.join(self.app.project.path, "subgraphs")
        os.makedirs(d, exist_ok=True)
        return d

    def files(self):
        return sorted(f for f in os.listdir(self.dir) if f.endswith(".json"))

    def sub_files(self):
        return sorted(f for f in os.listdir(self.sub_dir) if f.endswith(".json"))

    # --- sub-graphs as node types ------------------------------------------------------
    def resolve_sub(self, ident):
        """The Graph for a sub-graph node type, by file stem. Cached until
        refresh_lib(), which runs whenever one is saved."""
        if ident not in self._subs:
            path = os.path.join(self.sub_dir, ident + ".json")
            if not os.path.exists(path):
                return None
            self._subs[ident] = G.load(path, lib=self.lib, resolver=self.resolve_sub)
        return self._subs[ident]

    def refresh_lib(self):
        """Rebuild the library: the built-ins, the user nodes, and one node
        type per sub-graph file, its pins read from the boundary nodes."""
        self._subs.clear()
        self.lib = library(self._user_nodes())
        for f in self.sub_files():
            ident = f[:-5]
            sub = self.resolve_sub(ident)
            if sub is not None:
                self.lib[G.SUB + ident] = G.sub_def(ident, sub)
        if self.graph is not None:
            self.graph.lib = self.lib
        if dpg.does_item_exist("graph_add_type"):
            dpg.configure_item("graph_add_type", items=self.type_names())
        self.fill_add_menu()

    def new(self, name):
        name = (name or "").strip() or "New Graph"
        fname = G._ident(name) + ".json"
        n = 2
        while os.path.exists(os.path.join(self.dir, fname)):
            fname = f"{G._ident(name)}_{n}.json"; n += 1
        g = G.starter(name, lib=self.lib, resolver=self.resolve_sub)
        G.save(g, os.path.join(self.dir, fname))
        self.open(fname)

    def open(self, fname, sub=False):
        if not fname:
            return
        self.refresh_lib()
        d = self.sub_dir if sub else self.dir
        self.graph = G.load(os.path.join(d, fname), lib=self.lib, resolver=self.resolve_sub)
        self.file = fname
        self.cur_dir = d
        self._undo.clear(); self._redo.clear(); self._last_snap = None
        self.preview = None
        self.rebuild()
        dpg.configure_item("graph_file", items=self.files())
        dpg.set_value("graph_file", fname if not sub else "")
        dpg.configure_item("graph_back", show=bool(self.stack))
        self.status(("sub-graph " if sub else "") + fname)
        self.app.refresh_import_buttons()

    def save(self):
        if not self.graph:
            return
        for nid, n in self.graph.nodes.items():
            tag = f"gnode_{nid}"
            if dpg.does_item_exist(tag):
                n["pos"] = list(dpg.get_item_pos(tag))
        G.save(self.graph, os.path.join(self.cur_dir or self.dir, self.file))
        self.status(f"{self.file} saved")
        if self.cur_dir == self.sub_dir:
            self._subs.pop(self.file[:-5], None)     # its pins may have changed

    def effect_file(self):
        """The effect file this graph generates, or None with no graph open."""
        return os.path.splitext(self.file)[0] + ".cpp" if self.file else None

    def rename(self, name):
        """The graph, its file and its generated effect take a new name. A
        sub-graph's name is also its node type, so every graph that uses it
        is rewritten to the new one."""
        name = (name or "").strip()
        if not name or not self.graph:
            self.status("type the new name in the box first")
            return
        self.save()
        old_stem = os.path.splitext(self.file)[0]
        new_stem = G._ident(name)
        d = self.cur_dir or self.dir
        n = 2
        while new_stem != old_stem and os.path.exists(os.path.join(d, new_stem + ".json")):
            new_stem = f"{G._ident(name)}_{n}"; n += 1
        self.graph.name = name
        if new_stem != old_stem:
            os.remove(os.path.join(d, self.file))
            self.file = new_stem + ".json"
        G.save(self.graph, os.path.join(d, self.file))
        proj = self.app.project
        old_cpp, new_cpp = old_stem + ".cpp", new_stem + ".cpp"
        if old_cpp in proj.effect_files():
            if new_cpp != old_cpp and new_cpp in proj.effect_files():
                os.remove(proj.effect_path(new_cpp))
            proj.rename_effect(old_cpp, name)      # keeps the list entry, regenerated below anyway
        if d == self.sub_dir and new_stem != old_stem:
            # the node type changed: rewrite every graph that uses this sub-graph
            for gd in (self.dir, self.sub_dir):
                for f in os.listdir(gd):
                    if not f.endswith(".json") or (gd == d and f == self.file):
                        continue
                    p = os.path.join(gd, f)
                    txt = open(p, encoding="utf-8").read()
                    if f'"{G.SUB}{old_stem}"' in txt:
                        open(p, "w", encoding="utf-8").write(txt.replace(f'"{G.SUB}{old_stem}"', f'"{G.SUB}{new_stem}"'))
        self.refresh_lib()
        self.open(self.file, sub=(d == self.sub_dir))
        dpg.set_value("graph_new_name", "")
        self.status(f"renamed to {name}")
        if self.app.edit_file == old_cpp:
            self.app.edit_file = new_cpp if new_cpp in proj.effect_files() else None
        self.compile()

    # --- sub-graphs: in and out --------------------------------------------------------
    def enter_sub(self, nid):
        """Open the sub-graph a node stands for; back returns to here."""
        n = self.graph.nodes.get(nid)
        if not n or not n["type"].startswith(G.SUB):
            return
        self.save()
        self.stack.append((self.cur_dir, self.file))
        self.open(n["type"][len(G.SUB):] + ".json", sub=True)

    def back(self):
        if not self.stack:
            return
        self.save()
        d, f = self.stack.pop()
        self.open(f, sub=(d == self.sub_dir))

    def make_sub_from_selection(self, name=None):
        """The selected nodes become one sub-graph node. Wires crossing the
        boundary become the new node's pins - a Graph input for each link
        coming in, named after the pin it fed; a Graph output for each
        distinct output feeding out, named after it - and the parent is
        rewired through the new node in their place."""
        if not self.graph:
            return
        sel = [dpg.get_item_user_data(t) for t in dpg.get_selected_nodes("node_editor")]
        sel = [nid for nid in sel if nid in self.graph.nodes and self.graph.nodes[nid]["type"] not in ("Output",)]
        if not sel:
            self.status("select the nodes to fold first")
            return
        self.snapshot()
        self.save()                                   # positions
        g = self.graph
        S = set(sel)
        name = (name or "").strip() or f"Sub {len(self.sub_files()) + 1}"
        ident = G._ident(name)
        while os.path.exists(os.path.join(self.sub_dir, ident + ".json")):
            ident += "_2"
        sub = G.Graph({"name": name}, lib=self.lib, resolver=self.resolve_sub)
        # the chosen nodes, moved so the group starts near the origin
        x0 = min(g.nodes[n]["pos"][0] for n in S); y0 = min(g.nodes[n]["pos"][1] for n in S)
        smap = {}
        for nid in sel:
            n = g.nodes[nid]
            smap[nid] = sub.add(n["type"], (n["pos"][0] - x0 + 260, n["pos"][1] - y0 + 40), dict(n.get("params", {})))
            sub.nodes[smap[nid]]["inputs"] = dict(n.get("inputs", {}))
        for a, o, b, i in g.links:
            if a in S and b in S:
                sub.link(smap[a], o, smap[b], i)
        # boundary: in
        in_pins, in_nodes = {}, {}     # (a, o) outside -> pin name ; pin -> Graph input id
        y = 40
        for a, o, b, i in g.links:
            if a not in S and b in S:
                key = (a, o)
                if key not in in_pins:
                    pin = i
                    k = 2
                    while pin in in_nodes:
                        pin = f"{i}{k}"; k += 1
                    t = next((x["type"] for x in g.node_def(g.nodes[a])["outputs"] if x["name"] == o), "float")
                    in_pins[key] = pin
                    in_nodes[pin] = sub.add("Graph input", (20, y), {"name": pin, "type": t, "default": 0.0}); y += 135
                sub.link(in_nodes[in_pins[key]], "value", smap[b], i)
        # boundary: out
        out_pins, out_nodes = {}, {}
        y = 40
        xmax = max(sub.nodes[n]["pos"][0] for n in smap.values()) + 260 if smap else 500
        for a, o, b, i in g.links:
            if a in S and b not in S:
                key = (a, o)
                if key not in out_pins:
                    pin = o
                    k = 2
                    while pin in out_nodes:
                        pin = f"{o}{k}"; k += 1
                    t = next((x["type"] for x in g.node_def(g.nodes[a])["outputs"] if x["name"] == o), "float")
                    out_pins[key] = pin
                    out_nodes[pin] = sub.add("Graph output", (xmax, y), {"name": pin, "type": t}); y += 110
                    sub.link(smap[a], o, out_nodes[pin], "value")
        G.save(sub, os.path.join(self.sub_dir, ident + ".json"))
        self.refresh_lib()
        # the parent: one node where the group was
        cx = sum(g.nodes[n]["pos"][0] for n in S) / len(S); cy = sum(g.nodes[n]["pos"][1] for n in S) / len(S)
        new = g.add(G.SUB + ident, (cx, cy))
        outer_in = [(a, o, b, i) for a, o, b, i in g.links if a not in S and b in S]
        outer_out = [(a, o, b, i) for a, o, b, i in g.links if a in S and b not in S]
        for nid in sel:
            g.remove(nid)
        for a, o, b, i in outer_in:
            g.link(a, o, new, in_pins[(a, o)])
        for a, o, b, i in outer_out:
            g.link(new, out_pins[(a, o)], b, i)
        self.rebuild()
        self.save()
        self.status(f"folded {len(sel)} nodes into sub-graph '{name}'")

    def status(self, msg):
        if dpg.does_item_exist("graph_status"):
            dpg.set_value("graph_status", msg)

    # --- build the widgets from the graph -----------------------------------------
    def themes(self):
        if self._themes is None:
            self._themes = PinThemes()
        return self._themes

    # --- undo / redo -----------------------------------------------------------------
    # Every edit first pushes the graph as JSON. Cheap - a graph is a few KB -
    # and it makes every mutation, however it was reached, undoable with one
    # line at the top of it. A slider or text param being dragged or typed
    # would push a snapshot per tick; edits to the same key within a second
    # share one, so undo steps back over the drag, not each pixel of it.
    UNDO_MAX = 200

    def _sync_pos(self):
        if not self.graph:
            return
        for nid, n in self.graph.nodes.items():
            tag = f"gnode_{nid}"
            if dpg.does_item_exist(tag):
                n["pos"] = list(dpg.get_item_pos(tag))

    def snapshot(self, key=None):
        """Call before changing the graph. `key` names a continuous edit."""
        if not self.graph:
            return
        now = time.time()
        if key is not None and self._last_snap and self._last_snap[0] == key and now - self._last_snap[1] < 1.0:
            self._last_snap = (key, now)
            return
        self._last_snap = (key, now)
        self._sync_pos()
        self._undo.append(json.dumps(self.graph.to_json()))
        del self._undo[:-self.UNDO_MAX]
        self._redo.clear()

    def _restore(self, snap):
        self.graph = G.Graph(json.loads(snap), lib=self.lib, resolver=self.resolve_sub)
        self._last_snap = None
        self.rebuild()

    def undo(self):
        if not self._undo:
            self.status("nothing to undo"); return
        self._sync_pos()
        self._redo.append(json.dumps(self.graph.to_json()))
        self._restore(self._undo.pop())
        self.status(f"undo ({len(self._undo)} more)")

    def redo(self):
        if not self._redo:
            self.status("nothing to redo"); return
        self._sync_pos()
        self._undo.append(json.dumps(self.graph.to_json()))
        self._restore(self._redo.pop())
        self.status("redo")

    def nudge(self, dx, dy):
        """Move the selected nodes by a step - the arrow keys."""
        sel = self._selected()
        if not sel:
            return
        self.snapshot("nudge")
        for nid in sel:
            t = f"gnode_{nid}"
            x, y = dpg.get_item_pos(t)
            dpg.set_item_pos(t, [x + dx, y + dy])
        self._sync_pos()

    def home(self):
        """Bring the graph back to the origin: the editor cannot be panned
        from code, so the nodes move instead, their top-left to (20, 20)."""
        if not self.graph or not self.graph.nodes:
            return
        self._sync_pos()
        self.snapshot()
        x0 = min(n["pos"][0] for n in self.graph.nodes.values())
        y0 = min(n["pos"][1] for n in self.graph.nodes.values())
        for nid, n in self.graph.nodes.items():
            n["pos"] = [n["pos"][0] - x0 + 20, n["pos"][1] - y0 + 20]
            if dpg.does_item_exist(f"gnode_{nid}"):
                dpg.set_item_pos(f"gnode_{nid}", n["pos"])
        self._frame_last = {nid: tuple(n["pos"]) for nid, n in self.graph.nodes.items() if n["type"] == "Frame"}

    def typing(self):
        """True while a value box on a node has the keyboard."""
        return any(dpg.does_item_exist(w) and dpg.is_item_active(w) for w in self._widgets)

    # --- copy / cut / paste ----------------------------------------------------------
    # The clipboard is the selected nodes and the wires between them, as
    # graph JSON, held on the app so it survives switching graphs and going
    # into a sub-graph. Pasting gives fresh ids and nudges the copies so they
    # do not land exactly on the originals.
    def _selected(self):
        if not self.graph:
            return []
        out = []
        for tag in dpg.get_selected_nodes("node_editor"):
            nid = dpg.get_item_user_data(tag)
            if nid in self.graph.nodes:
                out.append(nid)
        return out

    def copy(self):
        sel = self._selected()
        if not sel:
            self.status("select nodes to copy"); return
        self._sync_pos()
        S = set(sel)
        nodes = [json.loads(json.dumps(self.graph.nodes[n])) for n in sel]
        links = [list(l) for l in self.graph.links if l[0] in S and l[2] in S]
        meta = {f"{b}:{i}": m for (b, i), m in self.graph.link_meta.items() if b in S}
        self.app.clipboard = {"nodes": nodes, "links": links, "meta": meta}
        self.status(f"copied {len(nodes)} node(s)")

    def cut(self):
        sel = self._selected()
        if not sel:
            return
        self.copy()
        self.snapshot()
        for nid in sel:
            self.graph.remove(nid)
        self.rebuild()
        self.status(f"cut {len(sel)} node(s)")

    def paste(self, at=None):
        clip = getattr(self.app, "clipboard", None)
        if not clip or not self.graph:
            self.status("nothing to paste"); return
        self.snapshot()
        ids = {}
        xs = [n["pos"][0] for n in clip["nodes"]]; ys = [n["pos"][1] for n in clip["nodes"]]
        if at is not None:
            dx, dy = at[0] - min(xs), at[1] - min(ys)
        else:
            dx = dy = 40
        for n in clip["nodes"]:
            t = n["type"]
            if t not in self.lib and not t.startswith(G.SUB):
                continue
            new = self.graph.add(t, (n["pos"][0] + dx, n["pos"][1] + dy), dict(n.get("params", {})))
            self.graph.nodes[new]["inputs"] = dict(n.get("inputs", {}))
            ids[n["id"]] = new
        for a, o, b, i in clip["links"]:
            if a in ids and b in ids:
                self.graph.link(ids[a], o, ids[b], i)
                m = clip["meta"].get(f"{b}:{i}")
                if m:
                    self.graph.link_meta[(ids[b], i)] = dict(m)
        self.rebuild()
        self.status(f"pasted {len(ids)} node(s)")

    # --- live preview ------------------------------------------------------------------
    # Every edit marks the graph dirty; poll() - called each frame from the
    # main loop - waits until the edits pause for a moment, then compiles and
    # builds on the worker exactly as the button does. The 3-D view keeps
    # running the previous build meanwhile, and the swap keeps the sliders,
    # palette and colours, so the effect just changes under the cursor a
    # second or two after the wire lands.
    AUTO_DELAY = 0.5

    def touch(self):
        self._dirty = time.time()

    def set_auto(self, on):
        self.auto = bool(on)
        if self.auto:
            self.touch()

    def poll(self):
        self._poll_frames()
        if not self.auto or not self._dirty or not self.graph:
            return
        if time.time() - self._dirty < self.AUTO_DELAY:
            return
        if self.app.building:
            return                    # tried again next frame; the last edit wins
        self._dirty = 0.0
        self.compile()

    def rebuild(self):
        self.touch()
        self._widgets.clear()
        dpg.delete_item("node_editor", children_only=True)
        self.links.clear(); self._pins.clear(); self._ptype.clear()
        if not self.graph:
            return
        # frames first: nodes draw in creation order, so a frame made first
        # sits behind the nodes inside it
        for nid, n in sorted(self.graph.nodes.items(), key=lambda kv: kv[1]["type"] != "Frame"):
            self._make_node(nid, n)
        self._frame_last = {nid: tuple(n["pos"]) for nid, n in self.graph.nodes.items() if n["type"] == "Frame"}
        self._frame_drag.clear()
        # a wire to a pin that no longer exists - a sub-graph's input was
        # renamed or removed - is dropped rather than kept invisibly
        stale = [l for l in self.graph.links
                 if (l[0], "out", l[1]) not in self._pins or (l[2], "in", l[3]) not in self._pins]
        if stale:
            self.graph.links = [l for l in self.graph.links if l not in stale]
            self.status(f"dropped {len(stale)} wire(s) to pins that no longer exist")
        for a, out, b, inp in self.graph.links:
            self._make_link(a, out, b, inp)
        self._mark_problems()

    # --- validation ---------------------------------------------------------------------
    # Problems are painted on the node - a red outline for what stops the
    # compile, amber for what only looks wrong - and listed in the status
    # line, so a broken graph says where before a build is tried.
    def _mark_theme(self, kind):
        th = self._mark_themes.get(kind)
        if th is None:
            col = (235, 80, 70) if kind == "error" else (240, 190, 70)
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNode):
                    dpg.add_theme_color(dpg.mvNodeCol_NodeOutline, col, category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_style(dpg.mvNodeStyleVar_NodeBorderThickness, 2.5, category=dpg.mvThemeCat_Nodes)
            self._mark_themes[kind] = th
        return th

    def _mark_problems(self):
        if not self.graph:
            return
        self.problems = self.graph.problems()
        errs = []
        for nid, msg in self.problems.items():
            tag = f"gnode_{nid}"
            if not dpg.does_item_exist(tag):
                continue
            kind = "error" if msg.startswith("error") else "warn"
            n = self.graph.nodes[nid]
            # a coloured or framed node keeps its colour theme; the outline wins on top of it
            if kind == "error" or not (n.get("color") or n["type"] == "Frame"):
                dpg.bind_item_theme(tag, self._mark_theme(kind))
            if kind == "error":
                errs.append(f"{n['type']} #{nid}: {msg[7:]}")
        if errs:
            self.status("; ".join(errs)[:200])

    def _make_node(self, nid, n):
        try:
            d = self.graph.node_def(n)
        except G.GraphError as e:
            self.status(str(e)); return
        th = self.themes()
        linked = {(b, inp) for _, _, b, inp in self.graph.links}
        n.setdefault("inputs", {})
        label = d.get("label") or n["type"]
        if n["type"] in ("Graph input", "Graph output"):
            label = f"{n['type']}: {n['params'].get('name', '')}"
        if n["type"] == "Frame":
            label = str(n["params"].get("title", "group"))
        collapsed = bool(n.get("collapsed"))
        width = NARROW_W if d.get("narrow") else NODE_W
        with dpg.node(label=label, parent="node_editor", pos=n.get("pos", [0, 0]), tag=f"gnode_{nid}",
                      user_data=nid):
            if n["type"] == "Frame":
                self._frame_body(nid, n)
            with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                dpg.add_spacer(width=width, height=1)
            for i in d["inputs"]:
                tag = f"gin_{nid}_{i['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Input, tag=tag,
                                        user_data=(nid, i["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    # An unconnected input is EDITABLE on the node: the value
                    # it takes stands in for the wire. Connected, the widget
                    # hides and the name stays.
                    is_linked = (nid, i["name"]) in linked
                    dpg.add_text(i["name"], tag=tag + "_t", show=is_linked or collapsed)
                    if not collapsed:
                        self._input_widget(nid, n, i, tag + "_w", show=not is_linked)
                dpg.bind_item_theme(tag, th.pin[i["type"]])
                self._pins[(nid, "in", i["name"])] = tag
                self._ptype[tag] = i["type"]
            if not collapsed and n["type"] != "Frame":
                for p in d["params"]:
                    with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                        self._param_widget(nid, n, p, multiline=d.get("multiline", False))
            for o in d["outputs"]:
                tag = f"gout_{nid}_{o['name']}"
                with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Output, tag=tag,
                                        user_data=(nid, o["name"]), shape=dpg.mvNode_PinShape_CircleFilled):
                    dpg.add_text(o["name"], indent=_right(o["name"], width))
                dpg.bind_item_theme(tag, th.pin[o["type"]])
                self._pins[(nid, "out", o["name"])] = tag
                self._ptype[tag] = o["type"]
        col = n.get("color")
        if col:
            dpg.bind_item_theme(f"gnode_{nid}", self._node_theme(tuple(col)))
        elif n["type"] == "Frame":
            dpg.bind_item_theme(f"gnode_{nid}", self._node_theme(tuple(n["params"].get("colour", [90, 110, 160]))[:3], frame=True))

    def _node_theme(self, col, frame=False):
        """A node theme whose title bar is `col`; a frame's body is a wash of
        the same colour so the nodes inside still read through it."""
        key = (col, frame)
        th = self._node_themes.get(key)
        if th is None:
            r, g, b = col
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNode):
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBar, (r, g, b, 255), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBarHovered, (min(255, r + 30), min(255, g + 30), min(255, b + 30), 255),
                                        category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_TitleBarSelected, (min(255, r + 50), min(255, g + 50), min(255, b + 50), 255),
                                        category=dpg.mvThemeCat_Nodes)
                    if frame:
                        dpg.add_theme_color(dpg.mvNodeCol_NodeBackground, (r, g, b, 40), category=dpg.mvThemeCat_Nodes)
                        dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundHovered, (r, g, b, 55), category=dpg.mvThemeCat_Nodes)
                        dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundSelected, (r, g, b, 70), category=dpg.mvThemeCat_Nodes)
                        dpg.add_theme_color(dpg.mvNodeCol_NodeOutline, (r, g, b, 160), category=dpg.mvThemeCat_Nodes)
            self._node_themes[key] = th
        return th

    # --- frames ---------------------------------------------------------------------
    # A Frame is an ordinary node with nothing in it but a spacer of its size,
    # its body tinted by theme. Nodes are not parented to it - imnodes has no
    # groups - so poll() watches the frame's position: when it moves, the nodes
    # whose corner was inside it are moved by the same amount. Nodes in the
    # current selection are left alone, since the drag moves them already.
    def _frame_body(self, nid, n):
        w = int(n["params"].get("w", 400)); h = int(n["params"].get("h", 300))
        with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
            dpg.add_spacer(width=w, height=h - 40)
            with dpg.group(horizontal=True):
                w_ = dpg.add_input_int(label="w", width=70, default_value=w, step=0, user_data=(nid, "w"),
                                       callback=self._on_param)
                h_ = dpg.add_input_int(label="h", width=70, default_value=h, step=0, user_data=(nid, "h"),
                                       callback=self._on_param)
                self._widgets.update((w_, h_))

    def _frame_rect(self, nid, pos=None):
        n = self.graph.nodes[nid]
        x, y = pos if pos is not None else dpg.get_item_pos(f"gnode_{nid}")
        return x, y, x + int(n["params"].get("w", 400)) + 16, y + int(n["params"].get("h", 300)) + 30

    def _poll_frames(self):
        if not self.graph or not self._frame_last:
            return
        selected = {dpg.get_item_user_data(t) for t in dpg.get_selected_nodes("node_editor")}
        for fid, last in list(self._frame_last.items()):
            tag = f"gnode_{fid}"
            if not dpg.does_item_exist(tag):
                continue
            cur = tuple(dpg.get_item_pos(tag))
            dx, dy = cur[0] - last[0], cur[1] - last[1]
            if dx == 0 and dy == 0:
                self._frame_drag.pop(fid, None)
                continue
            if fid not in self._frame_drag:
                x0, y0, x1, y1 = self._frame_rect(fid, last)
                members = []
                for nid in self.graph.nodes:
                    if nid == fid or nid in selected or self.graph.nodes[nid]["type"] == "Frame":
                        continue
                    t = f"gnode_{nid}"
                    if dpg.does_item_exist(t):
                        px, py = dpg.get_item_pos(t)
                        if x0 <= px <= x1 and y0 <= py <= y1:
                            members.append(nid)
                self._frame_drag[fid] = members
            for nid in self._frame_drag[fid]:
                t = f"gnode_{nid}"
                if dpg.does_item_exist(t):
                    px, py = dpg.get_item_pos(t)
                    dpg.set_item_pos(t, [px + dx, py + dy])
            self._frame_last[fid] = cur

    def _input_widget(self, nid, n, i, tag, show):
        """The editable stand-in for an unconnected input pin."""
        v = n["inputs"].get(i["name"], i.get("default", 0))
        ud = (nid, i["name"])
        if i["type"] == "float":
            w = dpg.add_input_float(label=i["name"], tag=tag, width=78, default_value=float(v), step=0,
                                format="%.3g", user_data=ud, callback=self._on_input, show=show)
        elif i["type"] == "bool":
            w = dpg.add_checkbox(label=i["name"], tag=tag, default_value=bool(v), user_data=ud,
                             callback=self._on_input, show=show)
        else:
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [0, 0, 0]
            w = dpg.add_color_edit([int(c) for c in rgb] + [255], label=i["name"], tag=tag, width=90,
                               no_alpha=True, no_inputs=True, user_data=ud, callback=self._on_input, show=show)
        self._widgets.add(w)

    def _on_input(self, sender, val):
        self.touch()
        nid, name = dpg.get_item_user_data(sender)
        self.snapshot(("in", nid, name))
        if isinstance(val, (list, tuple)) and len(val) >= 3 and all(isinstance(x, float) for x in val):
            val = [int(round(x * 255)) if x <= 1.0 else int(x) for x in val[:3]]
        self.graph.nodes[nid].setdefault("inputs", {})[name] = val

    def _show_input(self, b, inp, linked):
        tag = f"gin_{b}_{inp}"
        if dpg.does_item_exist(tag + "_t"):
            dpg.configure_item(tag + "_t", show=linked)
            dpg.configure_item(tag + "_w", show=not linked)

    def _param_widget(self, nid, n, p, multiline=False):
        v = n["params"].get(p["name"], p["default"])
        ud = (nid, p["name"])
        cb = self._on_param
        if p["type"] == "text" and multiline:
            w = dpg.add_input_text(width=220, height=90, multiline=True, default_value=str(v), user_data=ud,
                                   callback=cb)
            self._widgets.add(w)
            return
        if p["type"] == "float":
            w = dpg.add_input_float(label=p["name"], width=78, default_value=float(v), step=0,
                                format="%.3f", user_data=ud, callback=cb)
        elif p["type"] == "int":
            w = dpg.add_input_int(label=p["name"], width=78, default_value=int(v), step=0,
                              min_value=int(p.get("min", -1 << 30)), max_value=int(p.get("max", 1 << 30)),
                              min_clamped="min" in p, max_clamped="max" in p, user_data=ud, callback=cb)
        elif p["type"] == "bool":
            w = dpg.add_checkbox(label=p["name"], default_value=bool(v), user_data=ud, callback=cb)
        elif p["type"] == "choice":
            w = dpg.add_combo(p["choices"], label=p["name"], width=90, default_value=str(v), user_data=ud, callback=cb)
        elif p["type"] == "color":
            rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [255, 255, 255]
            w = dpg.add_color_edit([int(c) for c in rgb] + [255], label=p["name"], width=110, no_alpha=True,
                               user_data=ud, callback=cb)
        elif p["type"] == "text":
            w = dpg.add_input_text(label=p["name"], width=100, default_value=str(v), user_data=ud, callback=cb)
        else:
            return
        self._widgets.add(w)

    def _on_param(self, sender, val):
        self.touch()
        nid, name = dpg.get_item_user_data(sender)
        self.snapshot(("param", nid, name))
        if isinstance(val, (list, tuple)) and len(val) >= 3 and all(isinstance(x, float) for x in val):
            val = [int(round(x * 255)) if x <= 1.0 else int(x) for x in val[:3]]
        self.graph.nodes[nid]["params"][name] = val
        if self.graph.nodes[nid]["type"] == "Frame" and name in ("title", "colour"):
            self._sync_pos(); self.rebuild()
        if self.graph.nodes[nid]["type"] in ("Graph input", "Graph output") and name in ("name", "type"):
            if name == "type":
                # the pin changed type: its wires no longer fit
                self.graph.links = [l for l in self.graph.links if l[0] != nid and l[2] != nid]
            self.rebuild()

    def _make_link(self, a, out, b, inp):
        ta, tb = self._pins.get((a, "out", out)), self._pins.get((b, "in", inp))
        if not ta or not tb:
            return
        lid = dpg.add_node_link(ta, tb, parent="node_editor")
        meta = self.graph.link_meta.get((b, inp)) or {}
        col = meta.get("color")
        dpg.bind_item_theme(lid, self._wire_theme(tuple(col)) if col else self.themes().link[self._ptype.get(ta, "float")])
        self.links[lid] = (b, inp)
        self._show_input(b, inp, True)

    def _wire_theme(self, col):
        th = self._wire_themes.get(col)
        if th is None:
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvNodeLink):
                    dpg.add_theme_color(dpg.mvNodeCol_Link, col, category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkHovered, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
                    dpg.add_theme_color(dpg.mvNodeCol_LinkSelected, (255, 255, 255), category=dpg.mvThemeCat_Nodes)
            self._wire_themes[col] = th
        return th

    # --- editing callbacks ------------------------------------------------------------
    def on_link(self, sender, app_data):
        self.touch()
        out_attr, in_attr = app_data
        a, out = dpg.get_item_user_data(out_attr)
        b, inp = dpg.get_item_user_data(in_attr)
        ta, tb = self._ptype.get(out_attr), self._ptype.get(in_attr)
        if ta and tb and not compatible(ta, tb):
            self.status(f"cannot connect {ta} to {tb}")
            return
        self.snapshot()
        # replace whatever fed this input
        for lid, (bb, ii) in list(self.links.items()):
            if bb == b and ii == inp:
                dpg.delete_item(lid); self.links.pop(lid, None)
        self.graph.link(a, out, b, inp)
        self._make_link(a, out, b, inp)

    def on_delink(self, sender, app_data):
        self.touch()
        self.snapshot()
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
                self._drag_from = (nid, name)
                self._press_at = dpg.get_mouse_pos(local=False)
                break
        else:
            return
        th = self.themes()
        for (nid, kind, name), tag in self._pins.items():
            if kind == "in" and dpg.does_item_exist(tag):
                t = self._ptype.get(tag)
                dpg.bind_item_theme(tag, th.pin[t] if compatible(self._drag_type, t) else th.grey[t])

    def on_release(self):
        # a clicked frame comes to the front and would then take the clicks
        # meant for the nodes inside it: send it back behind them
        if self.graph and self._frame_last and dpg.does_item_exist("node_editor"):
            for fid in self._frame_last:
                if dpg.does_item_exist(f"gnode_{fid}") and dpg.is_item_hovered(f"gnode_{fid}"):
                    self._sync_pos(); self.rebuild()
                    break
        if self._drag_type is None:
            return
        t, frm = self._drag_type, self._drag_from
        self._drag_type = self._drag_from = None
        th = self.themes()
        for (nid, kind, name), tag in self._pins.items():
            if kind == "in" and dpg.does_item_exist(tag):
                dpg.bind_item_theme(tag, th.pin[self._ptype.get(tag, "float")])
        # A wire dropped on empty editor: offer the nodes it could feed, and
        # wire the one chosen. Over a pin or a node the drop is DPG's (a link
        # or nothing); a short drag is a click on the pin.
        mx, my = dpg.get_mouse_pos(local=False)
        if abs(mx - self._press_at[0]) + abs(my - self._press_at[1]) < 12:
            return
        if not dpg.is_item_hovered("node_editor"):
            return
        for (nid, kind, name), tag in self._pins.items():
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                return
        for nid in self.graph.nodes:
            if dpg.does_item_exist(f"gnode_{nid}") and dpg.is_item_hovered(f"gnode_{nid}"):
                return
        ex, ey = dpg.get_item_rect_min("node_editor")
        self._menu_pos = (max(0, mx - ex - 20), max(0, my - ey - 10))
        self._pending = (frm[0], frm[1], t)
        self.show_add_menu((mx, my), only=self._consumers(t, limit=60))

    # --- the right-click menus -------------------------------------------------------------
    def open_menu(self):
        """Right click: over a pin, the pin's menu; over a node, the node's;
        over empty editor, the add-node menu at the pointer."""
        if not dpg.does_item_exist("node_editor") or not dpg.is_item_hovered("node_editor"):
            return
        mx, my = dpg.get_mouse_pos(local=False)
        for (nid, kind, name), tag in self._pins.items():
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                self._ctx = (kind, nid, name)
                self._fill_ctx_menu()
                dpg.configure_item("graph_ctx", show=True); dpg.set_item_pos("graph_ctx", [mx, my])
                return
        for nid in list(self.graph.nodes) if self.graph else []:
            tag = f"gnode_{nid}"
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                self._ctx = ("node", nid, None)
                self._fill_ctx_menu()
                dpg.configure_item("graph_ctx", show=True); dpg.set_item_pos("graph_ctx", [mx, my])
                return
        ex, ey = dpg.get_item_rect_min("node_editor")
        self._menu_pos = (max(0, mx - ex - 20), max(0, my - ey - 10))
        self._pending = None
        self.show_add_menu((mx, my))

    def show_add_menu(self, at, only=None, focus=True):
        """The add menu at a screen position, its search box focused and
        empty. `only` narrows it to those node types (a dropped wire)."""
        self._only = only
        dpg.set_value("graph_search", "")
        self._search("graph_search", "")
        dpg.configure_item("graph_menu", show=True)
        dpg.set_item_pos("graph_menu", list(at))
        if focus:
            dpg.focus_item("graph_search")

    def _search(self, sender, text):
        """Filter the add menu: with text, a flat list of matches on name or
        description; without, the categories (or the dropped wire's list)."""
        text = (text or "").strip().lower()
        only = getattr(self, "_only", None)
        flat = bool(text) or only is not None
        dpg.configure_item("graph_cats", show=not flat)
        dpg.configure_item("graph_hits", show=flat)
        if not flat:
            return
        dpg.delete_item("graph_hits", children_only=True)
        names = only if only is not None else [n.split(" / ", 1)[1] for n in self.type_names()]
        hits = []
        for n in names:
            d = self.lib.get(n, {})
            lbl = d.get("label", n)
            if not text or text in lbl.lower() or text in n.lower() or text in d.get("doc", "").lower():
                hits.append((0 if text and lbl.lower().startswith(text) else 1, lbl, n))
        if text:
            hits.sort()                    # else the given order: most useful first
        if only is not None and not text:
            dpg.add_text("connect to a new", parent="graph_hits", color=DIM)
        for _, lbl, n in hits[:24]:
            dpg.add_selectable(label=lbl, parent="graph_hits", user_data=n,
                               callback=lambda s, a, u: self.add_node_at_menu(u))
        if not hits:
            dpg.add_text("no match", parent="graph_hits", color=DIM)
        rows = min(len(hits), 24) + (1 if only is not None and not text else 0)
        dpg.configure_item("graph_hits", height=max(30, 21 * max(rows, 1) + 12))

    def _search_enter(self, sender, text):
        """Enter in the search box adds the first hit."""
        kids = dpg.get_item_children("graph_hits", 1) or []
        for k in kids:
            u = dpg.get_item_user_data(k)
            if u:
                self.add_node_at_menu(u)
                return

    def _fill_ctx_menu(self):
        """The context menu's rows, for whatever was right-clicked."""
        dpg.delete_item("graph_ctx", children_only=True)
        kind, nid, name = self._ctx
        n = self.graph.nodes[nid]
        d = self.graph.node_def(n)
        P = "graph_ctx"
        close = lambda: dpg.configure_item(P, show=False)

        def row(label, fn):
            dpg.add_selectable(label=label, parent=P, callback=lambda s, a, u=fn: (close(), u()))

        if kind == "in":
            linked = any(l[2] == nid and l[3] == name for l in self.graph.links)
            dpg.add_text(f"{n['type']} . {name}", parent=P, color=DIM)
            if linked:
                row("disconnect", lambda: self._disconnect_in(nid, name))
                self._colour_rows(P, [(nid, name)])
            i = next(x for x in d["inputs"] if x["name"] == name)
            if linked:
                a, out = next((l[0], l[1]) for l in self.graph.links if l[2] == nid and l[3] == name)
                at = next((o["type"] for o in self.graph.node_def(self.graph.nodes[a])["outputs"] if o["name"] == out), "float")
                between = self._between(at, i["type"])
                if between:
                    dpg.add_text("insert on the wire", parent=P, color=DIM)
                    for t in between[:8]:
                        row(f"  {t}", lambda t=t: self._insert_before(nid, name, t))
            row("reset to default", lambda: self._reset_input(nid, name, i))
            # expose this input as a control: a slider or checkbox node, wired in
            ctrls = ["Speed", "Intensity", "Custom 1", "Custom 2", "Custom 3"] if i["type"] != "bool" \
                    else ["Check 1", "Check 2", "Check 3"]
            if i["type"] != "color":
                dpg.add_text("drive with", parent=P, color=DIM)
                for c in ctrls:
                    row(f"  {c}", lambda c=c: self._drive_with(nid, name, c))
        elif kind == "out":
            outs = [l for l in self.graph.links if l[0] == nid and l[1] == name]
            dpg.add_text(f"{n['type']} . {name}", parent=P, color=DIM)
            if outs:
                row(f"disconnect all ({len(outs)})", lambda: self._disconnect_out(nid, name))
                self._colour_rows(P, [(l[2], l[3]) for l in outs])
            o = next(x for x in d["outputs"] if x["name"] == name)
            if self.preview == (nid, name):
                row("stop previewing this output", self.stop_preview)
            else:
                row("preview this output", lambda: self.preview_pin(nid, name))
            dpg.add_text("connect to new", parent=P, color=DIM)
            for t in self._consumers(o["type"]):
                row(f"  {t}", lambda t=t: self._connect_new(nid, name, o["type"], t))
        else:
            dpg.add_text(d.get("label") or n["type"], parent=P, color=DIM)
            if nid in self.problems:
                m = self.problems[nid]
                dpg.add_text(m, parent=P, color=(235, 80, 70) if m.startswith("error") else (240, 190, 70))
            if n["type"].startswith(G.SUB):
                row("edit sub-graph", lambda: self.enter_sub(nid))
            if dpg.get_selected_nodes("node_editor"):
                row("fold selection into a sub-graph", lambda: self.make_sub_from_selection(dpg.get_value("graph_new_name")))
                row("copy selection", self.copy)
                row("cut selection", self.cut)
            row("duplicate", lambda: self._dup(nid))
            if d["inputs"] or d["params"]:
                row("expand" if n.get("collapsed") else "collapse", lambda: self._collapse(nid))
            row("disconnect all", lambda: self._disconnect_node(nid))
            row("delete", lambda: self._delete_node(nid))
            self._node_colour_rows(P, nid)

    def _node_colour_rows(self, P, nid):
        dpg.add_text("node colour", parent=P, color=DIM)
        for chunk in (WIRE_COLOURS[:5], WIRE_COLOURS[5:]):
            with dpg.group(parent=P, horizontal=True):
                for label, col in chunk:
                    if col is None:
                        dpg.add_button(label="auto", small=True,
                                       callback=lambda: (dpg.configure_item(P, show=False), self._set_colour(nid, None)))
                    else:
                        dpg.add_color_button(default_value=list(col) + [255], width=18, height=18, no_border=True,
                                             callback=lambda s, a, c=col: (dpg.configure_item(P, show=False), self._set_colour(nid, c)))

    def _set_colour(self, nid, col):
        self.snapshot(); self._sync_pos()
        if col is None:
            self.graph.nodes[nid].pop("color", None)
        else:
            self.graph.nodes[nid]["color"] = list(col)
        self.rebuild()

    def _collapse(self, nid):
        self.snapshot(); self._sync_pos()
        n = self.graph.nodes[nid]
        n["collapsed"] = not n.get("collapsed")
        self.rebuild()

    def _between(self, at, bt):
        """Node types that can sit on a wire of type at -> bt: an input that
        takes `at`, an output that gives `bt`."""
        prefer = ["Knot", "Knot colour", "Scale", "Multiply", "Add", "Remap", "Smoothstep", "Clamp", "Abs", "Fade",
                  "Blend", "Mask", "Mix", "Select", "Threshold", "Expression", "Colour expression"]
        out = []
        for name in prefer + sorted(self.lib):
            d = self.lib.get(name)
            if not d or name in out or d.get("decor"):
                continue
            if any(compatible(at, i["type"]) for i in d["inputs"]) and any(compatible(o["type"], bt) for o in d["outputs"]):
                out.append(name)
        return out

    def _insert_before(self, nid, name, new_type):
        """Splice a node into the wire feeding this input."""
        self.snapshot(); self._sync_pos()
        a, out = next((l[0], l[1]) for l in self.graph.links if l[2] == nid and l[3] == name)
        d = self.lib[new_type]
        bt = next(i["type"] for i in self.graph.node_def(self.graph.nodes[nid])["inputs"] if i["name"] == name)
        at = next(o["type"] for o in self.graph.node_def(self.graph.nodes[a])["outputs"] if o["name"] == out)
        inp = next(i["name"] for i in d["inputs"] if compatible(at, i["type"]))
        outp = next(o["name"] for o in d["outputs"] if compatible(o["type"], bt))
        pa, pb = self.graph.nodes[a]["pos"], self.graph.nodes[nid]["pos"]
        new = self.graph.add(new_type, ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2 + 20))
        self.graph.link(a, out, new, inp)
        self.graph.link(new, outp, nid, name)
        self.rebuild()

    def _colour_rows(self, P, keys):
        dpg.add_text("wire colour", parent=P, color=DIM)
        # two rows of five, so the swatches never run past the menu's edge
        for chunk in (WIRE_COLOURS[:5], WIRE_COLOURS[5:]):
            with dpg.group(parent=P, horizontal=True):
                for label, col in chunk:
                    if col is None:
                        dpg.add_button(label="auto", small=True,
                                       callback=lambda s, a, k=keys: (dpg.configure_item(P, show=False), self._set_wire(k, None)))
                    else:
                        dpg.add_color_button(default_value=list(col) + [255], width=18, height=18, no_border=True,
                                             callback=lambda s, a, k=keys, c=col: (dpg.configure_item(P, show=False), self._set_wire(k, c)))

    def _set_wire(self, keys, col):
        self.snapshot()
        for k in keys:
            if col is None:
                self.graph.link_meta.pop(k, None)
            else:
                self.graph.link_meta[k] = {"color": list(col)}
        self.rebuild()

    def _disconnect_in(self, nid, name):
        self.snapshot(); self.graph.unlink(nid, name); self.rebuild()

    def _disconnect_out(self, nid, name):
        self.snapshot(); self.graph.unlink_out(nid, name); self.rebuild()

    def _disconnect_node(self, nid):
        self.snapshot()
        for l in [l for l in self.graph.links if l[0] == nid or l[2] == nid]:
            self.graph.unlink(l[2], l[3])
        self.rebuild()

    def _reset_input(self, nid, name, i):
        self.snapshot()
        self.graph.nodes[nid].setdefault("inputs", {}).pop(name, None)
        self.rebuild()

    def _drive_with(self, nid, name, ctrl):
        """A control node feeding this input - reuse one already in the graph,
        else add one just to the left."""
        self.snapshot()
        existing = next((m["id"] for m in self.graph.nodes.values() if m["type"] == ctrl), None)
        if existing is None:
            pos = self.graph.nodes[nid]["pos"]
            existing = self.graph.add(ctrl, (max(0, pos[0] - 220), pos[1]))
        out = self.lib[ctrl]["outputs"][0]["name"]
        self.graph.link(existing, out, nid, name)
        self.rebuild()

    def _consumers(self, t, limit=14):
        """Node types with a first input this output can feed, most useful first."""
        prefer = ["Palette", "Blend", "Mask", "Scale", "HSV", "Add", "Multiply", "Mix", "Remap",
                  "Smoothstep", "Wave", "Noise", "Select", "Threshold", "Output", "Split", "Fade"]
        out = []
        for name in prefer + sorted(self.lib):
            d = self.lib.get(name)
            if not d or name in out or not d["inputs"]:
                continue
            if any(compatible(t, i["type"]) for i in d["inputs"]):
                out.append(name)
        return out[:limit]

    def _connect_new(self, nid, out_name, t, new_type):
        self.snapshot()
        d = self.lib[new_type]
        inp = next(i["name"] for i in d["inputs"] if compatible(t, i["type"]))
        pos = self.graph.nodes[nid]["pos"]
        new = self.graph.add(new_type, (pos[0] + 230, pos[1]))
        self.graph.link(nid, out_name, new, inp)
        self.rebuild()

    def _dup(self, nid):
        self.snapshot(); self.graph.duplicate(nid); self.rebuild()

    def _delete_node(self, nid):
        self.snapshot(); self.graph.remove(nid); self.rebuild()

    def fill_add_menu(self):
        """The right-click add menu, rebuilt whenever the library changes so
        new sub-graphs appear in it."""
        if not dpg.does_item_exist("graph_menu"):
            return
        dpg.delete_item("graph_menu", children_only=True)
        cats = {}
        for name in self.type_names():
            c, n = name.split(" / ", 1)
            cats.setdefault(c, []).append(n)
        with dpg.group(horizontal=True, parent="graph_menu"):
            dpg.add_button(label="undo", small=True, callback=lambda: (self._hide_menus(), self.undo()))
            dpg.add_button(label="redo", small=True, callback=lambda: (self._hide_menus(), self.redo()))
            dpg.add_button(label="paste here", small=True,
                           callback=lambda: (self._hide_menus(), self.paste(self._menu_pos)))
        dpg.add_input_text(tag="graph_search", parent="graph_menu", hint="search nodes", width=200,
                           callback=self._search, on_enter=False)
        # on_enter would stop the per-keystroke callback; Enter is read separately
        dpg.add_text("add node", parent="graph_menu", color=DIM)
        # child windows rather than groups: a collapsing header stretches to
        # its parent, and an autosized popup would stretch with it
        dpg.add_child_window(tag="graph_hits", parent="graph_menu", show=False, width=230, height=60,
                             border=False)
        with dpg.child_window(tag="graph_cats", parent="graph_menu", width=230, height=430, border=False):
            for c, names in cats.items():
                with dpg.collapsing_header(label=c, default_open=(c in ("generate", "colour", "subgraphs"))):
                    for n in names:
                        lbl = self.lib[n].get("label", n) if n in self.lib else n
                        dpg.add_selectable(label=lbl, user_data=n,
                                           callback=lambda s, a, u: self.add_node_at_menu(u))
        self._widgets.add("graph_search")

    def _hide_menus(self):
        for t in ("graph_menu", "graph_ctx"):
            if dpg.does_item_exist(t):
                dpg.configure_item(t, show=False)

    def add_node_at_menu(self, type_):
        self.touch()
        dpg.configure_item("graph_menu", show=False)
        if not self.graph or type_ not in self.lib:
            return
        self.snapshot()
        nid = self.graph.add(type_, self._menu_pos)
        self._make_node(nid, self.graph.nodes[nid])
        if type_ == "Frame":
            self._sync_pos(); self.rebuild()      # behind the nodes it now covers
        if self._pending:
            a, out, t = self._pending
            self._pending = None
            d = self.graph.node_def(self.graph.nodes[nid])
            inp = next((i["name"] for i in d["inputs"] if compatible(t, i["type"])), None)
            if inp and a in self.graph.nodes:
                self.graph.link(a, out, nid, inp)
                self.rebuild()

    def add_node(self, type_):
        self.touch()
        if not self.graph or type_ not in self.lib:
            return
        self.snapshot()
        self._add_count += 1
        pos = (60 + 30 * (self._add_count % 8), 60 + 30 * (self._add_count % 8))
        nid = self.graph.add(type_, pos)
        self._make_node(nid, self.graph.nodes[nid])

    def delete_selected(self):
        if not self.graph or not dpg.get_selected_nodes("node_editor"):
            return
        self.snapshot()
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
    # --- pin preview ---------------------------------------------------------------------
    # "Preview this output" builds the graph with that pin shown instead of
    # the Output: a colour straight, a float or bool as a grey level. The
    # effect is a draft named Preview; the graph's own file is untouched,
    # and every compile while the preview is on shows the pin.
    PREVIEW_FILE = "_preview.cpp"

    def preview_pin(self, nid, name):
        self.preview = (nid, name)
        self.status(f"previewing {self.graph.nodes[nid]['type']} . {name}")
        self.compile()

    def stop_preview(self):
        self.preview = None
        p = self.app.project
        if self.PREVIEW_FILE in p.effect_files():
            os.remove(p.effect_path(self.PREVIEW_FILE))
        self.compile()

    def _preview_graph(self):
        """A copy of the graph with the previewed pin driving a fresh Output."""
        nid, name = self.preview
        if nid not in self.graph.nodes:
            self.preview = None
            return None
        g = G.Graph(self.graph.to_json(), lib=self.lib, resolver=self.resolve_sub)
        for o in [m for m, n in g.nodes.items() if n["type"] == "Output"]:
            g.remove(o)
        d = g.node_def(g.nodes[nid])
        t = next((o["type"] for o in d["outputs"] if o["name"] == name), "float")
        pos = g.nodes[nid]["pos"]
        out = g.add("Output", (pos[0] + 400, pos[1]))
        if t == "color":
            g.link(nid, name, out, "color")
        else:
            hsv = g.add("HSV", (pos[0] + 200, pos[1]))
            g.nodes[hsv]["inputs"] = {"h": 0.0, "s": 0.0}
            g.link(nid, name, hsv, "v")
            g.link(hsv, "color", out, "color")
        g.name = "Preview"
        return g

    def compile(self, and_build=True):
        """Graph -> effects/<graph>.cpp -> the normal build and reload."""
        if not self.graph:
            return
        self.save()
        g = self.graph
        fname = os.path.splitext(self.file)[0] + ".cpp"
        if self.preview:
            g = self._preview_graph()
            if g is not None:
                fname = self.PREVIEW_FILE
        try:
            src = (g or self.graph).compile()
        except G.GraphError as e:
            self.status(f"graph: {e}")
            self._mark_problems()
            return None
        self.app.project.write_effect(fname, src)
        self.status(f"wrote {fname}" + (f" (previewing {self.preview[1]} of #{self.preview[0]})" if self.preview else ""))
        if and_build:
            # the code pane follows: edit_build saves what the pane holds, and
            # that must be this file, not whatever was open before
            self.app.edit_open(fname)
            self.app.edit_build()
        return fname

    def import_effect(self):
        """The graph's effect joins the list - generated first if it has not
        been - or leaves it."""
        f = self.effect_file()
        if not f:
            return
        if f not in self.app.project.effect_files() and not self.app.project.is_imported(f):
            if self.compile(and_build=False) is None:
                return
        self.app.toggle_import(f)

    def type_names(self):
        cats = {}
        for n, d in self.lib.items():
            cats.setdefault(d["cat"], []).append(n)
        out = []
        for c in ("controls", "signals", "coords", "generate", "maths", "colour", "graph", "subgraphs", "custom", "output"):
            out += [f"{c} / {n}" for n in sorted(cats.pop(c, []))]
        for c, ns in sorted(cats.items()):
            out += [f"{c} / {n}" for n in sorted(ns)]
        return out


def build_panel(app, panel):
    """The graph pane's widgets. Called once from build()."""
    with dpg.group(horizontal=True):
        dpg.add_button(label="< back", tag="graph_back", show=False, callback=lambda: panel.back())
        dpg.add_combo(panel.files(), tag="graph_file", width=170, default_value=panel.file or "",
                      callback=lambda s, v: panel.open(v))
        dpg.add_button(label="save", callback=lambda: panel.save())
        dpg.add_button(label="compile + reload", callback=lambda: panel.compile())
        dpg.add_checkbox(label="live", tag="graph_auto", default_value=panel.auto,
                         callback=lambda s, v: panel.set_auto(v))
        dpg.add_button(label="open as code", callback=lambda: app.open_graph_code())
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="graph_new_name", hint="new / renamed graph name", width=170,
                           on_enter=True, callback=lambda s, v: panel.new(v))
        dpg.add_button(label="new", callback=lambda: panel.new(dpg.get_value("graph_new_name")))
        dpg.add_button(label="rename", callback=lambda: panel.rename(dpg.get_value("graph_new_name")))
        dpg.add_button(label="import to list", tag="graph_import",
                       callback=lambda: panel.import_effect())
    with dpg.group(horizontal=True):
        dpg.add_combo(panel.type_names(), tag="graph_add_type", width=190, default_value="generate / Noise",
                      callback=lambda s, v: dpg.set_value("graph_status",
                                                          panel.lib.get(v.split(" / ", 1)[1], {}).get("doc", "")))
        dpg.add_button(label="add node", callback=lambda: panel.add_node(dpg.get_value("graph_add_type").split(" / ", 1)[1]))
        dpg.add_button(label="delete selected", callback=lambda: panel.delete_selected())
        dpg.add_button(label="fold into sub-graph",
                       callback=lambda: panel.make_sub_from_selection(dpg.get_value("graph_new_name")))
    dpg.add_text("", tag="graph_status", color=DIM)
    with dpg.node_editor(tag="node_editor", callback=panel.on_link, delink_callback=panel.on_delink,
                         minimap=True, minimap_location=dpg.mvNodeMiniMap_Location_BottomRight,
                         width=-1, height=-1):
        pass
    # The right-click menu: a small window shown at the pointer, categories as
    # collapsing headers, a node per line. A window rather than a popup so it
    # can be positioned exactly and dismissed by the click that adds.
    with dpg.window(tag="graph_ctx", show=False, no_title_bar=True, no_resize=True, no_move=True,
                    autosize=True, popup=True):
        pass
    with dpg.window(tag="graph_menu", show=False, no_title_bar=True, no_resize=True, no_move=True,
                    autosize=True, popup=True):
        pass
    panel.fill_add_menu()
