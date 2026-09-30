#!/usr/bin/env python3
"""Build the immutable, offline Task 002C-3/4 Apple-Silicon handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "configs/proteins.tsv",
    "configs/splits/sequence_partitions_002c_v1.toml",
    "manifests/dataset_audit.json",
    "manifests/sequence_assignment_002c2b.json",
    "manifests/sequence_decode_002b2.json",
    "manifests/sequence_legacy_cluster_evidence_002c2a.json",
    "manifests/sequence_non_mmseqs_audits_002c2c.json",
    "manifests/sequence_partition_environment_002c3_arm64.explicit.txt",
    "docs/PROJECT_ROADMAP.md",
    "docs/tasks/002c_partition_assignment_and_audit.md",
    "docs/tasks/002c3_portable_cross_partition_audit.md",
    "docs/reviews/002b_real_sequence_grouping_acceptance.md",
    "docs/reviews/002c2b_real_assignment_acceptance.md",
    "docs/reviews/002c2c_non_mmseqs_diagnostics_acceptance.md",
)

DECODE_REL = Path("artifacts/splits/sequence_partitions_v1/decode/generations/decode_907eac7a0a69415a")
OUTPUT_REL = Path("artifacts/splits/sequence_partitions_002c_v1")
EVIDENCE_REL = Path("artifacts/teammate_run_results/20260928T091014Z_87391_arm64")
EVIDENCE_FILES = (
    "RETURN_MANIFEST.json",
    "RETURN_INVENTORY.json",
    "memberships/cluster_500.membership.tsv",
    "memberships/cluster_251.membership.tsv",
    "memberships/cluster_101.membership.tsv",
    "selected_records/cluster_500.json",
    "selected_records/cluster_251.json",
    "selected_records/cluster_101.json",
    "final_component_result/component_membership.tsv.gz",
    "final_component_result/component_report.json",
)
ACCEPTED_OUTPUT_SUBTREES = ("assign", "legacy_diagnostic", "exact_audit")
ACCEPTED_SELECTED = (
    "assign.json",
    "legacy_diagnostic.json",
    "exact_audit_500.json",
    "exact_audit_251.json",
    "exact_audit_101.json",
)
RUNTIME_REL = Path(".runtime/rbpbench-splits-002c-arm64")
EXPECTED_ARM64_MMSEQS_SHA256 = "3fa397a9af5f8142ab8df13cc3e19b3aefc91cb9908d9c147883c8ac4162db0d"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def ignore_generated(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {"__pycache__", ".DS_Store"} or name.endswith((".pyc", ".pyo"))}


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True, ignore=ignore_generated)


def git_value(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def assert_clean_source(repo: Path) -> str:
    status = git_value(repo, "status", "--porcelain")
    if status:
        raise RuntimeError("source worktree must be clean before the handoff is built")
    return git_value(repo, "rev-parse", "HEAD")


def assert_fresh_accepted_output(repo: Path) -> None:
    selected = repo / OUTPUT_REL / "selected"
    actual = {path.name for path in selected.glob("*.json")}
    expected = set(ACCEPTED_SELECTED)
    if actual != expected:
        raise RuntimeError(
            f"Task 002C output is not at the accepted pre-002C-3 boundary; selected={sorted(actual)}, "
            f"expected={sorted(expected)}"
        )
    forbidden = [repo / OUTPUT_REL / name for name in ("audit_probe", "audit_search", "finalize")]
    existing = [str(path) for path in forbidden if path.exists()]
    if existing:
        raise RuntimeError(f"refusing to bundle pre-existing Task 002C-3/4 outputs: {existing}")


def inventory_tree(root: Path, *, excluded: frozenset[str]) -> list[dict]:
    entries: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in {"__pycache__", ".DS_Store"})
        for name in sorted(filenames):
            path = Path(dirpath) / name
            relative = str(path.relative_to(root))
            if relative in excluded or name in {".DS_Store"} or name.endswith((".pyc", ".pyo")):
                continue
            if path.is_symlink():
                entries.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
            elif path.is_file():
                entries.append({
                    "path": relative,
                    "type": "file",
                    "byte_size": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
            else:
                raise RuntimeError(f"unsupported filesystem object in bundle: {path}")
    return entries


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_launcher(destination: Path) -> None:
    text = """#!/bin/zsh
set -eu
BUNDLE_ROOT=${0:A:h}
cd "$BUNDLE_ROOT"

# Cloud downloads may attach a quarantine xattr to every bundled executable.
# Remove only that metadata and only inside this handoff's private runtime.
if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$BUNDLE_ROOT/.runtime" 2>/dev/null || true
fi

PYTHON_BIN="$BUNDLE_ROOT/.runtime/rbpbench-splits-002c-arm64/bin/python"
export PYTHONPATH="$BUNDLE_ROOT/src"
export PYTHONNOUSERSITE=1
export PATH="$BUNDLE_ROOT/.runtime/rbpbench-splits-002c-arm64/bin:$PATH"

