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
// WHY THESE FOUR, GIVEN AUDIOREACTIVE ALREADY SHIPS THREE
// ---------------------------------------------------------------------------
// Its three - Ratio, Hue, Spectrum - are all the same idea: hue taken from an
// FFT bin, brightness from that bin's level. The palette IS the spectrum, a
// chart of the sound.
//
// These are deliberately not that. They take audio as placement and force:
// one is an EVENT (the whole palette turns on a kick), one is a BALANCE (warm
// when the bass leads, cool when the treble does), one is DYNAMIC RANGE (how
// much black the palette contains follows loudness), and only the last reads
// the spectrum directly - and it does so across the stops rather than as hue,
// so it does not duplicate the three that already exist.
//
// ---------------------------------------------------------------------------
// NOT VISIBLE IN THE SIMULATOR
// ---------------------------------------------------------------------------
// The filename has no NN prefix on purpose: cube_sim/build.py globs
// cube_fx_[0-9][0-9]_*.cpp, so the simulator skips this file, while the
// firmware build compiles every .cpp in the folder and picks it up. That is
// deliberate - the simulator carries six fixed palettes of its own and has no
// usermod registry to register into - but it does mean these cannot be
// previewed there. They are verified by compiling for the device.
// ===========================================================================

#ifndef CFX_PAL_COUNT
  #define CFX_PAL_COUNT 4
#endif

// One shared name pointer for all four, which is also how removeUsermodPalettes()
// identifies them - it matches on pointer identity, not on string contents.
static const char _cfxPalName[] PROGMEM = "CubeFX";
static const char _cfxPal0[]    PROGMEM = "Kick";
static const char _cfxPal1[]    PROGMEM = "Tilt";
static const char _cfxPal2[]    PROGMEM = "Bloom";
static const char _cfxPal3[]    PROGMEM = "Ladder";

class CfxPalettes : public Usermod {
  private:
    bool     registered = false;
    uint8_t  kickHue    = 0;     // where Kick's wheel currently sits
    uint8_t  kickEnv    = 0;     // and how recently it was hit
    uint8_t  prevPeak   = 0;
    uint8_t  tilt       = 128;   // smoothed bass/treble balance
    uint8_t  loud       = 0;     // smoothed loudness
    uint32_t lastMs     = 0;

    // Audio without going through SEGMENT - this runs in loop(), outside any
    // effect, where there is no current segment to ask about sound simulation.
    static um_data_t *audio() {
      um_data_t *um = nullptr;
      if (!UsermodManager::getUMData(&um, USERMOD_ID_AUDIOREACTIVE)) return nullptr;
      return um;
    }

    static CRGB hsv(uint8_t h, uint8_t s, uint8_t v) { return (CRGB)CHSV(h, s, v); }

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
    }

    void loop() override {
      if (!registered) return;
      um_data_t *um = audio();
      if (!um) return;                       // no audioreactive: leave them black

      const uint32_t now = millis();
      uint16_t dt = (uint16_t)(now - lastMs);
      if (dt < 20) return;                   // 50 Hz is plenty for a gradient
      if (dt > 250) dt = 250;
      lastMs = now;

      const float   vol  = *(float *)um->u_data[0];
      const uint8_t *fft = (uint8_t *)um->u_data[2];
      const uint8_t  pk  = *(uint8_t *)um->u_data[3];

      int bass = (fft[0] + fft[1] + fft[2]) / 3;
      int mid  = (fft[5] + fft[6] + fft[7] + fft[8]) / 4;
      int treb = (fft[12] + fft[13] + fft[14] + fft[15]) / 4;

      // --- Kick: an EVENT, not a level -----------------------------------
      // The wheel steps on a rising transient and then holds. Stepping by a
      // large, non-dividing amount matters: small steps read as a slow drift
      // and a step that divides 256 evenly cycles through the same few hues.
      {
        const bool rising = pk && !prevPeak;
        prevPeak = pk ? 1 : 0;
        if (rising && bass > 40) { kickHue = (uint8_t)(kickHue + 71); kickEnv = 255; }
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

          case 0: {   // Kick - whole palette turns on the beat, then settles
            const uint8_t base = kickHue;
            const uint8_t lift = (uint8_t)(60 + (kickEnv * 195) / 255);
            for (int i = 0; i < 16; i++) {
              // a tight spread around the current hue, so the palette reads as
              // one colour that CHANGES rather than as a rainbow that spins
              const uint8_t h = (uint8_t)(base + (i - 8) * 4);
              uint8_t v = (uint8_t)((i == 0) ? 0 : lift);        // keep a black stop
              if (i > 12) v = (uint8_t)(v / (i - 11));           // and fall away
              e[i] = hsv(h, (uint8_t)(255 - (kickEnv / 6)), v);
            }
            break; }

          case 1: {   // Tilt - warm when the bass leads, cool when treble does
            for (int i = 0; i < 16; i++) {
              // 0 = deep red, 160 = blue; tilt slides the whole ramp along it
              const uint8_t h = (uint8_t)(((int)tilt * 150) / 255 + i * 5);
              const uint8_t v = (uint8_t)(i == 0 ? 0 : 40 + i * 14);
              e[i] = hsv(h, (uint8_t)(230 - i * 4), v);
            }
            break; }

          case 2: {   // Bloom - loudness buys CONTRAST, not brightness
            // Quiet keeps the ramp compressed near black; loud opens it to the
            // full range. Black is always present at stop 0, which is what
            // stops it turning into a wash when the track is loud.
            const int span = 40 + ((int)loud * 215) / 255;
            for (int i = 0; i < 16; i++) {
              int v = (i * span) / 15;
              if (v > 255) v = 255;
              const uint8_t h = (uint8_t)(150 - ((int)loud * 90) / 255 + i * 3);
              e[i] = hsv(h, (uint8_t)(255 - v / 3), (uint8_t)v);
            }
            break; }

          default: {  // Ladder - the spectrum ACROSS the stops, not as hue
            // Stop i is band i, so a gradient sweep walks up the spectrum and
            // the palette's shape is the sound. Hue stays fixed per stop so
            // the reading is in brightness, which is what the other three
            // audio palettes do not do.
            for (int i = 0; i < 16; i++) {
              const uint8_t lvl = fft[i];
              const uint8_t h   = (uint8_t)(20 + i * 13);
              e[i] = hsv(h, (uint8_t)(255 - lvl / 4), lvl);
            }
            break; }
        }
      }
    }

    uint16_t getId() override { return USERMOD_ID_UNSPECIFIED; }
};

static CfxPalettes cfx_palettes_instance;
REGISTER_USERMOD(cfx_palettes_instance);
