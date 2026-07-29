"""Speech-to-text with word-level timestamps.

`Transcriber` is the public interface the pipeline depends on. Tests inject a
fake; the real implementation wraps WhisperX and is imported lazily so the heavy
ML stack is only touched when actually transcribing.
"""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from typing import Iterator, List, Protocol

from .manifest import Word


@contextmanager
def _heartbeat(label: str, interval: float = 15.0) -> Iterator[None]:
    """Print `label` with elapsed seconds every `interval` while the block runs.

    WhisperX's VAD/ASR can run silently for minutes; this reassures a watching
    human that the process is working rather than hung. Emits to stderr so it
    never mixes with the manifest/transcript paths printed on stdout.
    """
    stop = threading.Event()
    start = time.monotonic()

    def tick() -> None:
        while not stop.wait(interval):
            print(f"  … {label} ({time.monotonic() - start:.0f}s)", file=sys.stderr, flush=True)

    thread = threading.Thread(target=tick, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1.0)


class Transcriber(Protocol):
    """Turns an audio file into timestamped words."""

    def transcribe(self, audio_path: str) -> List[Word]:
        ...


class WhisperXTranscriber:
    """Word-level ASR via WhisperX (Whisper + wav2vec2 forced alignment).

    WhisperX is imported inside `transcribe` so importing this module — and
    running the test suite — never requires torch. Install the stack with
    `just setup-asr`.
    """

    def __init__(
        self,
        model_size: str = "base.en",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "en",
        threads: int = 8,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.threads = threads

    def transcribe(self, audio_path: str) -> List[Word]:
        import whisperx  # lazy: keeps torch out of the pure path

        # WhisperX operates on a loaded waveform, not a path.
        audio = whisperx.load_audio(audio_path)

        model = whisperx.load_model(
            self.model_size,
            self.device,
            compute_type=self.compute_type,
            language=self.language,
            threads=self.threads,
        )
        with _heartbeat("transcribing (VAD + ASR)"):
            result = model.transcribe(audio)

        align_model, meta = whisperx.load_align_model(
            language_code=self.language, device=self.device
        )
        with _heartbeat("aligning word timestamps"):
            aligned = whisperx.align(
                result["segments"], align_model, meta, audio, self.device
            )

        words: List[Word] = []
        for segment in aligned["segments"]:
            for w in segment.get("words", []):
                # Alignment can drop timestamps for non-speech tokens; skip them.
                if "start" not in w or "end" not in w:
                    continue
                words.append(
                    Word(
                        text=w["word"],
                        start=float(w["start"]),
                        end=float(w["end"]),
                        confidence=float(w.get("score", 1.0)),
                    )
                )
        return words