if [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 "Bundled Python is missing or not executable: $PYTHON_BIN"
  exit 1
fi

if command -v caffeinate >/dev/null 2>&1; then
  exec caffeinate -ims "$PYTHON_BIN" -m rbpbench.splits.portable_002c3 --bundle-root "$BUNDLE_ROOT"
fi
exec "$PYTHON_BIN" -m rbpbench.splits.portable_002c3 --bundle-root "$BUNDLE_ROOT"
"""
    destination.write_text(text)
    destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_bundle(repo: Path, destination: Path, environment_prefix: Path) -> tuple[Path, dict]:
    repo = repo.resolve()
    destination = destination.resolve()
    environment_prefix = environment_prefix.resolve()
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    commit = assert_clean_source(repo)
    assert_fresh_accepted_output(repo)

    mmseqs = environment_prefix / "bin/mmseqs"
    python = environment_prefix / "bin/python"
    if not mmseqs.is_file() or not python.is_file():
        raise RuntimeError(f"environment prefix lacks bin/python or bin/mmseqs: {environment_prefix}")
    mmseqs_hash = sha256_file(mmseqs)
    if mmseqs_hash != EXPECTED_ARM64_MMSEQS_SHA256:
        raise RuntimeError(f"arm64 MMseqs2 hash {mmseqs_hash} != expected {EXPECTED_ARM64_MMSEQS_SHA256}")

    destination.mkdir(parents=True)
    for relative in PROJECT_FILES:
        copy_file(repo / relative, destination / relative)
    copy_tree(repo / "src/rbpbench", destination / "src/rbpbench")
    copy_file(
        repo / "docs/tasks/002c3_portable_cross_partition_audit.md",
        destination / "RUNBOOK.md",
    )
    copy_file(
        repo / "docs/handoffs/002c3_002c4_portable_executor_prompt.md",
        destination / "PROMPT_FOR_CLAUDE_OR_CODEX.md",
    )
    copy_file(repo / "dataset_K562_multilabel_with_NEGs.csv", destination / "dataset_K562_multilabel_with_NEGs.csv")
    copy_tree(repo / DECODE_REL, destination / DECODE_REL)
    for subtree in ACCEPTED_OUTPUT_SUBTREES:
        copy_tree(repo / OUTPUT_REL / subtree, destination / OUTPUT_REL / subtree)
    for name in ACCEPTED_SELECTED:
        copy_file(repo / OUTPUT_REL / "selected" / name, destination / OUTPUT_REL / "selected" / name)
    for relative in EVIDENCE_FILES:
        copy_file(repo / EVIDENCE_REL / relative, destination / EVIDENCE_REL / relative)
    copy_tree(environment_prefix, destination / RUNTIME_REL)

    (destination / "SOURCE_COMMIT.txt").write_text(commit + "\n")
    write_launcher(destination / "RUN_002C3_002C4.command")
    summary = {
        "schema_version": 1,
        "checkpoint": "002C-3-and-conditional-002C-4",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_commit": commit,
        "execution_host": "native Apple-Silicon macOS",
        "bundled_mmseqs_sha256": mmseqs_hash,
        "network_required_at_execution": False,
        "single_entrypoint": "RUN_002C3_002C4.command",
        "return_location": "return/RBP_002C3_RETURN_<timestamp>_<host>.zip",
    }
    write_json(destination / "BUNDLE_SUMMARY.json", summary)

    manifest = {
        "schema_version": 1,
        "checkpoint": "002C-3-and-conditional-002C-4",
        "source_commit": commit,
        "entries": inventory_tree(
            destination,
            excluded=frozenset({"HANDOFF_INPUT_MANIFEST.json", "HANDOFF_INPUT_MANIFEST.sha256"}),
        ),
    }
    manifest_path = destination / "HANDOFF_INPUT_MANIFEST.json"
    write_json(manifest_path, manifest)
    manifest_hash = sha256_file(manifest_path)
    (destination / "HANDOFF_INPUT_MANIFEST.sha256").write_text(
        f"{manifest_hash}  HANDOFF_INPUT_MANIFEST.json\n"
    )
    return destination, summary | {
        "input_manifest_sha256": manifest_hash,
        "input_entry_count": len(manifest["entries"]),
        "input_regular_file_bytes": sum(
            entry.get("byte_size", 0) for entry in manifest["entries"] if entry["type"] == "file"
        ),
    }


def create_archive(bundle: Path) -> tuple[Path, str]:
    archive = bundle.with_suffix(".tar.gz")
    if archive.exists():
        raise FileExistsError(f"archive already exists: {archive}")
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(bundle, arcname=bundle.name, recursive=True)
    digest = sha256_file(archive)
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{digest}  {archive.name}\n")
    return archive, digest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--environment-prefix", type=Path, required=True)
    parser.add_argument("--archive", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    bundle, summary = build_bundle(args.repo, args.destination, args.environment_prefix)
    result = {"bundle": str(bundle), **summary}
    if args.archive:
        archive, digest = create_archive(bundle)
        result.update({"archive": str(archive), "archive_sha256": digest, "archive_byte_size": archive.stat().st_size})
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
