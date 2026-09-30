"""One-shot portable execution for Task 002C-3 and conditional 002C-4.

This module is the only launcher used on the high-memory Apple-Silicon host.
It verifies the immutable handoff inventory, runs three width probes and all
18 directed cross-partition MMseqs2 searches sequentially, stops on the first
operational or scientific failure, finalizes only after every search reports
zero hits, independently reconciles the final membership, and always attempts
to create a small drag-and-drop return package.

It never downloads software, changes a scientific flag, retries a failed
stage, deletes an accepted generation, or copies the raw CSV/FASTA/MMseqs2
databases into the return package.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from rbpbench.coordinates.diskbudget import snapshot
from rbpbench.coordinates.preflight import detect_available_memory_gib, detect_physical_ram_gib
from rbpbench.data.audit import sha256_file
from rbpbench.splits import restart
from rbpbench.splits.mmseqs_audit import ORDERED_PARTITION_PAIRS, probe_selection_key, selection_key
from rbpbench.splits.runner_002c import MMSEQS2_ARM64_NATIVE_SHA256


CONFIG_REL = Path("configs/splits/sequence_partitions_002c_v1.toml")
OUTPUT_REL = Path("artifacts/splits/sequence_partitions_002c_v1")
DECODE_REL = Path("artifacts/splits/sequence_partitions_v1/decode/generations/decode_907eac7a0a69415a")
DECODE_MANIFEST_REL = Path("manifests/sequence_decode_002b2.json")
CLUSTER_EVIDENCE_REL = Path("artifacts/teammate_run_results/20260928T091014Z_87391_arm64")
RUNTIME_REL = Path(".runtime/rbpbench-splits-002c-arm64")
MMSEQS_REL = RUNTIME_REL / "bin/mmseqs"
INPUT_MANIFEST_REL = Path("HANDOFF_INPUT_MANIFEST.json")
INPUT_MANIFEST_HASH_REL = Path("HANDOFF_INPUT_MANIFEST.sha256")
EXPECTED_ROW_COUNT = 361_180
EXPECTED_COMPONENT_COUNT = 173_465
EXPECTED_PARTITION_COUNTS = {"train": 246_465, "validation": 57_391, "test": 57_324}
WIDTHS = (500, 251, 101)


class PortableHandoffError(RuntimeError):
    """A portable-handoff invariant failed before the final result could be accepted."""


class ScientificAuditFailure(PortableHandoffError):
    """A directed audit found at least one qualifying cross-partition hit."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_host_slug() -> str:
    value = platform.node() or "unknown-host"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:80]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(tmp, path)


