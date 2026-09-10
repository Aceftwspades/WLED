#include "wled.h"

// ===========================================================================
// cube_fx_palettes.cpp - audio-reactive palettes, registered at runtime
// ===========================================================================
// These are PALETTES, not effects. They appear in the normal palette dropdown
// and work under any effect - this folder's and WLED's stock ones alike -
// because every effect ultimately asks the segment for a colour and the
// segment reads whichever palette is selected.
//
// No core file is touched. WLED carries a registry for exactly this:
//
//   std::vector<UsermodPalette> usermodPalettes;   // wled00/colors.h
//
// A usermod pushes {palette, name, index, displayName} into it and the entry
// shows up in the UI as "name: displayName". IDs run downward from 255, and
// there are 55 slots; the audioreactive usermod claims three when its "add
// palettes" setting is on, which leaves plenty.
//
// The part that makes them REACTIVE rather than merely custom: Segment::
// loadPalette() reads usermodPalettes[i].palette live, every frame. So a
// usermod that rewrites those sixteen stops in its loop() is repainting the
// palette under whatever is drawing, continuously, with no cooperation needed
// from the effect. That is the whole mechanism.
//
// ---------------------------------------------------------------------------
// THE COLOURS ARE YOURS, NOT MINE
// ---------------------------------------------------------------------------
// The first version invented its own hues - a wheel stepping by 71, a warm-cool
// ramp with hard-coded endpoints - so whatever the rest of a setup looked like,
// these four went their own way. They now take no view on colour at all. Each
// one SAMPLES a source palette, and the audio decides only WHERE and HOW WIDELY
// it samples:
//
//   Kick    a narrow window that jumps to a new place in the source on a beat
//   Tilt    the window slides along the source with the bass/treble balance
//   Bloom   the window WIDENS with loudness, from one colour to the whole ramp
//   Ladder  stop i is source position i, brightness is band i's level
//
// The source is set in Usermods settings ("source"), and it is an ordinary WLED
// palette id, which is what makes this cover both halves of the ask:
//
//   2..5      WLED's own "primary colour", "primary + secondary" and so on, so
//             these follow the segment's COLOUR PICKERS - pick colours directly
//   0..71     any built-in palette
//   72..200   custom palettes, i.e. any gradient uploaded to the device
//
// Usermod ids (201-255) are refused, because a usermod palette sourcing another
// usermod palette is a loop, and sourcing itself is a loop that also stops
// producing any colour at all after one frame.
//
// ---------------------------------------------------------------------------
// WHY THESE FOUR, GIVEN AUDIOREACTIVE ALREADY SHIPS THREE
// ---------------------------------------------------------------------------
// Its three - Ratio, Hue, Spectrum - are all the same idea: hue taken from an
// FFT bin, brightness from that bin's level. The palette IS the spectrum, a
// chart of the sound - and like the first draft of these, it picks its own
// colours and cannot be pointed at yours.
//
// These take audio as placement and force instead: one is an EVENT, one a
// BALANCE, one DYNAMIC RANGE, and only the last reads the spectrum directly.
//
// ---------------------------------------------------------------------------
// THE SIMULATOR RUNS THESE TOO
// ---------------------------------------------------------------------------
// The filename has no NN prefix, so cube_sim/build.py's effect glob skips it -
// it is not an effect - and build.py names it explicitly instead. The simulator
// carries WLED's real palette set, its own usermodPalettes registry and a
// usermod loop, so these four appear in its palette list and react there
// exactly as they do on the device.
// ===========================================================================

#ifndef CFX_PAL_COUNT
  #define CFX_PAL_COUNT 4
#endif
#ifndef CFX_PAL_SOURCE_DEFAULT
  #define CFX_PAL_SOURCE_DEFAULT 11    // Rainbow: wide, so the movement shows
#endif

