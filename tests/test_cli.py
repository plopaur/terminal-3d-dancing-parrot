import pytest

from dancing_parrot.cli import EXIT_ERROR, build_parser, main


def test_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.fps == 15.0
    assert args.duration is None
    assert not args.no_color
    assert not args.no_spin
    assert not args.mute


@pytest.mark.parametrize("argv", [["--fps", "0"], ["--fps", "abc"], ["--fps", "1000"], ["-d", "-1"]])
def test_rejects_invalid_values(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(argv)
    assert exc.value.code == 2


def test_requires_tty(capsys: pytest.CaptureFixture[str]) -> None:
    # Under pytest stdin/stdout are not terminals.
    assert main([]) == EXIT_ERROR
    assert "interactive terminal" in capsys.readouterr().err