def _append_log(path: Path, message: str) -> None:
    line = f"[{_utc_now()}] {message}"
    print(line, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(line + "\n")


def _read_expected_manifest_hash(root: Path) -> str:
    hash_path = root / INPUT_MANIFEST_HASH_REL
    if not hash_path.is_file():
        raise PortableHandoffError(f"missing {INPUT_MANIFEST_HASH_REL}")
    token = hash_path.read_text().strip().split()
    if not token or not re.fullmatch(r"[0-9a-f]{64}", token[0]):
        raise PortableHandoffError(f"{INPUT_MANIFEST_HASH_REL} does not contain a valid SHA-256")
    return token[0]


def verify_handoff_inputs(root: Path) -> dict:
    """Verify every immutable file/symlink listed by the bundle builder."""
    root = Path(root).resolve()
    manifest_path = root / INPUT_MANIFEST_REL
    if not manifest_path.is_file():
        raise PortableHandoffError(f"missing {INPUT_MANIFEST_REL}")
    expected_manifest_hash = _read_expected_manifest_hash(root)
    actual_manifest_hash = sha256_file(manifest_path)
    if actual_manifest_hash != expected_manifest_hash:
        raise PortableHandoffError(
            f"{INPUT_MANIFEST_REL} hashes to {actual_manifest_hash}, expected {expected_manifest_hash}"
        )

    manifest = json.loads(manifest_path.read_text())
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise PortableHandoffError("handoff input manifest has no entries")

    total_bytes = 0
    for entry in entries:
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative:
            raise PortableHandoffError(f"invalid manifest entry path: {entry!r}")
        candidate = (root / relative).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError:
            raise PortableHandoffError(f"manifest path escapes the bundle root: {relative!r}") from None

        kind = entry.get("type")
        lexical_path = root / relative
        if kind == "symlink":
            if not lexical_path.is_symlink():
                raise PortableHandoffError(f"expected symlink is missing or changed: {relative}")
            actual_target = os.readlink(lexical_path)
            if actual_target != entry.get("target"):
                raise PortableHandoffError(
                    f"symlink {relative} targets {actual_target!r}, expected {entry.get('target')!r}"
                )
            continue
        if kind != "file":
            raise PortableHandoffError(f"unsupported input-manifest entry type {kind!r} for {relative}")
        if not lexical_path.is_file() or lexical_path.is_symlink():
            raise PortableHandoffError(f"required regular file is missing or changed to a symlink: {relative}")
        actual_size = lexical_path.stat().st_size
        if actual_size != entry.get("byte_size"):
            raise PortableHandoffError(
                f"{relative} is {actual_size} bytes, expected {entry.get('byte_size')}"
            )
        actual_hash = sha256_file(lexical_path)
        if actual_hash != entry.get("sha256"):
            raise PortableHandoffError(
                f"{relative} hashes to {actual_hash}, expected {entry.get('sha256')}"
            )
        total_bytes += actual_size
    return {
        "manifest_sha256": actual_manifest_hash,
        "entry_count": len(entries),
        "regular_file_bytes": total_bytes,
        "source_commit": manifest.get("source_commit"),
    }


def _assert_bundle_runtime(root: Path) -> dict:
    if platform.system() != "Darwin":
        raise PortableHandoffError(f"this handoff requires macOS; detected {platform.system()!r}")
    machine = platform.machine().lower()
    if machine not in {"arm64", "aarch64"}:
        raise PortableHandoffError(f"this handoff requires native Apple Silicon; detected {machine!r}")

    expected_python = (root / RUNTIME_REL / "bin/python").resolve()
    actual_python = Path(sys.executable).resolve()
    if actual_python != expected_python:
        raise PortableHandoffError(
            f"launcher must use the bundled Python at {expected_python}; current interpreter is {actual_python}"
        )

    mmseqs_path = root / MMSEQS_REL
    if not mmseqs_path.is_file() or not os.access(mmseqs_path, os.X_OK):
        raise PortableHandoffError(f"bundled MMseqs2 executable is missing or not executable at {mmseqs_path}")
    mmseqs_hash = sha256_file(mmseqs_path)
    if mmseqs_hash != MMSEQS2_ARM64_NATIVE_SHA256:
        raise PortableHandoffError(
            f"bundled MMseqs2 hashes to {mmseqs_hash}, expected native arm64 hash {MMSEQS2_ARM64_NATIVE_SHA256}"
        )
    version = subprocess.run(
        [str(mmseqs_path), "version"], capture_output=True, text=True, timeout=30, check=False
    )
    if version.returncode != 0 or version.stdout.strip() != "18.8cc5c":
        raise PortableHandoffError(
            f"bundled MMseqs2 version check failed: exit={version.returncode}, "
            f"stdout={version.stdout.strip()!r}, stderr={version.stderr.strip()!r}"
        )

    physical = detect_physical_ram_gib()
    available = detect_available_memory_gib()
    disk = snapshot(root)
    if physical is None or physical < 16.0:
        raise PortableHandoffError(f"installed RAM {physical!r} GiB is below the frozen 16-GiB minimum")
    if available is None or available < 10.0:
        raise PortableHandoffError(f"available RAM {available!r} GiB is below the frozen 10-GiB launch gate")
    if disk.free_gib < 80.0:
        raise PortableHandoffError(f"free disk {disk.free_gib:.2f} GiB is below the frozen 80-GiB floor")

    probe = root / ".handoff_write_probe"
    if probe.exists():
        raise PortableHandoffError(f"refusing to overwrite unexpected write probe at {probe}")
    probe.write_text("write-ok\n")
    probe.unlink()

    active = subprocess.run(["pgrep", "-x", "mmseqs"], capture_output=True, text=True, check=False)
    if active.returncode == 0 and active.stdout.strip():
        raise PortableHandoffError(
            f"another MMseqs2 process is already running (PID(s): {active.stdout.strip()}); no stage was launched"
        )

    return {
        "system": platform.system(),
        "machine": machine,
        "host": platform.node(),
        "python_version": platform.python_version(),
        "python_executable": str(actual_python),
        "mmseqs_path": str(mmseqs_path),
        "mmseqs_version": version.stdout.strip(),
        "mmseqs_sha256": mmseqs_hash,
        "physical_ram_gib": physical,
        "available_ram_gib": available,
        "free_disk_gib": disk.free_gib,
    }


def _runner_base(root: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "rbpbench.splits.runner_002c",
        "--config",
        str(root / CONFIG_REL),
        "--repo-root",
        str(root),
        "--output-dir",
        str(root / OUTPUT_REL),
    ]


def _stage_command(root: Path, *, stage: str, width: int | None = None, query: str | None = None, target: str | None = None) -> list[str]:
    command = _runner_base(root) + ["--stage", stage]
    if stage in {"audit_probe", "audit_search"}:
        command += [
            "--width",
            str(width),
            "--decode-fasta-dir",
            str(root / DECODE_REL),
            "--decode-manifest",
            str(root / DECODE_MANIFEST_REL),
            "--mmseqs-bin",
            str(root / MMSEQS_REL),
            "--authorize-mmseqs",
        ]
    if stage == "audit_search":
        command += ["--query-partition", str(query), "--target-partition", str(target)]
    if stage == "finalize":
        command += ["--cluster-evidence-root", str(root / CLUSTER_EVIDENCE_REL)]
    return command


def _run_stage(root: Path, log_dir: Path, *, index: int, stage: str, width: int | None = None, query: str | None = None, target: str | None = None) -> dict:
    label_parts = [stage]
    if width is not None:
        label_parts.append(str(width))
    if query is not None and target is not None:
        label_parts.append(f"{query}_to_{target}")
    label = "_".join(label_parts)
    command = _stage_command(root, stage=stage, width=width, query=query, target=target)
    stdout_path = log_dir / f"{index:02d}_{label}.stdout.log"
    stderr_path = log_dir / f"{index:02d}_{label}.stderr.log"
    meta_path = log_dir / f"{index:02d}_{label}.meta.json"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONNOUSERSITE"] = "1"
    env["PATH"] = str(root / RUNTIME_REL / "bin") + os.pathsep + env.get("PATH", "")
    started_at = _utc_now()
    start = time.monotonic()
    with stdout_path.open("w") as out_handle, stderr_path.open("w") as err_handle:
        completed = subprocess.run(command, cwd=root, env=env, stdout=out_handle, stderr=err_handle, text=True, check=False)
    elapsed = time.monotonic() - start
    meta = {
        "stage": stage,
        "width": width,
        "query_partition": query,
        "target_partition": target,
        "command": command,
        "started_at_utc": started_at,
        "finished_at_utc": _utc_now(),
        "elapsed_seconds": elapsed,
        "exit_code": completed.returncode,
        "stdout_path": str(stdout_path.relative_to(root)),
        "stderr_path": str(stderr_path.relative_to(root)),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
    }
    _write_json(meta_path, meta)
    if completed.returncode != 0:
        tail = stderr_path.read_text(errors="replace")[-4000:]
        raise PortableHandoffError(
            f"{label} exited {completed.returncode}; no retry was attempted. Last stderr bytes:\n{tail}"
        )
    try:
        result = json.loads(stdout_path.read_text())
    except Exception as exc:
        raise PortableHandoffError(f"{label} returned non-JSON stdout: {exc}") from exc
    if not result.get("executed"):
        raise PortableHandoffError(f"{label} did not return executed=true: {result}")
    if stage == "audit_search":
        hit_count = result.get("hit_count")
        if result.get("passed") is not True or hit_count != 0:
            raise ScientificAuditFailure(
                f"{label} found {hit_count!r} qualifying cross-partition hit(s); later searches and finalize were not run"
            )
    return {"label": label, "result": result, "meta": meta}


def _decompressed_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_final_result(root: Path) -> dict:
    output_dir = root / OUTPUT_REL
    final_record = restart.require_accepted(output_dir, "finalize")
    membership_path = Path(final_record["membership_path"])
    manifest_path = Path(final_record["manifest_path"])
    if not membership_path.is_absolute():
        membership_path = root / membership_path
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path

    assign_record = restart.require_accepted(output_dir, "assign")
    assign_membership = Path(assign_record["membership_path"])
    if not assign_membership.is_absolute():
        assign_membership = root / assign_membership
    final_uncompressed_hash = _decompressed_sha256(membership_path)
    assign_uncompressed_hash = _decompressed_sha256(assign_membership)
    if final_uncompressed_hash != assign_uncompressed_hash:
        raise PortableHandoffError("final membership differs from the accepted assignment after decompression")

    seen_ids: set[str] = set()
    component_partitions: dict[str, str] = {}
    partition_counts = {"train": 0, "validation": 0, "test": 0}
    with gzip.open(membership_path, "rt") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        if header != ["sample_id", "component_id", "partition"]:
            raise PortableHandoffError(f"unexpected final membership header: {header!r}")
        for line_number, raw_line in enumerate(handle, start=2):
            fields = raw_line.rstrip("\n").split("\t")
            if len(fields) != 3:
                raise PortableHandoffError(f"malformed final membership line {line_number}")
            sample_id, component_id, partition = fields
            if sample_id in seen_ids:
                raise PortableHandoffError(f"duplicate final sample ID {sample_id!r}")
            seen_ids.add(sample_id)
            if partition not in partition_counts:
                raise PortableHandoffError(f"unexpected partition {partition!r}")
            partition_counts[partition] += 1
            prior = component_partitions.setdefault(component_id, partition)
            if prior != partition:
                raise PortableHandoffError(f"component {component_id!r} spans {prior!r} and {partition!r}")
    if len(seen_ids) != EXPECTED_ROW_COUNT:
        raise PortableHandoffError(f"final membership has {len(seen_ids)} rows, expected {EXPECTED_ROW_COUNT}")
    expected_ids = {f"row_{i}" for i in range(EXPECTED_ROW_COUNT)}
    if seen_ids != expected_ids:
        raise PortableHandoffError("final membership does not contain the exact canonical row_0..row_361179 universe")
    if len(component_partitions) != EXPECTED_COMPONENT_COUNT:
        raise PortableHandoffError(
            f"final membership has {len(component_partitions)} components, expected {EXPECTED_COMPONENT_COUNT}"
        )
    if partition_counts != EXPECTED_PARTITION_COUNTS:
        raise PortableHandoffError(
            f"final partition counts {partition_counts} differ from accepted assignment {EXPECTED_PARTITION_COUNTS}"
        )

    manifest = json.loads(manifest_path.read_text())
    search_summary = manifest.get("audit_search_summary", {})
    probe_summary = manifest.get("audit_probe_summary", {})
    if len(search_summary) != 18 or any(
        entry.get("passed") is not True or entry.get("hit_count") != 0 for entry in search_summary.values()
    ):
        raise PortableHandoffError("final manifest does not contain exactly 18 passing zero-hit directed searches")
    if len(probe_summary) != 3:
        raise PortableHandoffError("final manifest does not contain exactly three width probes")
    if manifest.get("partition_row_counts") != EXPECTED_PARTITION_COUNTS:
        raise PortableHandoffError("final manifest partition counts disagree with the accepted assignment")
    if not manifest.get("minimum_count_report", {}).get("passed", False):
        raise PortableHandoffError("final manifest reports an evaluation-floor failure")

    return {
        "membership_path": str(membership_path),
        "membership_byte_size": membership_path.stat().st_size,
        "membership_sha256": sha256_file(membership_path),
        "membership_decompressed_sha256": final_uncompressed_hash,
        "manifest_path": str(manifest_path),
        "manifest_byte_size": manifest_path.stat().st_size,
        "manifest_sha256": sha256_file(manifest_path),
        "row_count": len(seen_ids),
        "component_count": len(component_partitions),
        "partition_row_counts": partition_counts,
        "probe_count": len(probe_summary),
        "directed_search_count": len(search_summary),
        "directed_search_total_hits": sum(entry["hit_count"] for entry in search_summary.values()),
    }


def _copy_if_file(source: Path, destination: Path) -> None:
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _inventory_files(root: Path, *, excluded_names: frozenset[str] = frozenset()) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in excluded_names:
            entries.append({
                "path": str(path.relative_to(root)),
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return entries


def package_return(
    root: Path,
    *,
    status: str,
    started_at_utc: str,
    input_verification: dict | None,
    host_preflight: dict | None,
    stage_results: list[dict],
    final_verification: dict | None,
    failure: dict | None,
    execution_log_dir: Path,
) -> tuple[Path, Path]:
    return_parent = root / "return"
    return_parent.mkdir(parents=True, exist_ok=True)
    return_dir = return_parent / f"RBP_002C3_RETURN_{_timestamp_slug()}_{_safe_host_slug()}"
    counter = 1
    while return_dir.exists():
        return_dir = return_parent / f"RBP_002C3_RETURN_{_timestamp_slug()}_{_safe_host_slug()}_{counter}"
        counter += 1
    return_dir.mkdir(parents=True)

    status_payload = {
        "schema_version": 1,
        "checkpoint": "002C-3-and-conditional-002C-4",
        "status": status,
        "started_at_utc": started_at_utc,
        "finished_at_utc": _utc_now(),
        "input_verification": input_verification,
        "host_preflight": host_preflight,
        "completed_stage_labels": [entry["label"] for entry in stage_results],
        "completed_stage_count": len(stage_results),
        "final_verification": final_verification,
        "failure": failure,
        "raw_csv_fastas_and_mmseqs_databases_in_return": False,
        "working_tree_retained_in_bundle": True,
    }
    _write_json(return_dir / "STATUS.json", status_payload)

    summary_lines = [
        "# Task 002C-3/4 portable return",
        "",
        f"- Status: **{status}**",
        f"- Started: `{started_at_utc}`",
        f"- Finished: `{status_payload['finished_at_utc']}`",
        f"- Completed stages: {len(stage_results)}",
    ]
    if final_verification is not None:
        summary_lines += [
            f"- Final rows: {final_verification['row_count']:,}",
            f"- Final components: {final_verification['component_count']:,}",
            f"- Directed searches: {final_verification['directed_search_count']} (total qualifying hits: "
            f"{final_verification['directed_search_total_hits']})",
            f"- Partition counts: `{final_verification['partition_row_counts']}`",
        ]
    if failure is not None:
        summary_lines += ["", "## Stop reason", "", f"`{failure['type']}: {failure['message']}`"]
    summary_lines += [
        "",
        "The return intentionally excludes the raw dataset, decoded FASTAs, and MMseqs2 databases. "
        "Those remain inside the working bundle for follow-up only if review requests them.",
    ]
    (return_dir / "RETURN_SUMMARY.md").write_text("\n".join(summary_lines) + "\n")

    selected_dir = root / OUTPUT_REL / "selected"
    if selected_dir.is_dir():
        for path in sorted(selected_dir.glob("*.json")):
            _copy_if_file(path, return_dir / "selected_records" / path.name)

    for report in sorted((root / OUTPUT_REL).glob("audit_probe/*/generations/*/audit_probe_report.json")):
        width = report.parts[-4]
        _copy_if_file(report, return_dir / "audit_reports" / f"audit_probe_{width}.json")
    for report in sorted((root / OUTPUT_REL).glob("audit_search/*/*/generations/*/audit_search_report.json")):
        width = report.parts[-5]
        direction = report.parts[-4]
        _copy_if_file(report, return_dir / "audit_reports" / f"audit_search_{width}_{direction}.json")

    if execution_log_dir.is_dir():
        for path in sorted(execution_log_dir.rglob("*")):
            if path.is_file():
                _copy_if_file(path, return_dir / "execution_logs" / path.relative_to(execution_log_dir))
    for path in sorted((root / OUTPUT_REL).glob("audit_*/*/**/logs/*.log")):
        if path.is_file():
            _copy_if_file(path, return_dir / "tool_logs" / path.relative_to(root / OUTPUT_REL))

    environment = {
        "host_preflight": host_preflight,
        "python_runtime_relative_path": str(RUNTIME_REL),
        "mmseqs_relative_path": str(MMSEQS_REL),
        "source_commit": input_verification.get("source_commit") if input_verification else None,
        "input_manifest_sha256": input_verification.get("manifest_sha256") if input_verification else None,
    }
    _write_json(return_dir / "environment" / "execution_environment.json", environment)
    _copy_if_file(root / "SOURCE_COMMIT.txt", return_dir / "environment" / "SOURCE_COMMIT.txt")
    _copy_if_file(root / INPUT_MANIFEST_REL, return_dir / "environment" / INPUT_MANIFEST_REL.name)

    if final_verification is not None:
        final_membership = Path(final_verification["membership_path"])
        final_manifest = Path(final_verification["manifest_path"])
        _copy_if_file(final_membership, return_dir / "final" / "sequence_partitions_v1.tsv.gz")
        _copy_if_file(final_manifest, return_dir / "final" / "sequence_partitions_v1.json")
        _copy_if_file(
            root / OUTPUT_REL / "selected/finalize.json",
            return_dir / "final" / "finalize_selection_record.json",
        )

    return_manifest = {
        "schema_version": 1,
        "checkpoint": "002C-3-and-conditional-002C-4",
        "status": status,
        "status_sha256": sha256_file(return_dir / "STATUS.json"),
        "summary_sha256": sha256_file(return_dir / "RETURN_SUMMARY.md"),
        "completed_stages": [
            {
                "label": entry["label"],
                "stage": entry["result"].get("stage"),
                "width": entry["result"].get("width"),
                "query_partition": entry["result"].get("query_partition"),
                "target_partition": entry["result"].get("target_partition"),
                "generation_digest": entry["result"].get("generation_digest"),
                "passed": entry["result"].get("passed"),
                "hit_count": entry["result"].get("hit_count"),
            }
            for entry in stage_results
        ],
        "final_verification": final_verification,
        "failure": failure,
    }
    _write_json(return_dir / "RETURN_MANIFEST.json", return_manifest)

    inventory = _inventory_files(
        return_dir,
        excluded_names=frozenset({"RETURN_INVENTORY.json", "CHECKSUMS.sha256"}),
    )
    _write_json(return_dir / "RETURN_INVENTORY.json", inventory)
    checksum_entries = _inventory_files(return_dir, excluded_names=frozenset({"CHECKSUMS.sha256"}))
    (return_dir / "CHECKSUMS.sha256").write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in checksum_entries)
    )

    archive_base = return_parent / return_dir.name
    archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=return_parent, base_dir=return_dir.name))
    return return_dir, archive_path