// One shared name pointer for all four, which is also how removeUsermodPalettes()
// identifies them - it matches on pointer identity, not on string contents.
static const char _cfxPalName[] PROGMEM = "CubeFX";
static const char _cfxPal0[]    PROGMEM = "Kick";
static const char _cfxPal1[]    PROGMEM = "Tilt";
static const char _cfxPal2[]    PROGMEM = "Bloom";
static const char _cfxPal3[]    PROGMEM = "Ladder";
static const char _cfxSrcKey[]  PROGMEM = "source";

class CfxPalettes : public Usermod {
  private:
    bool     registered = false;
    uint8_t  source     = CFX_PAL_SOURCE_DEFAULT;
    uint8_t  builtFor   = 0xFF;          // which source `src` currently holds
    uint32_t builtCols[3] = {0, 0, 0};
    CRGBPalette16 src;                   // the colours everything is drawn from

    uint8_t  kickPos    = 0;             // where in the source Kick is sitting
    uint8_t  kickEnv    = 0;
    uint8_t  prevPeak   = 0;
    uint8_t  tilt       = 128;
    uint8_t  loud       = 0;
    uint32_t lastMs     = 0;

    static um_data_t *audio() {
      um_data_t *um = nullptr;
      if (!UsermodManager::getUMData(&um, USERMOD_ID_AUDIOREACTIVE)) return nullptr;
      return um;
    }

    static const uint32_t *segColors() {
      return strip.getSegment(strip.getMainSegmentId()).colors;
    }

    // Segment::loadPalette() is protected, so it cannot be borrowed - but every
    // table it reads is a public global, so the part that matters is short. A
    // bad or circular id falls back to the default rather than being clamped,
    // so a mistake is visible instead of silently sourcing itself.
    void buildSource() {
      const uint32_t *cols = segColors();
      uint8_t pal = source;
      if (pal > WLED_CUSTOM_PALETTE_ID_BASE) pal = CFX_PAL_SOURCE_DEFAULT;
      if (pal >= FIXED_PALETTE_COUNT &&
          (WLED_CUSTOM_PALETTE_ID_BASE - pal) >= (int)customPalettes.size())
        pal = CFX_PAL_SOURCE_DEFAULT;

      const CRGB p0 = CRGB(R(cols[0]), G(cols[0]), B(cols[0]));
      const CRGB p1 = CRGB(R(cols[1]), G(cols[1]), B(cols[1]));
      const CRGB p2 = CRGB(R(cols[2]), G(cols[2]), B(cols[2]));
      switch (pal) {
        case 0: case 1: src = PartyColors_gc22; break;
        case 2:  src = CRGBPalette16(p0); break;
        case 3:  src = CRGBPalette16(p0, p0, p1, p1); break;
        case 4:  src = CRGBPalette16(p2, p1, p0); break;
        case 5:
          if (cols[2]) src = CRGBPalette16(p0,p0,p0,p0,p0,p1,p1,p1,p1,p1,p2,p2,p2,p2,p2,p0);
          else         src = CRGBPalette16(p0,p0,p0,p0,p0,p0,p0,p0,p1,p1,p1,p1,p1,p1,p1,p1);
          break;
        default:
          if (pal >= FIXED_PALETTE_COUNT) {
            src = customPalettes[WLED_CUSTOM_PALETTE_ID_BASE - pal];
          } else if (pal < DYNAMIC_PALETTE_COUNT + FASTLED_PALETTE_COUNT) {
            src = *fastledPalettes[pal - DYNAMIC_PALETTE_COUNT];
          } else {
            // pgm_read_ptr, not pgm_read_dword. The firmware's own copy of
            // this uses the dword form, which is right where a pointer is 32
            // bits and truncates one where it is 64 - the simulator builds for
            // a 64-bit host and would dereference a cut-down pointer. The ptr
            // form is correct on both.
            byte tcp[72];
            memcpy_P(tcp, (const byte *)pgm_read_ptr(&(gGradientPalettes[pal - (DYNAMIC_PALETTE_COUNT + FASTLED_PALETTE_COUNT)])), sizeof(tcp));
            src.loadDynamicGradientPalette(tcp);
          }
          break;
      }
      builtFor = source;
      builtCols[0] = cols[0]; builtCols[1] = cols[1]; builtCols[2] = cols[2];
    }

