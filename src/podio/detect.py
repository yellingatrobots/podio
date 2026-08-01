"""Transcribe a take and detect spans -> (transcript, manifest).

`audio_path` is the take itself. Whatever decoding a model needs — mono, a
particular rate — belongs to the injected transcriber, which is the only thing
here that knows what its model wants.
"""

from __future__ import annotations

from typing import Tuple

from .manifest import Manifest, Transcript
from .adjust import adjust_spans
from .transcribe import Transcriber
from .wordlist import WordList, find_spans


def transcribe_and_detect(
    audio_path: str,
    transcriber: Transcriber,
    wordlist: WordList,
    inset: float = 0.03,
    min_confidence: float = 0.0,
) -> Tuple[Transcript, Manifest]:
    """Transcribe `audio_path`, then detect and post-process spans.

    Returns both artifacts: the full transcript (auditable record) and the
    manifest (the lean edit-list of spans to bleep). Detected spans below
    `min_confidence` are dropped (left for human review rather than bleeped
    blindly); the rest pass through Stage 5 post-processing (inset, drop, merge)
    before the manifest.
    """
    words = transcriber.transcribe(audio_path)
    transcript = Transcript(audio_path=audio_path, words=list(words))
    spans = [s for s in find_spans(words, wordlist) if s.confidence >= min_confidence]
    manifest = Manifest(audio_path=audio_path, spans=adjust_spans(spans, inset=inset))
    return transcript, manifest
