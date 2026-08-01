"""Building ffmpeg command lines and reading what ffmpeg says back.

Cleaning is an ffprobe for the take's rate, then three passes. The middle pass
is the only expensive one: ebur128 meters while passing audio through, so the
chain runs once rather than twice.
"""

import re
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path

from .levels import db_to_linear

WINDOW_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-inf)")

WINDOW_SECONDS = 1
#: WhisperX expects 16 kHz mono. Only the ASR input is downsampled.
ASR_RATE = 16_000
#: Where in the sorted per-window levels the noise floor is taken from. Low
#: enough to sit among the windows where nobody is talking, high enough not to
#: land on the handful that are digitally silent.
FLOOR_PERCENTILE = 0.10
#: Below this a window is not room tone, it is nothing. Excluded so that edits,
#: dropouts and muted passages cannot drag the estimate down.
SILENCE_LIMIT_DB = -100.0
INTEGRATED = re.compile(r"^\s+I:\s*(-?[\d.]+) LUFS", re.MULTILINE)
TRUE_PEAK = re.compile(r"^\s+Peak:\s*(-?[\d.]+) dBFS", re.MULTILINE)
RANGE = re.compile(r"^(\d+(?::\d+){0,2}(?:\.\d+)?)\+(\d+(?:\.\d+)?)$")
#: Containers that hold PCM, so a finished WAV can be muxed in untouched. MP4
#: is not one of them in any player worth relying on.
PCM_CONTAINERS = {".mov", ".mkv"}

Audition = tuple[float, float] | None


def parse_range(text: str) -> tuple[float, float]:
    """Read an audition range: START+SECONDS, e.g. 21:30+45."""
    match = RANGE.match(text.strip())
    if not match:
        raise ValueError(
            f"cannot read {text!r} as a range; expected START+SECONDS "
            f"such as 21:30+45, 300+30 or 1:02:03+10"
        )
    start, duration = match.groups()
    seconds = 0.0
    for part in start.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds, float(duration)


def parse_noise_floor(output: str) -> float:
    """Estimate the noise floor from per-window levels.

    A single figure over a whole take is worthless: one digitally silent moment
    drags it to -inf, and a censored or edited take is full of them. Taking a
    low percentile of one-second windows instead describes the room during the
    passages where nobody is speaking, which is what a gate needs to know.
    """
    levels = sorted(
        value
        for value in (float(m) for m in WINDOW_RMS.findall(output))
        if value > SILENCE_LIMIT_DB
    )
    if not levels:
        raise ValueError(
            "could not estimate a noise floor; every window was silent or the "
            "take is empty"
        )
    return levels[int(len(levels) * FLOOR_PERCENTILE)]


def parse_loudness(output: str) -> tuple[float, float]:
    integrated = INTEGRATED.findall(output)
    peak = TRUE_PEAK.findall(output)
    if not integrated or not peak:
        raise ValueError("ffmpeg reported no loudness summary")
    return float(integrated[-1]), float(peak[-1])


def probe_sample_rate(source) -> int:
    """The sample rate of `source`'s first audio stream."""
    command = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]
    result = subprocess.run(command, capture_output=True)
    reported = _text(result.stdout).strip()
    if result.returncode != 0 or not reported.isdigit():
        raise RuntimeError(
            f"could not read a sample rate from {source}:\n"
            f"  {' '.join(command)}\n\n{_text(result.stderr).strip()}"
        )
    return int(reported)


def _base(source: Path, audition: Audition) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y"]
    if audition:
        start, duration = audition
        cmd += ["-ss", f"{start:g}", "-t", f"{duration:g}"]
    return cmd + ["-i", str(source)]


