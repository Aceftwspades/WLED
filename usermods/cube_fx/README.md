# Cube FX — one file per effect

This folder used to be a single 4,974-line `user_fx_cube.cpp`. It's now split into
one small `.cpp` per effect plus one shared header, so you can work on a single
effect without scrolling past 29 others, and adding a new effect never means
editing a file that already has other people's (or your own past) work in it.

`cube_fx.cpp` is untouched and unrelated — WLED's usermod build compiles
every `.cpp` in the folder into one binary, so this split changes nothing about
how the project builds.

## Layout

```
cube_fx_common.h         shared helpers - #include this, don't duplicate from it
cube_fx_00_cube_axes.cpp
cube_fx_01_cube_ripples.cpp
cube_fx_02_spectral_globe.cpp
...
cube_fx_23_gyro_rain.cpp
```

The number prefix is just a stable sort order, contiguous from 00. It used to
carry the original numbering from the old monolithic file, gaps and all, but
once enough effects had been retired the gaps outnumbered the entries and the
numbers stopped telling you anything. They are renumbered on a cull now; the
prefix is a filing convention, not an identity.

Effects are keyed by NAME everywhere it matters — WLED assigns the runtime
effect id at boot in registration order, and `cube_fx_param_memory.cpp` hashes
the effect name rather than that id for exactly this reason. So renumbering
files never invalidates saved per-effect settings.

Each `cube_fx_NN_name.cpp` is fully self-contained:
- its `mode_x()` function
- its `_data_FX_MODE_X` metadata string
- any sprites/tables/helpers used ONLY by that effect
- its own tiny `Usermod` subclass that calls `strip.addEffect(...)` and its own
  `REGISTER_USERMOD(...)` call

That last part is what makes new effects drop in cleanly: WLED already supports
any number of `Usermod`s registering themselves independently (this codebase
already did that between `cube_fx.cpp` and the old `user_fx_cube.cpp`),
so each effect file registers *itself*. There's no central "add your effect
here" list to touch.

## `cube_fx_common.h`

Holds only things genuinely shared across effects:
- `FX_RET` / `FX_DONE` (0.15 vs 16.x/17-dev signature compatibility)
- the cube net geometry: `cfx_pos`, `cfx_buildCube`, `cfx_isCube`, the
  `CFX_NET_PREP/ROW/SKIP` gap-skipping macros
- audio helpers: `cfx_getAudioData`, `cfx_bands`, `cfx_drive`, `cfx_smoothSpec`,
  `fx_lowBeat`
- frame-timing helpers: `fx_dt`, `fx_dt8`, `fx_step`, `fx_fade`
- `mq_scale` (pixel scale/dim — used by every effect from Question Block on)
- the wall/face surface toolkit (`cfx_buildBand`, `lf_fwd`, `lf_inv`,
  `cfx_buildDirLut`, `cfx_buildCells`) used by Question Block, Tron, Split GEQ,
  Matrix Rain and Breakout

Two things got promoted into this header during the split even though they
weren't textually next to the other shared helpers in the old file:
- `mq_scale` used to be defined inline inside Question Block's file, just
  because Question Block happened to be the first effect that needed it.
- The wall/face toolkit used to sit in a gap between Question Block and Simon
  for the same reason.

If you ever find yourself copy-pasting a helper into a second effect file,
that's the sign it belongs in `cube_fx_common.h` instead — move it there and
delete the copies.

Anything used by exactly ONE effect (game boards, sprite tables, per-effect
`#define`s like `CFX_SRC`, `MZ_RACERS`, `RB_MOVES`, etc.) stays local to that
effect's own file, same as before.

## Adding a new effect

1. Copy `cube_fx_00_cube_axes.cpp` (the smallest one) to
   `cube_fx_NN_your_effect.cpp`, where `NN` is one past the highest prefix in
   the folder listing. Don't hardcode the number from this file - it drifts
   every time an effect is added or the set is renumbered.
2. Write `mode_your_effect()` and `_data_FX_MODE_YOUR_EFFECT`.
3. Update the bottom `Usermod`/`REGISTER_USERMOD` block to match your names.
4. That's it — no other file changes. Nothing else even needs to be recompiled
   except your new file and whatever links the binary.

If your effect needs a helper that already exists in another effect's file
(not `cube_fx_common.h`), don't `#include` that other `.cpp` — either
duplicate the small helper into your file, or, if it's clearly general-purpose,
promote it into `cube_fx_common.h` so both files reference one copy.
