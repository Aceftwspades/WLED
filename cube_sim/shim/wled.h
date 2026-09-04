#pragma once
// ===========================================================================
// wled.h - host stand-in, so the REAL effect sources compile unmodified
// ===========================================================================
// The point of the simulator is that it runs the same code the cube runs. Not
// a port, not a re-implementation - the actual .cpp files, built against this
// header instead of the firmware's.
//
// That constraint is what makes the thing worth having. Every Soap bug we
// chased lived in a detail a re-implementation would have quietly normalised:
// a palette lookup asking for NOWRAP, a refresh rate an order of magnitude too
// low, a missing smoothstep on a blend weight. A simulator that "mostly does
// the same thing" would have shown none of them, and would have lied
// confidently while we tuned against it.
//
// So where fidelity is cheap, it is bought outright:
//
//   * The MATH is WLED's own. fastled_slim.cpp compiles straight in, so
//     perlin8, sin8_t, scale8, qadd8 and ease8InOutCubic are bit-for-bit what
//     the device computes. This matters more than it looks - every magnitude
//     we tune (SP_CURL, Density, the whirlpool spin constants) is calibrated
//     against the noise field's actual shape, so a re-rolled Perlin would make
//     every number we pick here wrong on the hardware.
//
//   * allocateData() keeps WLED's REUSE SEMANTICS: an existing buffer is handed
//     back whenever it is already big enough, and `call` is not reset when the
//     request merely shrinks. Effects depend on that (it is what the geometry
//     watchdog exists to work around), so the shim reproduces it rather than
//     the obvious always-fresh-allocation version.
//
// What is NOT faithful, and is marked so at each site: the palette SET is a
// subset, and the segment model is one segment with no transitions, mirroring
// or grouping. Neither affects the questions the simulator is for.
// ===========================================================================

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <utility>                 // std::swap, used by WLED's soapPixels
#include <algorithm>
using std::min;
using std::max;
#include "pgmspace.h"
#include "../../wled00/src/dependencies/fastled_slim/fastled_slim.h"

typedef uint8_t byte;

// Stock WLED effects bail out through this when the segment is not 2D.
// Falling back to black is close enough for a comparison view.
#define FX_FALLBACK_STATIC { SEGMENT.fill(0); return; }

// Extracted from wled00/colors.cpp by build.py - the real thing, so the
// wrap/no-wrap behaviour that caused Soap's colour seams is reproduced exactly.
uint32_t ColorFromPalette(const CRGBPalette16 &pal, unsigned index,
                          uint8_t brightness = 255, TBlendType blendType = LINEARBLEND);

// --- trig ------------------------------------------------------------------
// Declared here, DEFINED by compiling WLED's own wled_math.cpp into the build.
// These are lookup-and-interpolate, not std::sin wrappers, and their exact
// curve is what every phase and frequency constant in the effects was tuned
// against - so substituting real sine here would quietly shift every one of
// them.
int16_t sin16_t(uint16_t theta);
int16_t cos16_t(uint16_t theta);
uint8_t sin8_t(uint8_t theta);
uint8_t cos8_t(uint8_t theta);
float   sin_approx(float);
float   cos_approx(float);
float   tan_approx(float);
float   atan2_t(float, float);
float   atan_t(float);
float   acos_t(float);
float   asin_t(float);
float   floor_t(float);
float   fmod_t(float, float);

// --- noise -----------------------------------------------------------------
// Declared here, DEFINED by gen/wled_noise.cpp, which build.py lifts verbatim
// out of wled00/util.cpp. Same signatures and same default arguments as
// fcn_declare.h, so the effects are compiling against the firmware's contract.
int32_t  perlin1D_raw(uint32_t x, bool is16bit = false);
int32_t  perlin2D_raw(uint32_t x, uint32_t y, bool is16bit = false);
int32_t  perlin3D_raw(uint32_t x, uint32_t y, uint32_t z, bool is16bit = false);
uint16_t perlin16(uint32_t x);
uint16_t perlin16(uint32_t x, uint32_t y);
uint16_t perlin16(uint32_t x, uint32_t y, uint32_t z);
uint8_t  perlin8(uint16_t x);
uint8_t  perlin8(uint16_t x, uint16_t y);
uint8_t  perlin8(uint16_t x, uint16_t y, uint16_t z);

// --- colour ----------------------------------------------------------------
#define RGBW32(r,g,b,w) (uint32_t)((uint32_t)(w)<<24 | (uint32_t)(r)<<16 | (uint32_t)(g)<<8 | (uint32_t)(b))
#define R(c) (uint8_t)(((c)>>16)&0xFF)
#define G(c) (uint8_t)(((c)>> 8)&0xFF)
#define B(c) (uint8_t)(((c)    )&0xFF)
#define W(c) (uint8_t)(((c)>>24)&0xFF)
#define BLACK 0u

