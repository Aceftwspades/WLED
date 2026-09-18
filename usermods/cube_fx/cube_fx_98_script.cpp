#include "wled.h"
#include "cube_fx_common.h"
#include "cube_fx_bank.h"
#include "cube_fx_studio_helpers.h"

// ===========================================================================
// Studio Script - the scripted runtime
// ===========================================================================
// Runs a program the WLED Effects Studio compiled from a node graph
// (native/script.py), so an effect reaches the cube over the network with no
// firmware build: the studio POSTs /studio.bin to /upload, this effect sees
// the file change and runs it. One effect slot, any graph the studio's
// subset can express (see script.py for what cannot).
//
// The program is straight-line bytecode over a float register file, colour
// registers and a state array kept between frames: a frame stream run once a
// frame after the VM fills the fixed registers (time, sliders, audio...), a
// pixel stream run per pixel with that pixel's coordinates in the fixed
// registers. No jumps: an `if` on a live value was compiled to selects.
// Every op is a switch case below, in the order of script.py's OPS table -
// the two are one table, kept in step by hand.
//
// In the simulator (CFX_SIM) the studio hands the program over in memory
// (simScriptLoad), so a script previews exactly as it will run.
// ===========================================================================

#define SS_FIXED 56          // fixed registers; the compiler allocates from here
#define SS_BAND0 36
#define SS_MAX_PROG (24 * 1024)

enum : uint8_t {
  SS_END, SS_CONST, SS_MOV, SS_ADD, SS_SUB, SS_MUL, SS_DIV, SS_MIN, SS_MAX, SS_POW, SS_MOD, SS_ATAN2,
  SS_ABS, SS_FLOOR, SS_FRACT, SS_SIN, SS_COS, SS_SQRT, SS_EXP, SS_LOG, SS_SAT, SS_SIGN, SS_ROUND, SS_NOT,
  SS_TAN, SS_TRUNC, SS_CEIL, SS_LT, SS_LE, SS_GT, SS_GE, SS_EQ, SS_NE, SS_AND, SS_OR, SS_SEL,
  SS_NOISE, SS_HASH, SS_FBM, SS_PAL, SS_HSV, SS_RGB, SS_CR, SS_CG, SS_CB, SS_CMIX, SS_CSCALE, SS_CADD, SS_CMUL,
  SS_CMAX, SS_CMIN, SS_CSEL, SS_SEGCOL, SS_CMOV, SS_CCONST, SS_OUT, SS_STLD, SS_STST, SS_RND, SS_BLEND,
  SS_RINGUV, SS_POSUV, SS_FOLD, SS_KNOT, SS_MANDEL, SS_EASE, SS_LOUDEST
};

enum { SSF_u, SSF_v, SSF_cx, SSF_cy, SSF_r, SSF_ang, SSF_px, SSF_py, SSF_W, SSF_H, SSF_N, SSF_t, SSF_dt,
       SSF_sx, SSF_ix, SSF_c1, SSF_c2, SSF_c3, SSF_o1, SSF_o2, SSF_o3, SSF_vol, SSF_beat, SSF_first,
       SSF_X3, SSF_Y3, SSF_Z3, SSF_nx, SSF_ny, SSF_nz, SSF_B, SSF_cube, SSF_hit, SSF_bass, SSF_mid, SSF_treb, SSF_call };

// Each op's operands, in script.py's OPS letters: f a float register, c a
// colour register, i a 16-bit integer, k a 32-bit float. ssParse walks both
// streams against this table once, when a program arrives, and refuses one
// with a register out of range or an op it does not know - so the run loop
// below indexes the register files straight, with no check per operand.
static const char *const SS_SIG[] = {
  "", "fk", "ff", "fff", "fff", "fff", "fff", "fff", "fff", "fff", "fff", "fff",
  "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff", "ff",
  "ff", "ff", "ff", "fff", "fff", "fff", "fff", "fff", "fff", "fff", "fff", "ffff",
  "ffff", "ffff", "fffffff", "cff", "cfff", "cfff", "fc", "fc", "fc", "cccf", "ccf", "ccc", "ccc",
  "ccc", "ccc", "cfcc", "ci", "cc", "ci", "c", "fi", "if", "f", "cccfi",
  "ffff", "fffff", "ffffffi", "ffffffffffffff", "ffffff", "fff", "ffii"
};
#define SS_NOPS (sizeof(SS_SIG) / sizeof(SS_SIG[0]))

