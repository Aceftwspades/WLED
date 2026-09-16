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


ALL = [slab_cut, cell_weave, truchet, ring_rain, box_fire]


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
        good = lit > 0.05 and motion > 0.5
        ok &= good
        print(f"  {name:14s} lit {lit*100:5.1f}%  motion {motion:6.2f}  {'ok' if good else 'FLAT'}")
    return ok


if __name__ == "__main__":
    for f in ALL:
        g = f(); print("wrote", g.name)
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
