"""
The node graph, and its compiler to a WLED effect.

A graph is nodes and links:

    {"name": "Aurora", "nodes": [{"id": 3, "type": "Noise", "pos": [x, y],
                                  "params": {...}}, ...],
     "links": [[from_id, "out", to_id, "in"], ...]}

compile() turns it into ONE ordinary effect file - the same shape as a
hand-written one, so it drops into a firmware build unchanged:

    helpers
    static FX_RET mode_<ident>() {
      guard, dimensions
      frame scope: t, dt, then every node that needs no coordinate, in order
      per pixel: the prologue (u, v, cx, cy, r, ang, nx, ny, nz), then every
                 remaining node in order, then the Output
    }
    metadata, registration

The order is a topological sort of the links, so a node is always emitted
after the nodes it reads. A cycle is an error - feedback is the Previous node,
which reads last frame's buffer rather than this frame's graph.

HOISTING is the one optimisation, and it matters: a Multiply of two sliders
computed per pixel is 1,280 multiplies a frame for nothing. Any node whose
template reads no per-pixel name and whose inputs are all frame-scope is
emitted at frame scope. Coords, Direction, Pixel, Previous, Ripple and
Sparkle read the prologue and stay per pixel; everything downstream of them
does too.

Type rules are small: float and bool coerce both ways (0/1, > 0.5), colour
converts to nothing. An unconnected input takes its default.
"""
import json
import re

from native.nodedefs import library, HELPERS

PIXEL_NAMES = re.compile(r"\b(px|py|u|v|cx|cy|r|ang|nx|ny|nz|W|H|N|gc_out)\b")
TYPES = {"float": "float", "color": "uint32_t", "bool": "bool"}


class GraphError(ValueError):
    pass


def _ident(name):
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    if not s or s[0].isdigit():
        s = "fx_" + s
    return s


def _lit(t, v):
    """A C++ literal of type t for default/param value v."""
    if t == "float":
        return f"{float(v)}f"
    if t == "bool":
        return "true" if v else "false"
    if t == "color":
        if isinstance(v, (list, tuple)):
            r, g, b = (int(x) for x in v[:3])
            return f"0x{(r << 16) | (g << 8) | b:06X}u"
        return f"{int(v)}u"
    if t == "int":
        return str(int(v))
    return str(v)


def _coerce(expr, have, want):
    if have == want:
        return expr
    if have == "bool" and want == "float":
        return f"({expr} ? 1.0f : 0.0f)"
    if have == "float" and want == "bool":
        return f"({expr} > 0.5f)"
    raise GraphError(f"cannot connect {have} to {want}")


