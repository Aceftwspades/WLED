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
- [ ] **Zoom / fit-to-view.** DearPyGui's node editor cannot zoom. The fix is
      a custom-drawn canvas, which would also allow wire styling and
      thumbnails. A structural decision: not now, but before the node UI
      accumulates much more that would have to be rewritten.

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
- [ ] **Effect metadata in the UI**: default slider values, default palette,
      the flags string — hand-edited in the generated file today.
- [ ] **Graph import / export** as one JSON carrying the sub-graphs it uses,
      so graphs can be traded.
- [ ] **Export as a deliverable**: zip of the usermod folder, ledmap and a
      README of build flags; **send ledmap to device** over the JSON API.
- [ ] **Record GIF / MP4** from the graph pane; screenshot to the project.

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
**Ctrl+Z / Ctrl+Y** undo / redo, **Ctrl+C / X / V** copy, cut, paste. Projects live in `cube_sim/projects/<name>/`;
the default one is created on first run.

## Compatibility rules for this branch

- Firmware changes live in one clearly-marked block per file with a comment
  naming what depends on it, and everything that depends on it must work
  without it.
- The engine shim stays a transcription of WLED, not a reinterpretation. When
  it disagrees with the firmware, the firmware is right.
- Generated code uses only what a stock build has, plus `cube_fx_common.h` when
  a shape needs it, and says so at the top of the file.
