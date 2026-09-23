"""Restart-safe, explicitly-staged runner for the Task 001A/001B pipeline.

Importing this module, or running the unit test suite, never downloads
anything or invokes a mapper: the ``align`` and ``exact_match`` stages only
*construct* commands unless the caller passes ``--allow-mapping`` together
with ``--host-role=approved_mac`` and a real ``--reference``, and even then
every real execution is gated a second time, immediately before the
subprocess call, by a *fresh* :func:`rbpbench.coordinates.preflight.run_preflight`
bound to the current OS/architecture, resource limits, pinned tool versions,
and hashes of the exact reference/reads that call is about to use — never
merely a declared ``--host-role=approved_mac``. ``--dry-run`` is an absolute
guard checked before any of that: it short-circuits both ``align`` and
``exact_match`` before even the basic capability check, so no external
mapping/exact-match subprocess can ever execute under it, regardless of what
other flags are also given.

The pipeline processes two reference builds (``hg38``/``hg19`` by default)
sequentially, each into its own ``<output-dir>/<build>/`` subdirectory so
their artifacts never collide, then a final ``combined_report`` stage reads
every build's persisted results and produces the one combined report.

Progress is tracked in ``<output-dir>/state.json`` so a re-run skips
already-completed stages; build-scoped stages (``align``/``exact_match``/
``report``) are tracked per build (``"align:hg38"``, ...) so processing one
build never skips or overwrites another's. A stage that only *planned* or
was *skipped* (dry-run, missing authorization, failed preflight) is never
recorded as completed when it was actually authorized to run for real: doing
so would silently prevent a later, real run of the same stage. The sampled
assignments are separately persisted to ``<output-dir>/sample_state.json`` so
a later stage can resume in a brand-new process without having re-run
``sample`` in the same one.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import subprocess
from pathlib import Path
from typing import Sequence

from rbpbench.coordinates import summaries
from rbpbench.coordinates.alignment import (
    AlignmentRecord,
    CandidateLocus,
    build_candidate_loci,
    classify_primary,
    classify_splice,
    has_plausible_distinct_secondary,
    near_tied_secondary_fractions,
    parse_sam_line,
)
from rbpbench.coordinates.cleanup import CleanupRefused, execute_index_cleanup
from rbpbench.coordinates.commands import (
    bwa_mem_command,
    format_command,
    minimap2_splice_command,
    seqkit_locate_command,
)
from rbpbench.coordinates.config import FeasibilityConfig, load_config
from rbpbench.coordinates.controls import generate_control
from rbpbench.coordinates.decode import decode_and_validate, fasta_record
from rbpbench.coordinates.diskbudget import (
    BUILD_OUTPUT_ALLOWANCE_GIB,
    PLANNED_ALLOWANCES_GIB,
    DiskBudgetLedger,
    check_projected_peak,
    start_ledger,
)
from rbpbench.coordinates.exact_match import exact_occurrence_count, exact_unique_confirmed, parse_seqkit_bed
from rbpbench.coordinates.execution_sources import load_execution_sources, verify_local_inputs
from rbpbench.coordinates.hashing import content_fingerprint, control_seed
from rbpbench.coordinates.indexing import (
    build_index_manifest,
    prepare_bwa_index,
    prepare_minimap2_index,
    verify_index_files_against_manifest,
)
from rbpbench.coordinates.manifest import validate_reference_manifest
from rbpbench.coordinates.preflight import APPROVED_MAC, DEV_VM, run_preflight
from rbpbench.coordinates.provenance import resolve_binary_provenance, run_tool_with_provenance
from rbpbench.coordinates.reference import IndexedFastaReader, load_fasta_sequences, prepare_reference_index
from rbpbench.coordinates.report import (
    MappingResult,
    build_combined_report,
    build_report,
    reconcile_counts,
    render_combined_report_markdown,
    render_markdown,
)
from rbpbench.coordinates.sampling import DatasetRow, SampleAssignment, SamplingResult, build_sample
from rbpbench.data.audit import parse_labels, sha256_file

STAGES = ("preflight", "sample", "decode", "controls", "index", "align", "exact_match", "report", "combined_report")
BUILD_SCOPED_STAGES = ("index", "align", "exact_match", "report")
DEFAULT_BUILDS = ("hg38", "hg19")

CONTROL_ID_PREFIX = "control_"

MAPPING_TSV_COLUMNS = (
    "sample_id",
    "is_control",
    "stratum",
    "build",
    "mode",
    "category",
    "chrom",
    "start",
    "end",
    "strand",
    "block_count",
    "block_starts",
    "block_sizes",
    "coverage",
    "identity",
    "mapq",
    "alignment_score",
    "intron_lengths",
    "canonical_junctions",
    "near_tied_fractions",
    # Exact-match evidence (primary mode only; empty for splice rows), kept
    # so BWA-vs-SeqKit discordance is auditable rather than collapsed into
    # just a category name (see rbpbench.coordinates.summaries.exact_match_discordance).
    "exact_occurrence_count",
    # bwa_best_is_perfect: the best BWA locus alone has 100% coverage and
    # identity (diagnostic only — true even when a second, equally perfect
    # locus makes the call ambiguous).
    "bwa_best_is_perfect",
    # bwa_perfect_unique_candidate: bwa_best_is_perfect AND no plausible
    # distinct secondary locus — the actual BWA-side precondition for
    # exact_unique, and the correct field for exact-match discordance
    # auditing (a read with two perfect BWA loci is ambiguous, not a
    # uniqueness candidate, regardless of what SeqKit reports).
    "bwa_perfect_unique_candidate",
    # Full best-secondary evidence (not just chrom/coverage/identity), so a
    # reviewer can audit *why* a row was called ambiguous.
    "best_secondary_chrom",
    "best_secondary_start",
    "best_secondary_end",
    "best_secondary_strand",
    "best_secondary_block_count",
    "best_secondary_block_starts",
    "best_secondary_block_sizes",
    "best_secondary_coverage",
    "best_secondary_identity",
    "best_secondary_mapq",
    "best_secondary_alignment_score",
    "best_secondary_intron_lengths",
    "best_secondary_canonical_junctions",
)


def read_dataset_rows(csv_path: Path, num_proteins: int) -> list[DatasetRow]:
    rows: list[DatasetRow] = []
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            labels = tuple(parse_labels(row["labels"], num_proteins))
            rows.append(DatasetRow(row_index=index, labels=labels))
    return rows


def _build_dir(output_dir: Path, build: str) -> Path:
    return output_dir / build


def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:
        state = {}
    state.setdefault("completed_stages", [])
    state.setdefault("mapping_executed", {})
    state.setdefault("stage_fingerprints", {})
    return state


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically: a partial write (crash, disk-full) can never
    leave ``path`` holding truncated/corrupt content, and a concurrent
    reader can never observe a half-written file — required for "successful
    replacements remain atomic" (B1 required item 6).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_path, path)


def _guarded_write_record(path: Path, record: dict) -> None:
    """Write an ``align.json``/``exact_match.json``/``index.json``-shaped
    record, refusing to silently overwrite a prior ``executed: true`` record
    with a *plainly unauthorized* attempt's record (``--dry-run``, or the
    basic capability check failing — missing ``--allow-mapping``, wrong
    ``--host-role``, or a missing reference/reads file). Used only for those
    two absolute-guard branches: a fully authorized re-attempt that
    legitimately re-validates a *changed* declared input (a new reference
    whose manifest is now stale, a preflight that now fails against updated
    content, ...) is not "a retry" in this sense — restart fingerprints
    already force it to re-run, and its outcome must be recorded even when
    that outcome is "invalid", so those branches write plainly via
    ``_write_json``. This guard exists only to stop an accidental
    unauthorized re-run (e.g. forgetting ``--allow-mapping``) from silently
    erasing previously accepted checkpoint evidence.
    """
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = None
        if existing is not None and existing.get("executed") and not record.get("executed"):
            raise SystemExit(
                f"refusing to overwrite {path}: it already records executed=true, but this attempt did not "
                f"execute real work ({record.get('skip_reason')!r}); a failed/dry-run/unauthorized retry must "
                "never erase prior accepted checkpoint evidence"
            )
    _write_json(path, record)


def _sample_state_path(output_dir: Path) -> Path:
    return output_dir / "sample_state.json"


def _save_sample_state(output_dir: Path, sample: SamplingResult) -> None:
    payload = {
        "assignments": [
            {
                "sample_id": a.sample_id,
                "row_index": a.row_index,
                "stratum": a.stratum,
                "labels": list(a.labels),
            }
            for a in sample.assignments
        ],
        "representative_ids": sorted(sample.representative_ids),
        "quota_ids": sorted(sample.quota_ids),
        "filler_ids": sorted(sample.filler_ids),
    }
    _write_json(_sample_state_path(output_dir), payload)


def _load_sample_state(output_dir: Path) -> SamplingResult | None:
    """Reload a previously-persisted sample assignment (requirement: an
    interrupted run must be able to resume a later stage in a *new* process,
    not just later in the same one).
    """
    path = _sample_state_path(output_dir)
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    assignments = tuple(
        SampleAssignment(
            sample_id=entry["sample_id"],
            row_index=entry["row_index"],
            stratum=entry["stratum"],
            labels=tuple(entry["labels"]),
        )
        for entry in payload["assignments"]
    )
    return SamplingResult(
        assignments=assignments,
        representative_ids=frozenset(payload["representative_ids"]),
        quota_ids=frozenset(payload["quota_ids"]),
        filler_ids=frozenset(payload["filler_ids"]),
        unsatisfied_quotas=(),
    )


def stage_preflight(
    cfg: FeasibilityConfig,
    *,
    output_dir: Path,
    host_role: str,
    allow_mapping: bool,
    threads: int,
    references: dict[str, Path],
    reads_fasta: Path | None,
) -> dict:
    required_input_paths = {}
    if allow_mapping:
        for build, reference in references.items():
            required_input_paths[f"reference:{build}"] = reference
        if reads_fasta is not None:
            required_input_paths["reads"] = reads_fasta
    report = run_preflight(
        host_role=host_role,
        resources=cfg.resources,
        disk_path=output_dir,
        allow_mapping=allow_mapping,
        tools=cfg.tools,
        threads=threads,
        required_input_paths=required_input_paths,
    )
    _write_json(output_dir / "preflight.json", report.to_dict())
    if not report.ok:
        raise SystemExit(f"preflight failed closed: {list(report.violations)}")
    return report.to_dict()


def stage_sample(cfg: FeasibilityConfig, rows: Sequence[DatasetRow], *, output_dir: Path) -> SamplingResult:
    result = build_sample(
        rows,
        seed=cfg.sampling.seed,
        num_proteins=cfg.sampling.num_proteins,
        representative_size=cfg.sampling.representative_size,
        total_size=cfg.sampling.total_size,
        min_positive_per_protein=cfg.sampling.min_positive_per_protein,
        min_negative_per_protein=cfg.sampling.min_negative_per_protein,
    )
    sample_ids_path = output_dir / Path(cfg.outputs.sample_ids_tsv).name
    sample_ids_path.parent.mkdir(parents=True, exist_ok=True)
    with sample_ids_path.open("w") as handle:
        handle.write("sample_id\trow_index\tstratum\tlabels\n")
        for assignment in result.assignments:
            labels = ";".join(str(v) for v in assignment.labels)
            handle.write(f"{assignment.sample_id}\t{assignment.row_index}\t{assignment.stratum}\t{labels}\n")
    _save_sample_state(output_dir, result)
    return result


def stage_decode(
    rows_by_id: dict, sample: SamplingResult, *, sequence_length_nt: int, output_dir: Path
) -> Path:
    fasta_path = output_dir / "sample_sequences.fasta"
    fasta_path.parent.mkdir(parents=True, exist_ok=True)
    with fasta_path.open("w") as handle:
        for assignment in sample.assignments:
            bits = rows_by_id[assignment.sample_id]
            decoded = decode_and_validate(bits)
            if len(decoded) != sequence_length_nt:
                raise ValueError(
                    f"{assignment.sample_id}: decoded length {len(decoded)} != {sequence_length_nt}"
                )
            handle.write(fasta_record(assignment.sample_id, decoded))
    return fasta_path


def _prepare_mapping_reads(output_dir: Path) -> Path | None:
    """Combine the biological and control FASTAs into one mapping input.

    Real mapping must see both: control IDs are ``control_``-prefixed (see
    ``CONTROL_ID_PREFIX``) so classification can tell them apart downstream,
    but they still have to be submitted to the mapper to get a category at
    all. Returns None until the biological reads exist (before `decode`).
    This is build-independent: both reference builds map the same reads.
    """
    sample_fasta = output_dir / "sample_sequences.fasta"
    if not sample_fasta.exists():
        return None
    control_fasta = output_dir / "control_sequences.fasta"
    combined = output_dir / "mapping_reads.fasta"
    with combined.open("w") as handle:
        handle.write(sample_fasta.read_text())
        if control_fasta.exists():
            handle.write(control_fasta.read_text())
    return combined


def _read_fasta(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return load_fasta_sequences(path)


def stage_controls(
    rows_by_id: dict,
    sample: SamplingResult,
    *,
    seed: int,
    count: int,
    max_attempts: int,
    output_dir: Path,
) -> Path:
    representative = sorted(sample.representative_ids)[:count]
    if len(representative) < count:
        raise ValueError(f"representative stratum has only {len(representative)} rows; need {count} controls")

    fasta_path = output_dir / "control_sequences.fasta"
    fasta_path.parent.mkdir(parents=True, exist_ok=True)
    with fasta_path.open("w") as handle:
        for sample_id in representative:
            source = decode_and_validate(rows_by_id[sample_id])
            shuffled = generate_control(
                source,
                seed_fn=lambda attempt, sid=sample_id: control_seed(seed, sid, attempt),
                max_attempts=max_attempts,
            )
            handle.write(fasta_record(f"{CONTROL_ID_PREFIX}{sample_id}", shuffled))
    return fasta_path


_MAPPING_TOOL_TIMEOUT_SECONDS = 6 * 60 * 60  # generous bound for a feasibility-scale run; never unbounded


def _run_tool_to_file(argv: Sequence[str], *, output_path: Path, stderr_path: Path) -> None:
    """Execute a pinned mapper/matcher command, capturing stdout and stderr
    *separately*.

    stderr is never sent to ``DEVNULL``: a mapper's own diagnostic warnings
    (e.g. minimap2's parameter-override or multipart-index warnings) are
    load-bearing evidence, not noise, and must be preserved and hashed (see
    :mod:`rbpbench.coordinates.provenance`). Always ``shell=False``: ``argv``
    is a list built by :mod:`rbpbench.coordinates.commands`, never an
    interpolated shell string. Bounded by a generous timeout so a wedged
    mapper process cannot hang the pipeline forever.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as out_handle, stderr_path.open("w") as err_handle:
        subprocess.run(
            list(argv),
            shell=False,
            stdout=out_handle,
            stderr=err_handle,
            check=True,
            text=True,
            timeout=_MAPPING_TOOL_TIMEOUT_SECONDS,
        )


def _mapping_capable(*, allow_mapping: bool, host_role: str, reference: Path | None, reads_fasta: Path | None) -> str | None:
    """Return None when real execution may proceed, else the skip reason.

    This is only the *basic* capability check (flags/files present); it is
    not by itself sufficient authorization to execute — see the fresh
    ``run_preflight`` call in ``stage_align``/``stage_exact_match``, which is
    the hard, binding gate (bound to current OS/arch, resources, pinned tool
    versions, and hashes of these exact files) that a caller cannot bypass
    merely by declaring ``--host-role=approved_mac``.
    """
    if not allow_mapping or host_role != APPROVED_MAC:
        return (
            "mapping requires --allow-mapping together with --host-role=approved_mac "
            f"(got allow_mapping={allow_mapping}, host_role={host_role!r}); Task 001A never maps real data"
        )
    if reference is None or not Path(reference).is_file():
        return f"reference FASTA not found or not provided ({reference})"
    if reads_fasta is None or not Path(reads_fasta).is_file():
        return f"reads FASTA not found ({reads_fasta}); run the decode/controls stages first"
    return None


def _check_disk_budget_or_fail(
    ledger: DiskBudgetLedger | None, *, label: str, allowance_gib: float, disk_path: Path
) -> dict | None:
    """Fail-closed projected-peak check (review item 5 / B1 required item 8)
    run before every download/derivation/indexing/mapping subprocess. Raises
    ``SystemExit`` (never proceeds) when the projected total new disk would
    exceed the 30-GiB ceiling or free disk would fall below 80 GiB. Returns
    ``None`` when no ledger is supplied (direct unit-test calls of a single
    stage function without a shared runner-level ledger).
    """
    if ledger is None:
        return None
    check = check_projected_peak(ledger, next_step_allowance_gib=allowance_gib, disk_path=disk_path)
    if not check.ok:
        raise SystemExit(f"disk-budget check failed before {label!r}: {list(check.violations)}")
    return check.to_dict()


def _index_capable(*, allow_mapping: bool, host_role: str, reference: Path | None) -> str | None:
    """Same basic capability shape as ``_mapping_capable`` but for index
    preparation, which needs a reference but not a reads FASTA.
    """
    if not allow_mapping or host_role != APPROVED_MAC:
        return (
            "index preparation requires --allow-mapping together with --host-role=approved_mac "
            f"(got allow_mapping={allow_mapping}, host_role={host_role!r})"
        )
    if reference is None or not Path(reference).is_file():
        return f"reference FASTA not found or not provided ({reference})"
    return None


def stage_index(
    cfg: FeasibilityConfig,
    *,
    build: str,
    index_dir: Path,
    allow_mapping: bool,
    host_role: str,
    threads: int,
    reference: Path | None,
    reference_manifest: dict | None,
    dry_run: bool,
    disk_ledger: DiskBudgetLedger | None = None,
) -> dict:
    """Prepare the build-specific BWA index prefix and minimap2 ``.mmi`` index
    under ``index_dir`` (the pinned ``indices/<build>/`` directory), with
    creation-time provenance (commands, output-file hashes/sizes, elapsed
    time, peak memory) and minimap2's resolved-parameter/single-part
    verification. Gated identically to ``stage_align``/``stage_exact_match``:
    ``--dry-run`` is an absolute guard checked first, then the same
    allow-mapping/host-role/reference-manifest/fresh-preflight chain.
    """
    bwa_prefix = index_dir / build
    mm2_index = index_dir / f"{build}.mmi"
    record = {
        "planned_commands": {
            "bwa_index": format_command(("bwa", "index", "-p", str(bwa_prefix), str(reference or Path("reference.fasta")))),
            "minimap2_index": format_command(
                ("minimap2", "-x", "splice:sr", "-I", "8G", "-d", str(mm2_index), str(reference or Path("reference.fasta")))
            ),
        },
        "executed": False,
        "skip_reason": None,
    }

    if dry_run:
        record["skip_reason"] = "--dry-run: real index preparation is never executed under --dry-run"
        _guarded_write_record(index_dir / "index.json", record)
        return record

    skip_reason = _index_capable(allow_mapping=allow_mapping, host_role=host_role, reference=reference)
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
        _guarded_write_record(index_dir / "index.json", record)
        return record

    if reference_manifest is None:
        record["skip_reason"] = f"reference manifest required for index preparation but not provided for build {build!r}"
        _write_json(index_dir / "index.json", record)
        return record
    record["reference_manifest"] = reference_manifest
    manifest_violations = validate_reference_manifest(reference_manifest, build=build, reference=reference)
    record["reference_manifest_validation"] = {"provided": True, "violations": list(manifest_violations)}
    if manifest_violations:
        record["skip_reason"] = f"reference manifest invalid for build {build!r}: {list(manifest_violations)}"
        _write_json(index_dir / "index.json", record)
        return record

    index_dir.mkdir(parents=True, exist_ok=True)
    preflight_report = run_preflight(
        host_role=host_role,
        resources=cfg.resources,
        disk_path=index_dir,
        allow_mapping=True,
        tools=cfg.tools,
        threads=threads,
        required_input_paths={"reference": reference},
    )
    _write_json(index_dir / "preflight_at_index_time.json", preflight_report.to_dict())
    record["preflight_ok"] = preflight_report.ok
    if not preflight_report.ok:
        record["skip_reason"] = f"preflight failed closed immediately before indexing: {list(preflight_report.violations)}"
        _write_json(index_dir / "index.json", record)
        return record

    _check_disk_budget_or_fail(
        disk_ledger,
        label=f"bwa_index:{build}",
        allowance_gib=PLANNED_ALLOWANCES_GIB["active_build_bwa_index"],
        disk_path=index_dir,
    )
    bwa_provenance = prepare_bwa_index(reference, bwa_prefix)
    if disk_ledger is not None:
        disk_ledger.record_step(f"bwa_index:{build}", path=index_dir)

    _check_disk_budget_or_fail(
        disk_ledger,
        label=f"minimap2_index:{build}",
        allowance_gib=PLANNED_ALLOWANCES_GIB["active_build_minimap2_index"],
        disk_path=index_dir,
    )
    mm2_provenance = prepare_minimap2_index(reference, mm2_index)
    if disk_ledger is not None:
        disk_ledger.record_step(f"minimap2_index:{build}", path=index_dir)

    manifest = build_index_manifest(build=build, bwa=bwa_provenance, minimap2=mm2_provenance)
    _write_json(index_dir / "index_manifest.json", manifest)

    record["executed"] = True
    record["bwa_index_prefix"] = str(bwa_prefix)
    record["minimap2_index"] = str(mm2_index)
    record["index_manifest_path"] = str(index_dir / "index_manifest.json")
    _guarded_write_record(index_dir / "index.json", record)
    return record


def stage_align(
    cfg: FeasibilityConfig,
    *,
    build: str,
    build_output_dir: Path,
    allow_mapping: bool,
    host_role: str,
    threads: int,
    reference: Path | None,
    reference_manifest: dict | None,
    reads_fasta: Path | None,
    dry_run: bool,
    bwa_index_prefix: Path | None = None,
    minimap2_index: Path | None = None,
    disk_ledger: DiskBudgetLedger | None = None,
) -> dict:
    placeholder_ref = reference or Path("reference.fasta")
    placeholder_reads = reads_fasta or Path("sample_sequences.fasta")
    # bwa mem takes the prepared build-specific index *prefix* (never the
    # bare FASTA) once one has been built by the `index` stage; minimap2
    # likewise takes the prepared `.mmi` in place of the FASTA when
    # available. SeqKit, manifest validation, and the junction-lookup
    # reference reader continue to use the plain FASTA (see stage_exact_match
    # and stage_report) regardless of whether indices were prepared.
    bwa_ref_arg = bwa_index_prefix or placeholder_ref
    mm2_ref_arg = minimap2_index or placeholder_ref
    bwa_cmd = bwa_mem_command(bwa_ref_arg, placeholder_reads, threads=threads)
    mm2_cmd = minimap2_splice_command(mm2_ref_arg, placeholder_reads, threads=threads)

    record = {
        "planned_commands": {
            "bwa_mem": format_command(bwa_cmd.argv),
            "minimap2_splice": format_command(mm2_cmd.argv),
        },
        "executed": False,
        "skip_reason": None,
    }

    # Absolute guard, checked before anything else: --dry-run guarantees no
    # external mapping subprocess can ever execute, regardless of whatever
    # other authorization flags were also given.
    if dry_run:
        record["skip_reason"] = "--dry-run: real mapping is never executed under --dry-run"
        _guarded_write_record(build_output_dir / "align.json", record)
        return record

    skip_reason = _mapping_capable(
        allow_mapping=allow_mapping, host_role=host_role, reference=reference, reads_fasta=reads_fasta
    )
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
        _guarded_write_record(build_output_dir / "align.json", record)
        return record

    # A reference manifest is now required (not merely recorded when
    # present) for real mapping, and validated against the exact reference
    # file this run is about to use — a stale or wrong-build manifest must
    # never be silently attributed to the current reference.
    if reference_manifest is None:
        record["skip_reason"] = f"reference manifest required for real mapping but not provided for build {build!r}"
        _write_json(build_output_dir / "align.json", record)
        return record
    # Persisted regardless of validation outcome: provenance reads this
    # back (rather than whatever --reference-manifest happens to be passed
    # on a *later* invocation) so a report already on disk is never
    # attributed to a manifest it was not actually produced under.
    record["reference_manifest"] = reference_manifest
    manifest_violations = validate_reference_manifest(reference_manifest, build=build, reference=reference)
    record["reference_manifest_validation"] = {"provided": True, "violations": list(manifest_violations)}
    if manifest_violations:
        record["skip_reason"] = f"reference manifest invalid for build {build!r}: {list(manifest_violations)}"
        _write_json(build_output_dir / "align.json", record)
        return record

    # Stale/foreign-index rejection (B1 required item 4): when a prepared
    # index is being used, its creation-time manifest is re-verified against
    # the files on disk right now — never trusted merely because the index
    # stage completed at some point in the past.
    index_dir = (bwa_index_prefix or minimap2_index).parent if (bwa_index_prefix or minimap2_index) else None
    if index_dir is not None:
        index_manifest_path = index_dir / "index_manifest.json"
        if not index_manifest_path.is_file():
            record["skip_reason"] = f"no index manifest found at {index_manifest_path} for the prepared index"
            _write_json(build_output_dir / "align.json", record)
            return record
        index_manifest = json.loads(index_manifest_path.read_text())
        index_violations: list[str] = []
        if bwa_index_prefix is not None:
            index_violations.extend(verify_index_files_against_manifest(index_manifest, key="bwa_index"))
        if minimap2_index is not None:
            index_violations.extend(verify_index_files_against_manifest(index_manifest, key="minimap2_index"))
        record["index_manifest_validation"] = {"violations": list(index_violations)}
        if index_violations:
            record["skip_reason"] = f"prepared index failed manifest verification (stale/foreign index): {index_violations}"
            _write_json(build_output_dir / "align.json", record)
            return record

    # Hard prerequisite (never bypassable by tests or callers): a *fresh*
    # preflight bound to the detected OS/architecture, resource limits,
    # pinned tool versions, and hashes of this exact reference/reads pair,
    # not merely the declared host_role/allow_mapping flags checked above.
    build_output_dir.mkdir(parents=True, exist_ok=True)
    preflight_report = run_preflight(
        host_role=host_role,
        resources=cfg.resources,
        disk_path=build_output_dir,
        allow_mapping=True,
        tools=cfg.tools,
        threads=threads,
        required_input_paths={"reference": reference, "reads": reads_fasta},
    )
    _write_json(build_output_dir / "preflight_at_align_time.json", preflight_report.to_dict())
    record["preflight_ok"] = preflight_report.ok
    if not preflight_report.ok:
        record["skip_reason"] = f"preflight failed closed immediately before mapping: {list(preflight_report.violations)}"
        _write_json(build_output_dir / "align.json", record)
        return record

    # Fail-closed disk-budget check (B1 required item 8): both mapper output
    # writers share the build's combined SAM/BED/report allowance, checked
    # once before either subprocess starts.
    disk_budget_check = _check_disk_budget_or_fail(
        disk_ledger, label=f"align:{build}", allowance_gib=BUILD_OUTPUT_ALLOWANCE_GIB, disk_path=build_output_dir
    )

    bwa_binary = resolve_binary_provenance("bwa", version=preflight_report.tool_versions.get("bwa"))
    mm2_binary = resolve_binary_provenance("minimap2", version=preflight_report.tool_versions.get("minimap2"))

    bwa_sam = build_output_dir / "align_bwa_mem.sam"
    bwa_stderr = build_output_dir / "align_bwa_mem.stderr.log"
    mm2_sam = build_output_dir / "align_minimap2_splice.sam"
    mm2_stderr = build_output_dir / "align_minimap2_splice.stderr.log"
    bwa_provenance = run_tool_with_provenance(
        bwa_cmd.argv,
        tool="bwa_mem",
        output_path=bwa_sam,
        stderr_path=bwa_stderr,
        command_text=format_command(bwa_cmd.argv),
        binary=bwa_binary,
        run_fn=_run_tool_to_file,
    )
    mm2_provenance = run_tool_with_provenance(
        mm2_cmd.argv,
        tool="minimap2_splice",
        output_path=mm2_sam,
        stderr_path=mm2_stderr,
        command_text=format_command(mm2_cmd.argv),
        binary=mm2_binary,
        run_fn=_run_tool_to_file,
    )
    if disk_ledger is not None:
        disk_ledger.record_step(f"align:{build}", path=build_output_dir)

    record["executed"] = True
    record["tool_versions"] = {"bwa": bwa_binary.version, "minimap2": mm2_binary.version}
    record["sam_paths"] = {"bwa_mem": str(bwa_sam), "minimap2_splice": str(mm2_sam)}
    record["index_paths"] = {
        "bwa_index_prefix": str(bwa_index_prefix) if bwa_index_prefix else None,
        "minimap2_index": str(minimap2_index) if minimap2_index else None,
    }
    record["disk_budget_check"] = disk_budget_check
    record["provenance"] = {
        "input_hashes": preflight_report.input_hashes,
        "bwa_mem": bwa_provenance.to_dict(),
        "minimap2_splice": mm2_provenance.to_dict(),
    }
    _guarded_write_record(build_output_dir / "align.json", record)
    return record


def stage_exact_match(
    cfg: FeasibilityConfig,
    *,
    build: str,
    build_output_dir: Path,
    allow_mapping: bool,
    host_role: str,
    threads: int,
    reference: Path | None,
    reference_manifest: dict | None,
    reads_fasta: Path | None,
    align_record: dict,
    dry_run: bool,
    disk_ledger: DiskBudgetLedger | None = None,
) -> dict:
    placeholder_query = reads_fasta or Path("sample_sequences.fasta")
    placeholder_ref = reference or Path("reference.fasta")
    cmd = seqkit_locate_command(placeholder_query, placeholder_ref)
    record = {
        "planned_command": format_command(cmd.argv),
        "executed": False,
        "skip_reason": "Task 001A never runs exact-match search against a real reference",
    }

    # Same absolute --dry-run guard as stage_align, checked first.
    if dry_run:
        record["skip_reason"] = "--dry-run: real exact-match search is never executed under --dry-run"
        _guarded_write_record(build_output_dir / "exact_match.json", record)
        return record

    skip_reason = _mapping_capable(
        allow_mapping=allow_mapping, host_role=host_role, reference=reference, reads_fasta=reads_fasta
    )
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
        _guarded_write_record(build_output_dir / "exact_match.json", record)
        return record

    if not align_record.get("executed"):
        record["skip_reason"] = "align stage did not execute real mapping; nothing to confirm"
        _write_json(build_output_dir / "exact_match.json", record)
        return record

    # Same reference-manifest requirement/validation as stage_align — an
    # independent check, not a reused one.
    if reference_manifest is None:
        record["skip_reason"] = f"reference manifest required for real exact-match but not provided for build {build!r}"
        _write_json(build_output_dir / "exact_match.json", record)
        return record
    record["reference_manifest"] = reference_manifest
    manifest_violations = validate_reference_manifest(reference_manifest, build=build, reference=reference)
    record["reference_manifest_validation"] = {"provided": True, "violations": list(manifest_violations)}
    if manifest_violations:
        record["skip_reason"] = f"reference manifest invalid for build {build!r}: {list(manifest_violations)}"
        _write_json(build_output_dir / "exact_match.json", record)
        return record

    # Same hard, fresh preflight prerequisite as stage_align — exact-match
    # search gets its own independent binding check, not a reused one.
    build_output_dir.mkdir(parents=True, exist_ok=True)
    preflight_report = run_preflight(
        host_role=host_role,
        resources=cfg.resources,
        disk_path=build_output_dir,
        allow_mapping=True,
        tools=cfg.tools,
        threads=threads,
        required_input_paths={"reference": reference, "reads": reads_fasta},
    )
    _write_json(build_output_dir / "preflight_at_exact_match_time.json", preflight_report.to_dict())
    record["preflight_ok"] = preflight_report.ok
    if not preflight_report.ok:
        record["skip_reason"] = f"preflight failed closed immediately before exact-match: {list(preflight_report.violations)}"
        _write_json(build_output_dir / "exact_match.json", record)
        return record

    disk_budget_check = _check_disk_budget_or_fail(
        disk_ledger, label=f"exact_match:{build}", allowance_gib=BUILD_OUTPUT_ALLOWANCE_GIB, disk_path=build_output_dir
    )

    seqkit_binary = resolve_binary_provenance("seqkit", version=preflight_report.tool_versions.get("seqkit"))

    bed_path = build_output_dir / "exact_match_hits.bed"
    stderr_path = build_output_dir / "exact_match_hits.stderr.log"
    query_cmd = seqkit_locate_command(reads_fasta, reference)
    provenance = run_tool_with_provenance(
        query_cmd.argv,
        tool="seqkit_locate",
        output_path=bed_path,
        stderr_path=stderr_path,
        command_text=format_command(query_cmd.argv),
        binary=seqkit_binary,
        run_fn=_run_tool_to_file,
    )
    if disk_ledger is not None:
        disk_ledger.record_step(f"exact_match:{build}", path=build_output_dir)

    record["executed"] = True
    record["tool_version"] = seqkit_binary.version
    record["bed_path"] = str(bed_path)
    record["disk_budget_check"] = disk_budget_check
    record["provenance"] = {
        "input_hashes": preflight_report.input_hashes,
        "seqkit_locate": provenance.to_dict(),
    }
    _guarded_write_record(build_output_dir / "exact_match.json", record)
    return record


def _group_records_by_query(sam_path: Path) -> dict[str, list[AlignmentRecord]]:
    grouped: dict[str, list[AlignmentRecord]] = {}
    with sam_path.open() as handle:
        for line in handle:
            record = parse_sam_line(line)
            if record is None:
                continue
            grouped.setdefault(record.query_name, []).append(record)
    return grouped


def _locus_detail(locus: CandidateLocus | None) -> dict:
    if locus is None:
        return {
            "chrom": "",
            "start": "",
            "end": "",
            "strand": "",
            "block_count": 0,
            "block_starts": "",
            "block_sizes": "",
            "coverage": "",
            "identity": "",
            "mapq": "",
            "alignment_score": "",
            "intron_lengths": "",
            "canonical_junctions": "",
        }
    # ``locus.blocks`` is ordered by template (read) position, which for a
    # '-' strand locus runs in *descending* genomic order (see
    # blocks_from_record's strand-flip). Serializing start/end/block_starts
    # straight from that order can yield start > end and out-of-order BED
    # blocks for a reverse-strand split mapping; genomic order is required
    # regardless of strand, with strand retained only in the ``strand`` field.
    genomic_blocks = sorted(locus.blocks, key=lambda b: b.ref_start)
    return {
        "chrom": locus.chrom,
        "start": genomic_blocks[0].ref_start,
        "end": genomic_blocks[-1].ref_end,
        "strand": locus.strand,
        "block_count": locus.block_count,
        "block_starts": ";".join(str(b.ref_start) for b in genomic_blocks),
        "block_sizes": ";".join(str(b.ref_end - b.ref_start) for b in genomic_blocks),
        "coverage": f"{locus.coverage:.6f}",
        "identity": f"{locus.identity:.6f}",
        "mapq": locus.mapq,
        "alignment_score": locus.as_score if locus.as_score is not None else "",
        "intron_lengths": ";".join(str(length) for length in locus.intron_lengths),
        "canonical_junctions": ";".join(
            "" if canonical is None else ("1" if canonical else "0") for canonical in locus.junction_is_canonical
        ),
    }


def _prefixed_locus_detail(locus: CandidateLocus | None, prefix: str) -> dict:
    """Full best-secondary evidence (coordinates, strand, blocks, MAPQ, and
    alignment score — not merely chrom/coverage/identity), so an ambiguous
    call is auditable against exactly what the plausible secondary locus
    looked like.
    """
    return {f"{prefix}{key}": value for key, value in _locus_detail(locus).items()}


def _near_tied_field(loci: Sequence[CandidateLocus], fractions: Sequence[float]) -> str:
    triggered = near_tied_secondary_fractions(loci, fractions)
    return ";".join(f"{fraction:g}" for fraction, is_triggered in triggered.items() if is_triggered)


def build_mapping_rows(
    cfg: FeasibilityConfig,
    expected_ids: dict[str, str],
    *,
    build: str,
    bwa_sam: Path,
    minimap2_sam: Path,
    exact_hits_bed: Path | None,
    reference_lookup=None,
) -> tuple[tuple[MappingResult, ...], list[dict]]:
    """Parse real SAM/BED output into (reconciliation results, TSV rows).

    ``expected_ids`` maps every sample/control ID that was actually submitted
    to the mappers (its stratum, or ``"control"``) and drives row
    construction: a query unmapped by *both* BWA-MEM and minimap2 never
    appears in either tool's SAM output (``parse_sam_line`` returns ``None``
    for an unmapped record), so deriving the query universe from the SAM
    dictionaries alone would silently drop it instead of emitting an
    ``unmapped`` row in both modes.

    Only ever called after ``align``/``exact_match`` actually executed; never
    invoked against the real 724-MB dataset or a human reference from this
    task's own tests (see module docstring).
    """
    thresholds = cfg.thresholds
    total_query = cfg.sequence_length_nt
    bwa_by_query = _group_records_by_query(bwa_sam)
    mm2_by_query = _group_records_by_query(minimap2_sam)
    exact_occurrences = (
        parse_seqkit_bed(exact_hits_bed.read_text().splitlines())
        if exact_hits_bed is not None and exact_hits_bed.is_file()
        else {}
    )

    query_ids = sorted(set(expected_ids) | set(bwa_by_query) | set(mm2_by_query))
    results: list[MappingResult] = []
    rows: list[dict] = []

    for sample_id in query_ids:
        is_control = sample_id.startswith(CONTROL_ID_PREFIX)
        stratum = expected_ids.get(sample_id, "control" if is_control else "")

        primary_loci = build_candidate_loci(
            bwa_by_query.get(sample_id, ()), total_query_bases=total_query, reference_lookup=reference_lookup
        )
        splice_loci = build_candidate_loci(
            mm2_by_query.get(sample_id, ()), total_query_bases=total_query, reference_lookup=reference_lookup
        )

        # bwa_best_is_perfect is a diagnostic only: the best locus alone
        # being 100% coverage/identity does not by itself mean BWA-MEM
        # considers the read uniquely mapped — a second, equally perfect
        # locus makes the call ambiguous. bwa_perfect_unique_candidate adds
        # exactly that check, so it (not bwa_best_is_perfect) is the correct
        # field for exact-match discordance auditing and for confirming
        # exact uniqueness against SeqKit.
        bwa_best_is_perfect = bool(primary_loci) and primary_loci[0].coverage == 1.0 and primary_loci[0].identity == 1.0
        if primary_loci and bwa_best_is_perfect:
            bwa_perfect_unique_candidate = not has_plausible_distinct_secondary(
                primary_loci[0], primary_loci[1:], thresholds
            )
        else:
            bwa_perfect_unique_candidate = False
        occurrence_count = exact_occurrence_count(exact_occurrences, sample_id)
        exact_confirmed = exact_unique_confirmed(
            primary_is_perfect_unique=bwa_perfect_unique_candidate, occurrence_count=occurrence_count
        )

        primary_category = classify_primary(primary_loci, thresholds, exact_confirmed=exact_confirmed)
        results.append(MappingResult(sample_id, is_control, build, "primary", primary_category))
        best_primary = primary_loci[0] if primary_loci else None
        second_primary = primary_loci[1] if len(primary_loci) > 1 else None
        row = {
            "sample_id": sample_id,
            "is_control": is_control,
            "stratum": stratum,
            "build": build,
            "mode": "primary",
            "category": primary_category,
            # Exact-match evidence (BWA-vs-SeqKit): persisted regardless of
            # the classification outcome so discordance is auditable, not
            # just implied by which category a row landed in.
            "exact_occurrence_count": occurrence_count,
            "bwa_best_is_perfect": bwa_best_is_perfect,
            "bwa_perfect_unique_candidate": bwa_perfect_unique_candidate,
        }
        row.update(_locus_detail(best_primary))
        row.update(_prefixed_locus_detail(second_primary, "best_secondary_"))
        row["near_tied_fractions"] = _near_tied_field(primary_loci, cfg.near_tied_fractions)
        rows.append(row)

        splice_category = classify_splice(splice_loci, thresholds)
        results.append(MappingResult(sample_id, is_control, build, "splice", splice_category))
        best_splice = splice_loci[0] if splice_loci else None
        second_splice = splice_loci[1] if len(splice_loci) > 1 else None
        row = {
            "sample_id": sample_id,
            "is_control": is_control,
            "stratum": stratum,
            "build": build,
            "mode": "splice",
            "category": splice_category,
            # Exact-substring validation only ever applies to the primary
            # (BWA-MEM) mode; not applicable to the splice-aware diagnostic.
            "exact_occurrence_count": "",
            "bwa_best_is_perfect": "",
            "bwa_perfect_unique_candidate": "",
        }
        row.update(_locus_detail(best_splice))
        row.update(_prefixed_locus_detail(second_splice, "best_secondary_"))
        row["near_tied_fractions"] = _near_tied_field(splice_loci, cfg.near_tied_fractions)
        rows.append(row)

    return tuple(results), rows


def write_mappings_tsv_gz(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MAPPING_TSV_COLUMNS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_mappings_tsv_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def stage_report(
    sample: SamplingResult,
    *,
    cfg: FeasibilityConfig,
    build_output_dir: Path,
    expected_total: int,
    expected_representative: int,
    expected_controls: int,
    build: str,
    align_record: dict,
    exact_match_record: dict,
    reference: Path | None,
) -> dict:
    mapping_evaluated = bool(align_record.get("executed")) and bool(exact_match_record.get("executed"))
    mapping_results: tuple[MappingResult, ...] = ()
    expected_control_ids: tuple[str, ...] = ()

    if mapping_evaluated:
        representative_ids = sorted(sample.representative_ids)
        expected_control_ids = tuple(f"{CONTROL_ID_PREFIX}{sid}" for sid in representative_ids[: expected_controls])
        expected_ids = {a.sample_id: a.stratum for a in sample.assignments}
        for control_id in expected_control_ids:
            expected_ids[control_id] = "control"

        reference_lookup = None
        if reference is not None and Path(reference).is_file():
            # Indexed random access (never a whole-file load): suitable for
            # an hg38/hg19-scale reference, since only a single sequential
            # pass builds the index and every lookup thereafter seeks
            # directly to the requested span.
            index_entries, index_record = prepare_reference_index(Path(reference))
            _write_json(build_output_dir / "reference_index.json", index_record)
            reference_lookup = IndexedFastaReader(Path(reference), index_entries).fetch

        mapping_results, rows = build_mapping_rows(
            cfg,
            expected_ids,
            build=build,
            bwa_sam=Path(align_record["sam_paths"]["bwa_mem"]),
            minimap2_sam=Path(align_record["sam_paths"]["minimap2_splice"]),
            exact_hits_bed=Path(exact_match_record["bed_path"]) if exact_match_record.get("bed_path") else None,
            reference_lookup=reference_lookup,
        )
        write_mappings_tsv_gz(build_output_dir / Path(cfg.outputs.mappings_tsv_gz).name, rows)

    reconciliation = reconcile_counts(
        sample.assignments,
        mapping_results,
        expected_total=expected_total,
        expected_representative=expected_representative,
        expected_controls=expected_controls,
        mapping_evaluated=mapping_evaluated,
        expected_control_ids=expected_control_ids,
        expected_builds=(build,) if mapping_evaluated else (),
        expected_modes=("primary", "splice") if mapping_evaluated else (),
    )
    report = build_report(sample.assignments, mapping_results, reconciliation=reconciliation)
    _write_json(build_output_dir / Path(cfg.outputs.report_json).name, report)
    (build_output_dir / Path(cfg.outputs.report_md).name).write_text(render_markdown(report))
    return report


def stage_combined_report(
    sample: SamplingResult,
    *,
    cfg: FeasibilityConfig,
    output_dir: Path,
    builds: Sequence[str],
    reference_manifests: dict[str, dict] | None = None,
) -> dict:
    """Collision-safe per-build artifacts already exist under
    ``output_dir/<build>/``; this reads every one of them back from disk (the
    same resume-safety pattern as align/exact_match reloading) and produces
    the single combined report the parent task requires before Task 001B.
    """
    reference_manifests = reference_manifests or {}
    sample_meta = [{"sample_id": a.sample_id, "labels": ";".join(str(v) for v in a.labels)} for a in sample.assignments]
    representative_ids = sorted(sample.representative_ids)
    all_sample_ids = sorted(a.sample_id for a in sample.assignments)
    sample_sequences = _read_fasta(output_dir / "sample_sequences.fasta")

    per_build_summaries: dict[str, dict] = {}
    per_build_primary_by_id: dict[str, dict] = {}
    evaluated_builds: list[str] = []
    for build in builds:
        build_dir = _build_dir(output_dir, build)
        report_path = build_dir / Path(cfg.outputs.report_json).name
        if not report_path.exists():
            raise SystemExit(
                f"combined_report requires {report_path} to exist; run the 'report' stage for build {build!r} first"
            )
        build_report_payload = json.loads(report_path.read_text())
        # A dry run, or a run that never authorized real mapping, produces a
        # per-build report whose reconciliation is honestly "not_evaluated"
        # (see rbpbench.coordinates.report): there is no mapping data to
        # summarize yet, so record that plainly rather than raising or
        # fabricating an empty-but-"passed"-looking summary.
        status = build_report_payload["reconciliation"]["status"]
        if status == "not_evaluated":
            per_build_summaries[build] = {"build": build, "mapping_evaluated": False}
            continue
        if status == "failed":
            # An evaluated-but-failed reconciliation means the per-build
            # mapping/category counts are internally inconsistent: combining
            # it into one report would launder that inconsistency into a
            # report that looks trustworthy. Stop clearly instead.
            raise SystemExit(
                f"combined_report refuses to finalize: build {build!r} reconciliation failed "
                f"({build_report_payload['reconciliation']['issues']})"
            )

        mappings_path = build_dir / Path(cfg.outputs.mappings_tsv_gz).name
        rows = read_mappings_tsv_gz(mappings_path)
        primary_rows = [r for r in rows if r["mode"] == "primary"]
        splice_rows = [r for r in rows if r["mode"] == "splice"]
        contig_categories = (reference_manifests.get(build) or {}).get("contig_categories")
        summary = summaries.build_per_build_summary(
            build=build,
            primary_rows=primary_rows,
            splice_rows=splice_rows,
            representative_ids=representative_ids,
            all_sample_ids=all_sample_ids,
            sample_meta=sample_meta,
            sample_sequences=sample_sequences,
            near_tied_fractions=cfg.near_tied_fractions,
            contig_categories=contig_categories,
        )
        per_build_summaries[build] = summary
        per_build_primary_by_id[build] = summaries.exclude_controls(
            summaries.index_rows_by_sample(primary_rows, mode="primary")
        )
        evaluated_builds.append(build)

    comparison = (
        summaries.compare_builds(
            {b: per_build_summaries[b] for b in evaluated_builds},
            {b: per_build_primary_by_id[b] for b in evaluated_builds},
        )
        if len(evaluated_builds) >= 2
        else {}
    )
    combined = build_combined_report(builds, per_build_summaries, comparison)
    _write_json(output_dir / Path(cfg.outputs.report_json).name, combined)
    (output_dir / Path(cfg.outputs.report_md).name).write_text(render_combined_report_markdown(combined))
    return combined


def _artifact_hash(path: Path) -> dict | None:
    """Hash-and-size a generated or declared artifact, or ``None`` (never a
    fabricated placeholder) when it does not exist.
    """
    if not path.is_file():
        return None
    return {"path": str(path), "sha256": sha256_file(path), "byte_size": path.stat().st_size}


def _write_provenance(
    *,
    cfg: FeasibilityConfig,
    output_dir: Path,
    csv_path: Path,
    config_path: Path,
    dataset_audit_path: Path | None,
    proteins_config_path: Path | None,
    builds: Sequence[str],
    index_records: dict[str, dict],
    align_records: dict[str, dict],
    exact_match_records: dict[str, dict],
    reference_manifests: dict[str, dict],
    state: dict,
    disk_ledger: DiskBudgetLedger | None = None,
) -> dict:
    """Connect provenance to the runner: declared input hashes (dataset CSV,
    config, dataset audit, protein config), resolved binary hashes/versions,
    commands, index commands/parameters/sizes/hashes, output hashes, elapsed
    time, peak memory, and reference-manifest metadata, all in one place per
    run. Bound to the current restart-state fingerprints (see
    ``state["stage_fingerprints"]``) so a reader can tell whether these
    outputs actually correspond to the current inputs rather than a stale
    prior run. Written unconditionally (cheap, idempotent) so it always
    reflects whatever align/exact_match records the current invocation has,
    whichever stages it actually ran.
    """
    declared_inputs = {
        "dataset_csv": _artifact_hash(csv_path),
        "config": _artifact_hash(config_path),
        "dataset_audit": _artifact_hash(dataset_audit_path) if dataset_audit_path is not None else None,
        "proteins_config": _artifact_hash(proteins_config_path) if proteins_config_path is not None else None,
    }
    generated_artifacts = {
        "sample_ids_tsv": _artifact_hash(output_dir / Path(cfg.outputs.sample_ids_tsv).name),
        "sample_sequences_fasta": _artifact_hash(output_dir / "sample_sequences.fasta"),
        "control_sequences_fasta": _artifact_hash(output_dir / "control_sequences.fasta"),
        "combined_report_json": _artifact_hash(output_dir / Path(cfg.outputs.report_json).name),
        "combined_report_md": _artifact_hash(output_dir / Path(cfg.outputs.report_md).name),
    }

    builds_payload = {}
    for build in builds:
        build_dir = _build_dir(output_dir, build)
        reference_index_path = build_dir / "reference_index.json"
        builds_payload[build] = {
            "index": index_records.get(build, {}),
            "align": align_records.get(build, {}),
            "exact_match": exact_match_records.get(build, {}),
            "reference_manifest": reference_manifests.get(build),
            "reference_index": json.loads(reference_index_path.read_text()) if reference_index_path.exists() else None,
            "generated_artifacts": {
                "mappings_tsv_gz": _artifact_hash(build_dir / Path(cfg.outputs.mappings_tsv_gz).name),
                "report_json": _artifact_hash(build_dir / Path(cfg.outputs.report_json).name),
                "report_md": _artifact_hash(build_dir / Path(cfg.outputs.report_md).name),
            },
        }

    payload = {
        "schema_version": 2,
        "declared_inputs": declared_inputs,
        "generated_artifacts": generated_artifacts,
        "builds": builds_payload,
        # Binds this provenance to the exact restart-state fingerprints that
        # decided which stages actually ran (see _stage_is_valid/
        # _mark_stage_complete): current inputs cannot be silently
        # attributed to stale outputs from a previous, differing run.
        "state_fingerprints": dict(state.get("stage_fingerprints", {})),
        "disk_budget": disk_ledger.to_dict() if disk_ledger is not None else None,
    }
    _write_json(output_dir / "provenance.json", payload)
    return payload


def _parse_key_value_path(spec: str, *, flag: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise SystemExit(f"{flag} expects BUILD=PATH, got {spec!r}")
    build, _, raw_path = spec.partition("=")
    if not build or not raw_path:
        raise SystemExit(f"{flag} expects BUILD=PATH, got {spec!r}")
    return build, Path(raw_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/coordinate_feasibility.toml"))
    parser.add_argument("--csv", type=Path, required=True, help="Tiny fixture CSV; never the real 724-MB dataset")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stage", action="append", choices=[*STAGES, "all"], default=None)
    parser.add_argument("--force", action="store_true", help="Re-run stages already marked complete")
    parser.add_argument("--allow-mapping", action="store_true", help="Required (with --host-role=approved_mac) before any real mapping")
    parser.add_argument("--host-role", choices=(DEV_VM, APPROVED_MAC), default=DEV_VM)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument(
        "--reference",
        action="append",
        default=None,
        metavar="BUILD=PATH",
        help="Reference FASTA for one build, e.g. --reference hg38=/path/hg38.fa; repeat per build",
    )
    parser.add_argument(
        "--reference-manifest",
        action="append",
        default=None,
        metavar="BUILD=PATH",
        help="Optional JSON reference-manifest metadata for one build (see rbpbench.coordinates.manifest)",
    )
    parser.add_argument(
        "--build",
        action="append",
        default=None,
        help=f"Reference build ID(s) to process; repeat per build (default: {', '.join(DEFAULT_BUILDS)})",
    )
    parser.add_argument(
        "--dataset-audit",
        type=Path,
        default=Path("manifests/dataset_audit.json"),
        help="Declared-input path to hash into provenance.json (parent-task dataset audit manifest)",
    )
    parser.add_argument(
        "--proteins-config",
        type=Path,
        default=Path("configs/proteins.tsv"),
        help="Declared-input path to hash into provenance.json (parent-task protein configuration)",
    )
    parser.add_argument(
        "--execution-sources",
        type=Path,
        default=None,
        help=(
            "Path to a checked-in execution-source spec (see "
            "rbpbench.coordinates.execution_sources); when given, its four frozen local-input "
            "hashes are compared against --csv/--dataset-audit/--proteins-config/--config before "
            "the CSV is opened for row-by-row reading, failing closed on any mismatch. Required "
            "for a real Task 001B run against configs/coordinate_execution_sources.toml; omitted "
            "by 001A fixture-only tests, which use hashes that intentionally do not match it."
        ),
    )
    parser.add_argument(
        "--indices-dir",
        type=Path,
        default=Path("indices"),
        help="Pinned root for disposable per-build mapper indices (indices/<build>/)",
    )
    parser.add_argument(
        "--bwa-index-prefix",
        action="append",
        default=None,
        metavar="BUILD=PATH",
        help="Override the default indices/<build>/<build> BWA index prefix for one build",
    )
    parser.add_argument(
        "--minimap2-index",
        action="append",
        default=None,
        metavar="BUILD=PATH",
        help="Override the default indices/<build>/<build>.mmi minimap2 index path for one build",
    )
    parser.add_argument(
        "--disk-budget-path",
        type=Path,
        default=Path("."),
        help="Filesystem volume to measure the disk-budget ledger's baseline/free-space against",
    )
    parser.add_argument(
        "--cleanup-index",
        default=None,
        metavar="BUILD",
        help=(
            "Remove indices/<build>/ for exactly this build and exit, after confirming index "
            "provenance, successful mapping outputs, and a passed reconciliation are all already "
            "recorded on disk; refuses (deleting nothing) otherwise. Bypasses --stage entirely."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Guarantee no external tool ever executes; plan commands only")
    return parser


def _stage_key(stage: str, build: str | None) -> str:
    return f"{stage}:{build}" if build is not None else stage


def _mark_stage_complete(state: dict, key: str, fingerprint: str) -> None:
    if key not in state["completed_stages"]:
        state["completed_stages"].append(key)
    state.setdefault("stage_fingerprints", {})[key] = fingerprint


def _stage_is_valid(state: dict, key: str, fingerprint: str) -> bool:
    """Restart-state validity check (review item 1): a stage is only
    skippable when it was both previously marked complete *and* its
    fingerprint (the declared inputs/config/reference/authorization it would
    run with right now) still matches what produced that completion. A
    planning-only (unauthorized or dry-run) attempt's fingerprint always
    differs from a later authorized real attempt's, so it can never block
    that later real run merely by being "in completed_stages".
    """
    if key not in state["completed_stages"]:
        return False
    return state.get("stage_fingerprints", {}).get(key) == fingerprint


def _run_cleanup_index(cfg: FeasibilityConfig, *, build: str, indices_dir: Path, output_dir: Path) -> None:
    """``--cleanup-index BUILD`` entry point (B1 required item 8 / R2):
    resolve exactly what evidence already exists on disk for ``build`` and
    delegate the actual safety checks to
    :func:`rbpbench.coordinates.cleanup.execute_index_cleanup`, which refuses
    (deleting nothing) unless index provenance, successful mapping outputs,
    and a passed reconciliation are all already recorded.
    """
    index_dir = indices_dir / build
    build_dir = _build_dir(output_dir, build)
    index_manifest_present = (index_dir / "index_manifest.json").is_file()

    align_path = build_dir / "align.json"
    exact_path = build_dir / "exact_match.json"
    report_path = build_dir / Path(cfg.outputs.report_json).name
    align_record = json.loads(align_path.read_text()) if align_path.exists() else {}
    exact_match_record = json.loads(exact_path.read_text()) if exact_path.exists() else {}
    report_payload = json.loads(report_path.read_text()) if report_path.exists() else {}

    mapping_outputs_present = bool(align_record.get("executed")) and bool(exact_match_record.get("executed"))
    reconciliation_passed = report_payload.get("reconciliation", {}).get("status") == "passed"

    try:
        plan = execute_index_cleanup(
            index_dir,
            index_manifest_present=index_manifest_present,
            mapping_outputs_present=mapping_outputs_present,
            reconciliation_passed=reconciliation_passed,
            reference=None,
            output_dir=output_dir,
        )
    except CleanupRefused as exc:
        raise SystemExit(f"cleanup refused for build {build!r}: {exc}") from exc
    print(f"removed {plan.resolved_target} ({len(plan.files)} file(s))")


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    stages = STAGES if not args.stage or "all" in args.stage else tuple(args.stage)
    builds = tuple(args.build) if args.build else DEFAULT_BUILDS

    # Exactly-one-build enforcement (B1 required item 7): real mapping must
    # never run against zero or multiple builds in one invocation.
    if args.allow_mapping and len(builds) != 1:
        raise SystemExit(
            f"--allow-mapping requires exactly one explicit --build, got {list(builds)}; "
            "process one reference build at a time"
        )

    references: dict[str, Path] = {}
    for spec in args.reference or ():
        build, path = _parse_key_value_path(spec, flag="--reference")
        references[build] = path

    reference_manifests: dict[str, dict] = {}
    reference_manifest_hashes: dict[str, str] = {}
    for spec in args.reference_manifest or ():
        build, path = _parse_key_value_path(spec, flag="--reference-manifest")
        reference_manifests[build] = json.loads(Path(path).read_text())
        # Hashed from the raw file, not the parsed dict, so any byte-level
        # edit (including one that leaves the parsed value unchanged, e.g.
        # whitespace) is still detected — see the fingerprint wiring below.
        reference_manifest_hashes[build] = sha256_file(Path(path))

    bwa_index_prefix_overrides: dict[str, Path] = {}
    for spec in args.bwa_index_prefix or ():
        build, path = _parse_key_value_path(spec, flag="--bwa-index-prefix")
        bwa_index_prefix_overrides[build] = path

    minimap2_index_overrides: dict[str, Path] = {}
    for spec in args.minimap2_index or ():
        build, path = _parse_key_value_path(spec, flag="--minimap2-index")
        minimap2_index_overrides[build] = path

    # Fail-closed local-input verification (B1 required item 1 / B2's actual
    # gate): compare the four frozen dataset/audit/protein/config hashes
    # before the real CSV can be opened for row-by-row reading. Opt-in via
    # --execution-sources so 001A's tiny-fixture tests (whose hashes
    # intentionally do not match the frozen production spec) are unaffected;
    # a real Task 001B invocation must pass
    # --execution-sources configs/coordinate_execution_sources.toml.
    if args.execution_sources is not None:
        execution_source_spec = load_execution_sources(args.execution_sources)
        local_input_violations = verify_local_inputs(
            execution_source_spec,
            paths={
                "dataset_csv": args.csv,
                "dataset_audit": args.dataset_audit,
                "proteins_config": args.proteins_config,
                "study_config": args.config,
            },
        )
        if local_input_violations:
            raise SystemExit(
                "execution-source verification failed closed before opening the CSV: "
                f"{[f'{v.key}: {v.detail}' for v in local_input_violations]}"
            )

    cfg = load_config(args.config)

    if args.cleanup_index is not None:
        _run_cleanup_index(cfg, build=args.cleanup_index, indices_dir=args.indices_dir, output_dir=args.output_dir)
        return

    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.output_dir / "state.json"
    state = _load_state(state_path)

    # Restart-state validity (review item 1): every stage's skip/re-run
    # decision is bound to a fingerprint of the declared inputs/config/
    # reference/authorization it would use right now, not merely "did this
    # key already run". See _stage_is_valid/_mark_stage_complete.
    dataset_csv_hash = sha256_file(args.csv) if args.csv.is_file() else None
    config_hash = sha256_file(args.config) if args.config.is_file() else None
    reference_hashes: dict[str, str | None] = {
        build: (sha256_file(path) if path.is_file() else None) for build, path in references.items()
    }
    base_fingerprint = content_fingerprint("sample_decode_controls", dataset_csv_hash, config_hash)

    def index_fingerprint(build: str) -> str:
        return content_fingerprint(
            "index",
            base_fingerprint,
            reference_hashes.get(build),
            reference_manifest_hashes.get(build),
            args.allow_mapping,
            args.host_role,
            args.threads,
            args.dry_run,
        )

    def align_fingerprint(build: str) -> str:
        # Includes the reference *manifest's* own content hash (not just the
        # reference FASTA's), so any manifest-only change — the manifest
        # becoming invalid (edited sha256/byte_size that no longer matches
        # the FASTA), or purely-descriptive metadata like contig_categories
        # changing — invalidates align and forces it to revalidate, rather
        # than trusting a manifest that was never re-checked against this
        # exact content. This also means align.json (and therefore
        # provenance.json's reference_manifest) can never be produced under
        # one manifest and then silently re-labeled with a newer one.
        # Also chained from index's *last recorded* fingerprint plus its
        # current executed status (B1 required item 6: restart fingerprints
        # must include the BWA prefix/minimap2 index manifest), so a
        # rebuilt/changed index invalidates and forces align to re-run rather
        # than reusing SAM output built against a stale index.
        recorded_index_fp = state.get("stage_fingerprints", {}).get(_stage_key("index", build), "never_run")
        return content_fingerprint(
            "align",
            base_fingerprint,
            reference_hashes.get(build),
            reference_manifest_hashes.get(build),
            recorded_index_fp,
            bool(index_records.get(build, {}).get("executed")),
            args.allow_mapping,
            args.host_role,
            args.threads,
            args.dry_run,
        )

    def exact_match_fingerprint(build: str) -> str:
        # Chained from align's *last recorded* fingerprint (not recomputed
        # from this invocation's CLI flags, which may not even mention
        # align/exact_match when only --stage report is requested) plus
        # align's current executed status, so any upstream change — a
        # changed input, or align actually executing after being merely
        # planned — propagates without guessing at flags this call never
        # received.
        recorded_align_fp = state.get("stage_fingerprints", {}).get(_stage_key("align", build), "never_run")
        return content_fingerprint("exact_match", recorded_align_fp, bool(align_records[build].get("executed")))

    def report_fingerprint(build: str) -> str:
        recorded_exact_fp = state.get("stage_fingerprints", {}).get(_stage_key("exact_match", build), "never_run")
        return content_fingerprint("report", recorded_exact_fp, bool(exact_match_records[build].get("executed")))

    def preflight_fingerprint() -> str:
        return content_fingerprint(
            "preflight",
            base_fingerprint,
            tuple(sorted(reference_hashes.items())),
            tuple(sorted(reference_manifest_hashes.items())),
            args.host_role,
            args.allow_mapping,
            args.threads,
        )

    def combined_report_fingerprint() -> str:
        report_fps = {
            build: state.get("stage_fingerprints", {}).get(_stage_key("report", build), "never_run")
            for build in builds
        }
        return content_fingerprint("combined_report", tuple(sorted(report_fps.items())))

    rows = read_dataset_rows(args.csv, cfg.sampling.num_proteins)
    rows_by_id: dict = {}
    with args.csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            rows_by_id[f"row_{index}"] = row["sequence"]

    # Resume-safety: a prior process may have completed `sample` and exited;
    # reload its persisted assignments rather than requiring `sample` to be
    # re-run in this same process before `decode`/`controls`/`report` can see it.
    sample: SamplingResult | None = _load_sample_state(args.output_dir)

    # Same resume-safety concern as `sample`, per build: index/align/
    # exact_match may have executed real work in a prior process. Reload
    # their recorded results rather than defaulting to "not executed" and
    # silently losing real evidence when a later stage runs standalone.
    index_records: dict[str, dict] = {}
    align_records: dict[str, dict] = {}
    exact_match_records: dict[str, dict] = {}
    index_dirs: dict[str, Path] = {build: args.indices_dir / build for build in builds}
    for build in builds:
        build_dir = _build_dir(args.output_dir, build)
        index_path = index_dirs[build] / "index.json"
        align_path = build_dir / "align.json"
        exact_path = build_dir / "exact_match.json"
        index_records[build] = json.loads(index_path.read_text()) if index_path.exists() else {"executed": False}
        align_records[build] = json.loads(align_path.read_text()) if align_path.exists() else {"executed": False}
        exact_match_records[build] = (
            json.loads(exact_path.read_text()) if exact_path.exists() else {"executed": False}
        )

    def _resolved_bwa_index_prefix(build: str) -> Path | None:
        if build in bwa_index_prefix_overrides:
            return bwa_index_prefix_overrides[build]
        if index_records.get(build, {}).get("executed"):
            return Path(index_records[build]["bwa_index_prefix"])
        return None

    def _resolved_minimap2_index(build: str) -> Path | None:
        if build in minimap2_index_overrides:
            return minimap2_index_overrides[build]
        if index_records.get(build, {}).get("executed"):
            return Path(index_records[build]["minimap2_index"])
        return None

    # One disk-budget ledger per invocation (B1 required item 8), baselined
    # once before any expensive step; every download/derivation/indexing/
    # mapping subprocess checks the *remaining* budget against it and
    # records its own observed new bytes afterward.
    disk_ledger = start_ledger(args.disk_budget_path) if args.allow_mapping and not args.dry_run else None

    for stage in stages:
        if stage in BUILD_SCOPED_STAGES:
            for build in builds:
                key = _stage_key(stage, build)
                if stage == "index":
                    fingerprint = index_fingerprint(build)
                elif stage == "align":
                    fingerprint = align_fingerprint(build)
                elif stage == "exact_match":
                    fingerprint = exact_match_fingerprint(build)
                else:  # "report"
                    fingerprint = report_fingerprint(build)

                if not args.force and _stage_is_valid(state, key, fingerprint):
                    print(f"skip {key} (already completed with matching inputs; pass --force to redo)")
                    continue
                if key in state["completed_stages"] and state.get("stage_fingerprints", {}).get(key) != fingerprint:
                    print(f"{key}: declared inputs/config/reference/authorization changed since it last completed; re-running")

                build_dir = _build_dir(args.output_dir, build)
                if stage == "index":
                    index_record = stage_index(
                        cfg,
                        build=build,
                        index_dir=index_dirs[build],
                        allow_mapping=args.allow_mapping,
                        host_role=args.host_role,
                        threads=args.threads,
                        reference=references.get(build),
                        reference_manifest=reference_manifests.get(build),
                        dry_run=args.dry_run,
                        disk_ledger=disk_ledger,
                    )
                    index_records[build] = index_record
                    executed = bool(index_record.get("executed"))
                    state["mapping_executed"].setdefault(build, {})["index"] = executed
                    retryable = args.allow_mapping and not executed
                elif stage == "align":
                    align_record = stage_align(
                        cfg,
                        build=build,
                        build_output_dir=build_dir,
                        allow_mapping=args.allow_mapping,
                        host_role=args.host_role,
                        threads=args.threads,
                        reference=references.get(build),
                        reference_manifest=reference_manifests.get(build),
                        reads_fasta=_prepare_mapping_reads(args.output_dir),
                        dry_run=args.dry_run,
                        bwa_index_prefix=_resolved_bwa_index_prefix(build),
                        minimap2_index=_resolved_minimap2_index(build),
                        disk_ledger=disk_ledger,
                    )
                    align_records[build] = align_record
                    executed = bool(align_record.get("executed"))
                    state["mapping_executed"].setdefault(build, {})["align"] = executed
                    # A stage that was authorized but did not execute (dry
                    # run, failed preflight, missing binary) must not be
                    # marked complete: doing so would silently prevent a
                    # later real run of this exact stage/build.
                    retryable = args.allow_mapping and not executed
                elif stage == "exact_match":
                    exact_match_record = stage_exact_match(
                        cfg,
                        build=build,
                        build_output_dir=build_dir,
                        allow_mapping=args.allow_mapping,
                        host_role=args.host_role,
                        threads=args.threads,
                        reference=references.get(build),
                        reference_manifest=reference_manifests.get(build),
                        reads_fasta=_prepare_mapping_reads(args.output_dir),
                        align_record=align_records.get(build, {"executed": False}),
                        dry_run=args.dry_run,
                        disk_ledger=disk_ledger,
                    )
                    exact_match_records[build] = exact_match_record
                    executed = bool(exact_match_record.get("executed"))
                    state["mapping_executed"].setdefault(build, {})["exact_match"] = executed
                    retryable = args.allow_mapping and not executed
                else:  # "report"
                    if sample is None:
                        raise SystemExit("report stage requires sample stage state; run --stage sample first")
                    build_report_payload = stage_report(
                        sample,
                        cfg=cfg,
                        build_output_dir=build_dir,
                        expected_total=cfg.sampling.total_size,
                        expected_representative=cfg.sampling.representative_size,
                        expected_controls=cfg.controls.count,
                        build=build,
                        align_record=align_records.get(build, {"executed": False}),
                        exact_match_record=exact_match_records.get(build, {"executed": False}),
                        reference=references.get(build),
                    )
                    retryable = False
                    # B1 required item 9: a failed reconciliation must make
                    # the runner exit nonzero, checked directly against
                    # reconciliation.status rather than trusting that a
                    # process reaching this point implies success.
                    if build_report_payload["reconciliation"]["status"] == "failed":
                        _mark_stage_complete(state, key, fingerprint)
                        _save_state(state_path, state)
                        raise SystemExit(
                            f"reconciliation failed for build {build!r}: "
                            f"{build_report_payload['reconciliation']['issues']}"
                        )

                if not retryable:
                    _mark_stage_complete(state, key, fingerprint)
            _save_state(state_path, state)
            continue

        if stage == "preflight":
            fingerprint = preflight_fingerprint()
        elif stage == "combined_report":
            fingerprint = combined_report_fingerprint()
        else:  # "sample", "decode", "controls"
            fingerprint = base_fingerprint

        if not args.force and _stage_is_valid(state, stage, fingerprint):
            print(f"skip {stage} (already completed with matching inputs; pass --force to redo)")
            continue
        if stage in state["completed_stages"] and state.get("stage_fingerprints", {}).get(stage) != fingerprint:
            print(f"{stage}: declared inputs/config changed since it last completed; re-running")

        if stage == "preflight":
            stage_preflight(
                cfg,
                output_dir=args.output_dir,
                host_role=args.host_role,
                allow_mapping=args.allow_mapping,
                threads=args.threads,
                references=references,
                reads_fasta=_prepare_mapping_reads(args.output_dir),
            )
        elif stage == "sample":
            sample = stage_sample(cfg, rows, output_dir=args.output_dir)
        elif stage == "decode":
            if sample is None:
                raise SystemExit("decode stage requires sample stage state; run --stage sample first")
            stage_decode(rows_by_id, sample, sequence_length_nt=cfg.sequence_length_nt, output_dir=args.output_dir)
        elif stage == "controls":
            if sample is None:
                raise SystemExit("controls stage requires sample stage state; run --stage sample first")
            stage_controls(
                rows_by_id,
                sample,
                seed=cfg.sampling.seed,
                count=cfg.controls.count,
                max_attempts=cfg.controls.max_shuffle_attempts,
                output_dir=args.output_dir,
            )
        elif stage == "combined_report":
            if sample is None:
                raise SystemExit("combined_report stage requires sample stage state; run --stage sample first")
            # The manifest each build's align/exact_match actually ran
            # under (persisted on align.json), not whichever
            # --reference-manifest this invocation happens to declare: a
            # build whose align stage was not re-attempted this invocation
            # must keep contributing its old manifest's contig_categories,
            # never a newer manifest it was never validated/re-run against.
            persisted_manifests = {
                build: align_records.get(build, {}).get("reference_manifest") or reference_manifests.get(build)
                for build in builds
            }
            stage_combined_report(
                sample,
                cfg=cfg,
                output_dir=args.output_dir,
                builds=builds,
                reference_manifests=persisted_manifests,
            )

        _mark_stage_complete(state, stage, fingerprint)
        _save_state(state_path, state)

    # Same principle for provenance.json: attribute each build's manifest
    # from what align/exact_match actually recorded using, not from
    # whatever --reference-manifest this invocation happens to pass.
    persisted_reference_manifests = {
        build: align_records.get(build, {}).get("reference_manifest") or reference_manifests.get(build)
        for build in builds
    }
    _write_provenance(
        cfg=cfg,
        output_dir=args.output_dir,
        csv_path=args.csv,
        config_path=args.config,
        dataset_audit_path=args.dataset_audit,
        proteins_config_path=args.proteins_config,
        builds=builds,
        index_records=index_records,
        align_records=align_records,
        exact_match_records=exact_match_records,
        reference_manifests=persisted_reference_manifests,
        state=state,
        disk_ledger=disk_ledger,
    )

    if args.dry_run:
        _write_json(
            args.output_dir / Path(cfg.outputs.dry_run_json).name,
            {"stages_run": list(stages), "completed_stages": state["completed_stages"]},
        )


if __name__ == "__main__":
    main()