    // One colour out of the source, scaled. Everything below is built from this
    // and nothing else, which is what keeps these on the chosen colours.
    inline CRGB pick(uint8_t pos, uint8_t bri) const {
      const uint32_t c = ColorFromPalette(src, pos, bri, LINEARBLEND);
      return CRGB(R(c), G(c), B(c));
    }

  public:
    void setup() override {
      static const char *const names[CFX_PAL_COUNT] PROGMEM =
        { _cfxPal0, _cfxPal1, _cfxPal2, _cfxPal3 };
      for (int i = 0; i < CFX_PAL_COUNT; i++) {
        if (usermodPalettes.size() >= WLED_MAX_USERMOD_PALETTES) break;
        usermodPalettes.push_back({ CRGBPalette16(CRGB::Black), _cfxPalName,
                                    (uint8_t)i, names[i] });
        registered = true;
      }
      buildSource();
    }

    void loop() override {
      if (!registered) return;
      um_data_t *um = audio();
      if (!um) return;                       // no audioreactive: leave them black

      // strip.now, NOT millis(). WLED sets strip.now = millis() every service,
      // so on the device they are the same number - but the simulator advances
      // a SIMULATED clock and renders far faster than real time, so gating on
      // wall time meant dt never cleared the threshold and these palettes sat
      // frozen on their first frame. The effect clock is the one to trust.
      const uint32_t now = strip.now;
      uint16_t dt = (uint16_t)(now - lastMs);
      if (dt < 20) return;                   // 50 Hz is plenty for a gradient
      if (dt > 250) dt = 250;
      lastMs = now;

      // Rebuilt when the setting moves, and also when the segment's COLOURS
      // move - sources 2-5 are built from them, so a colour picker has to take
      // effect without a restart.
      {
        const uint32_t *c = segColors();
        if (source != builtFor || c[0] != builtCols[0] ||
            c[1] != builtCols[1] || c[2] != builtCols[2]) buildSource();
      }

      const float   vol  = *(float *)um->u_data[0];
      const uint8_t *fft = (uint8_t *)um->u_data[2];
      const uint8_t  pk  = *(uint8_t *)um->u_data[3];

      const int bass = (fft[0] + fft[1] + fft[2]) / 3;
      const int treb = (fft[12] + fft[13] + fft[14] + fft[15]) / 4;

      // --- Kick: an EVENT, not a level -----------------------------------
      // Jumps to a new PLACE in the source. Stepping by a large, non-dividing
      // amount matters: small steps read as a slow drift, and a step that
      // divides 256 evenly visits the same few positions for ever.
      {
        const bool rising = pk && !prevPeak;
        prevPeak = pk ? 1 : 0;
        if (rising && bass > 40) {
          // Step to somewhere that is actually LIT. Kick samples a narrow slice,
          // and plenty of palettes have a long dark end - Fire is a quarter
          // black - so a blind jump lands there often enough that the beat
          // reads as the effect dying rather than as a hit. Up to four steps
          // looking for a live spot, then take what there is: a source that is
          // dark everywhere should stay dark, not be forced bright.
          for (int t = 0; t < 4; t++) {
            kickPos = (uint8_t)(kickPos + 71);
            const CRGB c = pick(kickPos, 255);
            if ((int)c.r + (int)c.g + (int)c.b > 90) break;
          }
          kickEnv = 255;
        }
        const int d = (int)kickEnv - (dt * 255) / 420;      // ~420 ms to settle
        kickEnv = (uint8_t)(d < 0 ? 0 : d);
      }

      // --- smoothed balance and loudness ----------------------------------
      {
        const int denom = bass + treb + 1;
        const int want  = 128 + ((treb - bass) * 127) / denom;   // 1..255
        tilt = (uint8_t)(tilt + ((want - (int)tilt) * (int)dt) / 260);
        int lw = (int)(vol * 2.2f); if (lw > 255) lw = 255;
        loud = (uint8_t)((lw > (int)loud) ? lw                    // fast attack
                         : (int)loud - (((int)loud - lw) * (int)dt) / 500);
      }

      for (auto &p : usermodPalettes) {
        if (p.name != _cfxPalName) continue;
        CRGB *e = p.palette.entries;
        switch (p.palIndex) {

          case 0: {   // Kick - a narrow slice of the source, moving on the beat
            const uint8_t lift = (uint8_t)(70 + (kickEnv * 185) / 255);
            for (int i = 0; i < 16; i++) {
              const uint8_t pos = (uint8_t)(kickPos + (i - 8) * 3);
              uint8_t v = (uint8_t)((i == 0) ? 0 : lift);   // keep a black stop
              if (i > 12) v = (uint8_t)(v / (i - 11));      // and fall away
              e[i] = pick(pos, v);
            }
            break; }

          case 1: {   // Tilt - the slice slides with the bass/treble balance
            for (int i = 0; i < 16; i++) {
              const uint8_t pos = (uint8_t)(tilt + i * 6);
              e[i] = pick(pos, (uint8_t)(i == 0 ? 0 : 45 + i * 14));
            }
            break; }

          case 2: {   // Bloom - loudness WIDENS the slice, it does not brighten it
            // Quiet is one colour held dim; loud opens out across the whole
            // source at full contrast. Stop 0 stays black either way, so it
            // never becomes a wash.
            const int span = 12 + ((int)loud * 243) / 255;
            for (int i = 0; i < 16; i++) {
              const uint8_t pos = (uint8_t)((int)loud + (i * span) / 15);
              int v = 30 + (i * (40 + ((int)loud * 185) / 255)) / 15;
              if (v > 255) v = 255;
              e[i] = pick(pos, (uint8_t)(i == 0 ? 0 : v));
            }
            break; }

          default: {  // Ladder - the spectrum ACROSS the stops
            // Stop i is band i, at source position i, so a gradient sweep walks
            // up the spectrum: the palette's SHAPE is the sound while its
            // colours stay the ones that were chosen.
            for (int i = 0; i < 16; i++) e[i] = pick((uint8_t)(i * 17), fft[i]);
            break; }
        }
      }
    }

