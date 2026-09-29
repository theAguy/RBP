"""Task 002C restart-safe runner: ``assign``, ``legacy_diagnostic``,
``exact_audit``, ``audit_probe``, ``audit_search``, and ``finalize`` stages.

Checkpoint 002C-1 (``docs/handoffs/002c1_partition_orchestration_claude_handoff.md``)
authorizes ONLY this orchestration code and tiny synthetic-fixture tests: no
real dataset access, no accepted Task 002B artifacts, no real MMseqs2
execution over real sequences, and no partition promoted to acceptance
anywhere in this module happen with real data. A SEPARATE console entry
point and a SEPARATE config file
(:mod:`rbpbench.splits.config_002c`) from Task 002B's own
:mod:`rbpbench.splits.runner` mean extending Task 002C can never
destabilize the already-accepted Task 002B runner.

There is no ``all`` stage. ``--width`` is rejected outside
:data:`WIDTH_SCOPED_STAGES`; ``--query-partition``/``--target-partition``
are rejected outside :data:`DIRECTION_SCOPED_STAGES`, where they are
required and must be distinct and each one of ``train``/``validation``/
``test``. Every audit-search/probe selection-record key and restart
fingerprint includes width, query partition, and target partition
(:func:`rbpbench.splits.mmseqs_audit.selection_key`), so an accepted result
from one direction can never satisfy the reverse direction.
``--dry-run`` is checked before any declared input is opened or subprocess
is launched. MMseqs2 stages (``audit_probe``, ``audit_search``) require
explicit ``--authorize-mmseqs`` and run only one external stage per
invocation.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Sequence

from rbpbench.coordinates.decode import fasta_record
from rbpbench.coordinates.hashing import content_fingerprint, label_blind_rank
from rbpbench.data.audit import sha256_file
from rbpbench.splits import assignment
from rbpbench.splits import audit as splits_audit
from rbpbench.splits import commands as splits_commands
from rbpbench.splits import exact_audit as splits_exact_audit
from rbpbench.splits import guarded_exec
from rbpbench.splits import ingestion
from rbpbench.splits import legacy_diagnostic as splits_legacy_diagnostic
from rbpbench.splits import mmseqs_audit
from rbpbench.splits import output as splits_output
from rbpbench.splits import restart
from rbpbench.splits.assignment import TARGET_FRACTIONS
from rbpbench.splits.config_002c import SplitsConfig002C, load_config_002c

STAGES: tuple[str, ...] = (
    "assign", "legacy_diagnostic", "exact_audit", "audit_probe", "audit_search", "finalize",
)
WIDTH_SCOPED_STAGES: tuple[str, ...] = ("exact_audit", "audit_probe", "audit_search")
DIRECTION_SCOPED_STAGES: tuple[str, ...] = ("audit_probe", "audit_search")
MMSEQS_STAGES: tuple[str, ...] = ("audit_probe", "audit_search")

DEFAULT_CONFIG_PATH = Path("configs/splits/sequence_partitions_002c_v1.toml")
DEFAULT_OUTPUT_DIR = Path("artifacts/splits/sequence_partitions_002c_v1")


class StageValidationError(ValueError):
    """A stage/argument combination is invalid -- raised before any
    subprocess or declared-real-input file access.
    """


class AuthorizationError(RuntimeError):
    """``--authorize-mmseqs`` was not given for a stage that may launch
    MMseqs2. Checked before any subprocess or declared-real-input access.
    """


class ReproducibilityError(RuntimeError):
    """Recomputing a result under reordered input did not reproduce the
    first computation byte-for-byte.
    """


class InputValidationError(ValueError):
    """A declared real input (CSV/component membership/decode FASTA) failed
    exact hash/size revalidation against the current config.
    """


class FinalizationRefusedError(RuntimeError):
    """``finalize`` refused because at least one required record is
    missing, stale, failed, or one-direction-only. Never promotes a partial
    or failing result.
    """


# --------------------------------------------------------------------------
# Small local helpers (FASTA I/O, deterministic label-blind subsetting).
# --------------------------------------------------------------------------


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


def _deterministic_subset(sequences: dict[str, str], sample_size: int, seed: int) -> dict[str, str]:
    if len(sequences) <= sample_size:
        return sequences
    ranked = sorted(sequences, key=lambda sid: (label_blind_rank(seed, sid), sid))
    selected = set(ranked[:sample_size])
    return {sid: seq for sid, seq in sequences.items() if sid in selected}


def _sample_to_partition(assign_record: dict) -> dict[str, str]:
    sample_to_component = assign_record["sample_to_component"]
    component_to_partition = assign_record["component_to_partition"]
    return {sample_id: component_to_partition[component_id] for sample_id, component_id in sample_to_component.items()}


def _verify_csv(csv_path: Path, config: SplitsConfig002C) -> str:
    if not Path(csv_path).is_file():
        raise InputValidationError(f"CSV not found at {csv_path}")
    actual_size = Path(csv_path).stat().st_size
    if actual_size != config.dataset.csv_byte_size:
        raise InputValidationError(
            f"CSV at {csv_path} is {actual_size} bytes, expected exactly {config.dataset.csv_byte_size}"
        )
    actual_sha256 = sha256_file(Path(csv_path))
    if actual_sha256 != config.dataset.csv_sha256:
        raise InputValidationError(
            f"CSV at {csv_path} hashes to {actual_sha256}, expected exactly {config.dataset.csv_sha256}"
        )
    return actual_sha256


# --------------------------------------------------------------------------
# assign
# --------------------------------------------------------------------------


def assign_fingerprint(*, config: SplitsConfig002C, csv_sha256: str, membership_sha256: str) -> str:
    return content_fingerprint("assign", config.content_hash, csv_sha256, membership_sha256)


def stage_assign(
    *, config: SplitsConfig002C, csv_path: Path, membership_path: Path, output_dir: Path, dry_run: bool = False
) -> dict:
    if dry_run:
        return {
            "dry_run": True, "stage": "assign",
            "would_read": {"csv": str(csv_path), "component_membership": str(membership_path)},
        }

    membership_sha256 = ingestion.verify_component_membership_file(
        membership_path,
        expected_sha256=config.components_002b.membership_sha256,
        expected_byte_size=config.components_002b.membership_byte_size,
    )
    universe = ingestion.load_component_membership(
        membership_path,
        expected_sample_count=config.dataset.expected_row_count,
        expected_component_count=config.components_002b.expected_component_count,
    )
    csv_sha256 = _verify_csv(csv_path, config)

    aggregates = ingestion.stream_component_label_aggregates(
        csv_path, universe, protein_id_min=config.dataset.protein_id_min, protein_id_max=config.dataset.protein_id_max
    )
    components = ingestion.to_component_label_counts(aggregates)

    assignment_result = assignment.assign_partitions(
        components,
        seed=config.seed,
        evaluation_floor=config.assignment.evaluation_floor,
        max_repair_passes=config.assignment.max_repair_passes,
        row_fraction_repair_limit_pct=config.assignment.row_fraction_repair_limit_pct,
    )

    total_rows = sum(assignment_result.partition_row_counts.values())
    balance = splits_audit.balance_report(assignment_result.partition_row_counts, TARGET_FRACTIONS, total_rows)
    per_protein_balance = splits_audit.per_protein_balance_report(assignment_result.partition_label_counts, TARGET_FRACTIONS)
    minimum_counts = splits_audit.minimum_count_check(
        assignment_result.partition_label_counts, floor=config.assignment.evaluation_floor
    )

    base_dir = output_dir / "assign"
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix="assign")
    try:
        rows = [
            (sample_id, component_id, assignment_result.component_to_partition[component_id])
            for sample_id, component_id in universe.sample_to_component.items()
        ]
        membership_path_out = generation_dir / "membership.tsv.gz"
        splits_output.write_deterministic_membership_gzip(rows, membership_path_out)
        repeat_path = generation_dir / "membership.repeat_check.tsv.gz"
        splits_output.write_deterministic_membership_gzip(list(reversed(rows)), repeat_path)
        if membership_path_out.read_bytes() != repeat_path.read_bytes():
            raise ReproducibilityError("assign membership gzip is not byte-identical across reordered reproduction")
        repeat_path.unlink()

        partition_label_counts_json = {
            partition: {str(pid): list(counts) for pid, counts in per_protein.items()}
            for partition, per_protein in assignment_result.partition_label_counts.items()
        }
        manifest = {
            "schema_version": 1,
            "checkpoint": "002C-1-assign",
            "config_hash": config.content_hash,
            "csv_sha256": csv_sha256,
            "component_membership_sha256": membership_sha256,
            "total_rows": total_rows,
            "component_count": len(universe.component_sizes),
            "partition_row_counts": dict(assignment_result.partition_row_counts),
            "partition_label_counts": partition_label_counts_json,
            "balance_report": balance,
            "per_protein_balance_report": {str(pid): v for pid, v in per_protein_balance.items()},
            "minimum_count_report": minimum_counts,
            "repair_step_count": len(assignment_result.repair_steps),
            "repair_steps": list(assignment_result.repair_steps),
        }
        manifest_path = generation_dir / "assign_manifest.json"
        restart.atomic_write_json(manifest_path, manifest)

        artifacts = restart.inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            "assign_generation", str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = assign_fingerprint(config=config, csv_sha256=csv_sha256, membership_sha256=membership_sha256)
        record = {
            "stage": "assign",
            "executed": True,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "membership_path": str(membership_path_out),
            "manifest_path": str(manifest_path),
            "csv_path": str(csv_path),
            "csv_sha256": csv_sha256,
            "component_membership_path": str(membership_path),
            "component_membership_sha256": membership_sha256,
            "sample_to_component": dict(universe.sample_to_component),
            "component_to_partition": dict(assignment_result.component_to_partition),
            "partition_row_counts": dict(assignment_result.partition_row_counts),
            "partition_label_counts": partition_label_counts_json,
            "minimum_count_report": minimum_counts,
            "balance_report": balance,
            "artifacts": artifacts,
        }
        restart.atomic_write_json(restart.selected_record_path(output_dir, "assign"), record)
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
    return record


# --------------------------------------------------------------------------
# legacy_diagnostic
# --------------------------------------------------------------------------


def legacy_diagnostic_fingerprint(*, config: SplitsConfig002C, csv_sha256: str, assign_stage_fingerprint: str) -> str:
    return content_fingerprint("legacy_diagnostic", config.content_hash, csv_sha256, assign_stage_fingerprint)


def stage_legacy_diagnostic(
    *,
    config: SplitsConfig002C,
    csv_path: Path,
    output_dir: Path,
    assign_record: dict,
    similarity_edges_dir: Path | None = None,
    dry_run: bool = False,
) -> dict:
    if dry_run:
        return {"dry_run": True, "stage": "legacy_diagnostic", "would_read": {"csv": str(csv_path)}}

    versions = splits_legacy_diagnostic.resolve_dependency_versions()
    splits_legacy_diagnostic.require_pinned_versions(
        versions,
        expected={
            "python_version": config.legacy_diagnostic.python_version,
            "numpy_version": config.legacy_diagnostic.numpy_version,
            "scipy_version": config.legacy_diagnostic.scipy_version,
            "scikit_learn_version": config.legacy_diagnostic.scikit_learn_version,
            "iterative_stratification_version": config.legacy_diagnostic.iterative_stratification_version,
        },
    )

    csv_sha256 = _verify_csv(csv_path, config)

    sample_ids_by_index: list[str] = []
    signed_labels_by_row: list[dict[int, int]] = []
    for _row_index, sample_id, labels in ingestion.iter_csv_component_label_rows(
        csv_path, protein_id_min=config.dataset.protein_id_min, protein_id_max=config.dataset.protein_id_max
    ):
        sample_ids_by_index.append(sample_id)
        signed_labels_by_row.append(labels)
    protein_ids = list(range(config.dataset.protein_id_min, config.dataset.protein_id_max + 1))

    fold_result = splits_legacy_diagnostic.run_legacy_fold(signed_labels_by_row, protein_ids=protein_ids)

    sample_to_component = assign_record["sample_to_component"]
    sample_to_partition = _sample_to_partition(assign_record)

    similarity_edges_by_width: dict[int, list[tuple[str, str]]] = {}
    exact_rc_edges_by_width: dict[int, list[tuple[str, str]]] = {}
    if similarity_edges_dir is not None:
        for width in config.protected_widths:
            edges_path = Path(similarity_edges_dir) / f"edges_{width}.json"
            if edges_path.is_file():
                similarity_edges_by_width[width] = [tuple(pair) for pair in json.loads(edges_path.read_text())]
            exact_rc_path = Path(similarity_edges_dir) / f"exact_rc_edges_{width}.json"
            if exact_rc_path.is_file():
                exact_rc_edges_by_width[width] = [tuple(pair) for pair in json.loads(exact_rc_path.read_text())]

    report = splits_legacy_diagnostic.build_leakage_diagnostic_report(
        legacy_result=fold_result,
        sample_ids_by_index=sample_ids_by_index,
        sample_to_component=sample_to_component,
        sample_to_partition=sample_to_partition,
        similarity_edges_by_width=similarity_edges_by_width,
        exact_rc_edges_by_width=exact_rc_edges_by_width,
    )

    base_dir = output_dir / "legacy_diagnostic"
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix="legacy_diagnostic")
    try:
        manifest_path = generation_dir / "legacy_diagnostic_report.json"
        restart.atomic_write_json(manifest_path, report)

        artifacts = restart.inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            "legacy_diagnostic_generation", str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = legacy_diagnostic_fingerprint(
            config=config, csv_sha256=csv_sha256, assign_stage_fingerprint=assign_record["stage_fingerprint"]
        )
        record = {
            "stage": "legacy_diagnostic",
            "executed": True,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "manifest_path": str(manifest_path),
            "train_digest": fold_result.train_digest,
            "holdout_digest": fold_result.holdout_digest,
            "dependency_versions": versions.to_dict(),
            "upstream": {"assign_stage_fingerprint": assign_record["stage_fingerprint"]},
            "artifacts": artifacts,
        }
        restart.atomic_write_json(restart.selected_record_path(output_dir, "legacy_diagnostic"), record)
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
    return record


# --------------------------------------------------------------------------
# exact_audit
# --------------------------------------------------------------------------


def exact_audit_fingerprint(*, config: SplitsConfig002C, width: int, assign_stage_fingerprint: str, fasta_sha256: str) -> str:
    return content_fingerprint("exact_audit", width, config.content_hash, assign_stage_fingerprint, fasta_sha256)


def stage_exact_audit(
    *, width: int, config: SplitsConfig002C, output_dir: Path, decode_fasta_dir: Path, assign_record: dict, dry_run: bool = False
) -> dict:
    if width not in config.protected_widths:
        raise StageValidationError(f"width {width!r} is not one of the protected widths {config.protected_widths}")
    if dry_run:
        return {"dry_run": True, "stage": "exact_audit", "width": width}

    fasta_path = Path(decode_fasta_dir) / f"width_{width}.fasta"
    if not fasta_path.is_file():
        raise InputValidationError(f"decode FASTA not found at {fasta_path}")
    sequences = _read_fasta(fasta_path)
    fasta_sha256 = sha256_file(fasta_path)
    sample_to_partition = _sample_to_partition(assign_record)

    report = splits_exact_audit.audit_width(sequences, sample_to_partition)

    base_dir = output_dir / "exact_audit" / str(width)
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix="exact_audit")
    try:
        manifest_path = generation_dir / "exact_audit_report.json"
        restart.atomic_write_json(manifest_path, {"width": width, **report})

        artifacts = restart.inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            "exact_audit_generation", width, str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = exact_audit_fingerprint(
            config=config, width=width, assign_stage_fingerprint=assign_record["stage_fingerprint"], fasta_sha256=fasta_sha256
        )
        record = {
            "stage": "exact_audit",
            "executed": True,
            "width": width,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "manifest_path": str(manifest_path),
            "fasta_sha256": fasta_sha256,
            "violation_count": report["violation_count"],
            "passed": report["passed"],
            "upstream": {"assign_stage_fingerprint": assign_record["stage_fingerprint"]},
            "artifacts": artifacts,
        }
        restart.atomic_write_json(restart.selected_record_path(output_dir, f"exact_audit_{width}"), record)
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
    return record


# --------------------------------------------------------------------------
# audit_probe / audit_search (share the directed-search shape)
# --------------------------------------------------------------------------


def directed_audit_fingerprint(
    *, stage_name: str, width: int, query_partition: str, target_partition: str, config: SplitsConfig002C,
    assign_stage_fingerprint: str, mmseqs_bin: str,
) -> str:
    binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    return content_fingerprint(
        stage_name, width, query_partition, target_partition, config.content_hash, assign_stage_fingerprint,
        binary.sha256 or "MISSING", mmseqs_bin,
    )


def _run_directed_audit(
    *, stage_name: str, width: int, query_partition: str, target_partition: str, config: SplitsConfig002C,
    output_dir: Path, decode_fasta_dir: Path, assign_record: dict, authorize: bool, mmseqs_bin: str,
    dry_run: bool, subset_sample_size: int | None,
) -> dict:
    mmseqs_audit.validate_direction(query_partition, target_partition)
    if width not in config.protected_widths:
        raise StageValidationError(f"width {width!r} is not one of the protected widths {config.protected_widths}")

    if dry_run:
        return {
            "dry_run": True, "stage": stage_name, "width": width, "query_partition": query_partition,
            "target_partition": target_partition, "would_authorize_mmseqs": authorize,
        }

    if not authorize:
        raise AuthorizationError(f"stage {stage_name!r} launches MMseqs2 and requires --authorize-mmseqs")

    key = mmseqs_audit.selection_key(stage_name, width, query_partition, target_partition)
    if stage_name == "audit_search":
        probe_key = mmseqs_audit.selection_key("audit_probe", width, query_partition, target_partition)
        restart.require_accepted(output_dir, probe_key)

    fasta_path = Path(decode_fasta_dir) / f"width_{width}.fasta"
    if not fasta_path.is_file():
        raise InputValidationError(f"decode FASTA not found at {fasta_path}")
    sequences = _read_fasta(fasta_path)
    sample_to_partition = _sample_to_partition(assign_record)

    live_binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    if live_binary.resolved_path is None:
        raise InputValidationError(f"mmseqs binary {mmseqs_bin!r} not found on PATH")
    if live_binary.version != splits_commands.PINNED_VERSION:
        raise InputValidationError(f"mmseqs version {live_binary.version!r} != pinned {splits_commands.PINNED_VERSION!r}")
    if live_binary.sha256 != config.binary.mmseqs_sha256:
        raise InputValidationError(
            f"mmseqs binary SHA-256 {live_binary.sha256!r} != accepted {config.binary.mmseqs_sha256!r} for stage {stage_name!r}"
        )

    guarded_exec.check_free_disk_or_fail(disk_path=output_dir, min_free_disk_gib=config.audit.min_free_disk_gib, label=stage_name)

    base_dir = output_dir / stage_name / str(width) / f"{query_partition}_to_{target_partition}"
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix=stage_name)
    try:
        query_seqs = mmseqs_audit.build_partition_fasta_subset(sequences, sample_to_partition, query_partition)
        target_seqs = mmseqs_audit.build_partition_fasta_subset(sequences, sample_to_partition, target_partition)
        if subset_sample_size is not None:
            query_seqs = _deterministic_subset(query_seqs, subset_sample_size, config.seed)
            target_seqs = _deterministic_subset(target_seqs, subset_sample_size, config.seed)

        query_fasta = generation_dir / "query.fasta"
        target_fasta = generation_dir / "target.fasta"
        _write_fasta(query_seqs, query_fasta)
        _write_fasta(target_seqs, target_fasta)

        query_db = generation_dir / "query_db"
        target_db = generation_dir / "target_db"
        result_prefix = generation_dir / "result"
        tmp_dir = generation_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        log_dir = generation_dir / "logs"
        threads = config.audit.max_threads
        guard_kwargs = dict(
            timeout_seconds=config.audit.timeout_seconds, output_dir=output_dir,
            max_new_disk_gib=config.audit.max_new_disk_gib, min_free_disk_gib=config.audit.min_free_disk_gib,
            poll_interval=config.audit.resource_poll_interval_seconds,
        )
        executed: list[dict] = []
        executed.append(guarded_exec.run_guarded_mmseqs(
            splits_commands.with_threads(splits_commands.createdb_command(query_fasta, query_db, mmseqs_bin=mmseqs_bin), threads),
            log_dir=log_dir, **guard_kwargs,
        ))
        executed.append(guarded_exec.run_guarded_mmseqs(
            splits_commands.with_threads(splits_commands.createdb_command(target_fasta, target_db, mmseqs_bin=mmseqs_bin), threads),
            log_dir=log_dir, **guard_kwargs,
        ))
        search_cmd = splits_commands.with_threads(
            splits_commands.audit_search_command(query_db, target_db, result_prefix, tmp_dir, width=width, mmseqs_bin=mmseqs_bin), threads
        )
        executed.append(guarded_exec.run_guarded_mmseqs(search_cmd, log_dir=log_dir, **guard_kwargs))
        hits_tsv = generation_dir / "hits.tsv"
        executed.append(guarded_exec.run_guarded_mmseqs(
            splits_commands.with_threads(
                splits_commands.createtsv_search_command(query_db, target_db, result_prefix, hits_tsv, mmseqs_bin=mmseqs_bin), threads
            ),
            log_dir=log_dir, **guard_kwargs,
        ))

        hits = mmseqs_audit.parse_search_hits(hits_tsv)
        directed_result = mmseqs_audit.reconcile_directed_hits(
            hits, width=width, query_partition=query_partition, target_partition=target_partition,
            query_universe=list(query_seqs), target_universe=list(target_seqs),
        )

        guarded_exec.check_combined_ceiling_or_discard(output_dir=output_dir, max_new_disk_gib=config.audit.max_new_disk_gib)

        manifest_path = generation_dir / f"{stage_name}_report.json"
        restart.atomic_write_json(manifest_path, directed_result.to_dict())

        artifacts = restart.inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            f"{stage_name}_generation", width, query_partition, target_partition, str(generation_dir),
            *((e["path"], e["sha256"]) for e in artifacts),
        )
        stage_fp = directed_audit_fingerprint(
            stage_name=stage_name, width=width, query_partition=query_partition, target_partition=target_partition,
            config=config, assign_stage_fingerprint=assign_record["stage_fingerprint"], mmseqs_bin=mmseqs_bin,
        )
        record = {
            "stage": stage_name,
            "executed": True,
            "width": width,
            "query_partition": query_partition,
            "target_partition": target_partition,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "manifest_path": str(manifest_path),
            "hits_tsv": str(hits_tsv),
            "hit_count": directed_result.hit_count,
            "violation_count": len(directed_result.violations),
            "passed": directed_result.passed,
            "upstream": {"assign_stage_fingerprint": assign_record["stage_fingerprint"]},
            "mmseqs_bin": mmseqs_bin,
            "threads": threads,
            "tool_provenance": executed,
            "artifacts": artifacts,
        }
        restart.atomic_write_json(restart.selected_record_path(output_dir, key), record)
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
    return record


def stage_audit_probe(
    *, width: int, query_partition: str, target_partition: str, config: SplitsConfig002C, output_dir: Path,
    decode_fasta_dir: Path, assign_record: dict, authorize: bool, mmseqs_bin: str = "mmseqs", dry_run: bool = False,
) -> dict:
    return _run_directed_audit(
        stage_name="audit_probe", width=width, query_partition=query_partition, target_partition=target_partition,
        config=config, output_dir=output_dir, decode_fasta_dir=decode_fasta_dir, assign_record=assign_record,
        authorize=authorize, mmseqs_bin=mmseqs_bin, dry_run=dry_run, subset_sample_size=config.audit.probe_sample_size,
    )


def stage_audit_search(
    *, width: int, query_partition: str, target_partition: str, config: SplitsConfig002C, output_dir: Path,
    decode_fasta_dir: Path, assign_record: dict, authorize: bool, mmseqs_bin: str = "mmseqs", dry_run: bool = False,
) -> dict:
    return _run_directed_audit(
        stage_name="audit_search", width=width, query_partition=query_partition, target_partition=target_partition,
        config=config, output_dir=output_dir, decode_fasta_dir=decode_fasta_dir, assign_record=assign_record,
        authorize=authorize, mmseqs_bin=mmseqs_bin, dry_run=dry_run, subset_sample_size=None,
    )


# --------------------------------------------------------------------------
# finalize
# --------------------------------------------------------------------------


def stage_finalize(*, config: SplitsConfig002C, output_dir: Path, dry_run: bool = False) -> dict:
    if dry_run:
        return {"dry_run": True, "stage": "finalize"}

    assign_record = restart.require_accepted(output_dir, "assign")
    legacy_record = restart.require_accepted(output_dir, "legacy_diagnostic")
    exact_audit_records = {
        width: restart.require_accepted(output_dir, f"exact_audit_{width}") for width in config.protected_widths
    }
    search_records: dict[str, dict] = {}
    for width in config.protected_widths:
        for query_partition, target_partition in mmseqs_audit.ORDERED_PARTITION_PAIRS:
            key = mmseqs_audit.selection_key("audit_search", width, query_partition, target_partition)
            search_records[key] = restart.require_accepted(output_dir, key)

    problems: list[str] = []
    minimum_count_report = assign_record.get("minimum_count_report", {})
    if not minimum_count_report.get("passed", False):
        problems.append("assign: evaluation-floor violation(s) present")
    balance = assign_record.get("balance_report", {})
    for partition, entry in balance.items():
        if entry.get("flagged"):
            problems.append(
                f"assign: row balance for {partition} deviates {entry['deviation_percentage_points']:.2f}pp (>3pp)"
            )
    for width, record in exact_audit_records.items():
        if not record.get("passed", False):
            problems.append(f"exact_audit width {width}: cross-partition violation(s) present")
    for key, record in search_records.items():
        if not record.get("passed", False):
            problems.append(f"{key}: cross-partition violation(s) present")

    if problems:
        raise FinalizationRefusedError("finalize refused: " + "; ".join(problems))

    rows = splits_output.read_membership_gzip(Path(assign_record["membership_path"]))

    base_dir = output_dir / "finalize"
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix="finalize")
    try:
        final_membership_path = generation_dir / "sequence_partitions_002c_v1.tsv.gz"
        splits_output.write_deterministic_membership_gzip(rows, final_membership_path)
        repeat_path = generation_dir / "sequence_partitions_002c_v1.repeat_check.tsv.gz"
        splits_output.write_deterministic_membership_gzip(list(reversed(rows)), repeat_path)
        if final_membership_path.read_bytes() != repeat_path.read_bytes():
            raise ReproducibilityError("final membership gzip is not byte-identical across reordered reproduction")
        repeat_path.unlink()

        upstream_digests = {
            "assign_stage_fingerprint": assign_record["stage_fingerprint"],
            "legacy_diagnostic_stage_fingerprint": legacy_record["stage_fingerprint"],
        }
        for width, record in exact_audit_records.items():
            upstream_digests[f"exact_audit_{width}_stage_fingerprint"] = record["stage_fingerprint"]
        for key, record in search_records.items():
            upstream_digests[f"{key}_stage_fingerprint"] = record["stage_fingerprint"]

        manifest = {
            "schema_version": 1,
            "checkpoint": "002C-1-finalize",
            "config_hash": config.content_hash,
            "partition_row_counts": assign_record["partition_row_counts"],
            "minimum_count_report": minimum_count_report,
            "balance_report": balance,
            "exact_audit_summary": {
                str(width): {"passed": record["passed"], "violation_count": record.get("violation_count")}
                for width, record in exact_audit_records.items()
            },
            "audit_search_summary": {
                key: {"passed": record["passed"], "hit_count": record.get("hit_count")}
                for key, record in search_records.items()
            },
            "legacy_diagnostic": {
                "train_digest": legacy_record["train_digest"], "holdout_digest": legacy_record["holdout_digest"],
            },
            "upstream_digests": upstream_digests,
        }
        manifest_path = generation_dir / "sequence_partitions_002c_v1_manifest.json"
        restart.atomic_write_json(manifest_path, manifest)

        artifacts = restart.inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            "finalize_generation", str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = content_fingerprint("finalize", config.content_hash, *sorted(upstream_digests.items()))
        record = {
            "stage": "finalize",
            "executed": True,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "membership_path": str(final_membership_path),
            "manifest_path": str(manifest_path),
            "upstream": upstream_digests,
            "artifacts": artifacts,
        }
        restart.atomic_write_json(restart.selected_record_path(output_dir, "finalize"), record)
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
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
    parser.add_argument("--width", type=int, choices=(500, 251, 101), default=None, action=_SingleOccurrenceAction)
    parser.add_argument("--query-partition", choices=("train", "validation", "test"), default=None)
    parser.add_argument("--target-partition", choices=("train", "validation", "test"), default=None)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--component-membership", type=Path, default=None)
    parser.add_argument("--decode-fasta-dir", type=Path, default=None)
    parser.add_argument("--similarity-edges-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mmseqs-bin", default="mmseqs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--authorize-mmseqs", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.width is not None and args.stage not in WIDTH_SCOPED_STAGES:
        raise StageValidationError(f"--width is not accepted for stage {args.stage!r}")
    if args.stage in WIDTH_SCOPED_STAGES and args.width is None:
        raise StageValidationError(f"stage {args.stage!r} requires --width")

    if args.stage in DIRECTION_SCOPED_STAGES:
        if args.query_partition is None or args.target_partition is None:
            raise StageValidationError(f"stage {args.stage!r} requires --query-partition and --target-partition")
        mmseqs_audit.validate_direction(args.query_partition, args.target_partition)
    elif args.query_partition is not None or args.target_partition is not None:
        raise StageValidationError(f"--query-partition/--target-partition are not accepted for stage {args.stage!r}")

    if args.stage in MMSEQS_STAGES and not args.authorize_mmseqs and not args.dry_run:
        raise AuthorizationError(f"stage {args.stage!r} launches MMseqs2 and requires --authorize-mmseqs")

    config = load_config_002c(args.config)
    output_dir = args.output_dir

    if args.stage == "assign":
        if args.dry_run:
            result = stage_assign(config=config, csv_path=args.csv, membership_path=args.component_membership, output_dir=output_dir, dry_run=True)
        else:
            csv_sha256 = sha256_file(Path(args.csv)) if args.csv and Path(args.csv).is_file() else "MISSING"
            membership_sha256 = (
                sha256_file(Path(args.component_membership))
                if args.component_membership and Path(args.component_membership).is_file() else "MISSING"
            )
            current_fp = assign_fingerprint(config=config, csv_sha256=csv_sha256, membership_sha256=membership_sha256)
            prior = None if args.force else restart.load_accepted(output_dir, "assign")
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_assign(config=config, csv_path=args.csv, membership_path=args.component_membership, output_dir=output_dir)

    elif args.stage == "legacy_diagnostic":
        if args.dry_run:
            result = stage_legacy_diagnostic(config=config, csv_path=args.csv, output_dir=output_dir, assign_record={}, dry_run=True)
        else:
            assign_record = restart.require_accepted(output_dir, "assign")
            csv_sha256 = sha256_file(Path(args.csv)) if args.csv and Path(args.csv).is_file() else "MISSING"
            current_fp = legacy_diagnostic_fingerprint(config=config, csv_sha256=csv_sha256, assign_stage_fingerprint=assign_record["stage_fingerprint"])
            prior = None if args.force else restart.load_accepted(output_dir, "legacy_diagnostic")
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_legacy_diagnostic(
                    config=config, csv_path=args.csv, output_dir=output_dir, assign_record=assign_record,
                    similarity_edges_dir=args.similarity_edges_dir,
                )

    elif args.stage == "exact_audit":
        if args.dry_run:
            result = stage_exact_audit(width=args.width, config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir, assign_record={}, dry_run=True)
        else:
            assign_record = restart.require_accepted(output_dir, "assign")
            fasta_path = Path(args.decode_fasta_dir) / f"width_{args.width}.fasta" if args.decode_fasta_dir else None
            fasta_sha256 = sha256_file(fasta_path) if fasta_path and fasta_path.is_file() else "MISSING"
            key = f"exact_audit_{args.width}"
            current_fp = exact_audit_fingerprint(config=config, width=args.width, assign_stage_fingerprint=assign_record["stage_fingerprint"], fasta_sha256=fasta_sha256)
            prior = None if args.force else restart.load_accepted(output_dir, key)
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_exact_audit(width=args.width, config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir, assign_record=assign_record)

    elif args.stage in DIRECTION_SCOPED_STAGES:
        stage_fn = stage_audit_probe if args.stage == "audit_probe" else stage_audit_search
        if args.dry_run:
            result = stage_fn(
                width=args.width, query_partition=args.query_partition, target_partition=args.target_partition,
                config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir, assign_record={},
                authorize=args.authorize_mmseqs, mmseqs_bin=args.mmseqs_bin, dry_run=True,
            )
        else:
            assign_record = restart.require_accepted(output_dir, "assign")
            key = mmseqs_audit.selection_key(args.stage, args.width, args.query_partition, args.target_partition)
            current_fp = directed_audit_fingerprint(
                stage_name=args.stage, width=args.width, query_partition=args.query_partition,
                target_partition=args.target_partition, config=config,
                assign_stage_fingerprint=assign_record["stage_fingerprint"], mmseqs_bin=args.mmseqs_bin,
            )
            prior = None if args.force else restart.load_accepted(output_dir, key)
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_fn(
                    width=args.width, query_partition=args.query_partition, target_partition=args.target_partition,
                    config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir,
                    assign_record=assign_record, authorize=args.authorize_mmseqs, mmseqs_bin=args.mmseqs_bin,
                )

    elif args.stage == "finalize":
        result = stage_finalize(config=config, output_dir=output_dir, dry_run=args.dry_run)

    else:  # pragma: no cover - argparse choices already excludes this
        raise StageValidationError(f"unknown stage {args.stage!r}")

    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
