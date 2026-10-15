import pytest

from dancing_parrot.frames import (
    ANIMATION_PERIOD,
    DANCE_TICKS,
    NOTES,
    SPIN_TICKS,
    SWAY_PERIOD,
    TRANSPARENT,
    build_frame,
    scale,
)
from dancing_parrot.model import SHADE_KEYS, base_color

ALLOWED_PIXELS = set("".join(SHADE_KEYS.values()) + TRANSPARENT)


def _colors(pixels: tuple[str, ...]) -> str:
    """Pixels reduced to their base colours, ignoring the lighting."""
    return "".join(base_color(p) for p in "".join(pixels))


@pytest.mark.parametrize("tick", range(ANIMATION_PERIOD))
def test_frames_have_constant_shape(tick: int) -> None:
    first = build_frame(0)
    frame = build_frame(tick)
    assert frame.height == first.height
    assert {len(row) for row in frame.pixels} == {first.width}


@pytest.mark.parametrize("tick", range(ANIMATION_PERIOD))
def test_only_known_colors(tick: int) -> None:
    assert set("".join(build_frame(tick).pixels)) <= ALLOWED_PIXELS


@pytest.mark.parametrize("tick", range(ANIMATION_PERIOD))
def test_parrot_never_touches_canvas_edge(tick: int) -> None:
    # Touching the edge would mean a sprite may have been clipped.
    pixels = build_frame(tick).pixels
    assert set(pixels[0][0] + pixels[0][-1]) == {TRANSPARENT}
    assert all(row[0] == row[-1] == TRANSPARENT for row in pixels)


def test_parrot_is_blue_and_yellow() -> None:
    text = _colors(build_frame(0).pixels)
    assert text.count("B") + text.count("D") > 50
    assert text.count("Y") > 50


def test_animation_loops() -> None:
    for tick in range(ANIMATION_PERIOD):
        assert build_frame(tick).pixels == build_frame(tick + ANIMATION_PERIOD).pixels


def _facing(pixels: tuple[str, ...]) -> str:
    """Which side the beak (black pixels in the head rows) is on."""
    head = _colors(pixels[:10])
    columns = [i % len(pixels[0]) for i, p in enumerate(head) if p == "K"]
    centre = len(pixels[0]) / 2
    return "right" if sum(columns) / len(columns) > centre else "left"


def _row_width(pixels: tuple[str, ...], y: int) -> int:
    row = pixels[y]
    return len(row.strip(TRANSPARENT))


BELLY_ROW = 16


def test_spin_turns_all_the_way_round() -> None:
    frames = [build_frame(DANCE_TICKS + i).pixels for i in range(SPIN_TICKS)]
    assert _facing(frames[0]) == "right"
    assert _facing(frames[SPIN_TICKS // 2]) == "left"
    # Seen from behind: almost all blue (a pixel or two of face or belly may
    # peek past the outline).
    back = _colors(frames[SPIN_TICKS // 4])
    assert back.count("Y") + back.count("W") <= 3
    assert back.count("B") + back.count("D") > 200
    # Seen from the front: the yellow belly, framed by blue on both sides.
    front_row = _colors((frames[SPIN_TICKS * 3 // 4][BELLY_ROW],)).strip(TRANSPARENT)
    assert "YYYYY" in front_row
    assert front_row[0] in "BD" and front_row[-1] in "BD"
    # Facing right again once the turn completes.
    after = build_frame(DANCE_TICKS + SPIN_TICKS).pixels
    assert _facing(after) == "right"


def test_parrot_has_volume() -> None:
    # A flat sprite would shrink to a sliver when seen edge-on; a 3D body
    # stays about as wide from the front as from the side.
    side = build_frame(DANCE_TICKS).pixels
    front = build_frame(DANCE_TICKS + SPIN_TICKS * 3 // 4).pixels
    assert _row_width(front, BELLY_ROW) >= 0.8 * _row_width(side, BELLY_ROW)


def test_singing_opens_beak() -> None:
    closed = _colors(build_frame(0).pixels)
    singing = _colors(build_frame(0, singing=True).pixels)
    assert "P" not in closed
    assert "P" in singing  # The tongue shows.


def test_parrot_is_lit() -> None:
    # Shading gives every visible colour several brightness levels.
    pixels = "".join(build_frame(0).pixels)
    assert all(key in pixels for key in SHADE_KEYS["Y"])


def test_spin_starts_from_upright_pose() -> None:
    # The first spin frame is the unturned, unswayed pose: no sudden jump.
    assert build_frame(DANCE_TICKS).pixels == build_frame(DANCE_TICKS, spin=False).pixels


def test_no_spin() -> None:
    for tick in range(ANIMATION_PERIOD):
        assert _facing(build_frame(tick, spin=False).pixels) == "right"


def test_frames_differ_over_time() -> None:
    assert len({build_frame(t).pixels for t in range(SWAY_PERIOD)}) > 1


def test_notes() -> None:
    assert {build_frame(t).note for t in range(SWAY_PERIOD)} == set(NOTES)
    assert {build_frame(t).note_side for t in range(SWAY_PERIOD)} == {0, 1}


def test_note_color_index_within_palette() -> None:
    assert {build_frame(t, palette_size=3).note_color_index for t in range(50)} == {0, 1, 2}


def test_scale_solid_blocks_unchanged() -> None:
    assert scale(("aa", "aa"), 2) == ("aaaa",) * 4
    assert scale(("ab",), 1) == ("ab",)


def test_scale2x_smooths_diagonal() -> None:
    # Plain repetition would leave a square step at the inner corner;
    # Scale2x fills it in so the edge becomes a finer diagonal.
    assert scale(("aa.", "a..", "..."), 2) == (
        "aaaa..",
        "aaa...",
        "aaa...",
        "a.....",
        "......",
        "......",
    )


@pytest.mark.parametrize("factor", [2, 3, 4, 6])
def test_scaled_frame_size(factor: int) -> None:
    frame = build_frame(0)
    scaled = scale(frame.pixels, factor)
    assert len(scaled) == frame.height * factor
    assert {len(row) for row in scaled} == {frame.width * factor}
    assert set("".join(scaled)) == set("".join(frame.pixels))


def test_invalid_arguments() -> None:
    with pytest.raises(ValueError):
        build_frame(-1)
    with pytest.raises(ValueError):
        build_frame(0, palette_size=0)
    with pytest.raises(ValueError):
        scale(("a",), 0)
    with pytest.raises(ValueError):
        scale(("a",), 5)
