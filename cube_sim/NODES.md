# The nodes

What every node, pin and setting does. Numbers are mostly 0..1; a 'turn' is one full circle.
Hover a node or a pin in the editor and the same text appears under the toolbar.

## controls

### Check 1

The first checkbox on the WLED page. Plug it into a Select to switch between two behaviours, or into a Mask to turn a layer on and off.

**Outputs**
- `on` *(bool)*: true when the box is ticked

**Settings**
- `label` *(text)*: the name the checkbox shows
- `default` *(bool)*: ticked to start with

### Check 2

The second checkbox on the WLED page.

**Outputs**
- `on` *(bool)*: true when the box is ticked

**Settings**
- `label` *(text)*: the name the checkbox shows
- `default` *(bool)*: ticked to start with

### Check 3

The third checkbox on the WLED page. On a cube it is taken by 'Flat mode', so prefer the first two.

**Outputs**
- `on` *(bool)*: true when the box is ticked

**Settings**
- `label` *(text)*: the name the checkbox shows
- `default` *(bool)*: ticked to start with

### Colour 1

The primary colour picked on the WLED page.

**Outputs**
- `color` *(color)*: that colour

### Colour 2

The secondary colour picked on the WLED page.

**Outputs**
- `color` *(color)*: that colour

### Colour 3

The tertiary colour picked on the WLED page.

**Outputs**
- `color` *(color)*: that colour

### Custom 1

The third slider on the WLED page, 0..1, with whatever name you give it.

**Outputs**
- `value` *(float)*: the slider's position, 0..1

**Settings**
- `label` *(text)*: the name the slider shows
- `default` *(int)*: where the slider starts, 0..255

### Custom 2

The fourth slider on the WLED page, 0..1, with whatever name you give it.

**Outputs**
- `value` *(float)*: the slider's position, 0..1

**Settings**
- `label` *(text)*: the name the slider shows
- `default` *(int)*: where the slider starts, 0..255

### Custom 3

The fifth slider, 0..1. On the device it has only 32 steps, so use it for choices (a shape, a count), not for anything that should glide.

**Outputs**
- `value` *(float)*: the slider's position, 0..1, in 32 steps

**Settings**
- `label` *(text)*: the name the slider shows
- `default` *(int)*: where the slider starts, 0..31

### Intensity

The Intensity slider on the WLED page, 0..1. Use it for how much - brightness, size, how many. The label you give it is what the page shows.

**Outputs**
- `value` *(float)*: the slider's position, 0..1

**Settings**
- `label` *(text)*: the name the slider shows on the WLED page
- `default` *(int)*: where the slider starts, 0..255

### Speed

