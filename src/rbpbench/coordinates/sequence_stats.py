"""Sequence-only descriptive statistics used for retention-bias auditing.

The parent task requires GC-content deciles and "low-complexity deciles,
using a declared sequence-only measure" without mandating a specific
low-complexity formula. This module declares that measure explicitly (Shannon
entropy of mono-nucleotide composition) so it is auditable, and buckets both
GC fraction and entropy into ten equal-width bins over their fixed natural
range (0..1 for GC fraction, 0..2 bits for entropy) rather than sample
quantiles, so decile assignment is reproducible independent of which rows
happen to be sampled.
"""

from __future__ import annotations

import math
from collections import Counter

GC_BASES = frozenset("GCgc")
_BASES = "ACGT"


def gc_fraction(sequence: str) -> float:
    if not sequence:
        return 0.0
    gc = sum(1 for base in sequence if base in GC_BASES)
    return gc / len(sequence)


def low_complexity_entropy(sequence: str) -> float:
    """Shannon entropy (bits) of the sequence's mono-nucleotide composition.

    Range is 0 (a homopolymer; minimally complex) to 2 (uniform A/C/G/T;
    maximally complex for a 4-letter alphabet). This is a declared,
    sequence-only measure: it depends only on base composition, never on
    labels or mapping outcome.
    """
    if not sequence:
        return 0.0
    counts = Counter(sequence.upper())
    total = sum(counts.get(base, 0) for base in _BASES)
    if total == 0:
        return 0.0
    entropy = 0.0
    for base in _BASES:
        count = counts.get(base, 0)
        if count == 0:
            continue
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def decile_index(value: float, *, max_value: float) -> int:
    """Bucket ``value`` into one of 10 equal-width bins over ``[0, max_value]``.

    Bin 0 is the lowest tenth, bin 9 the highest; values at or above
    ``max_value`` fall in bin 9, values at or below 0 fall in bin 0.
    """
    if max_value <= 0:
        return 0
    fraction = max(0.0, min(1.0, value / max_value))
    return min(9, int(fraction * 10))


def gc_decile(sequence: str) -> int:
    return decile_index(gc_fraction(sequence), max_value=1.0)


def low_complexity_decile(sequence: str) -> int:
    return decile_index(low_complexity_entropy(sequence), max_value=2.0)


__all__ = [
    "gc_fraction",
    "low_complexity_entropy",
    "decile_index",
    "gc_decile",
    "low_complexity_decile",
]
