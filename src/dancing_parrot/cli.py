"""Command-line entry point."""

from __future__ import annotations

import argparse
import locale
import os
import signal
import sys
from collections.abc import Sequence
from types import FrameType

from . import __version__

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    if not number > 0:
        raise argparse.ArgumentTypeError(f"{value!r} must be greater than 0")
    return number


def _fps(value: str) -> float:
    from .renderer import MAX_FPS, MIN_FPS

    number = _positive_float(value)
    if not MIN_FPS <= number <= MAX_FPS:
        raise argparse.ArgumentTypeError(f"fps must be between {MIN_FPS:g} and {MAX_FPS:g}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dancing-parrot",
        description="Display an animated dancing parrot in the terminal.",
        epilog=(
            "Keys: q/Esc quit, +/- change speed. Sound uses sounddevice if installed, "
            "else winsound (Windows), afplay (macOS) or aplay/pw-cat/paplay (Linux). "
            "Honours the NO_COLOR environment variable."
        ),
    )
    parser.add_argument(
        "-f", "--fps", type=_fps, default=15.0, help="animation speed in frames per second (default: 15)"
    )
    parser.add_argument(
        "-d", "--duration", type=_positive_float, metavar="SECONDS", help="stop automatically after SECONDS"
    )
    parser.add_argument("--no-color", action="store_true", help="disable colours")
    parser.add_argument("--no-spin", action="store_true", help="don't do the 360 degree pirouette")
    parser.add_argument(
        "-m", "--mute", action="store_true", help="sing silently (lyrics only, no sound)"
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _supports_unicode() -> bool:
    if sys.platform == "win32":
        return True  # Windows curses writes through the wide-character console API.
    encoding = locale.getpreferredencoding(False)
    return encoding.lower().replace("-", "") in {"utf8", "utf16", "utf32"}


def _raise_on_sigterm(signum: int, frame: FrameType | None) -> None:
    # Turn SIGTERM into a normal exception so curses.wrapper restores the terminal.
    raise SystemExit(128 + signum)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("dancing-parrot: needs an interactive terminal", file=sys.stderr)
        return EXIT_ERROR

    # Required for curses to output multi-byte characters correctly.
    locale.setlocale(locale.LC_ALL, "")
    if not _supports_unicode():
        print("dancing-parrot: needs a UTF-8 terminal (e.g. LANG=C.UTF-8)", file=sys.stderr)
        return EXIT_ERROR
    signal.signal(signal.SIGTERM, _raise_on_sigterm)

    # Imported lazily so --help works even where curses is unavailable.
    import curses

    from .renderer import Settings, run

    settings = Settings(
        fps=args.fps,
        color=not args.no_color and "NO_COLOR" not in os.environ,
        duration=args.duration,
        spin=not args.no_spin,
        sound=not args.mute,
    )
    try:
        run(settings)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except curses.error as exc:
        print(f"dancing-parrot: terminal error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
