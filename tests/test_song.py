from itertools import pairwise

import pytest

from dancing_parrot import song


def test_song_loops() -> None:
    assert song.state_at(1.0) == song.state_at(1.0 + song.DURATION)


def test_first_syllable() -> None:
    state = song.state_at(0.01)
    assert state.singing
    assert state.line.startswith("Polly")
    assert state.line[state.start : state.end] == "Pol"


def test_beak_closes_during_rests_and_between_notes() -> None:
    samples = [song.state_at(i * 0.01) for i in range(int(song.DURATION * 100))]
    singing = [s.singing for s in samples]
    assert any(singing) and not all(singing)
    # Many separate open/close cycles, not one long open beak.
    openings = sum(1 for a, b in pairwise(singing) if b and not a)
    assert openings >= 20


def test_every_lyric_line_is_shown() -> None:
    lines = {song.state_at(i * 0.05).line for i in range(int(song.DURATION * 20))}
    assert len(lines) == len(song.LYRICS)


@pytest.mark.parametrize("seconds", [0.0, 2.0, 5.5, 9.7, 12.7])
def test_highlight_inside_line(seconds: float) -> None:
    state = song.state_at(seconds)
    assert 0 <= state.start <= state.end <= len(state.line)


def test_pcm() -> None:
    pcm = song.render_pcm()
    assert len(pcm) == 2 * round(song.DURATION * song.SAMPLE_RATE)
    assert pcm == song.render_pcm()  # Deterministic.
    assert pcm.count(0) < len(pcm) // 2  # Not silent.
