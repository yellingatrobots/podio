from pathlib import Path

import pytest

from podio.ffmpeg import (
    analyse_command,
    apply_gain_command,
    parse_loudness,
    parse_noise_floor,
    parse_range,
    render_command,
)

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


def test_parse_range_minutes_and_seconds():
    assert parse_range("21:30+45") == (1290.0, 45.0)


def test_parse_range_bare_seconds():
    assert parse_range("300+30") == (300.0, 30.0)


def test_parse_range_hours():
    assert parse_range("1:02:03+10") == (3723.0, 10.0)


def test_parse_range_rejects_nonsense():
    with pytest.raises(ValueError, match="START"):
        parse_range("halfway")


def test_analyse_command_measures_in_one_second_windows_at_the_working_rate():
    cmd = analyse_command(Path("ian.wav"), audition=None)
    assert cmd[-3:] == ["-f", "null", "-"]
    assert cmd[cmd.index("-af") + 1] == (
        "aresample=48000,asetnsamples=n=48000,astats=metadata=1:reset=1,"
        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )


def test_analyse_command_bounds_itself_to_an_audition_range():
    cmd = analyse_command(Path("ian.wav"), audition=(1290.0, 45.0))
    assert cmd[cmd.index("-ss") + 1] == "1290"
    assert cmd[cmd.index("-t") + 1] == "45"


def test_render_command_meters_while_writing_the_working_file():
    cmd = render_command(
        Path("ian.wav"), "aresample=48000,highpass=f=80", Path("tmp.wav"), audition=None
    )
    chain = cmd[cmd.index("-af") + 1]
    assert chain == "aresample=48000,highpass=f=80,ebur128=peak=true"
    assert cmd[cmd.index("-c:a") + 1] == "pcm_f32le"
    assert cmd[-1] == "tmp.wav"


def test_apply_gain_writes_24_bit_and_leaves_the_limiter_out_by_default():
    cmd = apply_gain_command(
        Path("tmp.wav"), Path("out.wav"), gain_db=1.2, limiter=False, ceiling_db=-3.0
    )
    assert cmd[cmd.index("-af") + 1] == "volume=1.2dB"
    assert cmd[cmd.index("-c:a") + 1] == "pcm_s24le"


def test_apply_gain_pins_the_limiter_auto_level_off():
    cmd = apply_gain_command(
        Path("tmp.wav"), Path("out.wav"), gain_db=4.8, limiter=True, ceiling_db=-3.0
    )
    chain = cmd[cmd.index("-af") + 1]
    assert chain == "volume=4.8dB,alimiter=limit=0.70795:level=false"
