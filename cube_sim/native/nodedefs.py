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
    _n("Frame count", "signals", "frame", [], [("first", B), ("count", F)], [],
       "$out.first = (SEGENV.call == 0); $out.count = (float)SEGENV.call;",
       "true on the effect's first frame - for seeding a field - and the frame count"),
    _n("Loudest bin", "signals", "frame", [], [("bin", F), ("level", F)], [_p("from", "int", 1, 0, 15), _p("to", "int", 15, 0, 15)],
       "{ um_data_t *um_ = cfx_getAudioData(); const uint8_t *fft_ = (const uint8_t *)um_->u_data[2];\n"
       "  int b_ = $p.from; for (int i_ = $p.from; i_ <= $p.to && i_ < 16; i_++) if (fft_[i_] > fft_[b_]) b_ = i_;\n"
       "  $out.bin = (float)b_ * (1.0f / 15.0f); $out.level = (float)fft_[b_] * (1.0f / 255.0f); }",
       "which FFT bin is loudest (0..1 across the 16) and how loud - a hue for whatever the beat drops"),
    _n("Gravity", "signals", "frame", [("tilt_x", F, 0.0), ("tilt_y", F, 0.0)], [("gx", F), ("gy", F), ("gz", F), ("sensor", B)], [],
       "{ float gx_ = $in.tilt_x, gy_ = $in.tilt_y, gz_ = -1.0f; $out.sensor = false;\n"
       "#ifdef GC_HAS_IMU\n"
       "  { const CfxImuState &imu_ = cfx_imu(); if (imu_.valid) { gx_ = imu_.gx * (1.0f / 127.0f); gy_ = imu_.gy * (1.0f / 127.0f); gz_ = imu_.gz * (1.0f / 127.0f); $out.sensor = true; } }\n"
       "#endif\n"
       "  const float L_ = sqrtf(gx_ * gx_ + gy_ * gy_ + gz_ * gz_); const float iL_ = L_ > 1e-6f ? 1.0f / L_ : 1.0f;\n"
       "  $out.gx = gx_ * iL_; $out.gy = gy_ * iL_; $out.gz = gz_ * iL_; }",
       "where things fall, as a unit vector in the cube's frame: the IMU when one is fitted, else straight down tilted by the inputs"),
    # Emitters: up to eight things dropped on a trigger, each with a position,
    # a tag and an age; Shells reads them per pixel. `slots` carries where the
    # list lives so the two nodes can be wired.
    dict(_n("Emitters", "signals", "frame", [("trigger", B, False), ("x", F, 0.0), ("y", F, 0.0), ("z", F, 1.0),
                                             ("tag", F, 0.0), ("life", F, 4.0)],
            [("slots", F), ("count", F)], [_p("random", "bool", True)],
            "{ float *E_ = $st; if ($first) for (int k_ = 0; k_ < 8; k_++) E_[k_ * 6 + 4] = -1.0f;\n"
            "  int n_ = 0;\n"
            "  for (int k_ = 0; k_ < 8; k_++) { float *e_ = E_ + k_ * 6; if (e_[4] >= 0.0f) { e_[4] += (float)dt * 0.001f; if (e_[4] > e_[5]) e_[4] = -1.0f; else n_++; } }\n"
            "  if ($in.trigger) for (int k_ = 0; k_ < 8; k_++) { float *e_ = E_ + k_ * 6; if (e_[4] >= 0.0f) continue;\n"
            "    float px_ = $in.x, py_ = $in.y, pz_ = $in.z;\n"
            "    if ($p.random) { px_ = gc_rnd() * 2.0f - 1.0f; py_ = gc_rnd() * 2.0f - 1.0f; pz_ = gc_rnd() * 2.0f - 1.0f;\n"
            "      const float m_ = fmaxf(fabsf(px_), fmaxf(fabsf(py_), fabsf(pz_))); if (m_ > 1e-6f) { px_ /= m_; py_ /= m_; pz_ /= m_; } if (pz_ < -0.99f) pz_ = 1.0f; }\n"
            "    e_[0] = px_; e_[1] = py_; e_[2] = pz_; e_[3] = $in.tag; e_[4] = 0.0f; e_[5] = $in.life; n_++; break; }\n"
            "  $out.slots = (float)(E_ - gc_st); $out.count = (float)n_; }",
            "a list of up to eight events dropped on the trigger - at x, y, z, or at a random point on the surface - each with a tag and an age until `life`; feed `slots` to Shells"),
         state=48),
    # The one node a wire may loop back through: its output is what its input
    # was LAST frame, so a value can depend on its own past (a phase that
    # restarts only when a cycle is over, a gate that stays shut). The write
    # happens after every other frame-scope node has run.
    dict(_n("Delay", "signals", "frame", [("x", F, 0.0)], [("value", F)], [],
            "$out.value = $first ? 0.0f : $st.prev;",
            "last frame's x - the only way to wire a value back into what feeds it"),
         state=["prev"], late=True, late_code="$st.prev = $in.x;"),
    dict(_n("Spring", "signals", "frame", [("target", F, 0.0), ("kick", F, 0.0)], [("value", F), ("velocity", F)],
            [_p("hz", "float", 1.2), _p("damping", "float", 0.15)],
            "if ($first) { $st.x = $in.target; $st.v = 0.0f; }\n"
            "{ const float w_ = 6.2831853f * $p.hz, h_ = (float)dt * 0.001f;\n"
            "  $st.v += $in.kick;\n"
            "  $st.v += (-w_ * w_ * ($st.x - $in.target) - 2.0f * $p.damping * w_ * $st.v) * h_;\n"
            "  $st.x += $st.v * h_; }\n"
            "$out.value = $st.x; $out.velocity = $st.v;",
            "a damped oscillator pulled to `target`: a kick (an impulse, on the beat) makes it overshoot, rock back and settle - a slosh, a bounce"),
         state=["x", "v"]),
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
    _n("Cube face", "coords", "pixel", [], [("face", F), ("a", F), ("b", F), ("nx", F), ("ny", F), ("nz", F)], [],
       "{ const float ax_ = fabsf(X3), ay_ = fabsf(Y3), az_ = fabsf(Z3);\n"
       "  float m_, pa_, pb_; $out.nx = 0.0f; $out.ny = 0.0f; $out.nz = 0.0f;\n"
       "  if (cube && az_ >= ax_ && az_ >= ay_) { $out.face = Z3 >= 0 ? 4.0f : 5.0f; m_ = az_; pa_ = X3; pb_ = Y3; $out.nz = Z3 >= 0 ? 1.0f : -1.0f; }\n"
       "  else if (cube && ay_ >= ax_)          { $out.face = Y3 >= 0 ? 2.0f : 3.0f; m_ = ay_; pa_ = X3; pb_ = Z3; $out.ny = Y3 >= 0 ? 1.0f : -1.0f; }\n"
       "  else if (cube)                         { $out.face = X3 >= 0 ? 0.0f : 1.0f; m_ = ax_; pa_ = Y3; pb_ = Z3; $out.nx = X3 >= 0 ? 1.0f : -1.0f; }\n"
       "  else                                   { $out.face = 4.0f; m_ = 1.0f; pa_ = X3; pb_ = Y3; $out.nz = 1.0f; }\n"
       "  if (m_ < 1e-3f) m_ = 1e-3f;\n"
       "  $out.a = pa_ / m_ * 0.5f + 0.5f; $out.b = pb_ / m_ * 0.5f + 0.5f; }",
       "which face (0..5: +x -x +y -y top bottom), where on it (a, b 0..1 - tiles per face), and the face's outward normal"),
    _n("Cube ring", "coords", "pixel", [], [("around", F), ("depth", F)], [],
       "{ if (cube) {\n"
       "    $out.around = cfx_atan2f(Y3, X3) * (0.5f / 3.14159265f) + 0.5f;\n"
       "    $out.depth = (Z3 > 0.999f) ? (fmaxf(fabsf(X3), fabsf(Y3)) * 0.5f) : (0.5f + (1.0f - Z3) * 0.25f);\n"
       "  } else { $out.around = u; $out.depth = v; } }",
       "the lid-and-walls ruler: around the cube 0..1, depth 0 at the lid's centre, 0.5 at the rim, 1 at the bottom edge"),
    _n("Ring to uv", "coords", "pixel", [("around", F, 0.0), ("depth", F, 0.5)], [("u", F), ("v", F)], [],
       "gc_ring_uv($in.around, $in.depth, W, H, B, cube, $out.u, $out.v);",
       "Cube ring backwards: a point on the ring as the u, v Previous at reads - step depth to read up the walls"),
    _n("Position to uv", "coords", "pixel", [("x", F, 0.0), ("y", F, 0.0), ("z", F, 1.0)], [("u", F), ("v", F)], [],
       "gc_pos_uv($in.x, $in.y, $in.z, W, H, B, cube, $out.u, $out.v);",
       "any point of the box back to the pixel that shows it (pushed onto the surface) - read a neighbour one step along any 3-D direction"),
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
    _n("Shells", "generate", "pixel", [("slots", F, 0.0), ("x", F, 0.0), ("y", F, 0.0), ("z", F, 0.0), ("speed", F, 1.0), ("width", F, 0.2)],
       [("value", F), ("tag", F), ("age", F)], [],
       "{ const float *E_ = gc_st + (int)$in.slots; float sum_ = 0.0f, best_ = 0.0f, tag_ = 0.0f, age_ = 0.0f;\n"
       "  for (int k_ = 0; k_ < 8; k_++) { const float *e_ = E_ + k_ * 6; if (e_[4] < 0.0f) continue;\n"
       "    const float dx_ = $in.x - e_[0], dy_ = $in.y - e_[1], dz_ = $in.z - e_[2];\n"
       "    const float d_ = sqrtf(dx_ * dx_ + dy_ * dy_ + dz_ * dz_); const float rad_ = e_[4] * $in.speed;\n"
       "    float off_ = fabsf(d_ - rad_); if (off_ >= $in.width) continue;\n"
       "    const float life_ = 1.0f - e_[4] / (e_[5] > 0.0f ? e_[5] : 1.0f); const float v_ = (1.0f - off_ / $in.width) * life_;\n"
       "    sum_ += v_; if (v_ > best_) { best_ = v_; tag_ = e_[3]; age_ = e_[4]; } }\n"
       "  $out.value = sum_ > 1.0f ? 1.0f : sum_; $out.tag = tag_; $out.age = age_; }",
       "spherical shells expanding from each Emitter through 3-D space at `speed`, `width` thick, fading with age: the ripple that crosses every fold correctly"),
    # Reaction-diffusion: real chemistry on a small grid in whatever chart the
    # graph samples it through (a tunnel's log-polar, a face). Once per frame
    # the grid steps; per pixel it is read at u (wrapping), v.
    dict(_n("Reaction diffusion", "generate", "pixel", [("u", F, 0.0), ("v", F, 0.0)], [("v", F), ("u", F)],
            [_p("feed", "float", 0.037), _p("kill", "float", 0.06), _p("steps", "int", 2, 1, 8), _p("seed", "float", 0.02)],
            "{ float *S_ = $st; const int gw_ = 48, gh_ = 24; float *G_ = S_ + 2; float *T_ = G_ + gw_ * gh_ * 2;\n"
            "  if ($first || S_[0] != (float)(SEGENV.call & 0xFFFF)) {\n"
            "    if ($first) { for (int i_ = 0; i_ < gw_ * gh_; i_++) { G_[i_ * 2] = 1.0f; G_[i_ * 2 + 1] = 0.0f; }\n"
            "      for (int i_ = 0; i_ < gw_ * gh_; i_++) if (gc_rnd() < $p.seed) G_[i_ * 2 + 1] = 0.9f; }\n"
            "    for (int k_ = 0; k_ < $p.steps; k_++) gc_gray_scott(G_, gw_, gh_, 0.16f, 0.08f, $p.feed, $p.kill, T_);\n"
            "    S_[0] = (float)(SEGENV.call & 0xFFFF); }\n"
            "  float fu_ = $in.u - floorf($in.u); const int gx_ = (int)(fu_ * gw_) % gw_; int gy_ = (int)(gc_sat($in.v) * gh_); if (gy_ >= gh_) gy_ = gh_ - 1;\n"
            "  $out.u = G_[(gy_ * gw_ + gx_) * 2]; $out.v = G_[(gy_ * gw_ + gx_) * 2 + 1]; }",
            "Gray-Scott chemistry on a 48 x 24 grid, stepped each frame, read at u (wraps), v: tendrils that branch, merge and drip, with history. feed 0.03-0.06, kill 0.055-0.065"),
         state=2 + 48 * 24 * 4),
    # The bifurcation diagram of x -> x^2 + c, kept as a density: each column
    # a c, its orbit run on a little every frame and binned; read per pixel.
    dict(_n("Bifurcation", "generate", "pixel", [("u", F, 0.0), ("v", F, 0.0), ("c_lo", F, -1.6), ("c_hi", F, 0.3),
                                                 ("x_lo", F, -1.5), ("x_hi", F, 1.5)],
            [("density", F)], [_p("trail", "float", 0.9, 0.0, 0.99), _p("orbits", "int", 6, 1, 32)],
            "{ float *S_ = $st; const int NC_ = 64, NX_ = 48; float *X_ = S_ + 1; float *D_ = X_ + NC_;\n"
            "  if ($first || S_[0] != (float)(SEGENV.call & 0xFFFF)) {\n"
            "    if ($first) for (int i_ = 0; i_ < NC_ * NX_; i_++) D_[i_] = 0.0f;\n"
            "    for (int j_ = 0; j_ < NC_; j_++) { const float c_ = $in.c_lo + ($in.c_hi - $in.c_lo) * ((float)j_ + 0.5f) / NC_;\n"
            "      float x_ = X_[j_]; float *col_ = D_ + j_ * NX_; for (int b_ = 0; b_ < NX_; b_++) col_[b_] *= $p.trail;\n"
            "      for (int k_ = 0; k_ < $p.orbits; k_++) { x_ = x_ * x_ + c_; if (x_ > 4.0f || x_ < -4.0f) x_ = 0.0f;\n"
            "        const int b_ = (int)(((x_ - $in.x_lo) / ($in.x_hi - $in.x_lo)) * NX_); if (b_ >= 0 && b_ < NX_) col_[b_] += 1.0f / (float)$p.orbits; }\n"
            "      X_[j_] = x_; }\n"
            "    S_[0] = (float)(SEGENV.call & 0xFFFF); }\n"
            "  int j_ = (int)(gc_sat($in.u) * NC_); if (j_ >= NC_) j_ = NC_ - 1; int b_ = (int)(gc_sat($in.v) * NX_); if (b_ >= NX_) b_ = NX_ - 1;\n"
            "  $out.density = gc_sat(D_[j_ * NX_ + b_]); }",
            "the fig tree: the bifurcation diagram of x -> x^2 + c between c_lo..c_hi (u) and x_lo..x_hi (v), as orbit density with a trail - zoom the windows toward -1.401155 to fly into it"),
         state=1 + 64 + 64 * 48),
    _n("Bitmap", "generate", "pixel", [("u", F, 0.0), ("v", F, 0.0)], [("slot", F), ("on", B)],
       [_p("rows", "text", "0110/1001/1001/0110")],
       "{ const int s_ = gc_bitmap(\"$p.rows\", $in.u, $in.v); $out.on = s_ >= 0; $out.slot = (float)(s_ < 0 ? 0 : s_); }",
       "pixel art: rows of digits separated by '/', '.' transparent, read at u, v - the digit is a colour slot for Colour pick"),
    _n("Hash", "generate", "pixel", [("x", F, 0.0), ("y", F, 0.0), ("seed", F, 0.0)], [("value", F)], [],
       "$out.value = gc_hash($in.x, $in.y, $in.seed);",
       "a random 0..1 that is the same every frame for the same x, y, seed - one per cell or column"),
    _n("Torus knot", "generate", "pixel", [("nx", F, 0.0), ("ny", F, 0.0), ("nz", F, 1.0), ("tube", F, 0.25)],
       [("on", F), ("along", F), ("edge", F), ("Nx", F), ("Ny", F), ("Nz", F)],
       [_p("p", "int", 2, 1, 7), _p("q", "int", 3, 1, 9), _p("R", "float", 0.62), _p("r", "float", 0.3)],
       "{ float al_, ed_, Nx_, Ny_, Nz_; const bool hit_ = gc_knot($in.nx, $in.ny, $in.nz, $p.p, $p.q, $p.R, $p.r, $in.tube, al_, ed_, Nx_, Ny_, Nz_);\n"
       "  $out.on = hit_ ? 1.0f : 0.0f; $out.along = al_; $out.edge = ed_; $out.Nx = Nx_; $out.Ny = Ny_; $out.Nz = Nz_; }",
       "a (p, q) torus knot seen from the cube's centre along a direction: hit or not, where along the knot (0..1), how near the tube's edge (0 centre, 1 rim), and the tube's normal there for lighting"),
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
    _n("Colour pick", "colour", "pixel", [("index", F, 0.0)], [("color", C)],
       [_p("c0", "color", [255, 255, 255]), _p("c1", "color", [255, 0, 0]), _p("c2", "color", [0, 255, 0]), _p("c3", "color", [0, 0, 255])],
       "{ const int i_ = (int)$in.index; $out.color = i_ <= 0 ? RGBW32($p.c0_r, $p.c0_g, $p.c0_b, 0) : i_ == 1 ? RGBW32($p.c1_r, $p.c1_g, $p.c1_b, 0)\n"
       "    : i_ == 2 ? RGBW32($p.c2_r, $p.c2_g, $p.c2_b, 0) : RGBW32($p.c3_r, $p.c3_g, $p.c3_b, 0); }",
       "one of four colours by index (0..3) - a bitmap's palette"),
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
// Any point in the -1..1 box back to the logical pixel that shows it: the
// point is pushed onto the cube's surface (the box's own max-norm) and the
// face mapping of cfx_pos is run backwards. A read one step along gravity,
// or along any 3-D direction, is this and then Field or Previous at.
static inline void gc_pos_uv(float X, float Y, float Z, int W, int H, int B, bool cube, float &u, float &v) {
  if (!cube) { u = gc_sat((X + 1.0f) * 0.5f); v = gc_sat((1.0f - Y) * 0.5f); return; }
  const float m = fmaxf(fabsf(X), fmaxf(fabsf(Y), fabsf(Z)));
  if (m > 1e-6f) { X /= m; Y /= m; Z /= m; }
  int px_, py_;
  const float ax = fabsf(X), ay = fabsf(Y), az = fabsf(Z);
  if (az >= ax && az >= ay) {                                   // top (or the missing bottom)
    px_ = B + gc_q(X, B); py_ = B + gc_q(-Y, B);
  } else if (ay >= ax) {
    px_ = B + gc_q(X, B); py_ = (Y > 0) ? gc_q(Z, B) : 2 * B + gc_q(-Z, B);
  } else {
    py_ = B + gc_q(-Y, B); px_ = (X < 0) ? gc_q(Z, B) : 2 * B + gc_q(-Z, B);
  }
  u = (W > 1) ? (float)px_ / (float)(W - 1) : 0.5f; v = (H > 1) ? (float)py_ / (float)(H - 1) : 0.5f;
}
// A (P, Q) torus knot seen from the centre: does the ray along direction n
// hit the knot's tube, and where. For azimuth u the knot passes P times, at
// t = (u + 2 pi k) / P; each pass is a point in the half-plane of u, and the
// ray hits its tube if it passes within `tube` of it. The nearest hit wins.
static inline bool gc_knot(float nx, float ny, float nz, int P, int Q, float R, float r, float tube,
                           float &along, float &edge, float &Nx, float &Ny, float &Nz) {
  const float sxy = sqrtf(nx * nx + ny * ny);
  const float u = cfx_atan2f(ny, nx);
  float bestL = 1e9f, bestT = 0.0f, bestRho = 0.0f, bestZ = 0.0f, bestD2 = 0.0f;
  const float tube2 = tube * tube;
  for (int k = 0; k < P; k++) {
    const float t = (u + 6.2831853f * (float)k) / (float)P;
    const float v = (float)Q * t;
    const float rho = R + r * cosf(v), zz = r * sinf(v);
    const float ell = rho * sxy + zz * nz;
    if (ell <= 0.0f) continue;
    float d2 = rho * rho + zz * zz - ell * ell; if (d2 < 0.0f) d2 = 0.0f;
    if (d2 < tube2) {
      const float hit = ell - sqrtf(tube2 - d2);
      if (hit > 0.0f && hit < bestL) { bestL = hit; bestT = t; bestRho = rho; bestZ = zz; bestD2 = d2; }
    }
  }
  if (bestL > 1e8f) { along = 0.0f; edge = 1.0f; Nx = Ny = 0.0f; Nz = 1.0f; return false; }
  const float qx = bestL * nx, qy = bestL * ny, qz = bestL * nz;
  const float cu = (sxy > 1e-6f) ? (nx / sxy) : 1.0f, su = (sxy > 1e-6f) ? (ny / sxy) : 0.0f;
  Nx = qx - bestRho * cu; Ny = qy - bestRho * su; Nz = qz - bestZ;
  const float NL = sqrtf(Nx * Nx + Ny * Ny + Nz * Nz); const float iN = (NL > 1e-6f) ? 1.0f / NL : 1.0f;
  Nx *= iN; Ny *= iN; Nz *= iN;
  along = bestT * (1.0f / 6.2831853f); along -= floorf(along);
  edge = sqrtf(bestD2) / tube;
  return true;
}
#if __has_include("cube_fx_imu.h")
  #include "cube_fx_imu.h"
  #define GC_HAS_IMU 1
