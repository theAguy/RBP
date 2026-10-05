#!/usr/bin/env python3
"""Build the immutable, offline Task 002C-R2 resource-probe package.

Source/test checkpoint: this script is exercised only with generated tiny
inputs. It never reads the raw CSV, labels, partition/component results,
references, or models, and it copies only the R2 source tree, the tracked
decode manifest, the three manifest-bound decode FASTAs, the explicit native
arm64 runtime, and generated launcher/runbook/config files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rbpbench.splits import portable_002c_r2 as launcher  # noqa: E402

LAUNCHER_NAME = "RUN_002C_R2_PROBE.command"

# Explicit R2-only source subset (the static import closure of the launcher
# and ``resource_probe_r2``). Nothing else under src/rbpbench is shipped, so
# direct-edge, components-v2, assignment, audit, runner_002c, the 002C-3
# launcher and any R3-capable module are structurally absent. A test checks
# this list against the real import closure so it cannot drift.
R2_SOURCE_SUBSET: tuple[str, ...] = (
    "rbpbench/__init__.py",
    "rbpbench/coordinates/__init__.py",
    "rbpbench/coordinates/alignment.py",
    "rbpbench/coordinates/commands.py",
    "rbpbench/coordinates/config.py",
    "rbpbench/coordinates/decode.py",
    "rbpbench/coordinates/diskbudget.py",
    "rbpbench/coordinates/hashing.py",
    "rbpbench/coordinates/preflight.py",
    "rbpbench/coordinates/provenance.py",
    "rbpbench/coordinates/reference.py",
    "rbpbench/data/__init__.py",
    "rbpbench/data/audit.py",
    "rbpbench/splits/__init__.py",
    "rbpbench/splits/commands.py",
    "rbpbench/splits/guarded_exec.py",
    "rbpbench/splits/portable_002c_r2.py",
    "rbpbench/splits/resource_probe_r2.py",
)

PROMPT = """Instructions for the collaborator's AI assistant (Claude or Codex) - Task 002C-R2 resource probe

Do exactly this and nothing else:

1. Run ONLY the one launcher in this folder: RUN_002C_R2_PROBE.command (double-click it, or execute it once).
2. Wait for it to finish. Do not interrupt it, retry it, or run it a second time.
3. Return ONLY the generated ZIP: return/RBP_002C_R2_RETURN_<timestamp>_<host>.zip
   (return it even if the run reports STOPPED).

Do NOT:
- run mmseqs or any other program from this folder directly, or change any file, setting, or flag;
- inspect, copy, or upload the FASTA files, databases, or any other file in this folder;
- authorize, start, or prepare R3 (full edge discovery) or any other task. A successful probe is resource
  evidence only; it is NOT authorization for R3. Stop after returning the ZIP.
"""

RUNBOOK = """# Task 002C-R2 resource probe — runbook

1. Double-click **RUN_002C_R2_PROBE.command** (exactly one launcher; do not run anything else).
2. Wait for it to finish. It can take a long time; keep the Mac awake and plugged in.
3. Return **only** the generated ZIP: `return/RBP_002C_R2_RETURN_<timestamp>_<host>.zip`.

The probe runs three fixed resource measurements (500, 251, 101 nt) and stops at the first problem
without retrying. It never uses the network.

A successful resource probe is evidence only. It is **NOT** authorization for R3 (full edge discovery).
Do not run the launcher a second time: the package is single-use and will refuse to reuse its outputs.
"""


def git_value(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout.strip()


def assert_clean_source(repo: Path) -> str:
    if git_value(repo, "status", "--porcelain"):
        raise RuntimeError("source worktree must be clean before the package is built")
    return git_value(repo, "rev-parse", "HEAD")


def _ignore_generated(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n in {"__pycache__", ".DS_Store"} or n.endswith((".pyc", ".pyo"))}


def write_launcher(destination: Path) -> None:
    text = """#!/bin/zsh
set -eu
BUNDLE_ROOT=${0:A:h}
cd "$BUNDLE_ROOT"

# Remove only the download-quarantine attribute, only inside this package's private runtime.
if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$BUNDLE_ROOT/.runtime" 2>/dev/null || true
fi

PYTHON_BIN="$BUNDLE_ROOT/.runtime/rbpbench-splits-002c-arm64/bin/python"
export PYTHONPATH="$BUNDLE_ROOT/src"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PATH="$BUNDLE_ROOT/.runtime/rbpbench-splits-002c-arm64/bin:$PATH"

