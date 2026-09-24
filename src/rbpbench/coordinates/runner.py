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
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
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
from rbpbench.coordinates.cleanup import CleanupRefused, execute_index_cleanup, plan_index_cleanup, resolve_git_repo_root
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
from rbpbench.coordinates.derive_reference import (
    build_reference_manifest,
    current_git_commit,
    derive_reference_fasta,
    largest_contig,
    validate_contig_lengths,
)
from rbpbench.coordinates.download import (
    DownloadVerificationError,
    Transport,
    parse_md5checksums_evidence,
    restart_safe_download,
    urllib_transport,
)
from rbpbench.coordinates.diskbudget import (
    BUILD_OUTPUT_ALLOWANCE_GIB,
    GIB,
    PLANNED_ALLOWANCES_GIB,
    BuildOutputBudget,
    DiskBudgetExceeded,
    DiskBudgetLedger,
    check_pinned_volumes,
    check_projected_peak,
    start_build_output_budget,
    start_ledger,
)
from rbpbench.coordinates.exact_match import exact_occurrence_count, exact_unique_confirmed, parse_seqkit_bed
from rbpbench.coordinates.execution_sources import ReferenceSourceSpec, load_execution_sources, verify_local_inputs
from rbpbench.coordinates.hashing import content_fingerprint, control_seed
from rbpbench.coordinates.indexing import (
    BWA_INDEX_SUFFIXES,
    build_index_manifest,
    check_minimap2_mapping_stderr,
    prepare_bwa_index,
    prepare_minimap2_index,
    verify_index_binding,
    verify_index_files_against_manifest,
)
from rbpbench.coordinates.manifest import manifest_content_sha256, validate_reference_manifest
from rbpbench.coordinates.preflight import APPROVED_MAC, DEV_VM, run_preflight
from rbpbench.coordinates.probe import (
    ProbeError,
    build_pattern_fasta,
    compute_probe_projection,
    extract_contig_streaming,
    load_and_verify_b2_checkpoint,
    probe_fingerprint,
    select_probe_window,
    total_reference_bases,
    validate_probe_bed_rows,
)
from rbpbench.coordinates.provenance import (
    git_is_clean,
    host_memory_snapshot,
    resolve_binary_provenance,
    run_tool_with_provenance,
)
from rbpbench.coordinates.reference import (
    IndexedFastaReader,
    build_fasta_index,
    load_fasta_sequences,
    prepare_reference_index,
)
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

STAGES = (
    "preflight",
    "sample",
    "decode",
    "controls",
    "download",
    "derive",
    "index",
    "probe",
    "align",
    "exact_match",
    "report",
    "combined_report",
)
BUILD_SCOPED_STAGES = ("download", "derive", "index", "probe", "align", "exact_match", "report")
DEFAULT_BUILDS = ("hg38", "hg19")

# B3A-A3: the probe stage's own retained-output live sub-cap, carved out of
# (never additional to) the existing 4-GiB BUILD_OUTPUT_ALLOWANCE_GIB shared
# with align/exact_match/report for the same build (see
# docs/tasks/001b_b3_hg38_preparation.md, A3 item 10).
PROBE_OUTPUT_ALLOWANCE_GIB = 1.0
# B3A-A3 item 10: the probe stage's own pre-flight disk-budget reservations,
# drawn from the existing (not a new) 1.0-GiB
# ``environment_manifests_logs_margin`` category and a conservative 2-GiB
# whole-run projected-peak "next step" allowance -- never adding a new
# PLANNED_ALLOWANCES_GIB category, so the frozen 30-GiB table sum is
# unchanged.
PROBE_CANDIDATE_WORK_ALLOWANCE_GIB = 1.0
PROBE_PROJECTED_PEAK_NEXT_STEP_GIB = 2.0

# B3A-R1: the real CLI trust anchor for the probe's pattern population --
# the accepted B2 sampling checkpoint, frozen at its accepted commit
# (docs/reviews/001b_b3a_review.md, "B3A-R1"). NEVER exposed as a
# CLI-overridable flag: `main()`'s CLI wiring is the only place these are
# used, so a caller cannot activate a tiny population count through the
# real CLI -- only direct calls to `stage_probe`/`load_and_verify_b2_checkpoint`
# (the explicit test-only/direct-function seam) can supply different values.
B2_ACCEPTED_MANIFEST_SHA256 = "2dbe37bcdad4622e2801d1b42169acd5e2096a4ef6a8625fee99766c52f4e200"
B2_ACCEPTED_CHECKPOINT = "001B-B2"
B2_ACCEPTED_STATUS = "passed"
B2_REAL_BIOLOGICAL_COUNT = 10000
B2_REAL_CONTROL_COUNT = 100

# B1-F5: the ONLY stage that may accompany the single authorized
# build-scoped stage in one real --allow-mapping invocation without crossing
# a checkpoint review gate is "preflight" (a read-only readiness check that
# never itself executes real work). sample/decode/controls are B2-only
# stages and must never be combined with a build-scoped stage under real
# mapping authorization — doing so could cross the B2 review gate directly
# into real B3-B6 mapping in one invocation. combined_report must never
# accompany --allow-mapping AT ALL (even alone): Task 001B requires it to
# run as its own separate, non-mapping invocation over already-accepted
# per-build reports, never combined with (or mistaken for) an authorized
# mapping invocation.
_ALWAYS_ALLOWED_WITH_MAPPING = frozenset({"preflight"})
# B2-only stages: fine alone (or together with each other) under
# --allow-mapping — the flag is simply unused by them — but never together
# with a build-scoped stage in the same invocation (B1-F5).
_B2_ONLY_STAGES = frozenset({"sample", "decode", "controls"})

CONTROL_ID_PREFIX = "control_"
_ACGT_ONLY = frozenset("ACGT")

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
            _append_rejected_attempt(path, record)
            raise SystemExit(
                f"refusing to overwrite {path}: it already records executed=true, but this attempt did not "
                f"execute real work ({record.get('skip_reason')!r}); a failed/dry-run/unauthorized retry must "
                "never erase prior accepted checkpoint evidence"
            )
    _write_json(path, record)


def _append_rejected_attempt(path: Path, record: dict) -> None:
    """Durably record a refused non-executed attempt (B1-R3: "record failed
    attempts separately") without touching the protected accepted record at
    ``path``. Append-only, so every refused attempt is preserved, not just
    the most recent one.
    """
    rejected_path = path.with_name(path.name + ".rejected_attempts.jsonl")
    entry = {"rejected_at": datetime.now(timezone.utc).isoformat(), **record}
    with rejected_path.open("a") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


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


