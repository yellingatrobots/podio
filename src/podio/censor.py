"""Censor a cleaned take: detect the spans, then splice the tone over them.

Detection listens to the cleaned take rather than the raw one — denoising and
gating measurably help the ASR — and the tone goes on last, after leveling,
so it never passes through the compressor or the gate.
"""

from __future__ import annotations

from pathlib import Path

from .bleep import render_file
from .detect import transcribe_and_detect
from .transcribe import Transcriber
from .wordlist import WordList


def manifest_path(episode_dir: Path, take_name: str) -> Path:
    return Path(episode_dir) / f"{take_name}_manifest.json"


def transcript_path(episode_dir: Path, take_name: str) -> Path:
    return Path(episode_dir) / f"{take_name}_transcript.json"


def censored_path(episode_dir: Path, take_name: str) -> Path:
    return Path(episode_dir) / f"{take_name}_censored.wav"


def detect_into(
    prepped: Path,
    episode_dir: Path,
    take_name: str,
    wordlist: WordList,
    transcriber: Transcriber,
    *,
    inset: float,
    min_confidence: float,
) -> tuple[Path, int]:
    """Transcribe `prepped`, write the manifest and transcript, return (path, spans)."""
    # Handed the cleaned take as it is: a transcriber owns the decode its model
    # needs, and WhisperX already shells out to ffmpeg for mono 16 kHz. Doing it
    # here as well only wrote a temp copy for WhisperX to convert a second time.
    transcript, manifest = transcribe_and_detect(
        str(prepped), transcriber, wordlist,
        inset=inset, min_confidence=min_confidence,
    )

    written = manifest_path(episode_dir, take_name)
    _ = written.write_text(manifest.to_json())
    _ = transcript_path(episode_dir, take_name).write_text(transcript.to_json())
    return written, len(manifest.spans)


def splice(prepped: Path, manifest: Path, episode_dir: Path, take_name: str) -> Path:
    """Render the censored take from a manifest and the prepped audio."""
    return render_file(prepped, manifest, censored_path(episode_dir, take_name))
