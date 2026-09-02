#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// 26. ACE 3-D SOAP
// ===========================================================================
// Wide swaths of colour sliding over the whole cube, folding into each other
// like oil on water. A port of WLED's Soap, and deliberately a close one: the
// first attempt reinvented too much and lost the look entirely.
//
// ---------------------------------------------------------------------------
// WHAT ACTUALLY MAKES SOAP LOOK LIKE SOAP
// ---------------------------------------------------------------------------
// Reading the original rather than remembering it, four things carry the look,
// and all four matter:
//
//   1. COLOUR LIVES IN A BUFFER AND IS ONLY EVER MOVED - never recomputed from
//      position and time. Transported colour remembers where it has been, so it
//      stretches and folds; recomputed colour always reads as a pattern playing.
//
//   2. THE DISPLACEMENT IS LARGE AND COHERENT. The original drags a whole row
//      by up to twenty pixels at once, and the row beside it by nearly the same
//      amount, because the amount comes from a very low frequency noise field.
//      Big neighbouring regions therefore move together. THIS is what makes the
//      swaths wide - not the palette, and not the detail in the noise.
//
//   3. THE SAMPLING IS SUB-PIXEL. Colour is read between pixels and blended, so
//      motion is continuous instead of a grid of jumps. Nearest-pixel sampling
//      of a colour field re-quantises it every frame and grinds smooth
//      gradients into mush within seconds.
//
//   4. FRESH COLOUR KEEPS ARRIVING, AND FAR FASTER THAN IT LOOKS. In the flat
//      original it enters wherever a shift reads past the edge of the panel, and
//      those pixels are REPLACED outright, not blended - about a quarter of the
//      panel every frame at default Density. A cube surface is closed, with no
//      edge for colour to enter through, so here every pixel crossfades toward a
//      palette colour drawn from a slowly morphing noise field instead. The rate
//      has to be comparable, though: transport plus interpolation is a mixer,
//      and anything that stirs will go uniform unless fresh pigment arrives as
//      fast as the stirring blends it away.
//
// ---------------------------------------------------------------------------
// WHY THE FIRST ATTEMPT LOOKED WRONG
// ---------------------------------------------------------------------------
// Worth recording, because it violated three of those four. Displacement was
// about ONE pixel per frame rather than many, so nothing ever gathered into a
// swath. Sampling was nearest-pixel through a lookup table, so the field ground
// itself down. Several percent of cells were hard-overwritten with fresh noise
// every frame, shredding what structure survived. And the stored palette index
// was multiplied before lookup, wrapping the palette several times over and
// turning what should have been broad areas into fine rainbow banding.
//
// ---------------------------------------------------------------------------
// FLOW IN 3D, SO THE FOLDS DO NOT EXIST
// ---------------------------------------------------------------------------
// Shearing rows and columns is meaningless on a folded net - a row crosses
// three faces at two right angles. So the displacement here is a 3D vector
// field sampled at each pixel's position in space. Being a smooth function of
// 3D position it agrees across every fold for free: a swath slides off the lid
// and continues down a wall, because in the space the flow lives in there is no
// wall, only the surface of a cube.
//
// Reading colour back from an arbitrary surface point needs a reverse lookup,
// built once at start-up: every pixel is filed by which face it sits on (its
// dominant axis) and where on that face. A sample that runs off the edge of a
// face is turned back into a 3D point, which then classifies onto the
// neighbour - so a bilinear tap straddling a fold reads the right pixels on
// both sides of it.
//
// Speed, Smoothness and Density keep the meanings they have in the original.
// ===========================================================================

#ifndef SP_GRAD
  #define SP_GRAD 10                // finite-difference step for grad(psi)
#endif
#ifndef SP_CURL
  #define SP_CURL 6                 // gain from that gradient to flow units
#endif

struct SoapState {
  uint8_t  mode;
  uint16_t nx, ny, nz;              // potential-field time coords
  uint16_t ct;                      // colour-source noise time
  uint8_t  splash;                  // beat envelope for the colour refresh
  uint8_t  bassEnv;                 // bass envelope, also drives colour
  uint8_t  clk[2];
};

