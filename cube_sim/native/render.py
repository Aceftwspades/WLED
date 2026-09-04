"""
Software renderer for the cube view.

No GPU. The cube is five FLAT faces, so each one is a single projective warp of
a B x B image - five vectorised numpy operations per frame rather than a quad
per pixel. That removes OpenGL, a windowing toolkit and a driver surface from
the dependency list, and it happens to be the right choice visually as well:
sampling is nearest-neighbour, so the LED grid stays hard-edged instead of being
smoothed into a texture.

The face table is a transcription of surfacePos() in index.html, which is itself
a transcription of cfx_pos() in cube_fx_common.h. This is the one thing that
must not drift - if the simulator disagrees with the firmware about where a
pixel lives, everything judged here is worthless.
"""
import numpy as np

# (block x, block y, origin, edge along a, edge along b) for the five lit faces.
# From surfacePos(bx, by, a, b) with a, b spanning -1..1 across the face:
#     TOP    ( a, -b,  1)      NORTH  ( a,  1,  b)     SOUTH  ( a, -1, -b)
#     WEST   (-1, -b,  a)      EAST   ( 1, -b, -a)
# Corners are evaluated at (a,b) = (-1,-1), (+1,-1), (+1,+1), (-1,+1), which is
# the same winding the net's pixel block uses, so face-local (u,v) maps straight
# onto the block without a flip anywhere.
def _face(bx, by, fn):
    corners = [fn(a, b) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return dict(bx=bx, by=by, corners=np.array(corners, np.float64))

FACES = [
    _face(1, 1, lambda a, b: (a, -b,  1.0)),   # TOP
    _face(1, 0, lambda a, b: (a,  1.0, b)),    # NORTH
    _face(1, 2, lambda a, b: (a, -1.0, -b)),   # SOUTH
    _face(0, 1, lambda a, b: (-1.0, -b, a)),   # WEST
    _face(2, 1, lambda a, b: (1.0, -b, -a)),   # EAST
]


def _homography(src, dst):
    """3x3 taking src (4x2) onto dst (4x2)."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = np.linalg.solve(np.asarray(A, np.float64), np.asarray(b, np.float64))
    return np.append(h, 1.0).reshape(3, 3)


def _camera(yaw, pitch, dist):
    """World -> view. Cube is +Z up, matching the geometry table above."""
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    eye = np.array([dist * cp * sy, dist * cp * cy, dist * sp])
    fwd = -eye / np.linalg.norm(eye)
    up0 = np.array([0.0, 0.0, 1.0])
    right = np.cross(fwd, up0)
    n = np.linalg.norm(right)
    right = np.array([1.0, 0.0, 0.0]) if n < 1e-6 else right / n
    up = np.cross(right, fwd)
    return eye, np.stack([right, up, -fwd])


def render(net_rgb, B, size, yaw, pitch, dist, fov=38.0, bg=(0, 0, 0)):
    """Draw the cube from the unfolded net image.

    net_rgb : (3B, 3B, 3) uint8 - the same image the flat view shows
    returns : (size, size, 3) uint8
    """
    out = np.zeros((size, size, 3), np.uint8)
    out[:] = bg
    eye, R = _camera(yaw, pitch, dist)
    f = (size * 0.5) / np.tan(np.radians(fov) * 0.5)

    drawn = []
    for fc in FACES:
        c = fc["corners"]
        centre = c.mean(axis=0)
        # Outward normal of a cube face is its own centre direction. Cull when
        # it points away, so at most three faces are ever rasterised.
        if np.dot(centre, centre - eye) >= 0:
            continue
        cam = (c - eye) @ R.T
        if np.any(cam[:, 2] > -0.05):            # behind or through the eye
            continue
        scr = np.stack([size * 0.5 + f * cam[:, 0] / -cam[:, 2],
                        size * 0.5 - f * cam[:, 1] / -cam[:, 2]], axis=1)
        drawn.append((float(np.linalg.norm(centre - eye)), fc, scr))

    # Painter's algorithm: far faces first. With a convex solid and backface
    # culling this is exact, no z-buffer needed.
    for _, fc, scr in sorted(drawn, key=lambda t: -t[0]):
        x0 = max(0, int(np.floor(scr[:, 0].min())))
        x1 = min(size, int(np.ceil(scr[:, 0].max())) + 1)
        y0 = max(0, int(np.floor(scr[:, 1].min())))
        y1 = min(size, int(np.ceil(scr[:, 1].max())) + 1)
        if x1 <= x0 or y1 <= y0:
            continue

        # Screen -> face-local pixel coordinates, applied by inverse mapping so
        # every output pixel is written exactly once and no seams open up.
        src = np.array([[0, 0], [B, 0], [B, B], [0, B]], np.float64)
        try:
            H = _homography(scr, src)
        except np.linalg.LinAlgError:            # degenerate, face edge-on
            continue

        yy, xx = np.mgrid[y0:y1, x0:x1]
        p = np.stack([xx.ravel() + 0.5, yy.ravel() + 0.5, np.ones(xx.size)])
        q = H @ p
        w = np.where(np.abs(q[2]) < 1e-12, 1e-12, q[2])
        u = q[0] / w
        v = q[1] / w
        inside = (u >= 0) & (u < B) & (v >= 0) & (v < B)
        if not inside.any():
            continue
        ui = np.clip(u[inside].astype(np.int32), 0, B - 1)
        vi = np.clip(v[inside].astype(np.int32), 0, B - 1)
        block = net_rgb[fc["by"] * B:(fc["by"] + 1) * B,
                        fc["bx"] * B:(fc["bx"] + 1) * B]
        tgt = out[y0:y1, x0:x1].reshape(-1, 3)
        tgt[inside] = block[vi, ui]
        out[y0:y1, x0:x1] = tgt.reshape(y1 - y0, x1 - x0, 3)
    return out