struct SsProgram {
  uint8_t *bytes = nullptr;
  size_t len = 0;
  uint16_t nf = 0, nc = 0, ns = 0;
  uint32_t frameLen = 0, pixelLen = 0;
  const uint8_t *frame = nullptr, *pixel = nullptr;
  uint32_t stamp = 0;                // changes when a new program is loaded
  bool valid = false;
  bool usesPolar = false;            // the pixel stream reads r or ang
  bool usesSpace = false;            // ... or the 3-D position / normal
};
static SsProgram gSs;

// One stream checked against SS_SIG; false on a bad op or register. The
// fixed registers the stream reads are noted in `reads` (bits 0..55).
static bool ssCheck(const uint8_t *p, const uint8_t *end, const SsProgram &P, uint64_t &reads) {
  while (p < end) {
    const uint8_t op = *p++;
    if (op == SS_END) return true;
    if (op >= SS_NOPS) return false;
    for (const char *k = SS_SIG[op]; *k; k++) {
      if (*k == 'k') { if (end - p < 4) return false; p += 4; continue; }
      if (end - p < 2) return false;
      const uint16_t v = p[0] | (p[1] << 8); p += 2;
      if (*k == 'f') { if (v >= P.nf) return false; if (v < SS_FIXED) reads |= (uint64_t)1 << v; }
      else if (*k == 'c') { if (v >= P.nc) return false; }
    }
  }
  return true;
}

static bool ssParse(SsProgram &P) {
  P.valid = false;
  if (!P.bytes || P.len < 19 || memcmp(P.bytes, "STUV", 4) != 0 || P.bytes[4] != 1) return false;
  const uint8_t *h = P.bytes + 5;
  P.nf = h[0] | (h[1] << 8); P.nc = h[2] | (h[3] << 8); P.ns = h[4] | (h[5] << 8);
  P.frameLen = (uint32_t)h[6] | ((uint32_t)h[7] << 8) | ((uint32_t)h[8] << 16) | ((uint32_t)h[9] << 24);
  P.pixelLen = (uint32_t)h[10] | ((uint32_t)h[11] << 8) | ((uint32_t)h[12] << 16) | ((uint32_t)h[13] << 24);
  if (19 + P.frameLen + P.pixelLen > P.len) return false;
  if (P.nf < SS_FIXED || P.nf > 4096 || P.nc < 1 || P.nc > 2048 || P.ns > 4096) return false;
  P.frame = P.bytes + 19;
  P.pixel = P.frame + P.frameLen;
  uint64_t reads = 0;
  if (!ssCheck(P.frame, P.frame + P.frameLen, P, reads)) return false;
  reads = 0;
  if (!ssCheck(P.pixel, P.pixel + P.pixelLen, P, reads)) return false;
  P.usesPolar = (reads & (((uint64_t)1 << SSF_r) | ((uint64_t)1 << SSF_ang))) != 0;
  P.usesSpace = (reads & (((uint64_t)1 << SSF_X3) | ((uint64_t)1 << SSF_Y3) | ((uint64_t)1 << SSF_Z3)
                        | ((uint64_t)1 << SSF_nx) | ((uint64_t)1 << SSF_ny) | ((uint64_t)1 << SSF_nz))) != 0;
  P.valid = true;
  P.stamp++;
  return true;
}

// The palette, 256 entries, made on the first PAL of a frame and kept for
// the rest of it: one palette lookup per index per frame, not per pixel.
static uint32_t ssPalTab[256];
static bool ssPalReady = false;
static inline uint32_t ssPal(uint8_t i) {
  if (!ssPalReady) {
    for (int k = 0; k < 256; k++) ssPalTab[k] = SEGMENT.color_from_palette((uint8_t)k, false, true, 0);
    ssPalReady = true;
  }
  return ssPalTab[i];
}