// Which face a surface point sits on - just the dominant axis. sp_face() also
// normalises, which the curl only needs the normal for, so this is the cheap
// half of it.
static inline int sp_faceOnly(int x, int y, int z) {
  const int ax = x < 0 ? -x : x, ay = y < 0 ? -y : y, az = z < 0 ? -z : z;
  if (az >= ax && az >= ay) return (z >= 0) ? 4 : 5;
  if (ay >= ax)             return (y >= 0) ? 2 : 3;
  return (x >= 0) ? 0 : 1;
}

// Classify a point on (or near) the cube surface: which face, and where on it.
// face 0..5 = +X,-X,+Y,-Y,+Z,-Z; a and b are the two off-axis coordinates
// normalised to -127..127. Used to build the reverse table AND to look up a
// traced-back point, so the two can never disagree about the geometry.
static inline void sp_face(int x, int y, int z, int &face, int &a, int &b) {
  const int ax = x < 0 ? -x : x, ay = y < 0 ? -y : y, az = z < 0 ? -z : z;
  int m;
  if (az >= ax && az >= ay) { face = (z >= 0) ? 4 : 5; m = az; a = x; b = y; }
  else if (ay >= ax)        { face = (y >= 0) ? 2 : 3; m = ay; a = x; b = z; }
  else                      { face = (x >= 0) ? 0 : 1; m = ax; a = y; b = z; }
  if (m < 1) m = 1;
  a = (a * 127) / m;
  b = (b * 127) / m;
}

// The exact inverse: put a face-local (a,b) back into 3D. Feeding it an a or b
// beyond +/-127 gives a point past the edge of that face, which sp_face() then
// drops onto the neighbour - that is how a bilinear tap crosses a fold.
static inline void sp_unface(int face, int a, int b, int &x, int &y, int &z) {
  switch (face) {
    case 0:  x =  127; y = a;    z = b;    break;
    case 1:  x = -127; y = a;    z = b;    break;
    case 2:  x = a;    y =  127; z = b;    break;
    case 3:  x = a;    y = -127; z = b;    break;
    case 4:  x = a;    y = b;    z =  127; break;
    default: x = a;    y = b;    z = -127; break;
  }
}

// Reverse-table read that follows the fold when the cell runs off the face.
static inline uint16_t sp_rev(const uint16_t *rev, int Bq, int face, int ai, int bi) {
  if (ai >= 0 && ai < Bq && bi >= 0 && bi < Bq)
    return rev[((size_t)face * Bq + bi) * Bq + ai];

  const int half = 128 / (Bq > 0 ? Bq : 1);
  const int a = ((ai * 256) / Bq) - 128 + half;
  const int b = ((bi * 256) / Bq) - 128 + half;
  int x, y, z;    sp_unface(face, a, b, x, y, z);
  int f2, a2, b2; sp_face(x, y, z, f2, a2, b2);
  if (f2 == face) return 0xFFFF;                     // never left: no neighbour
  int ai2 = ((a2 + 128) * Bq) >> 8, bi2 = ((b2 + 128) * Bq) >> 8;
  if (ai2 < 0) ai2 = 0; else if (ai2 >= Bq) ai2 = Bq - 1;
  if (bi2 < 0) bi2 = 0; else if (bi2 >= Bq) bi2 = Bq - 1;
  return rev[((size_t)f2 * Bq + bi2) * Bq + ai2];
}

// Symmetric so it cannot drift. The obvious A + (B-A)*f/255 truncates toward
// zero, which biases every interpolation back toward A - harmless once, but this
// runs on its own output tens of times a second and small biases compound.
static inline uint8_t sp_lerp(uint8_t A, uint8_t Bv, uint8_t f) {
  return (uint8_t)(((int)A * (255 - (int)f) + (int)Bv * (int)f + 127) / 255);
}

