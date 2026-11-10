#!/usr/bin/env python3
"""Build the accepted test-blind 8,193/8,193 Task 004A-3 cache locally."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

from rbpbench.rescnn.cache_004a3 import (
    build_production_development_cache, require_accepted_count_matrix,
)
from rbpbench.rescnn.environment_004a2 import (
    canonical_manifest_bytes, discover_environment_manifest, environment_sha256,
)
from rbpbench.rescnn.resources_004a2 import local_resource_snapshot, require_local_resources


SUMMARY_SHA256 = "27e78cd924eddce6799ad388d46235687cb2ce916648bc15c2b6a28569f6d805"
ENVIRONMENT_SHA256 = "c4398ac454240b367eb7b8736915b67a038984724427eacffd9d98b19f3ae847"
SEED = 20261029
EXPECTED_PARTITIONS = {"train": 246017, "validation": 57565, "test": 57598}
EXPECTED_COMPONENTS = 169699
TIMEOUT_SECONDS = 2 * 60 * 60


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_clean(repo: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo,
        text=True, capture_output=True, check=True, timeout=10,
    )
    if result.stdout.strip():
        raise RuntimeError("worktree must be clean before real cache construction")


def _verify_file(path: Path, expected: str, label: str) -> None:
    if path.is_symlink() or not path.is_file() or sha256_file(path) != expected:
        raise RuntimeError(f"{label} is missing, symlinked, or hash-drifted")


def _verify_environment(path: Path) -> None:
    recorded = json.loads(path.read_text())
    if environment_sha256(recorded) != ENVIRONMENT_SHA256:
        raise RuntimeError("accepted local environment manifest digest drift")
    if canonical_manifest_bytes(recorded) != canonical_manifest_bytes(discover_environment_manifest()):
        raise RuntimeError("live environment differs from accepted Task 004A-2 environment")


def _verify_sources(repo: Path, summary: dict) -> str:
    files = summary.get("source_files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("accepted summary lacks source binding")
    digest_builder = hashlib.sha256()
    for row in sorted(files, key=lambda item: str(item.get("path", ""))):
        relative, digest = row.get("path"), row.get("sha256")
        if not isinstance(relative, str) or not isinstance(digest, str):
            raise RuntimeError("accepted source binding is malformed")
        _verify_file(repo / "src" / relative, digest, f"accepted source {relative}")
        encoded = relative.encode("utf-8")
        digest_builder.update(len(encoded).to_bytes(8, "big"))
        digest_builder.update(encoded)
        digest_builder.update(bytes.fromhex(digest))
    return digest_builder.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--membership", type=Path, required=True)
    parser.add_argument("--fasta", type=Path, required=True)
    parser.add_argument("--accepted-summary", type=Path, required=True)
    parser.add_argument("--accepted-manifest", type=Path, required=True)
    parser.add_argument("--environment-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    repo, output = args.repo.resolve(), args.output.resolve()
    summary_output = output.with_name(output.name + ".summary.json")
    if output.exists() or summary_output.exists():
        raise RuntimeError("cache output or summary already exists")
    _require_clean(repo)
    _verify_environment(args.environment_manifest)
    accepted = json.loads(args.accepted_manifest.read_text())
    if accepted.get("binding", {}).get("environment_sha256") != ENVIRONMENT_SHA256:
        raise RuntimeError("tracked 004A-2 manifest environment binding drift")
    _verify_file(args.accepted_summary, SUMMARY_SHA256, "accepted Task 004A-2 summary")
    summary = json.loads(args.accepted_summary.read_text())
    source_digest = _verify_sources(repo, summary)
    if source_digest != accepted.get("binding", {}).get("source_sha256"):
        raise RuntimeError("accepted Task 004A-2 source digest drift")
    hashes = accepted.get("input_sha256", {})
    _verify_file(args.csv, hashes.get("csv"), "CSV")
    _verify_file(args.membership, hashes.get("membership"), "membership")
    _verify_file(args.fasta, hashes.get("fasta_500"), "500-nt FASTA")
    before = local_resource_snapshot(output.parent)
    require_local_resources(before)
    candidate = output.parent / f".{output.name}.candidate-{uuid.uuid4().hex}"
    summary_candidate = output.parent / f".{output.name}.summary-{uuid.uuid4().hex}.json"

    def membership_factory():
        return gzip.open(args.membership, "rt", newline="")
    def csv_factory():
        return args.csv.open("rt", newline="")
    def fasta_factory():
        return args.fasta.open("rt")
    def timeout_handler(_signum, _frame):
        raise TimeoutError("cache build exceeded two hours")

    prior = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(TIMEOUT_SECONDS)
    started = time.monotonic()
    try:
        evidence = build_production_development_cache(
            candidate, membership_factory=membership_factory,
            csv_factory=csv_factory, fasta_factory=fasta_factory, seed=SEED,
            expected_partition_rows=EXPECTED_PARTITIONS,
            expected_component_count=EXPECTED_COMPONENTS,
        )
        require_accepted_count_matrix(evidence.development_count_matrix, summary)
        after = local_resource_snapshot(output.parent)
        require_local_resources(after)
        cache_summary = {
            "schema_version": "task004a3_development_cache_v1",
            "status": "COMPLETED", "seed": SEED,
            "wall_seconds": time.monotonic() - started,
            "development_count_matrix": evidence.development_count_matrix,
            "selected_content_sha256": evidence.selected_content_sha256,
            "gate_a_access": evidence.gate_a_access,
            "gate_b_access": evidence.gate_b_access,
            "cache_metadata": evidence.cache_metadata,
            "accepted_summary_sha256": SUMMARY_SHA256,
            "environment_sha256": ENVIRONMENT_SHA256,
        }
        summary_candidate.write_text(
            json.dumps(cache_summary, indent=2, sort_keys=True) + "\n"
        )
        candidate.rename(output)
        summary_candidate.rename(summary_output)
    except Exception:
        shutil.rmtree(candidate, ignore_errors=True)
        summary_candidate.unlink(missing_ok=True)
        if output.exists() and not summary_output.exists():
            shutil.rmtree(output, ignore_errors=True)
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prior)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