def _run_tool_to_file(
    argv: Sequence[str], *, output_path: Path, stderr_path: Path, max_output_bytes: int | None = None
) -> None:
    """Execute a pinned mapper/matcher command, capturing stdout and stderr
    *separately*.

    stderr is never sent to ``DEVNULL``: a mapper's own diagnostic warnings
    (e.g. minimap2's parameter-override or multipart-index warnings) are
    load-bearing evidence, not noise, and must be preserved and hashed (see
    :mod:`rbpbench.coordinates.provenance`). Always ``shell=False``: ``argv``
    is a list built by :mod:`rbpbench.coordinates.commands`, never an
    interpolated shell string. Bounded by a generous timeout so a wedged
    mapper process cannot hang the pipeline forever.

    ``max_output_bytes`` (B1-R4/F1), when given, is the maximum COMBINED
    stdout-plus-stderr byte count for this one call, polled live against the
    growing ``output_path`` AND ``stderr_path`` together while the subprocess
    is still running; a breach kills the process and raises
    :class:`DiskBudgetExceeded` rather than ever letting a caller promote a
    silently-truncated-but-accepted file. Counting stderr is required, not
    optional: a tool that writes little to stdout but grows its stderr
    unbounded must be caught exactly like one that grows stdout unbounded —
    polling ``output_path`` alone previously let stderr-only growth bypass
    the cap entirely. A fast-finishing process is still checked once more
    after it exits, so a tool that writes its whole output before the first
    poll cannot slip through uncapped.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    def _combined_bytes() -> int:
        total = 0
        if output_path.exists():
            total += output_path.stat().st_size
        if stderr_path.exists():
            total += stderr_path.stat().st_size
        return total

    with output_path.open("w") as out_handle, stderr_path.open("w") as err_handle:
        process = subprocess.Popen(list(argv), shell=False, stdout=out_handle, stderr=err_handle, text=True)
        start = time.monotonic()
        killed_for_budget = False
        while True:
            try:
                process.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if max_output_bytes is not None and _combined_bytes() > max_output_bytes:
                    process.kill()
                    process.wait()
                    killed_for_budget = True
                    break
                if time.monotonic() - start > _MAPPING_TOOL_TIMEOUT_SECONDS:
                    process.kill()
                    process.wait()
                    raise subprocess.TimeoutExpired(list(argv), _MAPPING_TOOL_TIMEOUT_SECONDS)
        if not killed_for_budget and max_output_bytes is not None and _combined_bytes() > max_output_bytes:
            killed_for_budget = True
        if killed_for_budget:
            raise DiskBudgetExceeded(
                f"combined stdout+stderr for {output_path}/{stderr_path} exceeded the {max_output_bytes}-byte "
                "build-output allowance while writing; the process was terminated before completion and this "
                "attempt's output must not be promoted (previously accepted evidence, if any, is untouched)"
            )
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, list(argv))


def _new_generation_dir(base_dir: Path, *, prefix: str) -> Path:
    """A fresh, uniquely-named, immutable home for one attempt's complete
    multi-file output set (B1-C2: "genuinely transactional artifact
    generations for every multi-file set"). Every file this attempt produces
    is written directly here and NEVER at a fixed, reused final path, so
    promotion is nothing more than the stage's own JSON record (written last,
    atomically — see ``_guarded_write_record``/``_write_json``) naming this
    directory's paths. No file is ever renamed on top of a previously
    accepted one: a failure at any point before that record write leaves the
    prior accepted generation (if any), still referenced by the prior
    record, completely untouched — the "inject a failure at every
    member/pointer/record transition" requirement follows directly, since
    there is no shared mutable final path for a partial attempt to corrupt.
    """
    gen_dir = base_dir / "generations" / f"{prefix}_{uuid.uuid4().hex[:16]}"
    gen_dir.mkdir(parents=True, exist_ok=False)
    return gen_dir


def _discard_generation(generation_dir: Path | None) -> None:
    if generation_dir is not None:
        shutil.rmtree(generation_dir, ignore_errors=True)


def _upstream_generation_digest_violation(
    record: dict, *, upstream_key: str, current_digest: str | None
) -> tuple[str, ...]:
    """B1-F3: whether ``record`` (an exact_match or report accepted record)
    still names the CURRENT upstream stage's generation digest — used at
    restart-skip time so a downstream stage is never left "skippable" after
    its upstream stage produced a genuinely new generation (even when the
    downstream stage's own declared-input fingerprint never changed, e.g. a
    forced same-input upstream rerun). ``None`` on either side (no digest
    recorded — an older record, or the upstream stage never executed) is
    never treated as a violation by itself; the caller's own evidence-hash
    check already covers a missing/non-executed record.
    """
    recorded = record.get(upstream_key)
    if recorded is None or current_digest is None:
        return ()
    if recorded != current_digest:
        return (
            f"{upstream_key}: recorded generation digest {recorded} != current {current_digest} (the upstream "
            "stage produced a new generation since this record was accepted)",
        )
    return ()


def _generation_still_referenced(
    old_generation_digest: str | None, *, downstream_records: Sequence[dict], upstream_keys: Sequence[str]
) -> bool:
    """B1-F3: whether any already-accepted downstream record still names
    ``old_generation_digest`` as the exact upstream generation it was
    produced from — used to refuse pruning a generation a downstream record
    still depends on (see ``_prune_superseded_generation``'s
    ``referenced_by`` argument).
    """
    if old_generation_digest is None:
        return False
    for record in downstream_records:
        if not record.get("executed"):
            continue
        for key in upstream_keys:
            value = record.get(key)
            if isinstance(value, dict):
                if old_generation_digest in value.values():
                    return True
            elif value == old_generation_digest:
                return True
    return False


def _prune_superseded_generation(
    old_record: dict,
    *,
    path_fields: Sequence[str],
    new_generation_dir: Path,
    referenced_by: Sequence[dict] = (),
    upstream_keys: Sequence[str] = (),
) -> None:
    """Best-effort disk hygiene, never required for correctness: once a new
    generation has been durably accepted (the caller's new JSON record has
    already been written), the OLD generation directory a just-replaced
    ``executed: true`` record pointed at is no longer referenced by anything
    and is safe to remove, keeping real disk usage bounded across repeated
    real B3-B6 retries. Only ever called AFTER the new record write
    succeeds; defensively never removes anything outside a ``generations/``
    directory this module itself created.

    B1-F3: ``referenced_by``/``upstream_keys``, when given, additionally
    refuse pruning when an already-accepted downstream record (e.g. an
    ``align.json`` still naming this exact index generation's digest) still
    depends on this generation — a forced upstream rerun must never silently
    delete evidence a downstream accepted record still reproduces from.
    """
    if not old_record.get("executed"):
        return
    if upstream_keys and _generation_still_referenced(
        old_record.get("generation_digest"), downstream_records=referenced_by, upstream_keys=upstream_keys
    ):
        return
    old_dir: Path | None = None
    for field_name in path_fields:
        value = old_record.get(field_name)
        if isinstance(value, dict):
            # A nested {"dest_path": "...", "byte_size": ..., ...}-shaped
            # entry (download's "fasta"/"assembly_report") always names its
            # path via "dest_path"; a plain {tool: path, ...}-shaped mapping
            # (align's "sam_paths") has no such key, so fall back to the
            # first string value. Picking "any truthy value" without this
            # distinction previously picked a nonzero byte_size *int* over
            # the actual path string, since JSON round-tripping sorts keys
            # alphabetically ("byte_size" before "dest_path").
            value = value.get("dest_path") or next((v for v in value.values() if isinstance(v, str) and v), None)
        if isinstance(value, str) and value:
            old_dir = Path(value).parent
            break
    if old_dir is None or old_dir == new_generation_dir:
        return
    if old_dir.parent.name == "generations" and old_dir.is_dir():
        shutil.rmtree(old_dir, ignore_errors=True)


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


def _current_output_bytes(paths: Sequence[str | Path | None]) -> int:
    """Sum of the on-disk byte sizes of every existing path in ``paths``
    (B1-C3): used to compute how much of a build's combined output
    allowance a LATER writer (e.g. SeqKit in ``stage_exact_match``) has
    remaining, given what an EARLIER writer (e.g. BWA/minimap2 in
    ``stage_align``) already accepted for the same build — a single shared
    live counter across writers, never each independently granted its own
    full allowance. Missing/None entries contribute zero, never raise.
    """
    total = 0
    for entry in paths:
        if entry is None:
            continue
        path = Path(entry)
        if path.is_file():
            total += path.stat().st_size
    return total


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


def _acquisition_capable(*, allow_mapping: bool, host_role: str) -> str | None:
    """Same basic capability shape as ``_mapping_capable``/``_index_capable``
    for download/derive, which need neither a reference file nor reads yet
    (they *produce* the reference).
    """
    if not allow_mapping or host_role != APPROVED_MAC:
        return (
            "reference acquisition/derivation requires --allow-mapping together with --host-role=approved_mac "
            f"(got allow_mapping={allow_mapping}, host_role={host_role!r})"
        )
    return None


def stage_download(
    *,
    build: str,
    source_spec: ReferenceSourceSpec,
    sources_dir: Path,
    allow_mapping: bool,
    host_role: str,
    dry_run: bool,
    disk_ledger: DiskBudgetLedger | None = None,
    transport: Transport = urllib_transport,
) -> dict:
    """B1-C1: restart-safe, disk-budget-gated acquisition of one reference
    build's compressed source FASTA, assembly report, AND the live
    ``md5checksums.txt`` listing (fetched through the same injected-transport
    interface), cross-checked against the execution-source spec's
    authoritative upstream MD5s/byte size (never silently re-pinned on
    drift) before being recorded as executed. The whole source set is
    promoted as one immutable generation (B1-C2): every file is written
    directly into a fresh ``sources_dir/generations/<id>/`` directory (see
    ``_new_generation_dir``) and only becomes "accepted" once
    ``download.json`` is written pointing at it — a failure at any point
    before that write (including a checksum-listing mismatch) leaves the
    previously accepted generation, if any, completely untouched.

    ``transport`` defaults to the real network transport
    (:func:`rbpbench.coordinates.download.urllib_transport`) for actual B3+
    use; B1 itself never reaches that default — every B1 test passes an
    injected local fake transport, and B1's authorization boundary forbids
    requesting any real NCBI URL regardless.
    """
    old_record_path = sources_dir / "download.json"
    record = {
        "planned": {
            "fasta_url": source_spec.fasta_url,
            "assembly_report_url": source_spec.assembly_report_url,
            "md5checksums_url": source_spec.md5checksums_url,
            # B3A-A1: the exact remote basenames (derived from the frozen
            # URLs' own final path segment, never the shorter assembly
            # label) this attempt binds local files and checksum lookup to.
            "fasta_remote_basename": source_spec.fasta_remote_basename,
            "assembly_report_remote_basename": source_spec.assembly_report_remote_basename,
        },
        "executed": False,
        "skip_reason": None,
    }

    if dry_run:
        record["skip_reason"] = "--dry-run: real download is never executed under --dry-run"
        _guarded_write_record(old_record_path, record)
        return record

    skip_reason = _acquisition_capable(allow_mapping=allow_mapping, host_role=host_role)
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
        _guarded_write_record(old_record_path, record)
        return record

    # The disk-budget snapshot requires an existing path; sources_dir may
    # not exist yet on a genuinely first download.
    sources_dir.mkdir(parents=True, exist_ok=True)
    _check_disk_budget_or_fail(
        disk_ledger,
        label=f"download:{build}",
        allowance_gib=PLANNED_ALLOWANCES_GIB["source_packages_and_metadata"],
        disk_path=sources_dir,
    )

    generation_dir = _new_generation_dir(sources_dir, prefix="download")
    violations: list[str] = []
    fasta_result = None
    report_result = None
    try:
        # B3A-A1: fetch and parse the SMALL checksum listing FIRST, through
        # the same injected-transport interface used for the FASTA/report
        # below — never a bare, ungated network call of its own. The exact
        # intended FASTA/assembly-report entries (by their real remote
        # basename, never the shorter assembly label) must be present and
        # agree with the frozen plan values BEFORE the large-FASTA transport
        # call is ever made.
        checksum_dest = generation_dir / "md5checksums.txt"
        transport(source_spec.md5checksums_url, checksum_dest)
        if not checksum_dest.is_file():
            raise DownloadVerificationError(
                f"transport for {source_spec.md5checksums_url!r} did not produce a file at {checksum_dest}"
            )
        listing = parse_md5checksums_evidence(checksum_dest.read_text())
        live_entries = listing.entries
        # B3A-A1: structured malformed/duplicate/conflicting listing
        # evidence is added to this SAME fail-closed violation list, never a
        # separate silent channel — a structurally broken listing is exactly
        # as disqualifying as a value mismatch.
        violations.extend(
            f"md5checksums.txt parse violation ({v.kind}): {v.detail}" for v in listing.violations
        )

        fasta_basename = source_spec.fasta_remote_basename
        report_basename = source_spec.assembly_report_remote_basename
        # B1-C1/B3A-A1: require exactly the two intended entries (keyed by
        # their real remote basename) and compare the live listing against
        # the frozen plan MD5. Plan-time size/MD5 values remain authoritative
        # (second-review R11): any disagreement is a hard stop requiring a
        # recorded decision, never silent re-pinning.
        for label, basename, frozen_md5 in (
            ("fasta", fasta_basename, source_spec.fasta_upstream_md5),
            ("assembly_report", report_basename, source_spec.assembly_report_md5),
        ):
            live_md5 = live_entries.get(basename)
            if live_md5 is None:
                violations.append(f"live md5checksums.txt has no entry for {basename!r} ({label})")
                continue
            if live_md5 != frozen_md5:
                violations.append(
                    f"live md5checksums.txt entry for {basename!r} ({label}) is {live_md5!r}, but the "
                    f"authoritative plan value is {frozen_md5!r}; this disagreement is a hard stop requiring a "
                    "recorded decision in docs/DECISIONS.md, never silent re-pinning"
                )

        # B3A-A1: only proceed to the large-file transport calls once the
        # listing itself (and its two intended entries) is confirmed clean —
        # a checksum-listing failure must never even attempt the large FASTA
        # transport.
        if not violations:
            fasta_dest = generation_dir / fasta_basename
            report_dest = generation_dir / report_basename
            fasta_result = restart_safe_download(
                source_spec.fasta_url, fasta_dest, expected_md5=source_spec.fasta_upstream_md5, transport=transport
            )
            report_result = restart_safe_download(
                source_spec.assembly_report_url,
                report_dest,
                expected_md5=source_spec.assembly_report_md5,
                transport=transport,
            )
            for label, dest, downloaded_md5 in (
                ("fasta", fasta_dest, fasta_result.md5),
                ("assembly_report", report_dest, report_result.md5),
            ):
                live_md5 = live_entries.get(dest.name)
                if live_md5 != downloaded_md5:
                    violations.append(
                        f"live md5checksums.txt entry for {dest.name!r} ({label}) is {live_md5!r}, but the "
                        f"downloaded file's own MD5 is {downloaded_md5!r}"
                    )
            if fasta_result.byte_size != source_spec.fasta_compressed_byte_size:
                violations.append(
                    f"downloaded FASTA byte size {fasta_result.byte_size} != authoritative plan size "
                    f"{source_spec.fasta_compressed_byte_size}; this disagreement is a hard stop requiring a "
                    "recorded decision in docs/DECISIONS.md, never silent re-pinning"
                )
    except BaseException:
        _discard_generation(generation_dir)
        raise

    if violations:
        _discard_generation(generation_dir)
        record["skip_reason"] = "; ".join(violations)
        _guarded_write_record(old_record_path, record)
        return record

    if disk_ledger is not None:
        disk_ledger.record_step(f"download:{build}", path=sources_dir)

    old_record = json.loads(old_record_path.read_text()) if old_record_path.is_file() else {}

    record["executed"] = True
    record["fasta"] = fasta_result.to_dict()
    record["assembly_report"] = report_result.to_dict()
    record["checksum_listing"] = {
        "dest_path": str(checksum_dest),
        "sha256": sha256_file(checksum_dest),
        "byte_size": checksum_dest.stat().st_size,
        "url": source_spec.md5checksums_url,
    }
    # Transaction completion requirement: a failure WRITING the atomic
    # selection record itself (after every file in the generation has
    # already been successfully produced) must discard the new generation
    # — never leave it lingering, unselected, on disk — while the previous
    # selection (if any) is untouched regardless, since `_guarded_write_record`
    # itself writes atomically (temp file + os.replace) and therefore can
    # never corrupt the prior accepted record on a mid-write failure.
    try:
        _guarded_write_record(old_record_path, record)
    except BaseException:
        _discard_generation(generation_dir)
        raise
    _prune_superseded_generation(old_record, path_fields=("fasta", "assembly_report"), new_generation_dir=generation_dir)
    return record


def stage_derive(
    *,
    build: str,
    source_spec: ReferenceSourceSpec,
    derived_dir: Path,
    allow_mapping: bool,
    host_role: str,
    download_record: dict,
    dry_run: bool,
    disk_ledger: DiskBudgetLedger | None = None,
) -> dict:
    """B1-C1/C2: streaming, restart-safe derivation of the frozen-contig-
    policy reference FASTA + manifest from an already-downloaded/verified
    source, re-hashing the CURRENT source files against ``download_record``
    immediately before deriving (never merely trusting its ``executed: true``
    boolean and recorded paths, which could have drifted since download
    ran). The derived FASTA and its manifest are promoted together as ONE
    immutable generation (see ``_new_generation_dir``): both are written
    directly into a fresh ``derived_dir/generations/<id>/`` directory and
    only become "accepted" once ``derive.json`` is written pointing at both
    — a failure between writing the FASTA and building/persisting the
    manifest can therefore never leave a new FASTA paired with a stale or
    missing manifest at a shared final path.
    """
    old_record_path = derived_dir / "derive.json"
    record = {"executed": False, "skip_reason": None}

    if dry_run:
        record["skip_reason"] = "--dry-run: real derivation is never executed under --dry-run"
        _guarded_write_record(old_record_path, record)
        return record

    skip_reason = _acquisition_capable(allow_mapping=allow_mapping, host_role=host_role)
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
        _guarded_write_record(old_record_path, record)
        return record

    if not download_record.get("executed"):
        record["skip_reason"] = "download stage did not execute; nothing to derive from"
        _guarded_write_record(old_record_path, record)
        return record

    # B1-C1: re-hash the current source files against what download.json
    # actually recorded, immediately before trusting them as derivation
    # input — never merely the "executed: true" boolean and recorded paths.
    source_evidence_violations = _verify_download_evidence_hashes(download_record)
    if source_evidence_violations:
        record["skip_reason"] = (
            "accepted source evidence has drifted since download; refusing to derive from it: "
            f"{list(source_evidence_violations)}"
        )
        _guarded_write_record(old_record_path, record)
        return record

    derived_dir.mkdir(parents=True, exist_ok=True)
    _check_disk_budget_or_fail(
        disk_ledger,
        label=f"derive:{build}",
        allowance_gib=PLANNED_ALLOWANCES_GIB["derived_references_and_indices"],
        disk_path=derived_dir,
    )

    source_fasta = Path(download_record["fasta"]["dest_path"])
    assembly_report = Path(download_record["assembly_report"]["dest_path"])
    generation_dir = _new_generation_dir(derived_dir, prefix="derive")
    try:
        output_fasta = generation_dir / "reference.fna"
        manifest_path = generation_dir / "reference_manifest.json"
        derivation = derive_reference_fasta(
            source_fasta=source_fasta, assembly_report=assembly_report, output_fasta=output_fasta
        )
        manifest = build_reference_manifest(
            derivation,
            build_id=build,
            assembly_accession=source_spec.refseq_assembly_accession,
            source_url=source_spec.fasta_url,
            source_fasta_compressed=source_fasta,
            source_fasta_compressed_upstream_md5=source_spec.fasta_upstream_md5,
            assembly_report=assembly_report,
            assembly_report_upstream_md5=source_spec.assembly_report_md5,
            derivation_command=f"derive_reference_fasta(build={build!r})",
            git_commit=current_git_commit(),
        )
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    except BaseException:
        _discard_generation(generation_dir)
        raise

    if disk_ledger is not None:
        disk_ledger.record_step(f"derive:{build}", path=derived_dir)

    old_record = json.loads(old_record_path.read_text()) if old_record_path.is_file() else {}

    record["executed"] = True
    record["output_fasta"] = str(output_fasta)
    record["output_fasta_sha256"] = derivation.output_fasta_sha256
    record["reference_manifest_path"] = str(manifest_path)
    # B1-F4: the derived MANIFEST's own file hash/size, not merely the
    # derived FASTA's — required so a later semantic edit to the manifest
    # file (its content, not merely its path existing) is detectable as
    # drifted evidence (see _verify_derive_evidence_hashes).
    record["reference_manifest_sha256"] = sha256_file(manifest_path)
    record["reference_manifest_byte_size"] = manifest_path.stat().st_size
    # Transaction completion requirement: see the matching comment in
    # stage_download.
    try:
        _guarded_write_record(old_record_path, record)
    except BaseException:
        _discard_generation(generation_dir)
        raise
    _prune_superseded_generation(old_record, path_fields=("output_fasta",), new_generation_dir=generation_dir)
    return record


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
    reference_manifest_raw_sha256: str | None = None,
    downstream_align_record: dict | None = None,
) -> dict:
    """Prepare the build-specific BWA index prefix and minimap2 ``.mmi`` index
    under ``index_dir`` (the pinned ``indices/<build>/`` directory), with
    creation-time provenance (commands, output-file hashes/sizes, elapsed
    time, peak memory) and minimap2's resolved-parameter/single-part
    verification. Gated identically to ``stage_align``/``stage_exact_match``:
    ``--dry-run`` is an absolute guard checked first, then the same
    allow-mapping/host-role/reference-manifest/fresh-preflight chain.

    B1-C2: the BWA/minimap2 index files AND their manifest are produced
    directly inside one fresh, immutable generation directory (see
    ``_new_generation_dir``) — never a fixed, reused ``index_dir/<build>``
    path — so promotion is nothing more than ``index.json`` (written last,
    atomically) naming that directory's paths.
    """
    placeholder_bwa_prefix = index_dir / build
    placeholder_mm2_index = index_dir / f"{build}.mmi"
    record = {
        "planned_commands": {
            "bwa_index": format_command(
                ("bwa", "index", "-p", str(placeholder_bwa_prefix), str(reference or Path("reference.fasta")))
            ),
            "minimap2_index": format_command(
                (
                    "minimap2",
                    "-x",
                    "splice:sr",
                    "-I",
                    "8G",
                    "-d",
                    str(placeholder_mm2_index),
                    str(reference or Path("reference.fasta")),
                )
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
        _guarded_write_record(index_dir / "index.json", record)
        return record
    record["reference_manifest"] = reference_manifest
    manifest_violations = validate_reference_manifest(reference_manifest, build=build, reference=reference)
    record["reference_manifest_validation"] = {"provided": True, "violations": list(manifest_violations)}
    if manifest_violations:
        record["skip_reason"] = f"reference manifest invalid for build {build!r}: {list(manifest_violations)}"
        _guarded_write_record(index_dir / "index.json", record)
        return record

    # B1-R2: the current reference/manifest content hashes this index is
    # about to be built from and bound to, recorded on the index manifest
    # itself (never merely inferred later from whatever happens to be on
    # disk) so a later real-mapping attempt can refuse a self-consistent but
    # foreign index (see rbpbench.coordinates.indexing.verify_index_binding).
    current_reference_sha256 = reference_manifest["sha256"]
    current_manifest_hash = manifest_content_sha256(reference_manifest)
    record["reference_sha256"] = current_reference_sha256
    record["reference_manifest_content_sha256"] = current_manifest_hash

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
        _guarded_write_record(index_dir / "index.json", record)
        return record

    # B1-C2: build both indices AND their manifest directly inside one
    # fresh, immutable generation directory — never at the fixed
    # ``index_dir/<build>``/``index_dir/index_manifest.json`` paths a prior
    # attempt may already occupy — so a failure at any point (including
    # between building the two indices and persisting the manifest) leaves
    # the previously accepted generation, if any, completely untouched; the
    # new generation only becomes "accepted" when index.json (below) is
    # written pointing at it.
    generation_dir = _new_generation_dir(index_dir, prefix="index")
    bwa_prefix = generation_dir / build
    mm2_index = generation_dir / f"{build}.mmi"
    try:
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

        manifest = build_index_manifest(
            build=build,
            bwa=bwa_provenance,
            minimap2=mm2_provenance,
            reference_sha256=current_reference_sha256,
            reference_manifest_content_sha256=current_manifest_hash,
            reference_manifest_raw_sha256=reference_manifest_raw_sha256,
        )
        manifest_path = generation_dir / "index_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    except BaseException:
        _discard_generation(generation_dir)
        raise

    old_record_path = index_dir / "index.json"
    old_record = json.loads(old_record_path.read_text()) if old_record_path.is_file() else {}

    record["executed"] = True
    record["bwa_index_prefix"] = str(bwa_prefix)
    record["minimap2_index"] = str(mm2_index)
    record["index_manifest_path"] = str(manifest_path)
    record["reference_manifest_raw_sha256"] = reference_manifest_raw_sha256
    # B1-F3: this generation's own content-derived digest — identical index
    # content (even rebuilt into a fresh generation directory by a forced
    # same-input rerun) yields the same digest, so downstream (align)
    # revalidation can distinguish "byte-equivalent rebuild" from "the index
    # actually changed" rather than trusting only a declared-input
    # fingerprint chain.
    record["generation_digest"] = manifest_content_sha256(manifest)
    # Transaction completion requirement: see the matching comment in
    # stage_download.
    try:
        _guarded_write_record(old_record_path, record)
    except BaseException:
        _discard_generation(generation_dir)
        raise
    _prune_superseded_generation(
        old_record,
        path_fields=("bwa_index_prefix", "minimap2_index"),
        new_generation_dir=generation_dir,
        referenced_by=(downstream_align_record or {},),
        upstream_keys=("upstream_index_generation_digest",),
    )
    return record


def _probe_capable(*, allow_mapping: bool, host_role: str, reference: Path | None) -> str | None:
    """Same basic capability shape as ``_mapping_capable``/``_index_capable``
    for the probe stage. The accepted B2 biological/control evidence is no
    longer a caller-supplied path/hash pair checked here (B3A-R1): see
    :func:`rbpbench.coordinates.probe.load_and_verify_b2_checkpoint`, called
    separately inside ``stage_probe`` against the real committed B2
    checkpoint manifest.
    """
    if not allow_mapping or host_role != APPROVED_MAC:
        return (
            "probe requires --allow-mapping together with --host-role=approved_mac "
            f"(got allow_mapping={allow_mapping}, host_role={host_role!r})"
        )
    if reference is None or not Path(reference).is_file():
        return f"reference FASTA not found or not provided ({reference})"
    return None


def _verify_index_record_for_probe(
    index_record: dict,
    *,
    build: str,
    expected_reference_sha256: str,
    expected_reference_manifest_content_sha256: str,
    expected_reference_manifest_raw_sha256: str | None = None,
) -> tuple[str, ...]:
    """B3A-R2: the accepted index generation the probe is about to
    smoke-test must itself be executed and FULLY bound -- build, actual
    paths/files, reference hash, canonical AND raw reference-manifest
    hashes, and the recomputed CURRENT index-manifest content digest against
    the ``generation_digest`` ``index.json`` recorded when it was accepted --
    using the same :func:`rbpbench.coordinates.indexing.verify_index_binding`
    logic ``align``'s own restart revalidation uses (never a partial check
    that only re-hashes files and compares two copied-over scalar fields).
    """
    if not index_record.get("executed"):
        return ("index.json does not record executed=true",)
    manifest_path = index_record.get("index_manifest_path")
    if not manifest_path or not Path(manifest_path).is_file():
        return ("index manifest missing (recorded evidence has drifted)",)
    try:
        manifest = json.loads(Path(manifest_path).read_text())
    except (json.JSONDecodeError, OSError):
        return ("index manifest unreadable (recorded evidence has drifted)",)

    violations: list[str] = []
    bwa_prefix = index_record.get("bwa_index_prefix")
    mm2_index = index_record.get("minimap2_index")
    for actual_path, key in (
        (Path(bwa_prefix) if bwa_prefix else None, "bwa_index"),
        (Path(mm2_index) if mm2_index else None, "minimap2_index"),
    ):
        if actual_path is None:
            violations.append(f"{key}: no path recorded in index.json")
            continue
        violations.extend(
            verify_index_binding(
                manifest,
                key=key,
                actual_path=actual_path,
                expected_build=build,
                expected_reference_sha256=expected_reference_sha256,
                expected_reference_manifest_content_sha256=expected_reference_manifest_content_sha256,
                expected_reference_manifest_raw_sha256=expected_reference_manifest_raw_sha256,
            )
        )

    recorded_digest = index_record.get("generation_digest")
    if recorded_digest is not None:
        current_digest = manifest_content_sha256(manifest)
        if current_digest != recorded_digest:
            violations.append(
                f"index generation_digest {recorded_digest} does not match the current index manifest content "
                f"digest {current_digest} (the index was rebuilt or altered since accepted)"
            )
    return tuple(violations)


def _validate_probe_sam(sam_path: Path, *, query_id: str, contigs: frozenset) -> tuple[str, ...]:
    """B3A-A3 item 5: require the one smoke query to appear exactly once as
    a PRIMARY, mapped record, on a contig actually in the accepted
    reference's contig set. Multi-mapping (secondary records) is allowed and
    never itself a violation.
    """
    primary_records = []
    for line in Path(sam_path).read_text().splitlines():
        record = parse_sam_line(line)
        if record is None or record.query_name != query_id or not record.is_primary:
            continue
        primary_records.append(record)
    if len(primary_records) != 1:
        return (
            f"expected exactly one primary, mapped SAM record for smoke query {query_id!r} in {sam_path}, "
            f"found {len(primary_records)}",
        )
    if primary_records[0].chrom not in contigs:
        return (
            f"smoke query {query_id!r} mapped to {primary_records[0].chrom!r}, which is not in the accepted "
            "reference's contig set (foreign-contig mapping)",
        )
    return ()


def stage_probe(
    cfg: FeasibilityConfig,
    *,
    build: str,
    build_output_dir: Path,
    allow_mapping: bool,
    host_role: str,
    reference: Path | None,
    reference_manifest: dict | None,
    reference_manifest_raw_sha256: str | None,
    index_record: dict,
    b2_manifest_path: Path | None,
    dry_run: bool,
    repo_root: Path = Path("."),
    b2_manifest_expected_sha256: str | None = None,
    b2_manifest_expected_checkpoint: str = B2_ACCEPTED_CHECKPOINT,
    b2_manifest_expected_status: str = B2_ACCEPTED_STATUS,
    b2_expected_biological_count: int | None = None,
    b2_expected_control_count: int | None = None,
    disk_ledger: DiskBudgetLedger | None = None,
    build_budget: BuildOutputBudget | None = None,
    window_length: int = 500,
) -> dict:
    """B3A-A3/R1-R7: the guarded, build-scoped feasibility probe stage.

    Gated exactly like ``stage_align``/``stage_index``: the absolute
    ``--dry-run`` guard is checked first, then the same allow-mapping/
    host-role/reference capability chain, then a *fresh* ``run_preflight``
    immediately before any real subprocess. NEVER writes ``align.json``,
    ``exact_match.json``, or any report/combined-report state -- this is its
    own protected ``probe.json`` record, using the same transactional
    generation-directory + ``_guarded_write_record`` pattern already used by
    ``stage_download``/``stage_derive``/``stage_index``.

    B3A-R1: the accepted B2 biological/control evidence is bound through
    ``b2_manifest_path`` (the real committed checkpoint manifest) rather than
    caller-supplied FASTA hashes -- see
    :func:`rbpbench.coordinates.probe.load_and_verify_b2_checkpoint`.
    ``b2_expected_biological_count``/``b2_expected_control_count`` are left
    ``None`` by default (the direct-function/test seam); real CLI mode
    (``main()``) always supplies the frozen 10,000/100 constants and is the
    ONLY caller that does so -- no CLI flag exposes them.
    """
    old_record_path = build_output_dir / "probe.json"
    record = {"executed": False, "skip_reason": None}

    # Absolute guard, checked before anything else (same as stage_align).
    if dry_run:
        record["skip_reason"] = "--dry-run: real probing is never executed under --dry-run"
        _guarded_write_record(old_record_path, record)
        return record

    skip_reason = _probe_capable(allow_mapping=allow_mapping, host_role=host_role, reference=reference)
    if skip_reason is not None:
        record["skip_reason"] = skip_reason
        _guarded_write_record(old_record_path, record)
        return record

    if reference_manifest is None:
        record["skip_reason"] = f"reference manifest required for probe but not provided for build {build!r}"
        _guarded_write_record(old_record_path, record)
        return record
    manifest_violations = validate_reference_manifest(reference_manifest, build=build, reference=reference)
    if manifest_violations:
        record["skip_reason"] = f"reference manifest invalid for build {build!r}: {list(manifest_violations)}"
        _guarded_write_record(old_record_path, record)
        return record

    contig_lengths = reference_manifest.get("contig_lengths") or {}
    if not contig_lengths:
        record["skip_reason"] = f"reference manifest for build {build!r} has no contig_lengths evidence (B3A-A2 required)"
        _guarded_write_record(old_record_path, record)
        return record

    current_reference_sha256 = reference_manifest["sha256"]
    current_manifest_hash = manifest_content_sha256(reference_manifest)

    # B3A-R1: the real trust anchor -- require and revalidate the accepted
    # B2 checkpoint manifest itself (never a caller-supplied hash pair) and
    # derive the exact accepted biological/control ID sets from it, BEFORE
    # any candidate work begins.
    if b2_manifest_path is None:
        record["skip_reason"] = "no accepted B2 checkpoint manifest path supplied to bind the probe to"
        _guarded_write_record(old_record_path, record)
        return record
    b2_evidence, b2_violations = load_and_verify_b2_checkpoint(
        b2_manifest_path,
        repo_root=repo_root,
        expected_manifest_sha256=b2_manifest_expected_sha256,
        expected_checkpoint=b2_manifest_expected_checkpoint,
        expected_status=b2_manifest_expected_status,
        expected_biological_count=b2_expected_biological_count,
        expected_control_count=b2_expected_control_count,
    )
    if b2_violations:
        record["skip_reason"] = f"accepted B2 checkpoint evidence is missing or has drifted: {list(b2_violations)}"
        _guarded_write_record(old_record_path, record)
        return record

    index_violations = _verify_index_record_for_probe(
        index_record, build=build, expected_reference_sha256=current_reference_sha256,
        expected_reference_manifest_content_sha256=current_manifest_hash,
        expected_reference_manifest_raw_sha256=reference_manifest_raw_sha256,
    )
    if index_violations:
        record["skip_reason"] = f"accepted index generation is missing, has drifted, or is foreign: {list(index_violations)}"
        _guarded_write_record(old_record_path, record)
        return record

    record["reference_sha256"] = current_reference_sha256
    record["reference_manifest_content_sha256"] = current_manifest_hash
    record["reference_manifest_raw_sha256"] = reference_manifest_raw_sha256
    record["upstream_index_generation_digest"] = index_record.get("generation_digest")
    record["b2_checkpoint_evidence"] = b2_evidence.to_dict()

    # Hard prerequisite: a fresh preflight bound to the current OS/
    # architecture, resources, pinned tool versions, and hashes of this
    # exact reference/B2-FASTA set -- never merely the flags checked above.
    build_output_dir.mkdir(parents=True, exist_ok=True)
    preflight_report = run_preflight(
        host_role=host_role,
        resources=cfg.resources,
        disk_path=build_output_dir,
        allow_mapping=True,
        tools=cfg.tools,
        threads=1,  # B3A-A3 item 5: probe smoke mapping is pinned one-thread.
        required_input_paths={
            "reference": reference, "b2_sample": b2_evidence.sample_fasta, "b2_control": b2_evidence.control_fasta,
        },
    )
    _write_json(build_output_dir / "preflight_at_probe_time.json", preflight_report.to_dict())
    record["preflight_ok"] = preflight_report.ok
    if not preflight_report.ok:
        record["skip_reason"] = f"preflight failed closed immediately before probing: {list(preflight_report.violations)}"
        _guarded_write_record(old_record_path, record)
        return record

    # B3A-R3: require a resolved, clean Git commit before any real probe
    # subprocess -- never merely recorded as evidence after the fact.
    git_commit_now = current_git_commit()
    git_clean_now = git_is_clean()
    if not git_commit_now or not git_clean_now:
        record["skip_reason"] = (
            f"a resolved clean Git commit is required before any real probe subprocess "
            f"(git_commit={git_commit_now!r}, git_clean={git_clean_now!r})"
        )
        _guarded_write_record(old_record_path, record)
        return record

    # B3A-A3 item 10 (budget rule 1 of 2): before any candidate work, the
    # whole-run projected-peak ledger must accept BOTH a <=1-GiB candidate-
    # work reservation (drawn from the EXISTING environment/logs margin) AND
    # a conservative 2-GiB next-step reservation -- neither adds a new
    # PLANNED_ALLOWANCES_GIB category.
    _check_disk_budget_or_fail(
        disk_ledger, label=f"probe_candidate:{build}", allowance_gib=PROBE_CANDIDATE_WORK_ALLOWANCE_GIB,
        disk_path=build_output_dir,
    )
    _check_disk_budget_or_fail(
        disk_ledger, label=f"probe_projected_peak:{build}", allowance_gib=PROBE_PROJECTED_PEAK_NEXT_STEP_GIB,
        disk_path=build_output_dir,
    )

    # B3A-R2: fully validate contig_lengths -- exact key equality with
    # `contigs`, positive integer values, AND agreement with an
    # independently-streamed total base count of the CURRENT reference file
    # on disk -- BEFORE the largest contig is ever selected. This is what
    # actually catches a hand-edited contig_lengths entry inside an
    # otherwise sha256/byte_size-valid reference_manifest.
    computed_total_bases = total_reference_bases(reference)
    contig_length_violations = validate_contig_lengths(
        contig_lengths, contigs=tuple(reference_manifest.get("contigs", ())),
        assembly_report_lengths={}, total_emitted_bases=computed_total_bases,
    )
    if contig_length_violations:
        record["skip_reason"] = f"contig_lengths validation failed for build {build!r}: {list(contig_length_violations)}"
        _guarded_write_record(old_record_path, record)
        return record

    accession = largest_contig(contig_lengths)
    contig_length = contig_lengths[accession]

    # B3A-R4: an explicitly reviewed non-destructive retention policy -- old
    # accepted probe generations are never deleted in B3A (see the module
    # docstring/A3 item 11), so accepted-bytes accounting must be the
    # CUMULATIVE total across every retained generation, never merely the
    # newest one, or real disk usage could silently exceed what is tracked.
    old_record = json.loads(old_record_path.read_text()) if old_record_path.is_file() else {}
    prior_retained_bytes = old_record.get("accepted_bytes", 0) if old_record.get("executed") else 0

    # B3A-A3 item 10 (budget rule 2 of 2): the probe's OWN retained-output
    # live sub-cap (<=1 GiB total across every retained generation),
    # independent of (and seeded into) the shared per-build BuildOutputBudget
    # later stages use.
    probe_output_budget = start_build_output_budget(
        already_accepted_bytes=prior_retained_bytes, total_allowance_gib=PROBE_OUTPUT_ALLOWANCE_GIB
    )

    def _tool_output_cap() -> int:
        # B3A-R5: live-cap each tool by the SMALLER of the probe's own
        # remaining 1-GiB retained share and the shared build budget's
        # remaining bytes -- never the probe's own share in isolation, which
        # could stay technically satisfied while the combined 4-GiB build
        # cap is already exhausted by another accepted stage for this build.
        remaining = probe_output_budget.remaining_bytes
        if build_budget is not None:
            remaining = min(remaining, build_budget.remaining_bytes)
        return remaining

    generation_dir = _new_generation_dir(build_output_dir, prefix="probe")
    candidate_dir = generation_dir / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    bwa_sam = generation_dir / "probe_bwa_mem.sam"
    bwa_stderr = generation_dir / "probe_bwa_mem.stderr.log"
    mm2_sam = generation_dir / "probe_minimap2_splice.sam"
    mm2_stderr = generation_dir / "probe_minimap2_splice.stderr.log"
    seqkit_bed = generation_dir / "probe_seqkit_locate.bed"
    seqkit_stderr = generation_dir / "probe_seqkit_locate.stderr.log"

    def _candidate_bytes_or_raise() -> int:
        # B3A-R5: enforce the candidate workspace's own 1-GiB bound on
        # OBSERVED growth, checked before every subsequent writer -- never
        # merely the whole-run projected-peak check above, which is a
        # pre-flight free-disk ESTIMATE, not a live cap on what this
        # attempt's own candidate files actually grow to.
        total = sum(f.stat().st_size for f in candidate_dir.rglob("*") if f.is_file())
        if total > PROBE_CANDIDATE_WORK_ALLOWANCE_GIB * GIB:
            raise ProbeError(
                f"probe candidate workspace at {candidate_dir} has grown to {total} bytes, exceeding the "
                f"{PROBE_CANDIDATE_WORK_ALLOWANCE_GIB}-GiB candidate-work cap"
            )
        return total

    try:
        # B3A-R6: an honest available/reclaimable-memory reading taken at the
        # very start of real probe work, used by the memory projection gate
        # below (distinct from ``host_mem_before``/``host_mem_after``, which
        # bracket the SeqKit call specifically for its own resource evidence).
        host_mem_at_probe_start = host_memory_snapshot()

        # Item 2: transactional 10,100(-equivalent) pattern FASTA, bound to
        # the accepted B2 checkpoint's exact biological/control ID sets.
        pattern_result = build_pattern_fasta(
            b2_evidence.sample_fasta, b2_evidence.control_fasta, candidate_dir / "patterns.fasta",
            expected_biological_ids=b2_evidence.biological_ids, expected_control_ids=b2_evidence.control_ids,
        )
        _candidate_bytes_or_raise()

        # Item 3: streaming single-largest-contig extraction, never
        # materializing the (potentially ~249-Mb) contig as one string.
        contig_extraction = extract_contig_streaming(
            reference, accession=accession, output_path=candidate_dir / "contig.fna"
        )
        _candidate_bytes_or_raise()
        extraction_violations: list[str] = []
        if contig_extraction.length != contig_length:
            extraction_violations.append(
                f"extracted contig {accession!r} length {contig_extraction.length} != accepted contig_lengths "
                f"{contig_length}"
            )
        total_extracted_bases = contig_extraction.upper_count + contig_extraction.lower_count + contig_extraction.ambiguous_count
        if total_extracted_bases != contig_extraction.length:
            extraction_violations.append("extracted contig base-count evidence is internally inconsistent")
        if extraction_violations:
            raise ProbeError("; ".join(extraction_violations))

        # Item 4: deterministic A/C/G/T-only smoke window.
        window = select_probe_window(
            contig_extraction.output_path, accession=accession, contig_length=contig_length, window_length=window_length
        )
        contig_index = build_fasta_index(contig_extraction.output_path)
        smoke_seq = IndexedFastaReader(contig_extraction.output_path, contig_index).fetch(accession, window.start, window.end)
        if len(smoke_seq) != window_length or set(smoke_seq) - _ACGT_ONLY:
            raise ProbeError(f"selected smoke window did not yield a clean {window_length}-nt A/C/G/T sequence")
        smoke_query_id = f"probe_smoke_{accession}_{window.start}_{window.end}"
        smoke_query_path = candidate_dir / "smoke_query.fasta"
        smoke_query_path.write_text(f">{smoke_query_id}\n{smoke_seq}\n")
        _candidate_bytes_or_raise()

        # Item 5: pinned, one-thread BWA-MEM and minimap2 smoke mapping
        # against the accepted build indices.
        bwa_index_prefix = Path(index_record["bwa_index_prefix"])
        minimap2_index = Path(index_record["minimap2_index"])
        bwa_cmd = bwa_mem_command(bwa_index_prefix, smoke_query_path, threads=1)
        mm2_cmd = minimap2_splice_command(minimap2_index, smoke_query_path, threads=1)
        bwa_binary = resolve_binary_provenance("bwa", version=preflight_report.tool_versions.get("bwa"))
        mm2_binary = resolve_binary_provenance("minimap2", version=preflight_report.tool_versions.get("minimap2"))
        seqkit_binary = resolve_binary_provenance("seqkit", version=preflight_report.tool_versions.get("seqkit"))

        bwa_provenance = run_tool_with_provenance(
            bwa_cmd.argv, tool="probe_bwa_mem", output_path=bwa_sam, stderr_path=bwa_stderr,
            command_text=format_command(bwa_cmd.argv), binary=bwa_binary, run_fn=_run_tool_to_file,
            run_kwargs={"max_output_bytes": _tool_output_cap()},
        )
        probe_output_budget.accept(bwa_sam.stat().st_size + bwa_stderr.stat().st_size)

        mm2_provenance = run_tool_with_provenance(
            mm2_cmd.argv, tool="probe_minimap2_splice", output_path=mm2_sam, stderr_path=mm2_stderr,
            command_text=format_command(mm2_cmd.argv), binary=mm2_binary, run_fn=_run_tool_to_file,
            run_kwargs={"max_output_bytes": _tool_output_cap()},
        )
        probe_output_budget.accept(mm2_sam.stat().st_size + mm2_stderr.stat().st_size)

        smoke_violations: list[str] = []
        smoke_violations.extend(check_minimap2_mapping_stderr(mm2_stderr.read_text()))
        contigs_frozenset = frozenset(reference_manifest.get("contigs", ()))
        smoke_violations.extend(_validate_probe_sam(bwa_sam, query_id=smoke_query_id, contigs=contigs_frozenset))
        smoke_violations.extend(_validate_probe_sam(mm2_sam, query_id=smoke_query_id, contigs=contigs_frozenset))
        if smoke_violations:
            raise ProbeError("; ".join(smoke_violations))

        # Item 6/7: pinned SeqKit 2.13.0, exact B4 command semantics, against
        # ONLY the extracted largest contig, with all patterns in one
        # invocation.
        seqkit_cmd = seqkit_locate_command(pattern_result.output_path, contig_extraction.output_path)
        host_mem_before = host_memory_snapshot()
        seqkit_provenance = run_tool_with_provenance(
            seqkit_cmd.argv, tool="probe_seqkit_locate", output_path=seqkit_bed, stderr_path=seqkit_stderr,
            command_text=format_command(seqkit_cmd.argv), binary=seqkit_binary, run_fn=_run_tool_to_file,
            run_kwargs={"max_output_bytes": _tool_output_cap()},
        )
        host_mem_after = host_memory_snapshot()
        seqkit_bytes_used = seqkit_bed.stat().st_size + seqkit_stderr.stat().st_size
        probe_output_budget.accept(seqkit_bytes_used)

        # B3A-R6: stream BED validation line-by-line -- never
        # ``read_text().splitlines()``, which materializes a file allowed to
        # approach 1 GiB (plus additional copies) as one Python list.
        with seqkit_bed.open() as bed_handle:
            bed_validation = validate_probe_bed_rows(
                bed_handle, known_pattern_ids=pattern_result.id_set,
                contig_accession=accession, contig_length=contig_length,
            )
        if not bed_validation.ok:
            raise ProbeError("; ".join(bed_validation.violations))

        # B3A-R6: the accepted wall/output/memory projection evidence and
        # fail-closed gates -- a failed or unavailable gate must prevent
        # probe acceptance, exactly like any other business-rule failure.
        projection = compute_probe_projection(
            largest_contig_length=contig_length,
            total_reference_bases=computed_total_bases,
            observed_wall_seconds=seqkit_provenance.elapsed_seconds,
            observed_output_bytes=seqkit_bed.stat().st_size,
            observed_peak_rss_kib=seqkit_provenance.peak_rss_kib_of_children,
            observed_hit_count=bed_validation.hit_count,
            physical_ram_gib=preflight_report.physical_ram_gib,
            available_memory_gib=host_mem_at_probe_start.get("available_reclaimable_memory_gib"),
            probe_output_allowance_bytes=int(PROBE_OUTPUT_ALLOWANCE_GIB * GIB),
        )
        if not projection.ok:
            raise ProbeError("probe projection gates failed: " + "; ".join(projection.violations))
    except ProbeError as exc:
        # Item 7/8: a business-rule validation failure (bad extraction,
        # unmapped/foreign-contig smoke mapping, malformed BED evidence,
        # over-cap candidate growth, a failed projection gate) is an honest,
        # non-executed probe outcome -- discard the candidate generation and
        # record it via skip_reason, the same graceful shape every other
        # guarded stage uses, never an uncaught exception.
        _discard_generation(generation_dir)
        record["skip_reason"] = f"probe validation failed: {exc}"
        _guarded_write_record(old_record_path, record)
        return record
    except BaseException:
        # Anything else (a genuine infrastructure failure: a killed
        # subprocess, an unexpected I/O error, a mocked interruption in
        # tests) discards the candidate generation and propagates, exactly
        # like every other guarded stage's transactional generation
        # handling.
        _discard_generation(generation_dir)
        raise

    # B3A-R4: fail closed if candidate cleanup is not complete -- a real
    # tool output must never be promoted while the ephemeral candidate
    # workspace it was built from silently failed to be removed.
    shutil.rmtree(candidate_dir, ignore_errors=True)
    if candidate_dir.exists():
        _discard_generation(generation_dir)
        record["skip_reason"] = f"probe candidate workspace cleanup did not complete at {candidate_dir}"
        _guarded_write_record(old_record_path, record)
        return record

    if disk_ledger is not None:
        disk_ledger.record_step(f"probe:{build}", path=build_output_dir)

    new_generation_bytes = (
        bwa_sam.stat().st_size + bwa_stderr.stat().st_size
        + mm2_sam.stat().st_size + mm2_stderr.stat().st_size
        + seqkit_bed.stat().st_size + seqkit_stderr.stat().st_size
    )
    # B3A-R4: the cumulative accepted-bytes total across EVERY retained probe
    # generation (never deleted in B3A -- see above), never merely this
    # newest generation's own bytes.
    accepted_bytes = prior_retained_bytes + new_generation_bytes

    fingerprint = probe_fingerprint(
        b2_manifest_sha256=b2_evidence.manifest_sha256,
        b2_sample_sha256=b2_evidence.sample_fasta_sha256,
        b2_control_sha256=b2_evidence.control_fasta_sha256,
        reference_sha256=current_reference_sha256,
        reference_manifest_content_sha256=current_manifest_hash,
        reference_manifest_raw_sha256=reference_manifest_raw_sha256,
        index_generation_digest=index_record.get("generation_digest"),
        bwa_binary_sha256=bwa_binary.sha256,
        minimap2_binary_sha256=mm2_binary.sha256,
        seqkit_binary_sha256=seqkit_binary.sha256,
        bwa_binary_version=bwa_binary.version,
        minimap2_binary_version=mm2_binary.version,
        seqkit_binary_version=seqkit_binary.version,
        bwa_command=format_command(bwa_cmd.argv),
        minimap2_command=format_command(mm2_cmd.argv),
        seqkit_command=format_command(seqkit_cmd.argv),
        git_commit=git_commit_now,
        git_clean=git_clean_now,
    )

    record["executed"] = True
    record["build"] = build
    record["selected_contig"] = {"accession": accession, "length": contig_length}
    record["total_reference_bases"] = computed_total_bases
    record["smoke_window"] = {"accession": window.accession, "start": window.start, "end": window.end}
    record["pattern_fasta"] = pattern_result.to_dict()
    record["candidate_contig_evidence"] = contig_extraction.to_dict()
    record["sam_paths"] = {"bwa_mem": str(bwa_sam), "minimap2_splice": str(mm2_sam)}
    record["stderr_paths"] = {
        "bwa_mem": str(bwa_stderr), "minimap2_splice": str(mm2_stderr), "seqkit_locate": str(seqkit_stderr),
    }
    record["bed_path"] = str(seqkit_bed)
    record["bed_validation"] = bed_validation.to_dict()
    record["resource_evidence"] = {
        "bwa_mem": bwa_provenance.to_dict(),
        "minimap2_splice": mm2_provenance.to_dict(),
        "seqkit_locate": seqkit_provenance.to_dict(),
        "host_memory_at_probe_start": host_mem_at_probe_start,
        "host_memory_before_seqkit": host_mem_before,
        "host_memory_after_seqkit": host_mem_after,
    }
    record["projection"] = projection.to_dict()
    record["accepted_bytes"] = accepted_bytes
    record["new_generation_bytes"] = new_generation_bytes
    record["probe_output_allowance_bytes"] = int(PROBE_OUTPUT_ALLOWANCE_GIB * GIB)
    record["git_commit"] = git_commit_now
    record["git_clean"] = git_clean_now
    record["probe_fingerprint"] = fingerprint
    record["generation_digest"] = content_fingerprint(
        "probe_generation",
        bwa_provenance.output_sha256, bwa_provenance.stderr_sha256,
        mm2_provenance.output_sha256, mm2_provenance.stderr_sha256,
        seqkit_provenance.output_sha256, seqkit_provenance.stderr_sha256,
        fingerprint,
    )

    # B3A-A3 item 10: seed the probe's own CUMULATIVE accepted bytes into the
    # SAME shared per-build BuildOutputBudget later used by align/
    # exact_match/report for this build, so probe+B4 accepted build outputs
    # can never together exceed the combined 4-GiB cap.
    if build_budget is not None:
        build_budget.accept(accepted_bytes)

    try:
        _guarded_write_record(old_record_path, record)
    except BaseException:
        _discard_generation(generation_dir)
        raise
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
    reference_manifest_raw_sha256: str | None = None,
    build_budget: BuildOutputBudget | None = None,
    downstream_exact_match_record: dict | None = None,
    downstream_report_state: dict | None = None,
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
        _guarded_write_record(build_output_dir / "align.json", record)
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
        _guarded_write_record(build_output_dir / "align.json", record)
        return record

    # B1-R1: the current reference/manifest content hashes this align
    # attempt is about to use, recorded on the accepted record so
    # exact_match/report can later refuse to combine themselves with a
    # different reference (see stage_exact_match/stage_report).
    current_reference_sha256 = reference_manifest["sha256"]
    current_manifest_hash = manifest_content_sha256(reference_manifest)
    record["reference_sha256"] = current_reference_sha256
    record["reference_manifest_content_sha256"] = current_manifest_hash
    record["reference_manifest_raw_sha256"] = reference_manifest_raw_sha256

    # B1-R2: stale/foreign/split-directory-override index rejection. Each
    # override (or the default indices/<build>/ pair) is verified against
    # *its own* index_manifest.json, looked up from its own directory — a
    # single shared index_dir inference previously let a minimap2-only
    # override silently skip verification against a BWA override rooted
    # elsewhere, or vice versa. Every check additionally proves the index
    # manifest itself is bound to the *current* reference/manifest content,
    # not merely that its own recorded files still hash correctly (a
    # self-consistent but foreign index, rebuilt from a different FASTA with
    # its own manifest replaced to match, must still be refused).
    index_violations: list[str] = []
    upstream_index_generation_digest: dict[str, str | None] = {}
    for override_path, key in ((bwa_index_prefix, "bwa_index"), (minimap2_index, "minimap2_index")):
        if override_path is None:
            continue
        override_manifest_path = override_path.parent / "index_manifest.json"
        if not override_manifest_path.is_file():
            index_violations.append(f"{key}: no index manifest found at {override_manifest_path}")
            continue
        override_manifest = json.loads(override_manifest_path.read_text())
        index_violations.extend(
            verify_index_binding(
                override_manifest,
                key=key,
                actual_path=override_path,
                expected_build=build,
                expected_reference_sha256=current_reference_sha256,
                expected_reference_manifest_content_sha256=current_manifest_hash,
                expected_reference_manifest_raw_sha256=reference_manifest_raw_sha256,
            )
        )
        # B1-F3: the exact index generation this align attempt is about to
        # bind to, content-derived (identical content -> identical digest,
        # regardless of which generation directory it happens to live in
        # right now) so downstream restart validation can later detect "the
        # index was rebuilt/altered since align last accepted it" even when
        # a forced same-input rerun never changed any declared-input
        # fingerprint.
        upstream_index_generation_digest[key] = manifest_content_sha256(override_manifest)
    record["index_manifest_validation"] = {"violations": list(index_violations)}
    if index_violations:
        record["skip_reason"] = f"prepared index failed manifest verification (stale/foreign index): {index_violations}"
        _guarded_write_record(build_output_dir / "align.json", record)
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
        _guarded_write_record(build_output_dir / "align.json", record)
        return record

    # Fail-closed disk-budget check (B1-C3): both mapper output writers share
    # ONE combined build-output allowance, checked once before either
    # subprocess starts and then split between them as each writer's actual
    # bytes become known — never each writer independently granted its own
    # full allowance.
    disk_budget_check = _check_disk_budget_or_fail(
        disk_ledger, label=f"align:{build}", allowance_gib=BUILD_OUTPUT_ALLOWANCE_GIB, disk_path=build_output_dir
    )
    # B1-F1: the LIVE per-build output budget, shared with exact_match/report
    # for this same build across separate invocations (see
    # ``rbpbench.coordinates.diskbudget.BuildOutputBudget``) — already seeded
    # by the caller with every OTHER stage's current accepted bytes for this
    # build. Falls back to a fresh, unseeded budget for direct unit-test
    # callers that invoke this function without going through ``main``.
    budget = build_budget if build_budget is not None else start_build_output_budget(
        total_allowance_gib=BUILD_OUTPUT_ALLOWANCE_GIB
    )

    bwa_binary = resolve_binary_provenance("bwa", version=preflight_report.tool_versions.get("bwa"))
    mm2_binary = resolve_binary_provenance("minimap2", version=preflight_report.tool_versions.get("minimap2"))

    # B1-C2: write directly into one fresh, immutable generation directory —
    # never a fixed, reused final path — so promotion is nothing more than
    # align.json (written last, atomically) naming this directory's paths. A
    # failure after bwa succeeds but before minimap2 completes (or before
    # its mapping stderr is confirmed clean — see B1-R8 below) simply
    # abandons this generation; the previously accepted one (if any) is
    # completely untouched.
    generation_dir = _new_generation_dir(build_output_dir, prefix="align")
    bwa_sam = generation_dir / "align_bwa_mem.sam"
    bwa_stderr = generation_dir / "align_bwa_mem.stderr.log"
    mm2_sam = generation_dir / "align_minimap2_splice.sam"
    mm2_stderr = generation_dir / "align_minimap2_splice.stderr.log"
    try:
        # B1-F1: bwa's own live cap is the budget's CURRENT remainder
        # (already net of every other build artifact already accepted for
        # this build) — both stdout (SAM) and stderr are polled together
        # inside ``_run_tool_to_file``, so stderr-only growth cannot bypass
        # this cap.
        bwa_provenance = run_tool_with_provenance(
            bwa_cmd.argv,
            tool="bwa_mem",
            output_path=bwa_sam,
            stderr_path=bwa_stderr,
            command_text=format_command(bwa_cmd.argv),
            binary=bwa_binary,
            run_fn=_run_tool_to_file,
            run_kwargs={"max_output_bytes": budget.remaining_bytes},
        )
        bwa_bytes_used = bwa_sam.stat().st_size + bwa_stderr.stat().st_size
        if bwa_bytes_used > budget.remaining_bytes:
            raise DiskBudgetExceeded(
                f"bwa_mem output for build {build!r} used {bwa_bytes_used} bytes, exceeding the remaining "
                f"{budget.remaining_bytes}-byte combined build-output allowance even though it finished before a "
                "live poll caught it; refusing to promote"
            )
        # Bytes are only durably ``accept``-ed into the shared budget once
        # this whole align attempt is actually promoted (below, after the
        # minimap2 mapping-stderr check) — never provisionally, which could
        # otherwise let a later writer in the SAME process under-count
        # remaining budget against an attempt that ends up discarded.
        bwa_probe_remaining = max(0, budget.remaining_bytes - bwa_bytes_used)
        # B1-C3/F1: minimap2's own share of the combined allowance is
        # whatever the budget has left AFTER bwa's actual accepted bytes —
        # a single shared live counter across both writers (and, via
        # ``budget``, across exact_match/report too), rather than each
        # independently capped at the full 4 GiB.
        mm2_provenance = run_tool_with_provenance(
            mm2_cmd.argv,
            tool="minimap2_splice",
            output_path=mm2_sam,
            stderr_path=mm2_stderr,
            command_text=format_command(mm2_cmd.argv),
            binary=mm2_binary,
            run_fn=_run_tool_to_file,
            run_kwargs={"max_output_bytes": bwa_probe_remaining},
        )
        mm2_bytes_used = mm2_sam.stat().st_size + mm2_stderr.stat().st_size
        if mm2_bytes_used > bwa_probe_remaining:
            raise DiskBudgetExceeded(
                f"minimap2_splice output for build {build!r} used {mm2_bytes_used} bytes, exceeding the remaining "
                f"{bwa_probe_remaining}-byte combined build-output allowance even though it finished before a "
                "live poll caught it; refusing to promote"
            )

        # B1-R8: minimap2's own mapping-time stderr must be inspected for
        # the same disqualifying parameter-override/multipart-index
        # conditions required at index-build time — capturing the warning is
        # not equivalent to stopping on it. Checked before promotion: a
        # disqualified attempt's SAM output must never become "accepted".
        mm2_mapping_stderr_violations = check_minimap2_mapping_stderr(mm2_stderr.read_text())
    except BaseException:
        _discard_generation(generation_dir)
        raise

    if mm2_mapping_stderr_violations:
        _discard_generation(generation_dir)
        record["skip_reason"] = (
            f"minimap2 mapping stderr indicates a disqualifying condition: {list(mm2_mapping_stderr_violations)}"
        )
        _guarded_write_record(build_output_dir / "align.json", record)
        return record

    # B1-F1: only now — after every disqualifying check has passed and this
    # generation is actually about to be promoted — durably accept both
    # writers' bytes into the shared per-build budget.
    budget.accept(bwa_bytes_used + mm2_bytes_used)

    if disk_ledger is not None:
        disk_ledger.record_step(f"align:{build}", path=build_output_dir)

    old_record_path = build_output_dir / "align.json"
    old_record = json.loads(old_record_path.read_text()) if old_record_path.is_file() else {}

    record["executed"] = True
    record["tool_versions"] = {"bwa": bwa_binary.version, "minimap2": mm2_binary.version}
    record["sam_paths"] = {"bwa_mem": str(bwa_sam), "minimap2_splice": str(mm2_sam)}
    record["stderr_paths"] = {"bwa_mem": str(bwa_stderr), "minimap2_splice": str(mm2_stderr)}
    record["index_paths"] = {
        "bwa_index_prefix": str(bwa_index_prefix) if bwa_index_prefix else None,
        "minimap2_index": str(minimap2_index) if minimap2_index else None,
    }
    record["upstream_index_generation_digest"] = upstream_index_generation_digest
    record["disk_budget_check"] = disk_budget_check
    record["provenance"] = {
        "input_hashes": preflight_report.input_hashes,
        "bwa_mem": bwa_provenance.to_dict(),
        "minimap2_splice": mm2_provenance.to_dict(),
    }
    # B1-F3: this align attempt's own content-derived generation digest,
    # chaining the exact index generation(s) it actually used — identical
    # SAM/stderr content and identical upstream index digests always yield
    # the same value, so a byte-equivalent forced rerun is distinguishable
    # from a genuinely different one downstream (exact_match/report).
    record["generation_digest"] = content_fingerprint(
        "align_generation",
        bwa_provenance.output_sha256,
        bwa_provenance.stderr_sha256,
        mm2_provenance.output_sha256,
        mm2_provenance.stderr_sha256,
        tuple(sorted(upstream_index_generation_digest.items())),
    )
    # Transaction completion requirement: see the matching comment in
    # stage_download.
    try:
        _guarded_write_record(old_record_path, record)
    except BaseException:
        _discard_generation(generation_dir)
        raise
    _prune_superseded_generation(
        old_record,
        path_fields=("sam_paths",),
        new_generation_dir=generation_dir,
        referenced_by=(downstream_exact_match_record or {}, downstream_report_state or {}),
        upstream_keys=("upstream_align_generation_digest",),
    )
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
    reference_manifest_raw_sha256: str | None = None,
    build_budget: BuildOutputBudget | None = None,
    downstream_report_state: dict | None = None,
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
        _guarded_write_record(build_output_dir / "exact_match.json", record)
        return record

    # Same reference-manifest requirement/validation as stage_align — an
    # independent check, not a reused one.
    if reference_manifest is None:
        record["skip_reason"] = f"reference manifest required for real exact-match but not provided for build {build!r}"
        _guarded_write_record(build_output_dir / "exact_match.json", record)
        return record
    record["reference_manifest"] = reference_manifest
    manifest_violations = validate_reference_manifest(reference_manifest, build=build, reference=reference)
    record["reference_manifest_validation"] = {"provided": True, "violations": list(manifest_violations)}
    if manifest_violations:
        record["skip_reason"] = f"reference manifest invalid for build {build!r}: {list(manifest_violations)}"
        _guarded_write_record(build_output_dir / "exact_match.json", record)
        return record

    # B1-R1: exact-match's active reference/manifest must equal the one
    # align recorded — fail closed rather than silently combining BWA
    # mapping evidence from one reference with SeqKit exact matches computed
    # against a different one (the original second-review R3 failure).
    current_reference_sha256 = reference_manifest["sha256"]
    current_manifest_hash = manifest_content_sha256(reference_manifest)
    if (
        align_record.get("reference_sha256") != current_reference_sha256
        or align_record.get("reference_manifest_content_sha256") != current_manifest_hash
        # B1-F4: also compare the RAW manifest-file hash, not merely the
        # canonical parsed-content hash — two manifest files that parse to
        # identical content but differ byte-for-byte must still be detected.
        or (
            reference_manifest_raw_sha256 is not None
            and align_record.get("reference_manifest_raw_sha256") not in (None, reference_manifest_raw_sha256)
        )
    ):
        record["skip_reason"] = (
            f"current reference/manifest for build {build!r} does not match the reference recorded by align "
            "(stale/foreign reference); refusing to combine exact-match evidence with mapping from a different "
            "reference"
        )
        _guarded_write_record(build_output_dir / "exact_match.json", record)
        return record
    record["reference_sha256"] = current_reference_sha256
    record["reference_manifest_content_sha256"] = current_manifest_hash
    record["reference_manifest_raw_sha256"] = reference_manifest_raw_sha256
    # B1-F3: the exact align generation this exact-match attempt is about to
    # confirm, so downstream restart validation can detect align having
    # produced a NEW generation since this exact_match record was accepted.
    record["upstream_align_generation_digest"] = align_record.get("generation_digest")

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
        _guarded_write_record(build_output_dir / "exact_match.json", record)
        return record

    disk_budget_check = _check_disk_budget_or_fail(
        disk_ledger, label=f"exact_match:{build}", allowance_gib=BUILD_OUTPUT_ALLOWANCE_GIB, disk_path=build_output_dir
    )
    # B1-C3/F1: SeqKit shares the SAME live per-build budget as align's
    # BWA/minimap2 writers (and report's writers) — never its own
    # independent full 4 GiB — already seeded by the caller with every OTHER
    # stage's current accepted bytes for this build.
    budget = build_budget if build_budget is not None else start_build_output_budget(
        already_accepted_bytes=_current_output_bytes(
            (*(align_record.get("sam_paths") or {}).values(), *(align_record.get("stderr_paths") or {}).values())
        ),
        total_allowance_gib=BUILD_OUTPUT_ALLOWANCE_GIB,
    )

    seqkit_binary = resolve_binary_provenance("seqkit", version=preflight_report.tool_versions.get("seqkit"))

    # B1-C2: write directly into one fresh, immutable generation directory —
    # never a fixed, reused final path — so promotion is nothing more than
    # exact_match.json (written last, atomically) naming this directory's
    # paths; a failed/killed seqkit run can never truncate a previously
    # accepted BED.
    generation_dir = _new_generation_dir(build_output_dir, prefix="exact_match")
    bed_path = generation_dir / "exact_match_hits.bed"
    stderr_path = generation_dir / "exact_match_hits.stderr.log"
    query_cmd = seqkit_locate_command(reads_fasta, reference)
    try:
        provenance = run_tool_with_provenance(
            query_cmd.argv,
            tool="seqkit_locate",
            output_path=bed_path,
            stderr_path=stderr_path,
            command_text=format_command(query_cmd.argv),
            binary=seqkit_binary,
            run_fn=_run_tool_to_file,
            run_kwargs={"max_output_bytes": budget.remaining_bytes},
        )
        seqkit_bytes_used = bed_path.stat().st_size + stderr_path.stat().st_size
        if seqkit_bytes_used > budget.remaining_bytes:
            raise DiskBudgetExceeded(
                f"seqkit_locate output for build {build!r} used {seqkit_bytes_used} bytes, exceeding the "
                f"remaining {budget.remaining_bytes}-byte combined build-output allowance even though it finished "
                "before a live poll caught it; refusing to promote"
            )
    except BaseException:
        _discard_generation(generation_dir)
        raise

    budget.accept(seqkit_bytes_used)

    if disk_ledger is not None:
        disk_ledger.record_step(f"exact_match:{build}", path=build_output_dir)

    old_record_path = build_output_dir / "exact_match.json"
    old_record = json.loads(old_record_path.read_text()) if old_record_path.is_file() else {}

    record["executed"] = True
    record["tool_version"] = seqkit_binary.version
    record["bed_path"] = str(bed_path)
    record["stderr_path"] = str(stderr_path)
    record["disk_budget_check"] = disk_budget_check
    record["provenance"] = {
        "input_hashes": preflight_report.input_hashes,
        "seqkit_locate": provenance.to_dict(),
    }
    record["generation_digest"] = content_fingerprint(
        "exact_match_generation", provenance.output_sha256, provenance.stderr_sha256, record["upstream_align_generation_digest"]
    )
    # Transaction completion requirement: see the matching comment in
    # stage_download.
    try:
        _guarded_write_record(old_record_path, record)
    except BaseException:
        _discard_generation(generation_dir)
        raise
    _prune_superseded_generation(
        old_record,
        path_fields=("bed_path",),
        new_generation_dir=generation_dir,
        referenced_by=(downstream_report_state or {},),
        upstream_keys=("upstream_exact_match_generation_digest",),
    )
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


def _report_state_path(build_output_dir: Path) -> Path:
    return build_output_dir / "report_state.json"


def _load_report_state(build_output_dir: Path) -> dict:
    path = _report_state_path(build_output_dir)
    if not path.is_file():
        return {"executed": False}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"executed": False}


def _verify_report_state_evidence_hashes(report_state: dict) -> tuple[str, ...]:
    """B1-F2: re-verify every artifact the accepted ``report_state.json``
    record names — inside its own generation directory, the authoritative
    source — still exists and hash-matches, immediately before a restart
    skip. Mirrors ``_verify_align_evidence_hashes``/
    ``_verify_exact_match_evidence_hashes`` for the report stage.
    """
    if not report_state.get("executed"):
        return ("report_state.json does not record executed=true",)
    violations: list[str] = []
    if not _hash_matches(report_state.get("report_json_path"), report_state.get("report_json_sha256")):
        violations.append("report report.json missing or hash mismatch (recorded evidence has drifted)")
    if not _hash_matches(report_state.get("report_md_path"), report_state.get("report_md_sha256")):
        violations.append("report report.md missing or hash mismatch (recorded evidence has drifted)")
    if report_state.get("mappings_tsv_gz_path") is not None and not _hash_matches(
        report_state.get("mappings_tsv_gz_path"), report_state.get("mappings_tsv_gz_sha256")
    ):
        violations.append("report mappings.tsv.gz missing or hash mismatch (recorded evidence has drifted)")
    if report_state.get("reference_index_path") is not None and not _hash_matches(
        report_state.get("reference_index_path"), report_state.get("reference_index_sha256")
    ):
        violations.append("report reference_index.json missing or hash mismatch (recorded evidence has drifted)")
    return tuple(violations)


def _load_accepted_report_state(
    build_output_dir: Path,
    *,
    align_record: dict | None = None,
    exact_match_record: dict | None = None,
) -> tuple[dict, tuple[str, ...]]:
    """B1 acceptance correction (final convergence review): the ONE shared
    fail-closed loader/validator for an accepted per-build report state,
    used by every downstream consumer — report-stage restart revalidation,
    ``stage_combined_report``, ``_write_provenance``, and cleanup — so none
    of them may independently reinvent this check or silently fall back to
    a human-convenience fixed-path mirror. Requires ``executed: true``,
    hash-verifies every artifact ``report_state.json`` selects
    (``_verify_report_state_evidence_hashes``), and — when the caller
    supplies the CURRENT align/exact_match records — additionally requires
    the exact upstream generation digests this report state names to still
    match what those records presently carry
    (``_upstream_generation_digest_violation``). Returns
    ``(report_state, violations)``: a non-empty ``violations`` tuple means
    no accepted report is currently usable, and every caller must fail
    closed rather than reading any fixed-path mirror as a substitute.
    """
    report_state = _load_report_state(build_output_dir)
    violations = list(_verify_report_state_evidence_hashes(report_state))
    if align_record is not None:
        violations.extend(
            _upstream_generation_digest_violation(
                report_state,
                upstream_key="upstream_align_generation_digest",
                current_digest=align_record.get("generation_digest"),
            )
        )
    if exact_match_record is not None:
        violations.extend(
            _upstream_generation_digest_violation(
                report_state,
                upstream_key="upstream_exact_match_generation_digest",
                current_digest=exact_match_record.get("generation_digest"),
            )
        )
    return report_state, tuple(violations)


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
    reference_manifest: dict | None = None,
    reference_manifest_raw_sha256: str | None = None,
    build_budget: BuildOutputBudget | None = None,
) -> dict:
    """B1-F2: the complete per-build report artifact set (reference-index
    diagnostic, compressed mappings table, report JSON, report Markdown) is
    produced into one fresh, immutable generation directory and validated
    (reconciliation status AND the combined build-output budget, B1-F1)
    BEFORE any promotion decision. Promotion is a single atomic write of the
    protected ``report_state.json`` pointer record (see
    ``_guarded_write_record``); human-convenience mirror copies at the
    conventional fixed ``build_output_dir`` filenames (``report.json`` etc.)
    are written ONLY after that record has already been durably committed —
    combined_report/cleanup/provenance all treat ``report_state.json`` (never
    the mirror) as ground truth. A failed reconciliation or a budget breach
    discards the candidate generation and NEVER touches a previously
    accepted report at the fixed filenames or ``report_state.json``: a forced
    retry that fails can never silently erase a previously accepted report
    (B1-F2's core defect).
    """
    mapping_evaluated = bool(align_record.get("executed")) and bool(exact_match_record.get("executed"))
    mapping_results: tuple[MappingResult, ...] = ()
    expected_control_ids: tuple[str, ...] = ()
    reference_binding: dict = {
        "reference_sha256": None,
        "reference_manifest_content_sha256": None,
        "reference_manifest_raw_sha256": reference_manifest_raw_sha256,
    }

    if mapping_evaluated:
        # B1-R1: report's active reference/manifest must equal both the
        # reference align recorded and the one exact_match recorded — fail
        # closed (hard stop, nothing written) rather than silently attaching
        # the current reference/junction diagnostics to mapping/exact-match
        # evidence produced under a different one. A forced re-run of just
        # `report` against a swapped --reference is exactly the scenario this
        # closes (the original second-review R3 failure).
        if reference_manifest is None:
            raise SystemExit(
                f"reference manifest required for report's reference-binding check but not provided for build "
                f"{build!r}"
            )
        report_manifest_violations = validate_reference_manifest(reference_manifest, build=build, reference=reference)
        if report_manifest_violations:
            raise SystemExit(
                f"reference manifest invalid for build {build!r} at report time: {list(report_manifest_violations)}"
            )
        current_reference_sha256 = reference_manifest["sha256"]
        current_manifest_hash = manifest_content_sha256(reference_manifest)
        for label, upstream_record in (("align", align_record), ("exact_match", exact_match_record)):
            if (
                upstream_record.get("reference_sha256") != current_reference_sha256
                or upstream_record.get("reference_manifest_content_sha256") != current_manifest_hash
                # B1-F4: also compare the RAW manifest-file hash, closing the
                # gap a canonical-content-only comparison leaves.
                or (
                    reference_manifest_raw_sha256 is not None
                    and upstream_record.get("reference_manifest_raw_sha256")
                    not in (None, reference_manifest_raw_sha256)
                )
            ):
                raise SystemExit(
                    f"report refuses to combine build {build!r}: the current reference/manifest does not match "
                    f"the reference recorded by {label} (stale/foreign reference); refusing to attach current "
                    "evidence to older mapping evidence"
                )
        reference_binding["reference_sha256"] = current_reference_sha256
        reference_binding["reference_manifest_content_sha256"] = current_manifest_hash

    build_output_dir.mkdir(parents=True, exist_ok=True)
    old_state = _load_report_state(build_output_dir)
    budget = build_budget if build_budget is not None else start_build_output_budget(
        already_accepted_bytes=_current_output_bytes(
            (
                *(align_record.get("sam_paths") or {}).values(),
                *(align_record.get("stderr_paths") or {}).values(),
                exact_match_record.get("bed_path"),
                exact_match_record.get("stderr_path"),
            )
        ),
        total_allowance_gib=BUILD_OUTPUT_ALLOWANCE_GIB,
    )

    generation_dir = _new_generation_dir(build_output_dir, prefix="report")
    mappings_path: Path | None = None
    reference_index_path: Path | None = None
    report_json_path = generation_dir / Path(cfg.outputs.report_json).name
    report_md_path = generation_dir / Path(cfg.outputs.report_md).name
    try:
        if mapping_evaluated:
            representative_ids = sorted(sample.representative_ids)
            expected_control_ids = tuple(
                f"{CONTROL_ID_PREFIX}{sid}" for sid in representative_ids[:expected_controls]
            )
            expected_ids = {a.sample_id: a.stratum for a in sample.assignments}
            for control_id in expected_control_ids:
                expected_ids[control_id] = "control"

            reference_lookup = None
            if reference is not None and Path(reference).is_file():
                # Indexed random access (never a whole-file load): suitable
                # for an hg38/hg19-scale reference, since only a single
                # sequential pass builds the index and every lookup
                # thereafter seeks directly to the requested span.
                index_entries, index_record = prepare_reference_index(Path(reference))
                reference_index_path = generation_dir / "reference_index.json"
                _write_json(reference_index_path, index_record)
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
            mappings_path = generation_dir / Path(cfg.outputs.mappings_tsv_gz).name
            write_mappings_tsv_gz(mappings_path, rows)

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
        report_md_text = render_markdown(report)
        report_json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
        report_json_path.write_text(report_json_text)
        report_md_path.write_text(report_md_text)

        # B1-F1: the candidate set's combined bytes must fit the remaining
        # per-build budget BEFORE any promotion decision — never promoted
        # first and discovered oversized after.
        candidate_bytes = _current_output_bytes(
            [mappings_path, reference_index_path, report_json_path, report_md_path]
        )
        if candidate_bytes > budget.remaining_bytes:
            raise DiskBudgetExceeded(
                f"report artifact set for build {build!r} would use {candidate_bytes} bytes, exceeding the "
                f"remaining {budget.remaining_bytes}-byte combined build-output allowance; refusing to promote "
                "(previously accepted report, if any, is untouched)"
            )
    except BaseException:
        _discard_generation(generation_dir)
        raise

    if reconciliation.status == "failed":
        # B1-F2: NEVER promote on a failed reconciliation — the candidate
        # generation is discarded and every previously accepted fixed-path
        # artifact / report_state.json is left byte-for-byte untouched, so a
        # forced retry that fails can never overwrite a previously accepted
        # report (the exact B1-F2 defect).
        _discard_generation(generation_dir)
        return report

    budget.accept(candidate_bytes)

    new_state = {
        "executed": True,
        "generation_dir": str(generation_dir),
        "mappings_tsv_gz_path": str(mappings_path) if mappings_path is not None else None,
        "mappings_tsv_gz_sha256": sha256_file(mappings_path) if mappings_path is not None else None,
        "reference_index_path": str(reference_index_path) if reference_index_path is not None else None,
        "reference_index_sha256": sha256_file(reference_index_path) if reference_index_path is not None else None,
        "report_json_path": str(report_json_path),
        "report_json_sha256": sha256_file(report_json_path),
        "report_md_path": str(report_md_path),
        "report_md_sha256": sha256_file(report_md_path),
        "reconciliation_status": reconciliation.status,
        "reference_binding": reference_binding,
        # B1-F3: the exact upstream align/exact_match generations this
        # report attempt is about to confirm, so downstream restart
        # validation can detect either having produced a NEW generation
        # since this report was accepted.
        "upstream_align_generation_digest": align_record.get("generation_digest"),
        "upstream_exact_match_generation_digest": exact_match_record.get("generation_digest"),
    }
    new_state["generation_digest"] = content_fingerprint(
        "report_generation",
        new_state["report_json_sha256"],
        new_state["report_md_sha256"],
        new_state["mappings_tsv_gz_sha256"],
        new_state["upstream_align_generation_digest"],
        new_state["upstream_exact_match_generation_digest"],
    )
    # Transaction completion requirement: see the matching comment in
    # stage_download.
    try:
        _guarded_write_record(_report_state_path(build_output_dir), new_state)
    except BaseException:
        _discard_generation(generation_dir)
        raise
    _prune_superseded_generation(old_state, path_fields=("report_json_path",), new_generation_dir=generation_dir)

    # Human-convenience mirror at the conventional fixed filenames, written
    # ONLY after report_state.json (the authoritative commit) has already
    # succeeded — combined_report/cleanup/provenance never read these mirror
    # files as ground truth, only report_state.json's generation-dir files.
    (build_output_dir / Path(cfg.outputs.report_json).name).write_text(report_json_text)
    (build_output_dir / Path(cfg.outputs.report_md).name).write_text(report_md_text)
    if mappings_path is not None:
        shutil.copyfile(mappings_path, build_output_dir / Path(cfg.outputs.mappings_tsv_gz).name)
    if reference_index_path is not None:
        shutil.copyfile(reference_index_path, build_output_dir / "reference_index.json")

    return report


def stage_combined_report(
    sample: SamplingResult,
    *,
    cfg: FeasibilityConfig,
    output_dir: Path,
    builds: Sequence[str],
    reference_manifests: dict[str, dict] | None = None,
    align_records: dict[str, dict] | None = None,
    exact_match_records: dict[str, dict] | None = None,
) -> dict:
    """Collision-safe per-build artifacts already exist under
    ``output_dir/<build>/``; this reads every one of them back from disk (the
    same resume-safety pattern as align/exact_match reloading) and produces
    the single combined report the parent task requires before Task 001B.

    B1 acceptance correction: each build's report/mappings evidence is read
    from its SELECTED ``report_state.json`` generation (via
    ``_load_accepted_report_state``), never the human-convenience fixed-path
    ``report.json``/``mappings.tsv.gz`` mirrors — a mirror that is missing,
    stale, or corrupt (a crash window between the atomic
    ``report_state.json`` commit and the mirror writes) must never affect
    this scientific result.

    Second acceptance correction (A1): ``align_records``/``exact_match_records``
    -- each build's CURRENT align/exact_match records, when supplied -- are
    forwarded to ``_load_accepted_report_state`` so a selected report whose
    recorded ``upstream_align_generation_digest``/
    ``upstream_exact_match_generation_digest`` no longer matches the current
    upstream generation (a forced align/exact-match rerun that never
    re-triggered ``report``) fails closed here too, exactly like the report
    stage's own restart revalidation, rather than silently combining a report
    that is stale with respect to its declared upstream inputs.
    """
    reference_manifests = reference_manifests or {}
    align_records = align_records or {}
    exact_match_records = exact_match_records or {}
    sample_meta = [{"sample_id": a.sample_id, "labels": ";".join(str(v) for v in a.labels)} for a in sample.assignments]
    representative_ids = sorted(sample.representative_ids)
    all_sample_ids = sorted(a.sample_id for a in sample.assignments)
    sample_sequences = _read_fasta(output_dir / "sample_sequences.fasta")

    per_build_summaries: dict[str, dict] = {}
    per_build_primary_by_id: dict[str, dict] = {}
    evaluated_builds: list[str] = []
    for build in builds:
        build_dir = _build_dir(output_dir, build)
        report_state, report_state_violations = _load_accepted_report_state(
            build_dir,
            align_record=align_records.get(build),
            exact_match_record=exact_match_records.get(build),
        )
        if report_state_violations:
            raise SystemExit(
                f"combined_report requires a valid, hash-verified accepted report_state.json for build {build!r} "
                f"(run the 'report' stage for build {build!r} first): {list(report_state_violations)}"
            )
        report_path = Path(report_state["report_json_path"])
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

        mappings_path = Path(report_state["mappings_tsv_gz_path"])
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
    download_records: dict[str, dict] | None = None,
    derive_records: dict[str, dict] | None = None,
    probe_records: dict[str, dict] | None = None,
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

    # Additional provenance correction: a real B1-B6 study spans several
    # *separate* runner invocations, each typically naming only its own
    # active --build. Starting from any provenance.json already on disk and
    # only overwriting the builds this invocation actually touched means
    # earlier checkpoints' build/disk evidence is preserved (cumulative)
    # rather than silently dropped whenever a later invocation names a
    # different --build subset.
    existing_provenance_path = output_dir / "provenance.json"
    builds_payload: dict = {}
    if existing_provenance_path.exists():
        try:
            builds_payload = dict(json.loads(existing_provenance_path.read_text()).get("builds", {}))
        except (json.JSONDecodeError, OSError):
            builds_payload = {}
    for build in builds:
        build_dir = _build_dir(output_dir, build)
        # B1 acceptance correction: attribute and hash the report JSON,
        # Markdown, mappings table, and reference-index diagnostic at their
        # SELECTED report_state.json generation paths, never the
        # human-convenience fixed-path mirrors -- a mirror that is missing,
        # stale, or only partially refreshed after the atomic
        # report_state.json commit must never be attributed as this build's
        # accepted evidence. A report state that fails its own fail-closed
        # validation contributes no generated-artifact evidence at all
        # (None), rather than silently falling back to a mirror.
        report_state, report_state_violations = _load_accepted_report_state(
            build_dir,
            align_record=align_records.get(build),
            exact_match_record=exact_match_records.get(build),
        )
        report_json_hash = None
        report_md_hash = None
        mappings_hash = None
        reference_index_hash = None
        reference_index_payload = None
        if not report_state_violations:
            report_json_hash = _artifact_hash(Path(report_state["report_json_path"]))
            report_md_hash = _artifact_hash(Path(report_state["report_md_path"]))
            if report_state.get("mappings_tsv_gz_path"):
                mappings_hash = _artifact_hash(Path(report_state["mappings_tsv_gz_path"]))
            if report_state.get("reference_index_path"):
                # A2: attribute the selected reference-index artifact's
                # exact path/SHA-256/byte size in generated_artifacts (the
                # same treatment as report_json/report_md/mappings_tsv_gz),
                # in addition to retaining its parsed diagnostic payload
                # separately below. A non-evaluated report genuinely has no
                # reference-index artifact -- report_state.get(...) is None
                # in that case, so this branch is skipped and both
                # reference_index_hash and reference_index_payload stay the
                # honest None they were initialized to.
                reference_index_path = Path(report_state["reference_index_path"])
                reference_index_hash = _artifact_hash(reference_index_path)
                if reference_index_path.is_file():
                    reference_index_payload = json.loads(reference_index_path.read_text())
        builds_payload[build] = {
            "download": (download_records or {}).get(build, {}),
            "derive": (derive_records or {}).get(build, {}),
            "index": index_records.get(build, {}),
            # B3A-A3 item 12: probe evidence is kept its own distinct
            # sub-key, never merged into align/exact_match/report evidence.
            "probe": (probe_records or {}).get(build, {}),
            "align": align_records.get(build, {}),
            "exact_match": exact_match_records.get(build, {}),
            "reference_manifest": reference_manifests.get(build),
            "reference_index": reference_index_payload,
            "generated_artifacts": {
                "mappings_tsv_gz": mappings_hash,
                "report_json": report_json_hash,
                "report_md": report_md_hash,
                "reference_index": reference_index_hash,
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
        "--sources-dir",
        type=Path,
        default=Path("references") / "sources",
        help="Pinned root for downloaded source packages (references/sources/<assembly>/)",
    )
    parser.add_argument(
        "--derived-dir",
        type=Path,
        default=Path("references") / "derived",
        help="Pinned root for derived reference FASTAs/manifests (references/derived/<build>/)",
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
        "--b2-manifest",
        type=Path,
        default=Path("manifests") / "coordinate_sampling_b2.json",
        help=(
            "Accepted B2 sampling-checkpoint manifest the 'probe' stage binds its pattern population to "
            "(B3A-R1). Real mode hashes this file against the frozen accepted trust anchor and enforces "
            "the accepted checkpoint/status identity and exact 10,000+100 population; there is no flag to "
            "override those frozen expectations."
        ),
    )
    parser.add_argument(
        "--disk-budget-path",
        type=Path,
        default=Path("."),
        help="Filesystem volume to measure the disk-budget ledger's baseline/free-space against",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help=(
            "Pinned repository root that --cleanup-index resolves indices/<build> against (B1-C4): cleanup "
            "refuses any --indices-dir that does not resolve to exactly repo-root/indices/<build>, and rejects "
            "every symlinked path component between the target and this root."
        ),
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


def _hash_matches(path_str: str | None, expected_sha256: str | None) -> bool:
    if not path_str or not expected_sha256:
        return False
    path = Path(path_str)
    return path.is_file() and sha256_file(path) == expected_sha256


def _verify_align_evidence_hashes(align_record: dict) -> tuple[str, ...]:
    """B1-R5/C6: prove the actual align SAM outputs still exist and match
    their own recorded hashes — never merely trust the ``executed`` JSON
    boolean, which says nothing about whether the underlying files still
    exist or were altered since. Used both by cleanup evidence-gating and by
    the runner's own restart-skip revalidation (a stage must never be
    skipped as "already completed" merely because its fingerprint still
    matches while its actual accepted artifacts have drifted).
    """
    violations: list[str] = []
    if not align_record.get("executed"):
        violations.append("align.json does not record executed=true")
        return tuple(violations)
    sam_paths = align_record.get("sam_paths", {})
    provenance = align_record.get("provenance", {})
    for tool, sam_key in (("bwa_mem", "bwa_mem"), ("minimap2_splice", "minimap2_splice")):
        expected = (provenance.get(tool) or {}).get("output_sha256")
        if not _hash_matches(sam_paths.get(sam_key), expected):
            violations.append(f"align {tool} output missing or hash mismatch (recorded evidence has drifted)")
    return tuple(violations)


def _verify_exact_match_evidence_hashes(exact_match_record: dict) -> tuple[str, ...]:
    """Same principle as :func:`_verify_align_evidence_hashes`, for the
    exact-match stage's BED output.
    """
    violations: list[str] = []
    if not exact_match_record.get("executed"):
        violations.append("exact_match.json does not record executed=true")
        return tuple(violations)
    expected = (exact_match_record.get("provenance", {}).get("seqkit_locate") or {}).get("output_sha256")
    if not _hash_matches(exact_match_record.get("bed_path"), expected):
        violations.append("exact_match seqkit_locate output missing or hash mismatch (recorded evidence has drifted)")
    return tuple(violations)


def _verify_mapping_evidence_hashes(align_record: dict, exact_match_record: dict) -> tuple[str, ...]:
    """Combined align+exact_match evidence check, kept for cleanup's use."""
    return (*_verify_align_evidence_hashes(align_record), *_verify_exact_match_evidence_hashes(exact_match_record))