static FX_RET mode_soap() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const size_t n = (size_t)cols * rows;

  const bool cube = cfx_isCube(cols, rows);
  const int  B   = cube ? (cols / 3) : 1;
  const int  Bq   = cube ? B : 1;
  const size_t lut = cube ? (size_t)6 * Bq * Bq : 0;

  const size_t need = sizeof(SoapState) + 3 * n      // cube coords
                    + 3 * n + 3 * n                  // colour buffer + next
                    + n                              // colour-source noise
                    + lut * sizeof(uint16_t);
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  SoapState *s  = (SoapState *)SEGENV.data;
  int8_t   *cx  = (int8_t *)(s + 1);
  int8_t   *cy  = cx + n;
  int8_t   *cz  = cy + n;
  uint8_t  *pix = (uint8_t *)(cz + n);       // rgb triplets - the transported field
  uint8_t  *nxt = pix + 3 * n;
  uint8_t  *nz3 = nxt + 3 * n;               // smoothed noise: the colour source
  uint16_t *rev = (uint16_t *)(nz3 + n);

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  const bool init = (SEGENV.call == 0 || s->mode != want);
  if (init) {
    cfx_buildCube(cx, cy, cz, nullptr, nullptr, cols, rows, cube);
    s->mode = want; s->splash = 0; s->clk[0] = s->clk[1] = 0;
    s->nx = hw_random16(); s->ny = hw_random16();
    s->nz = hw_random16(); s->ct = hw_random16();

    if (cube) {
      for (size_t k = 0; k < lut; k++) rev[k] = 0xFFFF;
      for (int y = 0; y < rows; y++)
        for (int x = 0; x < cols; x++) {
          if ((x / B) != 1 && (y / B) != 1) continue;     // gap corner
          const size_t i = (size_t)y * cols + x;
          int f, a, b; sp_face(cx[i], cy[i], cz[i], f, a, b);
          int ai = ((a + 128) * Bq) >> 8, bi = ((b + 128) * Bq) >> 8;
          if (ai < 0) ai = 0; else if (ai >= Bq) ai = Bq - 1;
          if (bi < 0) bi = 0; else if (bi >= Bq) bi = Bq - 1;
          rev[((size_t)f * Bq + bi) * Bq + ai] = (uint16_t)i;
        }
    }
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- audio ------------------------------------------------------------------
  um_data_t     *um  = cfx_getAudioData();
  const float    vol = *(float *)um->u_data[0];
  const uint8_t *fft = (uint8_t *)um->u_data[2];
  int bass, mid, treb; cfx_bands(fft, bass, mid, treb);
  const uint8_t beat = SEGMENT.check2 ? fx_lowBeat(um) : 0;
  if (beat > s->splash) s->splash = beat;
  { const int f = (int)s->splash - (int)fx_step(7, dt);
    s->splash = (uint8_t)(f < 0 ? 0 : f); }
  s->bassEnv = fx_env(s->bassEnv, (uint8_t)bass, dt, 260);

  // --- parameters ---------------------------------------------------------------
  // Scale is the size of a swath. Deliberately coarse - perlin8 repeats every
  // 256 units, so spanning the whole cube in well under one period is what lays
  // a single broad gradient across several faces instead of a fine mottle.
  const int sc = 2 + (((int)SEGMENT.custom2 * 12) >> 8);       // 2..14 (~0.5..3.5 periods)

  // Density is the displacement, in PIXELS, that a full-swing flow value drags
  // colour each frame. Large on purpose: this is point 2 above, and the single
  // biggest reason the first attempt had no swaths in it.
  const int pixAmp = 2 + (((int)SEGMENT.custom1 * 12) >> 8);   // 2..14 pixels
  const int amp = cube ? ((254 / (B > 0 ? B : 1)) * pixAmp) : pixAmp;

  int flowSp = 1 + (((int)SEGMENT.speed * 14) >> 8);
  if (SEGMENT.check1) flowSp += (int)s->bassEnv >> 5;          // Bass drive
  const uint16_t adv = (uint16_t)((flowSp * dt) / 23);
  s->nx = (uint16_t)(s->nx + adv);
  s->ny = (uint16_t)(s->ny + (adv * 3) / 4);
  s->nz = (uint16_t)(s->nz + (adv * 5) / 4);
  s->ct = (uint16_t)(s->ct + (adv + 1) / 2);

  const uint8_t smooth = (uint8_t)MIN(250, (int)SEGMENT.intensity);   // Smoothness

  // How hard each pixel crossfades toward fresh palette colour.
  //
  // This is the counterweight to the mixing, and it has to be much heavier than
  // it looks. The original fully REPLACES every pixel whose source read past the
  // edge of the panel - at default Density that is roughly an eighth of each row
  // per pass and two passes a frame, so about a quarter of the cube is repainted
  // with saturated palette colour every single frame. A 1% bleed, which is what
  // this was, loses that race badly: the field looked right for a few seconds
  // and then stirred itself into uniform grey with nothing arriving to stop it.
  // The audio now spends itself HERE rather than on brightness. Driving the
  // level was a poor use of it - the swing was invisible next to the colour, and
  // it fought the effect for headroom. Pushing pigment in instead is something
  // you can actually see: bass keeps fresh colour arriving, beats throw a
  // slug of it across the whole net at once.
  int refresh = 8 + (((int)SEGMENT.custom3 * 72) >> 8);        // 3%..31% per frame
  if (SEGMENT.check1) refresh += (int)s->bassEnv >> 3;         // Bass drive
  refresh += (int)s->splash >> 2;                              // Beat splash
  if (refresh > 120) refresh = 120;

  // --- the colour source: a slowly morphing noise field -------------------------
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;
      const int u = cube ? (cx[i] + 128) : ((x * 255) / (cols - 1));
      const int v = cube ? (cy[i] + 128) : ((y * 255) / (rows - 1));
      const int w = cube ? (cz[i] + 128) : 0;
      const uint8_t d = perlin8((uint16_t)(((u * sc) >> 2) + s->ct),
                                (uint16_t)((v * sc) >> 2),
                                (uint16_t)(((w * sc) >> 2) + 700));
      nz3[i] = init ? d
                    : (uint8_t)(scale8(nz3[i], smooth) + scale8(d, (uint8_t)(255 - smooth)));
    }
  }

  if (init) {                                     // open already marbled
    for (size_t i = 0; i < n; i++) {
      const uint32_t c = SEGMENT.color_from_palette((uint8_t)((uint8_t)(~nz3[i]) * 3), false, true, 0);
      pix[i * 3 + 0] = (uint8_t)((c >> 16) & 0xFF);
      pix[i * 3 + 1] = (uint8_t)((c >>  8) & 0xFF);
      pix[i * 3 + 2] = (uint8_t)( c        & 0xFF);
    }
  }

  // --- transport ------------------------------------------------------------------
  for (int y = 0; y < rows; y++) {
    for (int x = 0; x < cols; x++) {
      const size_t i = (size_t)y * cols + x;
      if (cube && (x / B) != 1 && (y / B) != 1) {
        nxt[i * 3] = nxt[i * 3 + 1] = nxt[i * 3 + 2] = 0; continue;
      }

      uint8_t out[3];

      if (cube) {
        const int u = cx[i] + 128, v = cy[i] + 128, w = cz[i] + 128;
        const uint16_t ka = (uint16_t)((u * sc) >> 2), kb = (uint16_t)((v * sc) >> 2),
                       kc = (uint16_t)((w * sc) >> 2);
        // Curl of a scalar potential, which is what actually swirls.
        //
        // Three independent noise channels give a GENERAL vector field: it has
        // sources and sinks, so colour pools in some places and drains out of
        // others, and the motion reads as blobby drift. The original has no such
        // thing. Shifting every row by an amount that varies with y and then
        // every column by an amount that varies with x composes into ROTATION -
        // that is where its swirl comes from, and it is not something three
        // unrelated channels reproduce.
        //
        // n x grad(psi) is divergence-free by construction, so nothing pools,
        // and the flow circulates around the peaks and troughs of psi. Four
        // samples instead of three buys the whole character.
        const int p0  = (int)perlin8((uint16_t)(ka + s->nx), (uint16_t)(kb + s->ny), (uint16_t)(kc + s->nz));
        const int pdx = (int)perlin8((uint16_t)(ka + s->nx + SP_GRAD), (uint16_t)(kb + s->ny), (uint16_t)(kc + s->nz));
        const int pdy = (int)perlin8((uint16_t)(ka + s->nx), (uint16_t)(kb + s->ny + SP_GRAD), (uint16_t)(kc + s->nz));
        const int pdz = (int)perlin8((uint16_t)(ka + s->nx), (uint16_t)(kb + s->ny), (uint16_t)(kc + s->nz + SP_GRAD));
        const int gx = pdx - p0, gy = pdy - p0, gz = pdz - p0;

        int nrx = 0, nry = 0, nrz = 0;              // outward face normal
        switch (sp_faceOnly(cx[i], cy[i], cz[i])) {
          case 0:  nrx =  1; break;   case 1:  nrx = -1; break;
          case 2:  nry =  1; break;   case 3:  nry = -1; break;
          case 4:  nrz =  1; break;   default: nrz = -1; break;
        }
        int vx = (nry * gz - nrz * gy) * SP_CURL;
        int vy = (nrz * gx - nrx * gz) * SP_CURL;
        int vz = (nrx * gy - nry * gx) * SP_CURL;
        if (vx >  127) vx =  127; else if (vx < -127) vx = -127;
        if (vy >  127) vy =  127; else if (vy < -127) vy = -127;
        if (vz >  127) vz =  127; else if (vz < -127) vz = -127;

        int qx = (int)cx[i] - (vx * amp) / 128;
        int qy = (int)cy[i] - (vy * amp) / 128;
        int qz = (int)cz[i] - (vz * amp) / 128;
        if (qx >  512) qx =  512; else if (qx < -512) qx = -512;
        if (qy >  512) qy =  512; else if (qy < -512) qy = -512;
        if (qz >  512) qz =  512; else if (qz < -512) qz = -512;

        int f, a, b; sp_face(qx, qy, qz, f, a, b);
        const int aq = (a + 128) * Bq, bq = (b + 128) * Bq;
        const int ai = aq >> 8, bi = bq >> 8;
        // Smoothstep the blend weights, exactly as the original does. Straight
        // bilinear averages four neighbours every frame, and since the flow also
        // STRETCHES colour into thin filaments, that average is a mixer: stir
        // long enough and every hue meets every other one, which is why it went
        // uniform - and brighter, because averaging red with green gives yellow.
        // Easing pushes the weights toward 0 and 1 so the resample stays close
        // to a straight copy, keeping the motion smooth without the blur.
        const uint8_t fa = ease8InOutCubic((uint8_t)(aq & 255));
        const uint8_t fb = ease8InOutCubic((uint8_t)(bq & 255));

        uint16_t t00 = sp_rev(rev, Bq, f, ai,     bi);
        uint16_t t10 = sp_rev(rev, Bq, f, ai + 1, bi);
        uint16_t t01 = sp_rev(rev, Bq, f, ai,     bi + 1);
        uint16_t t11 = sp_rev(rev, Bq, f, ai + 1, bi + 1);
        if (t00 == 0xFFFF) t00 = (uint16_t)i;
        if (t10 == 0xFFFF) t10 = t00;
        if (t01 == 0xFFFF) t01 = t00;
        if (t11 == 0xFFFF) t11 = t10;

        for (int c = 0; c < 3; c++) {
          const uint8_t c0 = sp_lerp(pix[(size_t)t00 * 3 + c], pix[(size_t)t10 * 3 + c], fa);
          const uint8_t c1 = sp_lerp(pix[(size_t)t01 * 3 + c], pix[(size_t)t11 * 3 + c], fa);
          out[c] = sp_lerp(c0, c1, fb);
        }
      } else {
        // Flat: the same transport in the plane, which is what Soap always was.
        const int u = (x * 255) / (cols - 1), v = (y * 255) / (rows - 1);
        const uint16_t ka = (uint16_t)((u * sc) >> 2), kb = (uint16_t)((v * sc) >> 2);
        // Same trick in the plane: rotating the gradient of a potential by 90
        // degrees gives a divergence-free field, so it circulates instead of
        // pooling.
        const int p0  = (int)perlin8((uint16_t)(ka + s->nx), (uint16_t)(kb + s->ny));
        const int pdx = (int)perlin8((uint16_t)(ka + s->nx + SP_GRAD), (uint16_t)(kb + s->ny));
        const int pdy = (int)perlin8((uint16_t)(ka + s->nx), (uint16_t)(kb + s->ny + SP_GRAD));
        int vx =  (pdy - p0) * SP_CURL;
        int vy = -(pdx - p0) * SP_CURL;
        if (vx >  127) vx =  127; else if (vx < -127) vx = -127;
        if (vy >  127) vy =  127; else if (vy < -127) vy = -127;

        const int qxQ = (x << 8) - (vx * amp * 2);
        const int qyQ = (y << 8) - (vy * amp * 2);
        int ix = qxQ >> 8, iy = qyQ >> 8;
        const uint8_t fa = ease8InOutCubic((uint8_t)(qxQ & 255));
        const uint8_t fb = ease8InOutCubic((uint8_t)(qyQ & 255));
        const int ix1 = (((ix + 1) % cols) + cols) % cols, iy1 = (((iy + 1) % rows) + rows) % rows;
        ix = ((ix % cols) + cols) % cols;  iy = ((iy % rows) + rows) % rows;

        const size_t t00 = (size_t)iy  * cols + ix,  t10 = (size_t)iy  * cols + ix1;
        const size_t t01 = (size_t)iy1 * cols + ix,  t11 = (size_t)iy1 * cols + ix1;
        for (int c = 0; c < 3; c++) {
          const uint8_t c0 = sp_lerp(pix[t00 * 3 + c], pix[t10 * 3 + c], fa);
          const uint8_t c1 = sp_lerp(pix[t01 * 3 + c], pix[t11 * 3 + c], fa);
          out[c] = sp_lerp(c0, c1, fb);
        }
      }

      // Fresh colour bleeds in everywhere, because a closed surface offers no
      // edge for it to enter through.
      const uint32_t fr = SEGMENT.color_from_palette((uint8_t)((uint8_t)(~nz3[i]) * 3), false, true, 0);
      nxt[i * 3 + 0] = sp_lerp(out[0], (uint8_t)((fr >> 16) & 0xFF), (uint8_t)refresh);
      nxt[i * 3 + 1] = sp_lerp(out[1], (uint8_t)((fr >>  8) & 0xFF), (uint8_t)refresh);
      nxt[i * 3 + 2] = sp_lerp(out[2], (uint8_t)( fr        & 0xFF), (uint8_t)refresh);
    }
  }
  memcpy(pix, nxt, 3 * n);

  // --- render ---------------------------------------------------------------------
  // Volume drives real dynamics rather than a token wobble. A floor of 190 with
  // 0.8 gain reached the 255 ceiling the moment volume passed 81 - which on
  // music is essentially always - so it never reacted at all, it just held the
  // whole effect at full brightness with a 75% floor under it in silence. These
  // numbers never saturate, so loud really is brighter than quiet, and quiet has
  // somewhere dark to go. It matters more here than in most effects: Soap paints
  // every pixel a saturated palette colour, so with nothing pulling the level
  // down the cube is a wall of full-brightness hues.
  const uint8_t drive = cfx_drive(vol, 0.35f, 102);
  CFX_NET_PREP();
  size_t i = 0;
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++, i++) {
      CFX_NET_SKIP(x);
      SEGMENT.setPixelColorXY(x, y,
        mq_scale(RGBW32(pix[i * 3], pix[i * 3 + 1], pix[i * 3 + 2], 0), drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_SOAP[] PROGMEM =
  "Ace 3-D Soap@!,Smoothness,Density,Scale,Splash,Bass drive,Beat splash,Flat mode;;!;2f;sx=110,ix=200,c1=140,c2=90,c3=120,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_26_soap_reg(&mode_soap, _data_FX_MODE_SOAP);
