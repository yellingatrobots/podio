from pathlib import Path

import pytest

from podio.clean import select_takes
from podio.config import Take

CONFIG = Path("audio.toml")


def take(name: str) -> Take:
    return Take(
        name=name,
        source=Path(f"{name}.wav"),
        chain=[],
        limiter=False,
        censor=None,
    )


TAKES = [take("ian"), take("josh")]


def test_no_names_selects_every_take():
    assert select_takes(TAKES, [], CONFIG) == TAKES


def test_a_name_selects_just_that_take():
    assert select_takes(TAKES, ["josh"], CONFIG) == [TAKES[1]]


def test_an_unknown_name_is_an_error_that_lists_the_takes_there_are():
    with pytest.raises(ValueError, match=r"ian\.wav.*ian, josh"):
        select_takes(TAKES, ["ian.wav"], CONFIG)