#ifdef CFX_SIM
// The simulator loads programs from memory.
extern "C" void simScriptLoad(const uint8_t *bytes, int n) {
  free(gSs.bytes); gSs.bytes = nullptr; gSs.len = 0;
  if (bytes && n > 0 && n <= SS_MAX_PROG) {
    gSs.bytes = (uint8_t *)malloc(n); memcpy(gSs.bytes, bytes, n); gSs.len = n;
  }
  ssParse(gSs);
}
extern "C" int simScriptOk() { return gSs.valid ? 1 : 0; }
static void ssPoll() {}
#else
// The device reads /studio.bin, and again whenever it changes (a few KB,
// checked every two seconds - a read, not a rebuild).
static void ssPoll() {
  static uint32_t last = 0;
  if (millis() - last < 2000) return;
  last = millis();
  File f = WLED_FS.open("/studio.bin", "r");
  if (!f) return;
  size_t n = f.size();
  if (n < 19 || n > SS_MAX_PROG) { f.close(); return; }
  uint8_t *buf = (uint8_t *)malloc(n);
  if (!buf) { f.close(); return; }
  size_t got = f.read(buf, n);
  f.close();
  if (got == n && !(gSs.bytes && gSs.len == n && memcmp(gSs.bytes, buf, n) == 0)) {
    free(gSs.bytes); gSs.bytes = buf; gSs.len = n;
    ssParse(gSs);
  } else free(buf);
}
#endif

static inline uint16_t ssU16(const uint8_t *&p) { uint16_t v = p[0] | (p[1] << 8); p += 2; return v; }
static inline float ssF32(const uint8_t *&p) { float v; memcpy(&v, p, 4); p += 4; return v; }

