import math
import shutil
import subprocess

import pytest

from podio.bleep import bleep_pcm, render_file
from podio.ffmpeg import decode_command, mux_command, wav24_command


def test_mux_command_muxes_censored_audio_over_source_video():
    cmd = mux_command("in.mp4", "/tmp/censored.wav", "out.mp4")

    assert cmd == [
        "ffmpeg", "-y",
        "-i", "in.mp4",          # input 0: the original (video kept)
        "-i", "/tmp/censored.wav",  # input 1: the bleeped audio
        "-map", "0:v?",          # copy any video stream(s) from the source
        "-map", "1:a",           # take audio only from the censored track
        "-c:v", "copy",          # never re-encode the video
        "-c:a", "aac",           # encode the replacement audio
        "-shortest",
        "out.mp4",
    ]


def test_bleep_replaces_samples_inside_span_and_leaves_the_rest():
    sr = 8000
    samples = [5] * sr  # 1s of a constant non-zero background
    out = bleep_pcm(samples, sr, [(0.25, 0.75)], freq=1000, amplitude=10000)

    assert len(out) == sr
    assert list(out[:2000]) == [5] * 2000        # before the span: untouched
    assert list(out[6000:]) == [5] * 2000        # after the span: untouched
    assert any(s != 5 for s in out[2000:6000])   # inside: a tone was written


def test_tone_is_a_1khz_sine_at_the_given_amplitude():
    sr = 8000
    out = bleep_pcm([0] * sr, sr, [(0.25, 0.75)], freq=1000, amplitude=10000)

    # Span starts at sample 2000. Phase restarts there, so the onset is 0 and a
    # quarter-period later (2 samples, since 1kHz @ 8kHz = 8 samples/cycle) the
    # sine peaks at +amplitude.
    assert out[2000] == 0
    assert out[2002] == 10000
    assert max(out) == 10000
    assert min(out) == -10000


def test_samples_are_carried_at_32_bit_so_24_bit_audio_survives():
    """A 24-bit take does not fit in the int16 array the splice used to use."""
    sr = 8000
    loud = 8_000_000  # beyond int16, well inside 24-bit
    out = bleep_pcm([loud] * sr, sr, [], freq=1000, amplitude=1000)

    assert out.typecode == "i"
    assert out.itemsize == 4
    assert list(out[:3]) == [loud, loud, loud]


def test_the_tone_clamps_to_the_32_bit_range_not_the_16_bit_one():
    sr = 8000
    huge = 3_000_000_000  # past int32; must clamp, not wrap
    out = bleep_pcm([0] * sr, sr, [(0.0, 1.0)], freq=1000, amplitude=huge)

    assert max(out) == 2_147_483_647
    assert min(out) == -2_147_483_648


def test_decode_asks_ffmpeg_for_32_bit_samples():
    assert "pcm_s32le" in decode_command("in.wav", "out.wav")


def test_a_wav_render_is_written_as_24_bit():
    assert "pcm_s24le" in wav24_command("spliced.wav", "out.wav")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_rendering_a_24_bit_take_keeps_its_depth(tmp_path):
    source = tmp_path / "take.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=200:duration=1:sample_rate=48000",
         "-c:a", "pcm_s24le", str(source)],
        check=True,
    )
    manifest = tmp_path / "m.json"
    manifest.write_text('{"spans": [{"start": 0.2, "end": 0.4}]}')
    out = tmp_path / "censored.wav"

    render_file(source, manifest, out)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,sample_rate,channels", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.strip() == "pcm_s24le,48000,1"
