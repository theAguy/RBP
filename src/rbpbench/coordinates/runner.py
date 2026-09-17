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
    near_tied_secondary_fractions,
    parse_sam_line,
)
from rbpbench.coordinates.commands import (
    bwa_mem_command,
    format_command,
    minimap2_splice_command,
    seqkit_locate_command,
)
from rbpbench.coordinates.config import FeasibilityConfig, load_config
from rbpbench.coordinates.controls import generate_control
from rbpbench.coordinates.decode import decode_and_validate, fasta_record
from rbpbench.coordinates.exact_match import exact_occurrence_count, exact_unique_confirmed, parse_seqkit_bed
from rbpbench.coordinates.hashing import control_seed
from rbpbench.coordinates.preflight import APPROVED_MAC, DEV_VM, run_preflight
from rbpbench.coordinates.provenance import resolve_binary_provenance, run_tool_with_provenance
from rbpbench.coordinates.reference import load_fasta_sequences, make_reference_lookup
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

STAGES = ("preflight", "sample", "decode", "controls", "align", "exact_match", "report", "combined_report")
BUILD_SCOPED_STAGES = ("align", "exact_match", "report")
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
    "best_secondary_chrom",
    "best_secondary_coverage",
    "best_secondary_identity",
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
    return state


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


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


