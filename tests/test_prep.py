"""`podio prep`: one file in, the same kind of file out, ready for production."""

import shutil
import subprocess
from pathlib import Path

import pytest

from podio import ffmpeg
from podio.cli import main

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH"
)

RIG = """
[[stage]]
name = "highpass"
f = 80

[[stage]]
name = "compressor"
threshold_db = -18
ratio = 3
"""


def make_take(path: Path, seconds: int = 8):
    """A quiet steady tone with a little pink noise under it."""
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=f=1000:d={seconds}:sample_rate=44100",
            "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:a=0.001:s=1",
            "-filter_complex",
            "[0:a]volume=-20dB[tone];[tone][1:a]amix=inputs=2:normalize=0[out]",
            "-map", "[out]", "-ac", "1", "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )


def make_video(path: Path, seconds: int = 4):
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=15:d={seconds}",
            "-f", "lavfi", "-i", f"sine=f=200:d={seconds}",
            "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
        ],
        check=True,
    )


def loudness_of(path: Path) -> tuple[float, float]:
    return ffmpeg.parse_loudness(ffmpeg.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128=peak=true", "-f", "null", "-"]
    ))


def streams_of(path: Path) -> list[str]:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.split()


class EmptyTranscriber:
    def __init__(self, **_kwargs):
        pass

    def transcribe(self, _audio_path):
        return []


class NoTranscriber:
    def __init__(self, **_kwargs):
        raise AssertionError("--no-bleep must not load WhisperX")


@pytest.fixture
def episode(tmp_path, monkeypatch):
    rigs = tmp_path / "rigs"
    rigs.mkdir()
    for name in ("ian", "josh"):
        (rigs / f"{name}.toml").write_text(RIG)
    monkeypatch.setattr("podio.prep.WhisperXTranscriber", EmptyTranscriber)
    episode = tmp_path / "ep"
    episode.mkdir()
    return episode


def prep(episode: Path, *argv: str) -> int:
    return main(["prep", "--rigs", str(episode.parent / "rigs"), *argv])


def test_a_wav_comes_out_a_wav_at_delivery_loudness_and_nothing_else(episode):
    make_take(episode / "ian.wav")

    assert prep(episode, str(episode / "ian.wav")) == 0

    out = episode / "ian_prepped.wav"
    integrated, peak = loudness_of(out)
    assert integrated == pytest.approx(-16.0, abs=0.5)
    assert peak <= -1.0
    assert sorted(p.name for p in episode.iterdir()) == ["ian.wav", "ian_prepped.wav"]


def test_a_video_comes_out_the_same_container_with_its_picture_copied(episode):
    make_video(episode / "ian.mp4")

    assert prep(episode, str(episode / "ian.mp4")) == 0

    out = episode / "ian_prepped.mp4"
    assert streams_of(out) == ["mpeg4,video", "aac,audio"]
    integrated, peak = loudness_of(out)
    assert integrated == pytest.approx(-16.0, abs=1.0)
    assert peak <= -1.0


def test_a_wav_beside_the_video_supplies_the_audio(episode):
    make_video(episode / "ian.mp4")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=d=4",
         "-ac", "1", str(episode / "ian.wav")],
        check=True,
    )
    # Digital silence has no noise floor: failing on it proves the wav was read.
    assert prep(episode, str(episode / "ian.mp4")) == 1


def test_no_bleep_never_loads_whisperx(episode, monkeypatch):
    monkeypatch.setattr("podio.prep.WhisperXTranscriber", NoTranscriber)
    make_take(episode / "ian.wav")

    assert prep(episode, "--no-bleep", str(episode / "ian.wav")) == 0
    assert (episode / "ian_prepped.wav").exists()


def test_keep_temp_keeps_the_intermediates(episode, tmp_path):
    make_take(episode / "ian.wav")
    kept = tmp_path / "kept"

    assert prep(episode, "--keep-temp", str(kept), str(episode / "ian.wav")) == 0

    names = {p.name for p in (kept / "ian").iterdir()}
    assert {"ian_cleaned.wav", "ian_censored.wav", "ian_manifest.json",
            "ian_transcript.json", "audio_analysis.toml"} <= names


def test_a_file_with_no_rig_stops_everything_before_any_work(episode):
    make_take(episode / "ian.wav")
    make_take(episode / "DJI_0042.wav")

    assert prep(episode, str(episode / "ian.wav"), str(episode / "DJI_0042.wav")) == 1
    assert not (episode / "ian_prepped.wav").exists()


def test_a_missing_file_stops_everything_before_any_work(episode):
    make_take(episode / "ian.wav")

    assert prep(episode, str(episode / "ian.wav"), str(episode / "josh.wav")) == 1
    assert not (episode / "ian_prepped.wav").exists()


def test_one_file_failing_does_not_stop_the_others(episode):
    make_take(episode / "ian.wav")
    (episode / "josh.wav").write_bytes(b"not audio")

    assert prep(episode, "-j", "1", str(episode / "josh.wav"), str(episode / "ian.wav")) == 1
    assert (episode / "ian_prepped.wav").exists()
    assert not (episode / "josh_prepped.wav").exists()


def test_files_run_in_parallel_processes(episode):
    # Separate processes do not see the monkeypatched transcriber, hence --no-bleep.
    make_take(episode / "ian.wav")
    make_take(episode / "josh.wav")

    assert prep(episode, "--no-bleep", str(episode / "ian.wav"), str(episode / "josh.wav")) == 0
    assert (episode / "ian_prepped.wav").exists()
    assert (episode / "josh_prepped.wav").exists()
