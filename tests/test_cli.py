"""The parser's own behaviour, apart from any work it kicks off."""

import pytest

from podio import __version__
from podio.cli import build_parser


def test_version_prints_and_exits(capsys):
    with pytest.raises(SystemExit) as exit:
        build_parser().parse_args(["--version"])

    assert exit.value.code == 0
    assert capsys.readouterr().out.strip() == f"podio {__version__}"


@pytest.fixture
def help_text(capsys):
    def read(*argv: str) -> str:
        with pytest.raises(SystemExit):
            build_parser().parse_args([*argv, "--help"])
        return capsys.readouterr().out
    return read


def test_the_overview_lists_the_primary_commands_and_points_at_debug(help_text):
    overview = help_text()
    for command in ("prep", "devices", "bumper", "debug"):
        assert f"podio {command}" in overview
    for step in ("clean", "detect", "bleep", "mux", "normalize"):
        assert f"podio {step}" not in overview


@pytest.mark.parametrize("old", ["run", "finish", "master", "clean", "detect",
                                 "bleep", "mux", "normalize"])
def test_the_old_top_level_commands_are_gone(old):
    with pytest.raises(SystemExit):
        build_parser().parse_args([old, "x"])


@pytest.mark.parametrize("step", ["clean", "detect", "bleep", "mux", "normalize"])
def test_every_step_lives_under_debug(help_text, step):
    assert help_text("debug", step).split("\n\n")[1].startswith("debug:")


def test_prep_takes_many_files_and_bleeps_by_default():
    args = build_parser().parse_args(["prep", "ian.mp4", "josh.mp4"])
    assert [str(f) for f in args.files] == ["ian.mp4", "josh.mp4"]
    assert args.no_bleep is False
    assert args.jobs is None
    assert args.keep_temp is None


def test_prep_can_skip_the_bleep():
    assert build_parser().parse_args(["prep", "--no-bleep", "ian.mp4"]).no_bleep


@pytest.mark.parametrize("command", [["debug", "detect", "ian.wav"]])
def test_where_whisperx_runs_is_asr_device_not_device(command):
    assert build_parser().parse_args([*command, "--asr-device", "cuda"]).asr_device == "cuda"
    with pytest.raises(SystemExit):
        build_parser().parse_args([*command, "--device", "cuda"])


def test_bumper_keeps_device_for_the_microphone():
    assert build_parser().parse_args(["bumper", "--device", "2"]).device == "2"
