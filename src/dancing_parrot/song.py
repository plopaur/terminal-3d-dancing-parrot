"""The parrot's song: melody, lyrics and a pure-Python synthesiser.

Everything here is pure: ``state_at`` says what is being sung at a given
time (for the beak and the karaoke line) and ``render_pcm`` produces the
audio as signed 16-bit mono samples.
"""

from __future__ import annotations

import math
import random
from array import array
from dataclasses import dataclass

SAMPLE_RATE = 22050
BPM = 150
BEAT = 60 / BPM
"""Seconds per beat; at the default 15 fps this is two dance steps."""

SQUAWK = -1
"""Pseudo note number for an unpitched squawk."""


@dataclass(frozen=True)
class Syllable:
    text: str
    """Exactly as displayed, including any trailing space or punctuation."""
    note: int | None
    """MIDI note number, ``SQUAWK``, or ``None`` for a rest."""
    beats: float


def _line(*parts: tuple[str, int | None, float]) -> tuple[Syllable, ...]:
    return tuple(Syllable(*part) for part in parts)


# An original tune: four lines of eight beats each, ending with a rest so
# the beak closes between lines.
LYRICS: tuple[tuple[Syllable, ...], ...] = (
    _line(
        ("Pol", 72, 0.5), ("ly ", 72, 0.5), ("wants ", 74, 0.5), ("to ", 76, 0.5),
        ("dance ", 79, 1), ("to", 76, 0.5), ("night,", 72, 2.5), ("", None, 2),
    ),
    _line(
        ("Shake ", 74, 0.5), ("those ", 74, 0.5), ("fea", 76, 0.5), ("thers ", 77, 0.5),
        ("left ", 79, 1), ("and ", 77, 0.5), ("right!", 74, 2.5), ("", None, 2),
    ),
    _line(
        ("Blue ", 76, 0.5), ("and ", 76, 0.5), ("yel", 77, 0.5), ("low, ", 79, 0.5),
        ("spin ", 81, 1), ("a", 79, 0.5), ("round,", 77, 2.5), ("", None, 2),
    ),
    _line(
        ("SQUAWK! ", SQUAWK, 1), ("The ", 79, 0.5), ("best ", 77, 0.5), ("bird ", 76, 1),
        ("in ", 74, 0.5), ("town!", 72, 2.5), ("", None, 2),
    ),
)

DURATION = sum(s.beats for line in LYRICS for s in line) * BEAT
"""Length of one pass through the song, in seconds."""


@dataclass(frozen=True)
class SongState:
    line: str
    """The current lyric line."""
    start: int
    end: int
    """Character span of the syllable being sung (empty during rests)."""
    singing: bool
    """True while a note is being sung, i.e. the beak should be open."""


def _timeline() -> list[tuple[float, float, int, int, Syllable]]:
    """(start, end, line index, char offset, syllable) for every syllable."""
    events = []
    time = 0.0
    for index, line in enumerate(LYRICS):
        offset = 0
        for syllable in line:
            length = syllable.beats * BEAT
            events.append((time, time + length, index, offset, syllable))
            time += length
            offset += len(syllable.text)
    return events


TIMELINE = _timeline()
# The beak closes briefly between notes so repeated syllables are visible.
ARTICULATION = 0.8


def state_at(seconds: float) -> SongState:
    """What is being sung ``seconds`` into the (endlessly looping) song."""
    t = seconds % DURATION
    for start, end, index, offset, syllable in TIMELINE:
        if start <= t < end:
            text = "".join(s.text for s in LYRICS[index]).rstrip()
            if syllable.note is None:
                return SongState(text, offset, offset, singing=False)
            sung = t < start + (end - start) * ARTICULATION
            return SongState(text, offset, offset + len(syllable.text.rstrip()), singing=sung)
    raise AssertionError("timeline does not cover the song")  # pragma: no cover


def _frequency(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def _voice(out: list[float], start: int, length: int, note: int) -> None:
    """A chirpy, slightly nasal FM voice with vibrato."""
    base = _frequency(note)
    phase = 0.0
    sung = int(length * ARTICULATION)
    for i in range(sung):
        t = i / SAMPLE_RATE
        # Parrots swoop into notes: start two semitones flat, slide up.
        bend = -2 * math.exp(-t / 0.03)
        vibrato = 0.35 * min(1.0, t / 0.2) * math.sin(2 * math.pi * 6 * t)
        freq = base * 2 ** ((bend + vibrato) / 12)
        phase += 2 * math.pi * freq / SAMPLE_RATE
        envelope = min(1.0, i / (0.015 * SAMPLE_RATE), (sung - i) / (0.05 * SAMPLE_RATE))
        out[start + i] += 0.45 * envelope * math.sin(phase + 1.2 * math.sin(2 * phase))


def _squawk(out: list[float], start: int, length: int, rng: random.Random) -> None:
    """A harsh downward screech with a noisy edge."""
    phase = 0.0
    sung = min(length, int(0.4 * SAMPLE_RATE))
    for i in range(sung):
        t = i / SAMPLE_RATE
        freq = 1400 * math.exp(-t * 2.5)
        phase += 2 * math.pi * freq / SAMPLE_RATE
        envelope = min(1.0, i / (0.01 * SAMPLE_RATE)) * (1 - i / sung)
        tone = math.sin(phase + 3 * math.sin(3 * phase))
        out[start + i] += 0.5 * envelope * (0.7 * tone + 0.3 * rng.uniform(-1, 1))


def _drums(out: list[float], rng: random.Random) -> None:
    """Kick on every beat, hi-hat on the off-beats."""
    beat_samples = BEAT * SAMPLE_RATE
    beats = round(DURATION / BEAT)
    for beat in range(beats):
        start = round(beat * beat_samples)
        phase = 0.0
        for i in range(int(0.15 * SAMPLE_RATE)):
            t = i / SAMPLE_RATE
            phase += 2 * math.pi * (50 + 90 * math.exp(-t * 30)) / SAMPLE_RATE
            out[start + i] += 0.5 * math.exp(-t * 25) * math.sin(phase)
        hat = round((beat + 0.5) * beat_samples)
        for i in range(int(0.04 * SAMPLE_RATE)):
            if hat + i < len(out):
                out[hat + i] += 0.12 * math.exp(-i / SAMPLE_RATE * 120) * rng.uniform(-1, 1)


def render_pcm() -> bytes:
    """One pass of the song as signed 16-bit little-endian mono PCM."""
    total = round(DURATION * SAMPLE_RATE)
    mix = [0.0] * total
    rng = random.Random(1)  # Deterministic noise, so the song is identical every run.

    for start, end, _, _, syllable in TIMELINE:
        first = round(start * SAMPLE_RATE)
        length = min(round(end * SAMPLE_RATE), total) - first
        if syllable.note == SQUAWK:
            _squawk(mix, first, length, rng)
        elif syllable.note is not None:
            _voice(mix, first, length, syllable.note)
    _drums(mix, rng)

    peak = max(1e-9, max(abs(s) for s in mix))
    gain = 0.7 * 32767 / peak
    samples = array("h", (round(s * gain) for s in mix))
    if samples.itemsize != 2:  # pragma: no cover - 'h' is 2 bytes on Linux
        raise RuntimeError("unexpected sample size")
    if array("h", [1]).tobytes() != b"\x01\x00":  # pragma: no cover - big-endian host
        samples.byteswap()
    return samples.tobytes()
