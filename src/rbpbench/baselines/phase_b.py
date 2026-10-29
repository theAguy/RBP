"""Task 003B-3 Phase B: score the frozen test set with accepted Phase-A models."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
from typing import Mapping

import numpy as np
from scipy.special import expit

from rbpbench.baselines.config import BaselineConfig, canonical_json
from rbpbench.baselines.data import build_label_index, read_membership
from rbpbench.baselines.features import gc_matrix, kmer_matrix, read_fasta_subset
from rbpbench.baselines.gc_matching import matched_indices_with_edges
from rbpbench.baselines.metrics import summarize
from rbpbench.baselines.output import Generation, file_evidence, verify_selected
from rbpbench.baselines.phase_a import PROTEIN_IDS, selected_c_from_manifest
from rbpbench.baselines.pilot import sha256_file
from rbpbench.splits.audit import per_protein_balance_report


class PhaseBError(RuntimeError):
    pass


TARGET_FRACTIONS = {"train": 0.70, "validation": 0.15, "test": 0.15}
PREDICTION_FIELDS = [
    "sample_id", "component_id", "protein_id", "fold", "partition", "seed",
    "window", "config_id", "config_hash", "label", "score", "gc_matched",
]


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PhaseBError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise PhaseBError(f"JSON evidence must be an object: {path}")
    return value


def verify_phase_a(
    *, output_root: Path, phase_a_manifest_path: Path
) -> tuple[dict, dict, Path, dict]:
    """Validate the accepted Phase-A manifest, selection and generation."""
    manifest = _load_json(phase_a_manifest_path)
    if (
        manifest.get("schema_version") != "task003b_final_phase_a_acceptance_v1"
        or manifest.get("status") != "accepted"
    ):
        raise PhaseBError("Phase-A manifest is not accepted")
    boundary = manifest.get("test_boundary", {})
    if boundary.get("test_accessed") is not False or boundary.get("phase_b_record_exists") is not False:
        raise PhaseBError("Phase-A manifest has an invalid test boundary")

    selection_path = output_root / "selected/final_phase_a.json"
    expected_selection = manifest.get("accepted_evidence", {}).get("selection_record", {})
    actual_selection = file_evidence(selection_path)
    if expected_selection:
        for key in ("byte_size", "sha256"):
            if actual_selection[key] != expected_selection.get(key):
                raise PhaseBError(f"Phase-A selection {key} drift")
    selection = _load_json(selection_path)
    if selection.get("stage") != "final_phase_a" or selection.get("payload", {}).get("test_accessed") is not False:
        raise PhaseBError("Phase-A selection record is invalid")
    verified = verify_selected(output_root, "final_phase_a", fingerprint=selection.get("fingerprint", ""))
    if verified is None:
        raise PhaseBError("Phase-A selection record is stale")
    generation = output_root / selection["generation"]
    if manifest.get("execution", {}).get("generation") not in (None, selection["generation"]):
        raise PhaseBError("Phase-A manifest selects a different generation")
    summary = _load_json(generation / "summary.json")
    if (
        summary.get("schema_version") != "task003b_final_phase_a_v1"
        or summary.get("all_fits_converged") is not True
        or summary.get("fit_record_count") != 122 * 3 * 3
        or summary.get("test_accessed") is not False
    ):
        raise PhaseBError("Phase-A summary is incomplete or test-exposed")
    return manifest, selection, generation, summary


def phase_b_fingerprint(
    config: BaselineConfig,
    *,
    csv_path: Path,
    membership_path: Path,
    fasta_by_width: Mapping[int, Path],
    phase_a_manifest_path: Path,
    phase_a_selection_path: Path,
    partition_manifest_path: Path,
) -> str:
    evidence = {
        "config_semantic_sha256": config.semantic_sha256,
        "csv_sha256": sha256_file(csv_path),
        "membership_sha256": sha256_file(membership_path),
        "fastas": {str(width): sha256_file(fasta_by_width[width]) for width in config.windows},
        "phase_a_manifest_sha256": sha256_file(phase_a_manifest_path),
        "phase_a_selection_sha256": sha256_file(phase_a_selection_path),
        "partition_manifest_sha256": sha256_file(partition_manifest_path),
        "implementation": _implementation_evidence(),
        "mode": "accepted_phase_a_models_to_test_once_all_122",
    }
    return hashlib.sha256(canonical_json(evidence)).hexdigest()


def _implementation_evidence() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {
        name: sha256_file(root / name)
        for name in ("phase_b.py", "features.py", "gc_matching.py", "metrics.py")
    }


def _array_bytes(matrix) -> int:
    if hasattr(matrix, "indptr"):
        return int(matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes)
    return int(matrix.nbytes)


def _load_array(path: Path, *, shape: tuple[int, ...]) -> np.ndarray:
    try:
        value = np.load(path, allow_pickle=False)
    except Exception as exc:
        raise PhaseBError(f"cannot load Phase-A array: {path.name}") from exc
    if value.shape != shape or not np.isfinite(value).all():
        raise PhaseBError(f"invalid Phase-A array {path.name}: shape={value.shape}, expected={shape}")
    return np.asarray(value, dtype=np.float64)


def _load_model(generation: Path, *, width: int, baseline: str, feature_count: int) -> dict[str, np.ndarray]:
    prefix = generation / f"model_{width}_{baseline}"
    coefs = _load_array(prefix.with_name(prefix.name + "_coef.npy"), shape=(122, feature_count))
    scales = _load_array(prefix.with_name(prefix.name + "_scale.npy"), shape=(122, feature_count))
    intercepts = _load_array(prefix.with_name(prefix.name + "_intercept.npy"), shape=(122,))
    if np.any(scales <= 0):
        raise PhaseBError(f"non-positive Phase-A scale for {baseline}_{width}")
    result = {"coefs": coefs, "scales": scales, "intercepts": intercepts}
    if baseline == "gc":
        result["means"] = _load_array(prefix.with_name(prefix.name + "_mean.npy"), shape=(122, feature_count))
    return result


def _score_model(model: dict[str, np.ndarray], *, baseline: str, matrix, protein_offset: int) -> np.ndarray:
    if baseline == "gc":
        transformed = (
            np.asarray(matrix, dtype=np.float64) - model["means"][protein_offset]
        ) / model["scales"][protein_offset]
        decision = transformed @ model["coefs"][protein_offset] + model["intercepts"][protein_offset]
    else:
        decision = matrix.dot(
            model["coefs"][protein_offset] / model["scales"][protein_offset]
        ) + model["intercepts"][protein_offset]
    scores = expit(np.asarray(decision).ravel())
    if not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
        raise PhaseBError(f"invalid Phase-B scores for {baseline}")
    return scores


def _fit_hash(
    config: BaselineConfig, *, phase_a_selection_sha256: str, baseline: str,
    width: int, protein_id: int, c_value: float | None, gc_edges: list[float],
) -> str:
    value = {
        "base_config": config.semantic_sha256,
        "implementation": _implementation_evidence(),
        "phase_a_selection_sha256": phase_a_selection_sha256,
        "stage": "final_phase_b", "fit_partitions": ["train", "validation"],
        "evaluation_partition": "test", "baseline": baseline, "width": width,
        "protein_id": protein_id, "c": c_value, "gc_edges": gc_edges,
    }
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _open_prediction_writer(path: Path):
    raw = path.open("wb")
    compressed = gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0)
    text = io.TextIOWrapper(compressed, encoding="utf-8", newline="")
    writer = csv.DictWriter(text, fieldnames=PREDICTION_FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    return raw, compressed, text, writer


def _balance_disclosure(labels) -> tuple[dict, dict]:
    partition_counts: dict[str, dict[int, tuple[int, int]]] = {}
    for partition in TARGET_FRACTIONS:
        partition_counts[partition] = {}
        for protein_id in PROTEIN_IDS:
            values = labels.labels.get((protein_id, partition), [])
            positive = int(sum(values))
            partition_counts[partition][protein_id] = (positive, len(values) - positive)
    report = per_protein_balance_report(partition_counts, TARGET_FRACTIONS)
    counts = {
        "proteins_flagged_any_partition": sum(
            any(cell[cls]["flagged"] for cell in protein.values() for cls in ("known_positive", "known_negative"))
            for protein in report.values()
        ),
        "cells_flagged_any_partition": sum(
            cell[cls]["flagged"] for protein in report.values() for cell in protein.values()
            for cls in ("known_positive", "known_negative")
        ),
        "proteins_flagged_validation_or_test": sum(
            any(protein[part][cls]["flagged"] for part in ("validation", "test") for cls in ("known_positive", "known_negative"))
            for protein in report.values()
        ),
        "cells_flagged_validation_or_test": sum(
            protein[part][cls]["flagged"] for protein in report.values()
            for part in ("validation", "test") for cls in ("known_positive", "known_negative")
        ),
    }
    return report, counts


def _aggregate_metrics(metric_rows: list[dict]) -> list[dict]:
    aggregates = []
    for width in (500, 251, 101):
        for baseline in ("prevalence", "gc", "3mer", "6mer"):
            base = [row for row in metric_rows if row["width"] == width and row["baseline"] == baseline]
            groups = {
                "all": base,
                "flagged_validation_or_test": [row for row in base if row["imbalance_flag_validation_or_test"]],
                "not_flagged_validation_or_test": [row for row in base if not row["imbalance_flag_validation_or_test"]],
            }
            for group, rows in groups.items():
                if not rows:
                    continue
                aggregates.append({
                    "width": width, "baseline": baseline, "stratum": group,
                    "protein_count": len(rows),
                    "macro_auroc": float(np.mean([row["auroc"] for row in rows])),
                    "macro_average_precision": float(np.mean([row["average_precision"] for row in rows])),
                    "macro_matched_auroc": float(np.mean([row["matched_auroc"] for row in rows])),
                    "macro_matched_average_precision": float(np.mean([row["matched_average_precision"] for row in rows])),
                    "macro_auroc_minus_prevalence": float(np.mean([row["auroc"] - 0.5 for row in rows])),
                })
    return aggregates


def _reproduce_metrics(predictions_path: Path, metric_rows: list[dict], *, seed: int) -> None:
    grouped: dict[tuple[int, str, int], dict[str, list]] = {}
    expected = {(row["width"], row["baseline"], row["protein_id"]): row for row in metric_rows}
    seen: set[tuple[int, str, int, str]] = set()
    with gzip.open(predictions_path, "rt", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != PREDICTION_FIELDS:
            raise PhaseBError("prediction header drift")
        for row in reader:
            if row["partition"] != "test" or row["fold"] != "components_v2_final":
                raise PhaseBError("prediction partition/fold drift")
            if int(row["seed"]) != seed or row["gc_matched"] not in {"0", "1"}:
                raise PhaseBError("prediction seed or matched indicator drift")
            if not row["sample_id"] or not row["component_id"]:
                raise PhaseBError("prediction identity is empty")
            key = (int(row["window"]), row["config_id"], int(row["protein_id"]))
            if key not in expected or row["config_hash"] != expected[key]["config_hash"]:
                raise PhaseBError("prediction configuration identity drift")
            identity = (*key, row["sample_id"])
            if identity in seen:
                raise PhaseBError("duplicate prediction identity")
            seen.add(identity)
            label = int(row["label"])
            score = float(row["score"])
            if label not in (0, 1) or not np.isfinite(score):
                raise PhaseBError("prediction label or score is invalid")
            bucket = grouped.setdefault(key, {"labels": [], "scores": [], "matched": []})
            bucket["labels"].append(label)
            bucket["scores"].append(score)
            bucket["matched"].append(row["gc_matched"] == "1")
    if len(grouped) != 122 * 3 * 4:
        raise PhaseBError("prediction group count is incomplete")
    if set(grouped) != set(expected):
        raise PhaseBError("prediction and metric identities differ")
    for key, values in grouped.items():
        labels = np.asarray(values["labels"], dtype=np.int8)
        scores = np.asarray(values["scores"], dtype=np.float64)
        matched = np.asarray(values["matched"], dtype=bool)
        full = summarize(labels, scores)
        secondary = summarize(labels[matched], scores[matched])
        row = expected[key]
        checks = {
            **full,
            "matched_count": int(matched.sum()),
            "matched_auroc": secondary["auroc"],
            "matched_average_precision": secondary["average_precision"],
        }
        for name, actual in checks.items():
            if not np.isclose(float(row[name]), float(actual), rtol=0, atol=1e-12):
                raise PhaseBError(f"prediction metric reconciliation failed for {key}: {name}")


def run_phase_b(
    *,
    config: BaselineConfig,
    csv_path: Path,
    membership_path: Path,
    fasta_by_width: Mapping[int, Path],
    phase_a_manifest_path: Path,
    partition_manifest_path: Path,
    output_root: Path,
    expected_rows: int | None = None,
    authorize_test: bool = False,
    force: bool = False,
) -> Path:
    if not authorize_test:
        raise PhaseBError("Phase B requires explicit test authorization")
    phase_a_manifest, phase_a_selection, phase_a_generation, phase_a_summary = verify_phase_a(
        output_root=output_root, phase_a_manifest_path=phase_a_manifest_path,
    )
    phase_a_selection_path = output_root / "selected/final_phase_a.json"
    fingerprint = phase_b_fingerprint(
        config, csv_path=csv_path, membership_path=membership_path,
        fasta_by_width=fasta_by_width, phase_a_manifest_path=phase_a_manifest_path,
        phase_a_selection_path=phase_a_selection_path,
        partition_manifest_path=partition_manifest_path,
    )
    if not force:
        selected = verify_selected(output_root, "final_phase_b", fingerprint=fingerprint)
        if selected is not None:
            return output_root / selected["generation"]

    try:
        pilot_evidence = phase_a_manifest["inputs"]["pilot_manifest"]
        pilot_path = Path(pilot_evidence["path"])
        pilot_sha256 = pilot_evidence["sha256"]
    except (KeyError, TypeError) as exc:
        raise PhaseBError("Phase-A manifest lacks accepted pilot evidence") from exc
    if sha256_file(pilot_path) != pilot_sha256:
        raise PhaseBError("accepted pilot manifest has drifted")
    selected_c = selected_c_from_manifest(pilot_path)
    if selected_c != {key: float(value) for key, value in phase_a_summary["selected_c"].items()}:
        raise PhaseBError("selected C values drifted between pilot and Phase A")
    accepted_selected_c = phase_a_manifest.get("fitting", {}).get("selected_c")
    if accepted_selected_c is not None and selected_c != {
        key: float(value) for key, value in accepted_selected_c.items()
    }:
        raise PhaseBError("accepted Phase-A manifest selected C values drifted")
    phase_a_selection_sha = sha256_file(phase_a_selection_path)
    prevalence = _load_array(phase_a_generation / "prevalence.npy", shape=(122,))
    edges_record = _load_json(phase_a_generation / "gc_bin_edges.json")
    fit_records = {
        (int(row["width"]), str(row["baseline"]), int(row["protein_id"])): row
        for row in phase_a_summary["fit_records"]
    }
    if len(fit_records) != 122 * 3 * 3:
        raise PhaseBError("Phase-A fit-record identities are incomplete")

    with gzip.open(membership_path, "rt", newline="") as handle:
        membership = read_membership(handle, expected_rows=expected_rows)
    with csv_path.open(newline="") as handle:
        labels = build_label_index(handle, membership, protein_ids=PROTEIN_IDS, allowed_partitions=set(TARGET_FRACTIONS))
    if any(labels.skipped_partition_rows.values()):
        raise PhaseBError("Phase B unexpectedly skipped a partition")
    balance_report, balance_counts = _balance_disclosure(labels)
    partition_manifest = _load_json(partition_manifest_path)
    expected_balance = partition_manifest.get("balance_disclosure", {})
    for key, actual in balance_counts.items():
        if expected_balance.get(key) != actual:
            raise PhaseBError(f"accepted imbalance disclosure mismatch for {key}: {actual}")

    membership_by_id = {row.sample_id: row for row in membership}
    test_ids: dict[int, list[str]] = {}
    test_y: dict[int, np.ndarray] = {}
    wanted: set[str] = set()
    for protein_id in PROTEIN_IDS:
        ids = labels.sample_ids.get((protein_id, "test"), [])
        values = np.asarray(labels.labels.get((protein_id, "test"), []), dtype=np.int8)
        if not ids or len(set(values.tolist())) != 2:
            raise PhaseBError(f"protein {protein_id} lacks both test classes")
        test_ids[protein_id] = ids
        test_y[protein_id] = values
        wanted.update(ids)
    ordered_ids = sorted(wanted, key=lambda value: int(value.removeprefix("row_")))
    row_lookup = {sample_id: index for index, sample_id in enumerate(ordered_ids)}
    test_rows = {
        protein_id: np.asarray([row_lookup[sample_id] for sample_id in test_ids[protein_id]], dtype=np.int64)
        for protein_id in PROTEIN_IDS
    }

    metric_rows: list[dict] = []
    feature_storage_bytes: dict[str, dict[str, int]] = {}
    scoring_seconds: dict[str, float] = {}
    prediction_count = 0
    with Generation(output_root, "final_phase_b") as generation:
        raw, compressed, text, writer = _open_prediction_writer(generation.candidate / "predictions.tsv.gz")
        try:
            for width in config.windows:
                with fasta_by_width[width].open() as handle:
                    sequence_by_id = read_fasta_subset(handle, wanted_ids=wanted, width=width)
                sequences = [sequence_by_id[sample_id] for sample_id in ordered_ids]
                matrices = {
                    "gc": gc_matrix(sequences),
                    "3mer": kmer_matrix(sequences, 3),
                    "6mer": kmer_matrix(sequences, 6),
                }
                models = {
                    baseline: _load_model(
                        phase_a_generation, width=width, baseline=baseline,
                        feature_count=int(matrices[baseline].shape[1]),
                    )
                    for baseline in ("gc", "3mer", "6mer")
                }
                feature_storage_bytes[str(width)] = {name: _array_bytes(matrix) for name, matrix in matrices.items()}
                feature_storage_bytes[str(width)]["total"] = sum(feature_storage_bytes[str(width)].values())
                width_started = time.monotonic()
                for protein_offset, protein_id in enumerate(PROTEIN_IDS):
                    rows = test_rows[protein_id]
                    y = test_y[protein_id]
                    ids = test_ids[protein_id]
                    gc_values = matrices["gc"][rows, 0]
                    try:
                        edges = [float(value) for value in edges_record[str(width)][str(protein_id)]]
                    except (KeyError, TypeError, ValueError) as exc:
                        raise PhaseBError(f"missing Phase-A GC edges for {width}/{protein_id}") from exc
                    matched = matched_indices_with_edges(
                        edges=edges, evaluation_gc=gc_values, labels=y, sample_ids=ids,
                        seed=config.seed, protein_id=protein_id, width=width,
                    )
                    matched_set = set(map(int, matched))
                    protein_balance = balance_report[protein_id]
                    flag_any = any(
                        protein_balance[part][cls]["flagged"]
                        for part in TARGET_FRACTIONS for cls in ("known_positive", "known_negative")
                    )
                    flag_eval = any(
                        protein_balance[part][cls]["flagged"]
                        for part in ("validation", "test") for cls in ("known_positive", "known_negative")
                    )
                    flag_test = any(
                        protein_balance["test"][cls]["flagged"]
                        for cls in ("known_positive", "known_negative")
                    )
                    for baseline in ("prevalence", "gc", "3mer", "6mer"):
                        c_value = None if baseline == "prevalence" else selected_c[f"{baseline}_{width}"]
                        if baseline == "prevalence":
                            scores = np.full(len(y), prevalence[protein_offset], dtype=np.float64)
                            n_iter = 0
                        else:
                            scores = _score_model(
                                models[baseline], baseline=baseline,
                                matrix=matrices[baseline][rows], protein_offset=protein_offset,
                            )
                            n_iter = int(fit_records[(width, baseline, protein_id)]["n_iter"])
                        full = summarize(y, scores)
                        secondary = summarize(y[matched], scores[matched])
                        if baseline == "prevalence" and (
                            full["auroc"] != 0.5
                            or not np.isclose(full["average_precision"], full["prevalence"], rtol=0, atol=1e-15)
                        ):
                            raise PhaseBError(f"prevalence sanity check failed for {width}/{protein_id}")
                        config_hash = _fit_hash(
                            config, phase_a_selection_sha256=phase_a_selection_sha,
                            baseline=baseline, width=width, protein_id=protein_id,
                            c_value=c_value, gc_edges=edges,
                        )
                        metric_rows.append({
                            "protein_id": protein_id, "width": width, "baseline": baseline,
                            "c": c_value, "converged": True, "n_iter": n_iter,
                            **full, "matched_count": len(matched),
                            "matched_positive_count": int(y[matched].sum()),
                            "matched_negative_count": int(len(matched) - y[matched].sum()),
                            "matched_auroc": secondary["auroc"],
                            "matched_average_precision": secondary["average_precision"],
                            "matched_prevalence": secondary["prevalence"],
                            "auroc_matched_minus_full": secondary["auroc"] - full["auroc"],
                            "average_precision_matched_minus_full": secondary["average_precision"] - full["average_precision"],
                            "imbalance_flag_any_partition": flag_any,
                            "imbalance_flag_validation_or_test": flag_eval,
                            "imbalance_flag_test": flag_test,
                            "test_positive_deviation_percentage_points": protein_balance["test"]["known_positive"]["deviation_percentage_points"],
                            "test_negative_deviation_percentage_points": protein_balance["test"]["known_negative"]["deviation_percentage_points"],
                            "gc_bin_edges": edges, "config_hash": config_hash,
                        })
                        for offset, sample_id in enumerate(ids):
                            writer.writerow({
                                "sample_id": sample_id,
                                "component_id": membership_by_id[sample_id].component_id,
                                "protein_id": protein_id, "fold": "components_v2_final",
                                "partition": "test", "seed": config.seed, "window": width,
                                "config_id": baseline, "config_hash": config_hash,
                                "label": int(y[offset]), "score": format(float(scores[offset]), ".17g"),
                                "gc_matched": int(offset in matched_set),
                            })
                            prediction_count += 1
                scoring_seconds[str(width)] = time.monotonic() - width_started
                del models, matrices, sequences, sequence_by_id
        finally:
            text.flush()
            text.detach()
            compressed.close()
            raw.close()

        metric_rows.sort(key=lambda row: (row["width"], row["baseline"], row["protein_id"]))
        aggregate_rows = _aggregate_metrics(metric_rows)
        _reproduce_metrics(
            generation.candidate / "predictions.tsv.gz", metric_rows, seed=config.seed,
        )
        summary = {
            "schema_version": "task003b_final_phase_b_v1", "status": "complete",
            "test_authorized": True, "test_accessed": True,
            "fit_partitions": ["train", "validation"], "evaluation_partition": "test",
            "models_refit_in_phase_b": 0, "protein_count": 122,
            "test_sequence_count": len(ordered_ids), "metric_row_count": len(metric_rows),
            "prediction_row_count": prediction_count, "gc_matched_sets_training_derived": True,
            "prediction_metric_reconciliation_passed": True,
            "selected_c": selected_c, "balance_disclosure": balance_counts,
            "feature_storage_bytes": feature_storage_bytes,
            "peak_width_feature_storage_bytes": max(row["total"] for row in feature_storage_bytes.values()),
            "scoring_seconds_by_width": scoring_seconds,
            "phase_a_selection_sha256": phase_a_selection_sha,
            "phase_a_generation": phase_a_selection["generation"],
            "implementation": _implementation_evidence(),
            "interpretation_boundary": {
                "descriptive_point_estimates_only": True,
                "no_significance_claims": True,
                "no_method_or_width_selected_from_test": True,
                "former_model_and_competitors_not_run": True,
            },
        }
        (generation.candidate / "metrics.json").write_bytes(canonical_json(metric_rows))
        (generation.candidate / "aggregate_metrics.json").write_bytes(canonical_json(aggregate_rows))
        (generation.candidate / "summary.json").write_bytes(canonical_json(summary))
        return generation.commit(
            fingerprint=fingerprint,
            payload={
                "test_accessed": True, "models_refit_in_phase_b": 0,
                "metric_row_count": len(metric_rows), "prediction_row_count": prediction_count,
                "prediction_metric_reconciliation_passed": True,
            },
        )
