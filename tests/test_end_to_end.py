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


def test_a_prepped_take_lands_on_the_working_level(episode):
    assert run_on(episode) == 0

    integrated, peak = loudness_of(episode / "alex_prepped.wav")
    assert integrated == pytest.approx(-24.0, abs=0.5)
    assert peak < -2.0


def test_the_prepped_take_is_24_bit_48k_mono(episode):
    run_on(episode)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,sample_rate,channels", "-of", "csv=p=0",
         str(episode / "alex_prepped.wav")],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.strip() == "pcm_s24le,48000,1"


def test_the_run_records_what_it_measured(episode):
    run_on(episode)
    sidecar = tomllib.loads((episode / "audio.analysis.toml").read_text())

    assert sidecar["working_level_db"] == -24.0
    assert sidecar["peak_ceiling_db"] == -2.0
    assert sidecar["working_rate_hz"] == 48000
    assert sidecar["alex"]["output"] == "alex_prepped.wav"
    assert sidecar["alex"]["chain"].startswith("highpass=f=80")
    assert not sidecar["alex"]["clamped"]


def test_an_audition_writes_a_separate_short_file(episode):
    assert run_on(episode, "--range", "5+3") == 0

    audition = episode / "alex_audition.wav"
    assert audition.exists()
    assert not (episode / "alex_prepped.wav").exists()


def test_a_dry_run_measures_but_writes_nothing(episode):
    assert run_on(episode, "--dry-run") == 0
    assert not (episode / "alex_prepped.wav").exists()
    assert not (episode / "audio.analysis.toml").exists()


def full_pass(episode: Path, *extra: str) -> int:
    return main(
        ["run", "-c", str(episode / "audio.toml"), "--rigs", str(episode / "rigs"), *extra]
    )


def test_a_run_with_censoring_off_stops_after_the_prepped_take(episode):
    (episode / "audio.toml").write_text(EPISODE + "\n[censor]\nenabled = false\n")

    assert full_pass(episode) == 0
    assert (episode / "alex_prepped.wav").exists()
    assert not (episode / "alex_censored.wav").exists()
    assert not (episode / "alex.manifest.json").exists()


def test_an_audition_is_never_censored(episode):
    """A slice's manifest would be timed against the slice, not the take."""
    assert full_pass(episode, "--range", "0+2") == 0
    assert (episode / "alex_audition.wav").exists()
    assert not (episode / "alex.manifest.json").exists()


def test_a_run_refuses_to_discard_a_hand_edited_manifest(episode):
    edited = '{"spans": [{"start": 1.0, "end": 1.2}]}'
    (episode / "alex.manifest.json").write_text(edited)

    assert full_pass(episode) == 1
    assert (episode / "alex.manifest.json").read_text() == edited
    assert not (episode / "alex_censored.wav").exists()


def test_a_dry_run_censors_nothing(episode):
    assert full_pass(episode, "--dry-run") == 0
    assert not (episode / "alex_prepped.wav").exists()
    assert not (episode / "alex.manifest.json").exists()


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
    assert main(["mux", str(tmp_path / "episode.mp4"),
                 str(tmp_path / "alex_censored.wav"), "--out", str(out)]) == 0
    # The picture is copied through and the wav lands intact, not re-encoded.
    assert streams_of(out) == ["mpeg4,video", "pcm_s16le,audio"]


def test_mux_names_its_output_after_the_source_when_not_told(tmp_path):
    make_video(tmp_path / "episode.mp4")
    make_take(tmp_path / "alex_censored.wav")

    assert main(["mux", str(tmp_path / "episode.mp4"),
                 str(tmp_path / "alex_censored.wav")]) == 0
    assert (tmp_path / "episode_muxed.mov").exists()