// One stream. F, C, S are the register files; returns the OUT colour (or 0).
// Register operands were range-checked by ssParse; state slots are checked
// here, as the state block is sized separately.
static uint32_t ssRun(const uint8_t *p, const uint8_t *end, float *F, uint32_t *C, float *S,
                      uint16_t ns, const uint8_t *fft) {
  uint32_t out = 0;
  #define RF(i) F[(i)]
  #define RC(i) C[(i)]
  while (p < end) {
    const uint8_t op = *p++;
    uint16_t a, b, c, d;
    switch (op) {
      case SS_END: return out;
      case SS_CONST: a = ssU16(p); RF(a) = ssF32(p); break;
      case SS_MOV: a = ssU16(p); b = ssU16(p); RF(a) = RF(b); break;
      case SS_ADD: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) + RF(c); break;
      case SS_SUB: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) - RF(c); break;
      case SS_MUL: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) * RF(c); break;
      case SS_DIV: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(c) != 0.0f ? RF(b) / RF(c) : 0.0f; break;
      case SS_MIN: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = fminf(RF(b), RF(c)); break;
      case SS_MAX: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = fmaxf(RF(b), RF(c)); break;
      case SS_POW: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = powf(RF(b) < 0.0f ? 0.0f : RF(b), RF(c)); break;
      case SS_MOD: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(c) != 0.0f ? fmodf(RF(b), RF(c)) : 0.0f; break;
      case SS_ATAN2: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = cfx_atan2f(RF(b), RF(c)); break;
      case SS_ABS: a = ssU16(p); b = ssU16(p); RF(a) = fabsf(RF(b)); break;
      case SS_FLOOR: a = ssU16(p); b = ssU16(p); RF(a) = floorf(RF(b)); break;
      case SS_FRACT: a = ssU16(p); b = ssU16(p); RF(a) = RF(b) - floorf(RF(b)); break;
      case SS_SIN: a = ssU16(p); b = ssU16(p); RF(a) = sin_t(RF(b)); break;      // WLED's table sine: within 0.0015 of sinf, a fraction of the time
      case SS_COS: a = ssU16(p); b = ssU16(p); RF(a) = cos_t(RF(b)); break;
      case SS_SQRT: a = ssU16(p); b = ssU16(p); RF(a) = sqrtf(RF(b) < 0.0f ? 0.0f : RF(b)); break;
      case SS_EXP: a = ssU16(p); b = ssU16(p); RF(a) = expf(RF(b)); break;
      case SS_LOG: a = ssU16(p); b = ssU16(p); RF(a) = RF(b) > 0.0f ? logf(RF(b)) : 0.0f; break;
      case SS_SAT: a = ssU16(p); b = ssU16(p); RF(a) = gc_sat(RF(b)); break;
      case SS_SIGN: a = ssU16(p); b = ssU16(p); RF(a) = RF(b) > 0.0f ? 1.0f : (RF(b) < 0.0f ? -1.0f : 0.0f); break;
      case SS_ROUND: a = ssU16(p); b = ssU16(p); RF(a) = floorf(RF(b) + 0.5f); break;
      case SS_NOT: a = ssU16(p); b = ssU16(p); RF(a) = RF(b) != 0.0f ? 0.0f : 1.0f; break;
      case SS_TAN: a = ssU16(p); b = ssU16(p); RF(a) = tanf(RF(b)); break;
      case SS_TRUNC: a = ssU16(p); b = ssU16(p); RF(a) = (float)(int32_t)RF(b); break;
      case SS_CEIL: a = ssU16(p); b = ssU16(p); RF(a) = ceilf(RF(b)); break;
      case SS_LT: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) < RF(c) ? 1.0f : 0.0f; break;
      case SS_LE: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) <= RF(c) ? 1.0f : 0.0f; break;
      case SS_GT: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) > RF(c) ? 1.0f : 0.0f; break;
      case SS_GE: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) >= RF(c) ? 1.0f : 0.0f; break;
      case SS_EQ: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) == RF(c) ? 1.0f : 0.0f; break;
      case SS_NE: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = RF(b) != RF(c) ? 1.0f : 0.0f; break;
      case SS_AND: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = (RF(b) != 0.0f && RF(c) != 0.0f) ? 1.0f : 0.0f; break;
      case SS_OR: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = (RF(b) != 0.0f || RF(c) != 0.0f) ? 1.0f : 0.0f; break;
      case SS_SEL: a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); RF(a) = RF(b) != 0.0f ? RF(c) : RF(d); break;
      case SS_NOISE: { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p);
        RF(a) = perlin8((uint16_t)(RF(b) * 256.0f), (uint16_t)(RF(c) * 256.0f), (uint16_t)(RF(d) * 256.0f)) * (1.0f / 255.0f); break; }
      case SS_HASH: a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); RF(a) = gc_hash(RF(b), RF(c), RF(d)); break;
      case SS_FBM: { a = ssU16(p); uint16_t x = ssU16(p), y = ssU16(p), z = ssU16(p), s = ssU16(p), o = ssU16(p), rg = ssU16(p);
        RF(a) = gc_fbm(RF(x), RF(y), RF(z), RF(s), (int)RF(o), RF(rg)); break; }
      case SS_PAL: { a = ssU16(p); b = ssU16(p); c = ssU16(p);
        RC(a) = mq_scale(ssPal((uint8_t)(int)(gc_sat(RF(b)) * 255.0f)), (uint8_t)(gc_sat(RF(c)) * 255.0f)); break; }
      case SS_HSV: a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); RC(a) = gc_hsv(RF(b), RF(c), RF(d)); break;
      case SS_RGB: { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p);
        RC(a) = RGBW32((uint8_t)(gc_sat(RF(b)) * 255.0f), (uint8_t)(gc_sat(RF(c)) * 255.0f), (uint8_t)(gc_sat(RF(d)) * 255.0f), 0); break; }
      case SS_CR: a = ssU16(p); b = ssU16(p); RF(a) = (float)((RC(b) >> 16) & 255) * (1.0f / 255.0f); break;
      case SS_CG: a = ssU16(p); b = ssU16(p); RF(a) = (float)((RC(b) >> 8) & 255) * (1.0f / 255.0f); break;
      case SS_CB: a = ssU16(p); b = ssU16(p); RF(a) = (float)(RC(b) & 255) * (1.0f / 255.0f); break;
      case SS_CMIX: { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p);
        RC(a) = color_blend(RC(b), RC(c), (uint8_t)(gc_sat(RF(d)) * 255.0f)); break; }
      case SS_CSCALE: a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = mq_scale(RC(b), (uint8_t)(gc_sat(RF(c)) * 255.0f)); break;
      case SS_CADD: a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = color_add(RC(b), RC(c), true); break;
      case SS_CMUL: a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = gc_blend_multiply(RC(b), RC(c), 1.0f); break;
      case SS_CMAX: a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = gc_blend_max(RC(b), RC(c), 1.0f); break;
      case SS_CMIN: a = ssU16(p); b = ssU16(p); c = ssU16(p); RC(a) = gc_blend_min(RC(b), RC(c), 1.0f); break;
      case SS_CSEL: a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); RC(a) = RF(b) != 0.0f ? RC(c) : RC(d); break;
      case SS_SEGCOL: a = ssU16(p); b = ssU16(p); RC(a) = SEGCOLOR(b < 3 ? b : 0); break;
      case SS_CMOV: a = ssU16(p); b = ssU16(p); RC(a) = RC(b); break;
      case SS_CCONST: a = ssU16(p); b = ssU16(p); RC(a) = b; break;
      case SS_OUT: a = ssU16(p); out = RC(a); break;
      case SS_STLD: a = ssU16(p); b = ssU16(p); RF(a) = b < ns ? S[b] : 0.0f; break;
      case SS_STST: a = ssU16(p); b = ssU16(p); if (a < ns) S[a] = RF(b); break;
      case SS_RND: a = ssU16(p); RF(a) = gc_rnd(); break;
      case SS_BLEND: { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); uint16_t m = ssU16(p);
        const float amt = gc_sat(RF(d));
        switch (m) {
          case 0: RC(a) = gc_blend_over(RC(b), RC(c), amt); break;
          case 1: RC(a) = gc_blend_add(RC(b), RC(c), amt); break;
          case 2: RC(a) = gc_blend_multiply(RC(b), RC(c), amt); break;
          case 3: RC(a) = gc_blend_screen(RC(b), RC(c), amt); break;
          case 4: RC(a) = gc_blend_max(RC(b), RC(c), amt); break;
          case 5: RC(a) = gc_blend_min(RC(b), RC(c), amt); break;
          default: RC(a) = gc_blend_mode(m, RC(b), RC(c), amt); break;
        }
        break; }
      case SS_RINGUV: { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p);
        float u_ = 0, v_ = 0; const int W = (int)F[SSF_W], H = (int)F[SSF_H], B = (int)F[SSF_B];
        gc_ring_uv(RF(c), RF(d), W, H, B, F[SSF_cube] != 0.0f, u_, v_); RF(a) = u_; RF(b) = v_; break; }
      case SS_POSUV: { a = ssU16(p); b = ssU16(p); c = ssU16(p); d = ssU16(p); uint16_t e = ssU16(p);
        float u_ = 0, v_ = 0; const int W = (int)F[SSF_W], H = (int)F[SSF_H], B = (int)F[SSF_B];
        gc_pos_uv(RF(c), RF(d), RF(e), W, H, B, F[SSF_cube] != 0.0f, u_, v_); RF(a) = u_; RF(b) = v_; break; }
      case SS_FOLD: { a = ssU16(p); b = ssU16(p); c = ssU16(p); uint16_t x = ssU16(p), y = ssU16(p), z = ssU16(p), sym = ssU16(p);
        float fx = RF(x), fy = RF(y), fz = RF(z); gc_fold((int)sym, fx, fy, fz); RF(a) = fx; RF(b) = fy; RF(c) = fz; break; }
      case SS_KNOT: { uint16_t o[6]; for (int i = 0; i < 6; i++) o[i] = ssU16(p);
        uint16_t in[8]; for (int i = 0; i < 8; i++) in[i] = ssU16(p);
        float al = 0, ed = 0, Nx = 0, Ny = 0, Nz = 0;
        const bool hit = gc_knot(RF(in[0]), RF(in[1]), RF(in[2]), (int)RF(in[3]), (int)RF(in[4]), RF(in[5]), RF(in[6]), RF(in[7]), al, ed, Nx, Ny, Nz);
        RF(o[0]) = hit ? 1.0f : 0.0f; RF(o[1]) = al; RF(o[2]) = ed; RF(o[3]) = Nx; RF(o[4]) = Ny; RF(o[5]) = Nz; break; }
      case SS_MANDEL: { a = ssU16(p); uint16_t x = ssU16(p), y = ssU16(p), zx = ssU16(p), zy = ssU16(p), it = ssU16(p);
        RF(a) = gc_mandel(RF(x), RF(y), RF(zx), RF(zy), (int)RF(it)); break; }
      case SS_EASE: a = ssU16(p); b = ssU16(p); c = ssU16(p); RF(a) = gc_ease(RF(b), (int)RF(c)); break;
      case SS_LOUDEST: { a = ssU16(p); b = ssU16(p); uint16_t from = ssU16(p), to = ssU16(p);
        int best = from < 16 ? from : 15; for (int i = from; i <= to && i < 16; i++) if (fft[i] > fft[best]) best = i;
        RF(a) = (float)best * (1.0f / 15.0f); RF(b) = (float)fft[best] * (1.0f / 255.0f); break; }
      default: return out;                // an op this build does not know: stop the stream
    }
  }
  #undef RF
  #undef RC
  return out;
}

