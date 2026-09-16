"""
The node library: everything a graph can be made of, as data.

A node definition is a dict:

    name      shown on the node and used in graph files
    cat       category, for the add menu
    scope     "frame" - computed once per frame (a slider, the clock, audio)
              "pixel" - computed per pixel (anything that reads a coordinate)
              A pixel-scope node whose inputs all turn out to be frame-scope
              is hoisted out of the loop by the compiler, so a Multiply of two
              sliders costs nothing per pixel.
    inputs    [{name, type, default}]   type: float | color | bool
    outputs   [{name, type}]
    params    [{name, type, default, min, max, choices}]  widgets ON the node:
              type: float | int | bool | choice | color | text
              A control node's "label" text becomes the slider's name in the
              effect's metadata, so the exported effect has real slider names.
    code      C++ template. $in.x, $out.y, $p.z are replaced with variable
              names or literal values; $$ is a literal $. Every output must be
              assigned. Statements, not an expression.
    doc       one line for the tooltip

The per-pixel prologue the compiler emits provides, for a template to use:

    px, py        integer pixel (py is 0 on a strip)
    u, v          0..1 across the segment (v is 0.5 on a strip)
    cx, cy        -1..1, centred
    r, ang        polar about the centre: r 0..~1.4, ang -pi..pi
    nx, ny, nz    unit direction on the cube (a dome on a panel/strip)
    W, H, N       dimensions; N = W*H (or the strip length)

And at frame scope:

    t             seconds, as a float, from strip.now
    dt            milliseconds since the previous frame (uint16_t)

User nodes live in <project>/nodes/*.json with the same shape and are merged
in at start; a user node with a library node's name replaces it.
"""

F, C, B = "float", "color", "bool"


def _n(name, cat, scope, inputs, outputs, params, code, doc=""):
    return dict(name=name, cat=cat, scope=scope,
                inputs=[dict(zip(("name", "type", "default"), i)) for i in inputs],
                outputs=[dict(zip(("name", "type"), o)) for o in outputs],
                params=params, code=code.strip("\n"), doc=doc)


def _p(name, type, default, lo=None, hi=None, choices=None):
    d = dict(name=name, type=type, default=default)
    if lo is not None: d["min"] = lo
    if hi is not None: d["max"] = hi
    if choices: d["choices"] = choices
    return d


