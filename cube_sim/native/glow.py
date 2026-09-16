"""Rotating angular-gradient frames around what is active.

The frame is an angular (conic) gradient drawn as four thin strips around a
rectangle plus four wider, fainter ones outside them for a glow, turning
slowly. One texture holds the gradient; each strip is an image quad whose
texture coordinates are the strip's own position rotated about the
rectangle's centre, so the four strips read as one gradient and turning it is
a matter of new coordinates each frame - eight small updates per frame per
rectangle, nothing redrawn.

Two kinds of frame, each with its own gradient: "sel" (the selected nodes)
and "focus" (the pane last clicked in). A gradient is a list of stops,
[position 0..1, r, g, b], read around the circle - cyclic, the last stop
blending back into the first, or mirrored (0 -> 1 -> 0 around the circle),
which makes any palette seamless.

    frames = Frames()                                  # after the viewport exists
    frames.set_gradient("sel", stops, mirror=False)
    frames.update([(x0, y0, x1, y1, clip, alpha, "sel"), ...])   # every frame
"""
import math
import time
import numpy as np
import dearpygui.dearpygui as dpg

# The studio's own: the theme's blue, a violet, a pink, an amber, a mint.
DEFAULT_STOPS = [[0.0, 90, 169, 230], [0.2, 150, 120, 255], [0.4, 255, 110, 170],
                 [0.6, 255, 170, 80], [0.8, 90, 230, 200]]
SIZE = 128
BORDER = 2
GLOW = 5
TURNS_PER_S = 0.1
POOL = {"sel": 8 * 8, "focus": 8}


def sample(stops, t, mirror=False):
    """The gradient's colour at t (0..1), as (r, g, b)."""
    srt = sorted(stops, key=lambda s: s[0])
    if not srt:
        return (255, 255, 255)
    if mirror:
        t = 1.0 - abs(2.0 * (t % 1.0) - 1.0)
        if t <= srt[0][0]:
            return tuple(int(v) for v in srt[0][1:4])
        if t >= srt[-1][0]:
            return tuple(int(v) for v in srt[-1][1:4])
    else:
        t = t % 1.0
        if t < srt[0][0] or t >= srt[-1][0]:
            # across the seam: the last stop round to the first
            a, b = srt[-1], srt[0]
            span = (b[0] + 1.0) - a[0]
            f = ((t - a[0]) % 1.0) / span if span > 1e-6 else 0.0
            return tuple(int(a[i] + (b[i] - a[i]) * f) for i in (1, 2, 3))
    for i in range(len(srt) - 1):
        a, b = srt[i], srt[i + 1]
        if a[0] <= t <= b[0]:
            f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
            return tuple(int(a[k] + (b[k] - a[k]) * f) for k in (1, 2, 3))
    return tuple(int(v) for v in srt[-1][1:4])


def conic(stops, mirror=False):
    """The gradient around a SIZE x SIZE square, as texture floats."""
    ys, xs = np.mgrid[0:SIZE, 0:SIZE]
    ang = (np.arctan2(ys - SIZE / 2 + 0.5, xs - SIZE / 2 + 0.5) / (2 * math.pi)) % 1.0
    # 256 samples round the circle, then a lookup - the sampler is scalar
    table = np.array([sample(stops, k / 256.0, mirror) for k in range(256)], dtype=np.float32) / 255.0
    idx = np.clip((ang * 256).astype(int), 0, 255)
    rgb = table[idx]
    rgba = np.concatenate([rgb, np.ones((SIZE, SIZE, 1), dtype=np.float32)], axis=2)
    return rgba.ravel().tolist()


class Frames:
    def __init__(self):
        if not dpg.does_item_exist("icon_registry"):
            dpg.add_texture_registry(tag="icon_registry")
        self.tex = {}
        self.quads = {}
        self.shown = {}
        with dpg.viewport_drawlist(front=True, tag="glow_front"):
            for kind, n in POOL.items():
                self.tex[kind] = dpg.add_dynamic_texture(SIZE, SIZE, conic(DEFAULT_STOPS), parent="icon_registry")
                z = (0, 0)
                self.quads[kind] = [dpg.draw_image_quad(self.tex[kind], z, z, z, z, show=False) for _ in range(n)]
                self.shown[kind] = 0

    def set_gradient(self, kind, stops, mirror=False):
        if kind in self.tex:
            dpg.set_value(self.tex[kind], conic(stops, mirror))

    @staticmethod
    def _strips(x0, y0, x1, y1):
        b, g = BORDER, GLOW
        yield (x0 - b, y0 - b, x1 + b, y0, 255)
        yield (x0 - b, y1, x1 + b, y1 + b, 255)
        yield (x0 - b, y0, x0, y1, 255)
        yield (x1, y0, x1 + b, y1, 255)
        o = b + g
        yield (x0 - o, y0 - o, x1 + o, y0 - b, 70)
        yield (x0 - o, y1 + b, x1 + o, y1 + o, 70)
        yield (x0 - o, y0 - b, x0 - b, y1 + b, 70)
        yield (x1 + b, y0 - b, x1 + o, y1 + b, 70)

    def update(self, rects):
        """rects: (x0, y0, x1, y1, clip, alpha, kind) - clip a rect to keep
        the strips inside (or None), alpha 0..1 scaling the frame."""
        th = (time.perf_counter() * TURNS_PER_S * 2 * math.pi) % (2 * math.pi)
        c, s = math.cos(th), math.sin(th)
        used = {k: 0 for k in self.quads}
        for (x0, y0, x1, y1, clip, alpha, kind) in rects:
            quads = self.quads.get(kind)
            if quads is None:
                continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            size = max(1.0, max(x1 - x0, y1 - y0))

            def uv(px, py):
                dx, dy = (px - cx) / size, (py - cy) / size
                return (0.5 + 0.3 * (dx * c - dy * s), 0.5 + 0.3 * (dx * s + dy * c))

            for (sx0, sy0, sx1, sy1, a) in self._strips(x0, y0, x1, y1):
                if clip:
                    sx0, sy0 = max(sx0, clip[0]), max(sy0, clip[1])
                    sx1, sy1 = min(sx1, clip[2]), min(sy1, clip[3])
                    if sx1 <= sx0 or sy1 <= sy0:
                        continue
                k = used[kind]
                if k >= len(quads):
                    break
                dpg.configure_item(quads[k], p1=(sx0, sy0), p2=(sx1, sy0), p3=(sx1, sy1), p4=(sx0, sy1),
                                   uv1=uv(sx0, sy0), uv2=uv(sx1, sy0), uv3=uv(sx1, sy1), uv4=uv(sx0, sy1),
                                   color=(255, 255, 255, int(a * alpha)), show=True)
                used[kind] = k + 1
        for kind, quads in self.quads.items():
            for j in range(used[kind], self.shown[kind]):
                dpg.configure_item(quads[j], show=False)
            self.shown[kind] = used[kind]
