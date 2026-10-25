"""Immutable portable Darwin bundle: build, inventory, verify, archive.

The builder refuses to produce a bundle unless every required frozen input
is supplied and hashes/sizes exactly as the reviewed contract states; it
also refuses extra or unreviewed roles, a dirty source worktree, or a
configuration that differs from the reviewed constants.  The bundle carries
only the import closure of the Darwin entrypoint (computed, not hand
listed), the Darwin scripts, the versioned configuration, and the frozen
inputs at fixed relative paths.  At runtime :func:`verify_bundle` re-hashes
every listed file and rejects any unlisted file outside the runtime-owned
``r3r5_work/`` and ``returns/`` directories.
"""

from __future__ import annotations

import hashlib
import json
import modulefinder
import os
import shutil
import stat
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from rbpbench.data.audit import sha256_file
from rbpbench.splits.r3r5.contract import (
    CHECKPOINT,
    CONFIG_REL,
    PRODUCTION,
    REQUIRED_INPUT_ROLES,
    Contract,
    load_production_contract,
)
from rbpbench.splits.r3r5.stops import IntegrityStop

MANIFEST_REL = Path("R3R5_INPUT_MANIFEST.json")
MANIFEST_HASH_REL = Path("R3R5_INPUT_MANIFEST.sha256")
RUNTIME_OWNED = frozenset({"r3r5_work", "returns"})
_IGNORED = frozenset({"__pycache__", ".DS_Store"})
HPC_REL = Path("hpc/darwin/002c_r3r5")
ENTRYPOINT_MODULE = "rbpbench.splits.r3r5.darwin"
# ``rbpbench.coordinates.alignment``/``config`` are imported only for
# dataclass definitions by the accepted R2 resource monitors (preflight ->
# config -> alignment); no coordinate stage is reachable from the entrypoint.
FORBIDDEN_MODULE_FRAGMENTS = (
    "rbpbench.coordinates.download", "rbpbench.coordinates.indexing", "rbpbench.coordinates.probe",
    "rbpbench.coordinates.cleanup", "rbpbench.coordinates.execution_sources",
    "rbpbench.coordinates.runner", "rbpbench.coordinates.derive_reference",
    "rbpbench.splits.runner", "rbpbench.splits.runner_002c", "rbpbench.splits.legacy_diagnostic",
    "rbpbench.splits.portable_002c3", "rbpbench.models", "rbpbench.baselines",
)