def _verify_download_evidence_hashes(download_record: dict) -> tuple[str, ...]:
    """B1-C1: re-hash the actual accepted source FASTA, assembly report, and
    checksum-listing evidence against what ``download.json`` recorded — used
    both before a restart skip and immediately before derivation, so neither
    ever merely trusts the ``executed: true`` boolean and recorded paths.
    """
    violations: list[str] = []
    if not download_record.get("executed"):
        violations.append("download.json does not record executed=true")
        return tuple(violations)
    for key in ("fasta", "assembly_report"):
        entry = download_record.get(key) or {}
        if not _hash_matches(entry.get("dest_path"), entry.get("sha256")):
            violations.append(f"download {key} output missing or hash mismatch (recorded evidence has drifted)")
    checksum_listing = download_record.get("checksum_listing") or {}
    if not _hash_matches(checksum_listing.get("dest_path"), checksum_listing.get("sha256")):
        violations.append(
            "download checksum-listing evidence missing or hash mismatch (recorded evidence has drifted)"
        )
    return tuple(violations)


def _verify_derive_evidence_hashes(derive_record: dict) -> tuple[str, ...]:
    """Same principle as :func:`_verify_download_evidence_hashes`, for the
    derived FASTA + its manifest.
    """
    violations: list[str] = []
    if not derive_record.get("executed"):
        violations.append("derive.json does not record executed=true")
        return tuple(violations)
    if not _hash_matches(derive_record.get("output_fasta"), derive_record.get("output_fasta_sha256")):
        violations.append("derive output_fasta missing or hash mismatch (recorded evidence has drifted)")
    # B1-F4: the derived manifest's own CONTENT must still hash-match, not
    # merely still exist at the recorded path — a semantic edit to the
    # manifest file was previously accepted as valid restart evidence.
    if not _hash_matches(derive_record.get("reference_manifest_path"), derive_record.get("reference_manifest_sha256")):
        violations.append(
            "derive reference_manifest_path missing or hash mismatch (recorded evidence has drifted)"
        )
    return tuple(violations)


