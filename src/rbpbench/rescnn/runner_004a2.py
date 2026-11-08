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
import time
from typing import Callable, Iterator, Mapping

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
from rbpbench.rescnn.model import CNNMultiLabelResidual
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


def _hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(path for path in Path(root).rglob("*.py") if "__pycache__" not in path.parts)
    if not paths:
        raise ResCNN004A2RunnerError("ResCNN source tree is empty")
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


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
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repo_root, check=True, text=True, capture_output=True, timeout=10,
    )
    if completed.stdout.strip():
        raise ResCNN004A2RunnerError("tracked worktree must be clean before real execution")


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


def _input_evidence(path: Path, expected_sha256: str, label: str) -> dict[str, object]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ResCNN004A2RunnerError(f"{label} is missing or a symlink")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ResCNN004A2RunnerError(f"{label} SHA-256 drift")
    return {"path": str(path), "byte_size": path.stat().st_size, "sha256": actual}


def _fingerprint(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _verify_phase_a_bounds(path: Path) -> dict[str, object]:
    evidence = _input_evidence(path, PHASE_A_MANIFEST_SHA256, "Task 003B Phase A manifest")
    payload = json.loads(Path(path).read_text())
    fitting = payload.get("fitting")
    if not isinstance(fitting, dict):
        raise ResCNN004A2RunnerError("Task 003B Phase A fitting evidence is missing")
    observed = {key: fitting.get(key) for key in EXPECTED_BOUNDS}
    if observed != EXPECTED_BOUNDS:
        raise ResCNN004A2RunnerError("Task 003B Phase A development bounds drift")
    return evidence


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


def execute(args, *, model_factory: Callable[[], torch.nn.Module] | None = None) -> Path:
    start = time.monotonic()
    repo_root = Path(args.repo_root).resolve()
    _require_clean_worktree(repo_root)
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
        "config": _input_evidence(config_path, CONFIG_SHA256, "config"),
        "csv": _input_evidence(Path(args.csv), config.inputs["csv_sha256"], "CSV"),
        "dataset_audit": _input_evidence(
            Path(args.dataset_audit), config.inputs["dataset_audit_sha256"], "dataset audit",
        ),
        "proteins": _input_evidence(
            Path(args.proteins), config.inputs["proteins_sha256"], "proteins config",
        ),
        "decode_manifest": _input_evidence(
            Path(args.decode_manifest), config.inputs["decode_manifest_sha256"], "decode manifest",
        ),
        "partition_manifest": _input_evidence(
            Path(args.partition_manifest), config.inputs["partition_manifest_sha256"],
            "partition manifest",
        ),
        "membership": _input_evidence(
            Path(args.membership), config.inputs["membership_sha256"], "membership",
        ),
        "phase_a_manifest": _verify_phase_a_bounds(Path(args.phase_a_manifest)),
    }
    fasta_path = resolve_fasta_500(
        repo_root, Path(args.decode_manifest), config.inputs["fasta_500_sha256"],
    )
    fixed["fasta_500"] = _input_evidence(
        fasta_path, config.inputs["fasta_500_sha256"], "500-nt FASTA",
    )
    source_root = repo_root / "src/rbpbench/rescnn"
    source_digest = _hash_tree(source_root)
    provenance = {
        "inputs": fixed,
        "source_commit": _source_commit(repo_root),
        "source_sha256": source_digest,
        "environment_sha256": environment_digest,
        "threads": thread_evidence,
        "strict_float32": strict_evidence,
    }
    fingerprint = _fingerprint(provenance)
    prior = verify_selected(Path(args.output_dir), STAGE, fingerprint=fingerprint)
    if prior is not None:
        return Path(args.output_dir) / prior["generation"]

    factory = model_factory or (lambda: CNNMultiLabelResidual(config.output_count))
    with _deadline(TIMEOUT_SECONDS), WholeRunGeneration(Path(args.output_dir), STAGE) as generation:
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
        primary = run_paired_smoke(
            cache_result.cache, config=config,
            output_dir=generation.candidate / "primary",
            source_sha256=source_digest, config_sha256=CONFIG_SHA256,
            environment_sha256=environment_digest, model_factory=factory,
        )
        repeat = run_paired_smoke(
            cache_result.cache, config=config,
            output_dir=generation.candidate / "repeat",
            source_sha256=source_digest, config_sha256=CONFIG_SHA256,
            environment_sha256=environment_digest, model_factory=factory,
        )
        if scientific_signature(primary) != scientific_signature(repeat):
            raise ResCNN004A2RunnerError("primary/repeat scientific evidence differs")
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
            "audit_access": {"gate_a": dict(audit.access), "gate_b": dict(cache_result.access)},
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
        }
        return generation.commit(fingerprint=fingerprint, payload=sanitized)


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
