// ===========================================================================
// sim_main.cpp - the host side of the simulator
// ===========================================================================
// Owns the one segment, drives the clock, and exposes a tiny C surface to the
// page. The effect list is not maintained here: it is whatever the compiled
// effect sources registered into the bank roster at static-init time, so it
// cannot drift from what the firmware would register.
// ===========================================================================
#include <stdio.h>
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
uint8_t Segment::map1D2D = 0;

static Segment  gSeg;
// Room for the largest geometry the studio offers: a 256 x 256 matrix, or a
// cube with 85-pixel faces. simInit() refuses anything larger, and the Python
// side reads the size back rather than assuming it got what it asked for.
static uint32_t gPixels[256 * 256];

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
// wled00/palettes.cpp is compiled in, so the tables below are the firmware's
// own. What is transcribed here is Segment::loadPalette() from FX_fcn.cpp,
// which is the part that decides what a palette ID MEANS - including the
// dynamic ones built from segment colours and the usermod range that a
// registered palette lands in.
//
// It matters that this is a transcription and not an approximation: the whole
// point of the simulator is that a number set here means the same thing on the
// device, and palette IDs are numbers effects carry in their metadata.
std::vector<UsermodPalette> usermodPalettes;
std::vector<CRGBPalette16>  customPalettes;

size_t removeUsermodPalettes(const char *name) {
  const size_t before = usermodPalettes.size();
  for (int i = (int)usermodPalettes.size() - 1; i >= 0; i--)
    if (usermodPalettes[i].name == name) usermodPalettes.erase(usermodPalettes.begin() + i);
  return before - usermodPalettes.size();
}

int simPaletteCount() { return (int)(FIXED_PALETTE_COUNT + usermodPalettes.size()); }

// Transcribed from Segment::loadPalette(), wled00/FX_fcn.cpp.
static void simLoadPalette(CRGBPalette16 &target, uint8_t pal, const uint32_t *colors) {
  const int umCount   = (int)usermodPalettes.size();
  const int custCount = (int)customPalettes.size();
  if (pal >= FIXED_PALETTE_COUNT) {
    if (pal > WLED_CUSTOM_PALETTE_ID_BASE) {
      if ((WLED_USERMOD_PALETTE_ID_BASE - pal) >= umCount) pal = 0;
    } else {
      if ((WLED_CUSTOM_PALETTE_ID_BASE - pal) >= custCount) pal = 0;
    }
  }
  const CRGB prim = CRGB(R(colors[0]), G(colors[0]), B(colors[0]));
  const CRGB sec  = CRGB(R(colors[1]), G(colors[1]), B(colors[1]));
  const CRGB ter  = CRGB(R(colors[2]), G(colors[2]), B(colors[2]));
  switch (pal) {
    case 0:  target = PartyColors_gc22; break;
    // 1 is WLED's randomly generated palette, regenerated on a timer by
    // handleRandomPalette(). There is no such timer here, so it is pinned to
    // Party rather than left as an undefined third thing.
    case 1:  target = PartyColors_gc22; break;
    case 2:  target = CRGBPalette16(prim); break;
    case 3:  target = CRGBPalette16(prim, prim, sec, sec); break;
    case 4:  target = CRGBPalette16(ter, sec, prim); break;
    case 5:
      if (colors[2]) target = CRGBPalette16(prim,prim,prim,prim,prim,sec,sec,sec,sec,sec,ter,ter,ter,ter,ter,prim);
      else           target = CRGBPalette16(prim,prim,prim,prim,prim,prim,prim,prim,sec,sec,sec,sec,sec,sec,sec,sec);
      break;
    default:
      if (pal > WLED_CUSTOM_PALETTE_ID_BASE) {
        target = usermodPalettes[WLED_USERMOD_PALETTE_ID_BASE - pal].palette;
      } else if (pal >= FIXED_PALETTE_COUNT) {
        target = customPalettes[WLED_CUSTOM_PALETTE_ID_BASE - pal];
      } else if (pal < DYNAMIC_PALETTE_COUNT + FASTLED_PALETTE_COUNT) {
        target = *fastledPalettes[pal - DYNAMIC_PALETTE_COUNT];
      } else {
        // The ONE place this cannot be a literal transcription. The firmware
        // reads the table entry with pgm_read_dword, which is right on an
        // ESP32 where a pointer is 32 bits - on a 64-bit host it truncates the
        // pointer and the first gradient palette dereferences garbage. PROGMEM
        // is a no-op here, so the entry is just a pointer and is read as one.
        uint8_t tcp[72];
        memcpy(tcp, gGradientPalettes[pal - (DYNAMIC_PALETTE_COUNT + FASTLED_PALETTE_COUNT)], sizeof(tcp));
        target.loadDynamicGradientPalette(tcp);
      }
      break;
  }
}

