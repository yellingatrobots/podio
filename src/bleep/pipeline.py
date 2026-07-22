"""Detection pipeline: transcribe -> detect -> (transcript, manifest).

Audio normalization lives in the CLI (which owns ffmpeg and temp files); by the
time we get here, `audio_path` is whatever the injected transcriber should read.
"""

from __future__ import annotations

from typing import Tuple

from .model import Manifest, Transcript
from .transcribe import Transcriber
from .wordlist import WordList, find_spans


def transcribe_and_detect(
    audio_path: str, transcriber: Transcriber, wordlist: WordList
) -> Tuple[Transcript, Manifest]:
    """Transcribe `audio_path`, then detect spans.

    Returns both artifacts: the full transcript (auditable record) and the
    manifest (the lean edit-list of spans to bleep).
    """
    words = transcriber.transcribe(audio_path)
    transcript = Transcript(audio_path=audio_path, words=list(words))
    manifest = Manifest(audio_path=audio_path, spans=find_spans(words, wordlist))
    return transcript, manifest
