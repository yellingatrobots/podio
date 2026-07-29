import pytest

from podio.levels import (
    Measured,
    db_to_linear,
    gain_match,
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


def test_gain_match_raises_a_quiet_take_to_the_working_level():
    m = Measured(floor_db=-51.5, integrated_lufs=-21.2, true_peak_db=-4.9)
    result = gain_match(m, working_level_db=-20.0, peak_ceiling_db=-3.0)
    assert result.gain_db == pytest.approx(1.2)
    assert result.resulting_peak_db == pytest.approx(-3.7)
    assert not result.clamped


def test_gain_match_clamps_rather_than_breaching_the_ceiling():
    m = Measured(floor_db=-77.7, integrated_lufs=-24.8, true_peak_db=-2.1)
    result = gain_match(m, working_level_db=-20.0, peak_ceiling_db=-3.0)
    assert result.gain_db == pytest.approx(-0.9)
    assert result.resulting_peak_db == pytest.approx(-3.0)
    assert result.clamped


def test_gain_match_needs_a_post_chain_measurement():
    with pytest.raises(ValueError, match="not been measured"):
        gain_match(IAN, working_level_db=-20.0, peak_ceiling_db=-3.0)
