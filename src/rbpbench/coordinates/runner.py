"""Restart-safe, explicitly-staged runner for the Task 001A pipeline.

Importing this module, or running the unit test suite, never downloads
anything or invokes a mapper: the ``align`` and ``exact_match`` stages only
*construct* commands unless the caller passes ``--allow-mapping`` together
with ``--host-role=approved_mac`` (see ``rbpbench.coordinates.preflight``),
and even then they degrade to a recorded skip when a binary is not on PATH.
Progress is tracked in ``<output-dir>/state.json`` so a re-run skips
already-completed stages.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Sequence

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
from rbpbench.coordinates.hashing import control_seed
from rbpbench.coordinates.preflight import APPROVED_MAC, DEV_VM, run_preflight
from rbpbench.coordinates.report import build_report, reconcile_counts, render_markdown
from rbpbench.coordinates.sampling import DatasetRow, SamplingResult, build_sample
from rbpbench.data.audit import parse_labels

STAGES = ("preflight", "sample", "decode", "controls", "align", "exact_match", "report")


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
        return json.loads(state_path.read_text())
    return {"completed_stages": []}


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def stage_preflight(cfg: FeasibilityConfig, *, output_dir: Path, host_role: str, allow_mapping: bool) -> dict:
    report = run_preflight(
        host_role=host_role,
        resources=cfg.resources,
        disk_path=output_dir,
        allow_mapping=allow_mapping,
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
            handle.write(fasta_record(f"control_{sample_id}", shuffled))
    return fasta_path


def stage_align(cfg: FeasibilityConfig, *, output_dir: Path, allow_mapping: bool, host_role: str, threads: int) -> dict:
    placeholder_ref = Path("reference.fasta")
    placeholder_reads = Path("sample_sequences.fasta")
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

    if not allow_mapping or host_role != APPROVED_MAC:
        record["skip_reason"] = (
            "mapping requires --allow-mapping together with --host-role=approved_mac "
            f"(got allow_mapping={allow_mapping}, host_role={host_role!r}); Task 001A never maps real data"
        )
        _write_json(output_dir / "align.json", record)
        return record

    bwa_version = resolve_version(["bwa"])
    mm2_version = resolve_version(["minimap2", "--version"])
    if bwa_version is None or mm2_version is None:
        record["skip_reason"] = "bwa and/or minimap2 not found on PATH in this environment"
        _write_json(output_dir / "align.json", record)
        return record

    record["skip_reason"] = "binaries present, but Task 001A is scoped to stop before real mapping"
    _write_json(output_dir / "align.json", record)
    return record


def stage_exact_match(*, output_dir: Path, allow_mapping: bool, host_role: str) -> dict:
    placeholder_query = Path("candidates.fasta")
    placeholder_ref = Path("reference.fasta")
    cmd = seqkit_locate_command(placeholder_query, placeholder_ref)
    record = {
        "planned_command": format_command(cmd.argv),
        "executed": False,
        "skip_reason": "Task 001A never runs exact-match search against a real reference",
    }
    if allow_mapping and host_role == APPROVED_MAC:
        version = resolve_version(["seqkit", "version"])
        if version is None:
            record["skip_reason"] = "seqkit not found on PATH in this environment"
    _write_json(output_dir / "exact_match.json", record)
    return record


def stage_report(
    sample: SamplingResult,
    *,
    cfg: FeasibilityConfig,
    output_dir: Path,
    expected_total: int,
    expected_representative: int,
    expected_controls: int,
) -> dict:
    reconciliation = reconcile_counts(
        sample.assignments,
        (),
        expected_total=expected_total,
        expected_representative=expected_representative,
        expected_controls=expected_controls,
    )
    report = build_report(sample.assignments, (), reconciliation=reconciliation)
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

    sample: SamplingResult | None = None

    for stage in stages:
        if stage in state["completed_stages"] and not args.force:
            print(f"skip {stage} (already completed; pass --force to redo)")
            continue

        if stage == "preflight":
            stage_preflight(cfg, output_dir=args.output_dir, host_role=args.host_role, allow_mapping=args.allow_mapping)
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
            stage_align(cfg, output_dir=args.output_dir, allow_mapping=args.allow_mapping, host_role=args.host_role, threads=args.threads)
        elif stage == "exact_match":
            stage_exact_match(output_dir=args.output_dir, allow_mapping=args.allow_mapping, host_role=args.host_role)
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