def analyse_command(source: Path, audition: Audition, sample_rate: int) -> list[str]:
    """Pass 1: report a level per one-second window, write no audio.

    Windows are sized from the take's own rate. Nothing is resampled: this pass
    measures and discards, and `parse_noise_floor` takes a percentile over the
    windows, so a window that is not a second wide moves the estimate.
    """
    chain = (
        f"asetnsamples=n={sample_rate * WINDOW_SECONDS}"
        f",astats=metadata=1:reset=1"
        f",ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )
    return _base(source, audition) + ["-af", chain, "-f", "null", "-"]


def render_command(
    source: Path, chain: str, destination: Path, audition: Audition
) -> list[str]:
    """Pass 2: run the chain into a float working file, metering as it goes."""
    return _base(source, audition) + [
        "-af",
        f"{chain},ebur128=peak=true",
        "-c:a",
        "pcm_f32le",
        str(destination),
    ]


def apply_gain_command(
    source: Path, destination: Path, gain_db: float, limiter: bool, ceiling_db: float
) -> list[str]:
    """Pass 3: the gain match, and the ceiling guard if this take asked for it."""
    chain = f"volume={gain_db:g}dB"
    if limiter:
        chain += f",alimiter=limit={db_to_linear(ceiling_db):.5f}:level=false"
    return _base(source, None) + ["-af", chain, "-c:a", "pcm_s24le", str(destination)]


def normalize_command(source: Path, destination: Path, rate: int) -> list[str]:
    """Decode `source` to mono PCM WAV at `rate` Hz — what the ASR model wants."""
    return [
        "ffmpeg", "-y", "-i", str(source),
        "-ac", "1", "-ar", str(rate),
        "-f", "wav", str(destination),
    ]


def normalize(source, destination, *, rate: int = ASR_RATE) -> Path:
    """Decode `source` for the ASR model. The take itself is left untouched."""
    _execute(normalize_command(Path(source), Path(destination), rate))
    return Path(destination)


def decode_command(source: Path, destination: Path) -> list[str]:
    """Decode `source` to mono 32-bit WAV at its own sample rate.

    32-bit because a prepped take is 24-bit and Python's ``array`` has no
    three-byte type; s32 is the smallest that holds a 24-bit sample without
    loss, and ffmpeg converts back down on the way out.
    """
    return [
        "ffmpeg", "-y", "-i", str(source),
        "-ac", "1", "-c:a", "pcm_s32le", "-f", "wav", str(destination),
    ]


def _splice_input(sample_rate: int) -> list[str]:
    """Args for reading a spliced take off stdin.

    The splice arrives as the raw bytes of a mono 32-bit ``array``, which is
    native-endian; every platform podio runs on is little-endian, so ``s32le``
    describes it. Feeding it in saves writing a full-length intermediate WAV and
    reading it back — an hour-long take is about half a gigabyte each way.
    """
    return ["-f", "s32le", "-ar", str(sample_rate), "-ac", "1", "-i", "-"]


def write_pcm_command(sample_rate: int, destination: Path) -> list[str]:
    """Read the splice on stdin, write it at 24-bit — the depth a take arrives at."""
    return [
        "ffmpeg", "-y",
        *_splice_input(sample_rate),
        "-c:a", "pcm_s24le",
        str(destination),
    ]


def mux_pcm_command(source: Path, sample_rate: int, destination: Path) -> list[str]:
    """Read the splice on stdin, put it over `source`'s video."""
    return [
        "ffmpeg", "-y",
        "-i", str(source),
        *_splice_input(sample_rate),
        "-map", "0:v?", "-map", "1:a",
        "-c:v", "copy", "-c:a", _audio_codec(destination),
        "-shortest",
        str(destination),
    ]


def write_pcm(samples, sample_rate: int, destination) -> Path:
    """Write a spliced take straight to `destination` at 24-bit."""
    _execute(write_pcm_command(sample_rate, Path(destination)), samples.tobytes())
    return Path(destination)


def mux_pcm(source, samples, sample_rate: int, destination) -> Path:
    """Put a spliced take over `source`'s video, copying the picture through."""
    _execute(
        mux_pcm_command(Path(source), sample_rate, Path(destination)),
        samples.tobytes(),
    )
    return Path(destination)


def decode_pcm(source) -> tuple[int, array]:
    """Decode `source` to mono 32-bit PCM; return (sample_rate, samples).

    Native rate, not the ASR downsample — this is the audio that gets bleeped
    and written back out, so it keeps the quality it arrived with.
    """
    with tempfile.TemporaryDirectory() as tmp:
        decoded = Path(tmp) / "decoded.wav"
        _execute(decode_command(Path(source), decoded))
        with wave.open(str(decoded), "rb") as w:
            sample_rate = w.getframerate()
            raw = w.readframes(w.getnframes())
    samples = array("i")
    if samples.itemsize != 4:
        raise RuntimeError(f"expected 4-byte ints, got {samples.itemsize}")
    samples.frombytes(raw)
    return sample_rate, samples


def _audio_codec(destination: Path) -> str:
    """What the mux can write: PCM where the container carries it, else AAC.

    A container that carries PCM keeps the audio bit-for-bit; anywhere else it
    has to be encoded, and the censored track loses a generation.
    """
    return "pcm_s24le" if Path(destination).suffix.lower() in PCM_CONTAINERS else "aac"


def mux_command(source: Path, audio: Path, destination: Path) -> list[str]:
    """ffmpeg args to put `audio` over `source`'s video into `destination`.

    `audio` is a finished file, so a PCM container copies it rather than
    re-encoding: it is already at the depth it should be.
    """
    codec = "copy" if Path(destination).suffix.lower() in PCM_CONTAINERS else "aac"
    return [
        "ffmpeg", "-y",
        "-i", str(source),
        "-i", str(audio),
        "-map", "0:v?", "-map", "1:a",
        "-c:v", "copy", "-c:a", codec,
        "-shortest",
        str(destination),
    ]


def mux(source, audio, destination) -> Path:
    """Replace `source`'s audio track with `audio`, copying any video through."""
    _execute(mux_command(Path(source), Path(audio), Path(destination)))
    return Path(destination)


def _execute(
    command: list[str], stdin: bytes | None = None
) -> subprocess.CompletedProcess:
    """Run ffmpeg, optionally feeding it `stdin`. Pipes stay binary; only the
    diagnostics ffmpeg writes are decoded, and never strictly."""
    result = subprocess.run(command, input=stdin, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed:\n  {' '.join(command)}\n\n{_text(result.stderr).strip()}"
        )
    return result


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def run(command: list[str]) -> str:
    """Run ffmpeg, returning stderr — where its summaries are printed."""
    return _text(_execute(command).stderr)


def run_stdout(command: list[str]) -> str:
    """Run ffmpeg, returning stdout — where ametadata writes."""
    return _text(_execute(command).stdout)
