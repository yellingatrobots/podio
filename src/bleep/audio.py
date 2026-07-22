"""Audio ingest — decode/normalize to what the ASR model expects."""

from __future__ import annotations

import subprocess
from pathlib import Path

TARGET_RATE = 16_000  # WhisperX/Whisper expect 16 kHz mono


def normalize_audio(src, dst, *, rate: int = TARGET_RATE) -> Path:
    """Decode `src` to mono PCM WAV at `rate` Hz using ffmpeg.

    Only the ASR input is downsampled; the original file is left untouched so a
    later stage can bleep it at full quality.
    """
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-ac", "1", "-ar", str(rate),
        "-f", "wav", str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"ffmpeg failed to decode {src}:\n{e.stderr.decode(errors='replace')}"
        ) from e
    return Path(dst)
