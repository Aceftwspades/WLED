# Screen debugging tools

Test modes for `usermods/cube_fx/ace_ui_screen.cpp`. **Not compiled** unless you
ask for them — this directory is outside `usermods/`, so PlatformIO never looks
at it, and the usermod only includes the header when the flag is set.

```ini
build_flags = ${env:esp32s3dev_16MB_opi.build_flags}
  -D AUI_SCREEN_DEBUG=1
```

Six checkboxes then appear under *Settings → Usermods → AceUI-Screen*. Each
returns early from `loop()`, so nothing else touches the panel while one runs.
Turn them all off when you're done — several of them deliberately stop the UI
drawing.

## Why these exist

A 4-wire SPI panel cannot be asked anything. No MISO, no ACK, no status
register — the only output the entire system has is the glass. So when a panel
is dark, every layer is equally suspect: wiring, bus, addressing, init, buffer,
flush, power. Reasoning about which is broken does not work. Each of these
narrows it to one.

## The tests, in the order worth running them

| toggle | what it proves |
|---|---|
| `selfTest` | Blinks `0xA5` / `0xA4` — "all segments on" and "show RAM". Both are **commands** and need no data path. Blinking means the panel hears commands at all, which a dark screen cannot tell you. |
| `dcdcKick` | Flushes to a command boundary, then sends the whole register set by hand — both controllers' power commands, multiplex, contrast, display on. Repairs a live panel with no reboot. Lights up ⇒ the init was the fault, not the wiring. |
| `resetHold` | Holds RES low and nothing else. A connected reset blanks the panel instantly and keeps it blank. A panel that carries on is not wired to that GPIO. |
| `pageTest` | A staircase written with raw page-select commands and data — no u8g2 buffer, no `DrawTile`, no `x_offset`, no diff, no flush. Eight bars ⇒ the controller honours page addressing and every layer below the library is sound. |
| `rowTest` | The same staircase through u8g2's buffer and our flush. Compare with `pageTest`: clean there and broken here ⇒ the fault is in the library or our code, nowhere near the hardware. |
| `fullRefresh` | Whole panel via `sendBuffer()` instead of changed rows. Bisects "our diff is wrong" from "everything is wrong". Slow on purpose — 1024 bytes in one go. |

## What stayed in the firmware

The counters are **not** here. `Panel draw` (drawn / sent / deferred) and
`Panel pins` (DC / CS / RST write counts) live in the usermod, because they cost
an increment and they answer the two questions that come up first: *is the
software driving DC at all*, and *did anything actually reach the panel*.

## What this was written for

A 1.3" SH1106 that would only light after being fed garbage by a deliberately
mis-wired boot. The tests proved, in order, that commands were heard, that the
reset line was real, that page addressing worked, and that the entire transport
was innocent — which is what made it possible to stop suspecting the hardware.

The actual faults were both software switching the display off on a timer:

- `deepDim` stepping Vcomh to `0x00`, which on this glass is not dim but
  **invisible**, ten seconds after every boot
- the idle sleep timer keying off `lastInputMs`, which only ever moves on
  encoder events — with no knob fitted the panel slept after 30 s and nothing
  could wake it

Both are fixed and defaulted safe. A third real bug turned up on the way: u8g2's
`SH1106_128X64_NONAME` driver sends the **SSD1306** init sequence, whose
charge-pump line its own comment flags as wrong for SH1106, so the SH1106's
DC-DC converter is never enabled. The usermod's SH1106 option uses the Winstar
variant instead, which carries `0xAD 0x8B` and a pump-voltage setting.
