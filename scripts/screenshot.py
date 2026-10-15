"""Render docs/screenshot.svg: one frame of the app as a terminal window.

The image is drawn from the same frame data the app shows, using the
xterm-256 colours of the curses renderer, so it stays faithful to the real
output. Run from the repository root:

    PYTHONPATH=src python3 scripts/screenshot.py
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from dancing_parrot import song
from dancing_parrot.frames import TRANSPARENT, build_frame, scale
from dancing_parrot.renderer import COLORS, HINT

OUTPUT = Path("docs/screenshot.svg")
TICK = 3
"""A frame mid-sway, slightly turned so the parrot's volume shows."""
SONG_TIME = 0.9
"""Seconds into the song: the parrot is singing "dance"."""
FACTOR = 2
COLS, ROWS = 80, 44
CELL_W, CELL_H = 9, 18
"""Size of a character cell; each holds two stacked pixels, so pixels are square."""
PAD, BAR = 16, 32
BACKGROUND, FOREGROUND, DIM = "#1e1e2e", "#cdd6f4", "#6c7086"
HIGHLIGHT, NOTE = "#ffd700", "#ff5f5f"
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def xterm_rgb(index: int) -> str:
    """Hex colour of an xterm-256 palette entry (16-255)."""
    if index >= 232:
        level = 8 + 10 * (index - 232)
        return f"#{level:02x}{level:02x}{level:02x}"
    index -= 16
    steps = [0 if c == 0 else 55 + 40 * c for c in (index // 36, index // 6 % 6, index % 6)]
    return "#" + "".join(f"{c:02x}" for c in steps)


def main() -> None:
    state = song.state_at(SONG_TIME)
    frame = build_frame(TICK, singing=state.singing)
    pixels = scale(frame.pixels, FACTOR)
    height_cells = (len(pixels) + 1) // 2
    width = len(pixels[0])
    # Same layout as the renderer: centred, lyric line below, hint at the bottom.
    top = (ROWS - 3 - height_cells) // 2
    left = (COLS - width) // 2
    origin_x, origin_y = PAD, BAR + PAD
    px = CELL_H // 2

    svg_w = COLS * CELL_W + 2 * PAD
    svg_h = ROWS * CELL_H + BAR + 2 * PAD
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}" font-family="{FONT}" font-size="15">',
        f'<rect width="{svg_w}" height="{svg_h}" rx="10" fill="{BACKGROUND}"/>',
        f'<rect width="{svg_w}" height="{BAR}" rx="10" fill="#313244"/>',
        f'<rect y="{BAR - 10}" width="{svg_w}" height="10" fill="#313244"/>',
    ]
    for i, dot in enumerate(("#f38ba8", "#f9e2af", "#a6e3a1")):
        out.append(f'<circle cx="{20 + 20 * i}" cy="{BAR // 2}" r="6" fill="{dot}"/>')
    out.append(
        f'<text x="{svg_w // 2}" y="{BAR // 2 + 5}" fill="{DIM}" text-anchor="middle">'
        "dancing-parrot</text>"
    )

    # Pixels, merging horizontal runs of one colour to keep the file small.
    for y, row in enumerate(pixels):
        x = 0
        while x < width:
            key = row[x]
            run = 1
            while x + run < width and row[x + run] == key:
                run += 1
            if key != TRANSPARENT:
                colour = xterm_rgb(COLORS[key][0])
                out.append(
                    f'<rect x="{origin_x + (left + x) * CELL_W}" y="{origin_y + top * CELL_H + y * px}" '
                    f'width="{run * CELL_W}" height="{px}" fill="{colour}"/>'
                )
            x += run

    def text(col: int, row: int, content: str, fill: str, bold: bool = False) -> None:
        weight = ' font-weight="bold"' if bold else ""
        out.append(
            f'<text x="{origin_x + col * CELL_W}" y="{origin_y + row * CELL_H + 14}" '
            f'fill="{fill}"{weight} xml:space="preserve">{escape(content)}</text>'
        )

    note_col = left - 2 if frame.note_side == 0 else left + width + 1
    text(note_col, top + height_cells // 4 + frame.note_side * 2, frame.note, NOTE, bold=True)

    # One text element with spans, so the highlight lines up in any font.
    line = state.line
    before, sung, after = line[: state.start], line[state.start : state.end], line[state.end :]
    out.append(
        f'<text x="{origin_x + (COLS - len(line)) // 2 * CELL_W}" '
        f'y="{origin_y + (top + height_cells + 1) * CELL_H + 14}" fill="{DIM}" xml:space="preserve">'
        f'{escape(before)}<tspan fill="{HIGHLIGHT}" font-weight="bold">{escape(sung)}</tspan>'
        f"{escape(after)}</text>"
    )
    text((COLS - len(HINT)) // 2, ROWS - 1, HINT, DIM)

    out.append("</svg>")
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