def _verify_index_evidence_hashes(index_record: dict) -> tuple[str, ...]:
    """B1-C6: re-verify the actual current BWA/minimap2 index files against
    the creation-time index manifest immediately before a restart skip —
    ``index_manifest_is_current`` alone is only a cheap size/mtime hint,
    never a substitute for this full hash check, and a stage previously
    marked complete purely by fingerprint equality could otherwise stay
    "skippable" even after its index files were altered or removed.
    """
    if not index_record.get("executed"):
        return ("index.json does not record executed=true",)
    manifest_path = index_record.get("index_manifest_path")
    if not manifest_path or not Path(manifest_path).is_file():
        return ("index manifest missing (recorded evidence has drifted)",)
    try:
        manifest = json.loads(Path(manifest_path).read_text())
    except (json.JSONDecodeError, OSError):
        return ("index manifest unreadable (recorded evidence has drifted)",)
    bwa_prefix = index_record.get("bwa_index_prefix")
    mm2_index = index_record.get("minimap2_index")
    return (
        *verify_index_files_against_manifest(
            manifest, key="bwa_index", actual_path=Path(bwa_prefix) if bwa_prefix else None
        ),
        *verify_index_files_against_manifest(
            manifest, key="minimap2_index", actual_path=Path(mm2_index) if mm2_index else None
        ),
    )


