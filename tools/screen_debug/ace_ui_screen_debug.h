#pragma once

// ===========================================================================
// ace_ui_screen_debug.h - the panel test modes, kept out of the firmware
// ===========================================================================
// NOT COMPILED unless you ask for it. This file lives outside usermods/ so
// PlatformIO never sees it, and ace_ui_screen.cpp only includes it when
// AUI_SCREEN_DEBUG is set. Nothing here costs a byte of flash otherwise.
//
//   build_flags = -D AUI_SCREEN_DEBUG=1
//
// ---------------------------------------------------------------------------
// WHY THESE EXIST
// ---------------------------------------------------------------------------
// A 4-wire SPI panel cannot be asked anything. There is no MISO, no ACK, no
// status register - the only output the whole system has is the glass itself.
// So when a panel is dark, every layer is equally suspect: the wiring, the
// bus, the addressing, the init, the buffer, the flush, the power. Reasoning
// about which one is broken does not work; each of these narrows it to one.
//
// They were written one at a time while chasing a panel that would only light
// after being fed garbage by a deliberately mis-wired boot. In the end the
// fault was two settings switching the display off on a timer - but it took
// this much instrumentation to prove the entire transport was innocent, and
// the same tests will be worth having the next time a screen arrives dark.
//
// Each one returns early from loop(), so nothing else touches the panel while
// it runs. Read them in this order, because each assumes the ones above it:
//
//   selfTest    Blinks 0xA5 / 0xA4 - "all segments on" and "show RAM". Both
//               are COMMANDS and need no data path. Blinking means the panel
//               hears commands, which is the first thing worth knowing and
//               the thing a dark screen cannot tell you.
//
//   dcdcKick    Flushes to a command boundary, then sends the whole register
//               set by hand - both controllers' power commands, multiplex,
//               contrast, display on. Repairs a live panel without a reboot.
//               If a dark panel lights within a second, the init was the
//               fault and not the wiring.
//
//   resetHold   Holds RES low and does nothing else. A connected reset line
//               blanks the panel instantly and keeps it blank. A panel that
//               carries on is not wired to that GPIO, whatever it looks like.
//
//   pageTest    Writes a staircase using nothing but raw page-select commands
//               and data - no u8g2 buffer, no DrawTile, no x_offset, no diff,
//               no flush. Eight bars means the controller honours page
//               addressing and every layer below the library is sound. This
//               is the test that finally exonerated the whole transport.
//
//   rowTest     The same staircase, but through u8g2's buffer and our flush.
//               Compare against pageTest: if pageTest is clean and rowTest is
//               not, the fault is in the library or in our code, and nowhere
//               near the hardware.
//
//   fullRefresh Sends the whole panel with u8g2's sendBuffer() instead of the
//               changed tile rows. Bisects "our diff is wrong" from
//               "everything is wrong". Slow on purpose - 1024 bytes in one go.
//
// The counters they were used with - Panel draw, Panel pins - are NOT here.
// Those stayed in the usermod: they cost an increment, they answer "is the
// software driving DC at all" and "did anything reach the panel", and having
// them from the start would have saved most of the session that produced this
// file.
// ===========================================================================

