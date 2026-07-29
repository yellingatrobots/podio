"""Profanity matching: load a configurable wordlist and find censor spans.

Whole-word / whole-phrase matching only, never substrings — that avoids the
Scunthorpe problem (bleeping "class", "assassin", "cockpit"). An allowlist
provides explicit exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import yaml

from .manifest import CensorSpan, Word
from .text import normalize


@dataclass(frozen=True)
class Entry:
    """One wordlist rule."""

    term: str                # canonical/display term
    tokens: Tuple[str, ...]  # normalized token(s); >1 means a phrase


class WordList:
    """A loaded wordlist: exact terms, multi-word phrases, and an allowlist."""

    def __init__(self, exact: dict, phrases: List[Entry], allowlist: set):
        self._exact = exact                       # normalized token -> Entry
        # Longest phrases first so "son of a bitch" wins over any shorter overlap.
        self._phrases = sorted(phrases, key=lambda e: len(e.tokens), reverse=True)
        self._allowlist = allowlist               # set of normalized tokens

    @classmethod
    def from_dict(cls, data: dict) -> "WordList":
        allowlist = {normalize(w) for w in data.get("allowlist", [])}
        exact: dict = {}
        phrases: List[Entry] = []
        for raw in data.get("terms", []):
            term = raw["term"]
            tokens = tuple(normalize(t) for t in term.split())
            entry = Entry(term=term, tokens=tokens)
            if len(tokens) > 1:
                phrases.append(entry)
            else:
                exact[tokens[0]] = entry
        return cls(exact, phrases, allowlist)

    @classmethod
    def from_file(cls, path) -> "WordList":
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls.from_dict(data)

    def match_at(self, norms: Sequence[str], i: int) -> Tuple[Optional[Entry], int]:
        """Return (entry, length) for the longest match starting at index i.

        length is how many words the match consumes; (None, 0) means no match.
        Allowlisted tokens are never matched.
        """
        if norms[i] in self._allowlist:
            return None, 0

        for entry in self._phrases:
            k = len(entry.tokens)
            window = tuple(norms[i:i + k])
            if window == entry.tokens and not any(t in self._allowlist for t in window):
                return entry, k

        entry = self._exact.get(norms[i])
        if entry is not None:
            return entry, 1

        return None, 0


def find_spans(words: Sequence[Word], wordlist: WordList) -> List[CensorSpan]:
    """Scan transcribed words and return the spans that should be bleeped."""
    norms = [normalize(w.text) for w in words]
    spans: List[CensorSpan] = []
    i = 0
    n = len(words)
    while i < n:
        entry, length = wordlist.match_at(norms, i)
        if entry is None:
            i += 1
            continue
        matched = words[i:i + length]
        spans.append(
            CensorSpan(
                start=matched[0].start,
                end=matched[-1].end,
                term=entry.term,
                source_text=" ".join(w.text for w in matched),
                confidence=min(w.confidence for w in matched),
            )
        )
        i += length
    return spans
