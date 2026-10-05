"""Portable launcher for Task 002C-R2: the guarded direct-search RESOURCE probe.

Runs exactly the three fixed probe stages (``probe_500``, ``probe_251``,
``probe_101``) through :func:`rbpbench.splits.resource_probe_r2.run_probe`
on the collaborator's native Apple-Silicon Mac. It verifies the bundle's
immutable inventory BEFORE it opens any FASTA or launches any tool, stops
at the first failure without retry, and always attempts one small
checksum-complete SUCCESS/STOPPED return ZIP.

Boundary: no direct-edge writer, components-v2, assignment, audit, R3
module is imported or callable from here, and the CLI exposes no stage
selector. A SUCCESS return is resource evidence only and is NOT
authorization for R3. This module is deliberately separate from
``portable_002c3`` (the Task 002C-3/4 launcher).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from rbpbench.coordinates.diskbudget import snapshot
from rbpbench.coordinates.preflight import detect_available_memory_gib, detect_physical_ram_gib
from rbpbench.coordinates.provenance import BinaryProvenance
from rbpbench.splits import resource_probe_r2 as probe

CHECKPOINT = "002C-R2P"
INPUT_MANIFEST_REL = Path("R2_INPUT_MANIFEST.json")
INPUT_MANIFEST_HASH_REL = Path("R2_INPUT_MANIFEST.sha256")
CONFIG_REL = Path("R2_PACKAGE_CONFIG.json")
DECODE_MANIFEST_REL = Path("manifests/sequence_decode_002b2.json")
RUNTIME_MANIFEST_REL = Path("manifests/runtime_manifest.json")
ENVIRONMENT_LOCK_REL = Path("manifests/runtime_environment_lock.explicit.txt")
FASTA_DIR_REL = Path("data/decode")
RUNTIME_REL = Path(".runtime/rbpbench-splits-002c-arm64")
MMSEQS_REL = RUNTIME_REL / "bin/mmseqs"
OUTPUT_REL = Path("r2_output")
RETURN_PARENT_REL = Path("return")
LOG_PARENT_REL = Path("execution_logs")
WIDTHS = (500, 251, 101)
# Frozen native arm64 MMseqs2 (same value as Task 002C's accepted runner;
# duplicated, never imported, so this launcher cannot reach audit code).
FROZEN_ARM64_MMSEQS_SHA256 = "3fa397a9af5f8142ab8df13cc3e19b3aefc91cb9908d9c147883c8ac4162db0d"
FROZEN_MMSEQS_VERSION = "18.8cc5c"
FROZEN_SAMPLE_SIZE = probe.PROBE_QUERY_COUNT
MIN_INSTALLED_RAM_GIB = 64.0
MIN_AVAILABLE_RAM_GIB = 24.0
MIN_FREE_DISK_GIB = 100.0
_IGNORED_NAMES = frozenset({"__pycache__", ".DS_Store"})
_RAW_SEQUENCE_RE = re.compile(r"[ACGT]{40,}")
_MAX_RETURN_FILE_BYTES = 64 * 1024 * 1024
_FORBIDDEN_RETURN_SUFFIXES = (".fasta", ".fa", ".tsv", ".csv", ".dbtype", ".index", ".lookup", ".gz", ".pth")


class PortableR2Error(RuntimeError):
    """A package/launcher invariant failed; always a final stop."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_host_slug() -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", platform.node() or "unknown-host")[:80]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(tmp, path)


