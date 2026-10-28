"""Train-only to validation-only Task 003B development pilot."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Mapping

import numpy as np

from rbpbench.baselines.config import BaselineConfig, canonical_json
from rbpbench.baselines.data import build_label_index, read_membership
from rbpbench.baselines.features import gc_matrix, kmer_matrix, read_fasta_subset
from rbpbench.baselines.gc_matching import matched_indices
from rbpbench.baselines.metrics import summarize
from rbpbench.baselines.models import fit_logistic, prevalence_score, select_c
from rbpbench.baselines.output import Generation, verify_selected


class PilotError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pilot_fingerprint(config: BaselineConfig, *, csv_path: Path, membership_path: Path, fasta_by_width: Mapping[int, Path]) -> str:
    evidence = {
        "config_semantic_sha256": config.semantic_sha256,
        "csv_sha256": sha256_file(csv_path),
        "membership_sha256": sha256_file(membership_path),
        "fastas": {str(width): sha256_file(fasta_by_width[width]) for width in config.windows},
        "mode": "train_to_validation_development_pilot",
    }
    return hashlib.sha256(canonical_json(evidence)).hexdigest()


def _tsv_gzip(rows: list[dict], fields: list[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return gzip.compress(buffer.getvalue().encode(), compresslevel=6, mtime=0)


def _fit_hash(config: BaselineConfig, *, baseline: str, width: int, protein_id: int, c_value: float | None, gc_edges: list[float]) -> str:
    value = {
        "base_config": config.semantic_sha256, "stage": "pilot",
        "fit_partitions": ["train"], "evaluation_partition": "validation",
        "baseline": baseline, "width": width, "protein_id": protein_id,
        "c": c_value, "gc_edges": gc_edges,
    }
    return hashlib.sha256(canonical_json(value)).hexdigest()


def run_pilot(
    *,
    config: BaselineConfig,
    csv_path: Path,
    membership_path: Path,
    fasta_by_width: Mapping[int, Path],
    output_root: Path,
    expected_rows: int | None = None,
    force: bool = False,
) -> Path:
    fingerprint = pilot_fingerprint(config, csv_path=csv_path, membership_path=membership_path, fasta_by_width=fasta_by_width)
    if not force:
        selected = verify_selected(output_root, "pilot", fingerprint=fingerprint)
        if selected is not None:
            return output_root / selected["generation"]
    with gzip.open(membership_path, "rt", newline="") as handle:
        membership = read_membership(handle, expected_rows=expected_rows)
    with csv_path.open(newline="") as handle:
        labels = build_label_index(
            handle, membership,
            protein_ids=config.development_protein_ids,
            allowed_partitions={"train", "validation"},
        )
    wanted = set()
    for sample_ids in labels.sample_ids.values():
        wanted.update(sample_ids)
    if not wanted:
        raise PilotError("pilot found no known train/validation labels")
    membership_by_id = {row.sample_id: row for row in membership}
    ordered_ids = sorted(wanted, key=lambda value: int(value.removeprefix("row_")))
    row_lookup = {sample_id: index for index, sample_id in enumerate(ordered_ids)}

    metrics_rows: list[dict] = []
    prediction_rows: list[dict] = []
    selections: dict[str, dict] = {}
    feature_storage_bytes: dict[str, dict[str, int]] = {}
    for width in config.windows:
        with fasta_by_width[width].open() as handle:
            sequence_by_id = read_fasta_subset(handle, wanted_ids=wanted, width=width)
        sequences = [sequence_by_id[sample_id] for sample_id in ordered_ids]
        gc_all = gc_matrix(sequences)
        matrices = {"gc": gc_all, "3mer": kmer_matrix(sequences, 3), "6mer": kmer_matrix(sequences, 6)}
        feature_storage_bytes[str(width)] = {}
        for name, matrix in matrices.items():
            if hasattr(matrix, "indptr"):
                byte_size = int(matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes)
            else:
                byte_size = int(matrix.nbytes)
            feature_storage_bytes[str(width)][name] = byte_size
        feature_storage_bytes[str(width)]["total"] = sum(feature_storage_bytes[str(width)].values())

        for protein_id in config.development_protein_ids:
            train_ids = labels.sample_ids.get((protein_id, "train"), [])
            train_y = np.asarray(labels.labels.get((protein_id, "train"), []), dtype=np.int8)
            valid_ids = labels.sample_ids.get((protein_id, "validation"), [])
            valid_y = np.asarray(labels.labels.get((protein_id, "validation"), []), dtype=np.int8)
            if not train_ids or not valid_ids or len(set(train_y)) != 2 or len(set(valid_y)) != 2:
                raise PilotError(f"protein {protein_id} lacks both classes in train or validation")
            train_rows = np.asarray([row_lookup[sample_id] for sample_id in train_ids])
            valid_rows = np.asarray([row_lookup[sample_id] for sample_id in valid_ids])
            train_gc = gc_all[train_rows, 0]
            valid_gc = gc_all[valid_rows, 0]

            prevalence = prevalence_score(train_y)
            prevalence_scores = np.full(len(valid_y), prevalence)
            full = summarize(valid_y, prevalence_scores)
            matched, edges = matched_indices(
                fitting_gc=train_gc, evaluation_gc=valid_gc, labels=valid_y,
                sample_ids=valid_ids, seed=config.seed, protein_id=protein_id, width=width,
            )
            matched_summary = summarize(valid_y[matched], prevalence_scores[matched])
            config_hash = _fit_hash(config, baseline="prevalence", width=width, protein_id=protein_id, c_value=None, gc_edges=edges.tolist())
            metrics_rows.append({
                "protein_id": protein_id, "width": width, "baseline": "prevalence", "c": "",
                "converged": True, "n_iter": 0, **full,
                "matched_count": len(matched), "matched_auroc": matched_summary["auroc"],
                "matched_average_precision": matched_summary["average_precision"], "config_hash": config_hash,
            })
            for offset, sample_id in enumerate(valid_ids):
                prediction_rows.append({
                    "sample_id": sample_id, "component_id": membership_by_id[sample_id].component_id,
                    "protein_id": protein_id, "fold": "components_v2_pilot", "partition": "validation",
                    "seed": config.seed, "window": width, "config_id": "prevalence", "config_hash": config_hash,
                    "label": int(valid_y[offset]), "score": format(float(prevalence_scores[offset]), ".17g"),
                })

            for baseline in ("gc", "3mer", "6mer"):
                matrix = matrices[baseline]
                candidate_metrics: dict[float, list[dict]] = {c: [] for c in config.c_grid}
                fits = {}
                for c_value in config.c_grid:
                    fit = fit_logistic(matrix[train_rows], train_y, c_value=c_value, seed=config.seed, max_iter=config.max_iter, tol=config.tol)
                    scores = fit.scores(matrix[valid_rows])
                    summary = summarize(valid_y, scores)
                    candidate_metrics[c_value].append({"protein_id": protein_id, "converged": fit.converged, "auroc": summary["auroc"]})
                    fits[c_value] = (fit, scores, summary)
                # Selection is across all eight proteins, so defer until all
                # per-protein candidate evidence for this width is collected.
                selections.setdefault(f"{baseline}_{width}", {"candidates": {str(c): [] for c in config.c_grid}, "protein_context": {}})
                selection = selections[f"{baseline}_{width}"]
                selection["protein_context"][str(protein_id)] = {
                    "train_rows": train_rows, "valid_rows": valid_rows, "train_y": train_y,
                    "valid_y": valid_y, "train_gc": train_gc, "valid_gc": valid_gc,
                    "valid_ids": valid_ids, "fits": fits,
                }
                for c_value in config.c_grid:
                    selection["candidates"][str(c_value)].append(candidate_metrics[c_value][0])

        for baseline in ("gc", "3mer", "6mer"):
            selection = selections[f"{baseline}_{width}"]
            candidates = {float(key): value for key, value in selection["candidates"].items()}
            selected_c, evidence = select_c(candidates)
            selection["selected_c"] = selected_c
            selection["evidence"] = evidence
            for protein_id in config.development_protein_ids:
                context = selection["protein_context"][str(protein_id)]
                fit, scores, full = context["fits"][selected_c]
                matched, edges = matched_indices(
                    fitting_gc=context["train_gc"], evaluation_gc=context["valid_gc"],
                    labels=context["valid_y"], sample_ids=context["valid_ids"],
                    seed=config.seed, protein_id=protein_id, width=width,
                )
                matched_summary = summarize(context["valid_y"][matched], scores[matched])
                config_hash = _fit_hash(config, baseline=baseline, width=width, protein_id=protein_id, c_value=selected_c, gc_edges=edges.tolist())
                metrics_rows.append({
                    "protein_id": protein_id, "width": width, "baseline": baseline, "c": selected_c,
                    "converged": fit.converged, "n_iter": fit.n_iter, **full,
                    "matched_count": len(matched), "matched_auroc": matched_summary["auroc"],
                    "matched_average_precision": matched_summary["average_precision"], "config_hash": config_hash,
                })
                for offset, sample_id in enumerate(context["valid_ids"]):
                    prediction_rows.append({
                        "sample_id": sample_id, "component_id": membership_by_id[sample_id].component_id,
                        "protein_id": protein_id, "fold": "components_v2_pilot", "partition": "validation",
                        "seed": config.seed, "window": width, "config_id": baseline, "config_hash": config_hash,
                        "label": int(context["valid_y"][offset]), "score": format(float(scores[offset]), ".17g"),
                    })
            # Drop fitted objects and arrays before serializing selection.
            del selection["protein_context"]

    metrics_rows.sort(key=lambda row: (int(row["width"]), str(row["baseline"]), int(row["protein_id"])), reverse=True)
    prediction_rows.sort(key=lambda row: (int(row["window"]), str(row["config_id"]), int(row["protein_id"]), int(str(row["sample_id"]).removeprefix("row_"))), reverse=True)
    serializable_selections = {
        key: {"selected_c": value["selected_c"], "evidence": value["evidence"]}
        for key, value in sorted(selections.items())
    }
    summary = {
        "schema_version": "task003b_pilot_v1", "status": "complete",
        "test_accessed": False, "test_labels_parsed": 0, "test_features_built": 0,
        "protein_ids": list(config.development_protein_ids), "widths": list(config.windows),
        "selected_c": {key: value["selected_c"] for key, value in serializable_selections.items()},
        "selection_evidence": serializable_selections,
        "metric_row_count": len(metrics_rows), "prediction_row_count": len(prediction_rows),
        "development_sequence_count": len(ordered_ids),
        "feature_storage_bytes": feature_storage_bytes,
        "peak_width_feature_storage_bytes": max(row["total"] for row in feature_storage_bytes.values()),
    }
    with Generation(output_root, "pilot") as generation:
        (generation.candidate / "summary.json").write_bytes(canonical_json(summary))
        (generation.candidate / "metrics.json").write_bytes(canonical_json(metrics_rows))
        fields = ["sample_id", "component_id", "protein_id", "fold", "partition", "seed", "window", "config_id", "config_hash", "label", "score"]
        (generation.candidate / "predictions.tsv.gz").write_bytes(_tsv_gzip(prediction_rows, fields))
        return generation.commit(fingerprint=fingerprint, payload={"test_accessed": False, "selected_c": summary["selected_c"]})
