"""Curses-based renderer that plays the animation until asked to stop.

Pixels are drawn with the UTF-8 half-block characters, so each character
cell shows two vertically stacked pixels: the upper one as the foreground of
"▀" and the lower one as its background.
"""

from __future__ import annotations

import curses
import time
from dataclasses import dataclass

from . import song
from .audio import Singer
from .frames import SCALE_FACTORS, TRANSPARENT, Frame, build_frame, scale
from .model import SHADE_KEYS

# Base colour -> ((dark, mid, light) xterm-256 colours, 8-colour fallback).
BASE_PALETTE: dict[str, tuple[tuple[int, int, int], int]] = {
    "B": ((25, 33, 75), curses.COLOR_BLUE),
    "D": ((17, 19, 26), curses.COLOR_BLUE),
    "G": ((28, 70, 113), curses.COLOR_GREEN),
    "W": ((249, 254, 231), curses.COLOR_WHITE),
    "K": ((233, 236, 240), curses.COLOR_BLACK),
    "Y": ((178, 220, 227), curses.COLOR_YELLOW),
    "F": ((240, 245, 250), curses.COLOR_WHITE),
    "P": ((125, 168, 211), curses.COLOR_MAGENTA),
}

# Shaded pixel key -> (xterm-256 colour, 8-colour fallback).
COLORS: dict[str, tuple[int, int]] = {
    key: (shades[level], basic)
    for base, (shades, basic) in BASE_PALETTE.items()
    for level, key in enumerate(SHADE_KEYS[base])
}

# Without colour, show the lighting with shading characters.
SHADES: dict[str, str] = {
    key: "▒▓█"[level] for keys in SHADE_KEYS.values() for level, key in enumerate(keys)
}

NOTE_COLORS: tuple[int, ...] = (
    curses.COLOR_RED,
    curses.COLOR_YELLOW,
    curses.COLOR_GREEN,
    curses.COLOR_CYAN,
    curses.COLOR_BLUE,
    curses.COLOR_MAGENTA,
)

UPPER_HALF = "▀"
LOWER_HALF = "▄"
QUIT_KEYS = frozenset({ord("q"), ord("Q"), 27})  # 27 = Esc
HINT = "q: quit  +/-: speed"
MIN_FPS = 1.0
MAX_FPS = 60.0


@dataclass
class Settings:
    fps: float
    color: bool
    duration: float | None = None
    spin: bool = True
    sound: bool = True


class Palette:
    """Lazily allocates curses colour pairs as combinations are needed."""

    def __init__(self) -> None:
        self.enabled = curses.has_colors()
        self._pairs: dict[tuple[int, int], int] = {}
        if not self.enabled:
            return
        curses.start_color()
        try:
            curses.use_default_colors()
            self._default_bg = -1
        except curses.error:
            self._default_bg = curses.COLOR_BLACK
        self._rich = curses.COLORS >= 256

    def _color(self, key: str | None) -> int:
        if key is None:
            return self._default_bg
        rich, basic = COLORS[key]
        return rich if self._rich else basic

    def _attr(self, fg: int, bg: int) -> int:
        number = self._pairs.get((fg, bg))
        if number is None:
            number = len(self._pairs) + 1
            if number >= curses.COLOR_PAIRS:
                return 0  # Out of pairs; degrade gracefully.
            curses.init_pair(number, fg, bg)
            self._pairs[(fg, bg)] = number
        return curses.color_pair(number)

    def pair(self, fg: str | None, bg: str | None) -> int:
        """Attribute for the given pixel keys (``None`` = terminal default)."""
        if not self.enabled:
            return 0
        return self._attr(self._color(fg), self._color(bg))

    def note(self, index: int) -> int:
        if not self.enabled:
            return curses.A_BOLD
        return self._attr(NOTE_COLORS[index % len(NOTE_COLORS)], self._default_bg) | curses.A_BOLD


def _cell(top: str, bottom: str, palette: Palette, color: bool) -> tuple[str, int]:
    """Character and attribute for a cell showing pixels ``top`` over ``bottom``."""
    top_key = None if top == TRANSPARENT else top
    bottom_key = None if bottom == TRANSPARENT else bottom
    if top_key is None and bottom_key is None:
        return " ", 0
    if not color:
        if top_key and bottom_key:
            return SHADES[top_key], 0
        return (UPPER_HALF, 0) if top_key else (LOWER_HALF, 0)
    if top_key is None:
        return LOWER_HALF, palette.pair(bottom_key, None)
    return UPPER_HALF, palette.pair(top_key, bottom_key)


