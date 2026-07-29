from podio.manifest import CensorSpan
from podio.adjust import adjust_spans


def span(start, end, term="fuck"):
    return CensorSpan(
        start=start, end=end, term=term, source_text=term, confidence=1.0,
    )


def test_inset_shrinks_span_inward_on_each_edge():
    [out] = adjust_spans([span(1.0, 1.5)], inset=0.1)
    assert out.start == 1.1
    assert out.end == 1.4


def test_span_that_collapses_to_zero_or_less_is_dropped():
    # 40ms span, 30ms inset per edge -> would be -20ms wide, so drop it.
    assert adjust_spans([span(1.0, 1.04)], inset=0.03) == []


def test_overlapping_spans_merge_into_one_covering_both():
    out = adjust_spans([span(1.0, 2.0), span(1.5, 2.5)], inset=0.0)
    assert len(out) == 1
    assert out[0].start == 1.0
    assert out[0].end == 2.5


def test_non_overlapping_spans_are_kept_separate():
    out = adjust_spans([span(1.0, 2.0), span(3.0, 4.0)], inset=0.0)
    assert len(out) == 2


def test_merged_span_joins_both_words_and_takes_min_confidence():
    a = CensorSpan(1.0, 2.0, term="fuck", source_text="Fucking", confidence=0.9)
    b = CensorSpan(1.5, 2.5, term="shit", source_text="shit", confidence=0.6)
    [out] = adjust_spans([a, b], inset=0.0)
    assert out.term == "fuck shit"
    assert out.source_text == "Fucking shit"
    assert out.confidence == 0.6
