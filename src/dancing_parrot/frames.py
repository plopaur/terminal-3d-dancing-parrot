"""Pure frame generation for the dancing blue-and-yellow macaw.

Each frame poses the parrot's body parts (see ``sprites``), builds a 3D
voxel model from them and renders it from the current turning angle (see
``model``). Everything here is side-effect free so it can be unit tested
without a terminal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from .model import Part, Voxels, inflate, place, render
from .sprites import BODY, FEET, HEAD, HEAD_SINGING, TAIL, TRANSPARENT, WING_FOLDED, WING_RAISED

NOTES = ("♪", "♫", "♬", "♩")

CANVAS_WIDTH = 32
CANVAS_HEIGHT = 38
ORIGIN_X = 8
"""Column of the sprites' left edge, chosen so the spin axis is centred."""

SPIN_AXIS = ORIGIN_X + 8.0
"""Vertical axis the parrot spins around: the middle of its body."""

SWAY_AMPLITUDE = 2
"""Maximum number of pixels the head moves left or right."""

SWAY_PERIOD = 12
"""Number of ticks for one full left-right-left sway."""

STEP_PERIOD = 3
"""Number of ticks each foot and wing position is held."""

DANCE_TICKS = 48
"""Ticks of swaying before each spin (a multiple of SWAY_PERIOD, so the
parrot is upright when the spin starts)."""

SPIN_TICKS = 16
"""Ticks for one full 360 degree turn."""

TWIST = 0.35
"""Radians the parrot twists left and right while dancing, to show depth."""

ANIMATION_PERIOD = math.lcm(DANCE_TICKS + SPIN_TICKS, STEP_PERIOD * 4)
"""Ticks after which the whole animation repeats exactly."""

BODY_RADIUS = 4.5
"""Half the body's thickness; wings sit just outside it."""

# How each sprite becomes 3D. Beak and tail are narrow, wings are thin
# panels on both sides of the body and the two legs are separate.
HEAD_PART = Part(radius=4.0)
BEAK_PART = Part(radius=1.5)
BODY_PART = Part(radius=BODY_RADIUS)
TAIL_PART = Part(radius=1.5)
WING_PART = Part(radius=1.0, centers=(-4, 4))
WING_RAISED_PART = Part(radius=1.0, centers=(-5, 5))
FEET_PART = Part(radius=0.5, centers=(-2, 2))

BEAK_COLUMN = 14
"""Black (and tongue) pixels from this column on are the beak, not face markings."""


