"""Core data types passed between stages."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Word:
    """A single transcribed word with its time boundaries (seconds)."""

    text: str
    start: float
    end: float
    confidence: float = 1.0


@dataclass(frozen=True)
class CensorSpan:
    """A stretch of audio that should be bleeped."""

    start: float
    end: float
    term: str          # the matched list entry (canonical form)
    source_text: str   # what the ASR actually transcribed
    confidence: float


@dataclass
class Manifest:
    """The detection pass output: every span to bleep, plus metadata.

    Deliberately audio-agnostic — it is an edit list. A later rendering stage
    consumes it to produce censored audio, and a human can review or override
    it first.
    """

    audio_path: str
    spans: List[CensorSpan] = field(default_factory=list)
    version: int = SCHEMA_VERSION
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "audio_path": self.audio_path,
            "generated_at": self.generated_at,
            "spans": [dataclasses.asdict(s) for s in self.spans],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class Transcript:
    """The full ASR word list for a file — the auditable record behind a
    manifest. Written as a sibling `*.transcript.json` so the manifest stays a
    lean edit-list while every run remains reviewable.
    """

    audio_path: str
    words: List[Word] = field(default_factory=list)
    version: int = SCHEMA_VERSION
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "audio_path": self.audio_path,
            "generated_at": self.generated_at,
            "text": " ".join(w.text for w in self.words),
            "words": [dataclasses.asdict(w) for w in self.words],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
