"""A tiny voxel renderer that gives the parrot real volume.

Each side-view sprite is "inflated" into 3D: a pixel's thickness grows with
its distance from the sprite's outline, so parts get rounded cross-sections
like a balloon. The resulting voxels are ray cast from any angle around the
vertical axis and lit using normals derived from the depth buffer.

Coordinates: x runs right and y down (as in the sprites), z points towards
the viewer of the unrotated side view.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from .sprites import TRANSPARENT

Voxels = dict[tuple[int, int, int], str]

BASE_COLORS = "BDGWKYFP"
# Every base colour comes in three shades (dark, mid, light), each with its
# own single-character pixel key so the 2D pixel tools keep working.
SHADE_KEYS: dict[str, str] = {
    "B": "bB1",
    "D": "dD2",
    "G": "gG3",
    "W": "wW4",
    "K": "kK5",
    "Y": "yY6",
    "F": "fF7",
    "P": "pP8",
}
BASE_OF: dict[str, str] = {key: base for base, keys in SHADE_KEYS.items() for key in keys}

# Light comes from the upper left, in front. y points down, z to the viewer.
_LIGHT = (-0.45, -0.6, 0.66)
_LIGHT_NORM = math.hypot(*_LIGHT)
LIGHT = (_LIGHT[0] / _LIGHT_NORM, _LIGHT[1] / _LIGHT_NORM, _LIGHT[2] / _LIGHT_NORM)
DARK_BELOW = 0.4
LIGHT_ABOVE = 0.8
EDGE_DROP = 2.0
"""Assumed depth fall-off beyond the silhouette, so outlines read as round."""


def base_color(pixel: str) -> str:
    """The base colour key of a (possibly shaded) pixel key."""
    return BASE_OF.get(pixel, pixel)


@dataclass(frozen=True)
class Part:
    """How one sprite is extruded into 3D."""

    radius: float
    """Maximum half-thickness; thinner near the outline."""
    centers: tuple[int, ...] = (0,)
    """z positions of the part's copies, e.g. one wing on each side."""


@lru_cache(maxsize=64)
def inflate(sprite: tuple[str, ...], part: Part) -> tuple[tuple[int, int, int, str], ...]:
    """Voxels ``(x, y, z, colour)`` of ``sprite`` inflated according to ``part``."""
    opaque = [(x, y) for y, row in enumerate(sprite) for x, pixel in enumerate(row) if pixel != TRANSPARENT]
    opaque_set = set(opaque)
    height, width = len(sprite), max(len(row) for row in sprite)
    edge = [(x, y) for x in range(-1, width + 1) for y in range(-1, height + 1) if (x, y) not in opaque_set]

    voxels = []
    for x, y in opaque:
        # Distance to the outline, measured from the pixel's edge.
        distance = min(math.hypot(x - ex, y - ey) for ex, ey in edge) - 0.5
        depth = part.radius - distance
        half = part.radius if depth <= 0 else math.sqrt(max(0.0, part.radius**2 - depth**2))
        extent = max(0, math.floor(half + 0.25))
        for center in part.centers:
            for z in range(center - extent, center + extent + 1):
                voxels.append((x, y, z, sprite[y][x]))
    return tuple(voxels)


def place(voxels: Voxels, part_voxels: Iterable[tuple[int, int, int, str]], dx: int, dy: int) -> None:
    """Add a part's voxels at offset (dx, dy); later parts cover earlier ones."""
    for x, y, z, color in part_voxels:
        voxels[(x + dx, y + dy, z)] = color


def render(voxels: Voxels, angle: float, axis: float, width: int, height: int) -> tuple[str, ...]:
    """Ray cast the voxels seen after turning ``angle`` radians about x = ``axis``.

    Returns ``height`` rows of ``width`` shaded pixel keys.
    """
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    rows: dict[int, list[tuple[int, int, int]]] = {}
    for x, y, z in voxels:
        rows.setdefault(y, []).append((x, y, z))

    depth: list[list[float | None]] = [[None] * width for _ in range(height)]
    color: list[list[str]] = [[TRANSPARENT] * width for _ in range(height)]

    for y, row_voxels in rows.items():
        if not 0 <= y < height:
            continue
        # Rays farther from the axis than any voxel in this row can't hit.
        reach = max(math.hypot(x + 0.5 - axis, z) for x, _, z in row_voxels) + 1
        for sx in range(width):
            u = sx + 0.5 - axis
            if abs(u) > reach:
                continue
            v = math.sqrt(reach * reach - u * u)
            # March from the viewer into the scene; half steps don't skip voxels.
            while v >= -reach:
                rx = u * cos_a - v * sin_a
                rz = u * sin_a + v * cos_a
                hit = voxels.get((math.floor(axis + rx), y, math.floor(rz + 0.5)))
                if hit is not None:
                    depth[y][sx] = v
                    color[y][sx] = hit
                    break
                v -= 0.5

    smooth = _blur(depth)
    return tuple("".join(_shade(color, smooth, x, y) for x in range(width)) for y in range(height))


def _blur(depth: list[list[float | None]]) -> list[list[float | None]]:
    """3x3 average over covered pixels, hiding the voxel grid's depth steps."""
    height, width = len(depth), len(depth[0])
    out: list[list[float | None]] = [[None] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if depth[y][x] is None:
                continue
            values = [
                value
                for ny in range(max(0, y - 1), min(height, y + 2))
                for nx in range(max(0, x - 1), min(width, x + 2))
                if (value := depth[ny][nx]) is not None
            ]
            out[y][x] = sum(values) / len(values)
    return out


def _shade(color: list[list[str]], depth: list[list[float | None]], x: int, y: int) -> str:
    pixel = color[y][x]
    here = depth[y][x]
    if here is None:
        return TRANSPARENT

    def at(nx: int, ny: int) -> float:
        inside = 0 <= ny < len(depth) and 0 <= nx < len(depth[0])
        value = depth[ny][nx] if inside else None
        return here - EDGE_DROP if value is None else value

    gx = (at(x + 1, y) - at(x - 1, y)) / 2
    gy = (at(x, y + 1) - at(x, y - 1)) / 2
    nx, ny, nz = -gx, -gy, 1.0
    brightness = (nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) / math.hypot(nx, ny, nz)
    level = 0 if brightness < DARK_BELOW else 2 if brightness > LIGHT_ABOVE else 1
    return SHADE_KEYS[pixel][level]
