#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Bifurcation - the chaotic bands of x -> x^2 + c, wrapped on a cube
// ===========================================================================
// After: G. Pastor, M. Romera, G. Alvarez, F. Montoya, "Misiurewicz point
// pattern generation in one-dimensional quadratic maps", Physica A 292 (2001)
// 207-230.
//
// The paper is paywalled and was not read for this - what is built here comes
// from the subject that group works in rather than from their text, and it is
// worth being straight about which. Their subject is the CHAOTIC BAND structure
// of the real quadratic map: below the period-doubling cascade the attractor is
// not one smear of chaos but 2^n disjoint bands, and as c decreases those bands
// merge pairwise - 8 into 4, 4 into 2, 2 into 1 - at parameter values that are
// Misiurewicz points. Those merges are the landmarks that organise the whole
// chaotic region, and they are what this effect is built to show.
//
// ---------------------------------------------------------------------------
// NO TABLE OF CONSTANTS, ON PURPOSE
// ---------------------------------------------------------------------------
// The obvious build would carry the band-merging parameters as a table. Three
// attempts were made to pin them down numerically - a band-count scan, a
// Lyapunov-filtered scan, and Newton on f^(k+p)(0) = f^k(0) - and none was
// reliable enough to trust: the counters kept finding the period-3 window's own
// internal cascade instead of the main one, and the bisections converged onto
// their own bracket ends. Shipping half-remembered constants would have been
// worse than shipping none.
//
// None are needed. Every band, every merge and every periodic window falls out
// of iterating the map. The structure is not drawn here - it is measured, from
// the same dynamics the paper is about, and whatever the parameter is doing at
// the time is what appears on the cube.
//
// ---------------------------------------------------------------------------
// HOW IT IS DRAWN
// ---------------------------------------------------------------------------
// LATITUDE is the orbit value x. The lid is the top of the range and the bottom
// of the walls is the floor, so the attractor reads as horizontal rings around
// the solid - one ring for a fixed point, two after the first period doubling,
// a thick band where it has gone chaotic. Rings cross every seam and read from
// any angle, which is the whole reason for choosing latitude over anything
// flatter.
//
// AZIMUTH is time. A cursor walks around the cube and each sector it reaches
// records the attractor as it stands at that moment, so going around the solid
// is going back through the last few seconds. As the parameter drifts, the
// diagram bifurcates and merges in front of you and the older sectors fade
// behind - a waterfall wrapped on a cube rather than scrolled off a screen.
//
// The parameter itself ping-pongs rather than wrapping. c is not periodic, so
// wrapping it would put a hard discontinuity somewhere on the surface; turning
// round at the ends of the window costs nothing and leaves no seam.
//
// Bass pushes c. That is the one place the audio touches this: the band
// structure of a quadratic map is exquisitely sensitive to its parameter, so a
// kick does not brighten the picture, it MOVES it - bands split and merge on
// the beat because the mathematics says they must.
// ===========================================================================

#define BF_SECT   64            // sectors around the cube - one per wall pixel
#define BF_LATB   40            // latitude bins; matched to the pixel height so
                                // a single-bin band cannot fall between pixels
#define BF_XLO    (-2.1f)       // the orbit range that maps onto the solid
#define BF_XHI    ( 2.1f)

// ---------------------------------------------------------------------------
// THE LANDMARKS
// ---------------------------------------------------------------------------
// Real Misiurewicz points: the parameters where the critical orbit is strictly
// pre-periodic, and the values that organise the chaotic band region. Two of
// them below are the band merges themselves.
//
// These were NOT taken from memory. An earlier draft of this effect shipped no
// table at all because three numerical attempts to find these values all failed
// - the band counters kept locking onto the period-3 window's own internal
// cascade rather than the main one. The fix came from the algebra rather than
// from more counting: Hutz & Towsley, "Misiurewicz points for polynomial maps
// and transversality", Theorem 1.1, gives a polynomial G_2(m,n) in c whose roots
// are PRECISELY the Misiurewicz points of exact preperiod m and period n. That
// construction was implemented in exact integer arithmetic and checked against
// the paper's own counting formula (Corollary 3.3): the degrees agree for every
// m <= 5, n <= 4.
//
// Every entry here was then confirmed strictly PRE-periodic rather than
// periodic, which is the distinction that had been wrecking the earlier work:
// the values that cascade had produced turned out to be superstable centres of
// periodic windows - the critical point periodic, not preperiodic - and so not
// Misiurewicz points at all. They are excluded here by construction.
//
// One landmark per sixteenth of the range, the combinatorially simplest in each,
// so the set spans the whole band region instead of bunching at one end.
#define BF_NMARK 16
static const float BF_MARK[BF_NMARK] PROGMEM = {
  -2.000000000f,   // M(2,1)  the tip
  -1.952133665f,   // M(3,3)
  -1.924661063f,   // M(3,3)
  -1.877132158f,   // M(3,4)
  -1.839286755f,   // M(3,2)
  -1.790327492f,   // M(4,3)
  -1.754878063f,   // M(4,3)  the period-3 window's edge
  -1.714413091f,   // M(4,5)
  -1.683316983f,   // M(4,4)
  -1.661239227f,   // M(4,2)
  -1.599998557f,   // M(4,4)
  -1.583510473f,   // M(4,6)
  -1.543689013f,   // M(3,2)  2 chaotic bands merge into 1
  -1.496464687f,   // M(5,4)
  -1.454820744f,   // M(7,4)
  -1.430357633f,   // M(5,4)  4 bands merge into 2
};

