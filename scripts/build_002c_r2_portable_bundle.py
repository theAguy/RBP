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
import json
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rbpbench.splits import portable_002c_r2 as launcher  # noqa: E402

LAUNCHER_NAME = "RUN_002C_R2_PROBE.command"

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


def build_bundle(
    repo: Path, destination: Path, runtime_prefix: Path, decode_dir: Path, *, decode_manifest_sha256: str, seed: int,
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
    if launcher.sha256_file(mmseqs) != expected_mmseqs_sha256:
        raise RuntimeError("runtime MMseqs2 does not match the expected native arm64 SHA-256")

    destination.mkdir(parents=True)
    shutil.copytree(repo / "src/rbpbench", destination / "src/rbpbench", symlinks=True, ignore=_ignore_generated)
    (destination / launcher.DECODE_MANIFEST_REL).parent.mkdir(parents=True)
    shutil.copy2(manifest_src, destination / launcher.DECODE_MANIFEST_REL)
    (destination / launcher.FASTA_DIR_REL).mkdir(parents=True)
    for width, src in fastas.items():
        shutil.copy2(src, destination / launcher.FASTA_DIR_REL / src.name)
    shutil.copytree(runtime_prefix, destination / launcher.RUNTIME_REL, symlinks=True, ignore=_ignore_generated)

    config = {
        "schema_version": 1, "checkpoint": launcher.CHECKPOINT, "seed": seed,
        "decode_manifest_sha256": decode_manifest_sha256, "expected_mmseqs_sha256": expected_mmseqs_sha256,
        "expected_mmseqs_version": expected_mmseqs_version, "sample_size": sample_size,
        "expected_row_count": expected_row_count, "stages": list(launcher.probe.PROBE_STAGES),
    }
    (destination / launcher.CONFIG_REL).write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    (destination / "RUNBOOK.md").write_text(RUNBOOK)
    (destination / "SOURCE_COMMIT.txt").write_text(commit + "\n")
    write_launcher(destination / LAUNCHER_NAME)
    summary = {
        "schema_version": 1, "checkpoint": launcher.CHECKPOINT, "source_commit": commit,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "single_entrypoint": LAUNCHER_NAME, "network_required_at_execution": False,
        "return_location": "return/RBP_002C_R2_RETURN_<timestamp>_<host>.zip",
        "r3_authorization": "none",
    }
    (destination / "BUNDLE_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    entries = launcher.inventory_tree(destination, excluded=launcher._MANIFEST_FILES)
    for entry in entries:  # permitted symlinks live only inside the private runtime and stay inside the bundle
        if entry["type"] == "symlink":
            if Path(entry["path"]).parts[:1] != (launcher.RUNTIME_REL.parts[0],):
                raise RuntimeError(f"symlink outside the private runtime: {entry['path']}")
            target = (destination / entry["path"]).parent / entry["target"]
            try:
                Path(__import__("os").path.normpath(target)).relative_to(destination)
            except ValueError:
                raise RuntimeError(f"runtime symlink escapes the bundle: {entry['path']} -> {entry['target']}") from None
    manifest = {"schema_version": 1, "checkpoint": launcher.CHECKPOINT, "source_commit": commit, "entries": entries}
    manifest_path = destination / launcher.INPUT_MANIFEST_REL
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    digest = launcher.sha256_file(manifest_path)
    (destination / launcher.INPUT_MANIFEST_HASH_REL).write_text(f"{digest}  {launcher.INPUT_MANIFEST_REL.name}\n")
    return destination, summary | {"input_manifest_sha256": digest, "input_entry_count": len(entries)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--runtime-prefix", type=Path, required=True)
    p.add_argument("--decode-dir", type=Path, required=True)
    p.add_argument("--decode-manifest-sha256", required=True)
    p.add_argument("--seed", type=int, required=True)
    return p


def main(argv: Sequence[str] | None = None) -> None:
    a = build_parser().parse_args(argv)
    bundle, summary = build_bundle(a.repo, a.destination, a.runtime_prefix, a.decode_dir,
                                   decode_manifest_sha256=a.decode_manifest_sha256, seed=a.seed)
    print(json.dumps({"bundle": str(bundle), **summary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
