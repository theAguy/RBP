"""Task 002B restart-safe runner: ``preflight``, ``decode``, ``probe``,
``cluster``, and ``component_report`` stages.

Checkpoint 002B-1 (``docs/handoffs/002b1_orchestration_claude_handoff.md``)
authorizes ONLY this orchestration code and tiny synthetic-fixture tests: no
real dataset access, no real MMseqs2 execution over real sequences, and no
partition assignment happen anywhere in this module. Every stage that may
launch MMseqs2 requires explicit ``--authorize-mmseqs``, ``--dry-run`` is
checked before any subprocess or declared-real-input file is opened, exactly
one stage runs per invocation (no ``all``), and a stage never silently
continues into the next one -- each writes its own atomic selection record
under ``<output-dir>/selected/`` and the CLI simply refuses to run a
downstream stage whose upstream record is missing or invalid.

Mirrors ``rbpbench.coordinates.runner``'s transactional-generation/fingerprint
pattern (immutable ``generations/<prefix>_<uuid>`` directories, a
declared-inputs fingerprint recomputed fresh on every invocation so a changed
config/input/tool automatically invalidates a restart skip, and an
accepted-record re-hash before ever trusting a skip) without duplicating its
multi-build machinery, which Task 002 does not need.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Sequence

from rbpbench.coordinates.decode import fasta_record
from rbpbench.coordinates.hashing import content_fingerprint, label_blind_rank
from rbpbench.coordinates.preflight import detect_available_memory_gib
from rbpbench.coordinates.provenance import (
    current_git_commit,
    host_memory_snapshot,
    peak_rss_kib_of_children,
)
from rbpbench.data.audit import sha256_file
from rbpbench.coordinates.diskbudget import snapshot
from rbpbench.splits import audit as splits_audit
from rbpbench.splits import commands as splits_commands
from rbpbench.splits import components as splits_components
from rbpbench.splits import decode as splits_decode
from rbpbench.splits import hashing as splits_hashing
from rbpbench.splits import membership as splits_membership
from rbpbench.splits import output as splits_output
from rbpbench.splits.config import SplitsConfig, load_config

STAGES: tuple[str, ...] = ("preflight", "decode", "probe", "cluster", "component_report")
WIDTH_SCOPED_STAGES: tuple[str, ...] = ("probe", "cluster")
MMSEQS_STAGES: tuple[str, ...] = ("probe", "cluster")
PROTECTED_WIDTHS: tuple[int, ...] = (500, 251, 101)

DEFAULT_CONFIG_PATH = Path("configs/splits/sequence_partitions_v1.toml")
DEFAULT_OUTPUT_DIR = Path("artifacts/splits/sequence_partitions_v1")


class StageValidationError(ValueError):
    """A stage/argument combination is invalid (unknown stage/width, a width
    given for a non-width-scoped stage, or a required width missing) --
    raised before any subprocess or file access.
    """


class AuthorizationError(RuntimeError):
    """``--authorize-mmseqs`` was not given for a stage that may launch
    MMseqs2. Checked before any subprocess or declared-real-input access.
    """


class PriorStageNotAcceptedError(RuntimeError):
    """A required upstream stage has no accepted, currently-intact selection
    record. Never silently runs the upstream stage on this stage's behalf --
    each checkpoint stage must be separately invoked and accepted.
    """


class ResourceGateExceededError(RuntimeError):
    """A resource ceiling/floor was crossed; the candidate generation for
    this attempt is discarded and any prior accepted selection is untouched.
    """


class ReproducibilityError(RuntimeError):
    """Recomputing a result under a reordered/reshuffled input did not
    reproduce the first computation byte-for-byte.
    """


class PreflightError(RuntimeError):
    """A frozen input hash/size, environment, or resource check failed."""


# --------------------------------------------------------------------------
# Small generic helpers: atomic JSON I/O, restart-state, directory sizing.
# --------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_path, path)


def _load_json(path: Path) -> dict | None:
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _load_state(output_dir: Path) -> dict:
    state = _load_json(output_dir / "state.json")
    if state is None:
        return {"schema_version": 1, "stage_fingerprints": {}}
    state.setdefault("stage_fingerprints", {})
    return state


def _save_state(output_dir: Path, state: dict) -> None:
    _atomic_write_json(output_dir / "state.json", state)


def _stage_is_valid(state: dict, key: str, fingerprint: str) -> bool:
    return state.get("stage_fingerprints", {}).get(key) == fingerprint


def _mark_stage_complete(state: dict, key: str, fingerprint: str) -> None:
    state.setdefault("stage_fingerprints", {})[key] = fingerprint


def _selected_record_path(output_dir: Path, key: str) -> Path:
    return output_dir / "selected" / f"{key}.json"


def _verify_generation_intact(record: dict | None) -> bool:
    """Re-hashes every file the record's own ``artifacts`` mapping names,
    rather than trusting a matching fingerprint alone: a fingerprint only
    proves the DECLARED INPUTS haven't changed, not that the accepted output
    generation directory itself is still intact (not deleted, truncated, or
    corrupted since acceptance).
    """
    if record is None:
        return False
    for rel_path, expected_sha256 in record.get("artifacts", {}).items():
        path = Path(rel_path)
        if not path.is_file() or sha256_file(path) != expected_sha256:
            return False
    return True


def _directory_size_bytes(root: Path) -> int:
    root = Path(root)
    if not root.exists():
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            candidate = Path(dirpath) / name
            if candidate.is_file():
                total += candidate.stat().st_size
    return total


def _resolve(base: Path, maybe_relative: str) -> Path:
    candidate = Path(maybe_relative)
    return candidate if candidate.is_absolute() else Path(base) / candidate


def _read_fasta(path: Path) -> dict[str, str]:
    sequences: dict[str, str] = {}
    current_id: str | None = None
    chunks: list[str] = []
    with Path(path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if line.startswith(">"):
                if current_id is not None:
                    sequences[current_id] = "".join(chunks)
                current_id = line[1:].strip()
                chunks = []
            else:
                chunks.append(line)
        if current_id is not None:
            sequences[current_id] = "".join(chunks)
    return sequences


def _write_fasta(sequences: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w") as handle:
        for sample_id in sorted(sequences):
            handle.write(fasta_record(sample_id, sequences[sample_id]))


def _nearest_existing_ancestor(path: Path) -> Path:
    current = Path(path)
    for _ in range(64):
        if current.exists():
            return current
        if current.parent == current:
            return current
        current = current.parent
    return current


def _check_free_disk_or_fail(*, disk_path: Path, min_free_disk_gib: float, label: str) -> dict:
    current = snapshot(_nearest_existing_ancestor(disk_path))
    if current.free_gib < min_free_disk_gib:
        raise ResourceGateExceededError(
            f"free disk is {current.free_gib:.2f} GiB before {label!r}, below the required "
            f"{min_free_disk_gib:.2f} GiB floor"
        )
    return current.to_dict()


def _check_combined_ceiling_or_discard(
    *, output_dir: Path, generation_dir: Path, max_new_disk_gib: float
) -> dict:
    """Full candidate-directory disk monitoring (not only stdout/stderr):
    measures the WHOLE ``output_dir`` tree (every accepted plus this
    candidate generation) against the combined ceiling, and discards the
    just-produced candidate generation before raising when it is crossed --
    a prior accepted generation, living in its own directory, is untouched.
    """
    total_gib = _directory_size_bytes(output_dir) / (1024**3)
    if total_gib > max_new_disk_gib:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise ResourceGateExceededError(
            f"combined Task 002 artifact directory reached {total_gib:.2f} GiB, over the "
            f"{max_new_disk_gib:.2f} GiB ceiling; candidate generation {generation_dir} discarded"
        )
    return {"combined_output_gib": total_gib}


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------


def stage_preflight(
    *,
    config: SplitsConfig,
    dataset_csv: Path,
    output_dir: Path,
    mmseqs_bin: str = "mmseqs",
    dry_run: bool = False,
) -> dict:
    cwd = Path.cwd()
    audit_json = _resolve(cwd, config.dataset.audit_json_path)
    proteins_tsv = _resolve(cwd, config.dataset.proteins_tsv_path)

    if dry_run:
        return {
            "dry_run": True,
            "stage": "preflight",
            "would_check": {
                "dataset_csv": str(dataset_csv),
                "audit_json": str(audit_json),
                "proteins_tsv": str(proteins_tsv),
                "mmseqs_bin": mmseqs_bin,
                "min_free_disk_gib": config.resources.min_free_disk_gib,
            },
        }

    problems: list[str] = []
    hashes: dict[str, str] = {}
    for label, path, expected_sha256 in (
        ("dataset_csv", dataset_csv, config.dataset.csv_sha256),
        ("audit_json", audit_json, config.dataset.audit_json_sha256),
        ("proteins_tsv", proteins_tsv, config.dataset.proteins_tsv_sha256),
    ):
        if not Path(path).is_file():
            problems.append(f"{label} not found at {path}")
            continue
        actual = sha256_file(Path(path))
        hashes[label] = actual
        if actual != expected_sha256:
            problems.append(f"{label} at {path} has SHA-256 {actual}, expected {expected_sha256}")

    if Path(dataset_csv).is_file() and Path(dataset_csv).stat().st_size != config.dataset.csv_byte_size:
        problems.append(
            f"dataset_csv byte size {Path(dataset_csv).stat().st_size} != expected {config.dataset.csv_byte_size}"
        )

    binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    if binary.resolved_path is None:
        problems.append(f"mmseqs binary {mmseqs_bin!r} not found on PATH")
    elif binary.version != splits_commands.PINNED_VERSION:
        problems.append(f"mmseqs version {binary.version!r} != pinned {splits_commands.PINNED_VERSION!r}")

    disk_snapshot = _check_free_disk_or_fail(
        disk_path=output_dir, min_free_disk_gib=config.resources.min_free_disk_gib, label="preflight"
    )

    if problems:
        raise PreflightError("; ".join(problems))

    record = {
        "stage": "preflight",
        "executed": True,
        "git_commit": current_git_commit(cwd=cwd),
        "config_hash": config.content_hash,
        "input_hashes": hashes,
        "binary": binary.to_dict(),
        "host_memory": host_memory_snapshot(),
        "disk_snapshot": disk_snapshot,
        "artifacts": {},
    }
    _atomic_write_json(_selected_record_path(output_dir, "preflight"), record)
    return record


def preflight_fingerprint(*, config: SplitsConfig, dataset_csv: Path, mmseqs_bin: str) -> str:
    """Recomputed FRESH on every invocation (re-hashing the current on-disk
    files) so a changed CSV/audit/proteins file, or a different resolved
    binary, always invalidates a restart skip -- never trusted from a cached
    prior value.
    """
    cwd = Path.cwd()
    parts: list[str] = ["preflight", config.content_hash, str(dataset_csv), mmseqs_bin]
    for path in (dataset_csv, _resolve(cwd, config.dataset.audit_json_path), _resolve(cwd, config.dataset.proteins_tsv_path)):
        parts.append(sha256_file(Path(path)) if Path(path).is_file() else "MISSING")
    binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    parts.append(binary.sha256 or "MISSING")
    return content_fingerprint(*parts)


# --------------------------------------------------------------------------
# decode
# --------------------------------------------------------------------------


def stage_decode(
    *,
    config: SplitsConfig,
    dataset_csv: Path,
    output_dir: Path,
    preflight_record: dict,
    dry_run: bool = False,
) -> dict:
    if dry_run:
        return {"dry_run": True, "stage": "decode", "would_decode": str(dataset_csv)}

    base_dir = output_dir / "decode"
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix="decode")

    report = splits_decode.stream_decode_to_fastas(
        Path(dataset_csv), generation_dir, widths=config.protected_widths
    )

    if report.total_rows != config.dataset.expected_row_count:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise PreflightError(
            f"decoded {report.total_rows} rows, expected exactly {config.dataset.expected_row_count}"
        )

    artifacts: dict[str, str] = {}
    duplicate_edge_paths: dict[int, str] = {}
    duplicate_summary: dict[str, dict] = {}
    for width, fasta_path in report.output_paths.items():
        artifacts[str(fasta_path)] = sha256_file(fasta_path)
        sequences = _read_fasta(fasta_path)
        edges = splits_hashing.duplicate_edges(sequences)
        groups = splits_hashing.group_by_canonical_hash(sequences)
        edges_path = generation_dir / f"duplicate_edges_{width}.json"
        edges_path.write_text(json.dumps(edges))
        artifacts[str(edges_path)] = sha256_file(edges_path)
        duplicate_edge_paths[width] = str(edges_path)
        group_sizes = sorted((len(ids) for ids in groups.values()), reverse=True)
        duplicate_summary[str(width)] = {
            "duplicate_group_count": sum(1 for size in group_sizes if size > 1),
            "max_duplicate_group_size": group_sizes[0] if group_sizes else 0,
        }

    _check_free_disk_or_fail(disk_path=output_dir, min_free_disk_gib=config.resources.min_free_disk_gib, label="decode")
    _check_combined_ceiling_or_discard(
        output_dir=output_dir, generation_dir=generation_dir, max_new_disk_gib=config.resources.max_new_disk_gib
    )

    generation_digest = content_fingerprint("decode_generation", *sorted(artifacts.items()))
    record = {
        "stage": "decode",
        "executed": True,
        "generation_dir": str(generation_dir),
        "generation_digest": generation_digest,
        "total_rows": report.total_rows,
        "sample_ids": list(report.accepted_sample_ids),
        "fasta_paths": {str(width): str(path) for width, path in report.output_paths.items()},
        "duplicate_edge_paths": {str(width): path for width, path in duplicate_edge_paths.items()},
        "duplicate_edge_summary": duplicate_summary,
        "upstream": {"preflight_fingerprint_source": preflight_record.get("config_hash")},
        "artifacts": artifacts,
    }
    _atomic_write_json(_selected_record_path(output_dir, "decode"), record)
    return record


def decode_fingerprint(*, config: SplitsConfig, dataset_csv: Path, preflight_fp: str) -> str:
    current_sha = sha256_file(Path(dataset_csv)) if Path(dataset_csv).is_file() else "MISSING"
    return content_fingerprint("decode", config.content_hash, str(dataset_csv), current_sha, preflight_fp)


# --------------------------------------------------------------------------
# probe / cluster (share the same underlying MMseqs2 invocation shape)
# --------------------------------------------------------------------------


def _run_width_clustering(
    *, width: int, fasta_path: Path, base_dir: Path, prefix: str, config: SplitsConfig, mmseqs_bin: str
) -> dict:
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix=prefix)
    db_path = generation_dir / "db"
    cluster_prefix = generation_dir / "clu"
    tmp_dir = generation_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    log_dir = generation_dir / "logs"
    timeout_seconds = config.resources.timeout_seconds

    executed: list[dict] = []
    createdb_cmd = splits_commands.createdb_command(fasta_path, db_path, mmseqs_bin=mmseqs_bin)
    executed.append(
        splits_commands.run_mmseqs_command(createdb_cmd, log_dir=log_dir, timeout_seconds=timeout_seconds).to_dict()
    )

    cluster_cmd = splits_commands.with_threads(
        splits_commands.cluster_command(db_path, cluster_prefix, tmp_dir, width=width, mmseqs_bin=mmseqs_bin),
        config.resources.max_threads,
    )
    executed.append(
        splits_commands.run_mmseqs_command(cluster_cmd, log_dir=log_dir, timeout_seconds=timeout_seconds).to_dict()
    )

    membership_tsv = generation_dir / "membership.tsv"
    createtsv_cmd = splits_commands.createtsv_command(db_path, db_path, cluster_prefix, membership_tsv, mmseqs_bin=mmseqs_bin)
    executed.append(
        splits_commands.run_mmseqs_command(createtsv_cmd, log_dir=log_dir, timeout_seconds=timeout_seconds).to_dict()
    )

    return {"generation_dir": generation_dir, "membership_tsv": membership_tsv, "executed": executed}


def _cluster_or_probe(
    *,
    stage_name: str,
    width: int,
    config: SplitsConfig,
    output_dir: Path,
    decode_record: dict,
    authorize: bool,
    mmseqs_bin: str,
    dry_run: bool,
    subset_sample_size: int | None,
    peak_memory_gate_gib: float | None,
    available_memory_gate_gib: float | None,
) -> dict:
    if width not in PROTECTED_WIDTHS:
        raise StageValidationError(f"width {width!r} is not one of the protected widths {PROTECTED_WIDTHS}")

    if dry_run:
        return {"dry_run": True, "stage": stage_name, "width": width, "would_authorize_mmseqs": authorize}

    if not authorize:
        raise AuthorizationError(f"stage {stage_name!r} launches MMseqs2 and requires --authorize-mmseqs")

    fasta_path = Path(decode_record["fasta_paths"][str(width)])
    all_sequences = _read_fasta(fasta_path)

    if subset_sample_size is not None and subset_sample_size < len(all_sequences):
        ranked = sorted(all_sequences, key=lambda sid: (label_blind_rank(config.seed, sid), sid))
        selected_ids = set(ranked[:subset_sample_size])
        sequences = {sid: seq for sid, seq in all_sequences.items() if sid in selected_ids}
    else:
        sequences = all_sequences

    base_dir = output_dir / stage_name / str(width)
    input_fasta = base_dir / "input.fasta.tmp"
    _write_fasta(sequences, input_fasta)

    _check_free_disk_or_fail(disk_path=output_dir, min_free_disk_gib=config.resources.min_free_disk_gib, label=stage_name)

    result = _run_width_clustering(
        width=width, fasta_path=input_fasta, base_dir=base_dir, prefix=stage_name, config=config, mmseqs_bin=mmseqs_bin
    )
    rss_after_kib = peak_rss_kib_of_children()
    generation_dir = result["generation_dir"]

    membership = splits_membership.parse_cluster_tsv(result["membership_tsv"])
    expected_ids = set(sequences)
    splits_membership.reconcile_membership(membership, expected_ids)
    splits_membership.reconcile_representatives(membership, expected_ids)

    try:
        _check_combined_ceiling_or_discard(
            output_dir=output_dir, generation_dir=generation_dir, max_new_disk_gib=config.resources.max_new_disk_gib
        )
        if peak_memory_gate_gib is not None:
            peak_gib = rss_after_kib / (1024**2)
            if peak_gib > peak_memory_gate_gib:
                raise ResourceGateExceededError(
                    f"{stage_name} peak RSS {peak_gib:.2f} GiB exceeded the {peak_memory_gate_gib:.2f} GiB gate"
                )
        if available_memory_gate_gib is not None:
            available_gib = detect_available_memory_gib()
            if available_gib is not None and available_gib < available_memory_gate_gib:
                raise ResourceGateExceededError(
                    f"available memory {available_gib:.2f} GiB fell below the "
                    f"{available_memory_gate_gib:.2f} GiB gate required before the next stage"
                )
    except ResourceGateExceededError:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise

    artifacts = {str(result["membership_tsv"]): sha256_file(result["membership_tsv"])}
    for name, digest in splits_commands.hash_db_files(Path(generation_dir) / "db").items():
        artifacts[str(Path(generation_dir) / name)] = digest

    generation_digest = content_fingerprint(f"{stage_name}_generation", width, *sorted(artifacts.items()))
    record = {
        "stage": stage_name,
        "executed": True,
        "width": width,
        "generation_dir": str(generation_dir),
        "generation_digest": generation_digest,
        "membership_tsv": str(result["membership_tsv"]),
        "sample_count": len(sequences),
        "decode_generation_digest": decode_record.get("generation_digest"),
        "peak_rss_kib_of_children": rss_after_kib,
        "mmseqs_bin": mmseqs_bin,
        "threads": config.resources.max_threads,
        "split_memory_limit": None,
        "tool_provenance": result["executed"],
        "artifacts": artifacts,
    }
    _atomic_write_json(_selected_record_path(output_dir, f"{stage_name}_{width}"), record)
    return record


def stage_probe(
    *, width: int, config: SplitsConfig, output_dir: Path, decode_record: dict, authorize: bool, mmseqs_bin: str = "mmseqs", dry_run: bool = False
) -> dict:
    return _cluster_or_probe(
        stage_name="probe",
        width=width,
        config=config,
        output_dir=output_dir,
        decode_record=decode_record,
        authorize=authorize,
        mmseqs_bin=mmseqs_bin,
        dry_run=dry_run,
        subset_sample_size=config.probe.sample_size,
        peak_memory_gate_gib=config.probe.max_peak_memory_gib,
        available_memory_gate_gib=config.probe.min_available_memory_gib_before_next_stage,
    )


def stage_cluster(
    *, width: int, config: SplitsConfig, output_dir: Path, decode_record: dict, authorize: bool, mmseqs_bin: str = "mmseqs", dry_run: bool = False
) -> dict:
    return _cluster_or_probe(
        stage_name="cluster",
        width=width,
        config=config,
        output_dir=output_dir,
        decode_record=decode_record,
        authorize=authorize,
        mmseqs_bin=mmseqs_bin,
        dry_run=dry_run,
        subset_sample_size=None,
        peak_memory_gate_gib=None,
        available_memory_gate_gib=None,
    )


def width_stage_fingerprint(*, stage_name: str, width: int, config: SplitsConfig, decode_fp: str, mmseqs_bin: str) -> str:
    binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    return content_fingerprint(stage_name, width, config.content_hash, decode_fp, binary.sha256 or "MISSING", mmseqs_bin)


# --------------------------------------------------------------------------
# component_report
# --------------------------------------------------------------------------


def _edges_from_cluster_record(record: dict) -> list[tuple[str, str]]:
    membership = splits_membership.parse_cluster_tsv(Path(record["membership_tsv"]))
    return splits_membership.membership_edges(membership)


def _edges_from_decode_record(decode_record: dict, width: int) -> list[tuple[str, str]]:
    path = Path(decode_record["duplicate_edge_paths"][str(width)])
    raw = json.loads(path.read_text())
    return [tuple(pair) for pair in raw]


def stage_component_report(
    *, config: SplitsConfig, output_dir: Path, decode_record: dict, cluster_records: dict[int, dict], dry_run: bool = False
) -> dict:
    if dry_run:
        return {"dry_run": True, "stage": "component_report"}

    sample_ids = list(decode_record["sample_ids"])
    edge_groups: list[list[tuple[str, str]]] = []
    per_width_contribution: dict[str, int] = {}
    duplicate_edge_summary: dict[str, dict] = decode_record.get("duplicate_edge_summary", {})
    for width in config.protected_widths:
        cluster_edges = _edges_from_cluster_record(cluster_records[width])
        dup_edges = _edges_from_decode_record(decode_record, width)
        edge_groups.append(cluster_edges)
        edge_groups.append(dup_edges)
        per_width_contribution[str(width)] = len(cluster_edges)

    forward_assignment = splits_components.build_components(sample_ids, edge_groups)
    reversed_assignment = splits_components.build_components(
        list(reversed(sample_ids)), [list(reversed(group)) for group in reversed(edge_groups)]
    )
    if forward_assignment != reversed_assignment:
        raise ReproducibilityError(
            "component assignment differs when input row/edge order is reversed -- not reproducible"
        )

    component_sizes = splits_components.component_sizes(forward_assignment)
    total_rows = len(sample_ids)
    gate = splits_audit.giant_component_gate(component_sizes, total_rows)

    membership_rows = [(sample_id, cid) for sample_id, cid in forward_assignment.items()]
    output_path = output_dir / "component_membership.tsv.gz"
    splits_output.write_deterministic_component_membership_gzip(membership_rows, output_path)
    # Reproduce independently and require byte-identical compressed output.
    second_path = output_dir / "component_membership.repeat.tsv.gz.tmp"
    splits_output.write_deterministic_component_membership_gzip(list(reversed(membership_rows)), second_path)
    first_bytes = output_path.read_bytes()
    second_bytes = second_path.read_bytes()
    second_path.unlink(missing_ok=True)
    if first_bytes != second_bytes:
        raise ReproducibilityError("component membership gzip is not byte-identical across reordered reproduction")

    input_hashes = dict(decode_record.get("artifacts", {}))
    report = splits_output.build_component_report(
        total_rows=total_rows,
        component_sizes=component_sizes,
        protected_widths=config.protected_widths,
        giant_component_gate=gate,
        per_width_contribution=per_width_contribution,
        duplicate_edge_summary=duplicate_edge_summary,
        input_hashes=input_hashes,
        config={"seed": config.seed, "protected_widths": list(config.protected_widths)},
        tool_provenance=[entry for record in cluster_records.values() for entry in record.get("tool_provenance", [])],
    )
    manifest_path = output_dir / "component_report.json"
    splits_output.write_manifest_json(report, manifest_path)

    artifacts = {str(output_path): sha256_file(output_path), str(manifest_path): sha256_file(manifest_path)}
    record = {
        "stage": "component_report",
        "executed": True,
        "membership_path": str(output_path),
        "manifest_path": str(manifest_path),
        "component_count": len(component_sizes),
        "giant_component_gate": gate,
        "artifacts": artifacts,
    }
    _atomic_write_json(_selected_record_path(output_dir, "component_report"), record)
    return record


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class _SingleOccurrenceAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(self, f"{option_string} may only be given once")
        setattr(namespace, self.dest, values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=STAGES, action=_SingleOccurrenceAction)
    parser.add_argument("--width", type=int, choices=PROTECTED_WIDTHS, default=None, action=_SingleOccurrenceAction)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--dataset-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mmseqs-bin", default="mmseqs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--authorize-mmseqs", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def _require_prior_stage(output_dir: Path, key: str) -> dict:
    record = _load_json(_selected_record_path(output_dir, key))
    if record is None or not record.get("executed") or not _verify_generation_intact(record):
        raise PriorStageNotAcceptedError(
            f"stage {key!r} has no accepted, currently-intact selection record under {output_dir}/selected/; "
            "run and accept it first"
        )
    return record


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.width is not None and args.stage not in WIDTH_SCOPED_STAGES:
        raise StageValidationError(f"--width is not accepted for stage {args.stage!r}")
    if args.stage in WIDTH_SCOPED_STAGES and args.width is None:
        raise StageValidationError(f"stage {args.stage!r} requires --width")
    if args.stage in MMSEQS_STAGES and not args.authorize_mmseqs and not args.dry_run:
        raise AuthorizationError(f"stage {args.stage!r} launches MMseqs2 and requires --authorize-mmseqs")

    config = load_config(args.config)
    dataset_csv = args.dataset_csv if args.dataset_csv is not None else Path(config.dataset.csv_filename)
    output_dir = args.output_dir
    state = _load_state(output_dir)

    if args.stage == "preflight":
        fingerprint = None if args.dry_run else preflight_fingerprint(config=config, dataset_csv=dataset_csv, mmseqs_bin=args.mmseqs_bin)
        if not args.dry_run and not args.force and _stage_is_valid(state, "preflight", fingerprint):
            prior = _load_json(_selected_record_path(output_dir, "preflight"))
            if _verify_generation_intact(prior):
                result = prior
            else:
                result = stage_preflight(config=config, dataset_csv=dataset_csv, output_dir=output_dir, mmseqs_bin=args.mmseqs_bin)
        else:
            result = stage_preflight(config=config, dataset_csv=dataset_csv, output_dir=output_dir, mmseqs_bin=args.mmseqs_bin, dry_run=args.dry_run)
        if not args.dry_run:
            _mark_stage_complete(state, "preflight", fingerprint)
            _save_state(output_dir, state)

    elif args.stage == "decode":
        preflight_record = {} if args.dry_run else _require_prior_stage(output_dir, "preflight")
        preflight_fp = state.get("stage_fingerprints", {}).get("preflight", "never_run")
        fingerprint = None if args.dry_run else decode_fingerprint(config=config, dataset_csv=dataset_csv, preflight_fp=preflight_fp)
        if not args.dry_run and not args.force and _stage_is_valid(state, "decode", fingerprint):
            prior = _load_json(_selected_record_path(output_dir, "decode"))
            result = prior if _verify_generation_intact(prior) else stage_decode(config=config, dataset_csv=dataset_csv, output_dir=output_dir, preflight_record=preflight_record)
        else:
            result = stage_decode(config=config, dataset_csv=dataset_csv, output_dir=output_dir, preflight_record=preflight_record, dry_run=args.dry_run)
        if not args.dry_run:
            _mark_stage_complete(state, "decode", fingerprint)
            _save_state(output_dir, state)

    elif args.stage in ("probe", "cluster"):
        decode_record = {} if args.dry_run else _require_prior_stage(output_dir, "decode")
        decode_fp = state.get("stage_fingerprints", {}).get("decode", "never_run")
        key = f"{args.stage}_{args.width}"
        fingerprint = None if args.dry_run else width_stage_fingerprint(stage_name=args.stage, width=args.width, config=config, decode_fp=decode_fp, mmseqs_bin=args.mmseqs_bin)
        stage_fn = stage_probe if args.stage == "probe" else stage_cluster
        if not args.dry_run and not args.force and _stage_is_valid(state, key, fingerprint):
            prior = _load_json(_selected_record_path(output_dir, key))
            result = prior if _verify_generation_intact(prior) else stage_fn(width=args.width, config=config, output_dir=output_dir, decode_record=decode_record, authorize=args.authorize_mmseqs, mmseqs_bin=args.mmseqs_bin)
        else:
            result = stage_fn(width=args.width, config=config, output_dir=output_dir, decode_record=decode_record, authorize=args.authorize_mmseqs, mmseqs_bin=args.mmseqs_bin, dry_run=args.dry_run)
        if not args.dry_run:
            _mark_stage_complete(state, key, fingerprint)
            _save_state(output_dir, state)

    elif args.stage == "component_report":
        if args.dry_run:
            result = stage_component_report(config=config, output_dir=output_dir, decode_record={}, cluster_records={}, dry_run=True)
        else:
            decode_record = _require_prior_stage(output_dir, "decode")
            cluster_records = {width: _require_prior_stage(output_dir, f"cluster_{width}") for width in config.protected_widths}
            result = stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)
            fingerprint = content_fingerprint(
                "component_report", config.content_hash, *(cluster_records[w]["generation_digest"] for w in config.protected_widths), decode_record["generation_digest"]
            )
            _mark_stage_complete(state, "component_report", fingerprint)
            _save_state(output_dir, state)

    else:  # pragma: no cover - argparse choices already excludes this
        raise StageValidationError(f"unknown stage {args.stage!r}")

    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
