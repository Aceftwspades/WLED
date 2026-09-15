# WLED Effect Studio — the playground branch

The simulator grows into an effect editor for any WLED user: write an effect
as C++ in the app and see it on your own geometry within a second, or build one
from a stack of layers with sliders bound to the segment's controls, on a strip,
a matrix, a cube, a sphere, a cylinder, a torus, or a coordinate list you
imported from your own build. What you make exports as a usermod file that
compiles into stock WLED unchanged, plus the ledmap for your wiring.

This branch is allowed to change firmware and other usermods. Every such change
is made as if it will be brought forward: small, isolated, named, and with a
fallback so a dropped patch degrades rather than breaks.

## Decisions taken at the start

| question | decision |
|---|---|
| how effects are authored | **C++ first**, compiled with the clang already in use, hot-reloaded. A scripted runtime that runs the same effect on a device without reflashing is a later phase. |
| what the composer produces | **one generated C++ effect** — a node graph compiles to a single `mode_*()` function, exportable as a usermod file. (Decided as a layer stack at first; changed to a ComfyUI-style graph, since a stack is a graph with one edge per node.) |
| geometries | 1-D strip, 2-D matrix with WLED's own orientation options, 3-D parametric shapes (cube net, sphere, cylinder, torus), and custom 3-D from an XYZ file |
| platform | desktop, cross-platform from the start — the Python / DearPyGui app, with audio capture and toolchain detection per OS |

## How it fits together

```
 geometry.json ─┐                          ┌─ ledmap.json  (for the device)
                ├─► logical segment ───────┤
 (kind+params   │   1-D: n                  └─ XYZ per pixel (for the renderer)
  or XYZ list)  │   2-D: w x h (+ lit mask)
                │
 effects/*.cpp ─┼─► clang: one object per TU, cached ─► link ─► engine_N.dll ─► app loads it
 graphs/*.json  ┘   (a graph is generated to .cpp first)           (old one unloaded)
```

WLED itself has no idea of 3-D. An effect sees a 1-D segment or a 2-D matrix,
and a ledmap turns logical pixels into physical ones. So every 3-D shape here
is a **logical 2-D grid plus a position for each logical pixel** — exactly what
the cube net already is, made general. The renderer draws whatever positions
the geometry hands it; the effect code never knows the difference.

## Phases

### Phase 1 — foundation (done, first pass)

1. **Incremental build.** One object per translation unit, cached on source
   and header mtimes, compiled in parallel; a link step produces a **versioned**
   `engine_<n>.dll` so the running app can load the new one and drop the old
   without the file lock that made "close the sim before building" a rule.
   Editing one effect costs one compile and one link — the second, not the
   ten-second full build.
2. **Geometry model.** `native/geometry.py`: strip, matrix (with serpentine /
   vertical / start-corner as WLED's 2-D page defines them), cube net, sphere,
   cylinder, torus, XYZ file. Each yields the logical segment size, a lit mask,
   and an XYZ per logical pixel. The engine's `simInit` grows a 1-D mode; the
   shim gains the 1-D `Segment` surface (`setPixelColor(i)`, `length()`,
   `is2D()` that can say no) and the 1-D stock effects come in beside the 2-D
   ones.
3. **Point-cloud renderer.** `render.py` becomes a generic projector — every
   LED a disc at its XYZ, orbit camera — so a sphere and a strip render the
   same way the cube does.
4. **Code editor panel.** New / open / save an effect `.cpp`; edit; compile;
   errors listed with line numbers and click-to-line; the effect appears in the
   list on success and is selected. The template a new file starts from is the
   folder's own effect skeleton.
5. **Project files.** A folder with `geometry.json`, `effects/`, `recipes/`, and
   an `export/` that receives the usermod folder and the ledmap.

### Phase 2 — the node graph (done, first pass)

Not a layer stack: a node graph, ComfyUI-style, because layering is just one
node feeding another. `native/nodedefs.py` is the library — controls (the
five sliders, three checkboxes, three colours, each slider node carrying the
label the exported effect will show), signals (time, audio bands, the beat,
a beat-kick that lurches and settles, constants), coordinates (u/v, centred,
polar, the cube's seamless direction), generators (noise, wave, ripple,
sparkle, stripes), maths, colour (palette, HSV, blend with six modes, mask,
Previous for feedback, split/combine), two Expression nodes that take a line
of C++ so a node you have not got can be written on the spot, and Output.

Every node is data: inputs, outputs, params, and a C++ template. A user node
is the same JSON in `<project>/nodes/`. `native/graph.py` compiles a graph to
one ordinary effect file — a topological sort, frame-scope nodes hoisted out
of the pixel loop (a Multiply of two sliders is not 1,280 multiplies), types
checked, defaults for unconnected pins — and it goes through the same build
and reload as a hand-written one. "Open as code" hands the generated file to
the code pane for anything the nodes cannot reach.

### Phase 3 — wiring and export

The ledmap. For a matrix WLED's own settings suffice; for the shapes it is a
wiring model — per-face order for a cube, rings for a cylinder, a spiral for a
sphere — with the imported XYZ case taking its order from the file. Export
writes `ledmap.json` and a usermod folder ready to drop into `usermods/`.

### Phase 4 — the scripted runtime

A small interpreter usermod so an effect built in the editor can be sent to a
device over the network and run without a firmware build. Designed after the
composer exists, because the composer's recipe is the natural thing to ship.

### Alongside

- Cross-platform audio (done): WASAPI loopback on Windows, and any input
  device anywhere through sounddevice — a PulseAudio / PipeWire "Monitor of"
  on Linux, BlackHole on macOS, a microphone anywhere. The source picker is
  in the Audio section.
- True PCM into audioreactive: a ninth `u_data` slot fed from the FFT batch,
  double-buffered, with the effects falling back to the rebuilt waveform when
  the slot is absent. The one firmware-side change on the near horizon; small
  and self-contained by design.

## Running it

```bash
cd cube_sim
pip install dearpygui numpy pillow sounddevice        # pyaudiowpatch on Windows for loopback
python build.py --native-only                          # once; the app rebuilds incrementally
python -m native.app
```

Keys: **G** node graph, **C** code pane, **Q** logical view, **E** 3-D, **W** both,
**H** hide the controls, **space** pause, **Delete** removes selected nodes. Projects live in `cube_sim/projects/<name>/`;
the default one is created on first run.

## Compatibility rules for this branch

- Firmware changes live in one clearly-marked block per file with a comment
  naming what depends on it, and everything that depends on it must work
  without it.
- The engine shim stays a transcription of WLED, not a reinterpretation. When
  it disagrees with the firmware, the firmware is right.
- Generated code uses only what a stock build has, plus `cube_fx_common.h` when
  a shape needs it, and says so at the top of the file.