class Graph:
    def __init__(self, d=None, lib=None):
        self.lib = lib or library()
        d = d or {}
        self.name = d.get("name", "Untitled")
        self.nodes = {int(n["id"]): dict(n, id=int(n["id"])) for n in d.get("nodes", [])}
        self.links = [tuple(l) for l in d.get("links", [])]
        self._next = max(self.nodes.keys(), default=0) + 1

    # --- editing -----------------------------------------------------------
    def add(self, type_, pos=(0, 0), params=None):
        if type_ not in self.lib:
            raise GraphError(f"no node type {type_!r}")
        d = self.lib[type_]
        p = {q["name"]: q["default"] for q in d["params"]}
        if params:
            p.update(params)
        nid = self._next; self._next += 1
        self.nodes[nid] = {"id": nid, "type": type_, "pos": list(pos), "params": p}
        return nid

    def remove(self, nid):
        self.nodes.pop(nid, None)
        self.links = [l for l in self.links if l[0] != nid and l[2] != nid]

    def link(self, a, out, b, inp):
        # one link per input
        self.links = [l for l in self.links if not (l[2] == b and l[3] == inp)]
        self.links.append((a, out, b, inp))

    def unlink(self, b, inp):
        self.links = [l for l in self.links if not (l[2] == b and l[3] == inp)]

    def to_json(self):
        return {"name": self.name,
                "nodes": [dict(n) for n in self.nodes.values()],
                "links": [list(l) for l in self.links]}

    # --- compile -------------------------------------------------------------
    def _order(self):
        deps = {nid: set() for nid in self.nodes}
        for a, _, b, _ in self.links:
            if a in deps and b in deps:
                deps[b].add(a)
        out, seen, temp = [], set(), set()

        def visit(n):
            if n in seen:
                return
            if n in temp:
                raise GraphError(f"cycle through node {n} ({self.nodes[n]['type']}) - use Previous for feedback")
            temp.add(n)
            for d in sorted(deps[n]):
                visit(d)
            temp.discard(n); seen.add(n); out.append(n)
        for n in sorted(self.nodes):
            visit(n)
        return out

    def compile(self, title=None):
        """The effect as C++ text. Raises GraphError with a message worth
        showing when the graph cannot be compiled."""
        title = title or self.name
        ident = _ident(title)
        outs = [n for n in self.nodes.values() if n["type"] == "Output"]
        if len(outs) != 1:
            raise GraphError("the graph needs exactly one Output node" + (f" (it has {len(outs)})" if outs else ""))
        for n in self.nodes.values():
            if n["type"] not in self.lib:
                raise GraphError(f"node {n['id']}: unknown type {n['type']!r}")
        order = self._order()
        src_of = {(b, inp): (a, out) for a, out, b, inp in self.links}

        # scope: frame nodes, then anything hoistable whose inputs are all frame
        scope = {}
        for nid in order:
            d = self.lib[self.nodes[nid]["type"]]
            if d["scope"] == "frame":
                scope[nid] = "frame"; continue
            if PIXEL_NAMES.search(d["code"]):
                scope[nid] = "pixel"; continue
            ups = [src_of[(nid, i["name"])][0] for i in d["inputs"] if (nid, i["name"]) in src_of]
            scope[nid] = "frame" if all(scope.get(u) == "frame" for u in ups) else "pixel"

        def var(nid, out):
            return f"n{nid}_{re.sub(r'[^A-Za-z0-9]', '_', out)}"

        def expand(nid):
            n = self.nodes[nid]; d = self.lib[n["type"]]
            code = d["code"]
            otypes = {o["name"]: o["type"] for o in d["outputs"]}
            # inputs
            for i in d["inputs"]:
                key = (nid, i["name"])
                if key in src_of:
                    a, out = src_of[key]
                    ad = self.lib[self.nodes[a]["type"]]
                    at = next((o["type"] for o in ad["outputs"] if o["name"] == out), None)
                    if at is None:
                        raise GraphError(f"node {a} has no output {out!r}")
                    expr = _coerce(var(a, out), at, i["type"])
                else:
                    expr = _lit(i["type"], i.get("default", 0))
                code = code.replace(f"$in.{i['name']}", expr)
            for o in d["outputs"]:
                code = code.replace(f"$out.{o['name']}", var(nid, o["name"]))
            for p in d["params"]:
                v = n["params"].get(p["name"], p["default"])
                if p["type"] == "color":
                    rgb = list(v)[:3] if isinstance(v, (list, tuple)) else [255, 255, 255]
                    for k, c in zip("rgb", rgb):
                        code = code.replace(f"$p.{p['name']}_{k}", str(int(c)))
                elif p["type"] == "text":
                    code = code.replace(f"$p.{p['name']}", str(v).replace('"', "'"))
                elif p["type"] == "choice":
                    code = code.replace(f"$p.{p['name']}", str(v))
                else:
                    code = code.replace(f"$p.{p['name']}", _lit(p["type"], v))
            if "$in." in code or "$out." in code or "$p." in code:
                m = re.search(r"\$(in|out|p)\.\w+", code)
                raise GraphError(f"node {n['type']}: template refers to unknown {m.group(0)}")
            code = code.replace("$$", "$")
            decl = "".join(f"{TYPES[o['type']]} {var(nid, o['name'])} = 0; " for o in d["outputs"])
            return f"      // {n['type']} #{nid}\n      {decl}\n      " + code.replace("\n", "\n      ") + "\n"

        frame = "".join(expand(nid) for nid in order if scope[nid] == "frame")
        pixel = "".join(expand(nid) for nid in order if scope[nid] == "pixel")

        # metadata: slider labels from the control nodes that are present
        labels = ["", "", "", "", "", "", "", ""]
        slot = {"Speed": 0, "Intensity": 1, "Custom 1": 2, "Custom 2": 3, "Custom 3": 4,
                "Check 1": 5, "Check 2": 6, "Check 3": 7}
        for n in self.nodes.values():
            if n["type"] in slot:
                labels[slot[n["type"]]] = str(n["params"].get("label", n["type"])).replace(",", " ").replace(";", " ")
        meta = f'{title.replace(chr(34), chr(39))}@{",".join(labels)};;!;12;sx=128,ix=128,pal=11'

        return GENERATED.format(title=title, ident=ident, upper=ident.upper(), helpers=HELPERS,
                                frame=frame, pixel=pixel, meta=meta)


