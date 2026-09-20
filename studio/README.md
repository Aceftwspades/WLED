# The WLED Effects Studio has moved

It lives in its own repository now, with its history:

**https://github.com/Aceftwspades/wled-effects-studio**

Releases (the portable Windows app, compiler included) are there too. The
studio still works with this fork: it reads the firmware side from here -
`usermods/cube_fx` (the effect bank, the Studio Script VM, the Ace 3-D
effects) and the PlatformIO environments it flashes - from a checkout
beside it (`../WLED`) or one named by `WLED_ROOT`, and its `gen/` and
`runtime/` are vendored from a pinned commit of this branch
(`WLED_SOURCE.json` there).