def _run_tool_to_file(argv: Sequence[str], *, output_path: Path) -> None:
    """Execute a pinned mapper/matcher command and capture its stdout.

    Always ``shell=False``: ``argv`` is a list built by
    :mod:`rbpbench.coordinates.commands`, never an interpolated shell string.
    Bounded by a generous timeout so a wedged mapper process cannot hang the
    pipeline forever.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as handle:
        subprocess.run(
            list(argv),
            shell=False,
            stdout=handle,
            stderr=subprocess.DEVNULL,
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


def stage_align(
    cfg: FeasibilityConfig,
    *,
    build_output_dir: Path,
    allow_mapping: bool,
    host_role: str,
    threads: int,
    reference: Path | None,
    reads_fasta: Path | None,
    dry_run: bool,
) -> dict:
    placeholder_ref = reference or Path("reference.fasta")
    placeholder_reads = reads_fasta or Path("sample_sequences.fasta")
    bwa_cmd = bwa_mem_command(placeholder_ref, placeholder_reads, threads=threads)
    mm2_cmd = minimap2_splice_command(placeholder_ref, placeholder_reads, threads=threads)

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
        _write_json(build_output_dir / "align.json", record)
        return record

    skip_reason = _mapping_capable(
        allow_mapping=allow_mapping, host_role=host_role, reference=reference, reads_fasta=reads_fasta
    )
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
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

    bwa_binary = resolve_binary_provenance("bwa", version=preflight_report.tool_versions.get("bwa"))
    mm2_binary = resolve_binary_provenance("minimap2", version=preflight_report.tool_versions.get("minimap2"))

    bwa_sam = build_output_dir / "align_bwa_mem.sam"
    mm2_sam = build_output_dir / "align_minimap2_splice.sam"
    bwa_provenance = run_tool_with_provenance(
        bwa_cmd.argv,
        tool="bwa_mem",
        output_path=bwa_sam,
        command_text=format_command(bwa_cmd.argv),
        binary=bwa_binary,
        run_fn=_run_tool_to_file,
    )
    mm2_provenance = run_tool_with_provenance(
        mm2_cmd.argv,
        tool="minimap2_splice",
        output_path=mm2_sam,
        command_text=format_command(mm2_cmd.argv),
        binary=mm2_binary,
        run_fn=_run_tool_to_file,
    )

    record["executed"] = True
    record["tool_versions"] = {"bwa": bwa_binary.version, "minimap2": mm2_binary.version}
    record["sam_paths"] = {"bwa_mem": str(bwa_sam), "minimap2_splice": str(mm2_sam)}
    record["provenance"] = {
        "input_hashes": preflight_report.input_hashes,
        "bwa_mem": bwa_provenance.to_dict(),
        "minimap2_splice": mm2_provenance.to_dict(),
    }
    _write_json(build_output_dir / "align.json", record)
    return record


def stage_exact_match(
    cfg: FeasibilityConfig,
    *,
    build_output_dir: Path,
    allow_mapping: bool,
    host_role: str,
    threads: int,
    reference: Path | None,
    reads_fasta: Path | None,
    align_record: dict,
    dry_run: bool,
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
        _write_json(build_output_dir / "exact_match.json", record)
        return record

    skip_reason = _mapping_capable(
        allow_mapping=allow_mapping, host_role=host_role, reference=reference, reads_fasta=reads_fasta
    )
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
        _write_json(build_output_dir / "exact_match.json", record)
        return record

    if not align_record.get("executed"):
        record["skip_reason"] = "align stage did not execute real mapping; nothing to confirm"
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

    seqkit_binary = resolve_binary_provenance("seqkit", version=preflight_report.tool_versions.get("seqkit"))

    bed_path = build_output_dir / "exact_match_hits.bed"
    query_cmd = seqkit_locate_command(reads_fasta, reference)
    provenance = run_tool_with_provenance(
        query_cmd.argv,
        tool="seqkit_locate",
        output_path=bed_path,
        command_text=format_command(query_cmd.argv),
        binary=seqkit_binary,
        run_fn=_run_tool_to_file,
    )

    record["executed"] = True
    record["tool_version"] = seqkit_binary.version
    record["bed_path"] = str(bed_path)
    record["provenance"] = {
        "input_hashes": preflight_report.input_hashes,
        "seqkit_locate": provenance.to_dict(),
    }
    _write_json(build_output_dir / "exact_match.json", record)
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

        primary_is_perfect = bool(primary_loci) and primary_loci[0].coverage == 1.0 and primary_loci[0].identity == 1.0
        occurrence_count = exact_occurrence_count(exact_occurrences, sample_id)
        exact_confirmed = exact_unique_confirmed(
            primary_is_perfect_unique=primary_is_perfect, occurrence_count=occurrence_count
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
        }
        row.update(_locus_detail(best_primary))
        second = _locus_detail(second_primary)
        row["best_secondary_chrom"] = second["chrom"]
        row["best_secondary_coverage"] = second["coverage"]
        row["best_secondary_identity"] = second["identity"]
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
        }
        row.update(_locus_detail(best_splice))
        second = _locus_detail(second_splice)
        row["best_secondary_chrom"] = second["chrom"]
        row["best_secondary_coverage"] = second["coverage"]
        row["best_secondary_identity"] = second["identity"]
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
            reference_lookup = make_reference_lookup(_read_fasta(Path(reference)))

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
) -> dict:
    """Collision-safe per-build artifacts already exist under
    ``output_dir/<build>/``; this reads every one of them back from disk (the
    same resume-safety pattern as align/exact_match reloading) and produces
    the single combined report the parent task requires before Task 001B.
    """
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
        if build_report_payload["reconciliation"]["status"] == "not_evaluated":
            per_build_summaries[build] = {"build": build, "mapping_evaluated": False}
            continue

        mappings_path = build_dir / Path(cfg.outputs.mappings_tsv_gz).name
        rows = read_mappings_tsv_gz(mappings_path)
        primary_rows = [r for r in rows if r["mode"] == "primary"]
        splice_rows = [r for r in rows if r["mode"] == "splice"]
        summary = summaries.build_per_build_summary(
            build=build,
            primary_rows=primary_rows,
            splice_rows=splice_rows,
            representative_ids=representative_ids,
            all_sample_ids=all_sample_ids,
            sample_meta=sample_meta,
            sample_sequences=sample_sequences,
            near_tied_fractions=cfg.near_tied_fractions,
        )
        per_build_summaries[build] = summary
        per_build_primary_by_id[build] = summaries.index_rows_by_sample(primary_rows, mode="primary")
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


def _write_provenance(
    *,
    output_dir: Path,
    csv_path: Path,
    config_path: Path,
    builds: Sequence[str],
    align_records: dict[str, dict],
    exact_match_records: dict[str, dict],
    reference_manifests: dict[str, dict],
) -> dict:
    """Connect provenance to the runner: declared input hashes, resolved
    binary hashes/versions, commands, output hashes, elapsed time, peak
    memory, and reference metadata, all in one place per run. Written
    unconditionally (cheap, idempotent) so it always reflects whatever
    align/exact_match records the current invocation has, whichever stages
    it actually ran.
    """
    payload = {
        "schema_version": 1,
        "declared_inputs": {
            "dataset_csv": {"path": str(csv_path), "sha256": sha256_file(csv_path) if csv_path.is_file() else None},
            "config": {"path": str(config_path), "sha256": sha256_file(config_path) if config_path.is_file() else None},
        },
        "builds": {
            build: {
                "align": align_records.get(build, {}),
                "exact_match": exact_match_records.get(build, {}),
                "reference_manifest": reference_manifests.get(build),
            }
            for build in builds
        },
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
    parser.add_argument("--dry-run", action="store_true", help="Guarantee no external tool ever executes; plan commands only")
    return parser


def _stage_key(stage: str, build: str | None) -> str:
    return f"{stage}:{build}" if build is not None else stage


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    stages = STAGES if not args.stage or "all" in args.stage else tuple(args.stage)
    builds = tuple(args.build) if args.build else DEFAULT_BUILDS

    references: dict[str, Path] = {}
    for spec in args.reference or ():
        build, path = _parse_key_value_path(spec, flag="--reference")
        references[build] = path

    reference_manifests: dict[str, dict] = {}
    for spec in args.reference_manifest or ():
        build, path = _parse_key_value_path(spec, flag="--reference-manifest")
        reference_manifests[build] = json.loads(Path(path).read_text())

    cfg = load_config(args.config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.output_dir / "state.json"
    state = _load_state(state_path)

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

    # Same resume-safety concern as `sample`, per build: align/exact_match
    # may have executed real mapping in a prior process. Reload their
    # recorded results rather than defaulting to "not executed" and silently
    # losing real mapping evidence when `report` runs standalone later.
    align_records: dict[str, dict] = {}
    exact_match_records: dict[str, dict] = {}
    for build in builds:
        build_dir = _build_dir(args.output_dir, build)
        align_path = build_dir / "align.json"
        exact_path = build_dir / "exact_match.json"
        align_records[build] = json.loads(align_path.read_text()) if align_path.exists() else {"executed": False}
        exact_match_records[build] = (
            json.loads(exact_path.read_text()) if exact_path.exists() else {"executed": False}
        )

    for stage in stages:
        if stage in BUILD_SCOPED_STAGES:
            for build in builds:
                key = _stage_key(stage, build)
                if key in state["completed_stages"] and not args.force:
                    print(f"skip {key} (already completed; pass --force to redo)")
                    continue

                build_dir = _build_dir(args.output_dir, build)
                if stage == "align":
                    align_record = stage_align(
                        cfg,
                        build_output_dir=build_dir,
                        allow_mapping=args.allow_mapping,
                        host_role=args.host_role,
                        threads=args.threads,
                        reference=references.get(build),
                        reads_fasta=_prepare_mapping_reads(args.output_dir),
                        dry_run=args.dry_run,
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
                        build_output_dir=build_dir,
                        allow_mapping=args.allow_mapping,
                        host_role=args.host_role,
                        threads=args.threads,
                        reference=references.get(build),
                        reads_fasta=_prepare_mapping_reads(args.output_dir),
                        align_record=align_records.get(build, {"executed": False}),
                        dry_run=args.dry_run,
                    )
                    exact_match_records[build] = exact_match_record
                    executed = bool(exact_match_record.get("executed"))
                    state["mapping_executed"].setdefault(build, {})["exact_match"] = executed
                    retryable = args.allow_mapping and not executed
                else:  # "report"
                    if sample is None:
                        raise SystemExit("report stage requires sample stage state; run --stage sample first")
                    stage_report(
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

                if not retryable:
                    state["completed_stages"].append(key)
            _save_state(state_path, state)
            continue

        if stage in state["completed_stages"] and not args.force:
            print(f"skip {stage} (already completed; pass --force to redo)")
            continue

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
            stage_combined_report(sample, cfg=cfg, output_dir=args.output_dir, builds=builds)

        state["completed_stages"].append(stage)
        _save_state(state_path, state)

    _write_provenance(
        output_dir=args.output_dir,
        csv_path=args.csv,
        config_path=args.config,
        builds=builds,
        align_records=align_records,
        exact_match_records=exact_match_records,
        reference_manifests=reference_manifests,
    )

    if args.dry_run:
        _write_json(
            args.output_dir / Path(cfg.outputs.dry_run_json).name,
            {"stages_run": list(stages), "completed_stages": state["completed_stages"]},
        )


if __name__ == "__main__":
    main()
