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
6. **Drafts and the effects list.** A file in `effects/` is a draft: it is
   built, and shows in the roster, only while it is the one being edited, so
   trying things does not pile effects into the list. "import to list" (code
   or graph pane) makes it a project effect — always built, in the roster,
   exported; the same button removes it again. "rename" gives the current
   effect (or graph) a new title, file name and identifiers; a renamed
   sub-graph is rewritten in every graph that uses it.

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

What the library reached by rebuilding fifteen of the cube_fx effects as
graphs (`examples/build_examples.py` writes them; `--check` compiles, builds
and runs them; a new project starts with them in `graphs/`):

- **State between frames.** A node definition may name floats it keeps
  (`state`), held in `SEGENV.data`; `$st.name`, `$first`. Integrate (a
  running phase), Envelope (attack/release smoothing), Random hold (a random
  that re-rolls on a trigger - re-aim on the beat), Rising edge, Spectrum
  (the 16 bins, smoothed, read at an index - a spectrum along a coordinate).
  A frame-scope node fed a per-pixel value follows it down to per pixel; a
  stateful one refuses, with a message.
- **Fields.** A number per pixel kept between frames, double-buffered, up to
  two per graph: Field (read last frame's value at any u, v) and Field
  write. Cellular effects - fire, ripples, ageing - keep their simulation
  here instead of bending it through the palette.
- **Cube coordinates.** Position (the -1..1 box), Cube face (which face, and
  a, b on it - tiles per face), Cube ring (the lid-and-walls ruler: around,
  depth) and Ring to uv (its inverse, so a feedback read can step along the
  ring). Previous at reads last frame's colour at any position.
- **Maths.** Floor, Modulo, Cosine, Log, Exp, Band (a soft band around
  every whole number), Dot 3, Rotate, Length, Direction to (a unit vector
  from two angles), Hash (a stable random per cell, column or tile).
- **Events and things.** Emitters (up to eight things dropped on a
  trigger - at a point or at random on the surface - each with a tag and an
  age) and Shells (spherical shells expanding from each through 3-D space:
  the ripple that crosses every fold). Torus knot (a (p, q) knot seen from
  the centre: hit, where along it, how near the rim, the tube's normal).
  Gravity (the IMU's when fitted, else down, tilted by two inputs), Position
  to uv (any point of the box back to the pixel that shows it), Cube face's
  outward normal, Loudest bin, Frame count (first frame, count).
- **The heavy ones.** Mirror fold (a direction reflected into one
  fundamental domain of a finite mirror group - dihedral, tetrahedral,
  octahedral, icosahedral - so a picture is mirrored 6 to 120 times),
  Mandelbrot (escape time, or a Julia set), Drain (watershed drainage on
  the pixel grid over two fields: the water flowing into a pixel from the
  neighbours that drain to it).

The five: **Slab Cut** (Cube Slice - spectrum slabs through the solid at a
tumbling normal), **Cell Weave** (Cube Cell - nested sines over the position,
one axis per band, the fold drawing the walls), **Truchet Cube** (tiles per
face, arcs turned by a hash the beat re-rolls), **Ring Rain** (Matrix Rain
on the ring with no drop state - a hash per column), **Box Fire** (Cube Fire
- a heat field rising up the walls into the lid); then **Maelstrom** (the
log spiral, with the unwind when the kicks stop), **Kaleidoscope** (spin,
fold, cut by drifting planes), **Mandelbrot** (stereographic from the
bottom pole, a breathing zoom at a boundary point), **Watershed** (height
and water fields, Drain, erosion, storms on the beat) and **Moire** (funnel,
warp, two lattices); then **Cube Ripples** (Emitters on the beat, Shells
through the solid, a fading wake), **Cube Chladni** (the nodal surface of a
3-D standing wave, its three mode numbers following three bands),
**Candy Knot** (Torus knot, tumbling, striped, glossy, seamed), **Gyro
Sand** (a falling-sand automaton on a Field, gravity taken along the
surface, grains conserved by having both cells agree) and **Breakout**
(the ball two triangle waves, a paddle that follows it, bricks a Field it
clears - the ball does not bounce off them). Readings of the originals in
nodes, not ports; the ones that were particle systems are shader-style.

Sub-graphs: select some nodes and "fold into sub-graph" (toolbar or the
node's right-click menu) and they become one node. Each wire that crossed the
boundary becomes a pin — a "Graph input" node inside for every incoming one,
a "Graph output" for every outgoing — named after the pin it fed, and the
parent is rewired through the new node. The sub-graph is a file in
`<project>/subgraphs/`, appears under "subgraphs" in the add menus, and can
be dropped into any graph as many times as wanted. "Edit sub-graph" opens it
in place with a back button; a Graph input's name, type and default are edited
on the node, and a stale wire in a parent is dropped when it next opens. A
sub-graph previews on its own: its first colour output stands in for Output.
Compiling inlines the sub-graph wherever it is used — no call, no cost.

Live preview: the "live" checkbox beside "compile + reload" rebuilds after
every edit — a wire, a value on a pin, a param, a new node — once the edits
pause for half a second. The build runs on the worker while the 3-D view
keeps showing the previous one, and the hot swap keeps the sliders, palette
and colours, so the effect changes under the cursor a second or two later.

### Phase 3 — wiring and export

The ledmap. For a matrix WLED's own settings suffice; for the shapes it is a
wiring model — per-face order for a cube, rings for a cylinder, a spiral for a
sphere — with the imported XYZ case taking its order from the file. Export
writes `ledmap.json` and a usermod folder ready to drop into `usermods/`.

### Phase 4 — the scripted runtime

A small interpreter usermod so an effect built in the editor can be sent to a
device over the network and run without a firmware build. Designed after the
composer exists, because the composer's recipe is the natural thing to ship.

## Features remaining

Measured against ComfyUI and Blender's node editor, and an ordinary code
editor. Ticked when done; the order within a group is the order to do them.

### Node editor

- [x] **Undo / redo.** Every mutation pushes a JSON snapshot; Ctrl+Z /
      Ctrl+Y, also in the right-click menu. Drags of one slider or keystrokes
      in one box within a second share a step. History is per open graph.
- [x] **Copy / cut / paste** (Ctrl+C/X/V; "paste here" in the right-click
      menu, copy/cut in a node's). The clipboard is graph JSON held on the
      app, so it works across graphs and into sub-graphs.
- [x] **Search in the add menu** — a box at the top of the right-click menu,
      focused as it opens; matches on name or description, Enter adds the
      first hit, Escape closes.
- [x] **Drop a wire on empty space → add a node** wired to it: the menu
      offers what that output can feed, most useful first, and the chosen
      node lands where the wire was dropped.
- [x] **Insert on wire**: right-click a connected input → "insert on the
      wire" lists what fits between the two ends and splices it in. (Dropping
      a dragged node onto a wire is not possible: the node editor cannot say
      which wire is under the pointer.)
- [x] **Reroute knots**: Knot and Knot colour, narrow pass-through nodes the
      compiler folds away; also offered first by "insert on the wire".
- [x] **Frames** and **notes**: a Frame is a titled, tinted box with a size
      on the node; nodes whose corner is inside move with it. A Note is a
      multi-line text. Neither is compiled.
- [x] **Collapse a node** to its pins (node menu); **node colour** swatches
      in the node menu, ten colours, same set as the wires.
- [x] **Pin preview**: an output pin's menu → "preview this output" builds
      the graph with that pin shown instead of the Output (a colour straight,
      a float or bool as a grey level, 0..1) as a draft named Preview; every
      compile shows the pin until "stop previewing".
- [x] **Validation on the node**: a red outline for what stops the compile
      (a cycle, more than one Output, a missing sub-graph), amber for an
      output that feeds nothing; the message is in the node's menu and the
      status line. Every input has a default, so none is "required".
- [x] **Keyboard**: arrows nudge the selection 10 px (Shift: 1 px); Home
      brings the graph's top-left to the origin. Ctrl+A and true panning are
      not possible: the node editor exposes neither.
- [x] **Zoom** — 50% to 200% in nine steps: the wheel over the editor
      (about the cursor), Ctrl+= / Ctrl+- / Ctrl+0. DearPyGui's node editor
      cannot zoom, so the panel does: every size it lays nodes out with is
      scaled, the editor gets a font and style theme to match (a monospace
      TTF from the system: Consolas, Menlo, DejaVu Sans Mono), and positions
      are scaled on the way in and out so the saved graph never changes.
      The editor's own panning cannot be set from code, only watched, so
      the picture is shifted instead to keep the point under the cursor
      still. Remembered across runs. A custom canvas is no longer needed
      for this; it remains the route to wire styling and thumbnails.
- [x] **Resizable panes**: a splitter between the left pane and the 3-D
      view (one split per layout: both / code / graph) and one before the
      side panel; drag them, remembered across runs in `projects/studio.json`.

### Code editor

- [x] **Open in external editor** — VS Code if `code` is on the path (at
      the line, `-g`), else the system's .cpp association; `"editor"` in
      project.json overrides (a command with `{file}` and `{line}`). The pane
      reloads when the file is saved outside, and "watch" rebuilds too.
- [x] **Click an error to jump to its line** — the external editor opens at
      it, and the line's text shows in the status. The in-app box cannot move
      its own cursor, which is the limit of DearPyGui's text input.
- [x] **Find / replace** — find lists matching lines (click → line);
      replace all.
- [x] **API reference** under the code: `SEGMENT.*`, time, pixels, colour,
      noise, state, audio, cube helpers, metadata; a click copies the snippet
      (the box cannot take an insertion), Ctrl+V pastes it at the cursor.
- [ ] A real editor widget in-app (drawlist-based) — a project in itself;
      only if the external hand-off proves insufficient.

### Project and workflow

- [x] **Multiple projects**: a project picker at the top of the side panel
      lists `projects/`; the box takes a new name or any folder path. The
      last project opened is remembered (`projects/studio.json`) and opens
      next time. Switching applies the project's geometry, effects list and
      graphs and rebuilds the engine for its list.
- [x] **Palette source node**: the colours the palette-source setting names
      (what the audio-reactive palettes draw from), at an index. One small
      firmware addition, `cfxPaletteSourceColor()` in cube_fx_palettes.cpp,
      declared weak by the generated code with the segment's palette as the
      fallback, so the effect builds without that usermod. The audio-reactive
      palettes themselves are ordinary palettes: pick one on the Palette node.
- [x] **Effect metadata in the UI**. Graphs: each control node carries its
      default beside its label, and an "Effect settings" node (one per graph)
      sets the default palette, 1-D / 2-D / both, the audio flag and the
      colour-slot labels; the compiler writes the whole string. Code: a
      Metadata form under the code pane reads the string out of the file by
      field and writes it back.
- [x] **Graph import / export**: "export graph" writes
      `export/<graph>.graph.json` with every sub-graph it reaches and any
      user nodes it uses; "import graph" (file dialog) unpacks one into the
      project, keeping existing sub-graphs of the same name.
- [x] **Export as a deliverable**: `export/` holds `ledmap.json`, a
      `usermod_studio/` folder that builds on its own (effects, the two
      headers, the bank's .cpp, a library.json, a README with the build
      steps), and `studio_export.zip` of the lot. **send ledmap** uploads
      ledmap.json to a device over `/upload` from the address in the side
      panel (remembered per project).
- [x] **Record GIF** works in every layout (the button under the views);
      **screenshot** saves the 3-D view to `export/shots/`. MP4 is not
      offered: it would need ffmpeg on the path for no gain over the GIF.

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
**H** hide the controls, **space** pause. In the graph: **Delete** removes selected nodes,
**Ctrl+Z / Ctrl+Y** undo / redo, **Ctrl+C / X / V** copy, cut, paste, **wheel / Ctrl+= / Ctrl+- / Ctrl+0** zoom. Projects live in `cube_sim/projects/<name>/`;
the default one is created on first run.

## Compatibility rules for this branch

- Firmware changes live in one clearly-marked block per file with a comment
  naming what depends on it, and everything that depends on it must work
  without it.
- The engine shim stays a transcription of WLED, not a reinterpretation. When
  it disagrees with the firmware, the firmware is right.
- Generated code uses only what a stock build has, plus `cube_fx_common.h` when
  a shape needs it, and says so at the top of the file.
