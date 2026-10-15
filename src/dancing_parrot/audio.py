"""Plays the song on Linux, macOS and Windows.

Backends are tried in order until one works:

1. ``sounddevice`` (optional extra, any platform): streams through PortAudio
   with an exact clock.
2. The platform's built-in player: ``winsound`` on Windows, ``afplay`` on
   macOS, and ``aplay`` / ``pw-cat`` / ``paplay`` elsewhere.

Audio is strictly best effort: if nothing works, the parrot keeps dancing
and singing silently.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any

from . import song

RATE = str(song.SAMPLE_RATE)

# Players that accept raw signed 16-bit mono PCM on stdin, in order of preference.
PIPE_PLAYERS: tuple[tuple[str, ...], ...] = (
    ("aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", RATE, "-c", "1", "--buffer-time=100000", "-"),
    ("pw-cat", "--playback", "--raw", "--rate", RATE, "--channels", "1", "--format", "s16", "-"),
    ("paplay", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1"),
)
MACOS_PLAYER = ("afplay",)

CHUNK_SECONDS = 0.05
LEAD_SECONDS = 0.2
"""How far ahead of real time audio is written to a pipe, to avoid dropouts."""
OUTPUT_LATENCY = 0.1
"""Estimated delay between handing audio to a player and hearing it."""

SetOrigin = Callable[[float], None]
"""Called by a backend with the monotonic time at which the song starts."""


class AudioError(Exception):
    """A backend could not play; the next one should be tried."""


class Backend:
    """Plays looping PCM until ``stop`` is set."""

    name = "backend"

    def run(self, pcm: bytes, stop: threading.Event, set_origin: SetOrigin) -> None:
        """Play until ``stop`` is set. Raise ``AudioError`` if playback fails."""
        raise NotImplementedError

    def interrupt(self) -> None:
        """Called from another thread to unblock ``run`` quickly (optional)."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


def wav_bytes(pcm: bytes) -> bytes:
    """Wrap raw PCM in a WAV container."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(song.SAMPLE_RATE)
        wav.writeframes(pcm)
    return buffer.getvalue()


class _TempWav:
    """A temporary WAV file of the song, removed afterwards."""

    def __init__(self, pcm: bytes) -> None:
        handle, self.path = tempfile.mkstemp(prefix="dancing-parrot-", suffix=".wav")
        with os.fdopen(handle, "wb") as file:
            file.write(wav_bytes(pcm))

    def __enter__(self) -> str:
        return self.path

    def __exit__(self, *exc_info: object) -> None:
        with contextlib.suppress(OSError):
            os.unlink(self.path)


def _terminate(process: subprocess.Popen[bytes] | None) -> None:
    """Stop a player process, closing its input first so it can exit cleanly."""
    if process is None:
        return
    try:
        if process.stdin:
            process.stdin.close()
    except OSError:
        pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


class PipeBackend(Backend):
    """Streams raw PCM to a player's stdin, paced to real time (Linux)."""

    def __init__(self, command: Sequence[str]) -> None:
        self.command = list(command)
        self.name = command[0]
        self._process: subprocess.Popen[bytes] | None = None

    def run(self, pcm: bytes, stop: threading.Event, set_origin: SetOrigin) -> None:
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._feed(self._process, pcm, stop, set_origin)
        except (OSError, ValueError) as exc:
            if not stop.is_set():
                raise AudioError(f"{self.name}: {exc}") from exc
        finally:
            # The audio thread owns the player, so it is cleaned up however we got here.
            _terminate(self._process)

    @staticmethod
    def _feed(
        process: subprocess.Popen[bytes], pcm: bytes, stop: threading.Event, set_origin: SetOrigin
    ) -> None:
        stdin = process.stdin
        assert stdin is not None
        chunk = int(CHUNK_SECONDS * song.SAMPLE_RATE) * 2
        offset = 0
        start = time.monotonic()
        set_origin(start + OUTPUT_LATENCY)
        written = 0.0
        while not stop.is_set():
            # Loop seamlessly: the last piece may be short, then start over.
            piece = pcm[offset : offset + chunk]
            offset = 0 if offset + chunk >= len(pcm) else offset + chunk
            stdin.write(piece)
            stdin.flush()
            written += len(piece) / 2 / song.SAMPLE_RATE
            # Pace writing to real time so the song clock stays in sync.
            ahead = start + written - time.monotonic() - LEAD_SECONDS
            if ahead > 0:
                stop.wait(ahead)

    def interrupt(self) -> None:
        # Also unblocks a write stuck on a full pipe.
        _terminate(self._process)