LIBRARY = [
    # ---- controls: the segment's sliders, checkboxes, colours -----------------
    _n("Speed", "controls", "frame", [], [("value", F)], [_p("label", "text", "Speed")],
       "$out.value = SEGMENT.speed * (1.0f / 255.0f);", "the Speed slider, 0..1"),
    _n("Intensity", "controls", "frame", [], [("value", F)], [_p("label", "text", "Intensity")],
       "$out.value = SEGMENT.intensity * (1.0f / 255.0f);", "the Intensity slider, 0..1"),
    _n("Custom 1", "controls", "frame", [], [("value", F)], [_p("label", "text", "Custom 1")],
       "$out.value = SEGMENT.custom1 * (1.0f / 255.0f);", "the Custom 1 slider, 0..1"),
    _n("Custom 2", "controls", "frame", [], [("value", F)], [_p("label", "text", "Custom 2")],
       "$out.value = SEGMENT.custom2 * (1.0f / 255.0f);", "the Custom 2 slider, 0..1"),
    _n("Custom 3", "controls", "frame", [], [("value", F)], [_p("label", "text", "Custom 3")],
       "$out.value = SEGMENT.custom3 * (1.0f / 31.0f);",
       "the Custom 3 slider, 0..1 - FIVE BITS on the device, 32 steps"),
    _n("Check 1", "controls", "frame", [], [("on", B)], [_p("label", "text", "Check 1")], "$out.on = SEGMENT.check1;", "checkbox 1"),
    _n("Check 2", "controls", "frame", [], [("on", B)], [_p("label", "text", "Check 2")], "$out.on = SEGMENT.check2;", "checkbox 2"),
    _n("Check 3", "controls", "frame", [], [("on", B)], [_p("label", "text", "Check 3")], "$out.on = SEGMENT.check3;", "checkbox 3"),
    _n("Colour 1", "controls", "frame", [], [("color", C)], [], "$out.color = SEGCOLOR(0);", "the segment's primary colour"),
    _n("Colour 2", "controls", "frame", [], [("color", C)], [], "$out.color = SEGCOLOR(1);", "the segment's secondary colour"),
    _n("Colour 3", "controls", "frame", [], [("color", C)], [], "$out.color = SEGCOLOR(2);", "the segment's tertiary colour"),

    # ---- signals -------------------------------------------------------------
    _n("Time", "signals", "frame", [], [("t", F), ("dt", F)], [],
       "$out.t = t; $out.dt = (float)dt;", "seconds since start, and the frame's milliseconds"),
    _n("Audio", "signals", "frame", [],
       [("volume", F), ("bass", F), ("mid", F), ("treble", F), ("beat", B), ("hit", F)], [],
       """
{ um_data_t *um = cfx_getAudioData();
  int b_, m_, t_; cfx_bands((const uint8_t *)um->u_data[2], b_, m_, t_);
  $out.volume = *(float *)um->u_data[0] * (1.0f / 255.0f);
  $out.bass = b_ * (1.0f / 255.0f); $out.mid = m_ * (1.0f / 255.0f); $out.treble = t_ * (1.0f / 255.0f);
  const uint8_t k_ = fx_lowBeat(um);
  $out.beat = k_ != 0; $out.hit = k_ * (1.0f / 255.0f); }""",
       "levels 0..1, and the low-band beat this frame"),
    _n("FFT bin", "signals", "frame", [], [("level", F)], [_p("bin", "int", 0, 0, 15)],
       "$out.level = ((const uint8_t *)cfx_getAudioData()->u_data[2])[$p.bin] * (1.0f / 255.0f);",
       "one of the sixteen FFT bins, 0..1"),
    _n("Beat kick", "signals", "frame", [("beat", B, 0), ("throw", F, 1.0)], [("phase", F)], [],
       """
{ static uint16_t owed_ = 0; static float acc_ = 0.0f;
  if ($in.beat) { uint32_t k = owed_ + 255u; if (k > 620u) k = 620u; owed_ = (uint16_t)k; }
  if (owed_) { uint32_t g = ((uint32_t)owed_ * dt) / 70u; if (!g) g = 1; if (g > owed_) g = owed_;
    acc_ += (float)g * $in.throw * (1.0f / 620.0f); owed_ = (uint16_t)(owed_ - g); }
  $out.phase = acc_; }""",
       "a phase that lurches forward on each beat and settles over ~140 ms - add it to a position"),
    _n("Number", "signals", "frame", [], [("value", F)], [_p("value", "float", 1.0, -1000.0, 1000.0)],
       "$out.value = $p.value;", "a constant"),
    _n("Toggle", "signals", "frame", [], [("on", B)], [_p("on", "bool", True)],
       "$out.on = $p.on;", "a constant boolean"),
    _n("Colour", "signals", "frame", [], [("color", C)], [_p("rgb", "color", [255, 128, 0])],
       "$out.color = RGBW32($p.rgb_r, $p.rgb_g, $p.rgb_b, 0);", "a fixed colour"),

    # ---- coordinates ----------------------------------------------------------
    _n("Coords", "coords", "pixel", [],
       [("u", F), ("v", F), ("cx", F), ("cy", F), ("r", F), ("angle", F)], [],
       "$out.u = u; $out.v = v; $out.cx = cx; $out.cy = cy; $out.r = r; $out.angle = ang;",
       "where this pixel is: 0..1, centred -1..1, polar"),
    _n("Direction", "coords", "pixel", [], [("nx", F), ("ny", F), ("nz", F)], [],
       "$out.nx = nx; $out.ny = ny; $out.nz = nz;",
       "the pixel's outward direction on the cube (a dome elsewhere) - seamless across faces"),
    _n("Pixel", "coords", "pixel", [], [("x", F), ("y", F), ("i", F)], [],
       "$out.x = (float)px; $out.y = (float)py; $out.i = (float)(py * W + px);", "integer pixel and index"),

    # ---- generators -------------------------------------------------------------
    _n("Noise", "generate", "pixel", [("x", F, 0.0), ("y", F, 0.0), ("z", F, 0.0), ("scale", F, 4.0)],
       [("value", F)], [],
       "$out.value = perlin8((uint16_t)($in.x * $in.scale * 256.0f), (uint16_t)($in.y * $in.scale * 256.0f), (uint16_t)($in.z * $in.scale * 256.0f)) * (1.0f / 255.0f);",
       "Perlin noise of a point, 0..1 - feed Direction for a seamless field, Time into z to animate"),
    _n("Wave", "generate", "pixel", [("x", F, 0.0), ("phase", F, 0.0), ("cycles", F, 3.0)], [("value", F)],
       [_p("shape", "choice", "sine", choices=["sine", "triangle", "square", "saw"])],
       """
{ float f_ = $in.x * $in.cycles + $in.phase; f_ -= floorf(f_);
  const char *s_ = "$p.shape";
  if (s_[1] == 'i') $out.value = 0.5f + 0.5f * cfx_sinf16(f_ * 6.28318531f);
  else if (s_[0] == 't') $out.value = (f_ < 0.5f) ? f_ * 2.0f : 2.0f - f_ * 2.0f;
  else if (s_[1] == 'q') $out.value = (f_ < 0.5f) ? 1.0f : 0.0f;
  else $out.value = f_; }""",
       "a periodic wave of its input, 0..1"),
    _n("Ripple", "generate", "pixel", [("cx", F, 0.0), ("cy", F, 0.0), ("phase", F, 0.0), ("rings", F, 4.0)],
       [("value", F)], [],
       "{ const float d_ = sqrtf(($in.cx - cx) * ($in.cx - cx) + ($in.cy - cy) * ($in.cy - cy)); float f_ = d_ * $in.rings - $in.phase; f_ -= floorf(f_); $out.value = 0.5f + 0.5f * cfx_sinf16(f_ * 6.28318531f); }",
       "rings radiating from a point (cx, cy in -1..1)"),
    _n("Sparkle", "generate", "pixel", [("density", F, 0.1), ("seed", F, 0.0)], [("value", F)], [],
       "{ uint32_t h_ = (uint32_t)(px * 73856093u) ^ (uint32_t)(py * 19349663u) ^ (uint32_t)($in.seed * 83492791.0f); h_ ^= h_ >> 13; h_ *= 0x5bd1e995u; h_ ^= h_ >> 15; $out.value = ((h_ & 0xFFFFu) * (1.0f / 65535.0f) < $in.density) ? 1.0f : 0.0f; }",
       "random pixels lit, a fraction `density` of them; change seed over time to twinkle"),
    _n("Stripes", "generate", "pixel", [("x", F, 0.0), ("count", F, 6.0), ("phase", F, 0.0), ("duty", F, 0.5)],
       [("value", F)], [],
       "{ float f_ = $in.x * $in.count + $in.phase; f_ -= floorf(f_); $out.value = (f_ < $in.duty) ? 1.0f : 0.0f; }",
       "hard bands along an input"),

    # ---- maths -------------------------------------------------------------------
    _n("Add", "maths", "pixel", [("a", F, 0.0), ("b", F, 0.0)], [("result", F)], [], "$out.result = $in.a + $in.b;"),
    _n("Subtract", "maths", "pixel", [("a", F, 0.0), ("b", F, 0.0)], [("result", F)], [], "$out.result = $in.a - $in.b;"),
    _n("Multiply", "maths", "pixel", [("a", F, 1.0), ("b", F, 1.0)], [("result", F)], [], "$out.result = $in.a * $in.b;"),
    _n("Divide", "maths", "pixel", [("a", F, 1.0), ("b", F, 1.0)], [("result", F)], [],
       "$out.result = (fabsf($in.b) > 1e-6f) ? $in.a / $in.b : 0.0f;"),
    _n("Mix", "maths", "pixel", [("a", F, 0.0), ("b", F, 1.0), ("t", F, 0.5)], [("result", F)], [],
       "$out.result = $in.a + ($in.b - $in.a) * $in.t;", "linear interpolation"),
    _n("Remap", "maths", "pixel", [("x", F, 0.0)], [("result", F)],
       [_p("in_lo", "float", 0.0), _p("in_hi", "float", 1.0), _p("out_lo", "float", 0.0), _p("out_hi", "float", 1.0)],
       "$out.result = $p.out_lo + ($in.x - $p.in_lo) * (($p.out_hi - $p.out_lo) / (($p.in_hi - $p.in_lo) != 0.0f ? ($p.in_hi - $p.in_lo) : 1.0f));"),
    _n("Clamp", "maths", "pixel", [("x", F, 0.0)], [("result", F)], [_p("lo", "float", 0.0), _p("hi", "float", 1.0)],
       "$out.result = ($in.x < $p.lo) ? $p.lo : (($in.x > $p.hi) ? $p.hi : $in.x);"),
    _n("Fract", "maths", "pixel", [("x", F, 0.0)], [("result", F)], [], "$out.result = $in.x - floorf($in.x);"),
    _n("Abs", "maths", "pixel", [("x", F, 0.0)], [("result", F)], [], "$out.result = fabsf($in.x);"),
    _n("Power", "maths", "pixel", [("x", F, 0.0), ("e", F, 2.0)], [("result", F)], [],
       "$out.result = powf($in.x < 0.0f ? 0.0f : $in.x, $in.e);"),
    _n("Sine", "maths", "pixel", [("x", F, 0.0)], [("result", F)], [],
       "$out.result = cfx_sinf16($in.x * 6.28318531f);", "sin of x turns, -1..1"),
    _n("Smoothstep", "maths", "pixel", [("x", F, 0.0)], [("result", F)], [_p("e0", "float", 0.0), _p("e1", "float", 1.0)],
       "{ float t_ = ($in.x - $p.e0) / (($p.e1 - $p.e0) != 0.0f ? ($p.e1 - $p.e0) : 1.0f); t_ = t_ < 0.0f ? 0.0f : (t_ > 1.0f ? 1.0f : t_); $out.result = t_ * t_ * (3.0f - 2.0f * t_); }"),
    _n("Threshold", "maths", "pixel", [("x", F, 0.0), ("at", F, 0.5)], [("on", B), ("value", F)], [],
       "$out.on = $in.x >= $in.at; $out.value = $out.on ? 1.0f : 0.0f;"),
    _n("Select", "maths", "pixel", [("on", B, 0), ("a", F, 0.0), ("b", F, 1.0)], [("result", F)], [],
       "$out.result = $in.on ? $in.b : $in.a;", "b when on, else a"),
    _n("Min", "maths", "pixel", [("a", F, 0.0), ("b", F, 0.0)], [("result", F)], [], "$out.result = ($in.a < $in.b) ? $in.a : $in.b;"),
    _n("Max", "maths", "pixel", [("a", F, 0.0), ("b", F, 0.0)], [("result", F)], [], "$out.result = ($in.a > $in.b) ? $in.a : $in.b;"),
    _n("Not", "maths", "pixel", [("on", B, 0)], [("result", B)], [], "$out.result = !$in.on;"),

    # ---- colour -------------------------------------------------------------------
    _n("Palette", "colour", "pixel", [("index", F, 0.0), ("brightness", F, 1.0)], [("color", C)], [],
       "$out.color = mq_scale(SEGMENT.color_from_palette((uint8_t)(int)($in.index * 255.0f), false, true, 0), (uint8_t)(gc_sat($in.brightness) * 255.0f));",
       "the segment's palette at index 0..1 (wraps), scaled"),
    _n("HSV", "colour", "pixel", [("h", F, 0.0), ("s", F, 1.0), ("v", F, 1.0)], [("color", C)], [],
       "$out.color = gc_hsv($in.h, $in.s, $in.v);", "hue 0..1 round the wheel"),
    _n("Scale", "colour", "pixel", [("color", C, 0), ("by", F, 1.0)], [("color", C)], [],
       "$out.color = mq_scale($in.color, (uint8_t)(gc_sat($in.by) * 255.0f));", "brightness"),
    _n("Blend", "colour", "pixel", [("under", C, 0), ("over", C, 0), ("amount", F, 1.0)], [("color", C)],
       [_p("mode", "choice", "over", choices=["over", "add", "multiply", "screen", "max", "min"])],
       "$out.color = gc_blend_$p.mode($in.under, $in.over, gc_sat($in.amount));",
       "layer `over` onto `under` - the layering node"),
    _n("Mask", "colour", "pixel", [("color", C, 0), ("mask", F, 1.0)], [("color", C)], [],
       "$out.color = mq_scale($in.color, (uint8_t)(gc_sat($in.mask) * 255.0f));", "multiply a colour by a 0..1 field"),
    _n("Previous", "colour", "pixel", [], [("color", C)], [],
       "$out.color = SEGMENT.is2D() ? SEGMENT.getPixelColorXY(px, py) : SEGMENT.getPixelColor(px);",
       "this pixel's colour from the LAST frame - feedback, for trails and fades"),
    _n("Fade", "colour", "pixel", [("color", C, 0), ("keep", F, 0.9)], [("color", C)], [],
       "$out.color = mq_scale($in.color, (uint8_t)(gc_sat($in.keep) * 255.0f));", "same as Scale; reads better after Previous"),
    _n("Split", "colour", "pixel", [("color", C, 0)], [("r", F), ("g", F), ("b", F), ("luma", F)], [],
       "$out.r = (($in.color >> 16) & 255) * (1.0f / 255.0f); $out.g = (($in.color >> 8) & 255) * (1.0f / 255.0f); $out.b = ($in.color & 255) * (1.0f / 255.0f); $out.luma = $out.r * 0.3f + $out.g * 0.59f + $out.b * 0.11f;"),
    _n("Combine", "colour", "pixel", [("r", F, 0.0), ("g", F, 0.0), ("b", F, 0.0)], [("color", C)], [],
       "$out.color = RGBW32((uint8_t)(gc_sat($in.r) * 255.0f), (uint8_t)(gc_sat($in.g) * 255.0f), (uint8_t)(gc_sat($in.b) * 255.0f), 0);"),

    # ---- your own ----------------------------------------------------------------------
    _n("Expression", "custom", "pixel", [("a", F, 0.0), ("b", F, 0.0), ("c", F, 0.0)], [("result", F)],
       [_p("expr", "text", "a * b + c")],
       "{ const float a = $in.a, b = $in.b, c = $in.c; (void)a; (void)b; (void)c; $out.result = (float)($p.expr); }",
       "any C++ expression of a, b, c (and u, v, cx, cy, r, ang, nx, ny, nz, t) - a node you write yourself"),
    _n("Colour expression", "custom", "pixel", [("a", F, 0.0), ("b", F, 0.0), ("under", C, 0)], [("color", C)],
       [_p("expr", "text", "gc_hsv(a, 1.0f, b)")],
       "{ const float a = $in.a, b = $in.b; const uint32_t under = $in.under; (void)a; (void)b; (void)under; $out.color = (uint32_t)($p.expr); }",
       "any C++ expression giving a colour: gc_hsv(h,s,v), mq_scale(c, x), color_blend(a,b,x), SEGCOLOR(0)..."),

    # ---- output ---------------------------------------------------------------------
    _n("Output", "output", "pixel", [("color", C, 0)], [], [],
       "gc_out = $in.color;", "what the pixel shows - exactly one of these"),

    # ---- sub-graph boundaries -----------------------------------------------------
    # A graph that contains these can be used as a NODE in another graph: each
    # Graph input becomes an input pin of that node, each Graph output an
    # output pin, named and typed by the params here. The compiler inlines the
    # whole sub-graph, so there is no call and no cost. Compiled on its own -
    # previewing the sub-graph - a Graph input yields its default.
    _n("Graph input", "graph", "frame", [], [("value", F)],
       [_p("name", "text", "in"), _p("type", "choice", "float", choices=["float", "color", "bool"]),
        _p("default", "float", 0.0)],
       "$out.value = $p.default;", "an input pin of the node this graph becomes"),
    _n("Graph output", "graph", "pixel", [("value", F, 0.0)], [],
       [_p("name", "text", "out"), _p("type", "choice", "float", choices=["float", "color", "bool"])],
       "(void)$in.value;", "an output pin of the node this graph becomes"),

    # ---- tidiness ----------------------------------------------------------------------
    # Knots reroute a wire - a pass-through the compiler folds away. Notes and
    # Frames are decoration: the compiler skips them entirely.
    dict(_n("Knot", "graph", "frame", [("in", F, 0.0)], [("out", F)], [],
            "$out.out = $in.in;", "a bend in a wire - a pass-through with no cost"), narrow=True),
    dict(_n("Knot colour", "graph", "frame", [("in", C, 0)], [("out", C)], [],
            "$out.out = $in.in;", "a bend in a colour wire"), narrow=True),
    dict(_n("Note", "graph", "frame", [], [], [_p("text", "text", "note")],
            "", "a comment on the graph - not compiled"), decor=True, multiline=True),
    dict(_n("Frame", "graph", "frame", [], [],
            [_p("title", "text", "group"), _p("w", "int", 400, 80, 4000), _p("h", "int", 300, 60, 4000),
             _p("colour", "color", [90, 110, 160])],
            "", "a titled box - nodes inside move with it; not compiled"), decor=True),
]