#endif
// Gray-Scott reaction-diffusion on a small grid, periodic in x (a tunnel's
// azimuth), clamped in y. U and V interleaved; one Euler step per call.
static inline void gc_gray_scott(float *G, int gw, int gh, float Du, float Dv, float F, float k, float *tmp) {
  for (int y = 0; y < gh; y++) for (int x = 0; x < gw; x++) {
    const int i = (y * gw + x) * 2;
    const int xl = (x + gw - 1) % gw, xr = (x + 1) % gw, yu = y > 0 ? y - 1 : y, yd = y < gh - 1 ? y + 1 : y;
    const float u = G[i], v = G[i + 1];
    const float lu = G[(y * gw + xl) * 2] + G[(y * gw + xr) * 2] + G[(yu * gw + x) * 2] + G[(yd * gw + x) * 2] - 4.0f * u;
    const float lv = G[(y * gw + xl) * 2 + 1] + G[(y * gw + xr) * 2 + 1] + G[(yu * gw + x) * 2 + 1] + G[(yd * gw + x) * 2 + 1] - 4.0f * v;
    const float uvv = u * v * v;
    tmp[i]     = u + Du * lu - uvv + F * (1.0f - u);
    tmp[i + 1] = v + Dv * lv + uvv - (F + k) * v;
  }
  for (int i = 0; i < gw * gh * 2; i++) G[i] = tmp[i] < 0.0f ? 0.0f : (tmp[i] > 1.0f ? 1.0f : tmp[i]);
}
// One row of a text bitmap: rows separated by '/', '.' transparent, a digit
// its colour slot. Returns the slot at (u, v) or -1.
static inline int gc_bitmap(const char *bm, float u, float v) {
  int rows = 1; for (const char *p = bm; *p; p++) if (*p == '/') rows++;
  int r = (int)floorf(gc_sat(v) * (float)rows); if (r >= rows) r = rows - 1;
  const char *p = bm; for (int i = 0; i < r; i++) { while (*p && *p != '/') p++; if (*p) p++; }
  int cols = 0; for (const char *q = p; *q && *q != '/'; q++) cols++;
  if (cols == 0) return -1;
  int c = (int)floorf(gc_sat(u) * (float)cols); if (c >= cols) c = cols - 1;
  const char ch = p[c];
  return (ch >= '0' && ch <= '9') ? (ch - '0') : -1;
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
