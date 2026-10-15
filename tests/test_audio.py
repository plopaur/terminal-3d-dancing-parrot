import os
import sys
import threading
import time
import wave
from io import BytesIO
from types import SimpleNamespace
from typing import Any

from dancing_parrot import song
from dancing_parrot.audio import (
    MACOS_PLAYER,
    PIPE_PLAYERS,
    AudioError,
    Backend,
    FileLoopBackend,
    PipeBackend,
    Singer,
    SounddeviceBackend,
    WinsoundBackend,
    choose_backends,
    wav_bytes,
)

PCM = bytes(range(256)) * 40  # Small stand-in for the song.


def _wait(predicate: Any, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _run_in_thread(backend: Backend, pcm: bytes = PCM) -> tuple[threading.Event, list[Any], threading.Thread]:
    stop = threading.Event()
    result: list[Any] = []
    origins: list[float] = []

    def target() -> None:
        try:
            backend.run(pcm, stop, origins.append)
            result.append("ok")
        except AudioError as exc:
            result.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    return stop, [result, origins], thread


# --- backend selection ------------------------------------------------------


def _no_sd() -> None:
    return None


def test_linux_uses_pipe_players_in_order() -> None:
    backends = choose_backends("linux", lambda name: "/usr/bin/" + name, _no_sd)
    assert [b.name for b in backends] == [c[0] for c in PIPE_PLAYERS]
    only_paplay = choose_backends("linux", lambda n: n if n == "paplay" else None, _no_sd)
    assert [b.name for b in only_paplay] == ["paplay"]


def test_macos_uses_afplay() -> None:
    backends = choose_backends("darwin", lambda name: "/usr/bin/" + name, _no_sd)
    assert [b.name for b in backends] == [MACOS_PLAYER[0]]
    assert isinstance(backends[0], FileLoopBackend)


def test_windows_uses_winsound() -> None:
    backends = choose_backends("win32", lambda name: None, _no_sd)
    assert [b.name for b in backends] == ["winsound"]


def test_sounddevice_preferred_when_installed() -> None:
    fake = SimpleNamespace()
    for platform in ("linux", "darwin", "win32"):
        backends = choose_backends(platform, lambda name: "/usr/bin/" + name, lambda: fake)
        assert backends[0].name == "sounddevice"
        assert len(backends) >= 2  # Built-in fallback still available.


def test_no_players() -> None:
    assert choose_backends("linux", lambda name: None, _no_sd) == []


def test_wav_bytes() -> None:
    with wave.open(BytesIO(wav_bytes(PCM))) as wav:
        assert wav.getframerate() == song.SAMPLE_RATE
        assert wav.getnchannels() == 1
        assert wav.readframes(wav.getnframes()) == PCM


# --- backends -----------------------------------------------------------------


def test_pipe_backend_streams_and_cleans_up() -> None:
    backend = PipeBackend(["cat"])  # Consumes the stream silently.
    stop, (result, origins), thread = _run_in_thread(backend)
    assert _wait(lambda: origins)
    time.sleep(0.1)
    stop.set()
    backend.interrupt()
    thread.join(timeout=5)
    assert result == ["ok"]
    assert backend._process is not None and backend._process.poll() is not None


def test_pipe_backend_missing_player() -> None:
    stop, (result, _), thread = _run_in_thread(PipeBackend(["/nonexistent/player"]))
    thread.join(timeout=5)
    assert isinstance(result[0], AudioError)


def test_file_loop_backend_restarts_and_resyncs() -> None:
    # `sh -c "sleep 0.1" <file>` stands in for afplay playing a short file.
    backend = FileLoopBackend(["sh", "-c", 'test -s "$0" && sleep 0.1'])
    stop, (result, origins), thread = _run_in_thread(backend)
    assert _wait(lambda: len(origins) >= 3)  # Restarted for each loop.
    assert origins == sorted(origins)
    stop.set()
    backend.interrupt()
    thread.join(timeout=5)
    assert result == ["ok"]


def test_file_loop_backend_failing_player() -> None:
    stop, (result, _), thread = _run_in_thread(FileLoopBackend(["false"]))
    thread.join(timeout=5)
    assert isinstance(result[0], AudioError)


def test_file_loop_backend_removes_temp_file() -> None:
    backend = FileLoopBackend(["sh", "-c", "sleep 5"])
    stop, _, thread = _run_in_thread(backend)
    assert _wait(lambda: backend._process is not None)
    path = backend._process.args[-1]  # type: ignore[union-attr]
    assert os.path.exists(path)
    stop.set()
    backend.interrupt()
    thread.join(timeout=5)
    assert not os.path.exists(path)


class FakeWinsound:
    SND_FILENAME, SND_ASYNC, SND_LOOP, SND_NODEFAULT = 1, 2, 4, 8

    def __init__(self) -> None:
        self.calls: list[tuple[Any, int]] = []
        self.file_existed = False

    def PlaySound(self, sound: Any, flags: int) -> None:  # noqa: N802 - mirrors winsound
        self.calls.append((sound, flags))
        if sound is not None:
            self.file_existed = os.path.exists(sound)


def test_winsound_backend() -> None:
    fake = FakeWinsound()
    stop, (result, origins), thread = _run_in_thread(WinsoundBackend(fake))
    assert _wait(lambda: origins)
    stop.set()
    thread.join(timeout=5)
    assert result == ["ok"]
    (path, flags), stop_call = fake.calls
    assert fake.file_existed and path.endswith(".wav")
    assert flags & fake.SND_LOOP and flags & fake.SND_ASYNC
    assert stop_call == (None, 0)  # Playback stopped...
    assert not os.path.exists(path)  # ...and the file removed.


def test_winsound_backend_unavailable_off_windows() -> None:
    if sys.platform == "win32":
        return
    stop, (result, _), thread = _run_in_thread(WinsoundBackend())
    thread.join(timeout=5)
    assert isinstance(result[0], AudioError)


class FakeStream:
    """Mimics sounddevice.RawOutputStream by calling back from a thread."""

    latency = 0.05

    def __init__(self, callback: Any, **kwargs: Any) -> None:
        self.callback = callback
        self.kwargs = kwargs
        self.output = bytearray()
        self._stop = threading.Event()

    def __enter__(self) -> "FakeStream":
        def pump() -> None:
            while not self._stop.is_set():
                buffer = bytearray(2 * 300)
                self.callback(memoryview(buffer), 300, None, None)
                self.output += buffer
                time.sleep(0.001)

        self._thread = threading.Thread(target=pump)
        self._thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._stop.set()
        self._thread.join()


def test_sounddevice_backend_loops_pcm_exactly() -> None:
    streams: list[FakeStream] = []

    def factory(**kwargs: Any) -> FakeStream:
        stream = FakeStream(**kwargs)
        streams.append(stream)
        return stream

    backend = SounddeviceBackend(SimpleNamespace(RawOutputStream=factory))
    stop, (result, origins), thread = _run_in_thread(backend)
    assert _wait(lambda: streams and len(streams[0].output) > 3 * len(PCM))
    stop.set()
    thread.join(timeout=5)
    assert result == ["ok"]
    assert streams[0].kwargs["samplerate"] == song.SAMPLE_RATE
    assert streams[0].kwargs["dtype"] == "int16"
    output = bytes(streams[0].output)
    assert output[: 3 * len(PCM)] == PCM * 3  # Seamless loop.


def test_sounddevice_backend_device_error() -> None:
    def broken(**kwargs: Any) -> None:
        raise RuntimeError("no default output device")

    stop, (result, _), thread = _run_in_thread(SounddeviceBackend(SimpleNamespace(RawOutputStream=broken)))
    thread.join(timeout=5)
    assert isinstance(result[0], AudioError)


# --- singer -------------------------------------------------------------------


def test_muted_clock_starts_immediately() -> None:
    with Singer(sound=False) as singer:
        assert singer.position() is not None


def test_falls_back_to_next_backend() -> None:
    working = PipeBackend(["cat"])
    with Singer(sound=True, backends=[PipeBackend(["/nonexistent/player"]), working]) as singer:
        assert _wait(lambda: singer.backend_name == "cat" and singer.position() is not None)
        process = working._process
        assert process is not None and process.poll() is None
    assert process.poll() is not None  # Cleaned up on exit.


def test_nothing_works_sings_silently() -> None:
    with Singer(sound=True, backends=[FileLoopBackend(["false"])]) as singer:
        assert _wait(lambda: singer.position() is not None)
        assert _wait(lambda: singer.backend_name is None)


def test_exit_during_synthesis_leaves_no_player() -> None:
    backend = PipeBackend(["cat"])
    singer = Singer(sound=True, backends=[backend])
    with singer:
        pass
    assert singer._thread is not None
    singer._thread.join(timeout=5)
    assert backend._process is None or backend._process.poll() is not None
