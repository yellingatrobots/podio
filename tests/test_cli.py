"""The parser's own behaviour, apart from any pass it kicks off."""

import pytest

from podio import __version__
from podio.cli import build_parser


def test_version_prints_and_exits(capsys):
    with pytest.raises(SystemExit) as exit:
        build_parser().parse_args(["--version"])

    assert exit.value.code == 0
    assert capsys.readouterr().out.strip() == f"podio {__version__}"