def fit_scale(frame: Frame, rows: int, cols: int) -> int:
    """Largest scale (0 if none) at which the frame, lyrics and hint fit."""
    for factor in sorted(SCALE_FACTORS, reverse=True):
        needed_rows = (frame.height * factor + 1) // 2 + 3
        needed_cols = frame.width * factor + 4
        if needed_rows <= rows and needed_cols <= cols:
            return factor
    return 0


def _draw(
    screen: curses.window,
    frame: Frame,
    lyric: song.SongState | None,
    palette: Palette,
    color: bool,
) -> None:
    screen.erase()
    rows, cols = screen.getmaxyx()
    factor = fit_scale(frame, rows, cols)

    if factor == 0:
        message = "Terminal too small - please enlarge"
        _add(screen, rows // 2, max(0, (cols - len(message)) // 2), message, 0)
        screen.refresh()
        return

    pixels = scale(frame.pixels, factor)
    if len(pixels) % 2:
        pixels += (TRANSPARENT * len(pixels[0]),)
    height = len(pixels) // 2
    width = len(pixels[0])
    top = max(0, (rows - 3 - height) // 2)
    left = (cols - width) // 2

    for y in range(height):
        upper, lower = pixels[2 * y], pixels[2 * y + 1]
        for x in range(width):
            char, attr = _cell(upper[x], lower[x], palette, color)
            if char != " ":
                _add(screen, top + y, left + x, char, attr)

    note_x = left - 2 if frame.note_side == 0 else left + width + 1
    note_y = top + height // 4 + (frame.note_side * 2)
    _add(screen, note_y, note_x, frame.note, palette.note(frame.note_color_index) if color else 0)

    if lyric is not None:
        _draw_lyric(screen, lyric, top + height + 1, cols, palette, color)

    _add(screen, rows - 1, max(0, (cols - len(HINT)) // 2), HINT, curses.A_DIM)
    screen.refresh()


def _draw_lyric(
    screen: curses.window, lyric: song.SongState, y: int, cols: int, palette: Palette, color: bool
) -> None:
    """Karaoke line: the syllable being sung is highlighted."""
    line = lyric.line[:cols]
    x = max(0, (cols - len(line)) // 2)
    _add(screen, y, x, line, curses.A_DIM)
    if lyric.end > lyric.start:
        highlight = curses.A_BOLD | (palette.pair("Y", None) if color else curses.A_REVERSE)
        _add(screen, y, x + lyric.start, line[lyric.start : lyric.end], highlight)


def _add(screen: curses.window, y: int, x: int, text: str, attr: int) -> None:
    """addstr that tolerates writes touching the bottom-right cell."""
    try:
        screen.addstr(y, x, text, attr)
    except curses.error:
        pass


def _loop(screen: curses.window, settings: Settings) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass  # Some terminals cannot hide the cursor; not fatal.

    palette = Palette()
    color = settings.color and palette.enabled
    with Singer(settings.sound) as singer:
        _animate(screen, settings, singer, palette, color)


def _animate(
    screen: curses.window, settings: Settings, singer: Singer, palette: Palette, color: bool
) -> None:
    fps = settings.fps
    started = time.monotonic()
    next_frame = started
    tick = 0

    while True:
        now = time.monotonic()
        if settings.duration is not None and now - started >= settings.duration:
            return

        if now >= next_frame:
            # The beak and lyrics follow the song clock, not the frame rate,
            # so they stay in sync with the audio at any dance speed.
            position = singer.position()
            lyric = None if position is None else song.state_at(position)
            frame = build_frame(
                tick,
                palette_size=len(NOTE_COLORS),
                spin=settings.spin,
                singing=lyric is not None and lyric.singing,
            )
            _draw(screen, frame, lyric, palette, color)
            tick += 1
            # Schedule from the ideal time to avoid drift, but don't try to
            # catch up after a long stall (e.g. the process was suspended).
            next_frame = max(next_frame + 1 / fps, now)

        # Waiting for input doubles as the frame delay.
        screen.timeout(max(0, int((next_frame - time.monotonic()) * 1000)))
        key = screen.getch()
        if key in QUIT_KEYS:
            return
        if key in (ord("+"), ord("=")):
            fps = min(MAX_FPS, fps * 1.25)
        elif key in (ord("-"), ord("_")):
            fps = max(MIN_FPS, fps / 1.25)
        elif key == curses.KEY_RESIZE:
            next_frame = time.monotonic()  # Redraw immediately at the new size.


def run(settings: Settings) -> None:
    """Play the animation. ``curses.wrapper`` restores the terminal on exit."""
    curses.wrapper(_loop, settings)