static inline uint32_t color_fade(uint32_t c, uint8_t s, bool = false) {
  return RGBW32(scale8(R(c),s), scale8(G(c),s), scale8(B(c),s), scale8(W(c),s));
}
static inline uint32_t color_add(uint32_t a, uint32_t b, bool = false) {
  return RGBW32(qadd8(R(a),R(b)), qadd8(G(a),G(b)), qadd8(B(a),B(b)), qadd8(W(a),W(b)));
}

// --- randomness ------------------------------------------------------------
// xorshift rather than rand(), so a run is reproducible frame for frame when
// the seed is held - which is what makes "did that change help?" answerable.
static inline uint32_t &_rngState() { static uint32_t s = 0x2545F491u; return s; }
static inline uint32_t hw_random() {
  uint32_t &x = _rngState();
  x ^= x << 13; x ^= x >> 17; x ^= x << 5; return x;
}
static inline uint32_t hw_random(uint32_t lim)              { return lim ? hw_random() % lim : 0; }
static inline uint32_t hw_random(uint32_t lo, uint32_t hi)  { return lo + (hi > lo ? hw_random() % (hi - lo) : 0); }
static inline uint16_t hw_random16()                        { return (uint16_t)(hw_random() >> 8); }
static inline uint16_t hw_random16(uint16_t lim)            { return lim ? (uint16_t)(hw_random16() % lim) : 0; }
static inline uint8_t  hw_random8()                         { return (uint8_t)(hw_random() >> 16); }
static inline uint8_t  hw_random8(uint8_t lim)              { return lim ? (uint8_t)(hw_random8() % lim) : 0; }

// --- audio -----------------------------------------------------------------
// Same shape the audioreactive usermod publishes, so the effects' unpacking
// code is unchanged. The values are driven from the UI.
typedef struct { void **u_data; uint8_t u_size; } um_data_t;
#define USERMOD_ID_AUDIOREACTIVE 1
extern um_data_t *simAudio();
struct UsermodManager {
  static bool getUMData(um_data_t **d, uint8_t) { *d = simAudio(); return true; }
};
static inline um_data_t *simulateSound(uint8_t) { return simAudio(); }

// --- palettes --------------------------------------------------------------
// NOT the full WLED set - a representative handful, as 16-stop gradients. The
// BLENDING is faithful (linear, with the wrap/no-wrap distinction that bit us
// in Soap); only the choice of palettes is reduced.
enum { SIM_PAL_COUNT = 6 };
extern const uint8_t simPalettes[SIM_PAL_COUNT][16][3];
uint32_t simPaletteLookup(uint8_t pal, uint8_t idx, uint8_t bri, bool wrap);

class Segment;
extern Segment *_segPtr;

class Segment {
 public:
  static int _vw, _vh;
  static int vWidth()  { return _vw; }
  static int vHeight() { return _vh; }
  int virtualWidth()  const { return _vw; }
  int virtualHeight() const { return _vh; }
  int width()  const { return _vw; }          // stock WLED effects use these
  int height() const { return _vh; }
  bool is2D() const { return true; }

  // Built from the same 16-stop tables color_from_palette() uses, so a stock
  // effect and one of ours put side by side are drawing from the same colours.
  const CRGBPalette16 &currentPalette() const;

  uint8_t  speed = 128, intensity = 128;
  uint8_t  custom1 = 128, custom2 = 128;
  // custom3 is FIVE BITS in the firmware - `uint8_t custom3 : 5` in FX.h, range
  // 0..31, and WLED's own effects treat it that way (`map(custom3, 0, 31, ...)`,
  // and a comment calling it the reduced resolution slider).
  //
  // This shim declared it as a full byte, and that single mismatch made the
  // simulator lie about every effect that scales custom3 as if it were 0..255.
  // Anything tuned here against a value above 31 was tuned against a setting
  // the hardware cannot reach - json.cpp constrains the incoming value to
  // 0..31 before it is stored, so a request for 210 arrives as 31.
  //
  // simParams() applies that same constraint, so the two agree. Matching the
  // firmware means the simulator now fails the same way the cube does, which is
  // the only way it is worth anything.
  uint8_t  custom3 : 5;
  Segment() : custom3(16) {}
  bool     check1 = false, check2 = false, check3 = false;
  uint8_t  palette = 11, soundSim = 0, mode = 0;
  uint32_t colors[3] = { 0xFFAA00u, 0u, 0u };

  uint32_t *pixels = nullptr;          // the frame the renderers read
  uint8_t  *data   = nullptr;          // effect scratch
  uint16_t  _dataLen = 0;
  uint32_t  call = 0, step = 0;
  uint16_t  aux0 = 0, aux1 = 0;

  void markForReset() { call = 0; }

