"""The defaults podio ships with — the wordlist and the rigs — must resolve
from the installed package, not from a source checkout. podio runs from an
episode directory, and once installed there is no repo above it to find.
"""

from pathlib import Path

from podio import cli

PACKAGE = Path(cli.__file__).resolve().parent


def test_shipped_wordlist_is_package_data():
    assert PACKAGE in cli.WORDLIST.parents
    assert cli.WORDLIST.is_file()


def test_shipped_rigs_are_package_data():
    assert PACKAGE in cli.RIGS.parents
    assert list(cli.RIGS.glob("*.toml"))