if [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 "Bundled Python is missing or not executable: $PYTHON_BIN"
  exit 1
fi

if command -v caffeinate >/dev/null 2>&1; then
  exec caffeinate -ims "$PYTHON_BIN" -m rbpbench.splits.portable_002c_r2 --bundle-root "$BUNDLE_ROOT"
fi
exec "$PYTHON_BIN" -m rbpbench.splits.portable_002c_r2 --bundle-root "$BUNDLE_ROOT"
"""
    destination.write_text(text)
    destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def verify_runtime_against_manifest(runtime_prefix: Path, manifest_path: Path, expected_sha256: str) -> dict:
    """Verifies the WHOLE runtime prefix against an explicit expected runtime
    manifest (pinned by SHA-256) before anything is copied: every regular
    file (path, size, SHA-256) and every symlink (path, target) must match,
    with no missing, extra, retyped, or escaping path. The manifest's paths
    are relative to the runtime prefix. Raises RuntimeError on any mismatch."""
    runtime_prefix, manifest_path = Path(runtime_prefix).resolve(), Path(manifest_path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""):
        raise ValueError("expected runtime-manifest SHA-256 must be 64 lowercase hex characters")
    if not manifest_path.is_file() or launcher.sha256_file(manifest_path) != expected_sha256:
        raise RuntimeError("runtime manifest is missing or does not match its pinned SHA-256")
    data = json.loads(manifest_path.read_text())
    entries = data.get("entries")
    if data.get("schema_version") != 1 or not isinstance(entries, list) or not entries:
        raise RuntimeError("runtime manifest is not a non-empty schema-1 manifest")
    expected: dict[str, dict] = {}
    for entry in entries:
        rel = entry.get("path")
        if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in Path(rel).parts or rel in expected:
            raise RuntimeError(f"invalid or duplicate runtime manifest path: {rel!r}")
        if entry.get("type") not in ("file", "symlink"):
            raise RuntimeError(f"unsupported runtime manifest entry type for {rel}")
        expected[rel] = entry
    actual = {e["path"]: e for e in launcher.inventory_tree(runtime_prefix, excluded=frozenset())}
    missing, extra = sorted(set(expected) - set(actual)), sorted(set(actual) - set(expected))
    if missing or extra:
        raise RuntimeError(f"runtime differs from the expected manifest: missing {missing[:5]}, extra {extra[:5]}")
    for rel, want in expected.items():
        have = actual[rel]
        if have["type"] != want["type"]:
            raise RuntimeError(f"runtime entry changed type: {rel}")
        if want["type"] == "symlink":
            if have["target"] != want.get("target"):
                raise RuntimeError(f"runtime symlink target differs from the manifest: {rel}")
            resolved = Path(os.path.normpath((runtime_prefix / rel).parent / have["target"]))
            try:
                resolved.relative_to(runtime_prefix)
            except ValueError:
                raise RuntimeError(f"runtime symlink escapes the runtime prefix: {rel} -> {have['target']}") from None
        elif (have["byte_size"], have["sha256"]) != (want.get("byte_size"), want.get("sha256")):
            raise RuntimeError(f"runtime file differs from the expected manifest: {rel}")
    return {"entry_count": len(expected), "sha256": expected_sha256}


def build_bundle(
    repo: Path, destination: Path, runtime_prefix: Path, decode_dir: Path, *, decode_manifest_sha256: str, seed: int,
    runtime_manifest: Path, runtime_manifest_sha256: str, environment_lock: Path,
    expected_mmseqs_sha256: str = launcher.FROZEN_ARM64_MMSEQS_SHA256,
    expected_mmseqs_version: str = launcher.FROZEN_MMSEQS_VERSION,
    sample_size: int = launcher.FROZEN_SAMPLE_SIZE, expected_row_count: int = 361_180,
) -> tuple[Path, dict]:
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    runtime_prefix, decode_dir = Path(runtime_prefix).resolve(), Path(decode_dir).resolve()
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    if not re.fullmatch(r"[0-9a-f]{64}", decode_manifest_sha256):
        raise ValueError("decode manifest SHA-256 must be 64 lowercase hex characters")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an explicit integer")
    commit = assert_clean_source(repo)

    manifest_src = repo / launcher.DECODE_MANIFEST_REL
    if not manifest_src.is_file() or launcher.sha256_file(manifest_src) != decode_manifest_sha256:
        raise RuntimeError("decode manifest is missing or does not match the pinned SHA-256")
    evidence = {}
    for entry in json.loads(manifest_src.read_text()).get("retained_artifacts", []):
        m = re.search(r"sequence_partitions_width_(\d+)\.fasta$", entry.get("path", ""))
        if m:
            evidence[int(m.group(1))] = entry
    fastas = {}
    for width in launcher.WIDTHS:
        src = decode_dir / f"sequence_partitions_width_{width}.fasta"
        entry = evidence.get(width)
        if entry is None or not src.is_file() or src.stat().st_size != entry["byte_size"] or launcher.sha256_file(src) != entry["sha256"]:
            raise RuntimeError(f"FASTA for width {width} is missing or does not match the accepted decode evidence")
        fastas[width] = src

    mmseqs, python = runtime_prefix / "bin/mmseqs", runtime_prefix / "bin/python"
    if not mmseqs.is_file() or not python.is_file():
        raise RuntimeError(f"runtime prefix lacks bin/python or bin/mmseqs: {runtime_prefix}")
    # Gate 1: the complete runtime against the pinned expected runtime manifest (before any copy).
    verify_runtime_against_manifest(runtime_prefix, runtime_manifest, runtime_manifest_sha256)
    # Gate 2 (independent): the fixed MMseqs2 hash.
    if launcher.sha256_file(mmseqs) != expected_mmseqs_sha256:
        raise RuntimeError("runtime MMseqs2 does not match the expected native arm64 SHA-256")
    environment_lock = Path(environment_lock)
    if not environment_lock.is_file():
        raise RuntimeError("environment lock file is missing")

    destination.mkdir(parents=True)
    for rel in R2_SOURCE_SUBSET:
        source = repo / "src" / rel
        if not source.is_file():
            raise RuntimeError(f"required R2 source file is missing from the repository: src/{rel}")
        (destination / "src" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination / "src" / rel)
    (destination / launcher.DECODE_MANIFEST_REL).parent.mkdir(parents=True)
    shutil.copy2(manifest_src, destination / launcher.DECODE_MANIFEST_REL)
    (destination / launcher.FASTA_DIR_REL).mkdir(parents=True)
    for width, src in fastas.items():
        shutil.copy2(src, destination / launcher.FASTA_DIR_REL / src.name)
    shutil.copytree(runtime_prefix, destination / launcher.RUNTIME_REL, symlinks=True, ignore=_ignore_generated)
    shutil.copy2(runtime_manifest, destination / launcher.RUNTIME_MANIFEST_REL)
    shutil.copy2(environment_lock, destination / launcher.ENVIRONMENT_LOCK_REL)
    lock_sha256 = launcher.sha256_file(destination / launcher.ENVIRONMENT_LOCK_REL)

    config = {
        "schema_version": 1, "checkpoint": launcher.CHECKPOINT, "seed": seed,
        "decode_manifest_sha256": decode_manifest_sha256, "expected_mmseqs_sha256": expected_mmseqs_sha256,
        "expected_mmseqs_version": expected_mmseqs_version, "sample_size": sample_size,
        "expected_row_count": expected_row_count, "runtime_manifest_sha256": runtime_manifest_sha256,
        "environment_lock_sha256": lock_sha256, "stages": list(launcher.probe.PROBE_STAGES),
    }
    (destination / launcher.CONFIG_REL).write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    (destination / "RUNBOOK.md").write_text(RUNBOOK)
    (destination / "PROMPT_FOR_CLAUDE_OR_CODEX.txt").write_text(PROMPT)
    (destination / "SOURCE_COMMIT.txt").write_text(commit + "\n")
    write_launcher(destination / LAUNCHER_NAME)
    summary = {
        "schema_version": 1, "checkpoint": launcher.CHECKPOINT, "source_commit": commit,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "single_entrypoint": LAUNCHER_NAME, "network_required_at_execution": False,
        "return_location": "return/RBP_002C_R2_RETURN_<timestamp>_<host>.zip",
        "r3_authorization": "none",
        "expected_runtime_manifest_sha256": runtime_manifest_sha256, "environment_lock_sha256": lock_sha256,
    }
    (destination / "BUNDLE_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    entries = launcher.inventory_tree(destination, excluded=launcher._MANIFEST_FILES)
    for entry in entries:  # permitted symlinks live only inside the private runtime and stay inside the bundle
        if entry["type"] == "symlink":
            if Path(entry["path"]).parts[:1] != (launcher.RUNTIME_REL.parts[0],):
                raise RuntimeError(f"symlink outside the private runtime: {entry['path']}")
            target = (destination / entry["path"]).parent / entry["target"]
            try:
                Path(os.path.normpath(target)).relative_to(destination)
            except ValueError:
                raise RuntimeError(f"runtime symlink escapes the bundle: {entry['path']} -> {entry['target']}") from None
    manifest = {"schema_version": 1, "checkpoint": launcher.CHECKPOINT, "source_commit": commit, "entries": entries}
    manifest_path = destination / launcher.INPUT_MANIFEST_REL
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    digest = launcher.sha256_file(manifest_path)
    (destination / launcher.INPUT_MANIFEST_HASH_REL).write_text(f"{digest}  {launcher.INPUT_MANIFEST_REL.name}\n")
    return destination, summary | {"input_manifest_sha256": digest, "input_entry_count": len(entries)}


def verify_archive(archive: Path, bundle: Path) -> int:
    """Re-reads ``archive`` and checks it holds exactly the bundle's inventory
    (every file/symlink, matching size/SHA-256/target) plus the manifest and
    its hash file, under the bundle's top-level directory name."""
    manifest = json.loads((bundle / launcher.INPUT_MANIFEST_REL).read_text())
    expected = {e["path"]: e for e in manifest["entries"]}
    for rel in (launcher.INPUT_MANIFEST_REL, launcher.INPUT_MANIFEST_HASH_REL):
        expected[str(rel)] = {"path": str(rel), "type": "file", "byte_size": (bundle / rel).stat().st_size,
                              "sha256": launcher.sha256_file(bundle / rel)}
    seen = set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if member.isdir():
                continue
            if not member.name.startswith(bundle.name + "/"):
                raise RuntimeError(f"archive member outside the bundle directory: {member.name}")
            rel = member.name[len(bundle.name) + 1:]
            entry = expected.get(rel)
            if entry is None or rel in seen:
                raise RuntimeError(f"archive holds an unexpected or duplicate member: {rel}")
            seen.add(rel)
            if entry["type"] == "symlink":
                if not member.issym() or member.linkname != entry["target"]:
                    raise RuntimeError(f"archive symlink mismatch: {rel}")
            else:
                if not member.isfile() or member.size != entry["byte_size"]:
                    raise RuntimeError(f"archive file mismatch: {rel}")
                digest = hashlib.sha256()
                handle = tar.extractfile(member)
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                if digest.hexdigest() != entry["sha256"]:
                    raise RuntimeError(f"archive file hash mismatch: {rel}")
    if seen != set(expected):
        raise RuntimeError(f"archive is missing members: {sorted(set(expected) - seen)[:5]}")
    return len(seen)


def create_archive(bundle: Path) -> tuple[Path, str]:
    """``<bundle>.tar.gz`` plus ``<bundle>.tar.gz.sha256``, built only from a
    completed bundle (its input manifest must exist), verified by re-reading,
    and refused if either output already exists."""
    bundle = Path(bundle).resolve()
    if not (bundle / launcher.INPUT_MANIFEST_REL).is_file() or not (bundle / launcher.INPUT_MANIFEST_HASH_REL).is_file():
        raise RuntimeError("bundle has no completed input manifest; refusing to archive")
    launcher.verify_inventory(bundle)
    archive = bundle.parent / (bundle.name + ".tar.gz")
    checksum = bundle.parent / (archive.name + ".sha256")
    if archive.exists() or checksum.exists():
        raise FileExistsError(f"archive or checksum already exists: {archive}")
    try:
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(bundle, arcname=bundle.name, recursive=True)
        verify_archive(archive, bundle)
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
    digest = launcher.sha256_file(archive)
    checksum.write_text(f"{digest}  {archive.name}\n")
    return archive, digest


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--runtime-prefix", type=Path, required=True)
    p.add_argument("--decode-dir", type=Path, required=True)
    p.add_argument("--decode-manifest-sha256", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--runtime-manifest", type=Path, required=True, help="accepted expected runtime manifest (JSON)")
    p.add_argument("--runtime-manifest-sha256", required=True)
    p.add_argument("--environment-lock", type=Path, required=True, help="accepted explicit environment lock")
    p.add_argument("--archive", action="store_true", help="also create a verified <bundle>.tar.gz and .sha256")
    return p


def main(argv: Sequence[str] | None = None) -> None:
    a = build_parser().parse_args(argv)
    bundle, summary = build_bundle(a.repo, a.destination, a.runtime_prefix, a.decode_dir,
                                   decode_manifest_sha256=a.decode_manifest_sha256, seed=a.seed,
                                   runtime_manifest=a.runtime_manifest, runtime_manifest_sha256=a.runtime_manifest_sha256,
                                   environment_lock=a.environment_lock)
    result = {"bundle": str(bundle), **summary}
    if a.archive:
        archive, digest = create_archive(bundle)
        result.update({"archive": str(archive), "archive_sha256": digest, "archive_byte_size": archive.stat().st_size})
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
