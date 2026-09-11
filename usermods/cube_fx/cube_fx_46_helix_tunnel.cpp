#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"

// ===========================================================================
// Ace 3-D Helix Tunnel - a loxodromic vortex that becomes an arc tunnel
// ===========================================================================
// A helical vortex coiled round an axis, with a space-filling curve carved
// into it, that morphs into a tunnel of circular arcs converging on a focal
// point where the pattern repeats into the centre forever. The two are not two
// effects crossfaded; they are one conformal chart with one parameter turning
// its spirals into circles, and the axis they share wanders the solid.
//
// ---------------------------------------------------------------------------
// ONE CHART DOES ALL OF IT
// ---------------------------------------------------------------------------
// Every pixel's outward direction is a point on the unit sphere. About the
// tumbled axis it has a polar angle alpha and an azimuth theta, and the chart
// is Mercator's:
//
//     rho = ln tan(alpha / 2)          theta = atan2(y, x)
//
// which is the same thing as stereographic projection followed by log-polar
// coordinates, and it is CONFORMAL - it preserves local angles, which is the
// property the brief keeps asking for and the reason every texture here stays
// in proportion as it wraps the solid. Three things fall out of it for free:
//
//   SCALE INVARIANCE   circles of radius r_n = r_0 k^n about the pole are the
//                      horizontal lines rho = n ln k. A pattern PERIODIC in rho
//                      repeats geometrically into the pole - the infinite zoom
//                      is a tiling, and zooming is a translation.
//   THE HELIX          a straight line of any other slope in (rho, theta) is a
//                      loxodrome, a spiral crossing every ring at the same
//                      angle and winding infinitely tight into each pole. That
//                      is the coiled tube, and the transition to the tunnel of
//                      rings is nothing but that slope going to zero.
//   THE SHEAR          theta += k rho twists the pattern round the axis at a
//                      rate that, per unit of LINEAR radius, is proportional to
//                      1/r - the inner rings are already twisting tighter than
//                      the outer edge before any non-linear term is added. The
//                      Twist slider adds rho|rho| on top, which tightens them
//                      further still, and that is the torque and shear the
//                      brief describes seen from inside a conformal chart.
//
// Both poles are on the solid when the axis tumbles, and the chart treats them
// symmetrically: rho runs to -inf at one and +inf at the other, so the same
// tiling converges on both. The flow pushes rho one way, so one pole is the
// mouth of the vortex and the other its throat.
//
// ---------------------------------------------------------------------------
// THE SPACE-FILLING CURVE IS A LOOKUP, NOT A TRACE
// ---------------------------------------------------------------------------
// A Hilbert curve is carved into each tile of the chart while the helix is
// showing. The curve is never walked: for the cell a pixel lands in, the
// standard xy2d index gives its position along the curve, and the same index
// for its four neighbours says which of them the curve connects to - exactly
// the ones whose index differs by one. So each cell draws the arms of a cross
// that the curve actually uses, and the pixel measures its distance to those.
// Five three-iteration integer loops per pixel, on a curve that would have
// taken 64 segment tests to trace. Order 3, an 8 x 8 tile, is as fine as
// sixteen pixels to a face will resolve.
//
// The tiles repeat in theta and in rho, so the carving is self-similar: the
// same curve, a factor of k smaller, every ring inward, until the pole guard
// fades it out.
//
// ---------------------------------------------------------------------------
// THE MOBIUS ARCS, AND THEIR WIDTH
// ---------------------------------------------------------------------------
// Where the rings are showing, a square grid is drawn in z = 1/w, with w the
// stereographic point. Under that map straight lines become circles through
// w = 0, so two families of grid lines become two orthogonal families of
// circles all passing through the pole - the arc tunnel, converging on the
// focal point and overlapping on the way in.
//
// A constant line width in z is not a constant width on the sphere: the map
// stretches by 1/|w|^2, so lines would be hairlines at one pole and floods at
// the other. |dz / d(alpha)| works out to (1 + |z|^2) / 2, so the width is
// scaled by (1 + |z|^2) and the arcs are the same thickness everywhere the eye
// looks. That derivative is the only place the perspective is computed, and it
// is the honest one.
//
// ---------------------------------------------------------------------------
// THE POLE GUARD IS SIZED IN PIXELS
// ---------------------------------------------------------------------------
// Every one of these patterns has infinite detail at the poles by
// construction, and unbounded detail is this cube's one reliable failure.
// The guard does not fade at a fixed angle: the ring spacing in pixels is
// P sin(alpha) / (radians per pixel), and the fade begins where that drops
// through four pixels and is complete at two. So it follows the Rings slider -
// tighter rings fade further from the pole - and it follows the face size, so
// the 48-pixel simulator panel keeps detail a 16-pixel face cannot.
// ===========================================================================

