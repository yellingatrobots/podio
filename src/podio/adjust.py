"""Adjust detected spans into a render-ready edit list.

Pure transformation of the ``find_spans`` output — no audio or models. Applies a
negative inset (shrinkage) so the onset of the first consonant and the tail of
the last word stay audible, then drops collapsed spans and merges overlaps.
"""

from __future__ import annotations

import dataclasses
from typing import List, Sequence

from .manifest import CensorSpan


def adjust_spans(
    spans: Sequence[CensorSpan], inset: float = 0.03
) -> List[CensorSpan]:
    """Inset each span, drop collapsed ones, and merge overlaps."""
    inset_spans: List[CensorSpan] = []
    for s in spans:
        start, end = s.start + inset, s.end - inset
        if end - start <= 0:
            continue  # collapsed to nothing after inset — drop it
        inset_spans.append(dataclasses.replace(s, start=start, end=end))
    return _merge_overlaps(inset_spans)


def _merge_overlaps(spans: List[CensorSpan]) -> List[CensorSpan]:
    """Merge spans that overlap, treating each as a half-open interval."""
    merged: List[CensorSpan] = []
    for s in sorted(spans, key=lambda s: s.start):
        prev = merged[-1] if merged else None
        if prev is not None and s.start < prev.end:
            merged[-1] = dataclasses.replace(
                prev,
                end=max(prev.end, s.end),
                term=f"{prev.term} {s.term}",
                source_text=f"{prev.source_text} {s.source_text}",
                confidence=min(prev.confidence, s.confidence),
            )
        else:
            merged.append(s)
    return merged
