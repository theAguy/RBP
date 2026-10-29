"""Known-label validation metrics and measurable collapse diagnostics."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from rbpbench.baselines.metrics import MetricError, average_precision, auroc


class ResCNNMetricError(ValueError):
    pass


def summarize_protein(labels: Sequence[int], scores: Sequence[float]) -> dict[str, float | int]:
    labels_array = np.asarray(labels, dtype=np.int8)
    scores_array = np.asarray(scores, dtype=np.float64)
    if labels_array.ndim != 1 or scores_array.ndim != 1 or len(labels_array) != len(scores_array):
        raise ResCNNMetricError("labels and scores must be aligned vectors")
    if not len(labels_array) or not np.isfinite(scores_array).all():
        raise ResCNNMetricError("scores must be non-empty and finite")
    if not np.isin(labels_array, [0, 1]).all():
        raise ResCNNMetricError("labels must be binary")
    positives = int(labels_array.sum())
    negatives = len(labels_array) - positives
    if positives == 0 or negatives == 0:
        raise ResCNNMetricError("both classes are required")
    values, counts = np.unique(scores_array.astype(np.float32), return_counts=True)
    standard_deviation = float(scores_array.std(ddof=0))
    try:
        roc = auroc(labels_array, scores_array)
        ap = average_precision(labels_array, scores_array)
    except MetricError as exc:
        raise ResCNNMetricError(str(exc)) from exc
    return {
        "known_positive_count": positives,
        "known_negative_count": negatives,
        "auroc": roc,
        "average_precision": ap,
        "score_standard_deviation": standard_deviation,
        "unique_score_count": int(len(values)),
        "modal_score_fraction": float(counts.max() / len(scores_array)),
        "saturated_score_fraction": float(np.mean((scores_array <= 1e-6) | (scores_array >= 1 - 1e-6))),
        "technical_collapse": bool(len(values) == 1 or standard_deviation == 0.0),
    }


def evaluate_known_outputs(
    targets,
    scores,
    masks,
    *,
    expected_output_count: int = 122,
) -> tuple[list[dict[str, float | int]], dict[str, float | int]]:
    targets = np.asarray(targets)
    scores = np.asarray(scores)
    masks = np.asarray(masks)
    if targets.shape != scores.shape or targets.shape != masks.shape or targets.ndim != 2:
        raise ResCNNMetricError("targets, scores and masks must be aligned matrices")
    if expected_output_count != 122 or targets.shape[1] != expected_output_count:
        raise ResCNNMetricError(
            f"Task 004A requires exactly 122 scheduler outputs, got {targets.shape[1]}"
        )
    rows = []
    for protein_index in range(targets.shape[1]):
        known = masks[:, protein_index].astype(bool)
        row = summarize_protein(targets[known, protein_index], scores[known, protein_index])
        row["protein_id"] = protein_index + 1
        rows.append(row)
    eligible = len(rows)
    if eligible != expected_output_count:
        raise ResCNNMetricError(f"eligible output count {eligible} != {expected_output_count}")
    collapse_count = sum(bool(row["technical_collapse"]) for row in rows)
    macro_auroc = float(np.mean([float(row["auroc"]) for row in rows]))
    macro_ap = float(np.mean([float(row["average_precision"]) for row in rows]))
    pooled_labels = targets[masks.astype(bool)]
    pooled_scores = scores[masks.astype(bool)]
    pooled_ap = average_precision(pooled_labels, pooled_scores)
    if not all(math.isfinite(value) for value in (macro_auroc, macro_ap, pooled_ap)):
        raise ResCNNMetricError("aggregate metric is non-finite")
    return rows, {
        "eligible_output_count": eligible,
        "technical_collapse_count": collapse_count,
        "macro_auroc": macro_auroc,
        "macro_average_precision": macro_ap,
        "pooled_known_entry_AP": pooled_ap,
    }
