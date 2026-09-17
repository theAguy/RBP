"""Restart-safe, explicitly-staged runner for the Task 001A/001B pipeline.

Importing this module, or running the unit test suite, never downloads
anything or invokes a mapper: the ``align`` and ``exact_match`` stages only
*construct* commands unless the caller passes ``--allow-mapping`` together
with ``--host-role=approved_mac`` and a real ``--reference`` (see
``rbpbench.coordinates.preflight``), and even then they degrade to a recorded
skip when a binary or input is not available. When every guard is satisfied
they run the pinned tools via ``subprocess.run(argv, shell=False)`` (never a
shell string) and parse the real output. Task 001A itself never supplies
those flags against real data; the capability exists so Task 001B does not
require a rewrite.

Progress is tracked in ``<output-dir>/state.json`` so a re-run skips
already-completed stages, and the sampled assignments are separately
persisted to ``<output-dir>/sample_state.json`` so a later stage can resume
in a brand-new process without having re-run ``sample`` in the same one.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import subprocess
from pathlib import Path
from typing import Sequence

from rbpbench.coordinates.alignment import (
    AlignmentRecord,
    CandidateLocus,
    build_candidate_loci,
    classify_primary,
    classify_splice,
    parse_sam_line,
)
from rbpbench.coordinates.commands import (
    bwa_mem_command,
    format_command,
    minimap2_splice_command,
    resolve_version,
    seqkit_locate_command,
)
from rbpbench.coordinates.config import FeasibilityConfig, load_config
from rbpbench.coordinates.controls import generate_control
from rbpbench.coordinates.decode import decode_and_validate, fasta_record
from rbpbench.coordinates.exact_match import exact_occurrence_count, exact_unique_confirmed, parse_seqkit_bed
from rbpbench.coordinates.hashing import control_seed
from rbpbench.coordinates.preflight import APPROVED_MAC, DEV_VM, run_preflight
from rbpbench.coordinates.report import MappingResult, build_report, reconcile_counts, render_markdown
from rbpbench.coordinates.sampling import DatasetRow, SampleAssignment, SamplingResult, build_sample
from rbpbench.data.audit import parse_labels

STAGES = ("preflight", "sample", "decode", "controls", "align", "exact_match", "report")

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
    reference: Path | None,
    reads_fasta: Path | None,
) -> dict:
    required_input_paths = {}
    if allow_mapping:
        if reference is not None:
            required_input_paths["reference"] = reference
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
    """Return None when real execution may proceed, else the skip reason."""
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
    output_dir: Path,
    allow_mapping: bool,
    host_role: str,
    threads: int,
    reference: Path | None,
    reads_fasta: Path | None,
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

    skip_reason = _mapping_capable(
        allow_mapping=allow_mapping, host_role=host_role, reference=reference, reads_fasta=reads_fasta
    )
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
        _write_json(output_dir / "align.json", record)
        return record

    bwa_version = resolve_version(["bwa"])
    mm2_version = resolve_version(["minimap2", "--version"])
    if bwa_version is None or mm2_version is None:
        record["skip_reason"] = "bwa and/or minimap2 not found on PATH in this environment"
        _write_json(output_dir / "align.json", record)
        return record

    bwa_sam = output_dir / "align_bwa_mem.sam"
    mm2_sam = output_dir / "align_minimap2_splice.sam"
    _run_tool_to_file(bwa_cmd.argv, output_path=bwa_sam)
    _run_tool_to_file(mm2_cmd.argv, output_path=mm2_sam)

    record["executed"] = True
    record["tool_versions"] = {"bwa": bwa_version, "minimap2": mm2_version}
    record["sam_paths"] = {"bwa_mem": str(bwa_sam), "minimap2_splice": str(mm2_sam)}
    _write_json(output_dir / "align.json", record)
    return record


def stage_exact_match(
    *,
    output_dir: Path,
    allow_mapping: bool,
    host_role: str,
    reference: Path | None,
    reads_fasta: Path | None,
    align_record: dict,
) -> dict:
    placeholder_query = output_dir / "sample_sequences.fasta"
    placeholder_ref = reference or Path("reference.fasta")
    cmd = seqkit_locate_command(placeholder_query, placeholder_ref)
    record = {
        "planned_command": format_command(cmd.argv),
        "executed": False,
        "skip_reason": "Task 001A never runs exact-match search against a real reference",
    }

    skip_reason = _mapping_capable(
        allow_mapping=allow_mapping, host_role=host_role, reference=reference, reads_fasta=reads_fasta
    )
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
        _write_json(output_dir / "exact_match.json", record)
        return record

    if not align_record.get("executed"):
        record["skip_reason"] = "align stage did not execute real mapping; nothing to confirm"
        _write_json(output_dir / "exact_match.json", record)
        return record

    version = resolve_version(["seqkit", "version"])
    if version is None:
        record["skip_reason"] = "seqkit not found on PATH in this environment"
        _write_json(output_dir / "exact_match.json", record)
        return record

    bed_path = output_dir / "exact_match_hits.bed"
    query_cmd = seqkit_locate_command(reads_fasta, reference)
    _run_tool_to_file(query_cmd.argv, output_path=bed_path)

    record["executed"] = True
    record["tool_version"] = version
    record["bed_path"] = str(bed_path)
    _write_json(output_dir / "exact_match.json", record)
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
        }
    return {
        "chrom": locus.chrom,
        "start": locus.blocks[0].ref_start,
        "end": locus.blocks[-1].ref_end,
        "strand": locus.strand,
        "block_count": locus.block_count,
        "block_starts": ";".join(str(b.ref_start) for b in locus.blocks),
        "block_sizes": ";".join(str(b.ref_end - b.ref_start) for b in locus.blocks),
        "coverage": f"{locus.coverage:.6f}",
        "identity": f"{locus.identity:.6f}",
        "mapq": locus.mapq,
        "alignment_score": locus.as_score if locus.as_score is not None else "",
    }


def build_mapping_rows(
    cfg: FeasibilityConfig,
    stratum_by_id: dict[str, str],
    *,
    build: str,
    bwa_sam: Path,
    minimap2_sam: Path,
    exact_hits_bed: Path | None,
) -> tuple[tuple[MappingResult, ...], list[dict]]:
    """Parse real SAM/BED output into (reconciliation results, TSV rows).

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

    query_ids = sorted(set(bwa_by_query) | set(mm2_by_query))
    results: list[MappingResult] = []
    rows: list[dict] = []

    for sample_id in query_ids:
        is_control = sample_id.startswith(CONTROL_ID_PREFIX)
        stratum = stratum_by_id.get(sample_id, "control" if is_control else "")

        primary_loci = build_candidate_loci(bwa_by_query.get(sample_id, ()), total_query_bases=total_query)
        splice_loci = build_candidate_loci(mm2_by_query.get(sample_id, ()), total_query_bases=total_query)

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
        rows.append(row)

    return tuple(results), rows


