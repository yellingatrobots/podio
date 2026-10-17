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