# The helpers every generated file carries. Small, static, and named gc_ so
# they cannot collide with anything in wled.h or cube_fx_common.h.
HELPERS = r'''
static inline float gc_sat(float x) { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }
static inline uint32_t gc_hsv(float h, float s, float v) {
  h -= floorf(h); const float hh = h * 6.0f; const int i = (int)hh; const float f = hh - i;
  const float p = v * (1.0f - s), q = v * (1.0f - s * f), t = v * (1.0f - s * (1.0f - f));
  float r, g, b;
  switch (i) { case 0: r=v;g=t;b=p; break; case 1: r=q;g=v;b=p; break; case 2: r=p;g=v;b=t; break;
               case 3: r=p;g=q;b=v; break; case 4: r=t;g=p;b=v; break; default: r=v;g=p;b=q; break; }
  return RGBW32((uint8_t)(gc_sat(r)*255.0f), (uint8_t)(gc_sat(g)*255.0f), (uint8_t)(gc_sat(b)*255.0f), 0);
}
static inline uint32_t gc_blend_over(uint32_t u, uint32_t o, float a)     { return color_blend(u, o, (uint8_t)(a * 255.0f)); }
static inline uint32_t gc_blend_add(uint32_t u, uint32_t o, float a)      { return color_add(u, mq_scale(o, (uint8_t)(a * 255.0f)), true); }
static inline uint32_t gc_blend_max(uint32_t u, uint32_t o, float a) {
  o = mq_scale(o, (uint8_t)(a * 255.0f)); uint32_t r = 0;
  for (int s = 0; s < 24; s += 8) { const uint32_t x = (u >> s) & 255, y = (o >> s) & 255; r |= (x > y ? x : y) << s; }
  return r; }
static inline uint32_t gc_blend_min(uint32_t u, uint32_t o, float a) {
  uint32_t r = 0;
  for (int s = 0; s < 24; s += 8) { const uint32_t x = (u >> s) & 255, y = (o >> s) & 255; const uint32_t m = x < y ? x : y;
    r |= (uint32_t)(x + (int)((int)m - (int)x) * a) << s; }
  return r; }
static inline uint32_t gc_blend_multiply(uint32_t u, uint32_t o, float a) {
  uint32_t r = 0;
  for (int s = 0; s < 24; s += 8) { const uint32_t x = (u >> s) & 255, y = (o >> s) & 255; const uint32_t m = (x * y) / 255u;
    r |= (uint32_t)(x + (int)((int)m - (int)x) * a) << s; }
  return r; }
static inline uint32_t gc_blend_screen(uint32_t u, uint32_t o, float a) {
  uint32_t r = 0;
  for (int s = 0; s < 24; s += 8) { const uint32_t x = (u >> s) & 255, y = (o >> s) & 255; const uint32_t m = 255u - ((255u - x) * (255u - y)) / 255u;
    r |= (uint32_t)(x + (int)((int)m - (int)x) * a) << s; }
  return r; }
'''


def library(extra=()):
    """The node types by name: the library, then any user nodes over it."""
    lib = {}
    for d in LIBRARY:
        lib[d["name"]] = d
    for d in extra:
        try:
            lib[d["name"]] = d
        except Exception:
            pass
    return lib
