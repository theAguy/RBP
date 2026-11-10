#!/usr/bin/env python3
"""Build the reviewed Task 004A-3 bundle; execution remains separately gated."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from rbpbench.rescnn.cache_004a3 import PRODUCTION_PARTITION_SIZE, open_cache
from rbpbench.rescnn.environment_004a3 import sha256_file
from rbpbench.rescnn.portable_004a3 import build_inventory, verify_bundle
from rbpbench.rescnn.projection_004a3 import PROJECT_004A4_SLURM_LIMIT_SECONDS
from rbpbench.rescnn.runtime_004a3 import require_discovery_install_policy
from rbpbench.rescnn.runtime_004a3 import require_discovery_payload
from rbpbench.discovery_004a3 import (
    require_partition_preempt_mode, require_partition_time_evidence,
)


SOURCE_FILES = (
    "src/rbpbench/__init__.py",
    "src/rbpbench/discovery_004a3.py",
    "src/rbpbench/baselines/__init__.py",
    "src/rbpbench/baselines/data.py",
    "src/rbpbench/baselines/metrics.py",
    "src/rbpbench/rescnn/__init__.py",
    "src/rbpbench/rescnn/adam_004a3.py",
    "src/rbpbench/rescnn/cache_004a3.py",
    "src/rbpbench/rescnn/checkpoint.py",
    "src/rbpbench/rescnn/config.py",
    "src/rbpbench/rescnn/data.py",
    "src/rbpbench/rescnn/data_004a2.py",
    "src/rbpbench/rescnn/environment_004a2.py",
    "src/rbpbench/rescnn/environment_004a3.py",
    "src/rbpbench/rescnn/factories_004a2.py",
    "src/rbpbench/rescnn/fidelity.py",
    "src/rbpbench/rescnn/loss.py",
    "src/rbpbench/rescnn/metrics.py",
    "src/rbpbench/rescnn/model.py",
    "src/rbpbench/rescnn/output.py",
    "src/rbpbench/rescnn/portable_004a3.py",
    "src/rbpbench/rescnn/projection_004a3.py",
    "src/rbpbench/rescnn/reproducibility.py",
    "src/rbpbench/rescnn/resources_004a2.py",
    "src/rbpbench/rescnn/runner_004a2.py",
    "src/rbpbench/rescnn/runner_004a3.py",
    "src/rbpbench/rescnn/runtime_004a3.py",
    "src/rbpbench/rescnn/smoke_004a2.py",
    "src/rbpbench/rescnn/timing_004a3.py",
)
TEST_FILES = (
    "tests/test_rescnn_004a_contract.py", "tests/test_rescnn_004a_fidelity.py",
    "tests/test_rescnn_004a2_data.py", "tests/test_rescnn_004a2_runtime.py",
    "tests/test_rescnn_004a3.py",
)
OTHER_FILES = (
    "configs/models/task004a_v1.toml", "pyproject.toml",
    "intRBP ResCNN - for students.ipynb",
    "manifests/task003b_phase_a_003b3.json",
    "manifests/task004a2b_local_smoke.json",
    "scripts/run_004a2b_local_smoke_recovery.sh",
    "scripts/build_004a3_portable_bundle.py",
    "scripts/build_004a3_runtime_manifest.py",
    "scripts/build_004a3_development_cache.py",
    "hpc/newton/004a3/00_SUBMIT_DISCOVERY.sh",
    "hpc/newton/004a3/01_DISCOVERY.sbatch",
    "hpc/newton/004a3/02_INSTALL_EXACT_ENVIRONMENT.sh",
    "hpc/newton/004a3/02_SUBMIT_ENVIRONMENT.sh",
    "hpc/newton/004a3/02_PREPARE_ENVIRONMENT.sbatch",
    "hpc/newton/004a3/03_SUBMIT_SMOKE.sh",
    "hpc/newton/004a3/04_CHECK_STATUS.sh",
    "hpc/newton/004a3/05_VERIFY_RETURN.sh",
    "hpc/newton/004a3/RUN_004A3_SMOKE.sbatch",
    "hpc/newton/004a3/README.md",
)

TASK004A2_SUMMARY_SHA256 = "27e78cd924eddce6799ad388d46235687cb2ce916648bc15c2b6a28569f6d805"


def _reviewed_scheduler_policy(discovery: dict) -> dict[str, object]:
    time_evidence = require_partition_time_evidence(discovery)
    if (
        time_evidence["kind"] == "finite"
        and PROJECT_004A4_SLURM_LIMIT_SECONDS > int(time_evidence["seconds"])
    ):
        raise RuntimeError("project Slurm limit exceeds the finite partition limit")
    preempt_mode = require_partition_preempt_mode(discovery)
    return {
        "partition_slurm_limit_kind": time_evidence["kind"],
        "partition_slurm_limit_seconds": time_evidence["seconds"],
        "partition_slurm_limit_raw_value": time_evidence["raw_value"],
        "slurm_limit_seconds": PROJECT_004A4_SLURM_LIMIT_SECONDS,
        "slurm_limit_source": "project_owned_reviewed_ceiling",
        "partition_preempt_mode": preempt_mode,
        "smoke_requeue_policy": "disabled_fail_closed",
        "full_run_preemption_requirement": "restart_safe_before_004a4",
    }


def _copy(repo: Path, destination: Path, relative: str) -> None:
    source = repo / relative
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(f"required tracked file missing or symlinked: {relative}")
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _source_digest(repo: Path) -> str:
    """Bind the exact reviewed Python source subset copied into the bundle."""
    digest = hashlib.sha256()
    for relative in SOURCE_FILES:
        path = repo / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"required source file missing or symlinked: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _full_validation_known_counts(
    *, repo: Path, summary: Path, subset_counts: list[int],
) -> list[int]:
    accepted = json.loads((repo / "manifests/task004a2b_local_smoke.json").read_text())
    recorded = accepted.get("accepted_output", {}).get("summary", {}).get("sha256")
    if recorded != TASK004A2_SUMMARY_SHA256:
        raise RuntimeError("tracked 004A-2 manifest does not bind the accepted summary")
    if sha256_file(summary) != TASK004A2_SUMMARY_SHA256:
        raise RuntimeError("004A-2 accepted summary hash mismatch")
    payload = json.loads(summary.read_text())
    return _extract_full_validation_known_counts(
        payload=payload, subset_counts=subset_counts,
    )


def _extract_full_validation_known_counts(
    *, payload: dict, subset_counts: list[int],
) -> list[int]:
    validation = (
        payload.get("audit", {}).get("development_counts", {}).get("validation")
    )
    if not isinstance(validation, dict):
        raise RuntimeError("004A-2 summary lacks the Gate-A validation matrix")
    positive, negative = validation.get("positive"), validation.get("negative")
    if not isinstance(positive, list) or not isinstance(negative, list):
        raise RuntimeError("004A-2 validation positive/negative counts are missing")
    if len(positive) != 122 or len(negative) != 122 or len(subset_counts) != 122:
        raise RuntimeError("004A-2 validation count vectors must have length 122")
    if any(not isinstance(value, int) or value < 0 for value in (*positive, *negative)):
        raise RuntimeError("004A-2 validation counts must be non-negative integers")
    full = [positive[index] + negative[index] for index in range(122)]
    if any(full[index] <= int(subset_counts[index]) for index in range(122)):
        raise RuntimeError("full validation counts are not strictly larger than subset counts")
    return full


def _validate_gpu_policy(
    required_gpu_name: str, gpu_gres: str, gpu_constraint: str, gpu_nodelist: str,
) -> None:
    for label, value in (
        ("required GPU name", required_gpu_name), ("GPU GRES", gpu_gres),
    ):
        if not value or any(character in value for character in ("\n", "\r", "|")):
            raise RuntimeError(f"{label} is empty or malformed")
    if required_gpu_name != "RECORD_ONLY" and required_gpu_name.strip() != required_gpu_name:
        raise RuntimeError("required GPU name contains surrounding whitespace")
    if not gpu_gres.startswith("gpu:"):
        raise RuntimeError("reviewed GPU GRES must start with 'gpu:'")
    if any(character in gpu_constraint for character in ("\n", "\r", "|")):
        raise RuntimeError("GPU constraint is malformed")
    if not gpu_nodelist or any(character in gpu_nodelist for character in ("\n", "\r", "|", ",")):
        raise RuntimeError("GPU node binding is empty or malformed")
    if required_gpu_name == "NVIDIA L40S" and gpu_gres == "gpu:L40:1" and gpu_nodelist != "nlp-l40-2":
        raise RuntimeError("accepted L40S policy must bind the observed nlp-l40-2 node")


def build_bundle(
    *, repo: Path, destination: Path, cache: Path, discovery: Path,
    environment_lock: Path, runtime_manifest: Path, task004a2_summary: Path,
    expected_lock_sha256: str, expected_runtime_sha256: str,
    required_gpu_name: str, gpu_gres: str, gpu_constraint: str, gpu_nodelist: str,
) -> Path:
    repo = repo.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise RuntimeError("bundle destination already exists")
    parsed_discovery = require_discovery_payload(json.loads(discovery.read_text()))
    install_location = require_discovery_install_policy(parsed_discovery)
    scheduler_policy = _reviewed_scheduler_policy(parsed_discovery)
    _validate_gpu_policy(required_gpu_name, gpu_gres, gpu_constraint, gpu_nodelist)
    if sha256_file(environment_lock) != expected_lock_sha256:
        raise RuntimeError("environment lock hash mismatch")
    if sha256_file(runtime_manifest) != expected_runtime_sha256:
        raise RuntimeError("runtime manifest hash mismatch")
    runtime_payload = json.loads(runtime_manifest.read_text())
    environment_bytes = sum(
        int(entry.get("byte_size", 0))
        for entry in runtime_payload.get("entries", [])
        if entry.get("type") == "file"
    )
    accepted_cache = open_cache(cache)
    if any(len(accepted_cache.indices(p)) != PRODUCTION_PARTITION_SIZE for p in ("train", "validation")):
        raise RuntimeError("cache does not contain the frozen 8,193/8,193 rows")
    subset_validation_counts = [int(value) for value in accepted_cache.metadata["validation_known_counts"]]
    full_validation_counts = _full_validation_known_counts(
        repo=repo, summary=task004a2_summary, subset_counts=subset_validation_counts,
    )
    if (
        len(full_validation_counts) != 122
        or any(
            not isinstance(value, int) or value <= subset_validation_counts[index]
            for index, value in enumerate(full_validation_counts)
        )
    ):
        raise RuntimeError("bundle full-validation counts are missing or subset-derived")
    try:
        source_sha256 = _source_digest(repo)
        destination.mkdir(parents=True)
        for relative in (*SOURCE_FILES, *TEST_FILES, *OTHER_FILES):
            _copy(repo, destination, relative)
        shutil.copytree(cache, destination / "data/cache", symlinks=False)
        manifest_dir = destination / "manifests"
        manifest_dir.mkdir(exist_ok=True)
        shutil.copy2(discovery, manifest_dir / "DISCOVERY.json")
        shutil.copy2(environment_lock, manifest_dir / "environment.lock")
        shutil.copy2(runtime_manifest, manifest_dir / "runtime_manifest.json")
        config = {
            "schema_version": "task004a3_bundle_v2",
            "environment_lock_sha256": expected_lock_sha256,
            "runtime_manifest_sha256": expected_runtime_sha256,
            "source_sha256": source_sha256,
            "task004a2_summary_sha256": TASK004A2_SUMMARY_SHA256,
            "site_approved_install_location": install_location,
            "quota_available_bytes": int(parsed_discovery["quota_available_bytes"]),
            **scheduler_policy,
            "required_gpu_name": required_gpu_name,
            "gpu_gres": gpu_gres,
            "gpu_constraint": gpu_constraint,
            "gpu_nodelist": gpu_nodelist,
            "environment_bytes": environment_bytes,
            "train_rows": PRODUCTION_PARTITION_SIZE,
            "validation_rows": PRODUCTION_PARTITION_SIZE,
            "validation_known_counts": full_validation_counts,
            "subset_validation_known_counts": subset_validation_counts,
            "test_rows": 0,
        }
        (destination / "BUNDLE_CONFIG.json").write_text(json.dumps(config, indent=2, sort_keys=True)+"\n")
        inventory = build_inventory(destination)
        (destination / "BUNDLE_INVENTORY.json").write_text(json.dumps(inventory, indent=2, sort_keys=True)+"\n")
        # Inventory excludes itself to avoid a recursive digest.
        verify_bundle(destination)
        return destination
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def archive_bundle(bundle: Path) -> dict[str, object]:
    bundle = bundle.resolve()
    archive = bundle.with_suffix(".tar.gz")
    checksum = Path(str(archive) + ".sha256")
    if archive.exists() or checksum.exists():
        raise RuntimeError("archive destination exists")
    with tarfile.open(archive, "x:gz") as handle:
        handle.add(bundle, arcname=bundle.name, recursive=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n")
    with tarfile.open(archive, "r:gz") as handle:
        names = {member.name for member in handle.getmembers() if member.isfile()}
    expected = {f"{bundle.name}/{p.relative_to(bundle).as_posix()}" for p in bundle.rglob("*") if p.is_file()}
    if names != expected:
        archive.unlink(missing_ok=True); checksum.unlink(missing_ok=True)
        raise RuntimeError("archive member verification failed")
    return {"path": str(archive), "sha256": digest, "byte_size": archive.stat().st_size}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--environment-lock", type=Path, required=True)
    parser.add_argument("--runtime-manifest", type=Path, required=True)
    parser.add_argument("--task004a2-summary", type=Path, required=True)
    parser.add_argument("--environment-lock-sha256", required=True)
    parser.add_argument("--runtime-manifest-sha256", required=True)
    parser.add_argument("--required-gpu-name", required=True)
    parser.add_argument("--gpu-gres", required=True)
    parser.add_argument("--gpu-constraint", default="")
    parser.add_argument("--gpu-nodelist", required=True)
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args(argv)
    bundle = build_bundle(
        repo=args.repo, destination=args.destination, cache=args.cache,
        discovery=args.discovery, environment_lock=args.environment_lock,
        runtime_manifest=args.runtime_manifest,
        task004a2_summary=args.task004a2_summary,
        expected_lock_sha256=args.environment_lock_sha256,
        expected_runtime_sha256=args.runtime_manifest_sha256,
        required_gpu_name=args.required_gpu_name, gpu_gres=args.gpu_gres,
        gpu_constraint=args.gpu_constraint, gpu_nodelist=args.gpu_nodelist,
    )
    if args.archive:
        print(json.dumps(archive_bundle(bundle), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
