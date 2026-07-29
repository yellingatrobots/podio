"""Splice the tone over every span in a manifest.

The sample-level work is a pure function over mono PCM (unit-tested). Decoding
and muxing belong to `ffmpeg`; this module deals in samples and WAV files.
"""

from __future__ import annotations

import json
import math
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from . import ffmpeg
from .levels import TONE_LEVEL_DB, tone_amplitude

INT32_MIN, INT32_MAX = -2_147_483_648, 2_147_483_647
#: The tone's peak sample value, fixed at TONE_LEVEL_DB.
TONE_AMPLITUDE = tone_amplitude(TONE_LEVEL_DB, INT32_MAX)


def bleep_pcm(
    samples: Sequence[int],
    sample_rate: int,
    spans: Iterable[Tuple[float, float]],
    *,
    freq: float = 1000.0,
    amplitude: int = TONE_AMPLITUDE,
) -> array:
    """Return a copy of `samples` with a sine tone over each (start, end) span.

    Samples outside every span are left exactly as they were. The tone's phase
    restarts at each span's onset so it begins at zero. The copy is a 32-bit PCM
    ``array`` (four bytes per sample), not a Python list, so a long take stays a
    few hundred MB rather than several GB.
    """
    out = array("i", samples)
    for start, end in spans:
        i0 = max(0, round(start * sample_rate))
        i1 = min(len(out), round(end * sample_rate))
        for i in range(i0, i1):
            t = (i - i0) / sample_rate
            value = int(amplitude * math.sin(2 * math.pi * freq * t))
            out[i] = max(INT32_MIN, min(INT32_MAX, value))
    return out


def render_file(
    audio_src,
    manifest_path,
    out_path,
    *,
    freq: float = 1000.0,
    amplitude: int = TONE_AMPLITUDE,
) -> Path:
    """Bleep `audio_src` per the spans in `manifest_path`, write it to `out_path`.

    The source is decoded to mono 32-bit PCM at its native rate (full quality,
    not the 16 kHz ASR downsample) and bleeped. A ``.wav`` `out_path` is written
    as 24-bit; any other extension (e.g. ``.mp4``, ``.m4a``) is produced by
    muxing the bleeped audio back over the source — the video stream is copied
    through untouched and only the audio is replaced.

    Both paths go out through ffmpeg: the splice is written 32-bit and ffmpeg
    converts it, which keeps the three-byte packing 24-bit WAV needs out of
    Python, where it would mean a per-sample loop over the whole take.
    """
    spans = _load_spans(manifest_path)
    sample_rate, samples = ffmpeg.decode_pcm(audio_src)
    out = bleep_pcm(samples, sample_rate, spans, freq=freq, amplitude=amplitude)

    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as tmp:
        spliced = Path(tmp) / "spliced.wav"
        write_wav(spliced, sample_rate, out)
        if out_path.suffix.lower() == ".wav":
            return ffmpeg.to_wav24(spliced, out_path)
        return ffmpeg.mux(audio_src, spliced, out_path)


def _load_spans(manifest_path) -> List[Tuple[float, float]]:
    data = json.loads(Path(manifest_path).read_text())
    return [(s["start"], s["end"]) for s in data.get("spans", [])]


def write_wav(out_path, sample_rate: int, samples: array) -> Path:
    """Write an already-clamped 32-bit mono PCM `array` to `out_path` as WAV.

    An intermediate: ffmpeg converts it to the depth the caller asked for.
    """
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(4)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())
    return Path(out_path)
