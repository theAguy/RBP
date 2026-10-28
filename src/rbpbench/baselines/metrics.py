"""Deterministic binary ranking metrics with explicit tie handling."""

from __future__ import annotations

import numpy as np


class MetricError(ValueError):
    pass


def _arrays(labels, scores) -> tuple[np.ndarray, np.ndarray]:
    labels = np.asarray(labels, dtype=np.int8)
    scores = np.asarray(scores, dtype=np.float64)
    if labels.ndim != 1 or scores.ndim != 1 or len(labels) != len(scores) or not len(labels):
        raise MetricError("labels and scores must be non-empty aligned vectors")
    if not np.isin(labels, [0, 1]).all() or not np.isfinite(scores).all():
        raise MetricError("labels must be binary and scores finite")
    if labels.sum() == 0 or labels.sum() == len(labels):
        raise MetricError("both classes are required")
    return labels, scores


def auroc(labels, scores) -> float:
    labels, scores = _arrays(labels, scores)
    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = np.empty(len(scores), dtype=np.float64)
    start = 0
    while start < len(scores):
        end = start + 1
        while end < len(scores) and sorted_scores[end] == sorted_scores[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    positives = int(labels.sum())
    negatives = len(labels) - positives
    return float((ranks[labels == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def average_precision(labels, scores) -> float:
    labels, scores = _arrays(labels, scores)
    thresholds = np.unique(scores)[::-1]
    positives = int(labels.sum())
    true_positives = 0
    selected = 0
    previous_recall = 0.0
    result = 0.0
    for threshold in thresholds:
        group = scores == threshold
        true_positives += int(labels[group].sum())
        selected += int(group.sum())
        recall = true_positives / positives
        precision = true_positives / selected
        result += (recall - previous_recall) * precision
        previous_recall = recall
    return float(result)


def summarize(labels, scores) -> dict[str, float | int]:
    labels, scores = _arrays(labels, scores)
    positives = int(labels.sum())
    negatives = len(labels) - positives
    return {
        "positive_count": positives,
        "negative_count": negatives,
        "prevalence": positives / len(labels),
        "auroc": auroc(labels, scores),
        "average_precision": average_precision(labels, scores),
    }