static void mode_studio_script() {
  ssPoll();
  const bool is2d = SEGMENT.is2D();
  const int W = is2d ? SEG_W : SEGLEN, H = is2d ? SEG_H : 1;
  const int N = W * H;
  const bool cube = is2d && cfx_isCube(W, H);
  const int  B    = cube ? (W / 3) : 1;
  static uint8_t clk_[2] = {0, 0};
  const uint16_t dt = fx_dt8(clk_);
  const float t = (float)strip.now * 0.001f;
  (void)N;
  if (!gSs.valid) {
    // no program: a slow breathing dot, so a segment on this effect is not just dark
    const uint8_t k = (uint8_t)(96 + 64 * sinf(t * 2.0f));
    SEGMENT.fill(0);
    if (is2d) SEGMENT.setPixelColorXY(W / 2, H / 2, RGBW32(0, k, k, 0)); else SEGMENT.setPixelColor(0, RGBW32(0, k, k, 0));
    FX_DONE;
  }
  const SsProgram &P = gSs;
  const size_t need = ((size_t)P.nf + P.ns) * sizeof(float) + (size_t)P.nc * sizeof(uint32_t) + 8;
  if (!SEGENV.allocateData(need)) { SEGMENT.fill(0); FX_DONE; }
  uint32_t *stamp = (uint32_t *)SEGENV.data;
  float *F = (float *)(SEGENV.data + 8);
  float *S = F + P.nf;
  uint32_t *C = (uint32_t *)(S + P.ns);
  const bool first = (SEGENV.call == 0) || (*stamp != P.stamp);
  if (first) { memset(SEGENV.data, 0, need); *stamp = P.stamp; }

  um_data_t *um = cfx_getAudioData();
  const uint8_t *fft = (const uint8_t *)um->u_data[2];
  int bass_, mid_, treb_; cfx_bands(fft, bass_, mid_, treb_);
  const uint8_t kick = fx_lowBeat(um);

  F[SSF_W] = (float)W; F[SSF_H] = (float)H; F[SSF_N] = (float)N; F[SSF_t] = t; F[SSF_dt] = (float)dt;
  F[SSF_sx] = SEGMENT.speed * (1.0f / 255.0f); F[SSF_ix] = SEGMENT.intensity * (1.0f / 255.0f);
  F[SSF_c1] = SEGMENT.custom1 * (1.0f / 255.0f); F[SSF_c2] = SEGMENT.custom2 * (1.0f / 255.0f); F[SSF_c3] = SEGMENT.custom3 * (1.0f / 31.0f);
  F[SSF_o1] = SEGMENT.check1 ? 1.0f : 0.0f; F[SSF_o2] = SEGMENT.check2 ? 1.0f : 0.0f; F[SSF_o3] = SEGMENT.check3 ? 1.0f : 0.0f;
  F[SSF_vol] = *(float *)um->u_data[0] * (1.0f / 255.0f); F[SSF_beat] = kick != 0 ? 1.0f : 0.0f; F[SSF_hit] = kick * (1.0f / 255.0f);
  F[SSF_bass] = bass_ * (1.0f / 255.0f); F[SSF_mid] = mid_ * (1.0f / 255.0f); F[SSF_treb] = treb_ * (1.0f / 255.0f);
  F[SSF_first] = first ? 1.0f : 0.0f; F[SSF_B] = (float)B; F[SSF_cube] = cube ? 1.0f : 0.0f; F[SSF_call] = (float)SEGENV.call;
  for (int i = 0; i < 16; i++) F[SS_BAND0 + i] = fft[i] * (1.0f / 255.0f);

  ssPalReady = false;
  ssRun(P.frame, P.frame + P.frameLen, F, C, S, P.ns, fft);

  // The budget: a program too heavy for the chip runs at half, then a
  // quarter, of the horizontal resolution (each pixel's colour repeated
  // across its neighbours) rather than dragging the whole device down;
  // it climbs back when frames come in under the line. Measured per
  // frame; the stride is kept in the state block.
  static uint8_t stride = 1;
  const uint32_t t0 = micros();
  const int cols = W, rows = H; (void)rows;
  CFX_NET_PREP();
  for (int py = 0; py < H; py++) {
    CFX_NET_ROW(py);
    uint32_t last = 0;
    for (int px = 0; px < W; px++) {
      CFX_NET_SKIP(px);
      if (stride > 1 && (px % stride) != 0) {
        if (is2d) SEGMENT.setPixelColorXY(px, py, last); else SEGMENT.setPixelColor(px, last);
        continue;
      }
      const float u = (W > 1) ? (float)px / (float)(W - 1) : 0.5f;
      const float v = (H > 1) ? (float)py / (float)(H - 1) : 0.5f;
      const float cx = u * 2.0f - 1.0f, cy = 1.0f - v * 2.0f;
      F[SSF_u] = u; F[SSF_v] = v; F[SSF_cx] = cx; F[SSF_cy] = cy;
      F[SSF_px] = (float)px; F[SSF_py] = (float)py;
      // the polar and 3-D registers cost a root and an arc tangent a pixel: only for a program that reads them
      if (P.usesPolar) { F[SSF_r] = sqrtf(cx * cx + cy * cy); F[SSF_ang] = cfx_atan2f(cy, cx); }
      if (P.usesSpace) {
        float nx, ny, nz, X3, Y3, Z3;
        if (cube) {
          cfx_pos(px, py, W, H, B, true, X3, Y3, Z3);
          const float L = sqrtf(X3 * X3 + Y3 * Y3 + Z3 * Z3); const float iL = L > 1e-6f ? 1.0f / L : 1.0f;
          nx = X3 * iL; ny = Y3 * iL; nz = Z3 * iL;
        } else {
          X3 = cx; Y3 = cy; Z3 = 0.0f;
          const float Z = 1.0f - (cx * cx + cy * cy) * 0.5f;
          const float L = sqrtf(cx * cx + cy * cy + Z * Z); const float iL = L > 1e-6f ? 1.0f / L : 1.0f;
          nx = cx * iL; ny = cy * iL; nz = Z * iL;
        }
        F[SSF_X3] = X3; F[SSF_Y3] = Y3; F[SSF_Z3] = Z3; F[SSF_nx] = nx; F[SSF_ny] = ny; F[SSF_nz] = nz;
      }
      const uint32_t c = ssRun(P.pixel, P.pixel + P.pixelLen, F, C, S, P.ns, fft);
      last = c;
      if (is2d) SEGMENT.setPixelColorXY(px, py, c); else SEGMENT.setPixelColor(px, c);
    }
  }
  const uint32_t took = micros() - t0;
  if (took > 40000u && stride < 4) stride *= 2;                 // over 40 ms: coarser
  else if (took < 12000u && stride > 1) stride /= 2;            // well under: finer again
  FX_DONE;
}

static const char _data_FX_MODE_STUDIO_SCRIPT[] PROGMEM = "Studio Script@Speed,Intensity,Custom 1,Custom 2,Custom 3,Check 1,Check 2,Check 3;;!;12;sx=128,ix=128";
static CfxBankReg studio_script_reg(&mode_studio_script, _data_FX_MODE_STUDIO_SCRIPT);
