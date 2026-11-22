"""Bring audio to delivery loudness: -16 LUFS integrated, under -1 dBTP.

One constant gain to the target and a true-peak limiter to catch what that
pushes over. Limiting costs loudness, so the gain is corrected by what each
render fell short and the audio rendered again until it settles. Encoding
moves the true peak, so whatever is encoded afterwards is metered again.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg
from .levels import TARGET_LUFS, master_gain, master_settled

#: Each pass is a full render; raw speech settles in two or three.
MAX_PASSES = 4


@dataclass(frozen=True)
class Loudness:
    integrated_lufs: float
    true_peak_db: float


@dataclass(frozen=True)
class Leveled:
    gain_db: float
    rendered: Loudness


@dataclass(frozen=True)
class Mastered:
    source: Loudness
    gain_db: float
    delivered: dict[Path, Loudness]


def default_stem(video: Path) -> Path:
    return video.with_name(f"{video.stem}_mastered")


def measure(path: Path) -> Loudness:
    return Loudness(*ffmpeg.parse_loudness(ffmpeg.run(ffmpeg.measure_command(path))))


def level(source: Path, measured: Loudness, destination: Path) -> Leveled:
    """Write `source` to `destination` (24-bit wav) at delivery loudness.

    `measured` is what `source` meters at, passed in because the caller has
    usually just metered it on the way past.
    """
    gain = master_gain(measured.integrated_lufs)
    for _ in range(MAX_PASSES):
        rendered = Loudness(
            *ffmpeg.parse_loudness(
                ffmpeg.run(ffmpeg.master_command(source, gain, destination))
            )
        )
        if master_settled(rendered.integrated_lufs):
            break
        gain += TARGET_LUFS - rendered.integrated_lufs
    return Leveled(gain, rendered)


def master(video: Path, stem: Path) -> Mastered:
    """Write STEM.mp4 and STEM.mp3 from `video`, and what each measured."""
    source = measure(video)
    mp4 = stem.with_name(f"{stem.name}.mp4")
    mp3 = stem.with_name(f"{stem.name}.mp3")

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "master.wav"
        leveled = level(video, source, wav)
        ffmpeg.run(ffmpeg.encode_video_command(video, wav, mp4))
        ffmpeg.run(ffmpeg.encode_mp3_command(wav, mp3))

    return Mastered(
        source, leveled.gain_db, {out: measure(out) for out in (mp4, mp3)}
    )
