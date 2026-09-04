// ===========================================================================
// sim_main.cpp - the host side of the simulator
// ===========================================================================
// Owns the one segment, drives the clock, and exposes a tiny C surface to the
// page. The effect list is not maintained here: it is whatever the compiled
// effect sources registered into the bank roster at static-init time, so it
// cannot drift from what the firmware would register.
// ===========================================================================
#include "shim/wled.h"
#include "../usermods/cube_fx/cube_fx_bank.h"

// The same C surface serves two front ends. It was written for a browser and
// turned out to be exactly what a native host wants as well, because ctypes and
// Emscripten's ccall need the same thing: plain C linkage, no structs by value,
// and buffers handed back as pointers rather than copied.
//
//   WASM     browser page, via Emscripten
//   DLL      native app, via ctypes
//
// SIM_API is whichever "do not discard this symbol" the toolchain needs.
#ifdef __EMSCRIPTEN__
  #include <emscripten/emscripten.h>
  #define SIM_API EMSCRIPTEN_KEEPALIVE
#elif defined(_WIN32)
  #define SIM_API __declspec(dllexport)
#else
  #define SIM_API __attribute__((visibility("default")))
#endif

WS2812FX strip;
Segment *_segPtr = nullptr;
int Segment::_vw = 48;
int Segment::_vh = 48;

static Segment  gSeg;
static uint32_t gPixels[192 * 192];

// --- audio the page can steer ------------------------------------------------
static float   gVolume = 0.0f;
static uint8_t gFft[16] = {0};
static uint8_t gPeak = 0;
static float   gMajorPeak = 0.0f, gMagnitude = 0.0f;
static void   *gU[8];
static um_data_t gUm = { gU, 8 };

um_data_t *simAudio() {
  gU[0] = &gVolume;  gU[1] = &gVolume; gU[2] = gFft;
  gU[3] = &gPeak;    gU[4] = &gMajorPeak; gU[5] = &gMagnitude;
  return &gUm;
}

// --- palettes ----------------------------------------------------------------
// A representative subset, as 16-stop gradients. Indices line up with the
// selector in the page, not with WLED's full palette numbering.
const uint8_t simPalettes[SIM_PAL_COUNT][16][3] = {
  { {0,0,0},{40,0,60},{90,0,90},{160,0,60},{220,20,20},{255,90,0},{255,160,0},{255,220,60},
    {255,255,160},{220,255,200},{160,230,255},{80,170,255},{30,90,220},{10,40,150},{4,10,70},{0,0,0} }, // Rainbow-ish
  { {0,0,0},{20,0,0},{60,0,0},{110,4,0},{160,20,0},{200,45,0},{230,80,0},{245,120,0},
    {255,160,10},{255,195,40},{255,225,90},{255,240,150},{255,250,200},{255,255,235},{255,255,255},{255,255,255} }, // Fire
  { {0,0,20},{0,6,45},{0,16,75},{0,30,105},{0,50,130},{0,75,150},{10,105,165},{25,135,175},
    {50,165,185},{85,190,195},{125,210,205},{165,225,215},{200,238,230},{225,245,240},{240,250,248},{255,255,255} }, // Ocean
  { {80,0,120},{130,0,140},{180,0,120},{220,0,80},{240,20,40},{250,60,20},{255,110,10},{255,160,20},
    {240,200,50},{200,225,90},{140,230,140},{80,215,190},{40,180,220},{30,130,220},{50,80,200},{80,0,120} }, // Party
  { {0,0,0},{15,15,15},{35,35,35},{60,60,60},{90,90,90},{120,120,120},{150,150,150},{175,175,175},
    {200,200,200},{220,220,220},{235,235,235},{245,245,245},{252,252,252},{255,255,255},{255,255,255},{255,255,255} }, // Mono
  { {10,0,30},{35,0,70},{70,0,110},{110,0,130},{150,10,120},{190,30,95},{220,60,70},{240,100,55},
    {250,145,50},{255,185,65},{255,215,105},{250,235,160},{235,245,205},{215,250,240},{190,240,255},{160,220,255} }, // Sunset
};

uint32_t simPaletteLookup(uint8_t pal, uint8_t idx, uint8_t bri, bool wrap) {
  // Palette ids are 1-based here, mirroring WLED: id 0 is "Default", which means
  // "use the segment's own colour" and never reaches this function - Segment
  // returns early for it. The page's selector therefore starts at 1.
  const uint8_t p = (uint8_t)((pal ? pal - 1 : 0) % SIM_PAL_COUNT);
  const int hi = idx >> 4;                  // which of the 16 stops
  const uint8_t f = (uint8_t)((idx & 15) * 17);
  // The wrap distinction is not cosmetic: asking for the no-wrap form is what
  // put three hard seams through Soap's colour when the index swept the palette
  // more than once.
  const int nx = wrap ? ((hi + 1) & 15) : (hi < 15 ? hi + 1 : 15);
  uint8_t c[3];
  for (int k = 0; k < 3; k++) {
    const int a = simPalettes[p][hi][k], b = simPalettes[p][nx][k];
    c[k] = (uint8_t)(a + ((b - a) * (int)f) / 255);
  }
  return RGBW32(scale8(c[0], bri), scale8(c[1], bri), scale8(c[2], bri), 0);
}

