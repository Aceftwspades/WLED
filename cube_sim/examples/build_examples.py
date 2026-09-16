"""
The example graphs, written out by script so they stay reproducible: five
cube_fx effects rebuilt from nodes. Run from cube_sim:

    python examples/build_examples.py            # writes examples/graphs/*.json
    python examples/build_examples.py --check    # and compiles + builds them

Each is a reading of the C++ original in nodes - the same coordinates, the
same drivers, the same look - not a line-for-line port. Where the original
keeps per-pixel state (Cube Fire's heat field, Matrix Rain's drops) the graph
uses the feedback and hash nodes instead, the way a shader would.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from native import graph as G          # noqa: E402

OUT = os.path.join(HERE, "graphs")


class GB:
    """A graph builder: n() adds a node at a grid column/row, l() links."""
    def __init__(self, name):
        self.g = G.Graph({"name": name})
        self.col_w, self.row_h = 230, 130

    def n(self, type_, col, row, params=None, inputs=None):
        nid = self.g.add(type_, (40 + col * self.col_w, 40 + row * self.row_h), params or {})
        if inputs:
            self.g.nodes[nid]["inputs"] = dict(inputs)
        return nid

    def l(self, a, o, b, i):
        self.g.link(a, o, b, i)
        return b

    def save(self, fname):
        os.makedirs(OUT, exist_ok=True)
        G.save(self.g, os.path.join(OUT, fname))
        return self.g


# ---------------------------------------------------------------------------
def slab_cut():
    """Cube Slice: spectrum slabs cutting through the solid at a tumbling
    angle, re-aimed on the beat. Position . normal gives the slab number."""
    b = GB("Slab Cut")
    sp = b.n("Speed", 0, 0, {"label": "Tumble speed", "default": 70})
    it = b.n("Intensity", 0, 1, {"label": "Slab width", "default": 100})
    c1 = b.n("Custom 1", 0, 2, {"label": "Slab count", "default": 100})
    c2 = b.n("Custom 2", 0, 3, {"label": "Scroll speed", "default": 80})
    c3 = b.n("Custom 3", 0, 4, {"label": "Bass push", "default": 8})
    k1 = b.n("Check 1", 0, 5, {"label": "Re-aim on beat", "default": True})
    k2 = b.n("Check 2", 0, 6, {"label": "Reverse", "default": False})
    au = b.n("Audio", 0, 7)
    b.n("Effect settings", 0, 8, {"palette": 11, "audio": "frequency"})
    # the tumble: two angles from one running phase, the first kicked by a random on each beat
    rate = b.n("Multiply", 1, 0, inputs={"b": 0.12}); b.l(sp, "value", rate, "a")
    ang = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(rate, "result", ang, "rate")
    rnd = b.n("Random hold", 1, 6); b.l(au, "beat", rnd, "trigger")
    re = b.n("Select", 2, 6, inputs={"a": 0.0}); b.l(k1, "on", re, "on"); b.l(rnd, "value", re, "b")
    a = b.n("Add", 3, 0); b.l(ang, "value", a, "a"); b.l(re, "result", a, "b")
    half = b.n("Multiply", 3, 1, inputs={"b": 0.5}); b.l(ang, "value", half, "a")
    bb = b.n("Add", 4, 1, inputs={"b": 0.25}); b.l(half, "result", bb, "a")
    nrm = b.n("Direction to", 5, 0); b.l(a, "result", nrm, "turns_a"); b.l(bb, "result", nrm, "turns_b")
    pos = b.n("Position", 5, 2)
    d = b.n("Dot 3", 6, 1)
    for k in "xyz":
        b.l(pos, k, d, "a" + k); b.l(nrm, k, d, "b" + k)
    # slabs across the solid, scrolling with the music
    pitch = b.n("Remap", 1, 2, {"out_lo": 1.0, "out_hi": 8.0}); b.l(c1, "value", pitch, "x")
    scroll_base = b.n("Multiply", 1, 3, inputs={"b": 2.0}); b.l(c2, "value", scroll_base, "a")
    push = b.n("Multiply", 1, 4, inputs={"b": 4.0}); b.l(c3, "value", push, "a")
    bass_push = b.n("Multiply", 2, 4); b.l(au, "bass", bass_push, "a"); b.l(push, "result", bass_push, "b")
    scroll_rate = b.n("Add", 2, 3); b.l(scroll_base, "result", scroll_rate, "a"); b.l(bass_push, "result", scroll_rate, "b")
    neg = b.n("Multiply", 3, 4, inputs={"b": -1.0}); b.l(scroll_rate, "result", neg, "a")
    signed = b.n("Select", 3, 3); b.l(k2, "on", signed, "on"); b.l(scroll_rate, "result", signed, "a"); b.l(neg, "result", signed, "b")
    scroll = b.n("Integrate", 4, 3, {"wrap": 16.0}); b.l(signed, "result", scroll, "rate")
    dp = b.n("Multiply", 7, 1); b.l(d, "result", dp, "a"); b.l(pitch, "result", dp, "b")
    s = b.n("Subtract", 8, 1); b.l(dp, "result", s, "a"); b.l(scroll, "value", s, "b")
    # the slab profile, the spectrum bin it reads, the palette colour it wears
    sharp = b.n("Remap", 1, 1, {"out_lo": 1.0, "out_hi": 6.0}); b.l(it, "value", sharp, "x")
    prof = b.n("Band", 9, 1); b.l(s, "result", prof, "x"); b.l(sharp, "result", prof, "sharp")
    m16 = b.n("Modulo", 9, 2, inputs={"m": 16.0}); b.l(s, "result", m16, "x")
    idx16 = b.n("Multiply", 10, 2, inputs={"b": 1.0 / 16.0}); b.l(m16, "result", idx16, "a")
    spec = b.n("Spectrum", 11, 2, {"smooth": 0.7}); b.l(idx16, "result", spec, "index")
    lift = b.n("Smoothstep", 12, 2, {"e0": 0.0, "e1": 0.5}); b.l(spec, "level", lift, "x")
    floor_ = b.n("Add", 12, 0, inputs={"b": 0.12}); b.l(lift, "result", floor_, "a")
    lum = b.n("Multiply", 12, 1); b.l(floor_, "result", lum, "a"); b.l(prof, "result", lum, "b")
    fl = b.n("Floor", 9, 3); b.l(s, "result", fl, "x")
    fl16 = b.n("Multiply", 10, 3, inputs={"b": 1.0 / 16.0}); b.l(fl, "result", fl16, "a")
    hue = b.n("Integrate", 10, 4, {"wrap": 1.0}, inputs={"rate": 0.02})
    hh = b.n("Add", 11, 3); b.l(fl16, "result", hh, "a"); b.l(hue, "value", hh, "b")
    pal = b.n("Palette", 12, 3); b.l(hh, "result", pal, "index"); b.l(lum, "result", pal, "brightness")
    out = b.n("Output", 13, 3); b.l(pal, "color", out, "color")
    return b.save("slab_cut.json")


def cell_weave():
    """Cube Cell: nested sines over the 3-D position, one axis per band, the
    sum wrapped so the fold draws the cell walls; a tumble on Check 2."""
    b = GB("Cell Weave")
    sp = b.n("Speed", 0, 0, {"label": "Speed", "default": 128})
    it = b.n("Intensity", 0, 1, {"label": "Drive", "default": 150})
    c1 = b.n("Custom 1", 0, 2, {"label": "Cells X", "default": 200})
    c2 = b.n("Custom 2", 0, 3, {"label": "Cells Y", "default": 64})
    c3 = b.n("Custom 3", 0, 4, {"label": "Cells Z", "default": 26})
    k2 = b.n("Check 2", 0, 5, {"label": "Tumble", "default": True})
    au = b.n("Audio", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 12, "audio": "frequency"})
    pos = b.n("Position", 1, 6)
    # tumble: two slow rotations, or the raw position
    r1 = b.n("Multiply", 1, 0, inputs={"b": 0.04}); b.l(sp, "value", r1, "a")
    a1 = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(r1, "result", a1, "rate")
    r2 = b.n("Multiply", 1, 1, inputs={"b": 0.027}); b.l(sp, "value", r2, "a")
    a2 = b.n("Integrate", 2, 1, {"wrap": 1.0}); b.l(r2, "result", a2, "rate")
    rot1 = b.n("Rotate", 2, 6); b.l(pos, "x", rot1, "x"); b.l(pos, "y", rot1, "y"); b.l(a1, "value", rot1, "turns")
    rot2 = b.n("Rotate", 3, 6); b.l(rot1, "y", rot2, "x"); b.l(pos, "z", rot2, "y"); b.l(a2, "value", rot2, "turns")
    x = b.n("Select", 4, 5); b.l(k2, "on", x, "on"); b.l(pos, "x", x, "a"); b.l(rot1, "x", x, "b")
    y = b.n("Select", 4, 6); b.l(k2, "on", y, "on"); b.l(pos, "y", y, "a"); b.l(rot2, "x", y, "b")
    z = b.n("Select", 4, 7); b.l(k2, "on", z, "on"); b.l(pos, "z", z, "a"); b.l(rot2, "y", z, "b")
    # each axis' cell frequency: its slider, stretched by its band
    def freq(col, row, slider, band):
        base = b.n("Remap", col, row, {"out_lo": 0.05, "out_hi": 0.5}); b.l(slider, "value", base, "x")
        drive = b.n("Multiply", col + 1, row, inputs={"b": 0.8}); b.l(au, band, drive, "a")
        gain = b.n("Add", col + 2, row, inputs={"a": 0.7}); b.l(drive, "result", gain, "b")
        f = b.n("Multiply", col + 3, row); b.l(base, "result", f, "a"); b.l(gain, "result", f, "b")
        return f
    fx = freq(1, 2, c1, "bass"); fy = freq(1, 3, c2, "mid"); fz = freq(1, 4, c3, "treble")
    gx = b.n("Multiply", 5, 5); b.l(x, "result", gx, "a"); b.l(fx, "result", gx, "b")
    gy = b.n("Multiply", 5, 6); b.l(y, "result", gy, "a"); b.l(fy, "result", gy, "b")
    gz = b.n("Multiply", 5, 7); b.l(z, "result", gz, "a"); b.l(fz, "result", gz, "b")
    ph = b.n("Remap", 1, 5, {"out_lo": 0.0, "out_hi": 0.6}); b.l(sp, "value", ph, "x")
    t8 = b.n("Integrate", 2, 5, {"wrap": 1.0}); b.l(ph, "result", t8, "rate")
    # the nested sines, cycled across the axes
    # sin8 in the original is 0..255 - unsigned - so each sine is lifted to 0..1 here
    def nested(col, row, outer, inner):
        s1 = b.n("Add", col, row); b.l(inner, "result", s1, "a"); b.l(t8, "value", s1, "b")
        sn = b.n("Sine", col + 1, row); b.l(s1, "result", sn, "x")
        sc = b.n("Multiply", col + 2, row, inputs={"b": 0.25}); b.l(sn, "result", sc, "a")
        s2 = b.n("Add", col + 3, row); b.l(outer, "result", s2, "a"); b.l(sc, "result", s2, "b")
        sn2 = b.l(s2, "result", b.n("Sine", col + 4, row), "x")
        return b.l(sn2, "result", b.n("Remap", col + 5, row, {"in_lo": -1.0, "in_hi": 1.0}), "x")
    a = nested(6, 5, gx, gy); bb = nested(6, 6, gy, gz); c = nested(6, 7, gz, gx)
    # weights 1, 1/2, 1/2 sum to two: the fold wraps once, drawing one set of walls
    ha = b.n("Multiply", 12, 4, inputs={"b": 1.0}); b.l(a, "result", ha, "a")
    hb = b.n("Multiply", 12, 7, inputs={"b": 0.5}); b.l(bb, "result", hb, "a")
    hc = b.n("Multiply", 12, 8, inputs={"b": 0.5}); b.l(c, "result", hc, "a")
    s1 = b.n("Add", 13, 5); b.l(ha, "result", s1, "a"); b.l(hb, "result", s1, "b")
    s2 = b.n("Add", 13, 6); b.l(s1, "result", s2, "a"); b.l(hc, "result", s2, "b")
    hue = b.n("Integrate", 13, 7, {"wrap": 1.0}, inputs={"rate": 0.01})
    s3 = b.n("Add", 14, 6); b.l(s2, "result", s3, "a"); b.l(hue, "value", s3, "b")
    idx = b.n("Fract", 15, 6); b.l(s3, "result", idx, "x")          # the wrap IS the cell wall
    # brightness: volume, smoothed, through the Drive slider
    env = b.n("Envelope", 1, 7, {"attack": 30.0, "release": 300.0}); b.l(au, "volume", env, "x")
    dr = b.n("Remap", 2, 7, {"out_lo": 0.3, "out_hi": 1.0}); b.l(it, "value", dr, "x")
    bright = b.n("Multiply", 3, 8); b.l(env, "value", bright, "a"); b.l(dr, "result", bright, "b")
    br2 = b.n("Add", 4, 8, inputs={"b": 0.15}); b.l(bright, "result", br2, "a")
    pal = b.n("Palette", 16, 6); b.l(idx, "result", pal, "index"); b.l(br2, "result", pal, "brightness")
    out = b.n("Output", 17, 6); b.l(pal, "color", out, "color")
    return b.save("cell_weave.json")


def truchet():
    """Truchet: each face cut into N x N tiles, each tile a pair of quarter
    circles turned by a hash; the seed re-rolls on the beat, so the maze
    rewires itself."""
    b = GB("Truchet Cube")
    sp = b.n("Speed", 0, 0, {"label": "Flow", "default": 100})
    it = b.n("Intensity", 0, 1, {"label": "Line width", "default": 150})
    c1 = b.n("Custom 1", 0, 2, {"label": "Tiles per face", "default": 40})
    c3 = b.n("Custom 3", 0, 3, {"label": "Seed", "default": 3})
    k1 = b.n("Check 1", 0, 4, {"label": "Rewire on beat", "default": True})
    au = b.n("Audio", 0, 5)
    b.n("Effect settings", 0, 6, {"palette": 11, "audio": "frequency"})
    face = b.n("Cube face", 1, 3)
    nn = b.n("Remap", 1, 2, {"out_lo": 1.0, "out_hi": 8.99}); b.l(c1, "value", nn, "x")
    n = b.n("Floor", 2, 2); b.l(nn, "result", n, "x")
    ta = b.n("Multiply", 2, 3); b.l(face, "a", ta, "a"); b.l(n, "result", ta, "b")
    tb = b.n("Multiply", 2, 4); b.l(face, "b", tb, "a"); b.l(n, "result", tb, "b")
    ca = b.n("Floor", 3, 3); b.l(ta, "result", ca, "x")
    cb = b.n("Floor", 3, 4); b.l(tb, "result", cb, "x")
    la = b.n("Fract", 3, 5); b.l(ta, "result", la, "x")
    lb = b.n("Fract", 3, 6); b.l(tb, "result", lb, "x")
    # one random per tile: face, cell and the seed (which the beat can re-roll)
    rnd = b.n("Random hold", 1, 5); b.l(au, "beat", rnd, "trigger")
    rs = b.n("Select", 2, 5, inputs={"a": 0.0}); b.l(k1, "on", rs, "on"); b.l(rnd, "value", rs, "b")
    seed = b.n("Add", 2, 6); b.l(c3, "value", seed, "a"); b.l(rs, "result", seed, "b")
    f100 = b.n("Multiply", 4, 2, inputs={"b": 100.0}); b.l(face, "face", f100, "a")
    hx = b.n("Add", 4, 3); b.l(ca, "result", hx, "a"); b.l(f100, "result", hx, "b")
    h = b.n("Hash", 5, 3); b.l(hx, "result", h, "x"); b.l(cb, "result", h, "y"); b.l(seed, "result", h, "seed")
    flip = b.n("Threshold", 6, 3, inputs={"at": 0.5}); b.l(h, "value", flip, "x")
    ila = b.n("Subtract", 4, 5, inputs={"a": 1.0}); b.l(la, "result", ila, "b")
    la2 = b.n("Select", 5, 5); b.l(flip, "on", la2, "on"); b.l(la, "result", la2, "a"); b.l(ila, "result", la2, "b")
    # distance to the two arcs, radius 1/2, centred on opposite corners
    len1 = b.n("Length", 6, 5); b.l(la2, "result", len1, "x"); b.l(lb, "result", len1, "y")
    d1a = b.n("Subtract", 7, 5, inputs={"b": 0.5}); b.l(len1, "result", d1a, "a")
    d1 = b.n("Abs", 8, 5); b.l(d1a, "result", d1, "x")
    ila2 = b.n("Subtract", 6, 6, inputs={"a": 1.0}); b.l(la2, "result", ila2, "b")
    ilb = b.n("Subtract", 6, 7, inputs={"a": 1.0}); b.l(lb, "result", ilb, "b")
    len2 = b.n("Length", 7, 6); b.l(ila2, "result", len2, "x"); b.l(ilb, "result", len2, "y")
    d2a = b.n("Subtract", 8, 6, inputs={"b": 0.5}); b.l(len2, "result", d2a, "a")
    d2 = b.n("Abs", 9, 6); b.l(d2a, "result", d2, "x")
    d = b.n("Min", 9, 5); b.l(d1, "result", d, "a"); b.l(d2, "result", d, "b")
    width = b.n("Remap", 1, 1, {"out_lo": 0.06, "out_hi": 0.35}); b.l(it, "value", width, "x")
    dw = b.n("Divide", 10, 5); b.l(d, "result", dw, "a"); b.l(width, "result", dw, "b")
    inv = b.n("Subtract", 11, 5, inputs={"a": 1.0}); b.l(dw, "result", inv, "b")
    line = b.n("Smoothstep", 12, 5); b.l(inv, "result", line, "x")
    # colour flows along the curves: the tile's own hue plus a running phase
    fl = b.n("Multiply", 1, 0, inputs={"b": 0.4}); b.l(sp, "value", fl, "a")
    flow = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(fl, "result", flow, "rate")
    hh = b.n("Multiply", 6, 2, inputs={"b": 0.7}); b.l(h, "value", hh, "a")
    hi = b.n("Add", 7, 2); b.l(hh, "result", hi, "a"); b.l(flow, "value", hi, "b")
    pal = b.n("Palette", 13, 5); b.l(hi, "result", pal, "index"); b.l(line, "result", pal, "brightness")
    out = b.n("Output", 14, 5); b.l(pal, "color", out, "color")
    return b.save("truchet_cube.json")


def ring_rain():
    """Matrix Rain on the lid-and-walls ruler: each column its own speed and
    phase from a hash, a bright head and a trail behind it, no drop state."""
    b = GB("Ring Rain")
    sp = b.n("Speed", 0, 0, {"label": "Fall speed", "default": 128})
    it = b.n("Intensity", 0, 1, {"label": "Trail", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Columns", "default": 128})
    k1 = b.n("Check 1", 0, 3, {"label": "Bass brightens", "default": True})
    au = b.n("Audio", 0, 4)
    b.n("Effect settings", 0, 5, {"palette": 10, "audio": "volume"})
    ring = b.n("Cube ring", 1, 3)
    ncol = b.n("Remap", 1, 2, {"out_lo": 8.0, "out_hi": 64.0}); b.l(c1, "value", ncol, "x")
    colf = b.n("Multiply", 2, 2); b.l(ring, "around", colf, "a"); b.l(ncol, "result", colf, "b")
    col = b.n("Floor", 3, 2); b.l(colf, "result", col, "x")
    h1 = b.n("Hash", 4, 1, inputs={"y": 0.0, "seed": 1.0}); b.l(col, "result", h1, "x")
    h2 = b.n("Hash", 4, 2, inputs={"y": 1.0, "seed": 1.0}); b.l(col, "result", h2, "x")
    spd = b.n("Remap", 1, 0, {"out_lo": 0.1, "out_hi": 1.5}); b.l(sp, "value", spd, "x")
    vary = b.n("Remap", 5, 1, {"out_lo": 0.3, "out_hi": 1.0}); b.l(h1, "value", vary, "x")
    speed = b.n("Multiply", 6, 1); b.l(vary, "result", speed, "a"); b.l(spd, "result", speed, "b")
    tt = b.n("Integrate", 2, 0, {"wrap": 0.0}, inputs={"rate": 1.0})
    pos = b.n("Multiply", 7, 1); b.l(tt, "value", pos, "a"); b.l(speed, "result", pos, "b")
    ph = b.n("Add", 8, 1); b.l(pos, "result", ph, "a"); b.l(h2, "value", ph, "b")
    head = b.n("Fract", 9, 1); b.l(ph, "result", head, "x")
    # behind the head: 0 at the head, growing up the column (towards the lid)
    rel = b.n("Subtract", 9, 3); b.l(head, "result", rel, "a"); b.l(ring, "depth", rel, "b")
    behind = b.n("Modulo", 10, 3, inputs={"m": 1.0}); b.l(rel, "result", behind, "x")
    inv = b.n("Subtract", 11, 3, inputs={"a": 1.0}); b.l(behind, "result", inv, "b")
    tl = b.n("Remap", 1, 1, {"out_lo": 14.0, "out_hi": 3.0}); b.l(it, "value", tl, "x")
    trail = b.n("Power", 12, 3); b.l(inv, "result", trail, "x"); b.l(tl, "result", trail, "e")
    ishead = b.n("Threshold", 11, 4, inputs={"at": 0.035}); b.l(behind, "result", ishead, "x")
    headm = b.n("Select", 12, 4, inputs={"a": 1.0, "b": 0.0}); b.l(ishead, "on", headm, "on")
    # bass brightens the trails when asked
    bb = b.n("Multiply", 5, 4, inputs={"b": 1.5}); b.l(au, "bass", bb, "a")
    bsel = b.n("Select", 6, 4, inputs={"a": 0.0}); b.l(k1, "on", bsel, "on"); b.l(bb, "result", bsel, "b")
    gain = b.n("Add", 7, 4, inputs={"a": 0.6}); b.l(bsel, "result", gain, "b")
    tb = b.n("Multiply", 13, 3); b.l(trail, "result", tb, "a"); b.l(gain, "result", tb, "b")
    hue = b.n("Multiply", 5, 2, inputs={"b": 0.6}); b.l(h1, "value", hue, "a")
    pal = b.n("Palette", 14, 3); b.l(hue, "result", pal, "index"); b.l(tb, "result", pal, "brightness")
    white = b.n("Colour", 13, 5, {"rgb": [255, 255, 255]})
    mix = b.n("Blend", 15, 4, {"mode": "over"}); b.l(pal, "color", mix, "under"); b.l(white, "color", mix, "over"); b.l(headm, "result", mix, "amount")
    out = b.n("Output", 16, 4); b.l(mix, "color", out, "color")
    return b.save("ring_rain.json")


def box_fire():
    """Cube Fire: a heat field that rises up the walls and pools on the lid.
    The heat is a Field (a number per pixel kept between frames): each pixel
    reads last frame's heat one step down the ring, cools it, and the bottom
    edge is the source. The palette only colours it."""
    b = GB("Box Fire")
    sp = b.n("Speed", 0, 0, {"label": "Rise", "default": 128})
    it = b.n("Intensity", 0, 1, {"label": "Heat", "default": 170})
    c1 = b.n("Custom 1", 0, 2, {"label": "Flicker", "default": 128})
    k1 = b.n("Check 1", 0, 3, {"label": "Bass flare", "default": True})
    au = b.n("Audio", 0, 4)
    tm = b.n("Time", 0, 5)
    b.n("Effect settings", 0, 6, {"palette": 35, "audio": "frequency"})
    ring = b.n("Cube ring", 1, 4)
    # read one step deeper (toward the source) - that is what makes heat rise
    step = b.n("Remap", 1, 0, {"out_lo": 0.012, "out_hi": 0.05}); b.l(sp, "value", step, "x")
    deeper = b.n("Add", 2, 4); b.l(ring, "depth", deeper, "a"); b.l(step, "result", deeper, "b")
    t3 = b.n("Multiply", 1, 5, inputs={"b": 2.0}); b.l(tm, "t", t3, "a")
    wob = b.n("Noise", 2, 5, inputs={"scale": 6.0}); b.l(ring, "around", wob, "x"); b.l(ring, "depth", wob, "y"); b.l(t3, "result", wob, "z")
    wc = b.n("Subtract", 3, 5, inputs={"b": 0.5}); b.l(wob, "value", wc, "a")
    fl = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 0.05}); b.l(c1, "value", fl, "x")
    wamt = b.n("Multiply", 4, 5); b.l(wc, "result", wamt, "a"); b.l(fl, "result", wamt, "b")
    ar = b.n("Add", 3, 4); b.l(ring, "around", ar, "a"); b.l(wamt, "result", ar, "b")
    uv = b.n("Ring to uv", 4, 4); b.l(ar, "result", uv, "around"); b.l(deeper, "result", uv, "depth")
    heat = b.n("Field", 5, 4, {"field": 0}); b.l(uv, "u", heat, "u"); b.l(uv, "v", heat, "v")
    cool = b.n("Remap", 1, 1, {"out_lo": 0.86, "out_hi": 0.975}); b.l(it, "value", cool, "x")
    hc = b.n("Multiply", 6, 4); b.l(heat, "value", hc, "a"); b.l(cool, "result", hc, "b")
    # the source: the bottom edge smoulders, flickers, and flares with bass
    t4 = b.n("Multiply", 1, 6, inputs={"b": 4.0}); b.l(tm, "t", t4, "a")
    src = b.n("Noise", 2, 6, inputs={"y": 0.3, "scale": 8.0}); b.l(ring, "around", src, "x"); b.l(t4, "result", src, "z")
    bass = b.n("Multiply", 2, 7, inputs={"b": 1.5}); b.l(au, "bass", bass, "a")
    flare = b.n("Select", 3, 7, inputs={"a": 0.0}); b.l(k1, "on", flare, "on"); b.l(bass, "result", flare, "b")
    gain = b.n("Add", 4, 7, inputs={"a": 0.8}); b.l(flare, "result", gain, "b")
    s2 = b.n("Multiply", 5, 6); b.l(src, "value", s2, "a"); b.l(gain, "result", s2, "b")
    edge = b.n("Smoothstep", 5, 7, {"e0": 0.9, "e1": 1.0}); b.l(ring, "depth", edge, "x")
    s3 = b.n("Multiply", 6, 6); b.l(s2, "result", s3, "a"); b.l(edge, "result", s3, "b")
    h2 = b.n("Max", 7, 5); b.l(hc, "result", h2, "a"); b.l(s3, "result", h2, "b")
    keep = b.n("Field write", 8, 6, {"field": 0}); b.l(h2, "result", keep, "value")
    bri = b.n("Smoothstep", 8, 4, {"e0": 0.02, "e1": 0.3}); b.l(h2, "result", bri, "x")
    pal = b.n("Palette", 9, 5); b.l(h2, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 10, 5); b.l(pal, "color", out, "color")
    return b.save("box_fire.json")


# ---------------------------------------------------------------------------
# The second five: Maelstrom, Kaleidoscope, Mandelbrot, Watershed, Moire.
# ---------------------------------------------------------------------------
def maelstrom():
    """Maelstrom: a logarithmic spiral sinking into the lid - phase =
    density * log(radius) + arms * azimuth + t, so a constant rate of t is a
    constant rate of zoom. A beat surges the zoom; two seconds without one
    and it eases round and unwinds outward until the next."""
    b = GB("Maelstrom")
    sp = b.n("Speed", 0, 0, {"label": "Zoom", "default": 90})
    it = b.n("Intensity", 0, 1, {"label": "Contrast", "default": 120})
    c1 = b.n("Custom 1", 0, 2, {"label": "Arms", "default": 85})
    c2 = b.n("Custom 2", 0, 3, {"label": "Colour cycle", "default": 40})
    c3 = b.n("Custom 3", 0, 4, {"label": "Density", "default": 10})
    k1 = b.n("Check 1", 0, 5, {"label": "Colour along arms", "default": False})
    au = b.n("Audio", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 11, "audio": "frequency"})
    ring = b.n("Cube ring", 1, 5)
    # the zoom rate: the slider, a surge on the beat, and the turn-around when the kicks stop
    base = b.n("Remap", 1, 0, {"out_lo": 0.05, "out_hi": 1.2}); b.l(sp, "value", base, "x")
    kick = b.n("Envelope", 1, 6, {"attack": 10.0, "release": 350.0}); b.l(au, "hit", kick, "x")
    surge = b.n("Add", 2, 6, inputs={"a": 1.0}); b.l(kick, "value", surge, "b")
    since = b.n("Integrate", 1, 7, {"wrap": 0.0}, inputs={"rate": 1.0}); b.l(au, "beat", since, "reset")
    gone = b.n("Smoothstep", 2, 7, {"e0": 2.0, "e1": 3.5}); b.l(since, "value", gone, "x")
    dirn = b.n("Remap", 3, 7, {"out_lo": 1.0, "out_hi": -1.0}); b.l(gone, "result", dirn, "x")
    eased = b.n("Envelope", 4, 7, {"attack": 700.0, "release": 700.0}); b.l(dirn, "result", eased, "x")
    r1 = b.n("Multiply", 3, 6); b.l(base, "result", r1, "a"); b.l(surge, "result", r1, "b")
    rate = b.n("Multiply", 5, 6); b.l(r1, "result", rate, "a"); b.l(eased, "value", rate, "b")
    ph = b.n("Integrate", 6, 6, {"wrap": 1.0}); b.l(rate, "result", ph, "rate")
    # the spiral: density * log(radius) + arms * azimuth + phase
    arms = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 8.99}); b.l(c1, "value", arms, "x")
    narms = b.n("Floor", 2, 2); b.l(arms, "result", narms, "x")
    dens = b.n("Remap", 1, 4, {"out_lo": 0.5, "out_hi": 6.0}); b.l(c3, "value", dens, "x")
    rad = b.n("Add", 2, 5, inputs={"b": 0.02}); b.l(ring, "depth", rad, "a")
    lr = b.n("Log", 3, 5); b.l(rad, "result", lr, "x")
    dl = b.n("Multiply", 4, 4); b.l(lr, "result", dl, "a"); b.l(dens, "result", dl, "b")
    aa = b.n("Multiply", 4, 5); b.l(ring, "around", aa, "a"); b.l(narms, "result", aa, "b")
    ph1 = b.n("Add", 5, 4); b.l(dl, "result", ph1, "a"); b.l(aa, "result", ph1, "b")
    ph2 = b.n("Add", 6, 4); b.l(ph1, "result", ph2, "a"); b.l(ph, "value", ph2, "b")
    # contrast: how sharp the arms are; brightness lifts a little on the surge
    sharp = b.n("Remap", 1, 1, {"out_lo": 0.6, "out_hi": 6.0}); b.l(it, "value", sharp, "x")
    arm = b.n("Band", 7, 4); b.l(ph2, "result", arm, "x"); b.l(sharp, "result", arm, "sharp")
    lift = b.n("Remap", 3, 3, {"out_lo": 0.8, "out_hi": 1.15}); b.l(kick, "value", lift, "x")
    bri = b.n("Multiply", 8, 4); b.l(arm, "result", bri, "a"); b.l(lift, "result", bri, "b")
    # colour: along the arms (perpendicular phase) or across them, cycling
    cyc = b.n("Remap", 1, 3, {"out_lo": 0.0, "out_hi": 0.3}); b.l(c2, "value", cyc, "x")
    hue = b.n("Integrate", 2, 3, {"wrap": 1.0}); b.l(cyc, "result", hue, "rate")
    across = b.n("Multiply", 7, 2, inputs={"b": 0.25}); b.l(ph2, "result", across, "a")
    al1 = b.n("Multiply", 5, 2); b.l(lr, "result", al1, "a"); b.l(narms, "result", al1, "b")
    al2 = b.n("Multiply", 5, 3); b.l(ring, "around", al2, "a"); b.l(dens, "result", al2, "b")
    along = b.n("Subtract", 6, 2); b.l(al1, "result", along, "a"); b.l(al2, "result", along, "b")
    along2 = b.n("Multiply", 7, 3, inputs={"b": 0.08}); b.l(along, "result", along2, "a")
    pick = b.n("Select", 8, 2); b.l(k1, "on", pick, "on"); b.l(across, "result", pick, "a"); b.l(along2, "result", pick, "b")
    idx = b.n("Add", 9, 2); b.l(pick, "result", idx, "a"); b.l(hue, "value", idx, "b")
    pal = b.n("Palette", 10, 3); b.l(idx, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 11, 3); b.l(pal, "color", out, "color")
    return b.save("maelstrom.json")


def kaleidoscope():
    """Kaleidoscope: every direction is spun, folded into one fundamental
    domain of a mirror group, and cut by a few offset planes into flat cells
    - the cuts evaluated AFTER the fold, so each cell is mirrored over the
    whole solid. The offsets drift, so cells grow, merge and split."""
    b = GB("Kaleidoscope")
    sp = b.n("Speed", 0, 0, {"label": "Spin", "default": 110})
    it = b.n("Intensity", 0, 1, {"label": "Fill", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Drift", "default": 90})
    c2 = b.n("Custom 2", 0, 3, {"label": "Colour mix", "default": 170})
    k1 = b.n("Check 1", 0, 4, {"label": "Beat surge", "default": True})
    au = b.n("Audio", 0, 5)
    b.n("Effect settings", 0, 6, {"palette": 11, "audio": "frequency"})
    d = b.n("Direction", 1, 5)
    # two rotation clocks, then the fold
    ra = b.n("Remap", 1, 0, {"out_lo": 0.0, "out_hi": 0.12}); b.l(sp, "value", ra, "x")
    sa = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(ra, "result", sa, "rate")
    rb = b.n("Multiply", 1, 1, inputs={"b": 0.618}); b.l(ra, "result", rb, "a")
    sb = b.n("Integrate", 2, 1, {"wrap": 1.0}); b.l(rb, "result", sb, "rate")
    rot1 = b.n("Rotate", 2, 5); b.l(d, "nx", rot1, "x"); b.l(d, "ny", rot1, "y"); b.l(sa, "value", rot1, "turns")
    rot2 = b.n("Rotate", 3, 5); b.l(rot1, "y", rot2, "x"); b.l(d, "nz", rot2, "y"); b.l(sb, "value", rot2, "turns")
    fold = b.n("Mirror fold", 4, 5, {"symmetry": "octahedral"})
    b.l(rot1, "x", fold, "x"); b.l(rot2, "x", fold, "y"); b.l(rot2, "y", fold, "z")
    # the arrangement: four cut planes with drifting offsets, a bit per side
    dr = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 0.25}); b.l(c1, "value", dr, "x")
    drift = b.n("Integrate", 2, 2, {"wrap": 1.0}); b.l(dr, "result", drift, "rate")
    # each cut's offset sits at the domain's centroid (the generic direction the
    # mirrors are pointed at) and drifts by a fraction of the domain's spread,
    # so a cut always crosses the domain wherever the symmetry has put it
    cuts = [(0.5774, 0.5774, 0.5774, 0.0, 0.892), (-0.7071, 0.7071, 0.0, 0.29, 0.147),
            (0.2673, -0.5345, 0.8018, 0.61, 0.518), (0.8944, 0.0, -0.4472, 0.83, -0.174)]
    bits = []
    for k, (cx, cy, cz, phs, at0) in enumerate(cuts):
        dot = b.n("Dot 3", 5, 2 + k, inputs={"bx": cx, "by": cy, "bz": cz})
        b.l(fold, "x", dot, "ax"); b.l(fold, "y", dot, "ay"); b.l(fold, "z", dot, "az")
        p_ = b.n("Add", 3, 2 + k, inputs={"b": phs}); b.l(drift, "value", p_, "a")
        off = b.n("Sine", 4, 2 + k); b.l(p_, "result", off, "x")
        off2 = b.n("Remap", 4, 6 + k, {"in_lo": -1.0, "in_hi": 1.0, "out_lo": at0 - 0.22, "out_hi": at0 + 0.22}); b.l(off, "result", off2, "x")
        th = b.n("Threshold", 6, 2 + k); b.l(dot, "result", th, "x"); b.l(off2, "result", th, "at")
        w = b.n("Multiply", 7, 2 + k, inputs={"b": [1.0, 2.0, 4.0, 8.0][k] / 15.0}); b.l(th, "value", w, "a")
        bits.append(w)
    s1 = b.n("Add", 8, 2); b.l(bits[0], "result", s1, "a"); b.l(bits[1], "result", s1, "b")
    s2 = b.n("Add", 8, 3); b.l(bits[2], "result", s2, "a"); b.l(bits[3], "result", s2, "b")
    cell = b.n("Add", 9, 2); b.l(s1, "result", cell, "a"); b.l(s2, "result", cell, "b")
    # colour: the cell id spread over the palette by Colour mix, plus a slow turn
    mix = b.n("Remap", 1, 3, {"out_lo": 0.2, "out_hi": 1.0}); b.l(c2, "value", mix, "x")
    ci = b.n("Multiply", 10, 2); b.l(cell, "result", ci, "a"); b.l(mix, "result", ci, "b")
    hue = b.n("Integrate", 9, 4, {"wrap": 1.0}, inputs={"rate": 0.015})
    idx = b.n("Add", 11, 2); b.l(ci, "result", idx, "a"); b.l(hue, "value", idx, "b")
    # fill, with a beat surge
    fill = b.n("Remap", 1, 4, {"out_lo": 0.25, "out_hi": 1.0}); b.l(it, "value", fill, "x")
    kick = b.n("Envelope", 2, 6, {"attack": 10.0, "release": 300.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 3, 6, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    sg = b.n("Add", 4, 10, inputs={"a": 1.0}); b.l(ks, "result", sg, "b")
    bri = b.n("Multiply", 10, 4); b.l(fill, "result", bri, "a"); b.l(sg, "result", bri, "b")
    pal = b.n("Palette", 12, 3); b.l(idx, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 13, 3); b.l(pal, "color", out, "color")
    return b.save("kaleidoscope.json")


def mandelbrot():
    """Mandelbrot: the direction projected stereographically from the bottom
    pole onto the plane (lid = origin, equator = unit circle), the set drawn
    there around a filament-rich point, breathing in and out - a zoom that
    never has to reset because it never goes deeper than it came."""
    b = GB("Mandelbrot")
    sp = b.n("Speed", 0, 0, {"label": "Zoom", "default": 110})
    it = b.n("Intensity", 0, 1, {"label": "Brightness", "default": 150})
    c1 = b.n("Custom 1", 0, 2, {"label": "Filigree", "default": 180})
    c2 = b.n("Custom 2", 0, 3, {"label": "Locus", "default": 255})
    c3 = b.n("Custom 3", 0, 4, {"label": "Detail", "default": 18})
    k1 = b.n("Check 1", 0, 5, {"label": "Beat surge", "default": True})
    au = b.n("Audio", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 11, "audio": "frequency"})
    d = b.n("Direction", 1, 5)
    # stereographic: u = x / (1 + z), v = y / (1 + z)
    den = b.n("Add", 2, 6, inputs={"a": 1.0}); b.l(d, "nz", den, "b")
    u = b.n("Divide", 3, 5); b.l(d, "nx", u, "a"); b.l(den, "result", u, "b")
    v = b.n("Divide", 3, 6); b.l(d, "ny", v, "a"); b.l(den, "result", v, "b")
    # the breathing zoom: scale = exp(-(1 + sin(phase)) * depth), turning slowly
    zr = b.n("Remap", 1, 0, {"out_lo": 0.01, "out_hi": 0.2}); b.l(sp, "value", zr, "x")
    kick = b.n("Envelope", 1, 6, {"attack": 10.0, "release": 400.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 2, 7, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    sg = b.n("Add", 3, 7, inputs={"a": 1.0}); b.l(ks, "result", sg, "b")
    zr2 = b.n("Multiply", 4, 7); b.l(zr, "result", zr2, "a"); b.l(sg, "result", zr2, "b")
    phase = b.n("Integrate", 5, 7, {"wrap": 1.0}); b.l(zr2, "result", phase, "rate")
    sn = b.n("Sine", 6, 7); b.l(phase, "value", sn, "x")
    depth = b.n("Remap", 1, 4, {"out_lo": 0.5, "out_hi": 2.5}); b.l(c3, "value", depth, "x")
    e1 = b.n("Add", 7, 7, inputs={"a": 1.0}); b.l(sn, "result", e1, "b")
    e2 = b.n("Multiply", 8, 7); b.l(e1, "result", e2, "a"); b.l(depth, "result", e2, "b")
    e3 = b.n("Multiply", 9, 7, inputs={"b": -1.0}); b.l(e2, "result", e3, "a")
    scale = b.n("Exp", 10, 7); b.l(e3, "result", scale, "x")
    turn = b.n("Multiply", 6, 8, inputs={"b": 0.5}); b.l(phase, "value", turn, "a")
    # the locus: a line of points worth diving at, picked by the slider
    lx = b.n("Remap", 1, 3, {"out_lo": -0.7453, "out_hi": -0.1011}); b.l(c2, "value", lx, "x")
    ly = b.n("Remap", 2, 3, {"out_lo": 0.1127, "out_hi": 0.9563}); b.l(c2, "value", ly, "x")
    rot = b.n("Rotate", 4, 5); b.l(u, "result", rot, "x"); b.l(v, "result", rot, "y"); b.l(turn, "result", rot, "turns")
    sx = b.n("Multiply", 5, 5); b.l(rot, "x", sx, "a"); b.l(scale, "result", sx, "b")
    sy = b.n("Multiply", 5, 6); b.l(rot, "y", sy, "a"); b.l(scale, "result", sy, "b")
    cx = b.n("Add", 6, 5); b.l(sx, "result", cx, "a"); b.l(lx, "result", cx, "b")
    cy = b.n("Add", 6, 6); b.l(sy, "result", cy, "a"); b.l(ly, "result", cy, "b")
    mb = b.n("Mandelbrot", 7, 5, {"iterations": 90}); b.l(cx, "result", mb, "x"); b.l(cy, "result", mb, "y")
    # colour: escape time round the palette, the inside dark; Filigree sharpens the bands
    fil = b.n("Remap", 1, 2, {"out_lo": 1.0, "out_hi": 6.0}); b.l(c1, "value", fil, "x")
    tm = b.n("Multiply", 8, 5); b.l(mb, "value", tm, "a"); b.l(fil, "result", tm, "b")
    hue = b.n("Integrate", 8, 4, {"wrap": 1.0}, inputs={"rate": 0.03})
    idx = b.n("Add", 9, 5); b.l(tm, "result", idx, "a"); b.l(hue, "value", idx, "b")
    inside = b.n("Threshold", 8, 6, inputs={"at": 0.999}); b.l(mb, "value", inside, "x")
    dim = b.n("Select", 9, 6, inputs={"a": 1.0, "b": 0.12}); b.l(inside, "on", dim, "on")
    br = b.n("Remap", 1, 1, {"out_lo": 0.2, "out_hi": 1.0}); b.l(it, "value", br, "x")
    bri = b.n("Multiply", 10, 6); b.l(dim, "result", bri, "a"); b.l(br, "result", bri, "b")
    pal = b.n("Palette", 11, 5); b.l(idx, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 12, 5); b.l(pal, "color", out, "color")
    return b.save("mandelbrot.json")


def watershed():
    """Watershed: a height field over the surface (sinusoids of the position,
    drifting), every pixel draining to its lowest neighbour, water advected
    one hop per frame and summed where threads meet - trunks brighter than
    tributaries. Flow erodes the ground, so channels capture and heal. A beat
    is a downpour."""
    b = GB("Watershed")
    sp = b.n("Speed", 0, 0, {"label": "Drift", "default": 160})
    it = b.n("Intensity", 0, 1, {"label": "Rain", "default": 140})
    c1 = b.n("Custom 1", 0, 2, {"label": "Erosion", "default": 90})
    c2 = b.n("Custom 2", 0, 3, {"label": "Relief", "default": 128})
    k1 = b.n("Check 1", 0, 4, {"label": "Storms on the beat", "default": True})
    au = b.n("Audio", 0, 5)
    tm = b.n("Time", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 36, "audio": "frequency"})
    pos = b.n("Position", 1, 5)
    co = b.n("Coords", 1, 7)
    # the base ground: three sinusoids of the position, drifting
    dr = b.n("Remap", 1, 0, {"out_lo": 0.0, "out_hi": 0.08}); b.l(sp, "value", dr, "x")
    ph = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(dr, "result", ph, "rate")
    def wave(col, row, ax, k, pshift):
        m = b.n("Multiply", col, row, inputs={"b": k}); b.l(pos, ax, m, "a")
        p_ = b.n("Multiply", col, row + 3, inputs={"b": pshift}); b.l(ph, "value", p_, "a")
        a_ = b.n("Add", col + 1, row); b.l(m, "result", a_, "a"); b.l(p_, "result", a_, "b")
        return b.l(a_, "result", b.n("Sine", col + 2, row), "x")
    w1 = wave(2, 1, "x", 0.9, 1.0); w2 = wave(2, 2, "y", 1.3, -0.7); w3 = wave(5, 1, "z", 1.1, 0.5)
    s1 = b.n("Add", 8, 1); b.l(w1, "result", s1, "a"); b.l(w2, "result", s1, "b")
    ground = b.n("Add", 8, 2); b.l(s1, "result", ground, "a"); b.l(w3, "result", ground, "b")
    relief = b.n("Remap", 1, 3, {"out_lo": 0.3, "out_hi": 1.5}); b.l(c2, "value", relief, "x")
    g2 = b.n("Multiply", 9, 2); b.l(ground, "result", g2, "a"); b.l(relief, "result", g2, "b")
    # last frame's water here erodes the ground; the height field is written for next frame
    wprev = b.n("Field", 3, 7, {"field": 1}); b.l(co, "u", wprev, "u"); b.l(co, "v", wprev, "v")
    er = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 0.6}); b.l(c1, "value", er, "x")
    ero = b.n("Multiply", 4, 7); b.l(wprev, "value", ero, "a"); b.l(er, "result", ero, "b")
    ero2 = b.n("Clamp", 5, 7, {"lo": 0.0, "hi": 1.0}); b.l(ero, "result", ero2, "x")
    height = b.n("Subtract", 10, 2); b.l(g2, "result", height, "a"); b.l(ero2, "result", height, "b")
    b.l(height, "result", b.n("Field write", 11, 2, {"field": 0}), "value")
    # drainage: what flows in, plus this pixel's own rain; sinks pool
    drain = b.n("Drain", 3, 5, {"height_field": 0, "water_field": 1})
    rain = b.n("Remap", 1, 1, {"out_lo": 0.005, "out_hi": 0.06}); b.l(it, "value", rain, "x")
    storm_n = b.n("Noise", 4, 4, inputs={"scale": 3.0}); b.l(pos, "x", storm_n, "x"); b.l(pos, "y", storm_n, "y"); b.l(tm, "t", storm_n, "z")
    cell = b.n("Smoothstep", 5, 4, {"e0": 0.55, "e1": 0.75}); b.l(storm_n, "value", cell, "x")
    kick = b.n("Envelope", 2, 6, {"attack": 5.0, "release": 250.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 3, 6, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    storm = b.n("Multiply", 6, 4); b.l(cell, "result", storm, "a"); b.l(ks, "result", storm, "b")
    storm2 = b.n("Multiply", 7, 4, inputs={"b": 0.5}); b.l(storm, "result", storm2, "a")
    r2 = b.n("Add", 8, 4); b.l(rain, "result", r2, "a"); b.l(storm2, "result", r2, "b")
    keep = b.n("Select", 4, 5, inputs={"a": 0.95, "b": 0.85}); b.l(drain, "sink", keep, "on")   # a sink pools, soaking away slowly
    inflow = b.n("Multiply", 5, 5); b.l(drain, "water", inflow, "a"); b.l(keep, "result", inflow, "b")
    water = b.n("Add", 9, 4); b.l(inflow, "result", water, "a"); b.l(r2, "result", water, "b")
    wclamp = b.n("Clamp", 10, 4, {"lo": 0.0, "hi": 3.0}); b.l(water, "result", wclamp, "x")
    b.l(wclamp, "result", b.n("Field write", 11, 4, {"field": 1}), "value")
    # colour: trunks bright, headwaters faint; the hue from the ground height
    bri = b.n("Smoothstep", 11, 5, {"e0": 0.003, "e1": 0.25}); b.l(wclamp, "result", bri, "x")
    hi = b.n("Remap", 11, 3, {"in_lo": -1.5, "in_hi": 1.5, "out_lo": 0.0, "out_hi": 0.8}); b.l(height, "result", hi, "x")
    pal = b.n("Palette", 12, 4); b.l(hi, "result", pal, "index"); b.l(bri, "result", pal, "brightness")
    out = b.n("Output", 13, 4); b.l(pal, "color", out, "color")
    return b.save("watershed.json")


def moire():
    """Moire: a polar funnel about the lid, a curl-shaped warp of the 3-D
    point, then two dot lattices - each a product of cosines along two
    directions - at slightly different scales, interfering; the hue from the
    field itself."""
    b = GB("Moire")
    sp = b.n("Speed", 0, 0, {"label": "Flow", "default": 70})
    it = b.n("Intensity", 0, 1, {"label": "Fill", "default": 128})
    c1 = b.n("Custom 1", 0, 2, {"label": "Distort", "default": 128})
    c2 = b.n("Custom 2", 0, 3, {"label": "Scale", "default": 120})
    c3 = b.n("Custom 3", 0, 4, {"label": "Detune", "default": 20})
    k1 = b.n("Check 1", 0, 5, {"label": "Beat surge", "default": True})
    au = b.n("Audio", 0, 6)
    b.n("Effect settings", 0, 7, {"palette": 11, "audio": "frequency"})
    pos = b.n("Position", 1, 5)
    fl = b.n("Remap", 1, 0, {"out_lo": 0.02, "out_hi": 0.4}); b.l(sp, "value", fl, "x")
    p1 = b.n("Integrate", 2, 0, {"wrap": 1.0}); b.l(fl, "result", p1, "rate")
    p2 = b.n("Multiply", 3, 0, inputs={"b": 0.73}); b.l(p1, "value", p2, "a")
    kick = b.n("Envelope", 1, 7, {"attack": 10.0, "release": 300.0}); b.l(au, "hit", kick, "x")
    ks = b.n("Select", 2, 7, inputs={"a": 0.0}); b.l(k1, "on", ks, "on"); b.l(kick, "value", ks, "b")
    surge = b.n("Add", 3, 7, inputs={"a": 1.0}); b.l(ks, "result", surge, "b")
    # 1. the funnel: radius scaled by a travelling sine, angle twisted more near the lid
    dist = b.n("Remap", 1, 2, {"out_lo": 0.0, "out_hi": 0.5}); b.l(c1, "value", dist, "x")
    r_ = b.n("Length", 2, 5); b.l(pos, "x", r_, "x"); b.l(pos, "y", r_, "y")
    rs = b.n("Multiply", 2, 6, inputs={"b": 1.2}); b.l(r_, "result", rs, "a")
    rp = b.n("Subtract", 3, 6); b.l(rs, "result", rp, "a"); b.l(p1, "value", rp, "b")
    rsn = b.n("Sine", 4, 6); b.l(rp, "result", rsn, "x")
    ra = b.n("Multiply", 5, 6); b.l(rsn, "result", ra, "a"); b.l(dist, "result", ra, "b")
    ra2 = b.n("Multiply", 5, 7); b.l(ra, "result", ra2, "a"); b.l(surge, "result", ra2, "b")
    rf = b.n("Add", 6, 6, inputs={"a": 1.0}); b.l(ra2, "result", rf, "b")
    tw1 = b.n("Subtract", 4, 4, inputs={"a": 1.6}); b.l(r_, "result", tw1, "b")
    tw2 = b.n("Multiply", 5, 4); b.l(tw1, "result", tw2, "a"); b.l(dist, "result", tw2, "b")
    tw3 = b.n("Multiply", 6, 4, inputs={"b": 0.5}); b.l(tw2, "result", tw3, "a")
    rot = b.n("Rotate", 7, 5); b.l(pos, "x", rot, "x"); b.l(pos, "y", rot, "y"); b.l(tw3, "result", rot, "turns")
    X = b.n("Multiply", 8, 5); b.l(rot, "x", X, "a"); b.l(rf, "result", X, "b")
    Y = b.n("Multiply", 8, 6); b.l(rot, "y", Y, "a"); b.l(rf, "result", Y, "b")
    # 2. the warp: each axis pushed by a sine of another
    amp = b.n("Multiply", 6, 2, inputs={"b": 0.35}); b.l(dist, "result", amp, "a")
    amp2 = b.n("Multiply", 7, 2); b.l(amp, "result", amp2, "a"); b.l(surge, "result", amp2, "b")
    def push(col, row, src, k, ph):
        m = b.n("Multiply", col, row, inputs={"b": k}); b.l(src[0], src[1], m, "a")
        a_ = b.n("Add", col + 1, row); b.l(m, "result", a_, "a"); b.l(ph, "value", a_, "b")
        sn = b.n("Sine", col + 2, row); b.l(a_, "result", sn, "x")
        w = b.n("Multiply", col + 3, row); b.l(sn, "result", w, "a"); b.l(amp2, "result", w, "b")
        return w
    wx = push(9, 3, (Y, "result"), 0.46, p1); wy = push(9, 4, (pos, "z"), 0.43, p1); wz = push(9, 5, (X, "result"), 0.39, p1)
    X2 = b.n("Add", 13, 5); b.l(X, "result", X2, "a"); b.l(wx, "result", X2, "b")
    Y2 = b.n("Add", 13, 6); b.l(Y, "result", Y2, "a"); b.l(wy, "result", Y2, "b")
    Z2 = b.n("Add", 13, 7); b.l(pos, "z", Z2, "a"); b.l(wz, "result", Z2, "b")
    # 3. two lattices - cosines along two generic directions - and their beat
    sc = b.n("Remap", 1, 3, {"out_lo": 1.5, "out_hi": 6.0}); b.l(c2, "value", sc, "x")
    det = b.n("Remap", 1, 4, {"out_lo": 1.0, "out_hi": 1.12}); b.l(c3, "value", det, "x")
    sc2 = b.n("Multiply", 2, 4); b.l(sc, "result", sc2, "a"); b.l(det, "result", sc2, "b")
    def lattice(col, row, scale, da, db):
        A = b.n("Dot 3", col, row, inputs={"bx": da[0], "by": da[1], "bz": da[2]})
        Bd = b.n("Dot 3", col, row + 1, inputs={"bx": db[0], "by": db[1], "bz": db[2]})
        for n_ in (A, Bd):
            b.l(X2, "result", n_, "ax"); b.l(Y2, "result", n_, "ay"); b.l(Z2, "result", n_, "az")
        sa = b.n("Multiply", col + 1, row); b.l(A, "result", sa, "a"); b.l(scale, "result", sa, "b")
        sb = b.n("Multiply", col + 1, row + 1); b.l(Bd, "result", sb, "a"); b.l(scale, "result", sb, "b")
        pa = b.n("Add", col + 2, row); b.l(sa, "result", pa, "a"); b.l(p2, "result", pa, "b")
        pb = b.n("Subtract", col + 2, row + 1); b.l(sb, "result", pb, "a"); b.l(p1, "value", pb, "b")
        ca = b.n("Cosine", col + 3, row); b.l(pa, "result", ca, "x")
        cb = b.n("Cosine", col + 3, row + 1); b.l(pb, "result", cb, "x")
        g = b.n("Multiply", col + 4, row); b.l(ca, "result", g, "a"); b.l(cb, "result", g, "b")
        return b.l(g, "result", b.n("Power", col + 5, row, inputs={"e": 3.0}), "x")
    g1 = lattice(14, 2, sc, (0.8105, 0.3137, -0.4946), (0.1142, 0.7584, 0.6417))
    g2 = lattice(14, 5, sc2, (0.7300, 0.4500, -0.5100), (0.2100, 0.7100, 0.6700))
    mx = b.n("Max", 20, 3); b.l(g1, "result", mx, "a"); b.l(g2, "result", mx, "b")
    co = b.n("Multiply", 20, 4); b.l(g1, "result", co, "a"); b.l(g2, "result", co, "b")
    m = b.n("Add", 21, 3); b.l(mx, "result", m, "a"); b.l(co, "result", m, "b")
    fill = b.n("Remap", 1, 1, {"out_lo": 0.4, "out_hi": 2.0}); b.l(it, "value", fill, "x")
    lum = b.n("Multiply", 22, 3); b.l(m, "result", lum, "a"); b.l(fill, "result", lum, "b")
    # 4. hue from the field
    hd = b.n("Dot 3", 14, 8, inputs={"bx": 0.3, "by": 0.5, "bz": 0.2})
    b.l(X2, "result", hd, "ax"); b.l(Y2, "result", hd, "ay"); b.l(Z2, "result", hd, "az")
    hue = b.n("Integrate", 15, 9, {"wrap": 1.0}, inputs={"rate": 0.02})
    hi = b.n("Add", 16, 8); b.l(hd, "result", hi, "a"); b.l(hue, "value", hi, "b")
    pal = b.n("Palette", 23, 4); b.l(hi, "result", pal, "index"); b.l(lum, "result", pal, "brightness")
    out = b.n("Output", 24, 4); b.l(pal, "color", out, "color")
    return b.save("moire.json")


ALL = [slab_cut, cell_weave, truchet, ring_rain, box_fire, maelstrom, kaleidoscope, mandelbrot, watershed, moire]


def check():
    """Compile every example to C++, build them all into one engine, run
    each for a moment with the fake audio and report lit pixels and motion."""
    import numpy as np
    sys.path.insert(0, os.path.dirname(HERE))
    import build as B
    from native.toolchain import build_engine
    from native.engine import Engine
    tmp = os.path.join(HERE, "_check"); os.makedirs(tmp, exist_ok=True)
    srcs = []
    for fn in sorted(os.listdir(OUT)):
        g = G.load(os.path.join(OUT, fn))
        p = os.path.join(tmp, fn[:-5] + ".cpp")
        open(p, "w", encoding="utf-8", newline="\n").write(g.compile())
        srcs.append(p)
    rep = build_engine(B.engine_sources(srcs, log=lambda *a: None),
                       [os.path.join(B.HERE, "shim"), os.path.join(B.ROOT, "usermods", "cube_fx"), B.GEN],
                       log=lambda *a: None)
    if not rep.ok:
        for e in rep.error_lines():
            if e[2].startswith("error"): print("  ", os.path.basename(e[0]), e[1], e[2])
        print(rep.link_output[-800:]); return False
    e = Engine(); e.load(rep.library)
    from native.synth import Synth
    syn = Synth()
    ok = True
    for fn in sorted(os.listdir(OUT)):
        name = G.load(os.path.join(OUT, fn)).name
        e.select(e.names.index(name))
        frames = []
        for k in range(60):
            syn.push(e)                       # the fake music: bins, volume, beats
            e.frame(); frames.append(np.asarray(e.rgb()).copy())
        lit = float((frames[-1].max(axis=2) > 8).mean())
        motion = float(np.abs(frames[-1].astype(int) - frames[-20].astype(int)).mean())
        good = lit > 0.05 and motion > 0.2
        ok &= good
        print(f"  {name:14s} lit {lit*100:5.1f}%  motion {motion:6.2f}  {'ok' if good else 'FLAT'}")
    return ok


if __name__ == "__main__":
    for f in ALL:
        g = f(); print("wrote", g.name)
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
