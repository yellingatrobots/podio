from bleep.model import Word
from bleep.wordlist import WordList, find_spans

WL = WordList.from_dict(
    {
        "allowlist": ["class", "assassin"],
        "terms": [
            {"term": "fuck"},
            {"term": "damn"},
            {"term": "son of a bitch"},
        ],
    }
)


def words(*texts):
    """Build a word sequence with simple 1-second slots."""
    return [Word(text=t, start=float(i), end=i + 0.5) for i, t in enumerate(texts)]


def test_detects_exact_word():
    spans = find_spans(words("hello", "fuck", "world"), WL)
    assert len(spans) == 1
    assert spans[0].term == "fuck"
    assert spans[0].start == 1.0
    assert spans[0].end == 1.5


def test_match_is_case_and_punctuation_insensitive():
    spans = find_spans(words("Damn!"), WL)
    assert len(spans) == 1
    assert spans[0].term == "damn"
    assert spans[0].source_text == "Damn!"  # preserves what was said


def test_ignores_whole_word_lookalikes_scunthorpe():
    # "class" contains "ass"-like fragments; substring matching would bleep it.
    spans = find_spans(words("the", "class", "assassin"), WL)
    assert spans == []


def test_detects_multiword_phrase():
    ws = words("you", "son", "of", "a", "bitch")
    spans = find_spans(ws, WL)
    assert len(spans) == 1
    assert spans[0].term == "son of a bitch"
    assert spans[0].start == 1.0          # "son"
    assert spans[0].end == ws[-1].end     # "bitch"


def test_allowlist_blocks_a_listed_term():
    wl = WordList.from_dict(
        {"allowlist": ["damn"], "terms": [{"term": "damn"}]}
    )
    assert find_spans(words("oh", "damn"), wl) == []


def test_confidence_is_the_minimum_across_matched_words():
    ws = [Word("son", 1.0, 1.5, 0.9), Word("of", 2.0, 2.5, 0.4),
          Word("a", 3.0, 3.5, 0.8), Word("bitch", 4.0, 4.5, 0.7)]
    spans = find_spans(ws, WL)
    assert spans[0].confidence == 0.4