def _verify_probe_evidence_hashes(probe_record: dict) -> tuple[str, ...]:
    """Same principle as :func:`_verify_align_evidence_hashes`, for ALL SIX
    of the probe stage's retained files (B3A-R4): BWA/minimap2 SAM+stderr
    AND SeqKit BED+stderr -- never only the three stdout-equivalent outputs.
    minimap2's own stderr is load-bearing evidence (parameter-override/
    multipart-index warnings), so a mutated/removed stderr log must be exactly
    as disqualifying for a restart skip as a mutated SAM/BED file. Used by
    the runner's own restart-skip revalidation so a probe generation
    altered/removed on disk since acceptance can never stay silently
    "skippable".
    """
    if not probe_record.get("executed"):
        return ("probe.json does not record executed=true",)
    violations: list[str] = []
    sam_paths = probe_record.get("sam_paths", {})
    stderr_paths = probe_record.get("stderr_paths", {})
    resource_evidence = probe_record.get("resource_evidence", {})
    for tool in ("bwa_mem", "minimap2_splice"):
        evidence = resource_evidence.get(tool) or {}
        if not _hash_matches(sam_paths.get(tool), evidence.get("output_sha256")):
            violations.append(f"probe {tool} SAM output missing or hash mismatch (recorded evidence has drifted)")
        if not _hash_matches(stderr_paths.get(tool), evidence.get("stderr_sha256")):
            violations.append(f"probe {tool} stderr missing or hash mismatch (recorded evidence has drifted)")
    seqkit_evidence = resource_evidence.get("seqkit_locate") or {}
    if not _hash_matches(probe_record.get("bed_path"), seqkit_evidence.get("output_sha256")):
        violations.append("probe seqkit_locate BED output missing or hash mismatch (recorded evidence has drifted)")
    if not _hash_matches(stderr_paths.get("seqkit_locate"), seqkit_evidence.get("stderr_sha256")):
        violations.append("probe seqkit_locate stderr missing or hash mismatch (recorded evidence has drifted)")
    return tuple(violations)