#define HT_TWOPI   6.28318531f
#define HT_HORDER  2                         // Hilbert order: 2^2 = 4 cells a side
#define HT_HG      (1 << HT_HORDER)

struct HtState {
  uint8_t   mode;
  uint8_t   clk[2];
  uint8_t   surge;
  CfxTumble tumble;
  uint16_t  zoom;                // flow along rho - into the pole
  uint16_t  spin;                // flow round the axis
  uint16_t  kick;                // zoom owed but not yet delivered
  uint16_t  morphClk;            // helix <-> tunnel
  uint16_t  drift;               // palette rotation
};

// Position along an order-n Hilbert curve for cell (x, y) of an n x n tile.
static inline uint16_t ht_hilbert(int n, int x, int y) {
  uint16_t d = 0;
  for (int s = n >> 1; s > 0; s >>= 1) {
    const int rx = (x & s) ? 1 : 0, ry = (y & s) ? 1 : 0;
    d = (uint16_t)(d + s * s * ((3 * rx) ^ ry));
    if (!ry) {
      if (rx) { x = n - 1 - x; y = n - 1 - y; }
      const int t = x; x = y; y = t;
    }
  }
  return d;
}

// Distance, in cell units, from (fx, fy) in [0,1)^2 to the part of the Hilbert
// curve that passes through cell (cx, cy): the centre plus an arm toward each
// neighbour the curve connects to.
static inline float ht_carve(int cx, int cy, float fx, float fy) {
  const int d0 = ht_hilbert(HT_HG, cx, cy);
  const float ex = fx - 0.5f, ey = fy - 0.5f;
  float best = sqrtf(ex * ex + ey * ey);              // the centre itself
  const float aex = ex < 0.0f ? -ex : ex, aey = ey < 0.0f ? -ey : ey;
  // +x
  if (cx + 1 < HT_HG) { const int dn = ht_hilbert(HT_HG, cx + 1, cy);
    if (dn == d0 + 1 || dn + 1 == d0) { if (ex > 0.0f && aey < best) best = aey; } }
  if (cx > 0)         { const int dn = ht_hilbert(HT_HG, cx - 1, cy);
    if (dn == d0 + 1 || dn + 1 == d0) { if (ex < 0.0f && aey < best) best = aey; } }
  if (cy + 1 < HT_HG) { const int dn = ht_hilbert(HT_HG, cx, cy + 1);
    if (dn == d0 + 1 || dn + 1 == d0) { if (ey > 0.0f && aex < best) best = aex; } }
  if (cy > 0)         { const int dn = ht_hilbert(HT_HG, cx, cy - 1);
    if (dn == d0 + 1 || dn + 1 == d0) { if (ey < 0.0f && aex < best) best = aex; } }
  return best;
}

