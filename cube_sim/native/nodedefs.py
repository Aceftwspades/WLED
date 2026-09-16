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
    _n("Speed", "controls", "frame", [], [("value", F)], [_p("label", "text", "Speed"), _p("default", "int", 128, 0, 255)],
       "$out.value = SEGMENT.speed * (1.0f / 255.0f);", "the Speed slider, 0..1"),
    _n("Intensity", "controls", "frame", [], [("value", F)], [_p("label", "text", "Intensity"), _p("default", "int", 128, 0, 255)],
       "$out.value = SEGMENT.intensity * (1.0f / 255.0f);", "the Intensity slider, 0..1"),
    _n("Custom 1", "controls", "frame", [], [("value", F)], [_p("label", "text", "Custom 1"), _p("default", "int", 128, 0, 255)],
       "$out.value = SEGMENT.custom1 * (1.0f / 255.0f);", "the Custom 1 slider, 0..1"),
    _n("Custom 2", "controls", "frame", [], [("value", F)], [_p("label", "text", "Custom 2"), _p("default", "int", 128, 0, 255)],
       "$out.value = SEGMENT.custom2 * (1.0f / 255.0f);", "the Custom 2 slider, 0..1"),
    _n("Custom 3", "controls", "frame", [], [("value", F)], [_p("label", "text", "Custom 3"), _p("default", "int", 16, 0, 31)],
       "$out.value = SEGMENT.custom3 * (1.0f / 31.0f);",
       "the Custom 3 slider, 0..1 - FIVE BITS on the device, 32 steps"),
    _n("Check 1", "controls", "frame", [], [("on", B)], [_p("label", "text", "Check 1"), _p("default", "bool", False)], "$out.on = SEGMENT.check1;", "checkbox 1"),
    _n("Check 2", "controls", "frame", [], [("on", B)], [_p("label", "text", "Check 2"), _p("default", "bool", False)], "$out.on = SEGMENT.check2;", "checkbox 2"),
    _n("Check 3", "controls", "frame", [], [("on", B)], [_p("label", "text", "Check 3"), _p("default", "bool", False)], "$out.on = SEGMENT.check3;", "checkbox 3"),
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
    # --- state between frames -------------------------------------------------------
    dict(_n("Integrate", "signals", "frame", [("rate", F, 1.0), ("reset", B, False)], [("value", F)],
            [_p("wrap", "float", 1.0)],
            "if ($first || $in.reset) $st.acc = 0.0f;\n"
            "$st.acc += $in.rate * ((float)dt * 0.001f);\n"
            "if ($p.wrap > 0.0f) $st.acc -= floorf($st.acc / $p.wrap) * $p.wrap;\n"
            "$out.value = $st.acc;",
            "a running total of rate per second - a phase that keeps going; wrap 0 = never"),
         state=["acc"]),
    dict(_n("Envelope", "signals", "frame", [("x", F, 0.0)], [("value", F)],
            [_p("attack", "float", 20.0), _p("release", "float", 250.0)],
            "if ($first) $st.y = $in.x;\n"
            "{ const float tau_ = ($in.x > $st.y) ? $p.attack : $p.release;\n"
            "  const float k_ = tau_ > 0.0f ? 1.0f - expf(-(float)dt / tau_) : 1.0f;\n"
            "  $st.y += ($in.x - $st.y) * k_; }\n"
            "$out.value = $st.y;",
            "smooths a signal: fast up (attack ms), slow down (release ms)"),
         state=["y"]),
    dict(_n("Random hold", "signals", "frame", [("trigger", B, False)], [("value", F), ("changed", B)],
            [],
            "if ($first) { $st.val = gc_rnd(); $st.prev = 0.0f; }\n"
            "$out.changed = $in.trigger && $st.prev < 0.5f;\n"
            "if ($out.changed) $st.val = gc_rnd();\n"
            "$st.prev = $in.trigger ? 1.0f : 0.0f;\n"
            "$out.value = $st.val;",
            "a random 0..1 that holds until the trigger goes on - re-aim on the beat"),
         state=["val", "prev"]),
    dict(_n("Rising edge", "signals", "frame", [("x", B, False)], [("pulse", B)], [],
            "$out.pulse = $in.x && $st.prev < 0.5f; $st.prev = $in.x ? 1.0f : 0.0f;",
            "true for one frame when x turns on"),
         state=["prev"]),
    dict(_n("Spectrum", "signals", "pixel", [("index", F, 0.0)], [("level", F)],
            [_p("smooth", "float", 0.5, 0.0, 0.99), _p("interpolate", "bool", True)],
            "{ float *S_ = $st;\n"
            "  if (S_[16] != (float)(SEGENV.call & 0xFFFF) || $first) {\n"
            "    um_data_t *um_ = cfx_getAudioData(); const uint8_t *fft_ = (const uint8_t *)um_->u_data[2];\n"
            "    const float k_ = $first ? 1.0f : 1.0f - gc_sat($p.smooth);\n"
            "    for (int i_ = 0; i_ < 16; i_++) S_[i_] += ((float)fft_[i_] * (1.0f / 255.0f) - S_[i_]) * k_;\n"
            "    S_[16] = (float)(SEGENV.call & 0xFFFF); }\n"
            "  const float fi_ = gc_sat($in.index) * 15.0f; const int i0_ = (int)fi_; const int i1_ = i0_ < 15 ? i0_ + 1 : 15;\n"
            "  $out.level = $p.interpolate ? S_[i0_] + (S_[i1_] - S_[i0_]) * (fi_ - (float)i0_) : S_[i0_]; }",
            "the 16 FFT bins, smoothed, read at index 0..1 - a spectrum along a coordinate"),
         state=17),
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
    _n("Position", "coords", "pixel", [], [("x", F), ("y", F), ("z", F)], [],
       "$out.x = X3; $out.y = Y3; $out.z = Z3;",
       "the pixel's position in the cube's -1..1 box (z up, 1 on the lid); x, y on a matrix"),
    _n("Cube face", "coords", "pixel", [], [("face", F), ("a", F), ("b", F)], [],
       "{ const float ax_ = fabsf(X3), ay_ = fabsf(Y3), az_ = fabsf(Z3);\n"
       "  float m_, pa_, pb_;\n"
       "  if (cube && az_ >= ax_ && az_ >= ay_) { $out.face = Z3 >= 0 ? 4.0f : 5.0f; m_ = az_; pa_ = X3; pb_ = Y3; }\n"
       "  else if (cube && ay_ >= ax_)          { $out.face = Y3 >= 0 ? 2.0f : 3.0f; m_ = ay_; pa_ = X3; pb_ = Z3; }\n"
       "  else if (cube)                         { $out.face = X3 >= 0 ? 0.0f : 1.0f; m_ = ax_; pa_ = Y3; pb_ = Z3; }\n"
       "  else                                   { $out.face = 4.0f; m_ = 1.0f; pa_ = X3; pb_ = Y3; }\n"
       "  if (m_ < 1e-3f) m_ = 1e-3f;\n"
       "  $out.a = pa_ / m_ * 0.5f + 0.5f; $out.b = pb_ / m_ * 0.5f + 0.5f; }",
       "which face (0..5: +x -x +y -y top bottom) and where on it, a and b 0..1 - tiles per face"),
    _n("Cube ring", "coords", "pixel", [], [("around", F), ("depth", F)], [],
       "{ if (cube) {\n"
       "    $out.around = cfx_atan2f(Y3, X3) * (0.5f / 3.14159265f) + 0.5f;\n"
       "    $out.depth = (Z3 > 0.999f) ? (fmaxf(fabsf(X3), fabsf(Y3)) * 0.5f) : (0.5f + (1.0f - Z3) * 0.25f);\n"
       "  } else { $out.around = u; $out.depth = v; } }",
       "the lid-and-walls ruler: around the cube 0..1, depth 0 at the lid's centre, 0.5 at the rim, 1 at the bottom edge"),
    _n("Ring to uv", "coords", "pixel", [("around", F, 0.0), ("depth", F, 0.5)], [("u", F), ("v", F)], [],
       "gc_ring_uv($in.around, $in.depth, W, H, B, cube, $out.u, $out.v);",
       "Cube ring backwards: a point on the ring as the u, v Previous at reads - step depth to read up the walls"),
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
    _n("Mandelbrot", "generate", "pixel", [("x", F, 0.0), ("y", F, 0.0), ("jx", F, 0.0), ("jy", F, 0.0)], [("value", F)],
       [_p("iterations", "int", 40, 4, 200), _p("julia", "bool", False)],
       "$out.value = $p.julia ? gc_mandel($in.jx, $in.jy, $in.x, $in.y, $p.iterations) : gc_mandel($in.x, $in.y, 0.0f, 0.0f, $p.iterations);",
       "escape time at the point x, y as 0..1 (1 = inside); Julia mode uses jx, jy as the constant and x, y as the start"),
    _n("Hash", "generate", "pixel", [("x", F, 0.0), ("y", F, 0.0), ("seed", F, 0.0)], [("value", F)], [],
       "$out.value = gc_hash($in.x, $in.y, $in.seed);",
       "a random 0..1 that is the same every frame for the same x, y, seed - one per cell or column"),
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
    _n("Floor", "maths", "pixel", [("x", F, 0.0)], [("result", F)], [], "$out.result = floorf($in.x);", "round down"),
    _n("Modulo", "maths", "pixel", [("x", F, 0.0), ("m", F, 1.0)], [("result", F)], [],
       "$out.result = ($in.m != 0.0f) ? $in.x - floorf($in.x / $in.m) * $in.m : 0.0f;", "x mod m, always 0..m"),
    _n("Cosine", "maths", "pixel", [("x", F, 0.0)], [("result", F)], [],
       "$out.result = 0.5f + 0.5f * cosf($in.x * 6.2831853f);", "0..1 cosine, one cycle per unit of x"),
    _n("Band", "maths", "pixel", [("x", F, 0.0), ("sharp", F, 1.0)], [("result", F)], [],
       "{ const float c_ = 0.5f + 0.5f * cosf($in.x * 6.2831853f); $out.result = powf(c_, fmaxf(0.01f, $in.sharp)); }",
       "a soft band around every whole number of x, narrower as sharp rises - slabs, stripes"),
    _n("Dot 3", "maths", "pixel", [("ax", F, 0.0), ("ay", F, 0.0), ("az", F, 0.0), ("bx", F, 1.0), ("by", F, 0.0), ("bz", F, 0.0)],
       [("result", F)], [],
       "$out.result = $in.ax * $in.bx + $in.ay * $in.by + $in.az * $in.bz;",
       "dot product - a position against a direction gives the distance along it (slabs, sweeps)"),
    _n("Rotate", "maths", "pixel", [("x", F, 0.0), ("y", F, 0.0), ("turns", F, 0.0)], [("x", F), ("y", F)], [],
       "{ const float a_ = $in.turns * 6.2831853f; const float c_ = cosf(a_), s_ = sinf(a_);\n"
       "  $out.x = $in.x * c_ - $in.y * s_; $out.y = $in.x * s_ + $in.y * c_; }",
       "turn a pair of coordinates by `turns` (1 = a full turn) - a tumble is three of these"),
    _n("Length", "maths", "pixel", [("x", F, 0.0), ("y", F, 0.0), ("z", F, 0.0)], [("result", F)], [],
       "$out.result = sqrtf($in.x * $in.x + $in.y * $in.y + $in.z * $in.z);", "distance from the origin"),
    _n("Direction to", "maths", "pixel", [("turns_a", F, 0.0), ("turns_b", F, 0.0)], [("x", F), ("y", F), ("z", F)], [],
       "{ const float a_ = $in.turns_a * 6.2831853f, b_ = $in.turns_b * 6.2831853f;\n"
       "  $out.x = cosf(a_) * cosf(b_); $out.y = sinf(a_) * cosf(b_); $out.z = sinf(b_); }",
       "a unit direction from two angles (turns) - the normal of a tumbling slab"),
    _n("Log", "maths", "pixel", [("x", F, 1.0)], [("result", F)], [],
       "$out.result = logf($in.x > 1e-6f ? $in.x : 1e-6f);", "natural log; a log spiral is density * log(radius) + arms * angle"),
    _n("Exp", "maths", "pixel", [("x", F, 0.0)], [("result", F)], [],
       "$out.result = expf($in.x < 60.0f ? $in.x : 60.0f);", "e to the x - a zoom that is the same proportion per second"),
    _n("Mirror fold", "maths", "pixel", [("x", F, 0.0), ("y", F, 0.0), ("z", F, 1.0)], [("x", F), ("y", F), ("z", F)],
       [_p("symmetry", "choice", "octahedral",
           choices=["dihedral 3", "dihedral 4", "dihedral 5", "dihedral 6", "dihedral 7", "dihedral 8", "dihedral 9", "dihedral 10",
                    "tetrahedral", "octahedral", "icosahedral"])],
       "{ float fx_ = $in.x, fy_ = $in.y, fz_ = $in.z;\n"
       "  static const char *syms_[] = {\"dihedral 3\", \"dihedral 4\", \"dihedral 5\", \"dihedral 6\", \"dihedral 7\", \"dihedral 8\", \"dihedral 9\", \"dihedral 10\", \"tetrahedral\", \"octahedral\", \"icosahedral\"};\n"
       "  int sym_ = 9; for (int k_ = 0; k_ < 11; k_++) if (!strcmp(syms_[k_], \"$p.symmetry\")) sym_ = k_;\n"
       "  gc_fold(sym_, fx_, fy_, fz_); $out.x = fx_; $out.y = fy_; $out.z = fz_; }",
       "a kaleidoscope: reflects a direction into one fundamental domain of a finite mirror group, so whatever is drawn from the result is mirrored 6 to 120 times over the solid"),
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
    _n("Palette source", "colour", "pixel", [("index", F, 0.0), ("brightness", F, 1.0)], [("color", C)], [],
       "$out.color = gc_srcpal((uint8_t)(int)($in.index * 255.0f), (uint8_t)(gc_sat($in.brightness) * 255.0f));",
       "the palette-source setting's colours (what the audio palettes draw from) at index 0..1; "
       "the segment's palette where the palettes usermod is absent"),
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
    _n("Previous at", "colour", "pixel", [("u", F, 0.0), ("v", F, 0.0)], [("color", C)], [],
       "$out.color = gc_prev_at($in.u, $in.v, W, H, is2d);",
       "last frame's colour at a logical position (0..1) - read below to make things rise, beside to smear"),
    # A field is a number per pixel kept between frames - heat, height, age -
    # separate from the colour, so a simulation is not bent by its palette.
    # Read last frame's value anywhere (a neighbour, a step down the ring);
    # write this pixel's value for next frame. Two per graph, 0 and 1.
    dict(_n("Field", "colour", "pixel", [("u", F, 0.0), ("v", F, 0.0)], [("value", F)],
            [_p("field", "int", 0, 0, 1)],
            "{ const int x_ = (int)floorf(gc_sat($in.u) * (float)(W - 1) + 0.5f), y_ = (int)floorf(gc_sat($in.v) * (float)(H - 1) + 0.5f);\n"
            "  $out.value = gc_fr$p.field[y_ * W + x_]; }",
            "last frame's value of the field at a logical position (0..1) - a simulation's memory"),
         field=True),
    dict(_n("Field write", "colour", "pixel", [("value", F, 0.0)], [], [_p("field", "int", 0, 0, 1)],
            "gc_fw$p.field[py * W + px] = $in.value;",
            "this pixel's value of the field for next frame - what Field will read"),
         field=True),
    # Drainage on the pixel grid: every pixel drains to its lowest neighbour
    # in a height field, and the water that arrives here is the sum of last
    # frame's water on the neighbours that drain to this pixel. Gather, not
    # scatter, so it fits a per-pixel graph; convergence falls out.
    dict(_n("Drain", "colour", "pixel", [], [("water", F), ("sink", B), ("height", F)],
            [_p("height_field", "int", 0, 0, 1), _p("water_field", "int", 1, 0, 1)],
            "{ const float *Hf_ = gc_fr$p.height_field; const float *Wf_ = gc_fr$p.water_field;\n"
            "  const int me_ = py * W + px; float sum_ = 0.0f; const float h0_ = Hf_[me_];\n"
            "  static const int dx_[4] = {1, -1, 0, 0}, dy_[4] = {0, 0, 1, -1};\n"
            "  float lowest_ = h0_; $out.sink = true;\n"
            "  for (int k_ = 0; k_ < 4; k_++) {\n"
            "    const int nx_ = px + dx_[k_], ny_ = py + dy_[k_];\n"
            "    if (nx_ < 0 || ny_ < 0 || nx_ >= W || ny_ >= H) continue;\n"
            "    const int n_ = ny_ * W + nx_; const float hn_ = Hf_[n_];\n"
            "    if (hn_ < lowest_) { lowest_ = hn_; $out.sink = false; }\n"
            "    /* does n drain to me? me must be n's lowest neighbour */\n"
            "    float nl_ = hn_; int best_ = -1;\n"
            "    for (int j_ = 0; j_ < 4; j_++) {\n"
            "      const int mx_ = nx_ + dx_[j_], my_ = ny_ + dy_[j_];\n"
            "      if (mx_ < 0 || my_ < 0 || mx_ >= W || my_ >= H) continue;\n"
            "      const int m_ = my_ * W + mx_; if (Hf_[m_] < nl_) { nl_ = Hf_[m_]; best_ = m_; } }\n"
            "    if (best_ == me_) sum_ += Wf_[n_]; }\n"
            "  $out.water = sum_; $out.height = h0_; }",
            "watershed: the water flowing into this pixel from the neighbours that drain to it (their last-frame water), whether it is a sink, and its height - write the height and the water back with Field write"),
         fields=["height_field", "water_field"]),
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
    # The metadata string's other fields. One per graph; without it the
    # defaults below apply. Slider defaults and labels sit on the control
    # nodes themselves.
    dict(_n("Effect settings", "output", "frame", [], [],
            [_p("palette", "int", 11, 0, 255),
             _p("dimensions", "choice", "both", choices=["both", "1-D", "2-D"]),
             _p("audio", "choice", "none", choices=["none", "volume", "frequency"]),
             _p("colours", "text", "")],
            "", "the effect's metadata: default palette id, 1-D/2-D, audio flag, colour-slot labels"),
         decor=True),

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
static inline float gc_fract(float x) { return x - floorf(x); }
static inline float gc_rnd() { return (float)hw_random16() * (1.0f / 65535.0f); }
// A stable 0..1 from a position and a seed - the same every frame for the same
// inputs, so cells, tiles and columns can each own a random number.
static inline float gc_hash(float x, float y, float seed) {
  uint32_t h = (uint32_t)(int32_t)floorf(x * 4096.0f) * 374761393u
             ^ (uint32_t)(int32_t)floorf(y * 4096.0f) * 668265263u
             ^ (uint32_t)(int32_t)floorf(seed * 4096.0f) * 2246822519u;
  h ^= h >> 13; h *= 1274126177u; h ^= h >> 16;
  return (float)(h & 0xFFFFFFu) * (1.0f / 16777215.0f);
}
// Last frame's colour at a logical position (0..1, 0..1). On a matrix that is
// a neighbour read for trails and flows; the pixels already written this
// frame read as this frame's, as WLED's own fire effects accept.
// The inverse of the lid-and-walls ruler: (around, depth) back to the logical
// pixel, as u, v - the exact inverse of cfx_pos, so a read there lands on the
// pixel Cube ring would call that. Lets a feedback read step along the ring.
static inline int gc_q(float t, int B) { int i = (int)floorf((t + 1.0f) * 0.5f * (float)B); return i < 0 ? 0 : (i > B - 1 ? B - 1 : i); }
static inline void gc_ring_uv(float around, float depth, int W, int H, int B, bool cube, float &u, float &v) {
  around -= floorf(around);
  if (!cube) { u = around; v = gc_sat(depth); return; }
  const float a = (around - 0.5f) * 6.2831853f;
  float cx_ = cosf(a), sy_ = sinf(a);
  const float m = fmaxf(fabsf(cx_), fabsf(sy_)); if (m > 1e-6f) { cx_ /= m; sy_ /= m; }
  int px_, py_;
  if (depth < 0.5f) { const float r = depth * 2.0f; px_ = B + gc_q(cx_ * r, B); py_ = B + gc_q(-sy_ * r, B); }
  else {
    const float Z = 1.0f - (depth - 0.5f) * 4.0f;
    if (fabsf(sy_) >= fabsf(cx_)) { px_ = B + gc_q(cx_, B); py_ = (sy_ > 0) ? gc_q(Z, B) : 2 * B + gc_q(-Z, B); }
    else                          { py_ = B + gc_q(-sy_, B); px_ = (cx_ < 0) ? gc_q(Z, B) : 2 * B + gc_q(-Z, B); }
  }
  u = (W > 1) ? (float)px_ / (float)(W - 1) : 0.5f; v = (H > 1) ? (float)py_ / (float)(H - 1) : 0.5f;
}
// A finite reflection group's mirrors, each normal pointed at one generic
// direction so every set is the positive roots of a single chamber and the
// fold terminates (see cube_fx_39_kaleidoscope.cpp for the reasoning).
//   sym 0..7  dihedral D(n), n = sym + 3 (with the equator)
//   sym 8     tetrahedral   sym 9  octahedral   sym 10  icosahedral
static int gc_mirrors(int sym, float m[16][3]) {
  int n = 0;
  const float gx = 0.2374f, gy = 0.4451f, gz = 0.8632f;
  #define GC_MIR(a, b, c) { if (n < 16) { m[n][0] = (a); m[n][1] = (b); m[n][2] = (c); n++; } }
  if (sym <= 7) {
    const int k = sym + 3;
    for (int i = 0; i < k; i++) { const float a = (float)i * 3.14159265f / (float)k; GC_MIR(-sinf(a), cosf(a), 0.0f); }
    GC_MIR(0.0f, 0.0f, 1.0f);
  } else if (sym <= 9) {
    if (sym == 9) { GC_MIR(1, 0, 0); GC_MIR(0, 1, 0); GC_MIR(0, 0, 1); }
    GC_MIR(1, -1, 0); GC_MIR(1, 1, 0); GC_MIR(0, 1, -1); GC_MIR(0, 1, 1); GC_MIR(1, 0, -1); GC_MIR(1, 0, 1);
  } else {
    const float P = 1.61803399f, Q = 0.61803399f;
    GC_MIR(1, 0, 0); GC_MIR(0, 1, 0); GC_MIR(0, 0, 1);
    for (int a = 0; a < 2; a++) for (int b = 0; b < 2; b++) {
      const float sa = a ? -1.0f : 1.0f, sb = b ? -1.0f : 1.0f;
      GC_MIR(1.0f, sa * P, sb * Q); GC_MIR(sa * P, sb * Q, 1.0f); GC_MIR(sb * Q, 1.0f, sa * P);
    }
  }
  #undef GC_MIR
  for (int j = 0; j < n; j++) {
    const float L = sqrtf(m[j][0] * m[j][0] + m[j][1] * m[j][1] + m[j][2] * m[j][2]);
    float sgn = (m[j][0] * gx + m[j][1] * gy + m[j][2] * gz) < 0.0f ? -1.0f : 1.0f;
    if (L > 0.0f) sgn /= L;
    m[j][0] *= sgn; m[j][1] *= sgn; m[j][2] *= sgn;
  }
  return n;
}
// Reflect a direction into the group's fundamental domain: bounce off any
// mirror it is behind until nothing moves. Two or three sweeps in practice.
static inline void gc_fold(int sym, float &x, float &y, float &z) {
  static float mir[16][3]; static int nm = 0, have = -1;
  if (have != sym) { nm = gc_mirrors(sym, mir); have = sym; }
  for (int pass = 0; pass < 4; pass++) {
    bool moved = false;
    for (int j = 0; j < nm; j++) {
      const float d = x * mir[j][0] + y * mir[j][1] + z * mir[j][2];
      if (d < 0.0f) { const float t = 2.0f * d; x -= t * mir[j][0]; y -= t * mir[j][1]; z -= t * mir[j][2]; moved = true; }
    }
    if (!moved) break;
  }
}
// Escape time of z -> z^2 + c, smoothed, as 0..1 (1 = never escaped); a
// Julia set when jx, jy are given instead of the point itself.
static inline float gc_mandel(float cx, float cy, float zx, float zy, int maxit) {
  int i = 0; float x2 = zx * zx, y2 = zy * zy;
  while (i < maxit && x2 + y2 < 16.0f) { zy = 2.0f * zx * zy + cy; zx = x2 - y2 + cx; x2 = zx * zx; y2 = zy * zy; i++; }
  if (i >= maxit) return 1.0f;
  const float nu = (float)i + 1.0f - logf(logf(sqrtf(x2 + y2)) / 0.6931472f) / 0.6931472f;
  return gc_sat(nu / (float)maxit);
}
static inline uint32_t gc_prev_at(float u, float v, int W, int H, bool is2d) {
  int x = (int)floorf(gc_sat(u) * (float)(W - 1) + 0.5f), y = (int)floorf(gc_sat(v) * (float)(H - 1) + 0.5f);
  return is2d ? SEGMENT.getPixelColorXY(x, y) : SEGMENT.getPixelColor(x);
}
// The palette-source colour lives in the cube_fx palettes usermod. Weak, so a
// build without that usermod still links and the node falls back to the
// segment's own palette.
uint32_t cfxPaletteSourceColor(uint8_t pos, uint8_t bri) __attribute__((weak));
static inline uint32_t gc_srcpal(uint8_t pos, uint8_t bri) {
  if (cfxPaletteSourceColor) return cfxPaletteSourceColor(pos, bri);
  return mq_scale(SEGMENT.color_from_palette(pos, false, true, 0), bri);
}
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