def execute(root: Path) -> tuple[int, Path | None, Path | None]:
    root = Path(root).resolve()
    # Accepted 002C selection records intentionally store repository-relative
    # generation/input paths.  Anchor those paths to the portable project
    # root regardless of where the wrapper itself was launched from.
    os.chdir(root)
    started = _utc_now()
    attempt_dir = root / "execution_logs" / f"002c3_002c4_{_timestamp_slug()}"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    orchestrator_log = attempt_dir / "orchestrator.log"
    input_verification: dict | None = None
    host_preflight: dict | None = None
    stage_results: list[dict] = []
    final_verification: dict | None = None
    failure: dict | None = None
    status = "STOPPED"

    try:
        _append_log(orchestrator_log, "verifying immutable handoff inventory")
        input_verification = verify_handoff_inputs(root)
        _append_log(
            orchestrator_log,
            f"verified {input_verification['entry_count']} inputs ({input_verification['regular_file_bytes']} bytes)",
        )
        _append_log(orchestrator_log, "checking native runtime and frozen resource gates")
        host_preflight = _assert_bundle_runtime(root)
        _write_json(attempt_dir / "host_preflight.json", host_preflight)
        _append_log(
            orchestrator_log,
            f"preflight passed: available RAM {host_preflight['available_ram_gib']:.2f} GiB, "
            f"free disk {host_preflight['free_disk_gib']:.2f} GiB",
        )

        stage_index = 1
        for width in WIDTHS:
            _append_log(orchestrator_log, f"starting width-scoped resource probe {width}")
            result = _run_stage(root, attempt_dir, index=stage_index, stage="audit_probe", width=width)
            stage_results.append(result)
            stage_index += 1
            _append_log(orchestrator_log, f"accepted resource probe {width}")

        for width in WIDTHS:
            for query, target in ORDERED_PARTITION_PAIRS:
                _append_log(orchestrator_log, f"starting directed audit {width}: {query}->{target}")
                result = _run_stage(
                    root,
                    attempt_dir,
                    index=stage_index,
                    stage="audit_search",
                    width=width,
                    query=query,
                    target=target,
                )
                stage_results.append(result)
                stage_index += 1
                _append_log(orchestrator_log, f"accepted zero-hit directed audit {width}: {query}->{target}")

        _append_log(orchestrator_log, "all 18 directed searches passed; starting conditional finalization")
        result = _run_stage(root, attempt_dir, index=stage_index, stage="finalize")
        stage_results.append(result)
        _append_log(orchestrator_log, "independently reconciling final membership and manifest")
        final_verification = verify_final_result(root)
        _write_json(attempt_dir / "independent_final_verification.json", final_verification)
        status = "SUCCESS"
        _append_log(orchestrator_log, "Task 002C-3 and conditional 002C-4 completed successfully")
    except BaseException as exc:
        failure = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        _write_json(attempt_dir / "failure.json", failure)
        _append_log(orchestrator_log, f"STOPPED without retry: {type(exc).__name__}: {exc}")

    return_dir: Path | None = None
    archive_path: Path | None = None
    try:
        _append_log(orchestrator_log, f"creating clean {status} return package")
        return_dir, archive_path = package_return(
            root,
            status=status,
            started_at_utc=started,
            input_verification=input_verification,
            host_preflight=host_preflight,
            stage_results=stage_results,
            final_verification=final_verification,
            failure=failure,
            execution_log_dir=attempt_dir,
        )
        _append_log(orchestrator_log, f"return directory: {return_dir}")
        _append_log(orchestrator_log, f"return archive: {archive_path}")
    except BaseException as package_exc:
        _append_log(orchestrator_log, f"return packaging also failed: {type(package_exc).__name__}: {package_exc}")
        if failure is None:
            failure = {"type": type(package_exc).__name__, "message": str(package_exc)}
        status = "STOPPED"

    return (0 if status == "SUCCESS" else 1), return_dir, archive_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    exit_code, return_dir, archive_path = execute(args.bundle_root)
    print(json.dumps({
        "exit_code": exit_code,
        "return_dir": str(return_dir) if return_dir else None,
        "return_archive": str(archive_path) if archive_path else None,
    }, indent=2, sort_keys=True))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
