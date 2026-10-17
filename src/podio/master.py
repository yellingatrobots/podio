"""Master the NLE's mixdown to delivery loudness, after the pass is done.

One constant gain to the target and a true-peak limiter to catch what that
pushes over. Limiting costs loudness, so the gain is corrected by what each
render fell short and the master rendered again until it settles. Then the
same master is encoded twice: over the picture for video, and as the feed's
MP3. Both encodes are metered again, since encoding moves the true peak.
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
class Mastered:
    source: Loudness
    gain_db: float
    delivered: dict[Path, Loudness]


def default_stem(video: Path) -> Path:
    return video.with_name(f"{video.stem}_mastered")


def measure(path: Path) -> Loudness:
    return Loudness(*ffmpeg.parse_loudness(ffmpeg.run(ffmpeg.measure_command(path))))


def master(video: Path, stem: Path) -> Mastered:
    """Write STEM.mp4 and STEM.mp3 from `video`, and what each measured."""
    source = measure(video)
    gain = master_gain(source.integrated_lufs)
    mp4 = stem.with_name(f"{stem.name}.mp4")
    mp3 = stem.with_name(f"{stem.name}.mp3")

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "master.wav"
        for _ in range(MAX_PASSES):
            rendered = Loudness(
                *ffmpeg.parse_loudness(
                    ffmpeg.run(ffmpeg.master_command(video, gain, wav))
                )
            )
            if master_settled(rendered.integrated_lufs):
                break
            gain += TARGET_LUFS - rendered.integrated_lufs
        ffmpeg.run(ffmpeg.encode_video_command(video, wav, mp4))
        ffmpeg.run(ffmpeg.encode_mp3_command(wav, mp3))

    return Mastered(source, gain, {out: measure(out) for out in (mp4, mp3)})
