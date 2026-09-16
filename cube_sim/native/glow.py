"""Rotating angular-gradient frames around what is active.

The frame is an angular (conic) gradient - a few clean colours around a
circle - drawn as four thin strips around a rectangle plus four wider, fainter
ones outside them for a glow, turning slowly. One texture holds the gradient;
each strip is an image quad whose texture coordinates are the strip's own
position rotated about the rectangle's centre, so the four strips read as one
gradient and turning it is a matter of new coordinates each frame - eight
small updates per frame per rectangle, nothing redrawn.

    frames = Frames()                     # after the viewport exists
    frames.update([(x0, y0, x1, y1, clip, alpha), ...])   # every frame
"""
import math
import time
import numpy as np
import dearpygui.dearpygui as dpg

# The colours around the circle: the theme's blue, a violet, a pink, an
# amber, a mint, back to blue.
STOPS = [(90, 169, 230), (150, 120, 255), (255, 110, 170), (255, 170, 80), (90, 230, 200)]
SIZE = 128
BORDER = 2
GLOW = 5
TURNS_PER_S = 0.1
MAX_RECTS = 10


def _conic():
    ys, xs = np.mgrid[0:SIZE, 0:SIZE]
    ang = (np.arctan2(ys - SIZE / 2 + 0.5, xs - SIZE / 2 + 0.5) / (2 * math.pi)) % 1.0
    n = len(STOPS)
    pos = ang * n
    i = np.floor(pos).astype(int) % n
    f = (pos - np.floor(pos))[..., None]
    f = f * f * (3 - 2 * f)
    a = np.array(STOPS, dtype=np.float32)[i]
    b = np.array(STOPS, dtype=np.float32)[(i + 1) % n]
    rgb = (a + (b - a) * f) / 255.0
    rgba = np.concatenate([rgb, np.ones((SIZE, SIZE, 1), dtype=np.float32)], axis=2)
    return rgba.ravel().tolist()


class Frames:
    def __init__(self):
        if not dpg.does_item_exist("icon_registry"):
            dpg.add_texture_registry(tag="icon_registry")
        self.tex = dpg.add_static_texture(SIZE, SIZE, _conic(), parent="icon_registry")
        self.quads = []
        with dpg.viewport_drawlist(front=True, tag="glow_front"):
            for _ in range(MAX_RECTS * 8):
                z = (0, 0)
                self.quads.append(dpg.draw_image_quad(self.tex, z, z, z, z, show=False))
        self.shown = 0

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
        """rects: (x0, y0, x1, y1, clip, alpha) - clip a rect to keep the
        strips inside (or None), alpha 0..1 scaling the frame."""
        th = (time.perf_counter() * TURNS_PER_S * 2 * math.pi) % (2 * math.pi)
        c, s = math.cos(th), math.sin(th)
        k = 0
        for (x0, y0, x1, y1, clip, alpha) in rects[:MAX_RECTS]:
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
                if k >= len(self.quads):
                    break
                dpg.configure_item(self.quads[k], p1=(sx0, sy0), p2=(sx1, sy0), p3=(sx1, sy1), p4=(sx0, sy1),
                                   uv1=uv(sx0, sy0), uv2=uv(sx1, sy0), uv3=uv(sx1, sy1), uv4=uv(sx0, sy1),
                                   color=(255, 255, 255, int(a * alpha)), show=True)
                k += 1
        for j in range(k, self.shown):
            dpg.configure_item(self.quads[j], show=False)
        self.shown = k
