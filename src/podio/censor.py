"""Censor a prepped take: detect the spans, then splice the tone over them.

Detection listens to the prepped take rather than the raw one — denoising and
gating measurably help the ASR — and the tone goes on last, after gain match,
so it never passes through the compressor or the gate.
"""

from __future__ import annotations

from pathlib import Path

from .bleep import render_file
from .detect import transcribe_and_detect
from .transcribe import Transcriber
from .wordlist import WordList


def manifest_path(episode_dir: Path, take_name: str) -> Path:
    return Path(episode_dir) / f"{take_name}.manifest.json"


def transcript_path(episode_dir: Path, take_name: str) -> Path:
    return Path(episode_dir) / f"{take_name}.transcript.json"


def censored_path(episode_dir: Path, take_name: str) -> Path:
    return Path(episode_dir) / f"{take_name}_censored.wav"


def is_hand_edited(manifest: Path, transcript: Path) -> bool:
    """Has this manifest been touched since detection wrote it?

    Detection writes the manifest and its transcript together and nothing but a
    human edits either afterwards, so a manifest newer than its transcript
    carries judgement that a re-run would destroy. A manifest with no transcript
    beside it has nothing to prove where it came from, so it is treated the same
    way — the cautious answer is the one that cannot lose work.
    """
    if not manifest.exists():
        return False
    if not transcript.exists():
        return True
    return manifest.stat().st_mtime > transcript.stat().st_mtime


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
    # Handed the prepped take as it is: a transcriber owns the decode its model
    # needs, and WhisperX already shells out to ffmpeg for mono 16 kHz. Doing it
    # here as well only wrote a temp copy for WhisperX to convert a second time.
    transcript, manifest = transcribe_and_detect(
        str(prepped), transcriber, wordlist,
        inset=inset, min_confidence=min_confidence,
    )

    written = manifest_path(episode_dir, take_name)
    # Transcript last: is_hand_edited reads their order, and detection must
    # never leave behind a pair that looks hand-edited.
    written.write_text(manifest.to_json())
    transcript_path(episode_dir, take_name).write_text(transcript.to_json())
    return written, len(manifest.spans)


def splice(prepped: Path, manifest: Path, episode_dir: Path, take_name: str) -> Path:
    """Render the censored take from a manifest and the prepped audio."""
    return render_file(prepped, manifest, censored_path(episode_dir, take_name))