// Reloaded every call rather than cached on the palette id, because a usermod
// palette's SIXTEEN STOPS change under a fixed id - that is the entire point of
// them. Caching on the id would freeze the audio-reactive ones on their first
// frame, which is exactly the bug this would have shipped with.
const CRGBPalette16 &Segment::currentPalette() const {
  static CRGBPalette16 cache;
  simLoadPalette(cache, palette, colors);
  return cache;
}

// --- usermods -----------------------------------------------------------------
static std::vector<Usermod *> simUsermods;
static bool simUsermodsStarted = false;
void simRegisterUsermod(Usermod *u) { simUsermods.push_back(u); }

// setup() has to be able to run BEFORE the first frame, because that is where a
// usermod registers its palettes and the host asks for the palette list while
// building its UI. Deferring it to the first frame left the audio-reactive
// palettes missing from the list until something had already been rendered.
void simEnsureUsermods() {
  if (simUsermodsStarted) return;
  simUsermodsStarted = true;
  for (auto *u : simUsermods) u->setup();
}
static void simUsermodFrame() {
  simEnsureUsermods();
  for (auto *u : simUsermods) u->loop();
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
void simRegisterStock1D();     // gen/wled_fx1d.cpp, written by native/stock1d.py

static void registerStock() {
  static bool done = false;
  if (done) return;
  done = true;
  simRegisterStock();
  simRegisterStock1D();
}

// --- the C surface the page calls -------------------------------------------
// The palette usermod's one setting. On the device this comes from the Usermods
// settings page; here it comes from the control column. Declared OUTSIDE the
// extern "C" block below - inside it they would take C linkage and not match
// the C++ definitions in cube_fx_palettes.cpp.
void    cfxSetPaletteSource(uint8_t s);
uint8_t cfxGetPaletteSource();

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

// A segment of w x h logical pixels. h == 1 is a 1-D strip: is2D() says no,
// SEGLEN is w, and effects that need a matrix fall back exactly as they do on
// a device with no 2-D configured. The buffer is bounded by the static
// gPixels; a request past it is clamped rather than overrun.
SIM_API void simInit(int w, int h) {
  if (w < 1) w = 1;
  if (h < 1) h = 1;
  if ((size_t)w * h > sizeof(gPixels) / sizeof(gPixels[0])) { w = 256; h = 256; }
  Segment::_vw = w; Segment::_vh = h;
  gSeg.pixels = gPixels;
  gSeg.data = nullptr; gSeg._dataLen = 0;
  gSeg.call = 0; gSeg.step = 0; gSeg.aux0 = 0; gSeg.aux1 = 0;
  _segPtr = &gSeg;
  strip._currentSegment = &gSeg;
  strip.isMatrix = (h > 1);
  strip.now = 0;
  memset(gPixels, 0, sizeof(uint32_t) * (size_t)w * h);
}

// How a 1-D effect is expanded onto a 2-D segment: 0 strip, 1 bars, 2 arcs,
// 3 corner - WLED's map1D2D, set per segment in its UI.
SIM_API void simSetMap1D2D(int m) {
  Segment::map1D2D = (uint8_t)(m < 0 ? 0 : (m > 4 ? 4 : m));
}

SIM_API int simWidth()  { return Segment::_vw; }
SIM_API int simHeight() { return Segment::_vh; }

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
  // Usermods run BEFORE the effect, as they do on the device - the palette
  // usermod rewrites its gradients in loop(), and the effect must draw from the
  // version belonging to this frame rather than the previous one.
  simUsermodFrame();
  cfxBankRoster()[idx].fn();
  gSeg.call++;
}

// How many palettes exist right now, fixed plus whatever usermods registered.
// Queried after the first frame, because registration happens in setup().
SIM_API int simPalCount() { simEnsureUsermods(); return simPaletteCount(); }

// One palette entry as 0x00RRGGBB, so the Python side can draw swatches and a
// test can check a palette IS what its name says rather than inferring it from
// an effect's output.
// Display name of a usermod palette, in WLED's "name: palName" form, so the
// control column can list them without hard-coding what a usermod registered.
SIM_API const char *simUmPalName(int i) {
  simEnsureUsermods();
  static char buf[48];
  if (i < 0 || i >= (int)usermodPalettes.size()) return "";
  const UsermodPalette &u = usermodPalettes[i];
  snprintf(buf, sizeof(buf), "%s: %s", u.name ? u.name : "?",
           u.palName ? u.palName : "?");
  return buf;
}

SIM_API void simSetPalSource(int s) { simEnsureUsermods(); cfxSetPaletteSource((uint8_t)s); }
SIM_API int  simGetPalSource()      { simEnsureUsermods(); return (int)cfxGetPaletteSource(); }

SIM_API int simUmPalCount() { simEnsureUsermods(); return (int)usermodPalettes.size(); }

SIM_API uint32_t simPalColor(int pal, int idx) {
  static CRGBPalette16 tmp;
  simLoadPalette(tmp, (uint8_t)pal, gSeg.colors);
  return ColorFromPalette(tmp, (unsigned)(idx & 255), 255, LINEARBLEND);
}

SIM_API uint32_t *simPixels() { return gPixels; }

} // extern "C"
