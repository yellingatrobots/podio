"""One test that actually runs ffmpeg, proving the three passes chain up."""

import shutil
import subprocess
import tomllib
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

EPISODE = """
working_level_db = -20.0
peak_ceiling_db = -3.0

[takes.alex]
file = "alex.wav"
rig = "booth"
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
    (tmp_path / "rigs" / "booth.toml").write_text(RIG)
    (tmp_path / "audio.toml").write_text(EPISODE)
    make_take(tmp_path / "alex.wav")
    return tmp_path


def run_on(episode: Path, *extra: str) -> int:
    return main(
        ["clean", "-c", str(episode / "audio.toml"), "--rigs", str(episode / "rigs"), *extra]
    )


def test_a_clean_track_lands_on_the_working_level(episode):
    assert run_on(episode) == 0

    integrated, peak = loudness_of(episode / "alex_clean.wav")
    assert integrated == pytest.approx(-20.0, abs=0.5)
    assert peak < -3.0


def test_the_clean_track_is_24_bit_48k_mono(episode):
    run_on(episode)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,sample_rate,channels", "-of", "csv=p=0",
         str(episode / "alex_clean.wav")],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.strip() == "pcm_s24le,48000,1"


def test_the_run_records_what_it_measured(episode):
    run_on(episode)
    sidecar = tomllib.loads((episode / "audio.analysis.toml").read_text())

    assert sidecar["working_level_db"] == -20.0
    assert sidecar["alex"]["output"] == "alex_clean.wav"
    assert sidecar["alex"]["chain"].startswith("aresample=48000,highpass=f=80")
    assert not sidecar["alex"]["clamped"]


def test_an_audition_writes_a_separate_short_file(episode):
    assert run_on(episode, "--range", "5+3") == 0

    audition = episode / "alex_audition.wav"
    assert audition.exists()
    assert not (episode / "alex_clean.wav").exists()


def test_a_dry_run_measures_but_writes_nothing(episode):
    assert run_on(episode, "--dry-run") == 0
    assert not (episode / "alex_clean.wav").exists()
    assert not (episode / "audio.analysis.toml").exists()