GENERATED = r'''#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// {title} - generated by the WLED Effect Studio node editor
// ===========================================================================
// An ordinary effect: drop it into a usermod folder that has cube_fx_common.h
// and cube_fx_bank.h beside it and it compiles into the firmware unchanged.
// Edit the graph and regenerate, or edit this file by hand from here on.
// ===========================================================================
{helpers}
static FX_RET mode_{ident}() {{
  if (!strip.isMatrix && !SEGMENT.is2D() && SEGLEN < 1) {{ FX_DONE; }}
  const bool is2d = SEGMENT.is2D();
  const int W = is2d ? SEG_W : SEGLEN, H = is2d ? SEG_H : 1;
  const int N = W * H;
  const bool cube = is2d && cfx_isCube(W, H);
  const int  B    = cube ? (W / 3) : 1;
  static uint8_t clk_[2] = {{0, 0}};
  const uint16_t dt = fx_dt8(clk_);
  const float t = (float)strip.now * 0.001f;
  (void)N; (void)dt; (void)t;

  // --- frame scope -----------------------------------------------------------
{frame}
  // --- per pixel ---------------------------------------------------------------
  const int cols = W, rows = H; (void)rows;          // the net-skip macros' names
  CFX_NET_PREP();
  for (int py = 0; py < H; py++) {{
    CFX_NET_ROW(py);
    for (int px = 0; px < W; px++) {{
      CFX_NET_SKIP(px);
      const float u = (W > 1) ? (float)px / (float)(W - 1) : 0.5f;
      const float v = (H > 1) ? (float)py / (float)(H - 1) : 0.5f;
      const float cx = u * 2.0f - 1.0f, cy = 1.0f - v * 2.0f;
      const float r = sqrtf(cx * cx + cy * cy);
      const float ang = cfx_atan2f(cy, cx);
      float nx, ny, nz;
      if (cube) {{
        float X, Y, Z; cfx_pos(px, py, W, H, B, true, X, Y, Z);
        const float L = sqrtf(X * X + Y * Y + Z * Z); const float iL = L > 1e-6f ? 1.0f / L : 1.0f;
        nx = X * iL; ny = Y * iL; nz = Z * iL;
      }} else {{
        const float Z = 1.0f - (cx * cx + cy * cy) * 0.5f;
        const float L = sqrtf(cx * cx + cy * cy + Z * Z); const float iL = L > 1e-6f ? 1.0f / L : 1.0f;
        nx = cx * iL; ny = cy * iL; nz = Z * iL;
      }}
      (void)u; (void)v; (void)r; (void)ang; (void)nx; (void)ny; (void)nz;
      uint32_t gc_out = 0;
{pixel}
      if (is2d) SEGMENT.setPixelColorXY(px, py, gc_out); else SEGMENT.setPixelColor(px, gc_out);
    }}
  }}
  FX_DONE;
}}

static const char _data_FX_MODE_{upper}[] PROGMEM = "{meta}";
static CfxBankReg {ident}_reg(&mode_{ident}, _data_FX_MODE_{upper});
'''


def load(path, lib=None):
    return Graph(json.load(open(path, encoding="utf-8")), lib=lib)


def save(graph, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph.to_json(), f, indent=1)


def starter(name="New Graph", lib=None):
    """The graph a new file starts as: a palette gradient scrolled by Speed,
    so there is something on the LEDs the moment it compiles."""
    g = Graph({"name": name}, lib=lib)
    sp = g.add("Speed", (40, 40))
    tm = g.add("Time", (40, 140))
    mul = g.add("Multiply", (260, 90))
    co = g.add("Coords", (40, 260))
    ad = g.add("Add", (460, 180))
    pal = g.add("Palette", (660, 180))
    out = g.add("Output", (860, 180))
    g.link(sp, "value", mul, "a"); g.link(tm, "t", mul, "b")
    g.link(co, "u", ad, "a"); g.link(mul, "result", ad, "b")
    g.link(ad, "result", pal, "index")
    g.link(pal, "color", out, "color")
    return g