// Same 16 stops as simPaletteLookup, handed to stock effects as a real
// CRGBPalette16 so both families draw from identical colours.
const CRGBPalette16 &Segment::currentPalette() const {
  static CRGBPalette16 cache;
  static int cachedFor = -1;
  const int p = (palette ? palette - 1 : 0) % SIM_PAL_COUNT;
  if (p != cachedFor) {
    for (int i = 0; i < 16; i++)
      cache.entries[i] = CRGB(simPalettes[p][i][0], simPalettes[p][i][1], simPalettes[p][i][2]);
    cachedFor = p;
  }
  return cache;
}

// --- stock WLED effects, for side-by-side comparison -------------------------
// Extracted verbatim by build.py and pushed onto the same roster the cube
// effects register into, so they appear in the same list and are driven by the
// same clock, parameters and audio. Comparing "ours" against "theirs" is then
// just changing the dropdown, rather than an argument about whether the two
// were even fed the same thing.
// Defined in gen/wled_fx.cpp, which build.py writes: it adds every 2-D effect
// it extracted, with that effect's OWN metadata string. The list lives beside
// the extraction so the two cannot fall out of step, and so nothing has to be
// maintained here when WLED gains or loses an effect.
void simRegisterStock();

static void registerStock() {
  static bool done = false;
  if (done) return;
  done = true;
  simRegisterStock();
}

// --- the C surface the page calls -------------------------------------------
extern "C" {

SIM_API int simEffectCount() { registerStock(); return (int)cfxBankCount(); }

SIM_API const char *simEffectName(int i) {
  static char nm[48];
  if (i < 0 || i >= (int)cfxBankCount()) return "";
  cfxBankName(cfxBankRoster()[i].data, nm, sizeof(nm));
  return nm;
}

// The full metadata string, so the page can label sliders exactly as the web UI
// does rather than guessing what "custom2" means for this effect.
SIM_API const char *simEffectMeta(int i) {
  if (i < 0 || i >= (int)cfxBankCount()) return "";
  return cfxBankRoster()[i].data;
}

SIM_API void simInit(int w, int h) {
  Segment::_vw = w; Segment::_vh = h;
  gSeg.pixels = gPixels;
  gSeg.data = nullptr; gSeg._dataLen = 0;
  gSeg.call = 0; gSeg.step = 0; gSeg.aux0 = 0; gSeg.aux1 = 0;
  _segPtr = &gSeg;
  strip._currentSegment = &gSeg;
  strip.isMatrix = true;
  strip.now = 0;
  memset(gPixels, 0, sizeof(uint32_t) * (size_t)w * h);
}

// Selecting an effect must look like WLED selecting one: the scratch buffer is
// released, so the incoming effect initialises from nothing rather than reading
// the previous effect's leftovers as its own state.
SIM_API void simSelect() {
  if (gSeg.data) { free(gSeg.data); gSeg.data = nullptr; }
  gSeg._dataLen = 0; gSeg.call = 0; gSeg.step = 0; gSeg.aux0 = 0; gSeg.aux1 = 0;
}

SIM_API void simParams(int sx, int ix, int c1, int c2, int c3,
                                    int o1, int o2, int o3, int pal) {
  gSeg.speed = (uint8_t)sx; gSeg.intensity = (uint8_t)ix;
  gSeg.custom1 = (uint8_t)c1; gSeg.custom2 = (uint8_t)c2;
  // Constrained, not truncated - json.cpp:306 does constrain(c3, 0, 31) before
  // storing, so a request for 210 reaches an effect as 31 rather than as 210&31.
  gSeg.custom3 = (uint8_t)(c3 < 0 ? 0 : (c3 > 31 ? 31 : c3));
  gSeg.check1 = o1 != 0; gSeg.check2 = o2 != 0; gSeg.check3 = o3 != 0;
  gSeg.palette = (uint8_t)pal;
}

// The FFT bins live here and the page writes into them directly. Handing back a
// pointer to a static beats malloc'ing one in JS: nothing to free, and no extra
// export just to allocate 16 bytes.
// The segment's three colours. Several effects paint with SEGCOLOR(0) - WLED's
// DEFAULT_COLOR is amber, so without a way to set this the front end could only
// ever show those effects in one colour.
SIM_API void simColors(uint32_t c0, uint32_t c1, uint32_t c2) {
  gSeg.colors[0] = c0; gSeg.colors[1] = c1; gSeg.colors[2] = c2;
}

SIM_API uint8_t *simFftPtr() { return gFft; }

SIM_API void simAudioSet(float vol, int peak) {
  gVolume = vol; gPeak = (uint8_t)peak;
}

// One frame. dtMs is passed in rather than read from a wall clock so the page
// can step deterministically - which is the whole point of having this: you can
// hold a frame still and look at it.
SIM_API void simFrame(int idx, int dtMs) {
  if (idx < 0 || idx >= (int)cfxBankCount()) return;
  strip.now += (uint32_t)dtMs;
  cfxBankRoster()[idx].fn();
  gSeg.call++;
}

SIM_API uint32_t *simPixels() { return gPixels; }

} // extern "C"
