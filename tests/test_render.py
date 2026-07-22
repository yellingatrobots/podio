import math

from bleep.render import bleep_pcm


def test_bleep_replaces_samples_inside_span_and_leaves_the_rest():
    sr = 8000
    samples = [5] * sr  # 1s of a constant non-zero background
    out = bleep_pcm(samples, sr, [(0.25, 0.75)], freq=1000, amplitude=10000)

    assert len(out) == sr
    assert out[:2000] == [5] * 2000        # before the span: untouched
    assert out[6000:] == [5] * 2000        # after the span: untouched
    assert any(s != 5 for s in out[2000:6000])  # inside: a tone was written


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
