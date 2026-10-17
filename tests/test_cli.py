"""The parser's own behaviour, apart from any pass it kicks off."""

import pytest

from podio import __version__
from podio.cli import build_parser


def test_version_prints_and_exits(capsys):
    with pytest.raises(SystemExit) as exit:
        build_parser().parse_args(["--version"])

    assert exit.value.code == 0
    assert capsys.readouterr().out.strip() == f"podio {__version__}"


def test_master_takes_the_nle_mixdown():
    args = build_parser().parse_args(["master", "ep16.mp4"])
    assert args.video == "ep16.mp4"
    assert args.out is None



@pytest.fixture
def help_text(capsys):
    def read(*argv: str) -> str:
        with pytest.raises(SystemExit):
            build_parser().parse_args([*argv, "--help"])
        return capsys.readouterr().out
    return read


def test_the_overview_lists_the_pass_apart_from_the_standalone_commands(help_text):
    pass_part, standalone = help_text().split("standalone, outside the pass:")

    for step in ("1  clean", "2  detect", "3  bleep", "4  mux", "5  master"):
        assert step in pass_part
    for command in ("devices", "bumper", "normalize"):
        assert f"podio {command}" in standalone
        assert f"podio {command}" not in pass_part


@pytest.mark.parametrize("command, place", [
    ("run", "steps 1-3"), ("finish", "steps 1-4"), ("clean", "step 1"),
    ("detect", "step 2"), ("bleep", "step 3"), ("mux", "step 4"),
    ("master", "step 5"), ("devices", "standalone"), ("bumper", "standalone"),
    ("normalize", "standalone"),
])
def test_every_command_opens_by_saying_where_it_sits(help_text, command, place):
    # The paragraph after usage is the first thing the description says.
    assert help_text(command).split("\n\n")[1].startswith(place)


def test_run_groups_its_options_by_step(help_text):
    options = help_text("run").split("\noptions:")[1]
    clean, detect = options.split("step 1, clean:")[1].split("step 2, detect:")
    assert "--dry-run" in clean and "--min-confidence" not in clean
    assert "--min-confidence" in detect and "--dry-run" not in detect


@pytest.mark.parametrize("command", [["run"], ["finish"], ["detect", "ian.wav"]])
def test_where_whisperx_runs_is_asr_device_not_device(command):
    assert build_parser().parse_args([*command, "--asr-device", "cuda"]).asr_device == "cuda"
    with pytest.raises(SystemExit):
        build_parser().parse_args([*command, "--device", "cuda"])


def test_bumper_keeps_device_for_the_microphone():
    assert build_parser().parse_args(["bumper", "--device", "2"]).device == "2"