#define AUI_DBG_FIELDS                                                         \
  bool fullRefresh = false;                                                    \
  bool rowTest     = false;                                                    \
  bool pageTest    = false;                                                    \
  bool resetHold   = false;                                                    \
  bool dcdcKick    = false;                                                    \
  bool selfTest    = false;                                                    \
  uint32_t lastTestMs = 0;                                                     \
  bool     testOn     = false;                                                 \
                                                                               \
  /* true when a test mode handled this pass and loop() should stop */         \
  bool dbgLoop(uint32_t now) {                                                 \
    if (dcdcKick) {                                                            \
      if (now - lastTestMs >= 1000) {                                          \
        lastTestMs = now;                                                      \
        flushCmd();                                                            \
        sendFullInit();                                                        \
      }                                                                        \
      return true;                                                             \
    }                                                                          \
    if (resetHold) {                                                           \
      if (spiRst >= 0) { pinMode(spiRst, OUTPUT); digitalWrite(spiRst, LOW); } \
      return true;                                                             \
    }                                                                          \
    if (pageTest) {                                                            \
      if (now - lastTestMs >= 1000) {                                          \
        lastTestMs = now;                                                      \
        u8x8_t *u = g->getU8x8();                                              \
        uint8_t blob[128];                                                     \
        memset(blob, 0x0FF, sizeof(blob));                                     \
        for (uint8_t page = 0; page < 8; page++) {                             \
          u8x8_cad_StartTransfer(u);                                           \
          u8x8_cad_SendCmd(u, 0x0B0 | page);                                   \
          u8x8_cad_SendCmd(u, 0x000);                                          \
          u8x8_cad_SendCmd(u, 0x010);                                          \
          u8x8_cad_SendData(u, (uint8_t)((page + 1) * 16), blob);              \
          u8x8_cad_EndTransfer(u);                                             \
        }                                                                      \
      }                                                                        \
      return true;                                                             \
    }                                                                          \
    if (selfTest) {                                                            \
      if (now - lastTestMs >= 1000) {                                          \
        lastTestMs = now;                                                      \
        testOn = !testOn;                                                      \
        u8x8_t *u = g->getU8x8();                                              \
        u8x8_cad_StartTransfer(u);                                             \
        u8x8_cad_SendCmd(u, testOn ? 0x0A5 : 0x0A4);                           \
        u8x8_cad_EndTransfer(u);                                               \
      }                                                                        \
      return true;                                                             \
    }                                                                          \
    return false;                                                              \
  }                                                                            \
                                                                               \
  /* whole-panel send, instead of the changed rows. true when it did it */     \
  bool dbgFullFlush() {                                                        \
    if (!fullRefresh) return false;                                            \
    AceUiStats &st = aceUi().stats;                                            \
    const uint32_t t0 = micros();                                              \
    g->sendBuffer();                                                           \
    const uint32_t dt = micros() - t0;                                         \
    memcpy(shadow, g->getBufferPtr(), (size_t)rowBytes * th);                  \
    dirtyMask = 0;                                                             \
    pagesSec = (uint16_t)(pagesSec + th);                                      \
    st.busBusyUs += dt;                                                        \
    flushAcc += dt; flushN++;                                                  \
    if (dt > st.flushWorstUs) st.flushWorstUs = dt;                            \
    return true;                                                               \
  }                                                                            \
                                                                               \
  /* the staircase, drawn through u8g2's buffer. true when it drew */          \
  bool dbgDrawRows(int W) {                                                    \
    if (!rowTest) return false;                                                \
    for (int r = 0; r < (int)th; r++)                                          \
      g->drawBox(0, r * 8 + 1, ((r + 1) * W) / (int)th, 6);                    \
    return true;                                                              \
  }

#define AUI_DBG_LOOP(now)      do { if (dbgLoop(now)) return; } while (0)
#define AUI_DBG_FULL_FLUSH()   do { if (dbgFullFlush()) return; } while (0)
#define AUI_DBG_DRAW(W)        dbgDrawRows(W)
#define AUI_DBG_REDRAW(now)                                                    \
  if (rowTest && (now) - lastVuMs >= 250) { lastVuMs = (now); redraw = true; }

#define AUI_DBG_SAVE(top)                                                      \
  top["dcdcKick"]    = dcdcKick;                                               \
  top["resetHold"]   = resetHold;                                              \
  top["pageTest"]    = pageTest;                                               \
  top["rowTest"]     = rowTest;                                                \
  top["fullRefresh"] = fullRefresh;                                            \
  top["selfTest"]    = selfTest;

#define AUI_DBG_LOAD(top)                                                      \
  getJsonValue(top["dcdcKick"],    dcdcKick,    false);                        \
  getJsonValue(top["resetHold"],   resetHold,   false);                        \
  getJsonValue(top["pageTest"],    pageTest,    false);                        \
  getJsonValue(top["rowTest"],     rowTest,     false);                        \
  getJsonValue(top["fullRefresh"], fullRefresh, false);                        \
  getJsonValue(top["selfTest"],    selfTest,    false);

#define AUI_DBG_UI(info)                                                       \
  info("dcdcKick",    "flush + full register set by hand. lights = init was the fault"); \
  info("resetHold",   "holds RES low. no blank = RES is not wired");           \
  info("pageTest",    "raw page-select staircase. 8 bars = transport is sound"); \
  info("rowTest",     "same staircase through u8g2 and our flush. compare");   \
  info("fullRefresh", "whole panel per send, not changed rows. slow. a bisect"); \
  info("selfTest",    "blinks 0xA5/0xA4. blinking = the panel hears commands");
