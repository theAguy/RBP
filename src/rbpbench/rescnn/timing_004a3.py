"""Synchronized measurement and worst-case metric benchmark for Task 004A-3."""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
import time
from typing import Callable, Iterable, Sequence, TypeVar

import numpy as np

from rbpbench.rescnn.metrics import evaluate_known_outputs


WARMUP_BATCHES = 4
FULL_VALIDATION_ROWS = 57_565
OUTPUT_COUNT = 122
T = TypeVar("T")


class ResCNN004A3TimingError(RuntimeError):
    pass


@dataclass(frozen=True)
class TimingSummary:
    observed: int
    excluded_warmup: int
    retained: int
    median_seconds: float
    p95_seconds: float
    samples_seconds: tuple[float, ...]


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ResCNN004A3TimingError("no retained timing samples")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def measure_batches(
    batches: Iterable[T],
    *,
    step: Callable[[T], object],
    synchronize: Callable[[], None],
    clock: Callable[[], float] = time.perf_counter,
    warmup: int = WARMUP_BATCHES,
    outside_timed_region: Callable[[T, object], None] | None = None,
) -> TimingSummary:
    """Time the complete batch callback; evidence work occurs after end sync."""

    if warmup != WARMUP_BATCHES:
        raise ResCNN004A3TimingError("Task 004A-3 excludes exactly four warm-up batches")
    durations: list[float] = []
    observed = 0
    for batch in batches:
        synchronize()
        started = clock()
        result = step(batch)
        synchronize()
        ended = clock()
        duration = ended - started
        if not math.isfinite(duration) or duration < 0:
            raise ResCNN004A3TimingError("invalid batch duration")
        durations.append(duration)
        observed += 1
        if outside_timed_region is not None:
            outside_timed_region(batch, result)
    retained = durations[warmup:]
    if not retained:
        raise ResCNN004A3TimingError("warm-up exclusion removed every timing sample")
    return TimingSummary(
        observed=observed, excluded_warmup=warmup, retained=len(retained),
        median_seconds=float(statistics.median(retained)),
        p95_seconds=float(_percentile(retained, 0.95)),
        samples_seconds=tuple(retained),
    )


def worst_case_metric_arrays(
    validation_known_counts: Sequence[int],
    *,
    row_count: int = FULL_VALIDATION_ROWS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build full-shape metric inputs with a unique float32 score per known entry."""

    if row_count != FULL_VALIDATION_ROWS:
        raise ResCNN004A3TimingError("full metric benchmark row count is frozen")
    counts = tuple(int(value) for value in validation_known_counts)
    if len(counts) != OUTPUT_COUNT or any(value < 2 or value > row_count for value in counts):
        raise ResCNN004A3TimingError("invalid validation per-protein known counts")
    total_known = sum(counts)
    if total_known >= 2**24:
        raise ResCNN004A3TimingError("too many known entries for unique float32 ranks")
    targets = np.zeros((row_count, OUTPUT_COUNT), dtype=np.uint8)
    masks = np.zeros((row_count, OUTPUT_COUNT), dtype=np.uint8)
    scores = np.zeros((row_count, OUTPUT_COUNT), dtype=np.float32)
    rank = 1
    denominator = np.float32(total_known + 1)
    for protein_index, count in enumerate(counts):
        masks[:count, protein_index] = 1
        targets[:count, protein_index] = np.arange(count, dtype=np.uint8) % 2
        local = np.arange(rank, rank + count, dtype=np.float32) / denominator
        scores[:count, protein_index] = local
        rank += count
    known_scores = scores[masks.astype(bool)]
    if len(np.unique(known_scores)) != total_known:
        raise ResCNN004A3TimingError("worst-case metric scores are not all distinct")
    return targets, scores, masks


def benchmark_full_validation_metrics(
    validation_known_counts: Sequence[int],
    *,
    repeats: int = 3,
    clock: Callable[[], float] = time.perf_counter,
) -> TimingSummary:
    if repeats < 3:
        raise ResCNN004A3TimingError("metric benchmark requires at least three retained calls")
    targets, scores, masks = worst_case_metric_arrays(validation_known_counts)
    durations: list[float] = []
    # One untimed warm-up, followed by retained calls. Arrays are reused.
    evaluate_known_outputs(targets, scores, masks, expected_output_count=OUTPUT_COUNT)
    for _ in range(repeats):
        started = clock()
        rows, summary = evaluate_known_outputs(
            targets, scores, masks, expected_output_count=OUTPUT_COUNT,
        )
        ended = clock()
        if len(rows) != OUTPUT_COUNT or summary["eligible_output_count"] != OUTPUT_COUNT:
            raise ResCNN004A3TimingError("full metric benchmark lost output eligibility")
        durations.append(ended - started)
    return TimingSummary(
        observed=repeats + 1, excluded_warmup=1, retained=repeats,
        median_seconds=float(statistics.median(durations)),
        p95_seconds=float(_percentile(durations, 0.95)),
        samples_seconds=tuple(durations),
    )
