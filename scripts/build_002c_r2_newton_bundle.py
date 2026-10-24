#!/usr/bin/env python3
"""Build the immutable Linux/Slurm Task 002C-R2 Newton input bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rbpbench.splits import newton_002c_r2 as newton  # noqa: E402
from rbpbench.splits import portable_002c_r2 as package  # noqa: E402

SEED = 20260925
DECODE_MANIFEST_SHA256 = "d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3"

SOURCE_SUBSET: tuple[str, ...] = (
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
    "rbpbench/splits/newton_002c_r2.py",
)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if done.returncode:
        raise RuntimeError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout.strip()


def build(repo: Path, destination: Path, decode_dir: Path) -> tuple[Path, dict]:
    repo, destination, decode_dir = repo.resolve(), destination.resolve(), decode_dir.resolve()
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    if git(repo, "status", "--porcelain"):
        raise RuntimeError("source worktree must be clean before building the real Newton bundle")
    commit = git(repo, "rev-parse", "HEAD")
    decode_manifest = repo / package.DECODE_MANIFEST_REL
    if package.sha256_file(decode_manifest) != DECODE_MANIFEST_SHA256:
        raise RuntimeError("accepted decode manifest is missing or changed")
    decoded = json.loads(decode_manifest.read_text())
    evidence = {
        int(Path(entry["path"]).stem.rsplit("_", 1)[-1]): entry
        for entry in decoded.get("retained_artifacts", [])
        if Path(entry.get("path", "")).name.startswith("sequence_partitions_width_")
        and Path(entry["path"]).suffix == ".fasta"
    }
    fastas: dict[int, Path] = {}
    for width in package.WIDTHS:
        source = decode_dir / f"sequence_partitions_width_{width}.fasta"
        entry = evidence.get(width)
        if (
            entry is None or not source.is_file() or source.stat().st_size != entry["byte_size"]
            or package.sha256_file(source) != entry["sha256"]
        ):
            raise RuntimeError(f"width-{width} FASTA does not match accepted decode evidence")
        fastas[width] = source

    destination.mkdir(parents=True)
    for rel in SOURCE_SUBSET:
        source = repo / "src" / rel
        if not source.is_file():
            raise RuntimeError(f"missing source closure member: src/{rel}")
        target = destination / "src" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copytree(
        repo / "hpc" / "newton" / "002c_r2",
        destination / "hpc" / "newton" / "002c_r2",
        ignore=lambda _path, names: {
            name for name in names if name == "__pycache__" or name.endswith((".pyc", ".pyo"))
        },
    )
    for script in (destination / "hpc" / "newton" / "002c_r2").iterdir():
        if script.suffix in {".sh", ".sbatch", ".py"}:
            script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    (destination / package.DECODE_MANIFEST_REL).parent.mkdir(parents=True)
    shutil.copy2(decode_manifest, destination / package.DECODE_MANIFEST_REL)
    (destination / package.FASTA_DIR_REL).mkdir(parents=True)
    for source in fastas.values():
        shutil.copy2(source, destination / package.FASTA_DIR_REL / source.name)
    shutil.copy2(
        repo / "hpc" / "newton" / "002c_r2" / "README_NEWTON.md",
        destination / "README_NEWTON.md",
    )
    config = {
        "schema_version": 1,
        "checkpoint": newton.CHECKPOINT,
        "source_commit": commit,
        "seed": SEED,
        "decode_manifest_sha256": DECODE_MANIFEST_SHA256,
        "sample_size": package.FROZEN_SAMPLE_SIZE,
        "expected_row_count": 361_180,
        "expected_mmseqs_version": newton.FROZEN_MMSEQS_VERSION,
        "expected_mmseqs_conda_build": newton.FROZEN_MMSEQS_CONDA_BUILD,
        "stages": list(package.probe.PROBE_STAGES),
        "scientific_edge_evidence": False,
        "r3_authorization": "none",
    }
    (destination / newton.CONFIG_REL).write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    (destination / "SOURCE_COMMIT.txt").write_text(commit + "\n")
    summary = {
        "schema_version": 1,
        "checkpoint": newton.CHECKPOINT,
        "source_commit": commit,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "platform": "Technion Darwin Slurm / Linux x86_64 (legacy newton adapter path)",
        "environment_bundled": False,
        "environment_setup": "hpc/newton/002c_r2/01_INSTALL_ENVIRONMENT.sh",
        "single_submit_entrypoint": "hpc/newton/002c_r2/02_SUBMIT_R2_PROBE.sh",
        "return_pattern": "return/RBP_002C_R2_NEWTON_RETURN_<timestamp>_<host>.zip",
        "gpu_required": False,
        "r3_authorization": "none",
    }
    (destination / "BUNDLE_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    entries = package.inventory_tree(destination, excluded=package._MANIFEST_FILES)
    manifest = {
        "schema_version": 1,
        # Keep the accepted portable inventory schema/checkpoint.  The
        # Newton-specific execution checkpoint is in R2_NEWTON_CONFIG.json.
        "checkpoint": package.CHECKPOINT,
        "source_commit": commit,
        "entries": entries,
    }
    manifest_path = destination / package.INPUT_MANIFEST_REL
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    digest = package.sha256_file(manifest_path)
    (destination / package.INPUT_MANIFEST_HASH_REL).write_text(
        f"{digest}  {package.INPUT_MANIFEST_REL.name}\n"
    )
    package.verify_inventory(destination)
    return destination, summary | {"input_manifest_sha256": digest, "input_entry_count": len(entries)}


def archive(bundle: Path) -> tuple[Path, str]:
    output = bundle.parent / (bundle.name + ".tar.gz")
    checksum = output.with_name(output.name + ".sha256")
    if output.exists() or checksum.exists():
        raise FileExistsError("archive or checksum already exists")
    with tarfile.open(output, "x:gz") as handle:
        handle.add(bundle, arcname=bundle.name)
    expected = {
        entry["path"]: entry for entry in package.inventory_tree(bundle, excluded=frozenset())
    }
    seen: set[str] = set()
    with tarfile.open(output, "r:gz") as handle:
        for member in handle.getmembers():
            if member.isdir():
                continue
            prefix = bundle.name + "/"
            if not member.name.startswith(prefix):
                raise RuntimeError(f"archive member escaped the bundle root: {member.name}")
            rel = member.name[len(prefix):]
            entry = expected.get(rel)
            if entry is None or rel in seen:
                raise RuntimeError(f"unexpected or duplicate archive member: {rel}")
            seen.add(rel)
            if entry["type"] == "symlink":
                if not member.issym() or member.linkname != entry["target"]:
                    raise RuntimeError(f"archive symlink mismatch: {rel}")
            else:
                if not member.isfile() or member.size != entry["byte_size"]:
                    raise RuntimeError(f"archive file mismatch: {rel}")
                stream = handle.extractfile(member)
                digest_stream = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest_stream.update(chunk)
                if digest_stream.hexdigest() != entry["sha256"]:
                    raise RuntimeError(f"archive hash mismatch: {rel}")
    if seen != set(expected):
        raise RuntimeError(f"archive is missing members: {sorted(set(expected) - seen)[:5]}")
    digest = package.sha256_file(output)
    checksum.write_text(f"{digest}  {output.name}\n")
    return output, digest


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--decode-dir", type=Path, required=True)
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args(argv)
    bundle, summary = build(args.repo, args.destination, args.decode_dir)
    result = {"bundle": str(bundle), **summary}
    if args.archive:
        path, digest = archive(bundle)
        result.update({"archive": str(path), "archive_sha256": digest, "archive_byte_size": path.stat().st_size})
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