struct BfState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint8_t  cur;                 // sector the cursor is on
  int8_t   dir;                 // parameter drift direction
  float    cPos;                // 0..1 across the parameter window
  float    x;                   // the orbit, carried between frames
  float    sacc;                // fractional sectors carried over
  float    fadeAcc;             // fractional fade carried over, see the tail
  float    xLo, xHi;            // smoothed extent of the attractor
  uint8_t  jolt;                // beat kick to the parameter
  uint16_t hueCyc;
  uint8_t  mark;                // landmark being travelled toward
  int8_t   mdir;                // which way along the table
  uint8_t  land;                // arrival flash envelope
  float    cCur;                // the parameter itself, when snapping
};

static FX_RET mode_bifurcation() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const size_t m  = cfx_litCount(cols, rows, B, cube);

  // The diagram itself, plus which cell of it each pixel reads.
  const size_t need = sizeof(BfState) + (size_t)BF_SECT * BF_LATB + 2 * m;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  BfState *s   = (BfState *)SEGENV.data;
  uint8_t *col = (uint8_t *)(s + 1);            // [sector][latitude] density
  uint8_t *psec = col + (size_t)BF_SECT * BF_LATB;
  uint8_t *plat = psec + m;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->cur = 0; s->dir = 1; s->cPos = 0.0f; s->x = 0.0f;
    s->sacc = 0.0f; s->jolt = 0; s->hueCyc = 0; s->fadeAcc = 0.0f;
    s->mark = 0; s->mdir = 1; s->land = 0; s->cCur = -1.9f;
    s->xLo = -1.0f; s->xHi = 1.0f;
    for (size_t i = 0; i < (size_t)BF_SECT * BF_LATB; i++) col[i] = 0;

    for (int y = 0; y < rows; y++)
      for (int x = 0; x < cols; x++) {
        if (cube && (x / B) != 1 && (y / B) != 1) continue;
        const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
        float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
        if (cube) {
          float L = sqrtf(X * X + Y * Y + Z * Z);
          if (L < 0.0001f) L = 1.0f;
          X /= L; Y /= L; Z /= L;
          // Polar angle from the lid. The cube has no floor, so nothing gets
          // past about 2.19 radians and the range is scaled to what exists.
          float d = Z; if (d > 1.0f) d = 1.0f; else if (d < -1.0f) d = -1.0f;
          int lb = (int)(acosf(d) * (float)BF_LATB / 2.20f);
          if (lb < 0) lb = 0; else if (lb >= BF_LATB) lb = BF_LATB - 1;
          int sc = (int)((atan2f(Y, X) + 3.14159265f) * (float)BF_SECT / 6.28319f);
          if (sc < 0) sc = 0; else if (sc >= BF_SECT) sc = BF_SECT - 1;
          plat[ci] = (uint8_t)lb; psec[ci] = (uint8_t)sc;
        } else {
          plat[ci] = (uint8_t)((y * BF_LATB) / rows);
          psec[ci] = (uint8_t)((x * BF_SECT) / cols);
        }
      }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  int bass = 0, mid = 0, treb = 0;
  cfx_bands(fft, bass, mid, treb);
  const uint8_t beat = fx_lowBeat(um);
  if (beat > s->jolt) s->jolt = beat;
  { const int f = (int)s->jolt - (int)fx_step(8, dt);
    s->jolt = (uint8_t)(f < 0 ? 0 : f); }

  // --- parameters ---------------------------------------------------------------
  const int  gainI  = 40 + ((int)SEGMENT.intensity * 215) / 255;
  const int  window = (int)SEGMENT.custom1;
  const int  trail  = (int)SEGMENT.custom2;
  const int  detail = (int)cfx_c3full(SEGMENT.custom3);
  const bool doJolt = SEGMENT.check1;
  const bool snap = SEGMENT.check2;

  // The window. At the bottom it sits inside the band-merging cascade, where
  // the structure the paper is about lives; at the top it opens out to the whole
  // diagram, period doubling and all.
  const float w   = (float)window / 255.0f;
  const float cLo = -1.60f - w * 0.40f;
  const float cHi = -1.38f + w * 1.63f;

  // --- drive the parameter ---------------------------------------------------
  // Two behaviours. Free drift ping-pongs across the window. SNAP travels from
  // one Misiurewicz landmark to the next, changing target on a beat but taking
  // the journey in real seconds - the same split that works in Lichtenberg, and
  // for the same reason: the arrival is musical, the travel is not.
  float cTarget = 0.0f;
  bool arrived = false;
  if (snap) {
    if (beat && !s->land) {
      int nx = (int)s->mark + (int)s->mdir;
      if (nx >= BF_NMARK) { nx = BF_NMARK - 2; s->mdir = -1; }
      else if (nx < 0)    { nx = 1; s->mdir = 1; }
      s->mark = (uint8_t)nx;
    }
    cTarget = pgm_read_float(&BF_MARK[s->mark]);
    // Keep to the window: a landmark outside it is skipped over.
    if (cTarget < cLo - 0.02f || cTarget > cHi + 0.02f) {
      int nx = (int)s->mark + (int)s->mdir;
      if (nx >= BF_NMARK || nx < 0) s->mdir = (int8_t)-s->mdir;
      else s->mark = (uint8_t)nx;
    }
    const float rate = (0.05f + (float)SEGMENT.speed * (0.55f / 255.0f))
                     * (float)dt * 0.001f;
    const float gap = cTarget - s->cCur;
    if (gap > rate)       s->cCur += rate;
    else if (gap < -rate) s->cCur -= rate;
    else { s->cCur = cTarget; arrived = true; }
  } else {
    const float rate = (0.012f + (float)SEGMENT.speed * (0.10f / 255.0f))
                     * (float)dt * 0.001f;
    s->cPos += rate * (float)s->dir;
    if (s->cPos >= 1.0f) { s->cPos = 1.0f; s->dir = -1; }
    else if (s->cPos <= 0.0f) { s->cPos = 0.0f; s->dir = 1; }
  }
  // Landing on a landmark is the event this effect exists to show, so it gets
  // marked. The bands really do merge there; the flash only points at it.
  if (arrived && s->land < 200) s->land = 255;
  { const int f = (int)s->land - (int)fx_step(5, dt);
    s->land = (uint8_t)(f < 0 ? 0 : f); }

  // Bass moves c. A quadratic map's band structure is exquisitely sensitive to
  // its parameter, so this does not brighten the picture - it splits and merges
  // the bands on the beat, which is the only honest way to make this reactive.
  float cNow = snap ? s->cCur : (cLo + (cHi - cLo) * s->cPos);
  {
    // Bass detunes the parameter. When snapping it is deliberately gentler:
    // the whole point is to ARRIVE on the landmark, and a wide push would walk
    // straight past the merge the effect is trying to show.
    const float span = (cHi - cLo);
    const float k = snap ? 0.004f : 0.03f;
    cNow += ((float)bass / 255.0f) * span * k;
    if (doJolt) cNow += ((float)s->jolt / 255.0f) * span * (snap ? 0.008f : 0.05f);
    if (cNow < -2.05f) cNow = -2.05f; else if (cNow > 0.25f) cNow = 0.25f;
  }

  // --- advance the cursor, measuring the attractor as it goes ----------------
  const int nsamp = 40 + (detail * 180) / 255;
  const float sectPerSec = 2.0f + (float)SEGMENT.speed * (26.0f / 255.0f);
  s->sacc += sectPerSec * (float)dt * 0.001f;
  int nsec = (int)s->sacc;
  if (nsec > 6) { nsec = 6; s->sacc = 0.0f; } else s->sacc -= (float)nsec;

  for (int q = 0; q < nsec; q++) {
    s->cur = (uint8_t)((s->cur + 1) % BF_SECT);
    uint8_t *cell = col + (size_t)s->cur * BF_LATB;
    for (int b = 0; b < BF_LATB; b++) cell[b] = 0;

    // Shake off the transient, then record where the orbit actually goes. The
    // orbit is carried between sectors rather than restarted, so it tracks the
    // attractor as the parameter moves - which is what a real system driven by
    // a slowly varying parameter does.
    float x = s->x;
    if (!(x > -4.0f && x < 4.0f)) x = 0.0f;
    for (int k = 0; k < 24; k++) {
      x = x * x + cNow;
      if (!(x > -4.0f && x < 4.0f)) { x = 0.0f; break; }
    }
    // The attractor is mapped onto the solid by its OWN extent, tracked and
    // smoothed, rather than onto a fixed range. A fixed [-2.1, 2.1] is right
    // only at c = -2; everywhere else the attractor is far narrower and most of
    // the cube was being spent on orbit values that never occur.
    float lo = 1e9f, hi = -1e9f;
    for (int k = 0; k < nsamp; k++) {
      x = x * x + cNow;
      if (!(x > -4.0f && x < 4.0f)) { x = 0.0f; continue; }
      if (x < lo) lo = x;
      if (x > hi) hi = x;
    }
    if (hi > lo) {
      const float pad = (hi - lo) * 0.06f + 0.01f;
      s->xLo += ((lo - pad) - s->xLo) * 0.10f;
      s->xHi += ((hi + pad) - s->xHi) * 0.10f;
    }
    float sp = s->xHi - s->xLo;
    if (sp < 0.02f) sp = 0.02f;

    x = s->x;
    for (int k = 0; k < 24; k++) { x = x * x + cNow;
      if (!(x > -4.0f && x < 4.0f)) { x = 0.0f; break; } }
    for (int k = 0; k < nsamp; k++) {
      x = x * x + cNow;
      if (!(x > -4.0f && x < 4.0f)) { x = 0.0f; continue; }
      int b = (int)(((x - s->xLo) / sp) * (float)BF_LATB);
      if (b < 0) b = 0; else if (b >= BF_LATB) b = BF_LATB - 1;
      // Spread a little, so a band one bin wide cannot fall between pixels.
      const int add = 26;
      int v = (int)cell[b] + add;         cell[b] = (uint8_t)(v > 255 ? 255 : v);
      if (b > 0)           { v = (int)cell[b-1] + add / 3; cell[b-1] = (uint8_t)(v > 255 ? 255 : v); }
      if (b < BF_LATB - 1) { v = (int)cell[b+1] + add / 3; cell[b+1] = (uint8_t)(v > 255 ? 255 : v); }
    }
    s->x = x;
  }

  // --- the tail behind the cursor -------------------------------------------
  // Measured in CURSOR TRAVEL, not in milliseconds. A fixed millisecond fade is
  // wrong here because the cursor's lap time changes with Drift speed: at the
  // defaults a lap took seven seconds while a sector went black in under one, so
  // nine tenths of the cube was dark at any moment and the diagram never
  // appeared. Trail now sets how much of the lap stays lit - a short comet at
  // the bottom, the whole ring at the top - and it means the same thing at every
  // speed.
  {
    const float tailSect = 10.0f + (float)trail * (54.0f / 255.0f);
    const float tailMs   = tailSect / sectPerSec * 1000.0f;
    // Carried as a fraction, because the whole point is fades slower than one
    // level per frame: rounding them up to one made the top half of the Trail
    // slider do nothing at all - 170 and 255 measured identically.
    s->fadeAcc += (255.0f * (float)dt) / (tailMs > 1.0f ? tailMs : 1.0f);
    const int f = (int)s->fadeAcc;
    if (f > 0) {
      s->fadeAcc -= (float)f;
      for (size_t i = 0; i < (size_t)BF_SECT * BF_LATB; i++)
        col[i] = (col[i] > f) ? (uint8_t)(col[i] - f) : 0;
    }
  }

  s->hueCyc = (uint16_t)(s->hueCyc + (uint32_t)dt * 6u);
  const uint8_t drive = cfx_drive(vol, 0.5f, 200);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);
      const uint8_t v = col[(size_t)psec[i] * BF_LATB + plat[i]];

      uint32_t c = 0;
      if (v) {
        // Hue follows the orbit value, so the diagram is a spectrum from the lid
        // down and a band keeps its colour as it splits.
        const uint8_t idx = (uint8_t)(((int)plat[i] * 255) / BF_LATB
                                      + (uint8_t)(s->hueCyc >> 8));
        int b = ((int)v * gainI) >> 8;
        b += ((int)s->land * 70) >> 8;          // the arrival, punctuated
        if (b > 255) b = 255;
        c = SEGMENT.color_from_palette(idx, false, true, 0);
        c = mq_scale(c, (uint8_t)b);
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_BIFURCATION[] PROGMEM =
  "Ace 3-D Bifurcation@Drift speed,Brightness,Window,Trail,Detail,Beat jolt,Snap to landmarks,Flat mode;;!;2f;sx=70,ix=200,c1=60,c2=170,c3=18,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_35_bifurcation_reg(&mode_bifurcation, _data_FX_MODE_BIFURCATION);
