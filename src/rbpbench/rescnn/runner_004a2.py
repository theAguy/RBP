"""Single-invocation local runner for the reviewed Task 004A-2 smoke.

Real execution is intentionally not performed during 004A-2A.  This module
provides the reviewed boundary for the separately authorized 004A-2B run.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import gzip
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Iterator, Mapping

import torch

from rbpbench.rescnn.checkpoint import sha256_file
from rbpbench.rescnn.config import Task004AConfig, load_config
from rbpbench.rescnn.data_004a2 import (
    AuditResult,
    CacheBuildResult,
    audit_streams,
    build_cache_streams,
    require_count_reconciliation,
)
from rbpbench.rescnn.environment_004a2 import (
    canonical_manifest_bytes,
    discover_environment_manifest,
    environment_sha256,
)
from rbpbench.rescnn.model import (
    CNNMultiLabelResidual,
    EXPECTED_LEARNABLE_PARAMETERS,
    count_learnable_parameters,
)
from rbpbench.rescnn.output import (
    PREDICTION_FIELDS,
    WholeRunGeneration,
    atomic_write,
    canonical_json,
    generation_inventory,
    validate_prediction_rows,
    verify_selected,
)
from rbpbench.rescnn.reproducibility import configure_strict_float32
from rbpbench.rescnn.resources_004a2 import (
    GIB,
    configure_exact_threads,
    local_resource_snapshot,
    require_local_resources,
)
from rbpbench.rescnn.smoke_004a2 import run_paired_smoke, scientific_signature


CONFIG_SHA256 = "fb3faeee566b1eb799f4c550f143cf05d90358301bd732e21a4928208e2c498f"
PHASE_A_MANIFEST_SHA256 = "77922d6d906b7a4fd9ba8cae091e93072b0e1b09735a0397cdead2b2dfeed257"
EXPECTED_PARTITIONS = {"train": 246017, "validation": 57565, "test": 57598}
EXPECTED_COMPONENTS = 169699
EXPECTED_BOUNDS = {
    "train_plus_validation_rows": 303582,
    "known_labels_per_protein_min": 806,
    "known_labels_per_protein_max": 3159,
    "positive_labels_per_protein_min": 388,
    "negative_labels_per_protein_min": 408,
}
STAGE = "local_data_contract_smoke"
TIMEOUT_SECONDS = 2 * 60 * 60
MAX_GENERATION_BYTES = GIB


class ResCNN004A2RunnerError(RuntimeError):
    pass


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
        raise ResCNN004A2RunnerError(f"{label} is not a lowercase SHA-256")
    return value


def _bound_source_evidence(repo_root: Path) -> dict[str, object]:
    """Bind every already-loaded rbpbench module to the source tree and hash it."""

    source_root = (Path(repo_root) / "src").resolve()
    files: dict[Path, set[str]] = {}
    for module_name, module in sorted(sys.modules.items()):
        if module_name != "rbpbench" and not module_name.startswith("rbpbench."):
            continue
        raw_file = getattr(module, "__file__", None)
        if not isinstance(raw_file, str):
            raise ResCNN004A2RunnerError(f"loaded module has no source file: {module_name}")
        unresolved = Path(raw_file)
        if unresolved.is_symlink():
            raise ResCNN004A2RunnerError(f"loaded module uses a symlink: {module_name}")
        path = unresolved.resolve()
        if path.suffix != ".py" or not path.is_file() or not path.is_relative_to(source_root):
            raise ResCNN004A2RunnerError(
                f"loaded module is outside repo_root/src: {module_name} -> {path}"
            )
        files.setdefault(path, set()).add(module_name)
    if not files:
        raise ResCNN004A2RunnerError("no loaded rbpbench source modules were found")

    digest = hashlib.sha256()
    entries: list[dict[str, object]] = []
    for path in sorted(files):
        relative_text = path.relative_to(source_root).as_posix()
        relative = relative_text.encode("utf-8")
        file_sha256 = sha256_file(path)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(file_sha256))
        entries.append({
            "path": relative_text,
            "sha256": file_sha256,
            "modules": sorted(files[path]),
        })
    return {"sha256": digest.hexdigest(), "files": entries}


def _source_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True,
        text=True, capture_output=True, timeout=10,
    )
    value = completed.stdout.strip()
    if len(value) != 40 or set(value) - set("0123456789abcdef"):
        raise ResCNN004A2RunnerError("Git HEAD is not a full commit hash")
    return value


def _require_clean_worktree(repo_root: Path) -> None:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_root, check=True, text=True, capture_output=True, timeout=10,
    )
    if completed.stdout.strip():
        raise ResCNN004A2RunnerError(
            "worktree, including untracked files, must be clean before real execution"
        )


def resolve_fasta_500(repo_root: Path, decode_manifest: Path, expected_sha256: str) -> Path:
    payload = json.loads(Path(decode_manifest).read_text())
    matches = [
        row for row in payload.get("retained_artifacts", [])
        if isinstance(row, dict)
        and row.get("sha256") == expected_sha256
        and str(row.get("path", "")).endswith("sequence_partitions_width_500.fasta")
    ]
    if len(matches) != 1:
        raise ResCNN004A2RunnerError("decode manifest does not identify exactly one accepted 500-nt FASTA")
    relative = Path(str(matches[0]["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ResCNN004A2RunnerError("decode-manifest FASTA path is unsafe")
    resolved_root = Path(repo_root).resolve()
    unresolved = resolved_root / relative
    cursor = unresolved
    while cursor != resolved_root and cursor != cursor.parent:
        if cursor.is_symlink():
            raise ResCNN004A2RunnerError("decode-manifest FASTA path traverses a symlink")
        cursor = cursor.parent
    path = unresolved.resolve()
    if not path.is_relative_to(resolved_root) or not path.is_file():
        raise ResCNN004A2RunnerError("accepted 500-nt FASTA is missing or a symlink")
    if path.stat().st_size != int(matches[0]["byte_size"]):
        raise ResCNN004A2RunnerError("accepted 500-nt FASTA size drift")
    return path


def _verify_environment(path: Path) -> tuple[dict[str, object], str]:
    recorded = json.loads(Path(path).read_text())
    live = discover_environment_manifest()
    if canonical_manifest_bytes(recorded) != canonical_manifest_bytes(live):
        raise ResCNN004A2RunnerError("live environment differs from the frozen local manifest")
    digest = environment_sha256(recorded)
    return recorded, digest


def _input_evidence(
    path: Path, expected_sha256: str, label: str, *, repo_root: Path,
) -> dict[str, object]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ResCNN004A2RunnerError(f"{label} is missing or a symlink")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ResCNN004A2RunnerError(f"{label} SHA-256 drift")
    resolved = path.resolve()
    root = Path(repo_root).resolve()
    if not resolved.is_relative_to(root):
        raise ResCNN004A2RunnerError(f"{label} is outside the repository")
    return {
        "path": resolved.relative_to(root).as_posix(),
        "byte_size": resolved.stat().st_size,
        "sha256": actual,
    }


def _fingerprint(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _phase_a_bounds_from_payload(payload: object) -> dict[str, int]:
    """Translate the accepted Task 003B Phase-A schema to 004A-2 names."""

    if not isinstance(payload, dict):
        raise ResCNN004A2RunnerError("Task 003B Phase A manifest is not an object")
    fitting = payload.get("fitting")
    if not isinstance(fitting, dict):
        raise ResCNN004A2RunnerError("Task 003B Phase A fitting evidence is missing")
    if fitting.get("partitions") != ["train", "validation"]:
        raise ResCNN004A2RunnerError("Task 003B Phase A development partitions drift")
    if fitting.get("protein_count") != 122:
        raise ResCNN004A2RunnerError("Task 003B Phase A protein count drift")

    # Task 003B calls this aggregate ``fitting_sequence_count``.  Task 004A-2
    # uses the more explicit internal name ``train_plus_validation_rows``.
    # The translation is deliberate; it must not be inferred by matching
    # values or by accepting either field name interchangeably.
    observed = {
        "train_plus_validation_rows": fitting.get("fitting_sequence_count"),
        "known_labels_per_protein_min": fitting.get("known_labels_per_protein_min"),
        "known_labels_per_protein_max": fitting.get("known_labels_per_protein_max"),
        "positive_labels_per_protein_min": fitting.get("positive_labels_per_protein_min"),
        "negative_labels_per_protein_min": fitting.get("negative_labels_per_protein_min"),
    }
    if observed != EXPECTED_BOUNDS:
        raise ResCNN004A2RunnerError("Task 003B Phase A development bounds drift")
    return observed


def _verify_phase_a_bounds(path: Path, *, repo_root: Path) -> dict[str, object]:
    evidence = _input_evidence(
        path, PHASE_A_MANIFEST_SHA256, "Task 003B Phase A manifest", repo_root=repo_root,
    )
    payload = json.loads(Path(path).read_text())
    _phase_a_bounds_from_payload(payload)
    return evidence


def _structural_access_evidence() -> dict[str, int | bool | str]:
    return {
        "test_rows_seen": 0,
        "test_label_supplier_calls": 0,
        "test_csv_sequence_supplier_calls": 0,
        "test_fasta_sequence_interpretations": 0,
        "test_tensor_rows": 0,
        "test_prediction_rows": 0,
        "test_accessed": False,
        "measurement": "structural: test rows branch before field interpretation",
    }


def _write_stop_record(
    output_dir: Path,
    *,
    stage: str,
    error: Exception,
    input_evidence: Mapping[str, object],
    gate_a_access: Mapping[str, object] | None,
    gate_b_access: Mapping[str, object] | None,
) -> Path:
    path = Path(output_dir) / "STOPPED.json"
    if path.exists():
        raise ResCNN004A2RunnerError("a prior STOPPED.json requires review before any retry")
    gate_a = dict(gate_a_access) if gate_a_access is not None else _structural_access_evidence()
    gate_b = dict(gate_b_access) if gate_b_access is not None else _structural_access_evidence()
    payload = {
        "schema_version": "task004a2_sanitized_stop_v1",
        "status": "STOPPED",
        "stage": stage,
        "error": {
            "class": type(error).__name__,
            "message": str(error).replace("\n", " ")[:1000],
        },
        "input_evidence": dict(input_evidence),
        "access_counters": {"gate_a": gate_a, "gate_b": gate_b},
        "test_accessed": bool(gate_a.get("test_accessed") or gate_b.get("test_accessed")),
        "selection_record_written": False,
        "retry_authorized": False,
    }
    atomic_write(path, canonical_json(payload))
    return path


def _production_model_factory(output_count: int) -> CNNMultiLabelResidual:
    model = CNNMultiLabelResidual(output_count)
    if type(model) is not CNNMultiLabelResidual:
        raise ResCNN004A2RunnerError("production model class drifted")
    parameters = count_learnable_parameters(model)
    if parameters != EXPECTED_LEARNABLE_PARAMETERS:
        raise ResCNN004A2RunnerError(
            f"production model has {parameters} learnable parameters; "
            f"expected {EXPECTED_LEARNABLE_PARAMETERS}"
        )
    return model


def _open_membership(path: Path):
    return gzip.open(path, "rt", newline="")


def _write_selected_rows(path: Path, audit: AuditResult) -> None:
    rows = ["sample_id\tcomponent_id\tpartition\tcontent_sha256\n"]
    for partition in ("train", "validation"):
        for candidate in audit.selected[partition]:
            rows.append(
                f"{candidate.sample_id}\t{candidate.component_id}\t{partition}\t"
                f"{candidate.content_sha256}\n"
            )
    atomic_write(path, "".join(rows).encode("utf-8"))


def _write_predictions(path: Path, cache_result: CacheBuildResult, smoke, config_hash: str) -> int:
    cache = cache_result.cache
    validation_indices = cache.indices("validation")
    rows: list[dict[str, object]] = []
    for config_id, result in smoke.by_config.items():
        scores = result.validation_scores
        for local_index, cache_index in enumerate(validation_indices):
            targets = cache.targets[cache_index]
            masks = cache.masks[cache_index]
            for protein_index in range(122):
                if int(masks[protein_index]) == 0:
                    continue
                rows.append({
                    "sample_id": cache.sample_ids[cache_index],
                    "component_id": cache.component_ids[cache_index],
                    "protein_id": protein_index + 1,
                    "fold": "components_v2_coverage_smoke",
                    "partition": "validation",
                    "seed": 20261029,
                    "window": 500,
                    "config_id": config_id,
                    "config_hash": config_hash,
                    "label": int(targets[protein_index]),
                    "score": float(scores[local_index, protein_index]),
                })
    count = validate_prediction_rows(
        rows, artifact_role="coverage_smoke",
        schema_version="task004a_smoke_prediction_v1",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=PREDICTION_FIELDS, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return count


@contextmanager
def _deadline(seconds: int):
    if seconds <= 0:
        raise ResCNN004A2RunnerError("timeout must be positive")

    def expired(_signum, _frame):
        raise TimeoutError("Task 004A-2 exceeded its two-hour timeout")

    prior = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prior)


def execute(args) -> Path:
    start = time.monotonic()
    repo_root = Path(args.repo_root).resolve()
    _require_clean_worktree(repo_root)
    source_evidence = _bound_source_evidence(repo_root)
    source_digest = str(source_evidence["sha256"])
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    if sha256_file(config_path) != CONFIG_SHA256:
        raise ResCNN004A2RunnerError("Task 004A config SHA-256 drift")

    # Environment and host checks occur before any real CSV/membership/FASTA is opened.
    _environment, environment_digest = _verify_environment(Path(args.environment_manifest))
    thread_evidence = configure_exact_threads(torch)
    strict_evidence = configure_strict_float32(require_cuda=False)
    if torch.cuda.is_available():
        raise ResCNN004A2RunnerError("Task 004A-2 is CPU-only")
    before_a = local_resource_snapshot(Path(args.output_dir).parent)
    require_local_resources(before_a)

    fixed = {
        "config": _input_evidence(
            config_path, CONFIG_SHA256, "config", repo_root=repo_root,
        ),
        "csv": _input_evidence(
            Path(args.csv), config.inputs["csv_sha256"], "CSV", repo_root=repo_root,
        ),
        "dataset_audit": _input_evidence(
            Path(args.dataset_audit), config.inputs["dataset_audit_sha256"], "dataset audit",
            repo_root=repo_root,
        ),
        "proteins": _input_evidence(
            Path(args.proteins), config.inputs["proteins_sha256"], "proteins config",
            repo_root=repo_root,
        ),
        "decode_manifest": _input_evidence(
            Path(args.decode_manifest), config.inputs["decode_manifest_sha256"], "decode manifest",
            repo_root=repo_root,
        ),
        "partition_manifest": _input_evidence(
            Path(args.partition_manifest), config.inputs["partition_manifest_sha256"],
            "partition manifest", repo_root=repo_root,
        ),
        "membership": _input_evidence(
            Path(args.membership), config.inputs["membership_sha256"], "membership",
            repo_root=repo_root,
        ),
        "phase_a_manifest": _verify_phase_a_bounds(
            Path(args.phase_a_manifest), repo_root=repo_root,
        ),
    }
    fasta_path = resolve_fasta_500(
        repo_root, Path(args.decode_manifest), config.inputs["fasta_500_sha256"],
    )
    fixed["fasta_500"] = _input_evidence(
        fasta_path, config.inputs["fasta_500_sha256"], "500-nt FASTA", repo_root=repo_root,
    )
    output_dir = Path(args.output_dir)
    if (output_dir / "STOPPED.json").exists():
        raise ResCNN004A2RunnerError("a prior STOPPED.json requires review before any retry")

    audit: AuditResult | None = None
    cache_result: CacheBuildResult | None = None
    stage = "post_input_hash"
    try:
        provenance = {
            "inputs": fixed,
            "source_commit": _source_commit(repo_root),
            "source_sha256": source_digest,
            "source_files": source_evidence["files"],
            "environment_sha256": environment_digest,
            "threads": thread_evidence,
            "strict_float32": strict_evidence,
        }
        fingerprint = _fingerprint(provenance)
        stage = "restart_validation"
        prior = verify_selected(output_dir, STAGE, fingerprint=fingerprint)
        if prior is not None:
            return output_dir / prior["generation"]

        factory = lambda: _production_model_factory(config.output_count)
        with _deadline(TIMEOUT_SECONDS), WholeRunGeneration(output_dir, STAGE) as generation:
            stage = "gate_a_audit"
            with _open_membership(Path(args.membership)) as membership, \
                 Path(args.csv).open("r", newline="") as csv_handle, \
                 fasta_path.open("r") as fasta_handle:
                audit = audit_streams(
                    membership, csv_handle, fasta_handle,
                    width=config.window, output_count=config.output_count,
                    sample_size=513, seed=config.seeds[0],
                    expected_partition_rows=EXPECTED_PARTITIONS,
                    expected_component_count=EXPECTED_COMPONENTS,
                )
            if audit.counts.combined_bounds() != EXPECTED_BOUNDS:
                raise ResCNN004A2RunnerError("Gate A development-only aggregate bounds drift")
            _write_selected_rows(generation.candidate / "selected_rows.tsv", audit)

            stage = "gate_b_cache"
            before_b = local_resource_snapshot(generation.candidate)
            require_local_resources(before_b)
            with _open_membership(Path(args.membership)) as membership, \
                 Path(args.csv).open("r", newline="") as csv_handle, \
                 fasta_path.open("r") as fasta_handle:
                cache_result = build_cache_streams(
                    membership, csv_handle, fasta_handle, selected=audit.selected,
                    width=config.window, output_count=config.output_count,
                )
            require_count_reconciliation(
                audit.counts, cache_result.counts, expected_bounds=EXPECTED_BOUNDS,
            )
            stage = "paired_smoke_primary"
            primary = run_paired_smoke(
                cache_result.cache, config=config,
                output_dir=generation.candidate / "primary",
                source_sha256=source_digest, config_sha256=CONFIG_SHA256,
                environment_sha256=environment_digest, model_factory=factory,
            )
            stage = "paired_smoke_repeat"
            repeat = run_paired_smoke(
                cache_result.cache, config=config,
                output_dir=generation.candidate / "repeat",
                source_sha256=source_digest, config_sha256=CONFIG_SHA256,
                environment_sha256=environment_digest, model_factory=factory,
            )
            if scientific_signature(primary) != scientific_signature(repeat):
                raise ResCNN004A2RunnerError("primary/repeat scientific evidence differs")
            stage = "prediction_and_commit"
            prediction_count = _write_predictions(
                generation.candidate / "coverage_smoke_predictions.tsv",
                cache_result, primary, CONFIG_SHA256,
            )
            final_resources = local_resource_snapshot(generation.candidate)
            require_local_resources(final_resources)
            elapsed = time.monotonic() - start
            if elapsed > TIMEOUT_SECONDS:
                raise ResCNN004A2RunnerError("Task 004A-2 exceeded its timeout")

            full_summary = {
                "schema_version": "task004a2_local_smoke_generation_v1",
                "provenance": provenance,
                "audit": {
                    "row_count": audit.row_count,
                    "component_count": audit.component_count,
                    "partition_rows": dict(audit.partition_rows),
                    "development_counts": audit.counts.matrix(),
                    "development_bounds": audit.counts.combined_bounds(),
                    "selected_content_sha256": audit.selected_content_sha256,
                    "gate_a_access": dict(audit.access),
                    "gate_b_access": dict(cache_result.access),
                },
                "cache": {
                    "rows": len(cache_result.cache),
                    "base_shape": list(cache_result.cache.base_codes.shape),
                    "target_shape": list(cache_result.cache.targets.shape),
                    "base_dtype": str(cache_result.cache.base_codes.dtype),
                    "target_dtype": str(cache_result.cache.targets.dtype),
                    "mask_dtype": str(cache_result.cache.masks.dtype),
                    "retained_tensor_bytes": cache_result.cache.retained_bytes(),
                },
                "smoke": scientific_signature(primary),
                "coverage_smoke_prediction_rows": prediction_count,
                "runtime": {
                    "wall_seconds": elapsed,
                    "peak_rss_bytes": final_resources.peak_rss_bytes,
                    "free_disk_before_gate_a": before_a.free_disk_bytes,
                    "free_disk_before_gate_b": before_b.free_disk_bytes,
                    "free_disk_after": final_resources.free_disk_bytes,
                },
                "test_accessed": False,
                "test_access_evidence_type": "structural branch-before-interpretation guarantee",
            }
            atomic_write(generation.candidate / "summary.json", canonical_json(full_summary))
            inventory = generation_inventory(generation.candidate)
            generation_bytes = sum(int(row["byte_size"]) for row in inventory)
            if generation_bytes > MAX_GENERATION_BYTES:
                raise ResCNN004A2RunnerError("accepted generation exceeds 1 GiB")
            sanitized = {
                "input_evidence": fixed,
                "source_commit": provenance["source_commit"],
                "source_sha256": source_digest,
                "environment_sha256": environment_digest,
                "audit_access": {
                    "gate_a": dict(audit.access), "gate_b": dict(cache_result.access),
                },
                "partition_rows": dict(audit.partition_rows),
                "component_count": audit.component_count,
                "development_bounds": audit.counts.combined_bounds(),
                "sample_counts": {"train": 513, "validation": 513},
                "selected_content_sha256": audit.selected_content_sha256,
                "cache_retained_tensor_bytes": cache_result.cache.retained_bytes(),
                "smoke": scientific_signature(primary),
                "prediction_rows": prediction_count,
                "generation_bytes": generation_bytes,
                "wall_seconds": elapsed,
                "peak_rss_bytes": final_resources.peak_rss_bytes,
                "numerical_threads": 4,
                "test_accessed": False,
                "test_access_evidence_type": "structural branch-before-interpretation guarantee",
            }
            return generation.commit(fingerprint=fingerprint, payload=sanitized)
    except Exception as exc:
        _write_stop_record(
            output_dir,
            stage=stage,
            error=exc,
            input_evidence=fixed,
            gate_a_access=None if audit is None else audit.access,
            gate_b_access=None if cache_result is None else cache_result.access,
        )
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--dataset-audit", required=True)
    parser.add_argument("--proteins", required=True)
    parser.add_argument("--decode-manifest", required=True)
    parser.add_argument("--partition-manifest", required=True)
    parser.add_argument("--phase-a-manifest", required=True)
    parser.add_argument("--membership", required=True)
    parser.add_argument("--environment-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = execute(args)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
