#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Watershed - drainage, the inverse of a discharge
// ===========================================================================
// Lichtenberg is a DIVERGENT tree: one seed, branches spreading outward, every
// path the same width. This is the convergent mirror of it. Thousands of
// threads gather into fewer and thicker trunks and run to a sink, and the thing
// that carries the image is a variable Lichtenberg does not have - CHANNEL
// WEIGHT. Headwaters are faint; trunks are bright rivers. Same cellular walk on
// the pixel graph, opposite topology, completely different picture.
//
// Where lightning throws light outward, this pulls it inward.
//
// ---------------------------------------------------------------------------
// THE MACHINERY IS ONE LINE
// ---------------------------------------------------------------------------
// A height field over the surface; every pixel points at its steepest-descent
// neighbour; water advects one hop per step:
//
//     w2[down[i]] += w[i]
//
// Convergence is not simulated, it falls out. Two threads that reach the same
// pixel are one thread from there on, and their water adds, so a trunk is
// brighter than its tributaries for the same reason a river is bigger than its
// creeks. Pixels with no lower neighbour are sinks: water pools and glows.
//
// The height field is a sum of sinusoids in 3-D, which matters on a cube - a
// function of the surface POSITION is automatically seamless across every fold,
// where any 2-D noise sampled per face would leave four visible creases.
//
// ---------------------------------------------------------------------------
// EROSION, SO THE NETWORK IS NOT A FIXED PICTURE
// ---------------------------------------------------------------------------
// Flow lowers the ground it runs over and the ground relaxes back toward its
// base shape everywhere else. A busy channel therefore deepens and captures
// more of its neighbours, until a rearrangement upstream steals its supply and
// it heals. That is stream capture, and it is what keeps the network moving
// without anything random being added to it.
//
// ---------------------------------------------------------------------------
// COLOUR AND THE BEAT
// ---------------------------------------------------------------------------
// A beat is a downpour: a storm cell opens over part of the solid and its water
// carries the palette entry of the frequency bin that fired. Where two flows
// meet, the LARGER one keeps its colour rather than the two being averaged -
// averaging distant hues gives grey, and it would also throw away the thing the
// colour is carrying. So a trunk wears the colour of whichever storm is
// dominating it, and you can watch one storm's water take a channel over from
// another as it swells.
//
// Triggering is on the beat; the journey down the network is in real seconds
// and ignores tempo. Same split as Lichtenberg, for the same reason.
// ===========================================================================

#define WS_SINK   0xFFFF        // no lower neighbour: water pools here
#define WS_SLICE  8             // frames to walk the whole surface once
#define WS_HSCALE 64            // fixed-point headroom on the height field
// A candidate has to beat the CURRENT outflow by this much before the channel
// is allowed to move. Two neighbours a hair apart otherwise trade the outflow
// back and forth every frame, and the whole network shimmers - which is what
// the troughs were doing.
#define WS_HYST   44

// Flow accumulation spans orders of magnitude - a trunk carries hundreds of
// times what a headwater does - so brightness has to be LOGARITHMIC or the
// trunks saturate and the whole network above them is invisible. Drawn linearly
// this measured mean 10.5 with 85% of the surface dark; the hierarchy was there
// and could not be seen. Integer log2 with a linear fraction inside the octave.
static inline uint8_t ws_log(uint8_t v) {
  if (!v) return 0;
  int p = 7;
  while (p > 0 && !(v & (1 << p))) p--;
  const int base = 1 << p;
  return (uint8_t)(p * 32 + ((int)(v - base) * 32) / base);
}

struct WsState {
  uint8_t  mode;
  uint8_t  clk[2];
  uint16_t slice;               // where the incremental rebuild has got to
  float    hop;                 // fractional advection steps carried over
  float    drift;               // landscape phase, so the channels migrate
  uint8_t  surge;
  uint16_t hueCyc;
  uint8_t  relief;              // the Relief the field was last built at
};