    void addToConfig(JsonObject &root) override {
      JsonObject top = root.createNestedObject(FPSTR(_cfxPalName));
      top[FPSTR(_cfxSrcKey)] = source;
    }

    bool readFromConfig(JsonObject &root) override {
      JsonObject top = root[FPSTR(_cfxPalName)];
      if (top.isNull()) return false;
      const bool ok = getJsonValue(top[FPSTR(_cfxSrcKey)], source);
      builtFor = 0xFF;                       // force a rebuild on the next loop
      return ok;
    }

    void appendConfigData(Print &s) override {
      s.print(F("addInfo('CubeFX:source',1,'<i>WLED palette id (0-200) the four "
                "audio palettes take their colours from. 2-5 follow the segment "
                "colour pickers; 6-71 are the built-ins; 72+ are uploaded "
                "palettes.</i>');"));
    }

    uint16_t getId() override { return USERMOD_ID_UNSPECIFIED; }

    // The device writes `source` through the settings page. A host that has no
    // settings page - the simulator - needs some way in, and a setter is the
    // whole of it.
    void setSource(uint8_t s) { source = s; builtFor = 0xFF; }
    uint8_t getSource() const { return source; }
};

static CfxPalettes cfx_palettes_instance;
REGISTER_USERMOD(cfx_palettes_instance);

// Free functions so a host can reach the setting without knowing the class.
void    cfxSetPaletteSource(uint8_t s) { cfx_palettes_instance.setSource(s); }
uint8_t cfxGetPaletteSource()          { return cfx_palettes_instance.getSource(); }
