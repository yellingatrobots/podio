"""Token normalization — fold raw transcript words to a canonical match form."""

from __future__ import annotations

import re

# Strip punctuation that hugs the start/end of a token, keeping inner chars.
_SURROUNDING_PUNCT = re.compile(r"^\W+|\W+$")


def normalize(token: str) -> str:
    """Fold a raw transcript token to its canonical form for matching.

    The ASR emits correctly-spelled dictionary words, so normalization is
    deliberately minimal: lowercase, and strip punctuation that hugs the
    token edges (e.g. "Fuck!" -> "fuck", "...damn," -> "damn"). Inner
    characters are preserved. No leetspeak/obfuscation handling — that is a
    text-moderation concern, not a transcript-matching one.
    """
    return _SURROUNDING_PUNCT.sub("", token.lower())
