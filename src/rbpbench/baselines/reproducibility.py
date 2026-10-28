"""Numerical reproducibility checks for repeated Task 003B pilot runs."""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path


class ReproducibilityError(RuntimeError):
    pass


SCORE_ATOL = 1e-5
METRIC_ATOL = 5e-6
METRIC_FLOAT_FIELDS = {
    "auroc", "average_precision", "matched_auroc",
    "matched_average_precision", "prevalence",
}


def _load_json(path: Path):
    return json.loads(path.read_text())


def _require_equal(left, right, *, context: str) -> None:
    if left != right:
        raise ReproducibilityError(f"{context} differs: {left!r} != {right!r}")


def compare_pilot_generations(primary: Path, repeat: Path) -> dict:
    """Compare two pilots while allowing only bounded solver float noise."""
    primary_summary = _load_json(primary / "summary.json")
    repeat_summary = _load_json(repeat / "summary.json")
    exact_summary_fields = (
        "schema_version", "status", "test_accessed", "test_labels_parsed",
        "test_features_built", "protein_ids", "widths", "selected_c",
        "metric_row_count", "prediction_row_count", "development_sequence_count",
        "feature_storage_bytes", "peak_width_feature_storage_bytes",
    )
    for field in exact_summary_fields:
        if field not in primary_summary or field not in repeat_summary:
            raise ReproducibilityError(f"required summary field is missing: {field}")
        _require_equal(primary_summary.get(field), repeat_summary.get(field), context=f"summary.{field}")

    primary_selections = primary_summary["selection_evidence"]
    repeat_selections = repeat_summary["selection_evidence"]
    _require_equal(set(primary_selections), set(repeat_selections), context="selection keys")
    max_selection_auroc_difference = 0.0
    for key in sorted(primary_selections):
        left = primary_selections[key]
        right = repeat_selections[key]
        _require_equal(left["selected_c"], right["selected_c"], context=f"{key}.selected_c")
        _require_equal(len(left["evidence"]), len(right["evidence"]), context=f"{key}.evidence length")
        for index, (left_row, right_row) in enumerate(zip(left["evidence"], right["evidence"])):
            for field in ("c", "eligible", "fit_count"):
                _require_equal(left_row[field], right_row[field], context=f"{key}.evidence[{index}].{field}")
            left_auroc = left_row["macro_validation_auroc"]
            right_auroc = right_row["macro_validation_auroc"]
            if left_auroc is None or right_auroc is None:
                _require_equal(left_auroc, right_auroc, context=f"{key}.evidence[{index}].macro_validation_auroc")
            else:
                difference = abs(float(left_auroc) - float(right_auroc))
                max_selection_auroc_difference = max(max_selection_auroc_difference, difference)
                if difference > METRIC_ATOL:
                    raise ReproducibilityError(
                        f"{key}.evidence[{index}] AUROC difference {difference} exceeds {METRIC_ATOL}"
                    )

    primary_metrics = _load_json(primary / "metrics.json")
    repeat_metrics = _load_json(repeat / "metrics.json")
    _require_equal(len(primary_metrics), len(repeat_metrics), context="metric row count")
    max_metric_difference = 0.0
    max_iteration_difference = 0
    for index, (left, right) in enumerate(zip(primary_metrics, repeat_metrics)):
        _require_equal(set(left), set(right), context=f"metrics[{index}] fields")
        for field in left:
            if field in METRIC_FLOAT_FIELDS:
                difference = abs(float(left[field]) - float(right[field]))
                max_metric_difference = max(max_metric_difference, difference)
                if difference > METRIC_ATOL:
                    raise ReproducibilityError(
                        f"metrics[{index}].{field} difference {difference} exceeds {METRIC_ATOL}"
                    )
            elif field == "n_iter":
                max_iteration_difference = max(max_iteration_difference, abs(int(left[field]) - int(right[field])))
            else:
                _require_equal(left[field], right[field], context=f"metrics[{index}].{field}")

    prediction_count = 0
    differing_score_count = 0
    max_score_difference = 0.0
    with gzip.open(primary / "predictions.tsv.gz", "rt", newline="") as primary_handle, gzip.open(
        repeat / "predictions.tsv.gz", "rt", newline=""
    ) as repeat_handle:
        primary_rows = csv.DictReader(primary_handle, delimiter="\t")
        repeat_rows = csv.DictReader(repeat_handle, delimiter="\t")
        _require_equal(primary_rows.fieldnames, repeat_rows.fieldnames, context="prediction fields")
        while True:
            left = next(primary_rows, None)
            right = next(repeat_rows, None)
            if left is None or right is None:
                _require_equal(left, right, context="prediction row count")
                break
            for field in left:
                if field == "score":
                    difference = abs(float(left[field]) - float(right[field]))
                    max_score_difference = max(max_score_difference, difference)
                    differing_score_count += difference != 0.0
                    if difference > SCORE_ATOL:
                        raise ReproducibilityError(
                            f"prediction row {prediction_count} score difference {difference} exceeds {SCORE_ATOL}"
                        )
                else:
                    _require_equal(left[field], right[field], context=f"prediction row {prediction_count}.{field}")
            prediction_count += 1

    return {
        "schema_version": "task003b_pilot_reproducibility_v1",
        "passed": True,
        "score_atol": SCORE_ATOL,
        "metric_atol": METRIC_ATOL,
        "prediction_row_count": prediction_count,
        "differing_score_count": differing_score_count,
        "max_score_difference": max_score_difference,
        "max_metric_difference": max_metric_difference,
        "max_selection_auroc_difference": max_selection_auroc_difference,
        "max_iteration_difference": max_iteration_difference,
        "selected_c_exact": True,
        "prediction_identity_fields_exact": True,
        "test_boundary_exact": True,
    }