class BundleError(IntegrityStop):
    """The bundle is incomplete, drifted, tampered, or unreviewed."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def source_closure(src_root: Path) -> list[str]:
    """Package-relative paths of every ``rbpbench`` module imported by the
    Darwin entrypoint (plus package ``__init__`` files)."""
    src_root = Path(src_root).resolve()
    entrypoint = src_root / "rbpbench" / "splits" / "r3r5" / "darwin.py"
    finder = modulefinder.ModuleFinder(path=[str(src_root)])
    finder.run_script(str(entrypoint))
    # run_script registers the entrypoint itself as ``__main__``; it must ship too.
    files: set[str] = {str(entrypoint.relative_to(src_root))}
    for name, module in finder.modules.items():
        path = getattr(module, "__file__", None)
        if not path:
            continue
        resolved = Path(path).resolve()
        try:
            rel = resolved.relative_to(src_root)
        except ValueError:
            continue
        files.add(str(rel))
    for rel in list(files):
        parent = Path(rel).parent
        while str(parent) not in ("", "."):
            init = parent / "__init__.py"
            if (src_root / init).is_file():
                files.add(str(init))
            parent = parent.parent
    closure = sorted(files)
    for rel in closure:
        dotted = rel[:-3].replace("/", ".")
        if any(dotted == f or dotted.startswith(f + ".") for f in FORBIDDEN_MODULE_FRAGMENTS):
            raise BundleError(f"forbidden module {dotted} entered the R3–R5 import closure")
    return closure


def inventory(root: Path) -> list[dict]:
    root = Path(root)
    entries = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED and not (rel_dir == Path(".") and d in RUNTIME_OWNED))
        for d in list(dirnames):
            if (Path(dirpath) / d).is_symlink():
                raise BundleError(f"symlinked directory in bundle: {rel_dir / d}")
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = str(path.relative_to(root))
            if name in _IGNORED or name.endswith((".pyc", ".pyo")) or rel in {str(MANIFEST_REL), str(MANIFEST_HASH_REL)}:
                continue
            if path.is_symlink():
                raise BundleError(f"symlink in bundle: {rel}")
            entries.append({"path": rel, "byte_size": path.stat().st_size, "sha256": sha256_file(path)})
    return entries


def verify_bundle(root: Path, *, contract: Contract | None = None) -> dict:
    root = Path(root).resolve()
    manifest_path, hash_path = root / MANIFEST_REL, root / MANIFEST_HASH_REL
    if not manifest_path.is_file() or not hash_path.is_file():
        raise BundleError("bundle input manifest or its SHA-256 sidecar is missing")
    token = hash_path.read_text().split()
    actual = sha256_file(manifest_path)
    if not token or token[0] != actual:
        raise BundleError("bundle input manifest does not match its SHA-256 sidecar")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("checkpoint") != CHECKPOINT:
        raise BundleError("bundle manifest is not an R3–R5 manifest")
    listed = {e["path"]: e for e in manifest["entries"]}
    current = {e["path"]: e for e in inventory(root)}
    unlisted = sorted(set(current) - set(listed))
    missing = sorted(set(listed) - set(current))
    changed = sorted(p for p in set(listed) & set(current) if listed[p] != current[p])
    if unlisted or missing or changed:
        raise BundleError(f"bundle drift: unlisted {unlisted[:5]}, missing {missing[:5]}, changed {changed[:5]}")
    contract = contract or load_production_contract(root / CONFIG_REL)
    for spec in contract.inputs:
        entry = listed.get(spec.path)
        if entry is None or entry["sha256"] != spec.sha256 or (spec.byte_size is not None and entry["byte_size"] != spec.byte_size):
            raise BundleError(f"frozen input {spec.role} is absent or differs from the reviewed contract")
    return {"manifest_sha256": actual, "entry_count": len(listed), "source_commit": manifest.get("source_commit")}


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if done.returncode:
        raise BundleError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout.strip()


def build_bundle(repo: Path, destination: Path, sources: Mapping[str, Path], *, contract: Contract = PRODUCTION,
                 require_clean: bool = True, config_source: Path | None = None) -> dict:
    """Builds the immutable bundle; refuses missing, extra, drifted, or unreviewed inputs."""
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    if destination.exists():
        raise BundleError(f"destination already exists: {destination}")
    if require_clean and _git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise BundleError("source worktree has tracked changes; commit before building")
    commit = _git(repo, "rev-parse", "HEAD")
    config_source = Path(config_source) if config_source else repo / CONFIG_REL
    if contract.mode == "production":
        load_production_contract(config_source)
    roles = set(sources)
    unknown = sorted(roles - {spec.role for spec in contract.inputs})
    missing = sorted({spec.role for spec in contract.inputs} - roles)
    if unknown:
        raise BundleError(f"unreviewed/extra input roles supplied: {unknown}")
    if missing:
        raise BundleError(f"required frozen inputs missing: {missing}")
    if contract.mode == "production" and {spec.role for spec in contract.inputs} != REQUIRED_INPUT_ROLES:
        raise BundleError("production contract input roles differ from the reviewed set")
    for spec in contract.inputs:
        source = Path(sources[spec.role])
        if not source.is_file():
            raise BundleError(f"input {spec.role} is not a file: {source}")
        size = source.stat().st_size
        if spec.byte_size is not None and size != spec.byte_size:
            raise BundleError(f"input {spec.role} has {size} bytes; the reviewed contract requires {spec.byte_size}")
        digest = sha256_file(source)
        if digest != spec.sha256:
            raise BundleError(f"input {spec.role} hashes to {digest}; the reviewed contract requires {spec.sha256}")
    closure = source_closure(repo / "src")
    destination.mkdir(parents=True)
    try:
        for rel in closure:
            target = destination / "src" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / "src" / rel, target)
        shutil.copytree(repo / HPC_REL, destination / HPC_REL,
                        ignore=lambda _d, names: {n for n in names if n in _IGNORED or n.endswith((".pyc", ".pyo"))})
        for script in (destination / HPC_REL).iterdir():
            if script.suffix in {".sh", ".sbatch"}:
                script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        shutil.copy2(destination / HPC_REL / "README_DARWIN.md", destination / "README_DARWIN.md")
        (destination / CONFIG_REL).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_source, destination / CONFIG_REL)
        for spec in contract.inputs:
            target = destination / spec.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sources[spec.role], target)
        (destination / "SOURCE_COMMIT.txt").write_text(commit + "\n")
        summary = {"checkpoint": CHECKPOINT, "source_commit": commit, "created_at_utc": _now(),
                   "contract_sha256": contract.content_hash, "source_closure": closure,
                   "entrypoint": "hpc/darwin/002c_r3r5/02_SUBMIT_R3R5.sh", "gpu_required": False,
                   "stages": "E0-E8 only; no baseline/model/coordinate/network stage"}
        (destination / "BUNDLE_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        manifest = {"schema_version": 1, "checkpoint": CHECKPOINT, "source_commit": commit, "entries": inventory(destination)}
        (destination / MANIFEST_REL).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        (destination / MANIFEST_HASH_REL).write_text(f"{sha256_file(destination / MANIFEST_REL)}  {MANIFEST_REL.name}\n")
        verified = verify_bundle(destination, contract=contract)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {"bundle": str(destination), "source_commit": commit, **verified, "source_closure_count": len(closure)}


def archive_bundle(bundle: Path) -> dict:
    bundle = Path(bundle).resolve()
    output = bundle.parent / (bundle.name + ".tar.gz")
    sidecar = Path(str(output) + ".sha256")
    if output.exists() or sidecar.exists():
        raise BundleError("archive or sidecar already exists")
    expected = {e["path"]: e for e in inventory(bundle)}
    for name in (MANIFEST_REL, MANIFEST_HASH_REL):
        path = bundle / name
        expected[str(name)] = {"path": str(name), "byte_size": path.stat().st_size, "sha256": sha256_file(path)}
    with tarfile.open(output, "x:gz") as handle:
        handle.add(bundle, arcname=bundle.name)
    seen = set()
    with tarfile.open(output, "r:gz") as handle:
        for member in handle.getmembers():
            if member.isdir():
                continue
            prefix = bundle.name + "/"
            if not member.name.startswith(prefix) or not member.isfile():
                raise BundleError(f"unexpected archive member {member.name}")
            rel = member.name[len(prefix):]
            entry = expected.get(rel)
            if entry is None or rel in seen:
                raise BundleError(f"unexpected or duplicate archive member {rel}")
            digest = hashlib.sha256(handle.extractfile(member).read()).hexdigest()
            if member.size != entry["byte_size"] or digest != entry["sha256"]:
                raise BundleError(f"archive member {rel} differs from the bundle")
            seen.add(rel)
    if seen != set(expected):
        raise BundleError(f"archive lacks members {sorted(set(expected) - seen)[:5]}")
    digest = sha256_file(output)
    sidecar.write_text(f"{digest}  {output.name}\n")
    return {"archive": str(output), "sha256": digest, "byte_size": output.stat().st_size, "members": len(seen)}


__all__ = ["MANIFEST_REL", "MANIFEST_HASH_REL", "BundleError", "source_closure", "inventory", "verify_bundle",
           "build_bundle", "archive_bundle", "FORBIDDEN_MODULE_FRAGMENTS", "HPC_REL"]
