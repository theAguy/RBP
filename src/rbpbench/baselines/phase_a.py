"""Task 003B-3 Phase A: fit all final models without test access."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Mapping

import numpy as np

from rbpbench.baselines.config import BaselineConfig, canonical_json
from rbpbench.baselines.data import build_label_index, read_membership
from rbpbench.baselines.features import gc_matrix, kmer_matrix, read_fasta_subset
from rbpbench.baselines.gc_matching import gc_bin_edges
from rbpbench.baselines.models import fit_logistic, prevalence_score
from rbpbench.baselines.output import Generation, verify_selected
from rbpbench.baselines.pilot import sha256_file


class PhaseAError(RuntimeError):
    pass


PROTEIN_IDS = tuple(range(1, 123))
EXPECTED_SELECTED_C_KEYS = {
    f"{baseline}_{width}" for baseline in ("gc", "3mer", "6mer") for width in (500, 251, 101)
}


def selected_c_from_manifest(path: Path) -> dict[str, float]:
    record = json.loads(path.read_text())
    if record.get("schema_version") != "task003b_pilot_acceptance_v1" or record.get("status") != "accepted":
        raise PhaseAError("pilot manifest is not accepted")
    boundary = record.get("test_boundary", {})
    if boundary.get("test_accessed") is not False or boundary.get("final_stage_authorized") is not False:
        raise PhaseAError("pilot manifest test boundary is invalid")
    selected = record.get("development", {}).get("selected_c", {})
    if set(selected) != EXPECTED_SELECTED_C_KEYS:
        raise PhaseAError("pilot manifest selected-C keys are incomplete")
    values = {key: float(value) for key, value in selected.items()}
    if any(value not in (0.01, 0.1, 1.0, 10.0) for value in values.values()):
        raise PhaseAError("pilot manifest contains an unapproved C value")
    return values


def phase_a_fingerprint(
    config: BaselineConfig,
    *,
    csv_path: Path,
    membership_path: Path,
    fasta_by_width: Mapping[int, Path],
    pilot_manifest_path: Path,
) -> str:
    evidence = {
        "config_semantic_sha256": config.semantic_sha256,
        "csv_sha256": sha256_file(csv_path),
        "membership_sha256": sha256_file(membership_path),
        "fastas": {str(width): sha256_file(fasta_by_width[width]) for width in config.windows},
        "pilot_manifest_sha256": sha256_file(pilot_manifest_path),
        "mode": "train_plus_validation_fit_all_122_no_test_access",
    }
    return hashlib.sha256(canonical_json(evidence)).hexdigest()


def _array_bytes(matrix) -> int:
    if hasattr(matrix, "indptr"):
        return int(matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes)
    return int(matrix.nbytes)


def _write_array(path: Path, value) -> None:
    with path.open("wb") as handle:
        np.save(handle, np.asarray(value), allow_pickle=False)


def run_phase_a(
    *,
    config: BaselineConfig,
    csv_path: Path,
    membership_path: Path,
    fasta_by_width: Mapping[int, Path],
    pilot_manifest_path: Path,
    output_root: Path,
    expected_rows: int | None = None,
    force: bool = False,
) -> Path:
    selected_c = selected_c_from_manifest(pilot_manifest_path)
    fingerprint = phase_a_fingerprint(
        config, csv_path=csv_path, membership_path=membership_path,
        fasta_by_width=fasta_by_width, pilot_manifest_path=pilot_manifest_path,
    )
    if not force:
        selected = verify_selected(output_root, "final_phase_a", fingerprint=fingerprint)
        if selected is not None:
            return output_root / selected["generation"]

    with gzip.open(membership_path, "rt", newline="") as handle:
        membership = read_membership(handle, expected_rows=expected_rows)
    with csv_path.open(newline="") as handle:
        labels = build_label_index(
            handle, membership, protein_ids=PROTEIN_IDS,
            allowed_partitions={"train", "validation"},
        )
    wanted: set[str] = set()
    fit_ids: dict[int, list[str]] = {}
    fit_y: dict[int, np.ndarray] = {}
    count_report: dict[str, dict[str, int]] = {}
    for protein_id in PROTEIN_IDS:
        sample_ids = labels.sample_ids.get((protein_id, "train"), []) + labels.sample_ids.get((protein_id, "validation"), [])
        values = labels.labels.get((protein_id, "train"), []) + labels.labels.get((protein_id, "validation"), [])
        y = np.asarray(values, dtype=np.int8)
        if not sample_ids or len(set(y.tolist())) != 2:
            raise PhaseAError(f"protein {protein_id} lacks both fitting classes")
        fit_ids[protein_id] = sample_ids
        fit_y[protein_id] = y
        wanted.update(sample_ids)
        positives = int(y.sum())
        count_report[str(protein_id)] = {
            "known": len(y), "positive": positives, "negative": len(y) - positives,
        }

    ordered_ids = sorted(wanted, key=lambda value: int(value.removeprefix("row_")))
    row_lookup = {sample_id: index for index, sample_id in enumerate(ordered_ids)}
    fit_rows = {
        protein_id: np.asarray([row_lookup[sample_id] for sample_id in fit_ids[protein_id]], dtype=np.int64)
        for protein_id in PROTEIN_IDS
    }
    summary = {
        "schema_version": "task003b_final_phase_a_v1",
        "status": "complete",
        "fit_partitions": ["train", "validation"],
        "test_accessed": False,
        "test_labels_parsed": 0,
        "test_features_built": 0,
        "test_predictions_emitted": 0,
        "protein_count": len(PROTEIN_IDS),
        "fitting_sequence_count": len(ordered_ids),
        "selected_c": selected_c,
        "known_label_counts": count_report,
        "feature_storage_bytes": {},
        "fit_records": [],
        "all_fits_converged": False,
    }

    with Generation(output_root, "final_phase_a") as generation:
        prevalence = np.empty(len(PROTEIN_IDS), dtype=np.float64)
        for offset, protein_id in enumerate(PROTEIN_IDS):
            prevalence[offset] = prevalence_score(fit_y[protein_id])
        _write_array(generation.candidate / "prevalence.npy", prevalence)

        gc_edges_record: dict[str, dict[str, list[float]]] = {}
        for width in config.windows:
            with fasta_by_width[width].open() as handle:
                sequence_by_id = read_fasta_subset(handle, wanted_ids=wanted, width=width)
            sequences = [sequence_by_id[sample_id] for sample_id in ordered_ids]
            matrices = {
                "gc": gc_matrix(sequences),
                "3mer": kmer_matrix(sequences, 3),
                "6mer": kmer_matrix(sequences, 6),
            }
            summary["feature_storage_bytes"][str(width)] = {
                name: _array_bytes(matrix) for name, matrix in matrices.items()
            }
            summary["feature_storage_bytes"][str(width)]["total"] = sum(
                summary["feature_storage_bytes"][str(width)].values()
            )
            gc_edges_record[str(width)] = {}
            gc_values = matrices["gc"][:, 0]
            for protein_id in PROTEIN_IDS:
                rows = fit_rows[protein_id]
                gc_edges_record[str(width)][str(protein_id)] = gc_bin_edges(gc_values[rows]).tolist()

            for baseline in ("gc", "3mer", "6mer"):
                matrix = matrices[baseline]
                feature_count = int(matrix.shape[1])
                coefs = np.empty((len(PROTEIN_IDS), feature_count), dtype=np.float64)
                scales = np.empty_like(coefs)
                means = np.empty_like(coefs) if baseline == "gc" else None
                intercepts = np.empty(len(PROTEIN_IDS), dtype=np.float64)
                c_value = selected_c[f"{baseline}_{width}"]
                for offset, protein_id in enumerate(PROTEIN_IDS):
                    rows = fit_rows[protein_id]
                    fit = fit_logistic(
                        matrix[rows], fit_y[protein_id], c_value=c_value,
                        seed=config.seed, max_iter=config.max_iter, tol=config.tol,
                    )
                    if not fit.converged:
                        raise PhaseAError(
                            f"{baseline}_{width} protein {protein_id} did not converge: "
                            f"n_iter={fit.n_iter}, warnings={fit.warning_messages}"
                        )
                    coefs[offset] = fit.estimator.coef_[0]
                    scales[offset] = fit.scaler.scale_
                    if means is not None:
                        means[offset] = fit.scaler.mean_
                    intercepts[offset] = fit.estimator.intercept_[0]
                    summary["fit_records"].append({
                        "protein_id": protein_id, "width": width, "baseline": baseline,
                        "c": c_value, "converged": True, "n_iter": fit.n_iter,
                        "known": count_report[str(protein_id)]["known"],
                    })
                prefix = f"model_{width}_{baseline}"
                _write_array(generation.candidate / f"{prefix}_coef.npy", coefs)
                _write_array(generation.candidate / f"{prefix}_scale.npy", scales)
                _write_array(generation.candidate / f"{prefix}_intercept.npy", intercepts)
                if means is not None:
                    _write_array(generation.candidate / f"{prefix}_mean.npy", means)
            del matrices, sequences, sequence_by_id

        summary["fit_record_count"] = len(summary["fit_records"])
        summary["all_fits_converged"] = summary["fit_record_count"] == 122 * 3 * 3
        if not summary["all_fits_converged"]:
            raise PhaseAError("Phase A fit count is incomplete")
        summary["peak_width_feature_storage_bytes"] = max(
            row["total"] for row in summary["feature_storage_bytes"].values()
        )
        (generation.candidate / "gc_bin_edges.json").write_bytes(canonical_json(gc_edges_record))
        (generation.candidate / "summary.json").write_bytes(canonical_json(summary))
        return generation.commit(
            fingerprint=fingerprint,
            payload={
                "test_accessed": False,
                "all_fits_converged": True,
                "fit_record_count": summary["fit_record_count"],
                "selected_c": selected_c,
            },
        )