def _append_log(path: Path | None, message: str) -> None:
    line = f"[{_utc_now()}] {message}"
    print(line, flush=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(line + "\n")


# ------------------------------------------------------------- inventory


def inventory_tree(root: Path, *, excluded: frozenset[str]) -> list[dict]:
    """Every regular file and every symlink (including symlinked
    directories, which are never descended) under ``root``, sorted by path.
    Shared by the builder and the launcher so both mean the same thing."""
    root = Path(root)
    entries: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in list(dirnames):
            path = Path(dirpath) / name
            if name in _IGNORED_NAMES:
                dirnames.remove(name)
            elif path.is_symlink():
                dirnames.remove(name)
                entries.append({"path": str(path.relative_to(root)), "type": "symlink", "target": os.readlink(path)})
        for name in sorted(filenames):
            path = Path(dirpath) / name
            relative = str(path.relative_to(root))
            if relative in excluded or name in _IGNORED_NAMES or name.endswith((".pyc", ".pyo")):
                continue
            if path.is_symlink():
                entries.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
            elif path.is_file():
                entries.append({"path": relative, "type": "file", "byte_size": path.stat().st_size, "sha256": sha256_file(path)})
            else:
                raise PortableR2Error(f"unsupported filesystem object in bundle: {path}")
    return sorted(entries, key=lambda e: e["path"])


_MANIFEST_FILES = frozenset({str(INPUT_MANIFEST_REL), str(INPUT_MANIFEST_HASH_REL)})


def verify_inventory(root: Path) -> dict:
    """Verifies the bundle against its pinned manifest: manifest hash, every
    listed file's size/SHA-256 and symlink target, and that NO unlisted
    file/symlink exists (so an added file is tampering too). Returns the
    verified path->sha256 map so later steps never re-hash large files."""
    root = Path(root).resolve()
    manifest_path = root / INPUT_MANIFEST_REL
    hash_path = root / INPUT_MANIFEST_HASH_REL
    if not manifest_path.is_file() or not hash_path.is_file():
        raise PortableR2Error("missing input manifest or its hash file")
    token = hash_path.read_text().split()
    if not token or not re.fullmatch(r"[0-9a-f]{64}", token[0]):
        raise PortableR2Error("input manifest hash file does not hold a SHA-256")
    actual_manifest = sha256_file(manifest_path)
    if actual_manifest != token[0]:
        raise PortableR2Error(f"input manifest hashes to {actual_manifest}, expected {token[0]}")
    manifest = json.loads(manifest_path.read_text())
    entries = manifest.get("entries")
    if manifest.get("checkpoint") != CHECKPOINT or not isinstance(entries, list) or not entries:
        raise PortableR2Error("input manifest is not a non-empty R2 package manifest")
    listed: set[str] = set()
    hashes: dict[str, str] = {}
    by_path: dict[str, dict] = {}
    for entry in entries:
        rel = entry.get("path")
        if not isinstance(rel, str) or not rel:
            raise PortableR2Error(f"invalid manifest entry: {entry!r}")
        if rel in listed:
            raise PortableR2Error(f"duplicate manifest entry: {rel}")
        listed.add(rel)
        by_path[rel] = entry
        lexical = root / rel
        try:
            (root / rel).resolve(strict=False).relative_to(root)
        except ValueError:
            if entry.get("type") != "symlink" or Path(rel).parts[:1] != (RUNTIME_REL.parts[0],):
                raise PortableR2Error(f"manifest path escapes the bundle: {rel!r}") from None
        kind = entry.get("type")
        if kind == "symlink":
            if not lexical.is_symlink() or os.readlink(lexical) != entry.get("target"):
                raise PortableR2Error(f"symlink missing or changed: {rel}")
        elif kind == "file":
            if not lexical.is_file() or lexical.is_symlink():
                raise PortableR2Error(f"regular file missing or replaced: {rel}")
            if lexical.stat().st_size != entry.get("byte_size"):
                raise PortableR2Error(f"{rel} size changed")
            digest = sha256_file(lexical)
            if digest != entry.get("sha256"):
                raise PortableR2Error(f"{rel} hashes to {digest}, expected {entry.get('sha256')}")
            hashes[rel] = digest
        else:
            raise PortableR2Error(f"unsupported manifest entry type {kind!r}: {rel}")
    actual: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in sorted(dirnames) if d not in _IGNORED_NAMES]
        for name in list(dirnames):
            if (Path(dirpath) / name).is_symlink():
                dirnames.remove(name)
                actual.add(str((Path(dirpath) / name).relative_to(root)))
        for name in filenames:
            rel = str((Path(dirpath) / name).relative_to(root))
            if name in _IGNORED_NAMES or name.endswith((".pyc", ".pyo")) or rel in _MANIFEST_FILES:
                continue
            actual.add(rel)
    unlisted = sorted(actual - listed)
    if unlisted:
        raise PortableR2Error(f"{len(unlisted)} unlisted file(s) in the bundle (reused or tampered?): {unlisted[:5]}")
    return {
        "manifest_sha256": actual_manifest,
        "entry_count": len(entries),
        "source_commit": manifest.get("source_commit"),
        "hashes": hashes,
        "entries": by_path,
    }


