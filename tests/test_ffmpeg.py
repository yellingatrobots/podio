from pathlib import Path

import pytest

from podio.ffmpeg import (
    FFMPEG_VARIABLE,
    analyse_command,
    encode_video_command,
    level_command,
    measure_command,
    executable,
    parse_loudness,
    parse_noise_floor,
    render_command,
)


def test_executable_is_whatever_is_on_the_path_by_default():
    assert executable() == "ffmpeg"


def test_executable_prefers_the_one_the_package_baked_in(tmp_path, monkeypatch):
    """The installed entry point runs from episode directories, where the
    ambient ffmpeg is whatever the machine has rather than the pinned one."""
    baked = tmp_path / "ffmpeg"
    baked.write_text("#!/bin/sh\n")
    baked.chmod(0o755)
    monkeypatch.setenv(FFMPEG_VARIABLE, str(baked))
    assert executable() == str(baked)


def test_executable_falls_back_when_the_baked_path_has_gone(tmp_path, monkeypatch):
    """A nix store path moves when the flake is updated, and a stale install
    should still be able to clean an episode."""
    monkeypatch.setenv(FFMPEG_VARIABLE, str(tmp_path / "vanished" / "ffmpeg"))
    assert executable() == "ffmpeg"


def test_commands_run_the_resolved_executable(tmp_path, monkeypatch):
    baked = tmp_path / "ffmpeg"
    baked.write_text("#!/bin/sh\n")
    baked.chmod(0o755)
    monkeypatch.setenv(FFMPEG_VARIABLE, str(baked))
    assert analyse_command(Path("ian.wav"))[0] == str(baked)

def windows(*levels: str) -> str:
    return "".join(
        f"frame:{i}\nlavfi.astats.Overall.RMS_level={v}\n"
        for i, v in enumerate(levels)
    )


QUIET_TO_LOUD = windows(
    "-70.0", "-69.0", "-68.0", "-60.0", "-50.0",
    "-40.0", "-30.0", "-20.0", "-15.0", "-10.0",
)

EBUR128_OUTPUT = """
[Parsed_ebur128_0 @ 0x11] t: 1.4 M: -30.0 S: -120.7 I: -99.9 LUFS LRA: 0.0 LU
[Parsed_ebur128_0 @ 0x11] t: 2.4 M: -28.0 S: -120.7 I: -28.1 LUFS LRA: 0.0 LU
[Parsed_ebur128_0 @ 0x11] Summary:

  Integrated loudness:
    I:         -24.0 LUFS
    Threshold: -39.0 LUFS

  Loudness range:
    LRA:        19.9 LU
    Threshold: -48.9 LUFS

  True peak:
    Peak:       -4.0 dBFS
"""


def test_noise_floor_is_a_low_percentile_of_the_windows():
    assert parse_noise_floor(QUIET_TO_LOUD) == pytest.approx(-69.0)


def test_noise_floor_ignores_digitally_silent_windows():
    with_silence = windows("-inf", "-inf") + QUIET_TO_LOUD
    assert parse_noise_floor(with_silence) == pytest.approx(-69.0)


def test_noise_floor_ignores_windows_below_the_sanity_limit():
    with_near_silence = windows("-120.0", "-115.0") + QUIET_TO_LOUD
    assert parse_noise_floor(with_near_silence) == pytest.approx(-69.0)


def test_noise_floor_complains_when_nothing_is_measurable():
    with pytest.raises(ValueError, match="noise floor"):
        parse_noise_floor(windows("-inf", "-inf"))


def test_parse_loudness_reads_the_summary_not_the_running_frames():
    integrated, peak = parse_loudness(EBUR128_OUTPUT)
    assert integrated == pytest.approx(-24.0)
    assert peak == pytest.approx(-4.0)


def test_parse_loudness_complains_when_absent():
    with pytest.raises(ValueError, match="loudness"):
        parse_loudness("nothing useful here")


def test_analyse_command_measures_in_one_second_windows_at_the_working_rate():
    """Resampling first is what makes a window exactly a second wide whatever
    rate the take arrived at — a short window shifts the noise-floor percentile."""
    cmd = analyse_command(Path("ian.wav"))
    assert cmd[-3:] == ["-f", "null", "-"]
    assert cmd[cmd.index("-af") + 1] == (
        "aresample=48000,asetnsamples=n=48000,astats=metadata=1:reset=1,"
        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )


def test_render_command_pins_the_working_rate_ahead_of_the_chain():
    cmd = render_command(Path("ian.wav"), "highpass=f=80", Path("tmp.wav"))
    chain = cmd[cmd.index("-af") + 1]
    assert chain == "aresample=48000,highpass=f=80,ebur128=peak=true"
    assert cmd[cmd.index("-c:a") + 1] == "pcm_f32le"
    assert cmd[-1] == "tmp.wav"


def test_render_command_survives_a_chain_with_no_stages_enabled():
    cmd = render_command(Path("ian.wav"), "", Path("tmp.wav"))
    assert cmd[cmd.index("-af") + 1] == "aresample=48000,ebur128=peak=true"


def test_measuring_meters_only_the_first_audio_stream():
    cmd = measure_command(Path("ep.mp4"))
    assert cmd[cmd.index("-map") + 1] == "0:a:0"
    assert cmd[cmd.index("-af") + 1] == "ebur128=peak=true"
    assert cmd[-3:] == ["-f", "null", "-"]


def test_leveling_limits_oversampled_and_leaves_the_level_alone():
    cmd = level_command(Path("ep.mp4"), 8.0, Path("master.wav"))
    chain = cmd[cmd.index("-af") + 1].split(",")

    assert chain[0] == "volume=8dB"
    assert chain[1] == "aresample=192000"
    assert chain[2].startswith("alimiter=")
    # alimiter re-normalises unless told not to, and its look-ahead would
    # shift the audio against the picture unless compensated.
    assert "level=false" in chain[2] and "latency=true" in chain[2]
    assert chain[3] == "aresample=48000"
    # Metered as it renders, so a pass that misses the target is known at once.
    assert chain[4] == "ebur128=peak=true"
    assert cmd[cmd.index("-c:a") + 1] == "pcm_s24le"
    assert cmd[-1] == "master.wav"


def test_the_prepped_video_copies_the_picture_and_encodes_aac():
    cmd = encode_video_command(Path("ep.mp4"), Path("master.wav"), Path("out.mp4"))
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert "+faststart" in cmd
    assert cmd[-1] == "out.mp4"
