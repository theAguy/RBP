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
from rbpbench.rescnn.runtime_004a3 import require_discovery_install_policy


SOURCE_FILES = (
    "src/rbpbench/__init__.py",
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
    "hpc/newton/004a3/01_DISCOVERY.sbatch",
    "hpc/newton/004a3/02_INSTALL_EXACT_ENVIRONMENT.sh",
    "hpc/newton/004a3/03_SUBMIT_SMOKE.sh",
    "hpc/newton/004a3/04_CHECK_STATUS.sh",
    "hpc/newton/004a3/05_VERIFY_RETURN.sh",
    "hpc/newton/004a3/RUN_004A3_SMOKE.sbatch",
    "hpc/newton/004a3/README.md",
)


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


def build_bundle(
    *, repo: Path, destination: Path, cache: Path, discovery: Path,
    environment_lock: Path, runtime_manifest: Path,
    expected_lock_sha256: str, expected_runtime_sha256: str,
) -> Path:
    repo = repo.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise RuntimeError("bundle destination already exists")
    parsed_discovery = json.loads(discovery.read_text())
    install_location = require_discovery_install_policy(parsed_discovery)
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
    try:
        source_sha256 = _source_digest(repo)
        destination.mkdir(parents=True)
        for relative in (*SOURCE_FILES, *TEST_FILES, *OTHER_FILES):
            _copy(repo, destination, relative)
        shutil.copytree(cache, destination / "data/cache", symlinks=False)
        manifest_dir = destination / "manifests"
        manifest_dir.mkdir()
        shutil.copy2(discovery, manifest_dir / "DISCOVERY.json")
        shutil.copy2(environment_lock, manifest_dir / "environment.lock")
        shutil.copy2(runtime_manifest, manifest_dir / "runtime_manifest.json")
        config = {
            "schema_version": "task004a3_bundle_v1",
            "environment_lock_sha256": expected_lock_sha256,
            "runtime_manifest_sha256": expected_runtime_sha256,
            "source_sha256": source_sha256,
            "site_approved_install_location": install_location,
            "quota_available_bytes": int(parsed_discovery["quota_available_bytes"]),
            "environment_bytes": environment_bytes,
            "train_rows": PRODUCTION_PARTITION_SIZE,
            "validation_rows": PRODUCTION_PARTITION_SIZE,
            "validation_known_counts": accepted_cache.metadata["validation_known_counts"],
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
    parser.add_argument("--environment-lock-sha256", required=True)
    parser.add_argument("--runtime-manifest-sha256", required=True)
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args(argv)
    bundle = build_bundle(
        repo=args.repo, destination=args.destination, cache=args.cache,
        discovery=args.discovery, environment_lock=args.environment_lock,
        runtime_manifest=args.runtime_manifest,
        expected_lock_sha256=args.environment_lock_sha256,
        expected_runtime_sha256=args.runtime_manifest_sha256,
    )
    if args.archive:
        print(json.dumps(archive_bundle(bundle), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
