from podio.text import normalize


def test_lowercases():
    assert normalize("Damn") == "damn"


def test_strips_trailing_punctuation():
    assert normalize("fuck!") == "fuck"


def test_strips_surrounding_punctuation():
    assert normalize("...damn,") == "damn"


def test_keeps_inner_characters():
    assert normalize("bull-shit") == "bull-shit"


def test_pure_punctuation_becomes_empty():
    assert normalize("!!!") == ""