def _verify_report_evidence_hashes(
    build_dir: Path,
    *,
    cfg: FeasibilityConfig,
    output_dir: Path,
    align_record: dict | None = None,
    exact_match_record: dict | None = None,
) -> tuple[str, ...]:
    """B1-C4, corrected by the B1 acceptance correction: verify the accepted
    per-build report against the SELECTED ``report_state.json`` generation
    (via the shared :func:`_load_accepted_report_state` loader) — never the
    human-convenience fixed-path ``report.json``/``report.md``/
    ``mappings.tsv.gz`` mirrors — and additionally cross-check that
    ``provenance.json``'s own recorded ``generated_artifacts`` entry for
    this build identifies that EXACT selected generation's paths and
    hashes. A stale/corrupt/missing mirror is irrelevant to this gate;
    drifted selected evidence, or a ``provenance.json`` that still points at
    an older/different generation, both fail closed.
    """
    report_state, report_state_violations = _load_accepted_report_state(
        build_dir, align_record=align_record, exact_match_record=exact_match_record
    )
    if report_state_violations:
        return tuple(f"selected report_state.json: {v}" for v in report_state_violations)

    provenance_path = output_dir / "provenance.json"
    if not provenance_path.is_file():
        return ("no provenance.json found to verify the accepted report against",)
    try:
        provenance = json.loads(provenance_path.read_text())
    except (json.JSONDecodeError, OSError):
        return ("provenance.json is unreadable",)
    build = build_dir.name
    build_artifacts = (provenance.get("builds", {}).get(build) or {}).get("generated_artifacts") or {}
    violations: list[str] = []
    # B1-F6: also verify the recorded report Markdown, not merely
    # report.json/mappings.tsv.gz — a truncated/edited report.md must not be
    # allowed to slip past cleanup's evidence gate.
    #
    # A2: also cross-check the selected reference-index artifact whenever
    # the report state records one — a non-evaluated report honestly has no
    # reference-index artifact (selected_path is None below), which
    # correctly skips this cross-check rather than manufacturing a
    # violation for evidence that was never expected to exist.
    for key, path_field, sha_field in (
        ("report_json", "report_json_path", "report_json_sha256"),
        ("report_md", "report_md_path", "report_md_sha256"),
        ("mappings_tsv_gz", "mappings_tsv_gz_path", "mappings_tsv_gz_sha256"),
        ("reference_index", "reference_index_path", "reference_index_sha256"),
    ):
        selected_path = report_state.get(path_field)
        selected_sha256 = report_state.get(sha_field)
        if selected_path is None:
            # Not produced by this build's accepted report (an honest
            # not_evaluated/dry-run report has no mappings table, and a
            # report generated without index-diagnostic evidence has no
            # reference-index artifact) — nothing to cross-check.
            continue
        recorded = build_artifacts.get(key)
        if not recorded:
            violations.append(f"provenance.json has no recorded {key} evidence for build {build!r}")
            continue
        if recorded.get("path") != selected_path or recorded.get("sha256") != selected_sha256:
            violations.append(
                f"{key}: provenance.json's recorded evidence does not identify the exact selected "
                f"report_state.json generation (recorded {recorded.get('path')!r}, selected {selected_path!r})"
            )
        elif not _hash_matches(selected_path, selected_sha256):
            violations.append(f"{key} missing or hash mismatch against the selected report_state.json generation")
    return tuple(violations)


