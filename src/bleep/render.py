"""Stage 6: the bleep renderer.

Splices a 1 kHz tone over each censor span. The sample-level work is a pure
function over mono PCM (unit-tested); the file I/O wrapper (ffmpeg decode +
WAV write) lives alongside it and is verified by a real render.
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

INT16_MIN, INT16_MAX = -32768, 32767


def bleep_pcm(
    samples: Sequence[int],
    sample_rate: int,
    spans: Iterable[Tuple[float, float]],
    *,
    freq: float = 1000.0,
    amplitude: int = 12000,
) -> array:
    """Return a copy of `samples` with a sine tone over each (start, end) span.

    Samples outside every span are left exactly as they were. The tone's phase
    restarts at each span's onset so it begins at zero. The copy is a 16-bit PCM
    ``array`` (two bytes per sample), not a Python list, so a long file stays a
    few hundred MB rather than several GB.
    """
    out = array("h", samples)
    for start, end in spans:
        i0 = max(0, round(start * sample_rate))
        i1 = min(len(out), round(end * sample_rate))
        for i in range(i0, i1):
            t = (i - i0) / sample_rate
            value = int(amplitude * math.sin(2 * math.pi * freq * t))
            out[i] = max(INT16_MIN, min(INT16_MAX, value))
    return out


def render_file(
    audio_src,
    manifest_path,
    out_path,
    *,
    freq: float = 1000.0,
    amplitude: int = 12000,
) -> Path:
    """Bleep `audio_src` per the spans in `manifest_path`, write a WAV to `out_path`.

    The source is decoded to mono 16-bit PCM at its native rate (full quality,
    not the 16 kHz ASR downsample), bleeped, and written back as a WAV.
    """
    spans = _load_spans(manifest_path)
    sample_rate, samples = _decode_pcm(audio_src)
    out = bleep_pcm(samples, sample_rate, spans, freq=freq, amplitude=amplitude)
    return _write_wav(out_path, sample_rate, out)


def _load_spans(manifest_path) -> List[Tuple[float, float]]:
    data = json.loads(Path(manifest_path).read_text())
    return [(s["start"], s["end"]) for s in data.get("spans", [])]


def _decode_pcm(src) -> Tuple[int, array]:
    """Decode `src` to mono 16-bit PCM via ffmpeg; return (sample_rate, samples)."""
    with tempfile.TemporaryDirectory() as tmp:
        decoded = str(Path(tmp) / "decoded.wav")
        _run_ffmpeg(
            ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-f", "wav", decoded],
            src,
        )
        with wave.open(decoded, "rb") as w:
            sample_rate = w.getframerate()
            raw = w.readframes(w.getnframes())
    samples = array("h")
    samples.frombytes(raw)
    return sample_rate, samples


def _run_ffmpeg(cmd: Sequence[str], src) -> None:
    """Run ffmpeg, surfacing its stderr if it fails instead of a bare traceback."""
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"ffmpeg failed to decode {src}:\n{e.stderr.decode(errors='replace')}"
        ) from e


def _write_wav(out_path, sample_rate: int, samples: array) -> Path:
    """Write an already-clamped 16-bit mono PCM `array` to `out_path` as WAV."""
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())
    return Path(out_path)
