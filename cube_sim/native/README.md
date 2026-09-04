# Native simulator — phase 1

The engine, headless. No window yet; that is phase 2.

This exists because the browser build could not do two things: reach the system
audio properly, and keep time. `getDisplayMedia` is the only route a page has to
the speakers — a picker, a permission prompt, and no control over buffering —
and `requestAnimationFrame` is throttled whenever the tab is not frontmost,
which silently invalidated measurements more than once.

## Build

```
python build.py                 # both targets
python build.py --native-only   # just cubefx.dll
python build.py --wasm-only     # just the browser build
```

Requires the **MSVC Build Tools** (for headers and import libraries) and the
clang that already ships inside **emsdk**. Nothing else to install.

Compiled with clang rather than MSVC deliberately. `CFX_NET_PREP` declares
`uint8_t _outCol[cols]` — a variable-length array, a GCC/clang extension MSVC
has never supported and rejects in every effect that renders. The choice was to
change firmware to suit a host compiler, or use a host compiler that takes the
firmware as written. The second is the only one compatible with the point of
this tool.

## Use

```
python -m native.cli --list
python -m native.cli --measure "spectral fountain" --ms 25000
python -m native.cli --measure soap --sweep c3=50,120,210
python -m native.cli --measure "black hole" --set sx=200,o1=1 --faceB 8
python -m native.cli --snapshot "spectral wormhole" --at 6000,14000 --scale 6 --out shot
python -m native.cli --live 10
```

`--measure` reports the same five figures the browser harness reports — mean,
sigma, dark %, bright %, saturation — over all lit pixels and over the lid
alone, plus **swing**: the standard deviation of each measure *across* the run.
Swing is how consistent an effect is over time, as opposed to how much structure
it has in any one frame; the two are independent and both matter.

`--live` prints band levels from the system output, to check the loopback path.

## Parity with the browser build

Both targets compile the same `sim_main.cpp` and the same effect sources, and
`native/synth.py` is a line-for-line port of the page's audio generator, so a
measurement taken here is directly comparable with one taken there. Verified:

| effect | metric | native | browser |
|---|---|---|---|
| Spectral Fountain, 12 s | mean / σ / dark / sat | 52.7 / 49.0 / 35.2 / 168.1 | 52.7 / 49.0 / 35.2 / 168.1 |
| Ace 3-D Soap, 25 s | mean / σ / dark / sat | 66.2 / 48.9 / 24.5 / 163.1 | 66.2 / 48.9 / 24.5 / 163.1 |

Identical to the last decimal, which also confirms the two builds agree on the
float paths (`sinf`/`cosf`/`sqrtf` differ between C libraries in principle).

**Re-run this after any change to the shim or the build.** It is the check that
lets the browser build eventually be retired, and it is only meaningful while
both still exist.

## Gotcha worth knowing

Palette is **not** taken from an effect's metadata default. The simulator
carries six palettes where WLED has seventy-odd, so a default like `pal=11`
lands somewhere unrelated — it maps to Mono here, rendering the effect in
greyscale and reporting a saturation of zero. The browser page has always driven
this from its own selector, defaulting to 1, and the native side matches that.
Override with `--set pal=N`.