def _run_cleanup_index(
    cfg: FeasibilityConfig, *, build: str, indices_dir: Path, output_dir: Path, repo_root: Path, derived_dir: Path
) -> None:
    """``--cleanup-index BUILD`` entry point (B1-C4): resolve exactly what
    evidence already exists on disk for ``build``, verify it goes beyond
    mere JSON booleans (actual mapping/exact-match artifact hashes, the
    report/provenance hashes, and the index manifest's own files), print and
    durably persist the preview *before* anything is deleted, then delegate
    the actual deletion to
    :func:`rbpbench.coordinates.cleanup.execute_index_cleanup`, which
    refuses (deleting nothing) unless index provenance, successful mapping
    outputs, and a passed reconciliation are all already recorded, and pins
    the target to exactly ``repo_root/indices/<build>``.
    """
    index_dir = indices_dir / build
    build_dir = _build_dir(output_dir, build)

    # B1-F6: the pinned repository root must be resolved INDEPENDENTLY (the
    # checked-out Git working-tree top-level), never merely trusted from the
    # CLI-supplied --repo-root — even when --repo-root and --indices-dir's
    # parent agree with EACH OTHER, that proves nothing about whether the
    # agreed-upon path is actually the real repository root. This check is
    # CLI-level only; the low-level cleanup.py functions keep accepting an
    # explicit repo_root parameter unchanged for direct unit testing.
    independent_root = resolve_git_repo_root(repo_root)
    if independent_root is None:
        raise SystemExit(
            f"cleanup refused for build {build!r}: could not independently resolve the checked-out Git "
            f"repository root from {repo_root} (not inside a Git working tree, or git is unavailable); refusing "
            "to trust --repo-root alone"
        )
    if independent_root.resolve() != Path(repo_root).resolve():
        raise SystemExit(
            f"cleanup refused for build {build!r}: --repo-root {repo_root} does not match the independently "
            f"resolved Git repository root {independent_root}; refusing a non-pinned/conflicting root"
        )

    # B1-C4/F6: the actual accepted reference path (as derive.json recorded
    # it), never a hardcoded references/derived/<build>/reference.fna guess
    # — a real Task 001B run's derived-reference root may differ from the
    # documented default via --derived-dir. A valid, executed, hash-verified
    # derive record is now REQUIRED before cleanup proceeds at all (B1-F6):
    # a missing/invalid/altered derive record refuses cleanup outright,
    # rather than silently dropping the accepted-reference guard.
    derive_record_path = derived_dir / build / "derive.json"
    if not derive_record_path.is_file():
        raise SystemExit(
            f"cleanup refused for build {build!r}: no derive.json record found at {derive_record_path}; a valid, "
            "executed, hash-verified derived reference is required before cleanup"
        )
    try:
        derive_record = json.loads(derive_record_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(
            f"cleanup refused for build {build!r}: derive.json at {derive_record_path} is unreadable: {exc}"
        ) from exc
    derive_evidence_violations = _verify_derive_evidence_hashes(derive_record)
    if derive_evidence_violations:
        raise SystemExit(
            f"cleanup refused for build {build!r}: accepted derive evidence is missing or has drifted: "
            f"{list(derive_evidence_violations)}"
        )
    reference_path = Path(derive_record["output_fasta"])

    # B1-C2: the index manifest now lives inside the accepted generation
    # directory named by index.json, never at a fixed index_dir/
    # index_manifest.json path (which a newer, still-in-progress generation
    # attempt could otherwise leave stale or absent).
    index_record_path = index_dir / "index.json"
    index_manifest: dict | None = None
    index_manifest_present = False
    if index_record_path.is_file():
        try:
            index_record_for_cleanup = json.loads(index_record_path.read_text())
        except (json.JSONDecodeError, OSError):
            index_record_for_cleanup = {}
        manifest_path_str = index_record_for_cleanup.get("index_manifest_path")
        if index_record_for_cleanup.get("executed") and manifest_path_str and Path(manifest_path_str).is_file():
            index_manifest_present = True
            try:
                index_manifest = json.loads(Path(manifest_path_str).read_text())
            except (json.JSONDecodeError, OSError):
                index_manifest = None
                index_manifest_present = False
    if index_manifest_present and index_manifest is not None:
        index_file_violations = (
            *verify_index_files_against_manifest(index_manifest, key="bwa_index"),
            *verify_index_files_against_manifest(index_manifest, key="minimap2_index"),
        )
        if index_file_violations:
            index_manifest_present = False

    align_path = build_dir / "align.json"
    exact_path = build_dir / "exact_match.json"
    align_record = json.loads(align_path.read_text()) if align_path.exists() else {}
    exact_match_record = json.loads(exact_path.read_text()) if exact_path.exists() else {}

    # B1-C4: evidence goes beyond the naive `executed: true` booleans — the
    # actual SAM/BED artifacts, and now also the report/provenance hashes,
    # must still exist and hash-match what was recorded at the time.
    #
    # B1 acceptance correction: both the report-artifact hash check and the
    # reconciliation-status read now come from the SELECTED
    # report_state.json generation (via the shared
    # _load_accepted_report_state loader), never the human-convenience
    # fixed-path report.json mirror — a stale/corrupt/absent mirror must
    # never affect this authorization decision.
    mapping_evidence_violations = _verify_mapping_evidence_hashes(align_record, exact_match_record)
    report_evidence_violations = _verify_report_evidence_hashes(
        build_dir, cfg=cfg, output_dir=output_dir, align_record=align_record, exact_match_record=exact_match_record
    )
    evidence_violations = (*mapping_evidence_violations, *report_evidence_violations)
    mapping_outputs_present = not evidence_violations

    selected_report_state, selected_report_state_violations = _load_accepted_report_state(
        build_dir, align_record=align_record, exact_match_record=exact_match_record
    )
    reconciliation_passed = False
    if not selected_report_state_violations:
        try:
            selected_report_payload = json.loads(Path(selected_report_state["report_json_path"]).read_text())
            reconciliation_passed = selected_report_payload.get("reconciliation", {}).get("status") == "passed"
        except (json.JSONDecodeError, OSError):
            reconciliation_passed = False

    # Preview resolved and printed/persisted *before* any deletion decision
    # is acted on (B1-R5/C4: the CLI previously printed only after deletion).
    try:
        preview = plan_index_cleanup(index_dir, repo_root=repo_root, reference=reference_path, output_dir=output_dir)
    except CleanupRefused as exc:
        raise SystemExit(f"cleanup refused for build {build!r}: {exc}") from exc
    print(f"cleanup preview for build {build!r}: {preview.resolved_target} ({len(preview.files)} file(s))")
    for f in preview.files:
        print(f"  - {f}")
    if evidence_violations:
        print(f"  evidence violations: {list(evidence_violations)}")

    receipt_path = build_dir / "cleanup_receipts" / f"{build}_index_cleanup_receipt.json"

    try:
        plan = execute_index_cleanup(
            index_dir,
            index_manifest_present=index_manifest_present,
            mapping_outputs_present=mapping_outputs_present,
            reconciliation_passed=reconciliation_passed,
            repo_root=repo_root,
            reference=reference_path,
            output_dir=output_dir,
            build=build,
            index_manifest=index_manifest,
            receipt_path=receipt_path,
        )
    except CleanupRefused as exc:
        raise SystemExit(f"cleanup refused for build {build!r}: {exc}") from exc
    print(f"removed {plan.resolved_target} ({len(plan.files)} file(s)); receipt at {receipt_path}")


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

    # B1-R6: real mapping must never be requested with an omitted or "all"
    # --stage list — that convenience path could cross index/align/
    # exact_match/report/combined_report review gates in a single
    # invocation, exactly what the checkpointed execution model forbids.
    if args.allow_mapping and (not args.stage or "all" in args.stage):
        raise SystemExit(
            "--allow-mapping requires an explicit --stage allowlist naming only the stage(s) the active "
            "checkpoint allows; --stage all (or an omitted --stage, which defaults to every stage) is "
            "refused so a single invocation cannot cross review gates"
        )

    # B1-C5/F5: an explicit --stage list can still name every build-scoped
    # stage at once (download, derive, index, align, exact_match, report),
    # or combine a B2-only stage (sample/decode/controls) with a
    # build-scoped one, or combine combined_report with mapping
    # authorization — every one of these crosses directly from one
    # checkpoint's preparation into another's full execution (or from B2
    # straight into real mapping) without a review stop in between, despite
    # the omitted/"all" rejection above. The rule: exactly one real
    # build-scoped stage per --allow-mapping invocation, accompanied by
    # nothing but "preflight"; combined_report must never accompany
    # --allow-mapping at all, even alone. Only under --dry-run is a
    # multi-stage plan harmless (nothing ever executes for real), so this
    # check is scoped to real (non-dry-run) authorization only.
    if args.allow_mapping and not args.dry_run:
        requested_stages = tuple(args.stage or ())
        if "combined_report" in requested_stages:
            raise SystemExit(
                "--allow-mapping must never accompany --stage combined_report (B1-F5): combined_report reads "
                "already-produced per-build reports back from disk and must run as its own separate, "
                f"non-mapping invocation after the per-build report is accepted; got --stage {list(requested_stages)!r}"
            )
        build_scoped_requested = sorted(set(s for s in requested_stages if s in BUILD_SCOPED_STAGES))
        disallowed = [
            s for s in requested_stages if s not in BUILD_SCOPED_STAGES and s not in _ALWAYS_ALLOWED_WITH_MAPPING
        ]
        # At most one build-scoped stage (zero is fine: a call may be pure
        # B2 data-prep, e.g. --stage sample alone — allow_mapping is simply
        # unused by it); two or more is exactly the checkpoint-crossing
        # pattern this closes. A build-scoped stage combined with ANY
        # B2-only stage (or anything else besides "preflight") is likewise
        # refused: sample/decode/controls must never cross the B2 gate
        # directly into real mapping in the same invocation.
        if len(build_scoped_requested) > 1 or (build_scoped_requested and disallowed):
            raise SystemExit(
                "--allow-mapping requires an explicit --stage allowlist naming exactly one build-scoped stage "
                "(download/derive/index/align/exact_match/report) per invocation, accompanied by nothing but "
                "'preflight', so a single invocation cannot cross checkpoint review gates; got --stage "
                f"{list(requested_stages)!r} (build-scoped: {build_scoped_requested!r}, other/disallowed: "
                f"{disallowed!r})"
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

    # Fail-closed local-input verification (B1-R6 / B2's actual gate):
    # compare the four frozen dataset/audit/protein/config hashes before the
    # real CSV can be opened for row-by-row reading. --execution-sources is
    # now mandatory for any invocation that will reach the CSV: the runner
    # itself must guarantee this gate, never merely offer it as an optional
    # flag a caller could forget. Fixture-only tests must supply their own
    # fixture spec (never rely on a silent bypass); a real Task 001B
    # invocation passes --execution-sources
    # configs/coordinate_execution_sources.toml. --cleanup-index-only
    # invocations are exempt: they return before the CSV is ever opened.
    if args.cleanup_index is None and args.execution_sources is None:
        raise SystemExit(
            "--execution-sources is required (B1-R6): this invocation would read the dataset CSV, and the "
            "runner no longer permits a silent production bypass. Pass a checked-in spec — a real Task 001B "
            "run uses configs/coordinate_execution_sources.toml; fixture-only tests must supply their own "
            "fixture spec with matching fixture hashes."
        )
    execution_source_spec = None
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
        _run_cleanup_index(
            cfg,
            build=args.cleanup_index,
            indices_dir=args.indices_dir,
            output_dir=args.output_dir,
            repo_root=args.repo_root,
            derived_dir=args.derived_dir,
        )
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
    # B3A-R1/R3: the probe stage's own accepted-B2-checkpoint trust anchor,
    # resolved ONCE here (build-independent -- the accepted B2 biological/
    # control evidence is the same for every build) using the SAME frozen
    # real-mode constants `stage_probe` itself will be called with below, so
    # both the restart fingerprint and the actual probe call agree on
    # exactly what "the accepted B2 evidence" currently means.
    b2_manifest_raw_hash = sha256_file(args.b2_manifest) if args.b2_manifest.is_file() else None
    _b2_evidence_for_fingerprint, _ = load_and_verify_b2_checkpoint(
        args.b2_manifest,
        repo_root=args.repo_root,
        expected_manifest_sha256=B2_ACCEPTED_MANIFEST_SHA256,
        expected_checkpoint=B2_ACCEPTED_CHECKPOINT,
        expected_status=B2_ACCEPTED_STATUS,
        expected_biological_count=B2_REAL_BIOLOGICAL_COUNT,
        expected_control_count=B2_REAL_CONTROL_COUNT,
    )
    # B3A-R3: require a resolved commit and clean tree before any real probe
    # subprocess, resolved once here so the restart fingerprint and the
    # actual pre-execution gate inside `stage_probe` agree.
    _probe_git_commit_now = current_git_commit()
    _probe_git_clean_now = git_is_clean()

    def download_fingerprint(build: str) -> str:
        source_spec = execution_source_spec.reference_sources.get(build) if execution_source_spec else None
        return content_fingerprint(
            "download", base_fingerprint, build, source_spec, args.allow_mapping, args.host_role, args.dry_run
        )

    def derive_fingerprint(build: str) -> str:
        recorded_download_fp = state.get("stage_fingerprints", {}).get(_stage_key("download", build), "never_run")
        return content_fingerprint(
            "derive", recorded_download_fp, bool(download_records.get(build, {}).get("executed")), args.dry_run
        )

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

    def _current_canonical_probe_fingerprint(build: str) -> str:
        """B3A-R3: recompute the SAME ONE stable fingerprint contract
        (:func:`rbpbench.coordinates.probe.probe_fingerprint`) that an
        accepted ``probe.json`` itself records, from the CURRENT
        pre-execution declared inputs -- never a separately-derived skip/
        no-skip fingerprint. Command "semantics" use fixed placeholder
        paths: the fingerprint is only ever sensitive to command FLAGS
        (which never vary per generation), not to a specific attempt's
        candidate-workspace file paths.
        """
        reference_manifest = reference_manifests.get(build) or {}
        index_record = index_records.get(build, {})
        bwa_binary = resolve_binary_provenance("bwa", version=resolve_version(["bwa"]))
        mm2_binary = resolve_binary_provenance("minimap2", version=resolve_version(["minimap2", "--version"]))
        seqkit_binary = resolve_binary_provenance("seqkit", version=resolve_version(["seqkit", "version"]))
        return probe_fingerprint(
            b2_manifest_sha256=b2_manifest_raw_hash,
            b2_sample_sha256=_b2_evidence_for_fingerprint.sample_fasta_sha256 if _b2_evidence_for_fingerprint else None,
            b2_control_sha256=_b2_evidence_for_fingerprint.control_fasta_sha256 if _b2_evidence_for_fingerprint else None,
            reference_sha256=reference_hashes.get(build),
            reference_manifest_content_sha256=manifest_content_sha256(reference_manifest) if reference_manifest else None,
            reference_manifest_raw_sha256=reference_manifest_hashes.get(build),
            index_generation_digest=index_record.get("generation_digest"),
            bwa_binary_sha256=bwa_binary.sha256,
            minimap2_binary_sha256=mm2_binary.sha256,
            seqkit_binary_sha256=seqkit_binary.sha256,
            bwa_binary_version=bwa_binary.version,
            minimap2_binary_version=mm2_binary.version,
            seqkit_binary_version=seqkit_binary.version,
            bwa_command=format_command(bwa_mem_command(Path("REFERENCE"), Path("READS"), threads=1).argv),
            minimap2_command=format_command(minimap2_splice_command(Path("REFERENCE"), Path("READS"), threads=1).argv),
            seqkit_command=format_command(seqkit_locate_command(Path("QUERY"), Path("REFERENCE")).argv),
            git_commit=_probe_git_commit_now,
            git_clean=_probe_git_clean_now,
        )

    def probe_restart_fingerprint(build: str) -> str:
        """B3A-R3: restart-validity fingerprint for the probe stage's CLI
        invocation, recorded into ``state.json``'s generic per-stage
        fingerprint bookkeeping. This IS the same canonical fingerprint
        contract :func:`_current_canonical_probe_fingerprint` computes (B3A-
        R3: "one stable, reproducible fingerprint contract... used both for
        the accepted record and restart revalidation") -- not a separately
        maintained approximation. See also the direct comparison against
        the accepted ``probe.json``'s own recorded ``probe_fingerprint``,
        performed unconditionally at every proposed restart skip below,
        independent of this ``state.json`` bookkeeping.
        """
        return _current_canonical_probe_fingerprint(build)

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
        # received. B1-R1: also includes the *current* reference/manifest
        # hashes directly (not merely chained through align), so a
        # --reference override on an invocation that does not touch align
        # still invalidates a stale exact_match completion rather than
        # silently skipping it as "already completed with matching inputs".
        recorded_align_fp = state.get("stage_fingerprints", {}).get(_stage_key("align", build), "never_run")
        return content_fingerprint(
            "exact_match",
            recorded_align_fp,
            bool(align_records[build].get("executed")),
            reference_hashes.get(build),
            reference_manifest_hashes.get(build),
        )

    def report_fingerprint(build: str) -> str:
        recorded_exact_fp = state.get("stage_fingerprints", {}).get(_stage_key("exact_match", build), "never_run")
        return content_fingerprint(
            "report",
            recorded_exact_fp,
            bool(exact_match_records[build].get("executed")),
            reference_hashes.get(build),
            reference_manifest_hashes.get(build),
        )

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
        # B1 acceptance correction: a forced same-input report rebuild can
        # select a NEW report_state.json generation (a new
        # generation_digest) without changing the report stage's own
        # declared-input fingerprint above (its declared inputs, e.g. the
        # reference, never changed) — include each build's accepted
        # generation_digest directly so that case still invalidates a
        # previously completed combined report, rather than letting it be
        # silently skipped over stale evidence.
        report_generation_digests = {
            build: report_states.get(build, {}).get("generation_digest") for build in builds
        }
        return content_fingerprint(
            "combined_report", tuple(sorted(report_fps.items())), tuple(sorted(report_generation_digests.items()))
        )

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
    download_records: dict[str, dict] = {}
    derive_records: dict[str, dict] = {}
    index_records: dict[str, dict] = {}
    probe_records: dict[str, dict] = {}
    align_records: dict[str, dict] = {}
    exact_match_records: dict[str, dict] = {}
    report_states: dict[str, dict] = {}
    index_dirs: dict[str, Path] = {build: args.indices_dir / build for build in builds}
    sources_dirs: dict[str, Path] = {
        build: args.sources_dir / execution_source_spec.reference_sources[build].assembly
        for build in builds
        if execution_source_spec is not None and build in execution_source_spec.reference_sources
    }
    derived_dirs: dict[str, Path] = {build: args.derived_dir / build for build in builds}
    for build in builds:
        build_dir = _build_dir(args.output_dir, build)
        index_path = index_dirs[build] / "index.json"
        align_path = build_dir / "align.json"
        exact_path = build_dir / "exact_match.json"
        download_path = sources_dirs[build] / "download.json" if build in sources_dirs else None
        derive_path = derived_dirs[build] / "derive.json"
        download_records[build] = (
            json.loads(download_path.read_text()) if download_path is not None and download_path.exists() else {"executed": False}
        )
        derive_records[build] = json.loads(derive_path.read_text()) if derive_path.exists() else {"executed": False}
        index_records[build] = json.loads(index_path.read_text()) if index_path.exists() else {"executed": False}
        probe_path = build_dir / "probe.json"
        probe_records[build] = json.loads(probe_path.read_text()) if probe_path.exists() else {"executed": False}
        align_records[build] = json.loads(align_path.read_text()) if align_path.exists() else {"executed": False}
        exact_match_records[build] = (
            json.loads(exact_path.read_text()) if exact_path.exists() else {"executed": False}
        )
        report_states[build] = _load_report_state(build_dir)

    def _build_budget_excluding(build: str, *, exclude_stage: str) -> BuildOutputBudget:
        """B1-F1: a fresh, freshly-seeded per-build output budget for the
        stage about to run — seeded with every OTHER build-scoped
        writer-stage's CURRENT accepted bytes for this same build, never
        including ``exclude_stage``'s own prior bytes (which this very
        attempt is about to supersede).

        B3A-A3 item 10: also seeds the probe stage's own already-accepted
        bytes (never more than its own 1-GiB PROBE_OUTPUT_ALLOWANCE_GIB
        sub-cap), so probe+B4 accepted build outputs can never together
        exceed the combined 4-GiB BUILD_OUTPUT_ALLOWANCE_GIB.
        """
        align_record = align_records.get(build, {})
        exact_match_record = exact_match_records.get(build, {})
        report_state = report_states.get(build, {})
        probe_record = probe_records.get(build, {})
        already_accepted = 0
        if exclude_stage != "probe" and probe_record.get("executed"):
            already_accepted += probe_record.get("accepted_bytes") or _current_output_bytes(
                (*(probe_record.get("sam_paths") or {}).values(), *(probe_record.get("stderr_paths") or {}).values(), probe_record.get("bed_path"))
            )
        if exclude_stage != "align" and align_record.get("executed"):
            already_accepted += _current_output_bytes(
                (*(align_record.get("sam_paths") or {}).values(), *(align_record.get("stderr_paths") or {}).values())
            )
        if exclude_stage != "exact_match" and exact_match_record.get("executed"):
            already_accepted += _current_output_bytes(
                (exact_match_record.get("bed_path"), exact_match_record.get("stderr_path"))
            )
        if exclude_stage != "report" and report_state.get("executed"):
            already_accepted += _current_output_bytes(
                (
                    report_state.get("mappings_tsv_gz_path"),
                    report_state.get("reference_index_path"),
                    report_state.get("report_json_path"),
                    report_state.get("report_md_path"),
                )
            )
        return start_build_output_budget(already_accepted_bytes=already_accepted, total_allowance_gib=BUILD_OUTPUT_ALLOWANCE_GIB)

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

    def _current_index_binding_violations(build: str) -> tuple[str, ...]:
        """B1-C6: re-verify the CURRENTLY resolved BWA/minimap2 index (the
        default generation, or an explicit override — including one this
        run never itself built) against its own index manifest's binding to
        the current reference/manifest content, immediately before letting
        ``align`` be skipped as "already completed". Without this, an index
        rebuilt (or altered/removed on disk) into a new generation AFTER
        align last accepted it, without align's own restart fingerprint
        ever changing, could leave align marked complete without ever
        re-running the verification path stage_align itself performs when
        it actually executes.
        """
        reference_manifest = reference_manifests.get(build)
        if reference_manifest is None:
            return ()
        current_reference_sha256 = reference_manifest.get("sha256")
        current_manifest_hash = manifest_content_sha256(reference_manifest)
        align_record = align_records.get(build, {})
        recorded_upstream_digest = align_record.get("upstream_index_generation_digest") or {}
        violations: list[str] = []
        for override_path, key in (
            (_resolved_bwa_index_prefix(build), "bwa_index"),
            (_resolved_minimap2_index(build), "minimap2_index"),
        ):
            if override_path is None:
                continue
            manifest_path = override_path.parent / "index_manifest.json"
            if not manifest_path.is_file():
                violations.append(f"{key}: no index manifest found at {manifest_path}")
                continue
            try:
                override_manifest = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                violations.append(f"{key}: index manifest at {manifest_path} is unreadable")
                continue
            violations.extend(
                verify_index_binding(
                    override_manifest,
                    key=key,
                    actual_path=override_path,
                    expected_build=build,
                    expected_reference_sha256=current_reference_sha256,
                    expected_reference_manifest_content_sha256=current_manifest_hash,
                    expected_reference_manifest_raw_sha256=reference_manifest_hashes.get(build),
                )
            )
            # B1-F3: the CURRENT resolved index generation's own
            # content-derived digest must still equal the exact generation
            # digest align.json recorded when it was accepted — even a
            # currently-valid, correctly-bound index must be refused if it
            # is a DIFFERENT generation (by content) than the one align's
            # accepted SAM output actually used. A forced same-input index
            # rerun that reproduces byte-identical content keeps the same
            # digest and is correctly NOT flagged here.
            recorded_digest = recorded_upstream_digest.get(key)
            if recorded_digest is not None:
                current_digest = manifest_content_sha256(override_manifest)
                if current_digest != recorded_digest:
                    violations.append(
                        f"{key}: the current index generation (digest {current_digest}) differs from the exact "
                        f"generation align.json recorded using (digest {recorded_digest}); the index was rebuilt "
                        "or altered since align last accepted it"
                    )
        return tuple(violations)

    # One disk-budget ledger, persisted across separate B1-B6 checkpoint
    # invocations (B1-R4): its baseline/entries are reloaded from
    # <output-dir>/disk_budget_ledger.json when present, so files/bytes
    # retained from an earlier checkpoint's own invocation are never dropped
    # from the accounting merely because this is a new process. Every
    # download/derivation/indexing/mapping subprocess checks the *remaining*
    # budget against it and records its own observed new bytes afterward.
    disk_ledger = (
        start_ledger(args.disk_budget_path, state_path=args.output_dir / "disk_budget_ledger.json")
        if args.allow_mapping and not args.dry_run
        else None
    )
    if disk_ledger is not None:
        # B1-C3: every pinned output/reference/index/source/derived path
        # must resolve onto the same filesystem volume as the ledger's own
        # baseline, unless separately budgeted — merely checking free disk
        # on one volume cannot enforce a ceiling on bytes actually written
        # to another. --sources-dir/--derived-dir are the paths that receive
        # the downloaded and derived references during B3+; omitting them
        # from this check would make a same-volume proof meaningless for
        # exactly the largest artifacts the budget exists to bound.
        volume_check_paths = {
            "output_dir": args.output_dir,
            "indices_dir": args.indices_dir,
            "sources_dir": args.sources_dir,
            "derived_dir": args.derived_dir,
        }
        volume_check_paths.update({f"reference:{b}": p for b, p in references.items()})
        volume_violations = check_pinned_volumes(volume_check_paths, primary=args.disk_budget_path)
        if volume_violations:
            raise SystemExit(f"disk-budget volume check failed: {list(volume_violations)}")

    for stage in stages:
        if stage in BUILD_SCOPED_STAGES:
            for build in builds:
                key = _stage_key(stage, build)
                if stage == "download":
                    fingerprint = download_fingerprint(build)
                elif stage == "derive":
                    fingerprint = derive_fingerprint(build)
                elif stage == "index":
                    fingerprint = index_fingerprint(build)
                elif stage == "probe":
                    fingerprint = probe_restart_fingerprint(build)
                elif stage == "align":
                    fingerprint = align_fingerprint(build)
                elif stage == "exact_match":
                    fingerprint = exact_match_fingerprint(build)
                else:  # "report"
                    fingerprint = report_fingerprint(build)

                # B1-C1/C6: a matching fingerprint alone is never sufficient
                # to skip a build-scoped stage — the actual accepted
                # artifacts (and, for align, the index it depends on) must
                # still hash-verify against what was recorded, so an
                # altered/removed/superseded-without-refingerprinting file
                # can never stay silently "skippable".
                if not args.force and _stage_is_valid(state, key, fingerprint):
                    if stage == "download":
                        revalidation_violations = _verify_download_evidence_hashes(download_records.get(build, {}))
                    elif stage == "derive":
                        revalidation_violations = _verify_derive_evidence_hashes(derive_records.get(build, {}))
                    elif stage == "index":
                        revalidation_violations = _verify_index_evidence_hashes(index_records.get(build, {}))
                    elif stage == "probe":
                        # B3A-A3/R3: re-verify the probe's own retained
                        # six-file evidence AND that the accepted index
                        # generation it was bound to is still current, before
                        # letting a restart skip it. B3A-R3: additionally
                        # recompute the SAME canonical fingerprint contract
                        # and compare it DIRECTLY against the exact
                        # fingerprint the accepted probe.json itself
                        # recorded -- independent of (never merely trusting)
                        # state.json's own separate stage_fingerprints
                        # bookkeeping above.
                        probe_record_current = probe_records.get(build, {})
                        recomputed_fp = _current_canonical_probe_fingerprint(build)
                        accepted_fp = probe_record_current.get("probe_fingerprint")
                        if accepted_fp is not None and recomputed_fp != accepted_fp:
                            revalidation_violations = (
                                f"recomputed probe_fingerprint {recomputed_fp} does not match the accepted "
                                f"probe.json's recorded fingerprint {accepted_fp} (accepted B2/reference/index/"
                                "binary/command/implementation-commit evidence has changed since acceptance)",
                            )
                        else:
                            revalidation_violations = ()
                        if not revalidation_violations:
                            revalidation_violations = _verify_probe_evidence_hashes(probe_record_current)
                        if not revalidation_violations:
                            revalidation_violations = _verify_index_record_for_probe(
                                index_records.get(build, {}), build=build,
                                expected_reference_sha256=probe_record_current.get("reference_sha256"),
                                expected_reference_manifest_content_sha256=probe_record_current.get("reference_manifest_content_sha256"),
                                expected_reference_manifest_raw_sha256=probe_record_current.get("reference_manifest_raw_sha256"),
                            )
                    elif stage == "align":
                        revalidation_violations = (
                            *_verify_align_evidence_hashes(align_records.get(build, {})),
                            *_current_index_binding_violations(build),
                        )
                    elif stage == "exact_match":
                        revalidation_violations = (
                            *_verify_exact_match_evidence_hashes(exact_match_records.get(build, {})),
                            *_upstream_generation_digest_violation(
                                exact_match_records.get(build, {}),
                                upstream_key="upstream_align_generation_digest",
                                current_digest=align_records.get(build, {}).get("generation_digest"),
                            ),
                        )
                    else:  # "report"
                        # B1 acceptance correction: the ONE shared loader
                        # also used by combined_report/_write_provenance/
                        # cleanup, rather than reimplementing this same
                        # hash-plus-upstream-digest check a fourth time.
                        _, revalidation_violations = _load_accepted_report_state(
                            _build_dir(args.output_dir, build),
                            align_record=align_records.get(build, {}),
                            exact_match_record=exact_match_records.get(build, {}),
                        )

                    if not revalidation_violations:
                        print(f"skip {key} (already completed with matching inputs; pass --force to redo)")
                        continue
                    print(
                        f"{key}: previously accepted evidence has drifted since it last completed; re-running: "
                        f"{list(revalidation_violations)}"
                    )
                if key in state["completed_stages"] and state.get("stage_fingerprints", {}).get(key) != fingerprint:
                    print(f"{key}: declared inputs/config/reference/authorization changed since it last completed; re-running")

                build_dir = _build_dir(args.output_dir, build)
                if stage == "download":
                    source_spec = execution_source_spec.reference_sources.get(build) if execution_source_spec else None
                    if source_spec is None:
                        raise SystemExit(
                            f"download stage requires --execution-sources to supply a reference source spec for "
                            f"build {build!r}"
                        )
                    download_record = stage_download(
                        build=build,
                        source_spec=source_spec,
                        sources_dir=sources_dirs[build],
                        allow_mapping=args.allow_mapping,
                        host_role=args.host_role,
                        dry_run=args.dry_run,
                        disk_ledger=disk_ledger,
                        transport=urllib_transport,
                    )
                    download_records[build] = download_record
                    executed = bool(download_record.get("executed"))
                    state["mapping_executed"].setdefault(build, {})["download"] = executed
                    retryable = args.allow_mapping and not executed
                elif stage == "derive":
                    source_spec = execution_source_spec.reference_sources.get(build) if execution_source_spec else None
                    if source_spec is None:
                        raise SystemExit(
                            f"derive stage requires --execution-sources to supply a reference source spec for "
                            f"build {build!r}"
                        )
                    derive_record = stage_derive(
                        build=build,
                        source_spec=source_spec,
                        derived_dir=derived_dirs[build],
                        allow_mapping=args.allow_mapping,
                        host_role=args.host_role,
                        download_record=download_records.get(build, {"executed": False}),
                        dry_run=args.dry_run,
                        disk_ledger=disk_ledger,
                    )
                    derive_records[build] = derive_record
                    executed = bool(derive_record.get("executed"))
                    state["mapping_executed"].setdefault(build, {})["derive"] = executed
                    retryable = args.allow_mapping and not executed
                elif stage == "index":
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
                        reference_manifest_raw_sha256=reference_manifest_hashes.get(build),
                        downstream_align_record=align_records.get(build),
                    )
                    index_records[build] = index_record
                    executed = bool(index_record.get("executed"))
                    state["mapping_executed"].setdefault(build, {})["index"] = executed
                    retryable = args.allow_mapping and not executed
                elif stage == "probe":
                    probe_record = stage_probe(
                        cfg,
                        build=build,
                        build_output_dir=build_dir,
                        allow_mapping=args.allow_mapping,
                        host_role=args.host_role,
                        reference=references.get(build),
                        reference_manifest=reference_manifests.get(build),
                        reference_manifest_raw_sha256=reference_manifest_hashes.get(build),
                        index_record=index_records.get(build, {"executed": False}),
                        b2_manifest_path=args.b2_manifest,
                        repo_root=args.repo_root,
                        b2_manifest_expected_sha256=B2_ACCEPTED_MANIFEST_SHA256,
                        b2_manifest_expected_checkpoint=B2_ACCEPTED_CHECKPOINT,
                        b2_manifest_expected_status=B2_ACCEPTED_STATUS,
                        b2_expected_biological_count=B2_REAL_BIOLOGICAL_COUNT,
                        b2_expected_control_count=B2_REAL_CONTROL_COUNT,
                        dry_run=args.dry_run,
                        disk_ledger=disk_ledger,
                        build_budget=_build_budget_excluding(build, exclude_stage="probe"),
                    )
                    probe_records[build] = probe_record
                    executed = bool(probe_record.get("executed"))
                    state["mapping_executed"].setdefault(build, {})["probe"] = executed
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
                        reference_manifest_raw_sha256=reference_manifest_hashes.get(build),
                        build_budget=_build_budget_excluding(build, exclude_stage="align"),
                        downstream_exact_match_record=exact_match_records.get(build),
                        downstream_report_state=report_states.get(build),
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
                        reference_manifest_raw_sha256=reference_manifest_hashes.get(build),
                        build_budget=_build_budget_excluding(build, exclude_stage="exact_match"),
                        downstream_report_state=report_states.get(build),
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
                        reference_manifest=reference_manifests.get(build),
                        reference_manifest_raw_sha256=reference_manifest_hashes.get(build),
                        build_budget=_build_budget_excluding(build, exclude_stage="report"),
                    )
                    report_states[build] = _load_report_state(build_dir)
                    retryable = False
                    # B1 required item 9 / B1-R8: a failed reconciliation
                    # must make the runner exit nonzero, checked directly
                    # against reconciliation.status rather than trusting that
                    # a process reaching this point implies success. This
                    # stage key must NOT be marked complete on failure: doing
                    # so would let a later, non-forced invocation with the
                    # same fingerprint silently skip the still-failed report
                    # as "already completed with matching inputs".
                    if build_report_payload["reconciliation"]["status"] == "failed":
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
            # B1 acceptance correction: a matching fingerprint alone is
            # never sufficient to skip combined_report either — each
            # build's SELECTED report_state.json generation must still
            # hash-verify (never merely a fixed-path mirror), the same
            # revalidate-before-skip guarantee every build-scoped stage
            # above already gets.
            #
            # Second acceptance correction (A1): also re-validate each
            # build's report_state.json against the CURRENT align/
            # exact_match records (the shared _load_accepted_report_state
            # loader, not merely _verify_report_state_evidence_hashes) so a
            # forced align/exact-match rerun that produced a new upstream
            # generation WITHOUT re-triggering that build's report stage
            # (its own declared-input fingerprint never changed) still
            # invalidates a previously completed combined_report skip,
            # rather than silently combining a report that is now stale
            # with respect to its declared upstream inputs.
            combined_report_revalidation_violations: tuple[str, ...] = ()
            if stage == "combined_report":
                combined_report_revalidation_violations = tuple(
                    f"build {build!r} report: {violation}"
                    for build in builds
                    for violation in _load_accepted_report_state(
                        _build_dir(args.output_dir, build),
                        align_record=align_records.get(build, {}),
                        exact_match_record=exact_match_records.get(build, {}),
                    )[1]
                )
            if not combined_report_revalidation_violations:
                print(f"skip {stage} (already completed with matching inputs; pass --force to redo)")
                continue
            print(
                f"{stage}: previously accepted evidence has drifted since it last completed; re-running: "
                f"{list(combined_report_revalidation_violations)}"
            )
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
                align_records=align_records,
                exact_match_records=exact_match_records,
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
        download_records=download_records,
        derive_records=derive_records,
        probe_records=probe_records,
    )

    if args.dry_run:
        _write_json(
            args.output_dir / Path(cfg.outputs.dry_run_json).name,
            {"stages_run": list(stages), "completed_stages": state["completed_stages"]},
        )


if __name__ == "__main__":
    main()
