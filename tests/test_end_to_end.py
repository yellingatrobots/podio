"""The debug steps, run against the real ffmpeg."""

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

def make_take(path: Path):
    """A quiet steady tone with a little pink noise under it."""
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=f=1000:d=20:sample_rate=44100",
            "-f", "lavfi", "-i", "anoisesrc=d=20:c=pink:a=0.001:s=1",
            "-filter_complex",
            "[0:a]volume=-20dB[tone];[tone][1:a]amix=inputs=2:normalize=0[out]",
            "-map", "[out]", "-ac", "1", "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )


def loudness_of(path: Path) -> tuple[float, float]:
    output = ffmpeg.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128=peak=true", "-f", "null", "-"]
    )
    return ffmpeg.parse_loudness(output)


@pytest.fixture
def episode(tmp_path):
    (tmp_path / "rigs").mkdir()
    (tmp_path / "rigs" / "alex.toml").write_text(RIG)
    make_take(tmp_path / "alex.wav")
    return tmp_path


def clean(episode: Path, *extra: str) -> int:
    return main(["debug", "clean", str(episode / "alex.wav"),
                 "--rigs", str(episode / "rigs"), *extra])


def test_a_cleaned_take_lands_at_delivery_loudness(episode):
    assert clean(episode) == 0

    integrated, peak = loudness_of(episode / "alex_cleaned.wav")
    assert integrated == pytest.approx(-16.0, abs=0.5)
    assert peak <= -1.0


def test_the_cleaned_take_is_24_bit_48k_mono(episode):
    clean(episode)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,sample_rate,channels", "-of", "csv=p=0",
         str(episode / "alex_cleaned.wav")],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.strip() == "pcm_s24le,48000,1"


def test_a_dry_run_measures_but_writes_nothing(episode, capsys):
    assert clean(episode, "--dry-run") == 0
    assert sorted(p.name for p in episode.iterdir()) == ["alex.wav", "rigs"]
    assert "chain highpass=f=80" in capsys.readouterr().err


def make_video(path: Path):
    """A tiny silent-ish clip: colour bars over a 200 Hz tone."""
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15:d=2",
            "-f", "lavfi", "-i", "sine=f=200:d=2",
            "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
        ],
        check=True,
    )


def streams_of(path: Path) -> list[str]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return probe.stdout.split()


def test_mux_puts_the_censored_audio_over_the_source_video(tmp_path):
    make_video(tmp_path / "episode.mp4")
    make_take(tmp_path / "alex_censored.wav")

    out = tmp_path / "episode_censored.mov"
    assert main(["debug", "mux", str(tmp_path / "episode.mp4"),
                 str(tmp_path / "alex_censored.wav"), "--out", str(out)]) == 0
    # The picture is copied through and the wav lands intact, not re-encoded.
    assert streams_of(out) == ["mpeg4,video", "pcm_s16le,audio"]


def test_mux_names_its_output_after_the_source_when_not_told(tmp_path):
    make_video(tmp_path / "episode.mp4")
    make_take(tmp_path / "alex_censored.wav")

    assert main(["debug", "mux", str(tmp_path / "episode.mp4"),
                 str(tmp_path / "alex_censored.wav")]) == 0
    assert (tmp_path / "episode_muxed.mov").exists()
