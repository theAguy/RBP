"""Deterministic GC and ordered k-mer features."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

import numpy as np
from scipy.sparse import csr_matrix


class FeatureError(ValueError):
    pass


BASE = {"A": 0, "C": 1, "G": 2, "T": 3}


def validate_sequence(sequence: str, *, width: int | None = None) -> str:
    sequence = sequence.strip().upper()
    if not sequence or any(base not in BASE for base in sequence):
        raise FeatureError("sequence must be non-empty and contain only A/C/G/T")
    if width is not None and len(sequence) != width:
        raise FeatureError(f"sequence length {len(sequence)} != expected width {width}")
    return sequence


def gc_fraction(sequence: str) -> float:
    sequence = validate_sequence(sequence)
    return (sequence.count("G") + sequence.count("C")) / len(sequence)


def kmer_code(kmer: str) -> int:
    value = 0
    for base in validate_sequence(kmer):
        value = value * 4 + BASE[base]
    return value


def sequence_kmer_counts(sequence: str, k: int) -> tuple[list[int], list[float]]:
    sequence = validate_sequence(sequence)
    if k <= 0 or k > len(sequence):
        raise FeatureError("k must be positive and no larger than the sequence")
    code = 0
    factor = 4 ** (k - 1)
    counts: Counter[int] = Counter()
    for index, base in enumerate(sequence):
        digit = BASE[base]
        if index < k:
            code = code * 4 + digit
            if index == k - 1:
                counts[code] += 1
        else:
            code = (code % factor) * 4 + digit
            counts[code] += 1
    denominator = len(sequence) - k + 1
    indices = sorted(counts)
    return indices, [counts[index] / denominator for index in indices]


def gc_matrix(sequences: Sequence[str]) -> np.ndarray:
    return np.asarray([gc_fraction(sequence) for sequence in sequences], dtype=np.float64).reshape(-1, 1)


def kmer_matrix(sequences: Sequence[str], k: int) -> csr_matrix:
    indptr = [0]
    indices: list[int] = []
    data: list[float] = []
    for sequence in sequences:
        row_indices, row_data = sequence_kmer_counts(sequence, k)
        indices.extend(row_indices)
        data.extend(row_data)
        indptr.append(len(indices))
    return csr_matrix(
        (np.asarray(data, dtype=np.float64), np.asarray(indices, dtype=np.int32), np.asarray(indptr, dtype=np.int64)),
        shape=(len(sequences), 4**k),
    )


def read_fasta_subset(lines: Iterable[str], *, wanted_ids: set[str], width: int) -> dict[str, str]:
    if any(not sample_id or "\t" in sample_id or "\n" in sample_id or "\r" in sample_id for sample_id in wanted_ids):
        raise FeatureError("invalid wanted sample ID")
    result: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []

    def finish() -> None:
        nonlocal current, chunks
        if current is None:
            return
        if current in wanted_ids:
            if current in result:
                raise FeatureError(f"duplicate FASTA ID: {current}")
            result[current] = validate_sequence("".join(chunks), width=width)
        current, chunks = None, []

    seen_headers: set[str] = set()
    for line in lines:
        line = line.rstrip("\r\n")
        if line.startswith(">"):
            finish()
            current = line[1:]
            if not current or any(char.isspace() for char in current):
                raise FeatureError("FASTA headers must be non-empty canonical IDs")
            if current in seen_headers:
                raise FeatureError(f"duplicate FASTA ID: {current}")
            seen_headers.add(current)
        elif current is None:
            if line:
                raise FeatureError("sequence data before first FASTA header")
        elif current in wanted_ids:
            chunks.append(line)
    finish()
    missing = wanted_ids - result.keys()
    if missing:
        raise FeatureError(f"missing FASTA IDs: {sorted(missing)[:5]}")
    return result