def _split_head(sprite: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separate the beak from the head so it can be modelled narrower."""
    head, beak = [], []
    for row in sprite:
        head_row, beak_row = "", ""
        for x, pixel in enumerate(row):
            is_beak = pixel in "KP" and x >= BEAK_COLUMN
            head_row += TRANSPARENT if is_beak else pixel
            beak_row += pixel if is_beak else TRANSPARENT
        head.append(head_row)
        beak.append(beak_row)
    return tuple(head), tuple(beak)


HEADS = {False: _split_head(HEAD), True: _split_head(HEAD_SINGING)}
"""(head, beak) sprites keyed by whether the beak is open."""


@dataclass(frozen=True)
class Frame:
    """A single frame: a rectangular pixel grid plus a floating music note.

    ``note_side`` is 0 for left of the parrot and 1 for right.
    """

    pixels: tuple[str, ...]
    note: str
    note_side: int
    note_color_index: int

    @property
    def width(self) -> int:
        return len(self.pixels[0]) if self.pixels else 0

    @property
    def height(self) -> int:
        return len(self.pixels)


def _sway_offset(tick: int, weight: float) -> int:
    """Horizontal offset at ``tick`` for a layer that sways by ``weight``."""
    phase = math.sin(2 * math.pi * tick / SWAY_PERIOD)
    return round(SWAY_AMPLITUDE * phase * weight)


@lru_cache(maxsize=ANIMATION_PERIOD * 2)
def _pixels(position: int, step: int, spin: bool, singing: bool) -> tuple[str, ...]:
    """The rendered parrot; pure function of where we are in the dance."""
    spinning = spin and position >= DANCE_TICKS

    # Squat one pixel on every other step; the feet stay planted.
    bob = step % 2
    sway_tick = 0 if spinning else position
    head_x = ORIGIN_X + _sway_offset(sway_tick, 1.0)
    body_x = ORIGIN_X + _sway_offset(sway_tick, 0.5)
    # Keep the wings tucked in while spinning.
    raised = step % 2 == 1 and not spinning

    voxels: Voxels = {}
    # Back to front, so nearer parts overwrite those behind them.
    place(voxels, inflate(TAIL, TAIL_PART), body_x, 21 + bob)
    place(voxels, inflate(BODY, BODY_PART), body_x, 9 + bob)
    place(voxels, inflate(FEET[step % len(FEET)], FEET_PART), ORIGIN_X, 23)
    if raised:
        place(voxels, inflate(WING_RAISED, WING_RAISED_PART), body_x, 6 + bob)
    else:
        place(voxels, inflate(WING_FOLDED, WING_PART), body_x, 10 + bob)
    head, beak = HEADS[singing]
    place(voxels, inflate(head, HEAD_PART), head_x, bob)
    place(voxels, inflate(beak, BEAK_PART), head_x, bob)

    if spinning:
        angle = 2 * math.pi * (position - DANCE_TICKS) / SPIN_TICKS
    else:
        # Twist against the sway; zero at the start of each spin.
        angle = -TWIST * math.sin(2 * math.pi * position / (2 * SWAY_PERIOD))
    return render(voxels, angle, SPIN_AXIS, CANVAS_WIDTH, CANVAS_HEIGHT)


def build_frame(
    tick: int, *, palette_size: int = 6, spin: bool = True, singing: bool = False
) -> Frame:
    """Build the frame shown at animation step ``tick`` (any integer >= 0).

    The dance alternates ``DANCE_TICKS`` of swaying with a ``SPIN_TICKS``
    long 360 degree turn, unless ``spin`` is false. ``singing`` opens the beak.
    """
    if tick < 0:
        raise ValueError("tick must be non-negative")
    if palette_size < 1:
        raise ValueError("palette_size must be at least 1")

    step = tick // STEP_PERIOD
    position = tick % (DANCE_TICKS + SPIN_TICKS) if spin else tick % DANCE_TICKS
    return Frame(
        pixels=_pixels(position, step % 4, spin, singing),
        note=NOTES[step % len(NOTES)],
        note_side=step % 2,
        note_color_index=(tick // 2) % palette_size,
    )


def _scale2x(pixels: tuple[str, ...]) -> tuple[str, ...]:
    """Scale2x (EPX): double the size, smoothing diagonal edges."""
    h, w = len(pixels), len(pixels[0])
    out: list[str] = []
    for y in range(h):
        top: list[str] = []
        bottom: list[str] = []
        for x in range(w):
            e = pixels[y][x]
            b = pixels[y - 1][x] if y > 0 else e
            h_ = pixels[y + 1][x] if y < h - 1 else e
            d = pixels[y][x - 1] if x > 0 else e
            f = pixels[y][x + 1] if x < w - 1 else e
            if b != h_ and d != f:
                top += [d if d == b else e, f if b == f else e]
                bottom += [d if d == h_ else e, f if h_ == f else e]
            else:
                top += [e, e]
                bottom += [e, e]
        out += ["".join(top), "".join(bottom)]
    return tuple(out)


def _scale3x(pixels: tuple[str, ...]) -> tuple[str, ...]:
    """Scale3x (AdvMAME3x): triple the size, smoothing diagonal edges."""
    h, w = len(pixels), len(pixels[0])

    def at(y: int, x: int) -> str:
        return pixels[min(max(y, 0), h - 1)][min(max(x, 0), w - 1)]

    out: list[str] = []
    for y in range(h):
        rows: list[list[str]] = [[], [], []]
        for x in range(w):
            a, b, c = at(y - 1, x - 1), at(y - 1, x), at(y - 1, x + 1)
            d, e, f = at(y, x - 1), at(y, x), at(y, x + 1)
            g, h_, i = at(y + 1, x - 1), at(y + 1, x), at(y + 1, x + 1)
            if b != h_ and d != f:
                rows[0] += [
                    d if d == b else e,
                    b if (d == b and e != c) or (b == f and e != a) else e,
                    f if b == f else e,
                ]
                rows[1] += [
                    d if (d == b and e != g) or (d == h_ and e != a) else e,
                    e,
                    f if (b == f and e != i) or (h_ == f and e != c) else e,
                ]
                rows[2] += [
                    d if d == h_ else e,
                    h_ if (d == h_ and e != i) or (h_ == f and e != g) else e,
                    f if h_ == f else e,
                ]
            else:
                for row in rows:
                    row += [e, e, e]
        out += ["".join(row) for row in rows]
    return tuple(out)


SCALE_FACTORS = (1, 2, 3, 4, 6)
"""Supported factors: products of the 2x and 3x pixel-art scalers."""


@lru_cache(maxsize=512)
def scale(pixels: tuple[str, ...], factor: int) -> tuple[str, ...]:
    """Enlarge a pixel grid by ``factor`` (one of ``SCALE_FACTORS``).

    Uses Scale2x/Scale3x rather than plain pixel repetition, so curves and
    diagonals are drawn with finer steps instead of growing blockier.
    """
    if factor not in SCALE_FACTORS:
        raise ValueError(f"factor must be one of {SCALE_FACTORS}")
    while factor % 3 == 0:
        pixels, factor = _scale3x(pixels), factor // 3
    while factor % 2 == 0:
        pixels, factor = _scale2x(pixels), factor // 2
    return pixels