# -------------------------------------------------------------- host/gates


def _default_mmseqs_version(path: Path) -> str | None:
    try:
        done = subprocess.run([str(path), "version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _default_running_mmseqs() -> str:
    done = subprocess.run(["pgrep", "-x", "mmseqs"], capture_output=True, text=True, check=False)
    return done.stdout.strip() if done.returncode == 0 else ""


@dataclass
class HostChecks:
    """Injectable host facts/frozen constants. Production defaults only;
    tests substitute a fake host and a fake (never real) tool."""

    system: Callable[[], str] = platform.system
    machine: Callable[[], str] = platform.machine
    python_executable: Callable[[], str] = lambda: sys.executable
    installed_ram_gib: Callable[[], float | None] = detect_physical_ram_gib
    available_ram_gib: Callable[[], float | None] = detect_available_memory_gib
    free_disk_gib: Callable[[Path], float] = lambda p: snapshot(p).free_gib
    mmseqs_version: Callable[[Path], str | None] = _default_mmseqs_version
    running_mmseqs: Callable[[], str] = _default_running_mmseqs
    frozen_mmseqs_sha256: str = FROZEN_ARM64_MMSEQS_SHA256
    frozen_mmseqs_version: str = FROZEN_MMSEQS_VERSION
    frozen_sample_size: int = FROZEN_SAMPLE_SIZE
    monitors: probe.ResourceMonitors | None = None
    limits: probe.ProbeLimits = field(default_factory=probe.ProbeLimits)
    poll_interval: float = 1.0


def load_package_config(root: Path, checks: HostChecks) -> dict:
    config = json.loads((Path(root) / CONFIG_REL).read_text())
    required = {"schema_version", "checkpoint", "seed", "decode_manifest_sha256", "expected_mmseqs_sha256",
                "expected_mmseqs_version", "sample_size", "expected_row_count", "runtime_manifest_sha256",
                "environment_lock_sha256"}
    if required - set(config) or config["checkpoint"] != CHECKPOINT:
        raise PortableR2Error("package config is incomplete or not an R2 config")
    if config["expected_mmseqs_sha256"] != checks.frozen_mmseqs_sha256 or config["expected_mmseqs_version"] != checks.frozen_mmseqs_version:
        raise PortableR2Error("package config does not carry the frozen native arm64 MMseqs2 hash/version")
    if config["sample_size"] != checks.frozen_sample_size:
        raise PortableR2Error(f"package config sample size {config['sample_size']!r} is not the frozen {checks.frozen_sample_size}")
    if not isinstance(config["seed"], int):
        raise PortableR2Error("package config seed must be an integer")
    return config


def check_host_and_runtime(root: Path, checks: HostChecks, config: Mapping) -> dict:
    root = Path(root).resolve()
    if checks.system() != "Darwin":
        raise PortableR2Error(f"requires macOS; detected {checks.system()!r}")
    machine = checks.machine().lower()
    if machine not in {"arm64", "aarch64"}:
        raise PortableR2Error(f"requires native Apple Silicon (no Rosetta); detected {machine!r}")
    expected_python = (root / RUNTIME_REL / "bin/python").resolve()
    actual_python = Path(checks.python_executable()).resolve()
    if actual_python != expected_python:
        raise PortableR2Error(f"must run under the bundled Python {expected_python}; running {actual_python}")
    mmseqs = root / MMSEQS_REL
    if not mmseqs.is_file() or not os.access(mmseqs, os.X_OK):
        raise PortableR2Error(f"bundled MMseqs2 missing or not executable: {mmseqs}")
    digest = sha256_file(mmseqs)
    if digest != checks.frozen_mmseqs_sha256:
        raise PortableR2Error(f"bundled MMseqs2 hashes to {digest}, expected frozen {checks.frozen_mmseqs_sha256}")
    version = checks.mmseqs_version(mmseqs)
    if version != checks.frozen_mmseqs_version:
        raise PortableR2Error(f"bundled MMseqs2 version {version!r} != {checks.frozen_mmseqs_version!r}")
    running = checks.running_mmseqs()
    if running:
        raise PortableR2Error(f"another MMseqs2 process is running (PID(s) {running}); nothing launched")
    installed, available = checks.installed_ram_gib(), checks.available_ram_gib()
    free = checks.free_disk_gib(root)
    if installed is None or installed < MIN_INSTALLED_RAM_GIB:
        raise PortableR2Error(f"installed RAM {installed!r} GiB below {MIN_INSTALLED_RAM_GIB} (None fails)")
    if available is None or available < MIN_AVAILABLE_RAM_GIB:
        raise PortableR2Error(f"available RAM {available!r} GiB below {MIN_AVAILABLE_RAM_GIB} (None fails)")
    if free is None or free < MIN_FREE_DISK_GIB:
        raise PortableR2Error(f"free disk {free!r} GiB below {MIN_FREE_DISK_GIB}")
    return {
        "system": checks.system(), "machine": machine, "host": platform.node(),
        "python_executable": str(actual_python), "mmseqs_path": str(mmseqs), "mmseqs_version": version,
        "mmseqs_sha256": digest, "installed_ram_gib": installed, "available_ram_gib": available,
        "free_disk_gib": free,
    }


def bind_runtime_provenance(root: Path, config: Mapping, verified: Mapping) -> dict:
    """Surfaces and re-checks the runtime provenance recorded at build time:
    the bundled expected-runtime manifest and environment lock must hash to the
    values in the (inventory-bound) package config, and every runtime file and
    symlink the manifest lists must match the inventory-verified bundle entry.
    """
    hashes, entries = verified["hashes"], verified["entries"]
    if hashes.get(str(RUNTIME_MANIFEST_REL)) != config["runtime_manifest_sha256"]:
        raise PortableR2Error("bundled runtime manifest does not match the recorded expected-runtime-manifest SHA-256")
    if hashes.get(str(ENVIRONMENT_LOCK_REL)) != config["environment_lock_sha256"]:
        raise PortableR2Error("bundled environment lock does not match its recorded SHA-256")
    manifest = json.loads((Path(root) / RUNTIME_MANIFEST_REL).read_text())
    count = 0
    for entry in manifest.get("entries", []):
        rel = str(RUNTIME_REL / entry["path"])
        actual = entries.get(rel)
        if actual is None or actual["type"] != entry["type"]:
            raise PortableR2Error(f"runtime manifest entry is missing or retyped in the bundle: {rel}")
        if entry["type"] == "file" and (actual["sha256"], actual["byte_size"]) != (entry["sha256"], entry["byte_size"]):
            raise PortableR2Error(f"runtime file differs from the expected runtime manifest: {rel}")
        if entry["type"] == "symlink" and actual["target"] != entry["target"]:
            raise PortableR2Error(f"runtime symlink differs from the expected runtime manifest: {rel}")
        count += 1
    bundled = sum(1 for rel in entries if rel.startswith(str(RUNTIME_REL) + "/"))
    if bundled != count:
        raise PortableR2Error(f"bundle holds {bundled} runtime entries but the expected runtime manifest lists {count}")
    return {
        "expected_runtime_manifest_sha256": config["runtime_manifest_sha256"],
        "environment_lock_sha256": config["environment_lock_sha256"],
        "runtime_manifest_entry_count": count,
    }


_FASTA_RE = re.compile(r"sequence_partitions_width_(\d+)\.fasta$")


def bind_decode_manifest_and_fastas(root: Path, config: Mapping, verified_hashes: Mapping[str, str]) -> dict[int, Path]:
    """Binds the bundled decode manifest and the three FASTAs to the accepted
    decode evidence by hash/size, using the inventory-verified hashes (no
    FASTA is opened)."""
    root = Path(root).resolve()
    manifest_rel = str(DECODE_MANIFEST_REL)
    if verified_hashes.get(manifest_rel) != config["decode_manifest_sha256"]:
        raise PortableR2Error("bundled decode manifest does not match the pinned accepted SHA-256")
    data = json.loads((root / DECODE_MANIFEST_REL).read_text())
    evidence = {}
    for entry in data.get("retained_artifacts", []):
        m = _FASTA_RE.search(entry.get("path", ""))
        if m:
            evidence[int(m.group(1))] = entry
    paths: dict[int, Path] = {}
    for width in WIDTHS:
        rel = FASTA_DIR_REL / f"sequence_partitions_width_{width}.fasta"
        entry = evidence.get(width)
        if entry is None:
            raise PortableR2Error(f"decode manifest has no accepted entry for width {width}")
        path = root / rel
        if not path.is_file() or path.stat().st_size != entry["byte_size"] or verified_hashes.get(str(rel)) != entry["sha256"]:
            raise PortableR2Error(f"{rel} does not match the accepted decode evidence for width {width}")
        paths[width] = path
    return paths


def load_universe(fasta_500: Path, *, expected_rows: int) -> list[str]:
    """Canonical IDs = the headers of the manifest-bound 500-nt FASTA."""
    ids: list[str] = []
    with Path(fasta_500).open() as handle:
        for line in handle:
            if line.startswith(">"):
                ids.append(line[1:].strip())
    probe.validate_canonical_ids(ids, what="500-nt FASTA headers")
    if len(ids) != expected_rows:
        raise PortableR2Error(f"FASTA has {len(ids)} records, expected {expected_rows}")
    return ids


# --------------------------------------------------------- return package


def _inventory_files(root: Path, *, excluded_names: frozenset[str] = frozenset()) -> list[dict]:
    return [
        {"path": str(p.relative_to(root)), "byte_size": p.stat().st_size, "sha256": sha256_file(p)}
        for p in sorted(Path(root).rglob("*"))
        if p.is_file() and p.name not in excluded_names
    ]


def assert_return_clean(return_dir: Path) -> None:
    """Final guard: no raw sequence runs, FASTA/TSV/database/CSV/archive
    files, or oversized files may exist in the return directory."""
    for path in sorted(Path(return_dir).rglob("*")):
        if not path.is_file():
            continue
        if path.name.lower().endswith(_FORBIDDEN_RETURN_SUFFIXES):
            raise PortableR2Error(f"forbidden file type in return: {path.name}")
        if path.stat().st_size > _MAX_RETURN_FILE_BYTES:
            raise PortableR2Error(f"oversized file in return: {path.name}")
        if _RAW_SEQUENCE_RE.search(path.read_text(errors="replace")):
            raise PortableR2Error(f"raw sequence-like content in return file: {path.name}")


def _copy_if_file(source: Path, destination: Path) -> None:
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def package_return(
    root: Path, *, status: str, started_at_utc: str, input_verification: dict | None, host_preflight: dict | None,
    probe_summary: dict | None, failure: dict | None, log_dir: Path | None,
    runtime_provenance: dict | None = None,
) -> tuple[Path, Path, str]:
    """Returns ``(return_dir, archive, effective_status)``. If the sanitation
    guard trips, the full return is discarded, a minimal STATUS-only return
    is written, and the effective status is forced to ``STOPPED`` (the
    evidence cannot be safely returned, so the checkpoint cannot be accepted)."""
    root = Path(root)
    original_status = status
    parent = root / RETURN_PARENT_REL
    parent.mkdir(parents=True, exist_ok=True)
    name = f"RBP_002C_R2_RETURN_{_timestamp_slug()}_{_safe_host_slug()}"
    return_dir, counter = parent / name, 1
    while return_dir.exists():
        return_dir, counter = parent / f"{name}_{counter}", counter + 1

    def build(full: bool) -> None:
        return_dir.mkdir(parents=True)
        _write_json(return_dir / "STATUS.json", {
            "schema_version": 1, "checkpoint": CHECKPOINT, "status": status, "started_at_utc": started_at_utc,
            "finished_at_utc": _utc_now(), "failure": failure, "minimal_return": not full,
            "input_verification": None if input_verification is None else {k: v for k, v in input_verification.items() if k not in ("hashes", "entries")},
            "host_preflight": host_preflight,
            "runtime_provenance": runtime_provenance,
            "raw_fastas_databases_and_result_tsvs_in_return": False,
            "r3_authorization": "NOT GRANTED: a resource probe never authorizes R3",
        })
        summary = ["# Task 002C-R2 resource-probe return", "", f"- Status: **{status}**",
                   f"- Started: `{started_at_utc}`", "",
                   "A SUCCESS resource probe is evidence only. It is **not** authorization for R3 full edge discovery.",
                   "Raw FASTAs, MMseqs2 databases and result TSVs are excluded; their path/size/SHA-256 are recorded."]
        if failure:
            summary += ["", "## Stop reason", "", f"`{failure['type']}: {failure['message']}`"]
        (return_dir / "RETURN_SUMMARY.md").write_text("\n".join(summary) + "\n")
        if full and probe_summary is not None:
            _write_json(return_dir / "probe_summary.json", probe_summary)
            out = root / OUTPUT_REL
            for file in sorted((out / "selected").glob("*.json")) if (out / "selected").is_dir() else []:
                _copy_if_file(file, return_dir / "selected_records" / file.name)
            for file in ("selection.json", "stopped.json", "summary.json"):
                _copy_if_file(out / file, return_dir / "probe" / file)
            for log in sorted(out.glob("generations/*/logs/*.log")) if out.is_dir() else []:
                _copy_if_file(log, return_dir / "tool_logs" / log.relative_to(out / "generations"))
            if log_dir is not None and log_dir.is_dir():
                for file in sorted(log_dir.rglob("*")):
                    if file.is_file():
                        _copy_if_file(file, return_dir / "execution_logs" / file.relative_to(log_dir))
            _copy_if_file(root / "SOURCE_COMMIT.txt", return_dir / "environment" / "SOURCE_COMMIT.txt")
            _copy_if_file(root / INPUT_MANIFEST_REL, return_dir / "environment" / INPUT_MANIFEST_REL.name)
        _write_json(return_dir / "RETURN_MANIFEST.json", {
            "schema_version": 1, "checkpoint": CHECKPOINT, "status": status,
            "status_sha256": sha256_file(return_dir / "STATUS.json"),
            "summary_sha256": sha256_file(return_dir / "RETURN_SUMMARY.md"),
            "selection_digest": ((probe_summary or {}).get("selection") or {}).get("digest"),
            "failure": failure,
        })
        _write_json(return_dir / "RETURN_INVENTORY.json",
                    _inventory_files(return_dir, excluded_names=frozenset({"RETURN_INVENTORY.json", "CHECKSUMS.sha256"})))
        entries = _inventory_files(return_dir, excluded_names=frozenset({"CHECKSUMS.sha256"}))
        (return_dir / "CHECKSUMS.sha256").write_text("".join(f"{e['sha256']}  {e['path']}\n" for e in entries))

    build(full=True)
    try:
        assert_return_clean(return_dir)
    except PortableR2Error as exc:
        shutil.rmtree(return_dir)
        status = "STOPPED"
        failure = failure or {"type": "PortableR2Error", "message": f"return sanitation failed: {exc}"}
        failure = {**failure, "return_guard": str(exc), "status_before_return_guard": original_status}
        build(full=False)  # minimal STATUS-only return; never ship the offending content
    archive = Path(shutil.make_archive(str(parent / return_dir.name), "zip", root_dir=parent, base_dir=return_dir.name))
    (parent / (archive.name + ".sha256")).write_text(f"{sha256_file(archive)}  {archive.name}\n")
    return return_dir, archive, status


# ------------------------------------------------------------------ main


def execute(root: Path, checks: HostChecks | None = None) -> tuple[int, Path | None, Path | None]:
    """The single entry: verify inventory -> host/runtime -> manifest-bound
    FASTAs -> resources/output root -> fixed three-stage probe -> return
    package. Any failure is final (no retry, no later width)."""
    checks = checks or HostChecks()
    root = Path(root).resolve()
    started = _utc_now()
    status, failure = "STOPPED", None
    input_verification = host_preflight = probe_summary = runtime_provenance = None
    log_dir: Path | None = None
    orchestrator_log: Path | None = None
    try:
        for rel in (OUTPUT_REL, RETURN_PARENT_REL, LOG_PARENT_REL):
            if (root / rel).exists():
                raise PortableR2Error(f"{rel} already exists: this package is single-use; refusing to reuse it")
        _append_log(None, "verifying immutable package inventory before opening any FASTA")
        input_verification = verify_inventory(root)
        config = load_package_config(root, checks)
        runtime_provenance = bind_runtime_provenance(root, config, input_verification)
        log_dir = root / LOG_PARENT_REL / f"002c_r2_{_timestamp_slug()}"
        log_dir.mkdir(parents=True)
        orchestrator_log = log_dir / "orchestrator.log"
        _append_log(orchestrator_log, f"verified {input_verification['entry_count']} inventory entries")
        host_preflight = check_host_and_runtime(root, checks, config)
        _write_json(log_dir / "host_preflight.json", host_preflight)
        fasta_paths = bind_decode_manifest_and_fastas(root, config, input_verification["hashes"])
        universe = load_universe(fasta_paths[500], expected_rows=config["expected_row_count"])
        _append_log(orchestrator_log, "preflight passed; starting fixed stages " + ", ".join(probe.PROBE_STAGES))
        mmseqs = root / MMSEQS_REL
        binary = BinaryProvenance(
            exe_name="mmseqs", resolved_path=str(mmseqs), sha256=host_preflight["mmseqs_sha256"],
            version=host_preflight["mmseqs_version"],
        )
        probe.run_probe(
            root / OUTPUT_REL, fasta_paths=fasta_paths, universe=universe, seed=config["seed"], mmseqs_bin=str(mmseqs),
            binary=binary, monitors=checks.monitors, limits=checks.limits, sample_size=config["sample_size"],
            poll_interval=checks.poll_interval,
        )
        status = "SUCCESS"
        _append_log(orchestrator_log, "all three resource probes passed; STOP (R3 is not authorized)")
    except BaseException as exc:
        failure = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        if log_dir is not None:
            _write_json(log_dir / "failure.json", failure)
        _append_log(orchestrator_log, f"STOPPED without retry: {type(exc).__name__}: {exc}")

    return_dir = archive = None
    try:
        out = root / OUTPUT_REL
        if out.is_dir():
            probe_summary = probe.build_return_summary(out)
        return_dir, archive, effective = package_return(
            root, status=status, started_at_utc=started, input_verification=input_verification,
            host_preflight=host_preflight, probe_summary=probe_summary, failure=failure, log_dir=log_dir,
            runtime_provenance=runtime_provenance,
        )
        if effective != status:
            status = effective
            _append_log(orchestrator_log, "return sanitation fallback: effective status forced to STOPPED")
        _append_log(orchestrator_log, f"return archive: {archive}")
    except BaseException as package_exc:
        _append_log(orchestrator_log, f"return packaging failed: {type(package_exc).__name__}: {package_exc}")
        status = "STOPPED"
    return (0 if status == "SUCCESS" else 1), return_dir, archive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    code, return_dir, archive = execute(args.bundle_root)
    print(json.dumps({"exit_code": code, "return_dir": str(return_dir) if return_dir else None,
                      "return_archive": str(archive) if archive else None}, indent=2, sort_keys=True))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