The Speed slider on the WLED page, as a number from 0 (left) to 1 (right). Multiply it into a rate (Integrate's rate, a Multiply before Time) so the slider sets how fast things move.

**Outputs**
- `value` *(float)*: the slider's position, 0..1

**Settings**
- `label` *(text)*: the name the slider shows on the WLED page
- `default` *(int)*: where the slider starts, 0..255

## signals

### Audio

What the microphone hears, as numbers 0..1. volume is the overall loudness; bass, mid and treble are the low, middle and high bands; beat is true on the frame a kick lands; hit is how hard it landed. Plug bass into a brightness, beat into a Random hold or Emitters.

**Outputs**
- `volume` *(float)*: overall loudness, 0..1
- `bass` *(float)*: the low band, 0..1
- `mid` *(float)*: the middle band, 0..1
- `treble` *(float)*: the high band, 0..1
- `beat` *(bool)*: true for the frame a kick is detected
- `hit` *(float)*: how hard the kick was, 0..1 (0 between kicks)

### Beat kick

A position that jumps forward on each beat and settles over a few frames - the way a hit should move a pattern. Add its phase to whatever you scroll (a Wave's phase, a Palette index) and the picture lurches on the kick and eases.

**Inputs**
- `beat` *(bool)*: the beat, from Audio
- `throw` *(float)*: how far each beat throws it

**Outputs**
- `phase` *(float)*: the running offset: add it to a position

### Colour

A fixed colour you pick.

**Outputs**
- `color` *(color)*: the colour

**Settings**
- `rgb` *(color)*: the colour

### Delay

Remembers a number for one frame. It is the one node a wire may loop back through: feed it a value and plug its output back into what made that value, and each frame sees last frame's result. For 'only restart the cycle when the cycle is over' and the like.

**Inputs**
- `x` *(float)*: the value to remember

**Outputs**
- `value` *(float)*: what x was last frame (0 on the first)

### Emitters

Drops a thing on the surface each time the trigger fires - up to eight alive at once - and remembers where and how old each is. Plug the beat into trigger and the Shells node reads them: rings spreading from wherever each kick landed.

**Inputs**
- `trigger` *(bool)*: true drops a new one (the beat)
- `x` *(float)*: where to drop it, if not random
- `y` *(float)*: where to drop it
- `z` *(float)*: where to drop it (1 is the lid)
- `tag` *(float)*: a number kept with it - a hue, say (Loudest bin)
- `life` *(float)*: how many seconds each one lives

**Outputs**
- `slots` *(float)*: the list - wire this to Shells
- `count` *(float)*: how many are alive

**Settings**
- `random` *(bool)*: drop each one at a random point on the surface instead of x, y, z

### Envelope

Smooths a jumpy signal. It follows rises quickly (attack) and falls slowly (release), so a bass that flickers becomes a swell that breathes. Put it between Audio and anything that would flicker.

**Inputs**
- `x` *(float)*: the signal to smooth

**Outputs**
- `value` *(float)*: the smoothed signal

**Settings**
- `attack` *(float)*: how fast it rises, in milliseconds
- `release` *(float)*: how fast it falls, in milliseconds

### FFT bin

One of the sixteen frequency bands the microphone is split into, from low (0) to high (15). For a whole spectrum along a coordinate use Spectrum instead.

**Outputs**
- `level` *(float)*: how loud that band is, 0..1

**Settings**
- `bin` *(int)*: which band, 0 (lowest) to 15 (highest)

### Frame count

first is true only on the very first frame, for setting something up once (seeding a Field). count is how many frames have run.

**Outputs**
- `first` *(bool)*: true on the first frame only
- `count` *(float)*: frames since the effect started

### Gravity

Which way is down, as a direction in the cube's own frame. With a motion sensor fitted it is the real down; without one it is straight down, tilted by the two inputs. Feed the direction into Dot 3 with Position to get 'height', or step along it to make things fall.

**Inputs**
- `tilt_x` *(float)*: lean, -1..1, used when there is no sensor
- `tilt_y` *(float)*: lean the other way, -1..1

**Outputs**
- `gx` *(float)*: down's x part
- `gy` *(float)*: down's y part
- `gz` *(float)*: down's z part (-1 is straight down)
- `sensor` *(bool)*: true when a real sensor is supplying it

### Integrate

A number that keeps growing at a rate you set - the way to make a phase, a scroll or an angle that never stops. Plug a Speed slider into rate and you have a clock the slider controls. wrap makes it start over at that value (1 for a phase, 0 to never wrap).

**Inputs**
- `rate` *(float)*: how much to add per second (a slider, a Multiply of one)
- `reset` *(bool)*: true starts it from 0 again (the beat, to restart on a kick)

**Outputs**
- `value` *(float)*: the running total

**Settings**
- `wrap` *(float)*: start over when it reaches this; 0 = never

### Loudest bin

Which of the sixteen frequency bands is loudest right now, as a number from 0 (bass) to 1 (treble), and how loud it is. A hue for whatever the beat drops: kicks come out red, hi-hats blue.

**Outputs**
- `bin` *(float)*: the loudest band, 0..1
- `level` *(float)*: its loudness, 0..1

**Settings**
- `from` *(int)*: only look at bands from this one
- `to` *(int)*: up to this one

### Number

A fixed number you type in. Most pins can be typed straight on the node instead; this is for a value you want to send to several places.

**Outputs**
- `value` *(float)*: the number

**Settings**
- `value` *(float)*: the number

### Random hold

A random number that stays put until the trigger fires, then picks a new one. Feed it the beat and something changes direction, colour or place on every kick and holds in between.

**Inputs**
- `trigger` *(bool)*: true to pick a new random (the beat)

**Outputs**
- `value` *(float)*: the current random, 0..1
- `changed` *(bool)*: true on the frame it picked a new one

### Rising edge

Turns a switch into a tap: true for exactly one frame when its input goes from off to on. Use it when something should happen once per press or per beat, not for as long as the input stays on.

**Inputs**
- `x` *(bool)*: the switch to watch

**Outputs**
- `pulse` *(bool)*: true for one frame when x turns on

### Spectrum

The whole spectrum as a curve you can read anywhere: index 0 is the lowest band, 1 the highest. Feed a coordinate into index and the bands spread across the cube - a graphic equaliser along u, or round the ring. smooth stops it flickering.

**Inputs**
- `index` *(float)*: where to read, 0 (bass) .. 1 (treble); a coordinate spreads the spectrum out

**Outputs**
- `level` *(float)*: how loud it is there, 0..1

**Settings**
- `smooth` *(float)*: 0 = raw, near 1 = very smooth and slow
- `interpolate` *(bool)*: blend between bands rather than stepping

### Spring

A weight on a spring. It is pulled toward target, and a kick sends it swinging: overshoot, swing back, settle. Plug the beat's hit into kick and use the value to tilt or bounce something - it will slosh like liquid rather than snap.

**Inputs**
- `target` *(float)*: where it settles
- `kick` *(float)*: a push - the beat's hit

**Outputs**
- `value` *(float)*: where it is now
- `velocity` *(float)*: how fast it is moving

**Settings**
- `hz` *(float)*: how many swings a second
- `damping` *(float)*: how quickly the swinging dies away, 0 (forever) .. 1

### Time

The clock. t counts seconds since the effect started; feed it into a Wave, a Noise's z, or an Add to make something drift. dt is how long this frame took, for things that move a fixed amount per second.

**Outputs**
- `t` *(float)*: seconds since the effect started
- `dt` *(float)*: this frame's length in milliseconds

### Toggle

A fixed on or off.

**Outputs**
- `on` *(bool)*: the setting

**Settings**
- `on` *(bool)*: on or off

## coords

### Coords

Where this pixel is. u and v run 0..1 across and down the whole logical picture (on a cube, the unfolded net). cx, cy are the same centred (-1..1); r and angle are polar about the centre. The simplest way to make something vary across the strip or panel.

**Outputs**
- `u` *(float)*: across, 0 (left) .. 1 (right)
- `v` *(float)*: down, 0 (top) .. 1 (bottom)
- `cx` *(float)*: across, centred: -1 .. 1
- `cy` *(float)*: up, centred: -1 .. 1
- `r` *(float)*: distance from the centre, 0 .. ~1.4
- `angle` *(float)*: angle round the centre, in radians (-pi .. pi)

### Cube face

Which face this pixel is on, and where on that face - a and b run 0..1 across each face, so the same picture repeats on every face (tiles, sprites). nx, ny, nz is the face's outward normal.

**Outputs**
- `face` *(float)*: 0 east, 1 west, 2 north, 3 south, 4 lid, 5 bottom
- `a` *(float)*: across the face, 0..1
- `b` *(float)*: down the face, 0..1
- `nx` *(float)*: the face's outward direction, x
- `ny` *(float)*: y
- `nz` *(float)*: z

### Cube ring

The cube as a well: 'around' goes once round the walls (0..1), 'depth' goes from the middle of the lid (0), over the rim (0.5), down to the bottom edge (1). Rain falls along depth; a spiral is around plus depth.

**Outputs**
- `around` *(float)*: round the cube, 0..1 (wraps)
- `depth` *(float)*: 0 lid centre, 0.5 rim, 1 bottom edge

### Direction

On a cube, the direction from the middle of the cube out through this pixel (a unit vector, length 1). Because it never sees the folds, anything drawn from it - Noise, Dot 3, Mirror fold - flows over every edge seamlessly. On a flat panel it is a gentle dome.

**Outputs**
- `nx` *(float)*: the direction's x part
- `ny` *(float)*: its y part
- `nz` *(float)*: its z part (1 straight up)

### Pixel

This pixel's whole-number column, row and index. For when you want to count pixels rather than measure in 0..1.

**Outputs**
- `x` *(float)*: column, 0 .. width-1
- `y` *(float)*: row, 0 .. height-1
- `i` *(float)*: index, row * width + column

### Position

This pixel's place in the cube's box, each of x, y, z from -1 to 1, z up, so the lid is z = 1. Use it where a straight line matters (slabs, planes, gravity height); use Direction for angles.

**Outputs**
- `x` *(float)*: -1 (west) .. 1 (east)
- `y` *(float)*: -1 (south) .. 1 (north)
- `z` *(float)*: -1 (bottom) .. 1 (the lid)

### Position to uv

Any point in the box - even one slightly off the surface - to the pixel that shows it. Take Position, add a small step in some direction, and this tells you which pixel is that way: the neighbour a grain of sand falls into.

**Inputs**
- `x` *(float)*: the point's x
- `y` *(float)*: its y
- `z` *(float)*: its z

**Outputs**
- `u` *(float)*: that pixel, across
- `v` *(float)*: that pixel, down

### Ring to uv

The reverse of Cube ring: give it a point as around and depth and it tells you which pixel shows it, as the u, v that Previous at and Field read. Add a little to depth and you are reading the pixel one step down the wall - how fire rises and rain leaves a trail.

**Inputs**
- `around` *(float)*: round the cube, 0..1
- `depth` *(float)*: 0 lid centre .. 1 bottom edge

**Outputs**
- `u` *(float)*: that pixel, across
- `v` *(float)*: that pixel, down

## generate

### Bifurcation

The famous fig-tree diagram of chaos: for each value of c across the picture, where the sequence x -> x*x + c ends up. Read it with u (the c axis) and v (the x axis); narrow the windows to zoom in. Brightness is how often the sequence lands there.

**Inputs**
- `u` *(float)*: across: which c, 0..1 of the window
- `v` *(float)*: down: which x, 0..1 of the window
- `c_lo` *(float)*: the c window's left edge
- `c_hi` *(float)*: its right edge
- `x_lo` *(float)*: the x window's bottom
- `x_hi` *(float)*: its top

**Outputs**
- `density` *(float)*: how often the sequence visits here, 0..1

**Settings**
- `trail` *(float)*: how long visits glow, 0 .. 0.99
- `orbits` *(int)*: how many steps to run each frame

### Bitmap

Pixel art you type: one line per row, a digit for a coloured pixel, a dot for an empty one. Read it with a coordinate and send slot to Colour pick to give each digit a colour.

**Inputs**
- `u` *(float)*: where to read, across, 0..1
- `v` *(float)*: where to read, down, 0..1

**Outputs**
- `slot` *(float)*: the digit there (0..9)
- `on` *(bool)*: false where there is a dot

**Settings**
- `rows` *(text)*: the rows: digits and dots, one row per line

### Hash

A random number that is always the same for the same inputs. Feed it a cell number and every cell gets its own fixed random - a colour per tile, a speed per column. Change seed to reshuffle them all.

**Inputs**
- `x` *(float)*: what to hash (a cell, a column)
- `y` *(float)*: and this
- `seed` *(float)*: reshuffle: a different seed, different randoms

**Outputs**
- `value` *(float)*: the random, 0..1

### Image

A picture file, baked into the effect. Pick the file, choose how many pixels across and down and how many colours, and read it with any coordinate - Cube face's a, b puts it on every face. The device needs no file. Right-click the node to turn it into editable pixel art.

**Inputs**
- `u` *(float)*: where to read, across, 0..1
- `v` *(float)*: where to read, down, 0..1

**Outputs**
- `color` *(color)*: the picture's colour there
- `slot` *(float)*: which of its colours (a number)
- `on` *(bool)*: false where the picture is transparent

**Settings**
- `file` *(file)*: the image file (png, jpg, gif...)
- `width` *(int)*: pixels across
- `height` *(int)*: pixels down
- `colours` *(int)*: how many colours to keep
- `alpha_clear` *(bool)*: treat transparent pixels as off

### Mandelbrot

The Mandelbrot set. Give it a point x, y and it says how quickly that point escapes (0 = at once, 1 = never, it is inside). Scale and offset a coordinate to zoom around the edge. Julia mode draws a Julia set instead, with jx, jy as its constant.

**Inputs**
- `x` *(float)*: the point's x (real part)
- `y` *(float)*: the point's y (imaginary part)
- `jx` *(float)*: the Julia constant's x (Julia mode)
- `jy` *(float)*: the Julia constant's y (Julia mode)

**Outputs**
- `value` *(float)*: 0 (escaped at once) .. 1 (inside the set)

**Settings**
- `iterations` *(int)*: how carefully to look - more shows finer detail, costs more
- `julia` *(bool)*: draw a Julia set instead

### Noise

Smooth random blobs - clouds, plasma, flames. Give it a point (Direction's nx, ny, nz for a seamless cube, or Coords) and it returns 0..1 that varies smoothly from place to place. Plug Time into z to make the blobs drift; raise scale for smaller blobs.

**Inputs**
- `x` *(float)*: where to sample
- `y` *(float)*: where to sample
- `z` *(float)*: where to sample - Time makes it move
- `scale` *(float)*: how many blobs across: bigger = finer

**Outputs**
- `value` *(float)*: the noise, 0..1

### Reaction diffusion

Real chemistry: two substances that spread and react on a small hidden grid, making tendrils, spots and stripes that grow, split and merge - with a memory, so the picture is never the same twice. Read it with any coordinate (Coords u, v; or Cube ring). feed and kill choose the pattern family.

**Inputs**
- `u` *(float)*: where to read, across, 0..1 (wraps)
- `v` *(float)*: where to read, down, 0..1

**Outputs**
- `v` *(float)*: the second substance - the tendrils, 0..1
- `u` *(float)*: the first substance - the background, 0..1

**Settings**
- `feed` *(float)*: 0.03 .. 0.06: how much fuel comes in
- `kill` *(float)*: 0.055 .. 0.065: how fast the pattern dies
- `steps` *(int)*: simulation steps per frame - faster growth, more work
- `seed` *(float)*: how much to start with

### Ripple

Rings spreading from a point, like a drop in water. cx, cy is the centre in the -1..1 picture; phase moves the rings outward; rings is how many.

**Inputs**
- `cx` *(float)*: the centre, across, -1..1
- `cy` *(float)*: the centre, up, -1..1
- `phase` *(float)*: a clock spreads the rings
- `rings` *(float)*: how many rings across the picture

**Outputs**
- `value` *(float)*: the rings, 0..1

### Shells

Spheres growing out of every Emitter: at each pixel, how much of a shell is passing through. Wire Emitters' slots here and Position into x, y, z, and each beat becomes a ring that crosses every edge of the cube as one ring.

**Inputs**
- `slots` *(float)*: from Emitters
- `x` *(float)*: this pixel's position (Position)
- `y` *(float)*: Position's y
- `z` *(float)*: Position's z
- `speed` *(float)*: how fast the shells grow, in cube-widths per second
- `width` *(float)*: how thick a shell is

**Outputs**
- `value` *(float)*: how much shell is here, 0..1
- `tag` *(float)*: the tag of the strongest shell (its colour)
- `age` *(float)*: how old that shell is, in seconds

### Sparkle

Random pixels lit. density is what fraction; change seed (Time through a Floor for steps) to make them twinkle.

**Inputs**
- `density` *(float)*: what fraction of pixels are lit, 0..1
- `seed` *(float)*: a different seed lights different pixels

**Outputs**
- `value` *(float)*: 1 where lit, else 0

### Stripes

Hard-edged bands along a coordinate. count is how many, duty how wide the bright ones are, phase scrolls them.

**Inputs**
- `x` *(float)*: the coordinate to stripe along
- `count` *(float)*: how many stripes
- `phase` *(float)*: slides the stripes
- `duty` *(float)*: how much of each stripe is bright, 0..1

**Outputs**
- `value` *(float)*: 1 in a stripe, else 0

### Torus knot

A looping, twisted tube floating inside the cube, seen from the middle. Feed it Direction and it tells you whether this pixel looks at the tube, how far along the tube that spot is (for stripes), how close to its edge (for shading), and which way its surface faces (for lighting).

**Inputs**
- `nx` *(float)*: the pixel's direction (Direction)
- `ny` *(float)*: Direction's ny
- `nz` *(float)*: Direction's nz
- `tube` *(float)*: how fat the tube is

**Outputs**
- `on` *(float)*: 1 where the tube is seen, else 0
- `along` *(float)*: how far along the tube, 0..1 - stripes
- `edge` *(float)*: 0 at the tube's middle, 1 at its edge
- `Nx` *(float)*: which way the tube's surface faces, x
- `Ny` *(float)*: y
- `Nz` *(float)*: z

**Settings**
- `p` *(int)*: how many times the knot winds round
- `q` *(int)*: how many times it winds through
- `R` *(float)*: the knot's overall size
- `r` *(float)*: the loop's size

### Wave

A repeating wave along its input: sine, triangle, square or saw. Feed a coordinate into x for stripes and a phase (Integrate, or Time times a speed) to scroll them. cycles is how many waves fit in one unit of x.

**Inputs**
- `x` *(float)*: what to wave along - a coordinate
- `phase` *(float)*: slides the wave along; a clock scrolls it
- `cycles` *(float)*: waves per unit of x

**Outputs**
- `value` *(float)*: the wave, 0..1

**Settings**
- `shape` *(choice)*: sine (smooth), triangle (linear), square (on/off), saw (ramp)

## maths

### Abs

Drops the sign: -0.3 becomes 0.3. Distance from zero.

**Inputs**
- `x` *(float)*: any number

**Outputs**
- `result` *(float)*: |x|

### Add

a + b. Offsets a value, or sums two patterns.

**Inputs**
- `a` *(float)*: the first number
- `b` *(float)*: the second number

**Outputs**
- `result` *(float)*: a + b

### Band

A soft bright band around every whole number of x - slabs, bars, rings. sharp makes the bands narrower.

**Inputs**
- `x` *(float)*: in turns
- `sharp` *(float)*: 1 = wide and soft, 10 = thin lines

**Outputs**
- `result` *(float)*: 0..1

### Clamp

Keeps a value between lo and hi.

**Inputs**
- `x` *(float)*: the value to limit

**Outputs**
- `result` *(float)*: x, held between lo and hi

**Settings**
- `lo` *(float)*: the lowest allowed
- `hi` *(float)*: the highest allowed

### Cosine

A smooth 0..1 hump for every whole number of x: 1 at 0, 0 at 0.5, 1 at 1, and so on.

**Inputs**
- `x` *(float)*: in turns: 1 = one full cycle

**Outputs**
- `result` *(float)*: 0..1

### Direction to

A direction in 3-D from two angles: turn round (a), then tilt up (b). Feed clocks in and the direction sweeps about - a slab's normal, a light.

**Inputs**
- `turns_a` *(float)*: round, in turns
- `turns_b` *(float)*: up, in turns (0.25 = straight up)

**Outputs**
- `x` *(float)*: the direction's x
- `y` *(float)*: y
- `z` *(float)*: z

### Divide

a / b (0 when b is 0).

**Inputs**
- `a` *(float)*: the number to divide
- `b` *(float)*: what to divide it by

**Outputs**
- `result` *(float)*: a / b

### Dot 3

How far a point lies along a direction (the dot product). Position against Gravity gives height; Position against a slab's direction gives which slab; Direction against a light gives brightness.

**Inputs**
- `ax` *(float)*: the point's x
- `ay` *(float)*: y
- `az` *(float)*: z
- `bx` *(float)*: the direction's x
- `by` *(float)*: y
- `bz` *(float)*: z

**Outputs**
- `result` *(float)*: the distance along the direction

### Exp

e to the power x. A zoom that shrinks by the same proportion every second is Exp of a clock.

**Inputs**
- `x` *(float)*: any number

**Outputs**
- `result` *(float)*: e^x

### Floor

Rounds down to a whole number. Turns a smooth coordinate into cell numbers.

**Inputs**
- `x` *(float)*: any number

**Outputs**
- `result` *(float)*: x rounded down

### Fract

The part after the decimal point: 2.7 becomes 0.7. Turns a growing number into a 0..1 that wraps - the usual way to make anything repeat.

**Inputs**
- `x` *(float)*: any number

**Outputs**
- `result` *(float)*: x's fraction, 0..1

### Length

Distance from the origin: the size of a 2-D or 3-D vector. Length of (cx, cy) is the radius.

**Inputs**
- `x` *(float)*: the vector's x
- `y` *(float)*: its y
- `z` *(float)*: its z (leave 0 for 2-D)

**Outputs**
- `result` *(float)*: sqrt(x^2 + y^2 + z^2)

### Log

The natural logarithm. log of a radius makes rings that are evenly spaced when zooming.

**Inputs**
- `x` *(float)*: must be positive

**Outputs**
- `result` *(float)*: ln(x)

### Max

The larger of the two. Lays one pattern over another, brightest wins.

**Inputs**
- `a` *(float)*: one value
- `b` *(float)*: the other

**Outputs**
- `result` *(float)*: the larger

### Min

The smaller of the two. Cuts one pattern by another.

**Inputs**
- `a` *(float)*: one value
- `b` *(float)*: the other

**Outputs**
- `result` *(float)*: the smaller

### Mirror fold

A kaleidoscope for the whole cube. Give it a direction and it reflects that direction into one wedge, so whatever you draw from the result is mirrored over the whole solid - 6 to 120 copies depending on the symmetry. Draw after the fold, not before.

**Inputs**
- `x` *(float)*: a direction's x (Direction, perhaps Rotated)
- `y` *(float)*: its y
- `z` *(float)*: its z

**Outputs**
- `x` *(float)*: the folded direction's x
- `y` *(float)*: its y
- `z` *(float)*: its z

**Settings**
- `symmetry` *(choice)*: which mirror set: dihedral n (a pie of n slices), tetrahedral, octahedral (matches the cube), icosahedral (most copies)

### Mix

Slides between two values: t = 0 gives a, t = 1 gives b, halfway gives the average. Crossfades.

**Inputs**
- `a` *(float)*: the value at t = 0
- `b` *(float)*: the value at t = 1
- `t` *(float)*: the slider, 0..1

**Outputs**
- `result` *(float)*: the blend

### Modulo

The remainder after dividing by m, always 0..m. Like Fract but for any period.

**Inputs**
- `x` *(float)*: any number
- `m` *(float)*: the period

**Outputs**
- `result` *(float)*: x wrapped into 0..m

### Multiply

a x b. Scales a value (a slider times a rate), or masks one pattern with another.

**Inputs**
- `a` *(float)*: the first number
- `b` *(float)*: the second number

**Outputs**
- `result` *(float)*: a x b

### Not

Flips a switch: on becomes off.

**Inputs**
- `on` *(bool)*: the switch

**Outputs**
- `result` *(bool)*: the opposite

### Power

x to the power e. With x in 0..1, a high e squeezes a gradient toward 0 (sharp falloff, gloss highlights); e below 1 spreads it.

**Inputs**
- `x` *(float)*: the base, usually 0..1
- `e` *(float)*: the exponent

**Outputs**
- `result` *(float)*: x^e

### Remap

Changes a value's range: what was in_lo..in_hi becomes out_lo..out_hi. The everyday node for turning a 0..1 slider into 'between 2 and 8 stripes'.

**Inputs**
- `x` *(float)*: the value to remap

**Outputs**
- `result` *(float)*: the remapped value

**Settings**
- `in_lo` *(float)*: the input's low end
- `in_hi` *(float)*: the input's high end
- `out_lo` *(float)*: what in_lo becomes
- `out_hi` *(float)*: what in_hi becomes

### Rotate

Turns a pair of coordinates round the origin. Feed a clock into turns and a pattern spins; three of these on x, y, z tumble the whole cube.

**Inputs**
- `x` *(float)*: the point's x
- `y` *(float)*: the point's y
- `turns` *(float)*: how far to turn: 1 = a full circle

**Outputs**
- `x` *(float)*: the turned x
- `y` *(float)*: the turned y

### Select

One of two values, chosen by a switch: b when on, a when off. A checkbox into on and the effect changes behaviour.

**Inputs**
- `on` *(bool)*: the switch
- `a` *(float)*: the value when off
- `b` *(float)*: the value when on

**Outputs**
- `result` *(float)*: a or b

### Sine

A sine wave: -1..1, one full wave per turn of x. (Wave gives 0..1 with more shapes.)

**Inputs**
- `x` *(float)*: in turns

**Outputs**
- `result` *(float)*: -1 .. 1

### Smoothstep

A soft switch: 0 below e0, 1 above e1, an S-curve between. Turns a gradient into a soft edge - the usual way to get 'bright near here, dark elsewhere' without a hard line. Swap e0 and e1 to flip it.

**Inputs**
- `x` *(float)*: the value to soften

**Outputs**
- `result` *(float)*: 0..1

**Settings**
- `e0` *(float)*: where it starts rising
- `e1` *(float)*: where it reaches 1

### Subtract

a - b. A difference, or a distance from a level.

**Inputs**
- `a` *(float)*: the number to subtract from
- `b` *(float)*: the number taken away

**Outputs**
- `result` *(float)*: a - b

### Threshold

A hard switch: on when x reaches 'at'. Gives both a true/false and a 1/0 number.

**Inputs**
- `x` *(float)*: the value
- `at` *(float)*: the level

**Outputs**
- `on` *(bool)*: x >= at
- `value` *(float)*: 1 when on, else 0

## colour

### Blend

Puts one colour on top of another - the layering node. 'over' covers 'under' by amount; 'add' adds light; 'max' keeps the brighter; 'multiply' darkens; 'screen' lightens. Chain Blends to stack layers.

**Inputs**
- `under` *(color)*: the layer below
- `over` *(color)*: the layer on top
- `amount` *(float)*: how much of 'over' shows, 0..1

**Outputs**
- `color` *(color)*: the result

**Settings**
- `mode` *(choice)*: over (cover), add (light adds up), max (brighter wins), min, multiply (darken), screen (lighten)

### Colour pick

One of eight colours you set, chosen by number: 0 gives the first, 1 the second... The palette for a Bitmap's digits, or for a cell number.

**Inputs**
- `index` *(float)*: which colour, 0..7

**Outputs**
- `color` *(color)*: the colour

**Settings**
- `c0` *(color)*: colour 0
- `c1` *(color)*: colour 1
- `c2` *(color)*: colour 2
- `c3` *(color)*: colour 3
- `c4` *(color)*: colour 4
- `c5` *(color)*: colour 5
- `c6` *(color)*: colour 6
- `c7` *(color)*: colour 7

### Combine

Makes a colour from red, green and blue amounts, each 0..1.

**Inputs**
- `r` *(float)*: red, 0..1
- `g` *(float)*: green
- `b` *(float)*: blue

**Outputs**
- `color` *(color)*: the colour

### Drain

Water running downhill over the pixels. Given a height field and a water field, it tells each pixel how much water flows into it from the neighbours that are higher, whether it is a sink (a hollow), and its height. Write the height and the new water back with Field write and you have rivers.

**Outputs**
- `water` *(float)*: the water arriving here this frame
- `sink` *(bool)*: true if nothing around is lower
- `height` *(float)*: this pixel's height, from the field

**Settings**
- `height_field` *(int)*: the field holding heights
- `water_field` *(int)*: the field holding water

### Fade

Dims a colour by keep - the same as Scale, named for what it does after Previous: keep 0.9 and trails fade over about a second.

**Inputs**
- `color` *(color)*: the colour
- `keep` *(float)*: how much survives each frame, 0..1

**Outputs**
- `color` *(color)*: the faded colour

### Field

A hidden number stored per pixel between frames - a simulation's memory (heat, water, sand) kept separate from the colour. This reads last frame's value at any pixel; Field write stores this pixel's new value. Two fields per graph, 0 and 1.

**Inputs**
- `u` *(float)*: which pixel, across, 0..1
- `v` *(float)*: which pixel, down, 0..1

**Outputs**
- `value` *(float)*: the stored number there, from last frame

**Settings**
- `field` *(int)*: which field, 0 or 1

### Field write

Stores a number for this pixel, to be read by Field next frame. The other half of a simulation: compute the new heat, write it here, read it back next frame with Field.

**Inputs**
- `value` *(float)*: this pixel's number for next frame

**Settings**
- `field` *(int)*: which field, 0 or 1

### HSV

A colour from hue, saturation and brightness. h goes round the rainbow (0 red, 0.33 green, 0.67 blue, 1 red again, so it wraps); s 0 is white/grey, 1 full colour; v is brightness.

**Inputs**
- `h` *(float)*: hue, 0..1 round the wheel
- `s` *(float)*: saturation, 0 grey .. 1 vivid
- `v` *(float)*: brightness, 0..1

**Outputs**
- `color` *(color)*: the colour

### Mask

Shows a colour only where the mask is bright: colour times a 0..1 pattern. Noise as the mask makes clouds of that colour.

**Inputs**
- `color` *(color)*: the colour
- `mask` *(float)*: 0 hides it .. 1 shows it

**Outputs**
- `color` *(color)*: the masked colour

### Palette

A colour from the palette chosen on the WLED page. index 0..1 runs through the palette and wraps, so a coordinate plus a clock gives a scrolling rainbow; brightness dims it. This is how most effects get their colour.

**Inputs**
- `index` *(float)*: where in the palette, 0..1 (wraps)
- `brightness` *(float)*: 0 dark .. 1 full

**Outputs**
- `color` *(color)*: the colour

### Palette source

Like Palette, but reads the 'palette source' setting - the colours the audio-reactive palettes are built from - instead of the segment's palette. Falls back to the segment's palette on a build without that usermod.

**Inputs**
- `index` *(float)*: where in it, 0..1 (wraps)
- `brightness` *(float)*: 0 dark .. 1 full

**Outputs**
- `color` *(color)*: the colour

### Previous

This pixel's own colour last frame. Fade it a little and Blend the new picture on top and everything leaves a trail.

**Outputs**
- `color` *(color)*: last frame's colour here

### Previous at

What another pixel showed last frame. Give it a u, v and you read that pixel's colour from the frame before - read the pixel below to make things rise, beside to smear, and feed the result back into the output (through a Fade) for trails.

**Inputs**
- `u` *(float)*: which pixel, across, 0..1
- `v` *(float)*: which pixel, down, 0..1

**Outputs**
- `color` *(color)*: that pixel's colour last frame

### Scale

Dims a colour by a number (1 leaves it, 0.5 halves it, 0 is black).

**Inputs**
- `color` *(color)*: the colour
- `by` *(float)*: how much to keep, 0..1

**Outputs**
- `color` *(color)*: the dimmed colour

### Split

Takes a colour apart into red, green, blue and brightness, each 0..1.

**Inputs**
- `color` *(color)*: the colour to take apart

**Outputs**
- `r` *(float)*: red, 0..1
- `g` *(float)*: green
- `b` *(float)*: blue
- `luma` *(float)*: perceived brightness

## custom

### Colour expression

A node you write yourself, giving a colour: one line of C++, with a, b and the colour 'under' to use. Helpers: gc_hsv(h, s, v), mq_scale(c, 0..255), color_blend(a, b, 0..255), SEGCOLOR(0).

**Inputs**
- `a` *(float)*: a number
- `b` *(float)*: another
- `under` *(color)*: a colour

**Outputs**
- `color` *(color)*: what the expression gives

**Settings**
- `expr` *(text)*: the C++ expression

### Expression

A node you write yourself: one line of C++ giving a number, using a, b, c and the pixel's coordinates (u, v, cx, cy, r, ang, nx, ny, nz, t). For the one calculation the other nodes do not have.

**Inputs**
- `a` *(float)*: a number your expression can use
- `b` *(float)*: another
- `c` *(float)*: another

**Outputs**
- `result` *(float)*: what the expression gives

**Settings**
- `expr` *(text)*: the C++ expression, e.g. sinf(a * 6.283f) * b

## output

### Effect settings

Settings for the effect as a whole: which palette it starts with, whether it is for a strip, a matrix or both, whether it wants audio, and names for the colour pickers. One per graph.

**Settings**
- `palette` *(int)*: the palette id it starts with (11 is Rainbow)
- `dimensions` *(choice)*: where it runs
- `audio` *(choice)*: what it listens to, if anything
- `colours` *(text)*: names for the three colour pickers, comma separated

### Output

The colour this pixel will show. Every graph needs exactly one.

**Inputs**
- `color` *(color)*: the final colour

## graph

### Frame

A titled box to group nodes. Drag it and the nodes inside come along. Not part of the effect.

**Settings**
- `title` *(text)*: the box's title
- `w` *(int)*: width
- `h` *(int)*: height
- `colour` *(color)*: its colour

### Graph input

When this graph is used as a node inside another graph, this is one of that node's input pins. Name it, choose its type, and give it a default for when nothing is wired in.

**Outputs**
- `value` *(float)*: whatever the parent wires in (or the default)

**Settings**
- `name` *(text)*: the pin's name on the outer node
- `type` *(choice)*: number, colour or switch
- `default` *(float)*: the value when unwired

### Graph output

When this graph is used as a node inside another graph, this is one of that node's output pins.

**Inputs**
- `value` *(float)*: what the outer node's pin gives

**Settings**
- `name` *(text)*: the pin's name on the outer node
- `type` *(choice)*: number, colour or switch

### Knot

A bend in a wire, to route it neatly. Changes nothing.

**Inputs**
- `in` *(float)*: any number

**Outputs**
- `out` *(float)*: the same value

### Knot colour

A bend in a colour wire. Changes nothing.

**Inputs**
- `in` *(color)*: any colour

**Outputs**
- `out` *(color)*: the same colour

### Note

A note to yourself on the graph. Not part of the effect.

**Settings**
- `text` *(text)*: the note
