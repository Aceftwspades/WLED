#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Mandelbrot - the set, zoomed, on a cube
// ===========================================================================
// STEREOGRAPHIC projection, and it is the only sensible way to put a plane
// figure on a closed surface.
//
// Project each pixel's direction from the bottom pole onto the plane z = 0:
//
//     u = px / (1 + pz),   v = py / (1 + pz)
//
// The lid becomes the origin, the equator a unit circle, and the bottom edges
// run out to a radius of about two and a half. The map is CONFORMAL - it
// preserves angles, so a circle stays a circle and the set's filaments keep
// their shape as they cross a seam. Any of the obvious alternatives shear it:
// unwrapping the net puts four hard creases through the figure, and a polar
// map stretches everything into a fan. The whole appeal of this set is local
// structure, and a projection that does not preserve it is not worth drawing.
//
// The cube has no bottom face, so nothing ever reaches the pole and the
// projection stays bounded. That is luck rather than design, but it means no
// clamping and no special case at infinity.
//
// ---------------------------------------------------------------------------
// THE ZOOM, AND WHY IT BREATHES RATHER THAN DIVING FOREVER
// ---------------------------------------------------------------------------
// An endless inward zoom needs one of two things: arbitrary precision, or a
// cross-fade between two levels an octave apart. Float has about seven digits,
// which is four or five octaves before the set turns to mush, and the
// cross-fade costs a second full iteration of every pixel - on a cube already
// spending forty iterations on each of 1280 of them, that is not available.
//
// So it ping-pongs: in to the depth limit, then back out, with the turnaround
// eased so there is no moment where the motion snaps. Same reason Maelstrom
// eases through zero rather than flipping. The alternative, wrapping the scale,
// puts a visible jump in a figure whose entire job is to be continuous.
//
// ---------------------------------------------------------------------------
// COLOURING: THE ORBIT TRAP, AND ONLY THAT
// ---------------------------------------------------------------------------
// Every point's orbit is followed and the NEAREST it ever passes to either
// axis is recorded. That number, logged, is the colour. It ignores escape time
// completely, which is what makes it look unlike a fractal poster: instead of
// bands parading round the boundary it draws filigree threaded through the
// whole exterior, and the structure carries out into regions escape time
// renders as flat colour.
//
// Three others were built and measured first - smooth escape time, a distance
// estimate, and the argument at escape. Smooth escape is the classic and reads
// cleanly, but at forty-eight pixels its outer regions go flat. The distance
// estimate is the highest-contrast method on paper and the worst here in
// practice: it wants resolution the cube does not have, and lands as a soft
// halo rather than the thin filaments it draws on a screen. The argument gives
// rays but little else. The trap won on looks, and taking the others out also
// removed the orbit DERIVATIVE that only the distance estimate needed - two
// multiplies and an add per iteration per pixel, on the one effect here whose
// arithmetic is heavy enough for that to matter.
// ===========================================================================

struct MdState {
  uint8_t  mode;
  uint32_t tZoom;                   // ping-pong position, Q16
  int8_t   zdir;                    // +1 in, -1 out
  uint32_t tColour;                 // palette scroll, Q8
  uint8_t  surge;                   // beat envelope
  uint8_t  clk[2];
};