def write_mappings_tsv_gz(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MAPPING_TSV_COLUMNS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def stage_report(
    sample: SamplingResult,
    *,
    cfg: FeasibilityConfig,
    output_dir: Path,
    expected_total: int,
    expected_representative: int,
    expected_controls: int,
    build: str,
    align_record: dict,
    exact_match_record: dict,
) -> dict:
    mapping_evaluated = bool(align_record.get("executed")) and bool(exact_match_record.get("executed"))
    mapping_results: tuple[MappingResult, ...] = ()
    expected_control_ids: tuple[str, ...] = ()

    if mapping_evaluated:
        stratum_by_id = {a.sample_id: a.stratum for a in sample.assignments}
        representative_ids = sorted(sample.representative_ids)
        mapping_results, rows = build_mapping_rows(
            cfg,
            stratum_by_id,
            build=build,
            bwa_sam=Path(align_record["sam_paths"]["bwa_mem"]),
            minimap2_sam=Path(align_record["sam_paths"]["minimap2_splice"]),
            exact_hits_bed=Path(exact_match_record["bed_path"]) if exact_match_record.get("bed_path") else None,
        )
        write_mappings_tsv_gz(output_dir / Path(cfg.outputs.mappings_tsv_gz).name, rows)
        expected_control_ids = tuple(f"{CONTROL_ID_PREFIX}{sid}" for sid in representative_ids[: expected_controls])

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
    _write_json(output_dir / Path(cfg.outputs.report_json).name, report)
    (output_dir / Path(cfg.outputs.report_md).name).write_text(render_markdown(report))
    return report


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
    parser.add_argument("--reference", type=Path, default=None, help="Reference FASTA; required for real mapping")
    parser.add_argument("--build", default="hg38", help="Reference build ID tag recorded on mapping rows")
    parser.add_argument("--dry-run", action="store_true", help="Plan commands without executing external tools")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    stages = STAGES if not args.stage or "all" in args.stage else tuple(args.stage)

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

    # Same resume-safety concern as `sample`: align/exact_match may have
    # executed real mapping in a prior process. Reload their recorded
    # results rather than defaulting to "not executed" and silently losing
    # real mapping evidence when `report` runs standalone later.
    align_json_path = args.output_dir / "align.json"
    exact_match_json_path = args.output_dir / "exact_match.json"
    align_record: dict = json.loads(align_json_path.read_text()) if align_json_path.exists() else {"executed": False}
    exact_match_record: dict = (
        json.loads(exact_match_json_path.read_text()) if exact_match_json_path.exists() else {"executed": False}
    )
    for stage in stages:
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
                reference=args.reference,
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
        elif stage == "align":
            align_record = stage_align(
                cfg,
                output_dir=args.output_dir,
                allow_mapping=args.allow_mapping,
                host_role=args.host_role,
                threads=args.threads,
                reference=args.reference,
                reads_fasta=_prepare_mapping_reads(args.output_dir),
            )
            state["mapping_executed"]["align"] = bool(align_record.get("executed"))
        elif stage == "exact_match":
            exact_match_record = stage_exact_match(
                output_dir=args.output_dir,
                allow_mapping=args.allow_mapping,
                host_role=args.host_role,
                reference=args.reference,
                reads_fasta=_prepare_mapping_reads(args.output_dir),
                align_record=align_record,
            )
            state["mapping_executed"]["exact_match"] = bool(exact_match_record.get("executed"))
        elif stage == "report":
            if sample is None:
                raise SystemExit("report stage requires sample stage state; run --stage sample first")
            stage_report(
                sample,
                cfg=cfg,
                output_dir=args.output_dir,
                expected_total=cfg.sampling.total_size,
                expected_representative=cfg.sampling.representative_size,
                expected_controls=cfg.controls.count,
                build=args.build,
                align_record=align_record,
                exact_match_record=exact_match_record,
            )

        state["completed_stages"].append(stage)
        _save_state(state_path, state)

    if args.dry_run:
        _write_json(
            args.output_dir / Path(cfg.outputs.dry_run_json).name,
            {"stages_run": list(stages), "completed_stages": state["completed_stages"]},
        )


if __name__ == "__main__":
    main()
