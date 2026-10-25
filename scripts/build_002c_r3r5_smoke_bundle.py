#!/usr/bin/env python3
"""Build the self-contained Darwin real-binary smoke bundle for Task 002C-R3-R5.

The bundle contains reviewed source code, two synthetic tests, operational
scripts, and no project data.  It never runs MMseqs2 or contacts a scheduler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rbpbench.splits.r3r5.bundle import source_closure  # noqa: E402

MANIFEST = "SMOKE_PACKAGE_MANIFEST.json"
SIDECAR = MANIFEST + ".sha256"
RUNTIME_DIRS = {"runtime", "return"}
COPY_DIRS = ("hpc/darwin/002c_r3r5", "hpc/darwin/002c_r3r5_smoke")
COPY_FILES = (
    "tests/r3r5_support.py",
    "tests/test_splits_r3r5_real_binary.py",
    "configs/splits/sequence_partitions_002c_v2.toml",
    "pyproject.toml",
)


class BuildError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(root: Path) -> list[dict]:
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d not in RUNTIME_DIRS]
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if name in {MANIFEST, SIDECAR, ".DS_Store"} or name.endswith((".pyc", ".pyo")):
                continue
            if path.is_symlink() or not path.is_file():
                raise BuildError(f"unsupported package entry: {rel}")
            entries.append({"path": rel, "byte_size": path.stat().st_size, "sha256": sha256(path),
                            "executable": bool(path.stat().st_mode & 0o111)})
    return entries


def verify(root: Path) -> dict:
    root = Path(root).resolve()
    manifest_path = root / MANIFEST
    sidecar = root / SIDECAR
    if not manifest_path.is_file() or not sidecar.is_file():
        raise BuildError("package manifest or sidecar is missing")
    expected_line = f"{sha256(manifest_path)}  {MANIFEST}\n"
    if sidecar.read_text() != expected_line:
        raise BuildError("package manifest sidecar is wrong")
    doc = json.loads(manifest_path.read_text())
    expected = {e["path"]: e for e in doc["entries"]}
    current = {e["path"]: e for e in inventory(root)}
    if expected != current:
        raise BuildError(f"package inventory mismatch: missing={sorted(set(expected)-set(current))[:4]}, "
                         f"extra={sorted(set(current)-set(expected))[:4]}, "
                         f"changed={sorted(k for k in set(expected)&set(current) if expected[k] != current[k])[:4]}")
    return {"source_commit": doc["source_commit"], "entry_count": len(expected),
            "manifest_sha256": sha256(manifest_path)}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    if done.returncode:
        raise BuildError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout.strip()


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"))


def build(repo: Path, destination: Path) -> dict:
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    if destination.exists():
        raise BuildError(f"destination already exists: {destination}")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise BuildError("tracked worktree changes must be committed before building")
    commit = git(repo, "rev-parse", "HEAD")
    destination.mkdir(parents=True)
    try:
        for rel in COPY_DIRS:
            copy_tree(repo / rel, destination / rel)
        closure = source_closure(repo / "src")
        for rel in closure:
            target = destination / "src" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / "src" / rel, target)
        for rel in COPY_FILES:
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / rel, target)
        (destination / "SOURCE_COMMIT.txt").write_text(commit + "\n")
        doc = {
            "schema_version": 1,
            "checkpoint": "002C-R3R5-DARWIN-SMOKE",
            "source_commit": commit,
            "purpose": "two synthetic real-MMseqs2 tests only; no real dataset and no R3-R5 production execution",
            "environment_policy": "verify the accepted Darwin R2 environment; never install or modify it",
            "source_closure": closure,
            "entries": inventory(destination),
        }
        manifest_path = destination / MANIFEST
        manifest_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        (destination / SIDECAR).write_text(f"{sha256(manifest_path)}  {MANIFEST}\n")
        result = verify(destination)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {"bundle": str(destination), **result}


def archive(bundle: Path) -> dict:
    bundle = Path(bundle).resolve()
    verify(bundle)
    output = bundle.parent / f"{bundle.name}.tar.gz"
    sidecar = Path(f"{output}.sha256")
    if output.exists() or sidecar.exists():
        raise BuildError("archive or archive sidecar already exists")
    with tarfile.open(output, "x:gz") as handle:
        handle.add(bundle, arcname=bundle.name)
    expected = {e["path"]: e for e in inventory(bundle)}
    for special in (MANIFEST, SIDECAR):
        path = bundle / special
        expected[special] = {"path": special, "byte_size": path.stat().st_size, "sha256": sha256(path)}
    seen = set()
    with tarfile.open(output, "r:gz") as handle:
        prefix = bundle.name + "/"
        for member in handle.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or not member.name.startswith(prefix):
                raise BuildError(f"unexpected archive member {member.name}")
            rel = member.name[len(prefix):]
            entry = expected.get(rel)
            if entry is None or rel in seen:
                raise BuildError(f"unexpected or duplicate archive member {rel}")
            data = handle.extractfile(member).read()
            if len(data) != entry["byte_size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise BuildError(f"archive member changed: {rel}")
            seen.add(rel)
    if seen != set(expected):
        raise BuildError(f"archive is missing members: {sorted(set(expected)-seen)[:5]}")
    digest = sha256(output)
    sidecar.write_text(f"{digest}  {output.name}\n")
    return {"archive": str(output), "sha256": digest, "byte_size": output.stat().st_size,
            "members": len(seen)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args()
    result = build(args.repo, args.destination)
    if args.archive:
        result["archive"] = archive(args.destination)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
