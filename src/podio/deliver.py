"""Bring audio to delivery loudness: -16 LUFS integrated, under -1 dBTP.

One constant gain to the target and a true-peak limiter to catch what that
pushes over. Limiting costs loudness, so the gain is corrected by what each
render fell short and the audio rendered again until it settles. Encoding
moves the true peak, so an encoded file is metered again with `measure`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg
from .levels import TARGET_LUFS, delivery_gain, delivery_settled

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


def measure(path: Path) -> Loudness:
    return Loudness(*ffmpeg.parse_loudness(ffmpeg.run(ffmpeg.measure_command(path))))


def level(source: Path, measured: Loudness, destination: Path) -> Leveled:
    """Write `source` to `destination` (24-bit wav) at delivery loudness.

    `measured` is what `source` meters at, passed in because the caller has
    just metered it on the way past.
    """
    gain = delivery_gain(measured.integrated_lufs)
    for _ in range(MAX_PASSES):
        rendered = Loudness(
            *ffmpeg.parse_loudness(
                ffmpeg.run(ffmpeg.level_command(source, gain, destination))
            )
        )
        if delivery_settled(rendered.integrated_lufs):
            break
        gain += TARGET_LUFS - rendered.integrated_lufs
    return Leveled(gain, rendered)
