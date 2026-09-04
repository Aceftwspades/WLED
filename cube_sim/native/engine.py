"""
Native front end to the compiled effects.

The DLL exports exactly the C surface the browser build exports - it is the same
sim_main.cpp, compiled by clang instead of Emscripten. That surface was written
for JavaScript's ccall and turns out to be precisely what ctypes wants too:
plain C linkage, no structs by value, buffers handed back as pointers.

Nothing here interprets an effect. The effect list, the parameter labels and the
defaults all come out of the metadata string the effect itself registered, so
this cannot drift from what the firmware would do.
"""
import ctypes as C
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DLL = os.path.join(os.path.dirname(HERE), "cubefx.dll")


def parse_meta(s):
    """Split a WLED effect metadata string into name, slider labels, defaults.

    Mirrors parseMeta() in index.html. Format:
        Name@lab1,lab2,...;colours;palette;flags;def1=v1,def2=v2
    """
    at = s.find("@")
    name = s if at < 0 else s[:at]
    rest = "" if at < 0 else s[at + 1:]
    seg = rest.split(";")
    labels = (seg[0] if seg else "").split(",")
    defs = {}
    if len(seg) > 4:
        for kv in seg[4].split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    defs[k.strip()] = int(v)
                except ValueError:
                    pass
    return {"name": name, "labels": labels, "defs": defs}


class Engine:
    KEYS = ("sx", "ix", "c1", "c2", "c3", "o1", "o2", "o3")

    def __init__(self, dll=DLL):
        if not os.path.exists(dll):
            raise FileNotFoundError(
                f"{dll} not found - build it with:  python build.py --native-only")
        self.lib = C.CDLL(dll)
        L = self.lib
        L.simEffectCount.restype = C.c_int
        L.simEffectName.restype = C.c_char_p;  L.simEffectName.argtypes = [C.c_int]
        L.simEffectMeta.restype = C.c_char_p;  L.simEffectMeta.argtypes = [C.c_int]
        L.simInit.argtypes = [C.c_int, C.c_int]
        L.simParams.argtypes = [C.c_int] * 9
        L.simFftPtr.restype = C.POINTER(C.c_uint8)
        L.simAudioSet.argtypes = [C.c_float, C.c_int]
        L.simFrame.argtypes = [C.c_int, C.c_int]
        L.simPixels.restype = C.POINTER(C.c_uint32)

        self.count = L.simEffectCount()
        self.meta = [parse_meta(L.simEffectMeta(i).decode("utf-8", "replace"))
                     for i in range(self.count)]
        self.names = [m["name"] for m in self.meta]

        self.idx = 0
        self.pal = 1
        self.fx = {}
        self.sim_ms = 0
        self.B = 16
        self.resize(16)

    # --- geometry ------------------------------------------------------------
    def resize(self, B):
        self.B = B
        self.cols = self.rows = 3 * B
        self.lib.simInit(self.cols, self.rows)
        self._px = self.lib.simPixels()
        self._fft = self.lib.simFftPtr()
        self.sim_ms = 0
        self.select(self.idx)

    def find(self, needle):
        n = needle.lower()
        for i, name in enumerate(self.names):
            if n in name.lower():
                return i
        raise KeyError(f"no effect matching {needle!r}")

    # --- driving -------------------------------------------------------------
    def select(self, idx, params=None):
        """Pick an effect and reset it, exactly as WLED does on a mode change."""
        self.idx = idx
        m = self.meta[idx]
        # Defaults come from the effect's own metadata, same as the web UI.
        self.fx = {k: m["defs"].get(k, 16 if k == "c3" else 128) for k in self.KEYS[:5]}
        for k in self.KEYS[5:]:
            self.fx[k] = 1 if m["defs"].get(k) else 0
        if params:
            self.fx.update(params)
        # Palette is deliberately NOT taken from the effect's metadata default.
        # The simulator only carries six palettes, where WLED has seventy-odd,
        # so a metadata default like pal=11 lands somewhere unrelated - it maps
        # to Mono here, which renders the effect in greyscale and quietly
        # reports a saturation of zero. The browser page has always driven this
        # from its own selector, defaulting to 1; matching that is what makes
        # the two front ends comparable. Override with --set pal=N.
        self.push()
        self.lib.simSelect()
        self.sim_ms = 0

    def push(self):
        f = self.fx
        self.lib.simParams(f["sx"], f["ix"], f["c1"], f["c2"], f["c3"],
                           f["o1"], f["o2"], f["o3"], self.pal)

    def audio(self, vol, peak):
        self.lib.simAudioSet(C.c_float(vol), int(peak))

    @property
    def fft(self):
        """Writable 16-byte view of the FFT bins the effects read."""
        return np.ctypeslib.as_array(self._fft, shape=(16,))

    def frame(self, dt=23):
        self.sim_ms += dt
        self.lib.simFrame(self.idx, dt)

    def pixels(self):
        """(rows, cols) uint32 0x00RRGGBB, a live view of the engine's buffer."""
        n = self.cols * self.rows
        return np.ctypeslib.as_array(self._px, shape=(n,)).reshape(self.rows, self.cols)

    def rgb(self):
        """(rows, cols, 3) uint8."""
        p = self.pixels()
        return np.dstack(((p >> 16) & 255, (p >> 8) & 255, p & 255)).astype(np.uint8)

    # --- masks ---------------------------------------------------------------
    def lit_mask(self, flat=False):
        """True where a pixel exists. On the cube the four gap corners do not."""
        if flat:
            return np.ones((self.rows, self.cols), bool)
        B = self.B
        yy, xx = np.mgrid[0:self.rows, 0:self.cols]
        return ((xx // B) == 1) | ((yy // B) == 1)

    def lid_mask(self):
        B = self.B
        m = np.zeros((self.rows, self.cols), bool)
        m[B:2 * B, B:2 * B] = True
        return m


def stats(rgb, mask):
    """The same five measures harness.js reports, computed the same way.

    Kept bit-comparable on purpose: these numbers are how every tuning decision
    in this project has been argued, and they are only worth anything if the
    native and browser builds can be held against each other.
    """
    r = rgb[..., 0].astype(np.int32)
    g = rgb[..., 1].astype(np.int32)
    b = rgb[..., 2].astype(np.int32)
    L = (r * 54 + g * 183 + b * 19) >> 8          # same integer luma as the JS
    Lm = L[mask]
    if Lm.size == 0:
        return dict(mean=0.0, sigma=0.0, dark=0.0, bright=0.0, sat=0)
    mx = np.maximum(np.maximum(r, g), b)[mask]
    mn = np.minimum(np.minimum(r, g), b)[mask]
    sel = Lm > 32
    sat = np.where(mx > 0, (mx - mn) * 255.0 / np.maximum(mx, 1), 0)[sel]
    return dict(
        mean=round(float(Lm.mean()), 1),
        sigma=round(float(Lm.std()), 1),
        dark=round(float((Lm < 16).mean() * 100), 1),
        bright=round(float((Lm > 200).mean() * 100), 1),
        sat=int(round(float(sat.mean()))) if sat.size else 0,
    )