class FileLoopBackend(Backend):
    """Plays a WAV file with a command, restarting it for every loop (macOS)."""

    def __init__(self, command: Sequence[str]) -> None:
        self.command = list(command)
        self.name = command[0]
        self._process: subprocess.Popen[bytes] | None = None

    def run(self, pcm: bytes, stop: threading.Event, set_origin: SetOrigin) -> None:
        with _TempWav(pcm) as path:
            try:
                while not stop.is_set():
                    started = time.monotonic()
                    self._process = subprocess.Popen(
                        [*self.command, path],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    # Resync on every loop, since restarting adds a small gap.
                    set_origin(started + OUTPUT_LATENCY)
                    while self._process.poll() is None and not stop.wait(0.05):
                        pass
                    failed = self._process.poll() not in (None, 0)
                    if failed and not stop.is_set():
                        raise AudioError(f"{self.name} exited with {self._process.returncode}")
            except OSError as exc:
                raise AudioError(f"{self.name}: {exc}") from exc
            finally:
                _terminate(self._process)

    def interrupt(self) -> None:
        _terminate(self._process)


class WinsoundBackend(Backend):
    """Loops a WAV file with the standard library's ``winsound`` (Windows)."""

    name = "winsound"

    def __init__(self, module: Any = None) -> None:
        self._winsound = module

    def run(self, pcm: bytes, stop: threading.Event, set_origin: SetOrigin) -> None:
        try:
            winsound = self._winsound or importlib.import_module("winsound")
        except ImportError as exc:
            raise AudioError(str(exc)) from exc
        # winsound can't loop audio held in memory, only a file.
        with _TempWav(pcm) as path:
            flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP
            try:
                winsound.PlaySound(path, flags | winsound.SND_NODEFAULT)
            except RuntimeError as exc:
                raise AudioError(f"winsound: {exc}") from exc
            set_origin(time.monotonic() + OUTPUT_LATENCY)
            try:
                stop.wait()
            finally:
                winsound.PlaySound(None, 0)  # Stop playback before deleting the file.


class SounddeviceBackend(Backend):
    """Streams through PortAudio via the optional ``sounddevice`` package."""

    name = "sounddevice"

    def __init__(self, module: ModuleType | Any) -> None:
        self._sd = module

    def run(self, pcm: bytes, stop: threading.Event, set_origin: SetOrigin) -> None:
        offset = 0

        def callback(outdata: Any, frames: int, _time: Any, _status: Any) -> None:
            nonlocal offset
            needed = frames * 2
            data = bytearray()
            while len(data) < needed:
                piece = pcm[offset : offset + needed - len(data)]
                data += piece
                offset = (offset + len(piece)) % len(pcm)
            outdata[:] = bytes(data)

        try:
            stream = self._sd.RawOutputStream(
                samplerate=song.SAMPLE_RATE, channels=1, dtype="int16", callback=callback
            )
            with stream:
                set_origin(time.monotonic() + float(stream.latency))
                stop.wait()
        except Exception as exc:  # PortAudio raises its own error types.
            raise AudioError(f"sounddevice: {exc}") from exc


def _import_sounddevice() -> ModuleType | None:
    try:
        return importlib.import_module("sounddevice")
    except (ImportError, OSError):  # OSError: PortAudio library not installed.
        return None


def choose_backends(
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
    import_sounddevice: Callable[[], ModuleType | Any | None] = _import_sounddevice,
) -> list[Backend]:
    """Backends to try on this system, best first."""
    backends: list[Backend] = []
    sounddevice = import_sounddevice()
    if sounddevice is not None:
        backends.append(SounddeviceBackend(sounddevice))
    if platform == "win32":
        backends.append(WinsoundBackend())
    elif platform == "darwin":
        if which(MACOS_PLAYER[0]):
            backends.append(FileLoopBackend(MACOS_PLAYER))
    else:
        backends.extend(PipeBackend(command) for command in PIPE_PLAYERS if which(command[0]))
    return backends


class Singer:
    """Keeps the song clock and, unless muted, plays the song.

    Use as a context manager so playback is always cleaned up.
    """

    def __init__(self, sound: bool, backends: Sequence[Backend] | None = None) -> None:
        self._backends = (list(backends) if backends is not None else choose_backends()) if sound else []
        self._origin: float | None = None
        self._stop = threading.Event()
        self._current: Backend | None = None
        self._thread: threading.Thread | None = None
        self.backend_name: str | None = None
        """Name of the backend currently playing, if any."""

    def __enter__(self) -> Singer:
        if not self._backends:
            self._origin = time.monotonic()
        else:
            self._thread = threading.Thread(target=self._play, name="parrot-audio", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        current = self._current
        if current is not None:
            current.interrupt()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def position(self) -> float | None:
        """Seconds into the song being heard, or ``None`` before it starts."""
        if self._origin is None:
            return None
        return max(0.0, time.monotonic() - self._origin)

    def _set_origin(self, origin: float) -> None:
        self._origin = origin

    def _play(self) -> None:
        pcm = song.render_pcm()
        for backend in self._backends:
            if self._stop.is_set():
                return
            self._current = backend
            self.backend_name = backend.name
            try:
                backend.run(pcm, self._stop, self._set_origin)
                return  # Stopped normally.
            except AudioError:
                continue  # Try the next backend.
        self.backend_name = None
        if self._origin is None:
            self._origin = time.monotonic()  # Nothing worked: sing silently.