static FX_RET mode_mandel() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const size_t m  = cfx_litCount(cols, rows, B, cube);

  // Two Q8 shorts per pixel: the projected plane position, which never changes.
  const size_t need = sizeof(MdState) + 4 * m;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  MdState *s  = (MdState *)SEGENV.data;
  int16_t *pu = (int16_t *)(s + 1);
  int16_t *pv = pu + m;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want;
    s->tZoom = 0; s->zdir = 1; s->tColour = 0; s->surge = 0;
    s->clk[0] = s->clk[1] = 0;

    for (int y = 0; y < rows; y++) {
      for (int x = 0; x < cols; x++) {
        if (cube && (x / B) != 1 && (y / B) != 1) continue;
        const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
        float X, Y, Z;
        cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
        float u, v;
        if (cube) {
          const float L = sqrtf(X * X + Y * Y + Z * Z);
          const float nx = X / L, ny = Y / L, nz = Z / L;
          const float d = 1.0f + nz;
          u = (d > 0.05f) ? nx / d : nx * 20.0f;
          v = (d > 0.05f) ? ny / d : ny * 20.0f;
        } else {
          u = X; v = Y;                              // a panel IS the plane
        }
        // A quarter turn. The set's long axis ran across the net's arms, so
        // the busiest part of the figure sat on the seams and the lid held the
        // quiet interior. Turned, the structure lies along the faces instead.
        pu[i] = (int16_t)(-v * 256.0f);
        pv[i] = (int16_t)( u * 256.0f);
      }
    }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(6, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // --- parameters ---------------------------------------------------------------
  // How fast the trap distance turns into palette. Low is a few broad zones
  // of filigree, high is fine thread. It replaced the algorithm selector when
  // the other three algorithms went.
  const int fil = 8 + ((int)SEGMENT.custom1 * 46) / 255;
  const int iters = 12 + ((int)cfx_c3full(SEGMENT.custom3) * 52) / 255;

  // Ping-pong through the depth. tZoom runs 0..65535 and back.
  {
    const int32_t step = ((6 + (int32_t)SEGMENT.speed / 3)
                          * (int32_t)dt * (100 + (int32_t)s->surge / 3)) / (23 * 100);
    int32_t z = (int32_t)s->tZoom + (int32_t)s->zdir * step;
    if (z >= 65535) { z = 65535; s->zdir = -1; }
    else if (z <= 0) { z = 0; s->zdir = 1; }
    s->tZoom = (uint32_t)z;
  }
  s->tColour += (uint32_t)(((int32_t)SEGMENT.custom2 * 3 * (int32_t)dt) / 23);
  const uint8_t cs = (uint8_t)(s->tColour >> 8);

  // Eased, so the turnaround has no corner in it. Depth spans about four
  // octaves, which is where float stops holding the detail together.
  const float e = ease8InOutCubic((uint8_t)(s->tZoom >> 8)) / 255.0f;
  const float scale = 1.6f * powf(0.062f, e);

  // A point on the boundary that stays interesting all the way down - the
  // classic seahorse-valley target. Anything in the interior gives a black
  // screen after two octaves and anything well outside gives a blank one.
  const float ccx = -0.743643887f, ccy = 0.131825904f;

  const int   gainI = 40 + ((int)SEGMENT.intensity * 180) / 255;
  const uint8_t drive = cfx_drive(vol, 0.5f, 180);

  // --- paint --------------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);

      const float cr = ccx + (float)pu[i] * (1.0f / 256.0f) * scale;
      const float ci = ccy + (float)pv[i] * (1.0f / 256.0f) * scale;

      float zr = 0.0f, zi = 0.0f;
      float trap = 1e9f;
      int n = 0;
      for (; n < iters; n++) {
        const float zr2 = zr * zr, zi2 = zi * zi;
        if (zr2 + zi2 > 64.0f) break;
        const float nzr = zr2 - zi2 + cr;
        zi = 2.0f * zr * zi + ci;
        zr = nzr;
        const float a = zr < 0 ? -zr : zr, b = zi < 0 ? -zi : zi;
        const float t = a < b ? a : b;
        if (t < trap) trap = t;
      }

      uint32_t c = 0;
      if (n < iters) {                                // escaped: the exterior
        const float t = trap < 1e-5f ? 1e-5f : trap;
        const int idx = (int)(-log2f(t) * (float)fil);
        int b = gainI;
        b = (b * (215 + ((int)s->surge * 40) / 255)) >> 8;
        if (b > 255) b = 255;
        if (b > 0) {
          c = SEGMENT.color_from_palette((uint8_t)(idx + cs), false, true, 0);
          c = mq_scale(c, (uint8_t)b);
        }
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_MANDEL[] PROGMEM =
  "Ace 3-D Mandelbrot@Zoom,Brightness,Filigree,Palette cycle,Detail,Beat surge,,Flat mode;;!;2f;sx=110,ix=150,c1=100,c2=30,c3=18,o1=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_33_mandel_reg(&mode_mandel, _data_FX_MODE_MANDEL);