  // WLED's semantics, deliberately: reuse a buffer that is already big enough,
  // and do NOT reset `call` when the requirement shrinks. Effects are written
  // around this, so getting it "cleaner" here would hide real bugs.
  bool allocateData(size_t len) {
    if (data && _dataLen >= (uint16_t)len) return true;
    if (data) free(data);
    data = (uint8_t *)calloc(len, 1);
    if (!data) { _dataLen = 0; return false; }
    _dataLen = (uint16_t)len;
    return true;
  }

  void fill(uint32_t c) { for (int i = 0; i < _vw * _vh; i++) pixels[i] = c; }
  void setPixelColorXY(int x, int y, uint32_t c) {
    if (x < 0 || y < 0 || x >= _vw || y >= _vh) return;
    pixels[y * _vw + x] = c;
  }
  // Stock effects hand this a CRGB. WLED's real Segment overloads for it, and
  // CRGB's uint32_t conversion is explicit, so the overload is required rather
  // than optional.
  void setPixelColorXY(int x, int y, const CRGB &c) {
    setPixelColorXY(x, y, RGBW32(c.r, c.g, c.b, 0));
  }
  uint32_t getPixelColorXY(int x, int y) const {
    if (x < 0 || y < 0 || x >= _vw || y >= _vh) return 0;
    return pixels[y * _vw + x];
  }
  void addPixelColorXY(int x, int y, uint32_t c, bool pc = true) {
    setPixelColorXY(x, y, color_add(getPixelColorXY(x, y), c, pc));
  }
  void fadeToBlackBy(uint8_t n) {
    for (int i = 0; i < _vw * _vh; i++) pixels[i] = color_fade(pixels[i], 255 - n);
  }
  void blur(uint8_t n, bool = false) {                 // cheap separable box blur
    if (!n) return;
    const uint8_t keep = 255 - n;
    for (int y = 0; y < _vh; y++)
      for (int x = 1; x < _vw; x++)
        pixels[y*_vw+x] = color_add(color_fade(pixels[y*_vw+x], keep),
                                    color_fade(pixels[y*_vw+x-1], n), true);
    for (int x = 0; x < _vw; x++)
      for (int y = 1; y < _vh; y++)
        pixels[y*_vw+x] = color_add(color_fade(pixels[y*_vw+x], keep),
                                    color_fade(pixels[(y-1)*_vw+x], n), true);
  }
  void blur2D(uint8_t n, bool b = false) { blur(n, b); }

  uint32_t color_from_palette(uint16_t i, bool mapping, bool moving,
                              uint8_t mcol, uint8_t pbri = 255) const {
    if (palette == 0 && mcol < 3) return color_fade(colors[mcol], pbri);
    unsigned idx = i;
    if (mapping) idx = (i * 255) / (_vw * _vh ? _vw * _vh : 1);
    return simPaletteLookup(palette, (uint8_t)idx, pbri, moving);
  }
};

class WS2812FX {
 public:
  Segment *_currentSegment = nullptr;
  uint32_t now = 0;
  bool isMatrix = true;
  Segment &getSegment(int)        { return *_currentSegment; }
  unsigned getSegmentsNum() const { return 1; }
  unsigned getMainSegmentId() const { return 0; }
  uint8_t  getModeCount() const   { return 1; }
  const char *getModeData(unsigned = 0) const { return ""; }
  uint8_t  addEffect(uint8_t, void (*)(), const char *) { return 0; }
};
extern WS2812FX strip;

// Deliberately the SIMULATED clock, not the wall clock. The page advances time
// by an explicit dt each frame, so effects that lean on millis() (the IMU's
// staleness checks, the param-memory timers) stay in step with the ones that
// use strip.now - and a paused frame is genuinely frozen rather than drifting
// while you look at it.
static inline uint32_t millis() { return strip.now; }
static inline uint32_t micros() { return strip.now * 1000u; }

#define SEGMENT      (*strip._currentSegment)
#define SEGENV       (*strip._currentSegment)
#define SEG_W        Segment::vWidth()
#define SEG_H        Segment::vHeight()
#define SEGCOLOR(x)  (SEGMENT.colors[x])
#define SEGPALETTE   (SEGMENT.currentPalette())
#define FRAMETIME    23
#define MIN(a,b)     ((a)<(b)?(a):(b))
#define MAX(a,b)     ((a)>(b)?(a):(b))

// Usermod base + registration, stubbed: the effect files each declare a
// CfxBankReg, and that static registration is exactly the effect list the
// simulator enumerates - so the roster comes for free and cannot disagree with
// what the firmware would register.
class Usermod {
 public:
  virtual ~Usermod() {}
  virtual void setup() {}
  virtual void loop() {}
};
#define REGISTER_USERMOD(x) /* nothing */
