"""Render docs/screenshot.svg: one frame of the app as a terminal window.

The image is drawn from the same frame data and layout the app uses, with
the xterm-256 colours of the curses renderer, so it stays faithful to the
real output. Run with the package importable, e.g. from the repository root:

    PYTHONPATH=src python3 scripts/screenshot.py
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from dancing_parrot import song
from dancing_parrot.frames import build_frame
from dancing_parrot.renderer import COLORS, HIGHLIGHT_KEY, HINT, NOTE_COLORS, hint_x, layout, lyric_line
from dancing_parrot.sprites import TRANSPARENT

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "screenshot.svg"
TICK = 3
"""A frame mid-sway, slightly turned so the parrot's volume shows."""
SONG_TIME = 0.9
"""Seconds into the song; must fall on a sung syllable so the highlight shows."""
COLS, ROWS = 80, 44
CELL_W, CELL_H = 9, 18
"""Size of a character cell; each holds two stacked pixels, so pixels are square."""
PAD, BAR = 16, 32
BACKGROUND, FOREGROUND, DIM = "#1e1e2e", "#cdd6f4", "#6c7086"
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

# xterm's default colours for palette entries 0-15.
BASIC_RGB = (
    "#000000", "#cd0000", "#00cd00", "#cdcd00", "#0000ee", "#cd00cd", "#00cdcd", "#e5e5e5",
    "#7f7f7f", "#ff0000", "#00ff00", "#ffff00", "#5c5cff", "#ff00ff", "#00ffff", "#ffffff",
)  # fmt: skip


def xterm_rgb(index: int) -> str:
    """Hex colour of an xterm-256 palette entry."""
    if not 0 <= index <= 255:
        raise ValueError(f"not an xterm-256 colour: {index}")
    if index < 16:
        return BASIC_RGB[index]
    if index >= 232:
        level = 8 + 10 * (index - 232)
        return f"#{level:02x}{level:02x}{level:02x}"
    index -= 16
    steps = [0 if c == 0 else 55 + 40 * c for c in (index // 36, index // 6 % 6, index % 6)]
    return "#" + "".join(f"{c:02x}" for c in steps)


def main() -> None:
    state = song.state_at(SONG_TIME)
    if not state.singing or state.end <= state.start:
        raise SystemExit(f"SONG_TIME={SONG_TIME} is not on a sung syllable; pick another moment")
    frame = build_frame(TICK, palette_size=len(NOTE_COLORS), singing=state.singing)
    where = layout(frame, ROWS, COLS)
    if where is None:
        raise SystemExit(f"the parrot does not fit in {COLS}x{ROWS}")
    pixels = where.pixels
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
        f'<text x="{svg_w // 2}" y="{BAR // 2 + 5}" fill="{DIM}" text-anchor="middle">dancing-parrot</text>'
    )

    # Pixels, merging horizontal runs of one colour to keep the file small.
    for y, row in enumerate(pixels):
        x = 0
        while x < where.width:
            key = row[x]
            run = 1
            while x + run < where.width and row[x + run] == key:
                run += 1
            if key != TRANSPARENT:
                colour = xterm_rgb(COLORS[key][0])
                out.append(
                    f'<rect x="{origin_x + (where.left + x) * CELL_W}" '
                    f'y="{origin_y + where.top * CELL_H + y * px}" '
                    f'width="{run * CELL_W}" height="{px}" fill="{colour}"/>'
                )
            x += run

    def text(col: int, row: int, content: str, fill: str, bold: bool = False) -> None:
        weight = ' font-weight="bold"' if bold else ""
        out.append(
            f'<text x="{origin_x + col * CELL_W}" y="{origin_y + row * CELL_H + 14}" '
            f'fill="{fill}"{weight} xml:space="preserve">{escape(content)}</text>'
        )

    note = xterm_rgb(NOTE_COLORS[frame.note_color_index % len(NOTE_COLORS)])
    text(where.note_x, where.note_y, frame.note, note, bold=True)

    # One text element with spans, so the highlight lines up in any font.
    line, lyric_x = lyric_line(state, COLS)
    before, sung, after = line[: state.start], line[state.start : state.end], line[state.end :]
    highlight = xterm_rgb(COLORS[HIGHLIGHT_KEY][0])
    out.append(
        f'<text x="{origin_x + lyric_x * CELL_W}" '
        f'y="{origin_y + where.lyric_y * CELL_H + 14}" fill="{DIM}" xml:space="preserve">'
        f'{escape(before)}<tspan fill="{highlight}" font-weight="bold">{escape(sung)}</tspan>'
        f"{escape(after)}</text>"
    )
    text(hint_x(COLS), ROWS - 1, HINT, DIM)

    out.append("</svg>")
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