static FX_RET mode_watershed() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;
  const int  Bq   = cube ? B : 1;
  const size_t lut = cube ? (size_t)6 * Bq * Bq : 0;
  const size_t m  = cfx_litCount(cols, rows, B, cube);

  const size_t need = sizeof(WsState) + lut * sizeof(uint16_t)
                    + 8 * m + 2 * m * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  WsState  *s   = (WsState *)SEGENV.data;
  uint16_t *rev = (uint16_t *)(s + 1);
  int8_t   *px  = (int8_t *)(rev + lut);      // surface direction, x100
  int8_t   *py  = px + m;
  int8_t   *pz  = py + m;
  int8_t   *hb  = pz + m;                     // base landscape
  uint8_t  *w   = (uint8_t *)(hb + m);        // water here now
  uint8_t  *w2  = w + m;                      // and where it is going
  uint8_t  *acc = w2 + m;                     // the channel, lit by use
  uint8_t  *hue = acc + m;                    // whose storm this water is
  int16_t  *h   = (int16_t *)(hue + m);       // working height, eroded
  uint16_t *dn  = (uint16_t *)(h + m);        // steepest-descent neighbour

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  const bool fresh = (SEGENV.call == 0 || s->mode != want);
  if (fresh) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    s->slice = 0; s->hop = 0.0f; s->drift = 0.0f;
    s->surge = 0; s->hueCyc = 0; s->relief = 255;
    for (size_t i = 0; i < m; i++) { w[i] = 0; w2[i] = 0; acc[i] = 0; hue[i] = 0; }

    if (cube) {
      for (size_t k = 0; k < lut; k++) rev[k] = 0xFFFF;
      for (int y = 0; y < rows; y++)
        for (int x = 0; x < cols; x++) {
          if ((x / B) != 1 && (y / B) != 1) continue;
          const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
          float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
          int f, a, b; cfx_face((int)(X * 127.0f), (int)(Y * 127.0f),
                                (int)(Z * 127.0f), f, a, b);
          int ai = ((a + 128) * Bq) >> 8, bi = ((b + 128) * Bq) >> 8;
          if (ai < 0) ai = 0; else if (ai >= Bq) ai = Bq - 1;
          if (bi < 0) bi = 0; else if (bi >= Bq) bi = Bq - 1;
          rev[((size_t)f * Bq + bi) * Bq + ai] = (uint16_t)ci;
        }
    }
    for (int y = 0; y < rows; y++)
      for (int x = 0; x < cols; x++) {
        if (cube && (x / B) != 1 && (y / B) != 1) continue;
        const size_t ci = (size_t)cfx_cidx(x, y, cols, B, cube);
        float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
        if (cube) {
          float L = sqrtf(X * X + Y * Y + Z * Z);
          if (L < 0.0001f) L = 1.0f;
          X /= L; Y /= L; Z /= L;
        }
        px[ci] = (int8_t)(X * 100.0f);
        py[ci] = (int8_t)(Y * 100.0f);
        pz[ci] = (int8_t)(Z * 100.0f);
        hb[ci] = 0; h[ci] = 0; dn[ci] = WS_SINK;
      }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  const uint8_t  beat = fx_lowBeat(um);
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(7, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // --- parameters ---------------------------------------------------------------
  const int  gainI  = 40 + ((int)SEGMENT.intensity * 215) / 255;
  const int  relief = (int)SEGMENT.custom1;
  const int  memory = (int)SEGMENT.custom2;
  const int  rain   = (int)cfx_c3full(SEGMENT.custom3);
  const bool storms = SEGMENT.check1;
  const bool erode  = SEGMENT.check2;

  // --- rebuild a slice of the landscape and its drainage ----------------------
  // A sum of sinusoids in 3-D: seamless across every fold because it is a
  // function of position and knows nothing about faces. Rebuilt a slice at a
  // time so Relief stays live without ever costing a whole frame.
  {
    const bool reset = fresh || (s->relief != (uint8_t)relief);
    if (reset) s->relief = (uint8_t)relief;
    const size_t step = (m + WS_SLICE - 1) / WS_SLICE;
    const size_t from = reset ? 0 : (size_t)s->slice;
    const size_t to   = reset ? m : ((from + step > m) ? m : from + step);
    const float amp = 0.20f + (float)relief * (1.05f / 255.0f);
    const float ph = s->drift;

    for (size_t i = from; i < to; i++) {
      const float X = (float)px[i] * 0.01f, Y = (float)py[i] * 0.01f, Z = (float)pz[i] * 0.01f;
      // GRAVITY FIRST. Without it the landscape was pure noise and the drainage
      // ran off in whatever direction the noise happened to tilt - it came out
      // flowing east to west, with no reason for it to do anything else. Height
      // now rises with world Z, so the lid is the high ground and every wall
      // drains downward from it. That is also what a cube on a table does.
      float v = Z * 3.4f;
      v += sinf(2.1f * X + 1.3f * Y + ph) * 1.00f * amp
         + sinf(1.7f * Y - 2.3f * Z + 1.1f - ph * 0.7f) * 0.85f * amp
         + sinf(2.9f * Z + 1.9f * X + 2.4f + ph * 1.3f) * 0.60f * amp
         + sinf(4.3f * X - 3.7f * Z + 0.7f - ph * 1.9f) * 0.30f * amp
         + sinf(5.1f * Y + 4.7f * X + 1.8f + ph * 2.2f) * 0.18f * amp;
      int hbv = (int)(v * 30.0f);
      if (hbv < -127) hbv = -127; else if (hbv > 127) hbv = 127;
      hb[i] = (int8_t)hbv;
      if (reset) h[i] = (int16_t)(hbv * WS_HSCALE);
    }
    s->slice = (uint16_t)((to >= m) ? 0 : to);
    // The landscape itself creeps. Without this the troughs are fixed for ever
    // and the picture has no variance in it - the channels are wherever the
    // noise put them at boot and they stay there.
    s->drift += (float)dt * 0.000045f;
  }

  // Steepest descent. Recomputed over the whole surface every frame - it is four
  // comparisons per pixel and the network has to follow the erosion, not lag it.
  for (size_t i = 0; i < m; i++) {
    int f, a, b;
    cfx_face((int)px[i], (int)py[i], (int)pz[i], f, a, b);
    int ai = ((a + 128) * Bq) >> 8, bi = ((b + 128) * Bq) >> 8;
    if (ai < 0) ai = 0; else if (ai >= Bq) ai = Bq - 1;
    if (bi < 0) bi = 0; else if (bi >= Bq) bi = Bq - 1;
    uint16_t best = WS_SINK; int bh = h[i];
    const uint16_t cur = dn[i];
    const bool curOk = (cur != WS_SINK && (size_t)cur < m && (int)h[cur] < (int)h[i]);
    if (cube) {
      const uint16_t n0 = cfx_rev(rev, Bq, f, ai - 1, bi);
      const uint16_t n1 = cfx_rev(rev, Bq, f, ai + 1, bi);
      const uint16_t n2 = cfx_rev(rev, Bq, f, ai,     bi - 1);
      const uint16_t n3 = cfx_rev(rev, Bq, f, ai,     bi + 1);
      const uint16_t nn[4] = { n0, n1, n2, n3 };
      for (int q = 0; q < 4; q++) {
        const uint16_t j = nn[q];
        if (j == 0xFFFF || j >= m) continue;
        if ((int)h[j] < bh) { bh = h[j]; best = j; }
      }
    } else {
      const int xx = (int)(i % (size_t)cols), yy = (int)(i / (size_t)cols);
      const int cand[4] = { xx > 0 ? (int)i - 1 : -1,
                            xx < cols - 1 ? (int)i + 1 : -1,
                            yy > 0 ? (int)i - cols : -1,
                            yy < rows - 1 ? (int)i + cols : -1 };
      for (int q = 0; q < 4; q++) {
        const int j = cand[q];
        if (j < 0 || (size_t)j >= m) continue;
        if ((int)h[j] < bh) { bh = h[j]; best = (uint16_t)j; }
      }
    }
    // Move the outflow only on a clear win, or if the old one is no longer
    // downhill at all. This is the flicker fix.
    if (!curOk) dn[i] = best;
    else if (best != WS_SINK && (int)h[best] < (int)h[cur] - WS_HYST) dn[i] = best;
  }

  // --- rain -------------------------------------------------------------------
  // UNIFORM drizzle, on every pixel, every hop. This is the whole reason the
  // hierarchy appears: if each pixel contributes the same drop, then what a
  // channel carries is exactly the number of pixels draining through it, so a
  // trunk is bright because it is large. Scattering a handful of random drops
  // instead - which is what this did first - draws almost nothing: 8 lit pixels
  // a frame measured mean 4.0 with 94% of the surface dark.
  // Smaller drops, more often: the flow reads as water rather than as a
  // sequence of lumps arriving.
  const int drizzle = 1 + (rain * 3) / 255;
  if (storms && beat > 90) {
    int best = 0, bestRise = -1;
    for (int k = 0; k < 16; k++) {
      const int v = (int)fft[k];
      if (v > bestRise) { bestRise = v; best = k; }
    }
    const uint8_t sh = (uint8_t)((best * 255) / 15);
    // A cell over part of the solid, not the whole of it - the drainage only
    // reads as drainage when some of the surface is feeding and some is not.
    const size_t c0 = (size_t)(hw_random16() % (uint16_t)m);
    const int cx = px[c0], cy = py[c0], cz = pz[c0];
    const int lim = 3000 + (int)beat * 12;
    for (size_t i = 0; i < m; i++) {
      const int d = (int)px[i] * cx + (int)py[i] * cy + (int)pz[i] * cz;
      if (d < lim) continue;
      const int nw = (int)w[i] + 40 + (int)beat / 3;
      w[i] = (uint8_t)(nw > 255 ? 255 : nw);
      hue[i] = sh;
    }
  }

  // --- advect -----------------------------------------------------------------
  s->hop += (9.0f + (float)SEGMENT.speed * (52.0f / 255.0f)) * (float)dt * 0.001f;
  int hops = (int)s->hop;
  if (hops > 5) { hops = 5; s->hop = 0.0f; } else s->hop -= (float)hops;

  for (int q = 0; q < hops; q++) {
    for (size_t i = 0; i < m; i++) {
      const int nw = (int)w[i] + drizzle;
      w[i] = (uint8_t)(nw > 255 ? 255 : nw);
      if (!acc[i] && !hue[i]) hue[i] = (uint8_t)(s->hueCyc >> 8);
    }
    for (size_t i = 0; i < m; i++) w2[i] = 0;
    for (size_t i = 0; i < m; i++) {
      const uint8_t v = w[i];
      if (!v) continue;
      const uint16_t d = dn[i];
      const size_t t = (d == WS_SINK) ? i : (size_t)d;
      // The LARGER flow keeps its colour. Averaging two distant palette entries
      // gives grey and throws away the thing the colour is carrying.
      if (t != i && v > w2[t]) hue[t] = hue[i];
      const int nv = (int)w2[t] + (int)((t == i) ? (v * 3) / 4 : v);
      w2[t] = (uint8_t)(nv > 255 ? 255 : nv);
    }
    for (size_t i = 0; i < m; i++) w[i] = w2[i];
  }

  // --- the channel, and the ground it cuts -------------------------------------
  {
    const uint8_t f = fx_fade(1 + ((255 - memory) * 12) / 255, dt);
    for (size_t i = 0; i < m; i++) {
      // Rise toward the flow rather than snapping to it. Taking the max made
      // the channel jump with every arriving parcel of water, which read as the
      // memory flickering rather than as a channel filling.
      int a = (int)acc[i];
      if ((int)w[i] > a) a += ((int)w[i] - a + 1) >> 1;
      else               a -= (int)f;
      acc[i] = (uint8_t)(a < 0 ? 0 : (a > 255 ? 255 : a));
      if (erode) {
        // Flow cuts down; the ground everywhere relaxes back toward its base
        // shape. A busy channel deepens and captures its neighbours until
        // something upstream steals its supply - stream capture, no randomness.
        int hv = (int)h[i];
        hv -= ((int)acc[i] * 3) >> 6;
        hv += (((int)hb[i] * WS_HSCALE) - hv) >> 7;
        if (hv < -32000) hv = -32000; else if (hv > 32000) hv = 32000;
        h[i] = (int16_t)hv;
      }
    }
  }

  s->hueCyc = (uint16_t)(s->hueCyc + (uint32_t)dt * 9u);
  const uint8_t drive = cfx_drive(vol, 0.5f, 195);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);
      const size_t i = (size_t)cfx_cidx(x, y, cols, B, cube);

      uint32_t c = 0;
      const int chan = (int)acc[i], live = (int)w[i];
      if (chan) {
        // The channel is the standing figure; the water moving over it is the
        // event. Both, so a trunk stays visible between storms.
        int b = (int)ws_log((uint8_t)chan) + (int)ws_log((uint8_t)live) / 3;
        if (b > 255) b = 255;
        b = (b * gainI) >> 8;
        if (b > 255) b = 255;
        if (b > 0) {
          // The palette shifts with how much water this pixel carries, so a
          // trunk is not merely brighter than its headwaters but a different
          // colour - the hierarchy reads even where everything is bright.
          const uint8_t idx = (uint8_t)((int)hue[i] + (int)ws_log((uint8_t)chan) / 3);
          c = SEGMENT.color_from_palette(idx, false, true, 0);
          c = mq_scale(c, (uint8_t)b);
        }
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_WATERSHED[] PROGMEM =
  "Ace 3-D Watershed@Flow speed,Brightness,Relief,Channel memory,Rainfall,Storms on beat,Erosion,Flat mode;;!;2f;sx=110,ix=160,c1=150,c2=170,c3=14,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_36_watershed_reg(&mode_watershed, _data_FX_MODE_WATERSHED);