static FX_RET mode_helixtunnel() {
  if (!strip.isMatrix || !SEGMENT.is2D()) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  const int cols = SEG_W, rows = SEG_H;
  if (cols < 8 || rows < 8) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }

  const bool cube = cfx_isCube(cols, rows);
  const int  B    = cube ? (cols / 3) : 1;

  if (!SEGENV.allocateData(sizeof(HtState))) { SEGMENT.fill(SEGCOLOR(0)); FX_DONE; }
  HtState *s = (HtState *)SEGENV.data;

  const uint8_t want = (uint8_t)(cube ? 1 : 2);
  if (SEGENV.call == 0 || s->mode != want) {
    s->mode = want; s->clk[0] = s->clk[1] = 0;
    cfx_tumbleInit(s->tumble);
    s->zoom = 0; s->spin = 0; s->kick = 0; s->morphClk = 0; s->drift = 0; s->surge = 0;
  }

  uint16_t dt = fx_dt8(s->clk);
  if (dt > 60) dt = 60;

  // --- parameters -----------------------------------------------------------
  const int  fill   = (int)SEGMENT.intensity * 2;
  const int  ringI  = (int)SEGMENT.custom1;
  const int  twistI = (int)SEGMENT.custom2;
  const int  dwellI = (int)cfx_c3full(SEGMENT.custom3);    // custom3 is 5-bit
  const bool carve  = SEGMENT.check2;

  // Ring period in rho. k = e^P: at 0.55 each ring is 1.73x the last, at 1.2
  // it is 3.3x. The self-similar zoom is literal - the pattern one period in
  // is the same pattern, a factor of k smaller. The floor is set by the pole
  // guard: below about 0.4 the rings are under four pixels apart EVERYWHERE on
  // a sixteen-pixel face, the guard never opens, and the slider's bottom third
  // measured 80% dark. 0.55 keeps every position on it a picture.
  const float P    = 0.55f + (float)ringI * (0.65f / 255.0f);
  const float invP = 1.0f / P;
  // Carving tiles round the axis: as many as makes their cells square.
  int NT = (int)(HT_TWOPI / ((float)HT_HG * P) + 0.5f);
  if (NT < 1) NT = 1;

  // --- audio ----------------------------------------------------------------
  um_data_t     *um   = cfx_getAudioData();
  const float    vol  = *(float *)um->u_data[0];
  const uint8_t  beat = SEGMENT.check1 ? fx_lowBeat(um) : 0;
  if (beat > s->surge) s->surge = beat;
  { const int f = (int)s->surge - (int)fx_step(32, dt);
    s->surge = (uint8_t)(f < 0 ? 0 : f); }

  // A lurch INTO the pole - a jump along the zoom, owed rather than applied.
  // Delivered whole the tunnel would cut to a new depth and the rush is never
  // seen; a third of the debt a frame puts most of it inside 140 ms.
  if (beat) {
    uint32_t k = (uint32_t)s->kick + (uint32_t)beat;
    if (k > 620u) k = 620u;
    s->kick = (uint16_t)k;
  }
  if (s->kick) {
    uint32_t give = ((uint32_t)s->kick * (uint32_t)dt) / 70u;
    if (!give) give = 1;
    if (give > s->kick) give = s->kick;
    s->zoom = (uint16_t)(s->zoom + give * 30u);
    s->kick = (uint16_t)(s->kick - give);
  }

  // --- clocks ---------------------------------------------------------------
  { const uint32_t r = (uint32_t)(3 + (int)SEGMENT.speed / 2) * (uint32_t)dt / 23u;
    s->zoom     = (uint16_t)(s->zoom + r);
    s->spin     = (uint16_t)(s->spin + (r * 3u) / 5u);
    s->morphClk = (uint16_t)(s->morphClk + (r * 2u) / 9u);
    cfx_tumbleStep(s->tumble, (uint16_t)(r / 6u)); }
  s->drift = (uint16_t)(s->drift + ((uint32_t)dt * (uint32_t)SEGMENT.speed) / 90u);

  float M[3][3];
  cfx_tumbleMatrix(s->tumble, M);

  // --- the morph ------------------------------------------------------------
  // 0 is the helix with the curve carved into it, 1 is the ring tunnel with the
  // arcs. It cycles on its own clock, because the brief is a SEQUENCE; Dwell
  // bends the cycle so it lingers at one end - a power law on a sine, the
  // exponent running 0.4 to 2.5. The linear middle is where the slider is not.
  float morph;
  { const float ph = (float)s->morphClk * (HT_TWOPI / 65536.0f);
    float g = 0.5f + 0.5f * cfx_sinf16(ph);
    const float p = 0.4f + (float)dwellI * (2.1f / 255.0f);
    morph = powf(g, p); }
  const float helix = 1.0f - morph;

  // Slope of the loxodrome: stripes per turn, at full helix. Goes to zero with
  // the morph, which is the whole transition.
  const float slope = 2.0f * helix;
  // Shear: theta += sh1 rho + sh2 rho|rho|. Both scale with the helix so the
  // tunnel's rings come out as true circles.
  const float sh1 = (float)twistI * (1.00f / 255.0f) * helix;
  const float sh2 = (float)twistI * (0.30f / 255.0f) * helix;

  const float zoomF = (float)s->zoom * (P * 4.0f / 65536.0f);   // 4 rings per clock turn
  const float spinF = (float)s->spin * (HT_TWOPI / 65536.0f);

  // Pole guard, in pixels. Radians per pixel on a face of B pixels is about
  // (pi/2)/B; the ring spacing in pixels is P sin(alpha) / that. Fade between
  // two pixels and one.
  const float radPx = 1.5707963f / (float)(cube ? B : (cols < rows ? cols : rows) / 2);
  const float guardK = P / radPx;                    // ring spacing = guardK * sin(alpha)

  const uint8_t hueOff = (uint8_t)(s->drift >> 8);
  const uint8_t drive  = cfx_drive(vol, 0.5f, 200);

  // --- paint ----------------------------------------------------------------
  CFX_NET_PREP();
  for (int y = 0; y < rows; y++) {
    CFX_NET_ROW(y);
    for (int x = 0; x < cols; x++) {
      CFX_NET_SKIP(x);

      float X, Y, Z; cfx_pos(x, y, cols, rows, B, cube, X, Y, Z);
      if (!cube) Z = 1.0f - (X * X + Y * Y) * 0.5f;      // a panel becomes a dome
      const float PL = sqrtf(X * X + Y * Y + Z * Z);
      const float iL = (PL > 1e-6f) ? (1.0f / PL) : 1.0f;

      float nx = X * iL, ny = Y * iL, nz = Z * iL;
      { const float ax = M[0][0]*nx + M[0][1]*ny + M[0][2]*nz;
        const float ay = M[1][0]*nx + M[1][1]*ny + M[1][2]*nz;
        const float az = M[2][0]*nx + M[2][1]*ny + M[2][2]*nz;
        nx = ax; ny = ay; nz = az; }

      // --- the chart ---------------------------------------------------------
      const float sxy2 = nx * nx + ny * ny;
      const float sxy  = sqrtf(sxy2);

      // Guard first: near either pole the pattern is finer than a pixel and
      // there is nothing to compute.
      // Fade begins at four pixels a ring and is complete at two. It started
      // at two and one, and the rings just outside that measured as a wash: at
      // two pixels a period a band is one pixel and its gap is one pixel, and
      // that is not rings, that is a grey with the palette's hue.
      float guard = (guardK * sxy - 2.0f) * 0.5f;      // 0 at two px, 1 at four
      if (guard <= 0.0f) { SEGMENT.setPixelColorXY(x, y, 0); continue; }
      if (guard > 1.0f) guard = 1.0f;
      guard *= guard;

      // rho = ln tan(alpha/2) = ln( sin(alpha) / (1 + cos(alpha)) )
      float onz = 1.0f + nz;
      if (onz < 1e-4f) onz = 1e-4f;
      const float rho   = logf(sxy / onz);
      const float theta = cfx_atan2f(ny, nx);

      // --- the flow, the torque, the shear -----------------------------------
      const float r1 = rho - zoomF;
      const float ar = r1 < 0.0f ? -r1 : r1;
      const float t1 = theta + spinF + sh1 * r1 + sh2 * r1 * ar;

      // --- stripes: helix at slope, rings at zero ----------------------------
      const float a  = r1 * invP + slope * t1 * (1.0f / HT_TWOPI);
      const float fa = a - floorf(a);
      // A band under half the period wide, BLACK between. Black is a component
      // here: the tunnel reads as depth because the rings are separated by
      // nothing, and a triangle wave - the first version - lit the whole
      // period and measured as a wash at mean 89.
      const float off = ((fa < 0.5f) ? (0.5f - fa) : (fa - 0.5f)) * 2.0f;  // 0 mid, 1 edge
      float band = (0.52f - off) * (1.0f / 0.30f);
      if (band < 0.0f) band = 0.0f; else if (band > 1.0f) band = 1.0f;
      band = band * band * (3.0f - 2.0f * band);
      // The stripes are the body of the tunnel; in the helix phase the carving
      // is the surface and the stripes sit behind it.
      float bodyL = (0.40f + 0.32f * morph) * band;

      // --- the carving -------------------------------------------------------
      // The tile is HT_HG rings tall and NT tiles go round, so a cell is about
      // one ring period on each side - the chart is conformal, so square in
      // (rho, theta) is square on the solid. A tile one ring tall, the first
      // version, had cells sixteen pixels wide and under two tall, and the
      // curve came out as a row of dots. The v coordinate is the SLOPED one, so
      // the grid leans with the helix and the carving follows the coil.
      float carveL = 0.0f;
      if (carve && helix > 0.02f) {
        float tu = t1 * (1.0f / HT_TWOPI) * (float)NT; tu -= floorf(tu);
        float tv = a * (1.0f / (float)HT_HG);          tv -= floorf(tv);
        const float gu = tu * (float)HT_HG, gv = tv * (float)HT_HG;
        const int   cx = (int)gu, cy = (int)gv;
        const float dd = ht_carve(cx, cy, gu - (float)cx, gv - (float)cy);
        // Width in cells, widened as the guard closes so the line does not
        // shatter into dots before it fades.
        const float lw = 0.24f + 0.10f * (1.0f - guard);
        if (dd < lw) {
          float g = 1.0f - dd / lw;
          carveL = g * g * helix;
        }
      }

      // --- the arcs ----------------------------------------------------------
      float arcL = 0.0f;
      if (morph > 0.02f) {
        // w = e^rho (cos t, sin t) is the stereographic point; z = 1/w. The
        // arcs SPIN with the rest but do not zoom, and that is not an
        // oversight. A square grid in z is not scale-invariant - scaled by
        // e^zoom it is a different, denser grid, and over one zoom cycle the
        // factor reaches e^4P, fifteen at the default. The first version zoomed
        // them and the arcs crowded into speckle across the whole solid within
        // seconds. The rings carry the zoom; they are the family r_n = r_0 k^n
        // that the brief attributes it to. The arcs are the Mobius image of a
        // fixed grid, and they hold still.
        const float ez = expf(-rho);                    // |z|
        const float ta = theta + spinF + sh1 * rho + sh2 * rho * (rho < 0.0f ? -rho : rho);
        const float zx = ez * cfx_cosf16(ta), zy = -ez * cfx_sinf16(ta);
        const float GZ = 0.7f;
        float gx = zx * GZ; gx -= floorf(gx); if (gx > 0.5f) gx = 1.0f - gx;
        float gy = zy * GZ; gy -= floorf(gy); if (gy > 0.5f) gy = 1.0f - gy;
        const float gm = (gx < gy) ? gx : gy;           // distance to a grid line, in z
        // Uniform on the sphere: |dz/d(alpha)| = (1 + |z|^2) / 2 - see header.
        const float lw = 0.11f * (1.0f + ez * ez) * GZ;
        if (gm < lw) {
          float g = 1.0f - gm / lw;
          arcL = g * g * morph;
        }
      }

      // --- compose ------------------------------------------------------------
      // The brightest layer wins, rather than the layers summing. Summed, the
      // arcs and the carving filled the black between the rings and the whole
      // surface lit - measured 17% dark against a target of a third to a half.
      // With max, a pixel is black unless SOMETHING is drawn there, which is
      // what a tunnel with gaps in it means.
      const float carveB = carveL * 0.95f, arcB = arcL * 0.95f;
      float lumF = bodyL;
      if (carveB > lumF) lumF = carveB;
      if (arcB   > lumF) lumF = arcB;
      lumF *= guard;
      int lum = (int)((float)fill * lumF);
      if (lum < 0) lum = 0; else if (lum > 255) lum = 255;

      // Hue: one colour per ring so the self-similarity is visible as a
      // repeating sequence into the pole; the carving and the arcs sit a
      // third of the wheel away so they read as drawn ON the surface.
      uint8_t idx = (uint8_t)(hueOff + (int)floorf(a) * 23);
      if (carveB > bodyL && carveB >= arcB)  idx = (uint8_t)(idx + 85);
      else if (arcB > bodyL)                 idx = (uint8_t)(idx + 170);

      uint32_t c = 0;
      if (lum) {
        c = SEGMENT.color_from_palette(idx, false, true, 0);
        c = mq_scale(c, (uint8_t)lum);
      }
      SEGMENT.setPixelColorXY(x, y, mq_scale(c, drive));
    }
  }
  FX_DONE;
}

static const char _data_FX_MODE_HELIXTUNNEL[] PROGMEM =
  "Ace 3-D Helix Tunnel@Speed,Fill,Rings,Twist,Dwell,Beat surge,Carve,Flat mode;;!;2f;sx=100,ix=128,c1=110,c2=128,c3=16,o1=1,o2=1,pal=11";


// ---------------------------------------------------------------------------
// Registration - joins the effect bank, which decides whether this effect
// claims one of the device's limited effect slots. See cube_fx_bank.h.
// ---------------------------------------------------------------------------
static CfxBankReg cube_fx_46_helixtunnel_reg(&mode_helixtunnel, _data_FX_MODE_HELIXTUNNEL);
