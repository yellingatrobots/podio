import pytest

from podio.levels import (
    TARGET_LUFS,
    Measured,
    db_to_linear,
    delivery_gain,
    delivery_settled,
    meets_delivery,
    resolve_db,
    tone_amplitude,
)

IAN = Measured(floor_db=-51.5)


def test_db_to_linear_unity():
    assert db_to_linear(0.0) == pytest.approx(1.0)


def test_db_to_linear_minus_six_is_about_half():
    assert db_to_linear(-6.0) == pytest.approx(0.5012, abs=1e-4)


def test_resolve_passes_through_a_plain_number():
    assert resolve_db(-39.5, IAN) == pytest.approx(-39.5)


def test_resolve_bare_reference():
    assert resolve_db("floor", IAN) == pytest.approx(-51.5)


def test_resolve_reference_with_offset():
    assert resolve_db("floor+12", IAN) == pytest.approx(-39.5)


def test_resolve_reference_with_negative_offset():
    assert resolve_db("floor-3", IAN) == pytest.approx(-54.5)


def test_resolve_tolerates_whitespace():
    assert resolve_db(" floor + 12 ", IAN) == pytest.approx(-39.5)


def test_resolve_rejects_unknown_reference():
    with pytest.raises(ValueError, match="ceiling"):
        resolve_db("ceiling+12", IAN)


def test_tone_amplitude_is_the_peak_of_a_sine_at_that_rms():
    # A sine's peak sits 3.01 dB above its RMS, so -27 dBFS RMS peaks at -24.
    amplitude = tone_amplitude(-27.0, full_scale=2_147_483_647)
    assert amplitude == pytest.approx(0.0631 * 2_147_483_647, rel=0.01)


def test_tone_amplitude_never_exceeds_full_scale():
    """0 dBFS RMS would peak 3 dB over full scale; it has to clamp, not wrap."""
    assert tone_amplitude(0.0, full_scale=2_147_483_647) == 2_147_483_647


def test_delivery_gain_brings_quiet_audio_to_the_target():
    assert delivery_gain(-24.0) == pytest.approx(8.0)


def test_delivery_gain_turns_hot_audio_down():
    assert delivery_gain(-12.5) == pytest.approx(-3.5)


def test_delivery_within_a_loudness_unit_and_under_the_peak_limit_passes():
    assert meets_delivery(TARGET_LUFS - 0.4, -1.2)


def test_delivery_fails_on_a_true_peak_over_minus_one():
    assert not meets_delivery(TARGET_LUFS, -0.8)


def test_delivery_fails_more_than_a_loudness_unit_off_target():
    assert not meets_delivery(TARGET_LUFS - 1.3, -3.0)


def test_a_render_within_a_fifth_of_a_unit_has_settled():
    assert delivery_settled(TARGET_LUFS - 0.15)


def test_a_render_the_limiter_pulled_two_units_down_has_not():
    assert not delivery_settled(TARGET_LUFS - 2.0)
