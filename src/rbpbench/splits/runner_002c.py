"""Task 002C restart-safe runner: ``assign``, ``legacy_diagnostic``,
``exact_audit``, ``audit_probe``, ``audit_search``, and ``finalize`` stages.

Checkpoint 002C-1 (``docs/handoffs/002c1_partition_orchestration_claude_handoff.md``,
``docs/reviews/002c1_partition_orchestration_correction_review.md``)
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

Correction pass (docs/reviews/002c1_partition_orchestration_correction_review.md,
C1-C7): ``assign`` now binds and revalidates all FIVE frozen inputs (CSV,
dataset-audit JSON, proteins TSV, accepted Task 002B component membership,
and accepted Task 002B component report); the selection pointer stores only
paths/hashes/counts/digests, never the large sample-to-component/
component-to-partition maps themselves; every stage's FASTA reads go
through a strict validating reader; every downstream fingerprint binds its
upstream GENERATION digest (not merely its stage fingerprint), so a
force-rebuilt-but-byte-identical upstream generation still invalidates
downstream currency; ``finalize`` additionally requires all three width
probes and independently re-derives its own summary from the final
membership plus a fresh CSV stream before promotion.

Final acceptance correction (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md,
F1-F4): ``audit_probe`` is now WIDTH-scoped only -- exactly one
deterministic bounded resource probe per protected width (``audit_probe_500``/
``audit_probe_251``/``audit_probe_101``), never direction-scoped, and every
one of the six full ``audit_search`` directions at a width binds that same
current width probe generation; ``finalize`` requires exactly three probes
plus all 18 directed searches (F1). Every stage that reads a decode FASTA
verifies it against the already committed, sanitized
``manifests/sequence_decode_002b2.json`` decode-evidence manifest (pinned by
hash in the config's ``[decode_002b2]`` table) -- a syntactically valid but
non-accepted FASTA fails closed (F2). The live RAM/disk gates are rechecked
immediately before EVERY individual MMseqs2 subprocess launch inside a
directed audit, not merely once before the whole four-command attempt (F3).
A shared current-assignment validator re-hashes and re-fingerprints the
accepted ``assign`` record's five frozen inputs before every downstream real
stage/finalization, and the six legacy-diagnostic edge files are bound to
explicit, pinned ``(width, evidence kind, size, hash)`` provenance with
every endpoint reconciled against the closed canonical sample universe
(F4, :mod:`rbpbench.splits.legacy_edges`).
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import shutil

from rbpbench.coordinates.decode import fasta_record
from rbpbench.coordinates.hashing import content_fingerprint, label_blind_rank
from rbpbench.coordinates.provenance import peak_rss_kib_of_children
from rbpbench.data.audit import sha256_file
from rbpbench.splits import assignment
from rbpbench.splits import audit as splits_audit
from rbpbench.splits import commands as splits_commands
from rbpbench.splits import exact_audit as splits_exact_audit
from rbpbench.splits import guarded_exec
from rbpbench.splits import ingestion
from rbpbench.splits import legacy_diagnostic as splits_legacy_diagnostic
from rbpbench.splits import legacy_edges as splits_legacy_edges
from rbpbench.splits import mmseqs_audit
from rbpbench.splits import output as splits_output
from rbpbench.splits import restart
from rbpbench.splits.assignment import TARGET_FRACTIONS
from rbpbench.splits.config_002c import SplitsConfig002C, load_config_002c

STAGES: tuple[str, ...] = (
    "assign", "legacy_diagnostic", "exact_audit", "audit_probe", "audit_search", "finalize",
)
WIDTH_SCOPED_STAGES: tuple[str, ...] = ("exact_audit", "audit_probe", "audit_search")
# F1 (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md):
# ``audit_probe`` is WIDTH-scoped only, never direction-scoped -- exactly
# three probes (one per protected width), not 18.
DIRECTION_SCOPED_STAGES: tuple[str, ...] = ("audit_search",)
MMSEQS_STAGES: tuple[str, ...] = ("audit_probe", "audit_search")
DECODE_FASTA_FILENAME_TEMPLATE = "sequence_partitions_width_{width}.fasta"

DEFAULT_CONFIG_PATH = Path("configs/splits/sequence_partitions_002c_v1.toml")
DEFAULT_OUTPUT_DIR = Path("artifacts/splits/sequence_partitions_002c_v1")

_ACGT = frozenset("ACGT")


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
    """A declared real input (CSV/component membership/component report/
    dataset-audit JSON/proteins TSV/decode FASTA) failed exact hash/size
    revalidation against the current config, or a strict FASTA read failed
    universe/width/alphabet validation.
    """


class FinalizationRefusedError(RuntimeError):
    """``finalize`` refused because at least one required record is
    missing, stale, failed, or one-direction-only, or its own independent
    recomputation disagrees with the accepted evidence. Never promotes a
    partial or failing result.
    """


class StaleAssignmentInputError(InputValidationError):
    """The currently-accepted ``assign`` record's five frozen live inputs
    (CSV, component membership, component report, dataset-audit JSON,
    proteins TSV) no longer match the config's frozen expectations, the
    hashes recorded in the ``assign`` record itself, or its own stage
    fingerprint no longer reproduces from those recorded hashes
    (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md,
    F4). Checked before every downstream real stage/finalization -- never
    ``--dry-run`` -- so editing the component report, membership,
    dataset-audit JSON, or proteins table after ``assign`` accepted can
    never leave a downstream stage or finalization apparently current.
    """


class DecodeManifestError(InputValidationError):
    """The pinned, already committed, sanitized Task 002B-2 decode-evidence
    manifest failed hash verification, was missing a required field, or a
    per-width decode FASTA's current byte size/SHA-256 disagreed with its
    accepted entry (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md,
    F2): a syntactically valid but non-accepted FASTA fails closed here.
    """


# --------------------------------------------------------------------------
# Small local helpers (path resolution, strict FASTA I/O, deterministic
# label-blind subsetting, generic frozen-file hash verification).
# --------------------------------------------------------------------------


def _resolve(base: Path, maybe_relative: str) -> Path:
    candidate = Path(maybe_relative)
    return candidate if candidate.is_absolute() else Path(base) / candidate


def _repo_root(config_path: Path, explicit: Path | None) -> Path:
    """The deterministic base every declared-relative production path
    (``dataset.audit_json_path``, ``dataset.proteins_tsv_path``) resolves
    against (docs/reviews/002c1_partition_orchestration_correction_review.md,
    C1): an explicit ``--repo-root`` always wins; otherwise derived from the
    CONFIG FILE'S OWN resolved location (two levels above
    ``configs/splits/<file>.toml``), never from the process's current
    working directory -- mirrors ``rbpbench.splits.runner._repo_root``.
    """
    if explicit is not None:
        return Path(explicit).resolve()
    return Path(config_path).resolve().parent.parent.parent


def _verify_frozen_file(path: Path, *, expected_sha256: str, label: str) -> str:
    """Hash-only frozen-input verification (mirrors Task 002B's own
    ``stage_preflight`` treatment of ``audit_json``/``proteins_tsv``: a
    small manifest/config file is bound by SHA-256 alone, no separate
    byte-size check).
    """
    path = Path(path)
    if not path.is_file():
        raise InputValidationError(f"{label} not found at {path}")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise InputValidationError(f"{label} at {path} hashes to {actual}, expected exactly {expected_sha256}")
    return actual


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


@dataclass(frozen=True)
class DecodeFastaEvidence:
    path: str
    byte_size: int
    sha256: str


_DECODE_FASTA_PATTERN = re.compile(r"sequence_partitions_width_(\d+)\.fasta$")
_DECODE_DUPLICATE_EDGES_PATTERN = re.compile(r"duplicate_edges_(\d+)\.json$")


def _load_decode_manifest(
    manifest_path: Path, *, expected_sha256: str
) -> tuple[str, dict[int, DecodeFastaEvidence], dict[int, DecodeFastaEvidence]]:
    """Hash-verifies the pinned, already committed, sanitized Task 002B-2
    decode-evidence manifest (``manifests/sequence_decode_002b2.json``) and
    extracts its generation digest plus, from its own ``retained_artifacts``
    inventory, each protected width's accepted
    ``sequence_partitions_width_<width>.fasta`` AND ``duplicate_edges_<width>.json``
    byte size/SHA-256 (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md,
    F2, F4) -- never a second, independently hard-coded copy of those values
    in the 002C config.

    Returns ``(decode_generation_digest, fasta_evidence_by_width,
    duplicate_edges_evidence_by_width)``.
    """
    try:
        _verify_frozen_file(manifest_path, expected_sha256=expected_sha256, label="decode evidence manifest")
    except InputValidationError as exc:
        raise DecodeManifestError(str(exc)) from exc
    data = json.loads(Path(manifest_path).read_text())
    generation_digest = data.get("decode_generation_digest")
    if not generation_digest:
        raise DecodeManifestError(f"{manifest_path}: missing decode_generation_digest")

    fasta_evidence: dict[int, DecodeFastaEvidence] = {}
    duplicate_edges_evidence: dict[int, DecodeFastaEvidence] = {}
    for entry in data.get("retained_artifacts", []):
        entry_path = entry.get("path", "")
        fasta_match = _DECODE_FASTA_PATTERN.search(entry_path)
        if fasta_match is not None:
            width = int(fasta_match.group(1))
            fasta_evidence[width] = DecodeFastaEvidence(
                path=entry_path, byte_size=entry["byte_size"], sha256=entry["sha256"]
            )
            continue
        edges_match = _DECODE_DUPLICATE_EDGES_PATTERN.search(entry_path)
        if edges_match is not None:
            width = int(edges_match.group(1))
            duplicate_edges_evidence[width] = DecodeFastaEvidence(
                path=entry_path, byte_size=entry["byte_size"], sha256=entry["sha256"]
            )
    return generation_digest, fasta_evidence, duplicate_edges_evidence


def _verify_decode_fasta(fasta_path: Path, *, width: int, fasta_evidence: dict[int, DecodeFastaEvidence]) -> str:
    """F2: verifies the current decode FASTA at ``fasta_path`` against its
    accepted Task 002B-2 decode-evidence-manifest entry for ``width`` -- a
    syntactically valid but non-accepted (content-different) FASTA fails
    closed here, never merely recording its new hash.
    """
    entry = fasta_evidence.get(width)
    if entry is None:
        raise DecodeManifestError(f"decode evidence manifest has no accepted entry for width {width}")
    actual_size = Path(fasta_path).stat().st_size
    if actual_size != entry.byte_size:
        raise DecodeManifestError(
            f"{fasta_path} is {actual_size} bytes, expected exactly {entry.byte_size} per the accepted decode "
            f"evidence for width {width}"
        )
    actual_sha256 = sha256_file(Path(fasta_path))
    if actual_sha256 != entry.sha256:
        raise DecodeManifestError(
            f"{fasta_path} hashes to {actual_sha256}, expected exactly {entry.sha256} per the accepted decode "
            f"evidence for width {width} (syntactically valid but not the accepted content)"
        )
    return actual_sha256


def _verify_current_assignment(*, config: SplitsConfig002C, assign_record: dict) -> None:
    """F4: the shared current-assignment validator, called before every
    downstream real stage/finalization (never ``--dry-run``). Re-hashes all
    five frozen inputs recorded by the accepted ``assign`` record, compares
    each against BOTH the config's frozen expectation and the hash the
    ``assign`` record itself recorded, and recomputes the ``assign`` stage
    fingerprint from those recorded hashes -- so editing the component
    report, component membership, dataset-audit JSON, or protein table (or
    tampering the recorded hashes themselves) after ``assign`` accepted can
    never leave a downstream stage or ``finalize`` apparently current.
    """
    problems: list[str] = []

    csv_path = Path(assign_record["csv_path"])
    if not csv_path.is_file():
        problems.append(f"assign's CSV no longer exists at {csv_path}")
    else:
        actual_size = csv_path.stat().st_size
        if actual_size != config.dataset.csv_byte_size:
            problems.append(
                f"CSV at {csv_path} is now {actual_size} bytes, expected exactly {config.dataset.csv_byte_size}"
            )
        actual_sha256 = sha256_file(csv_path)
        if actual_sha256 != config.dataset.csv_sha256:
            problems.append(
                f"CSV at {csv_path} now hashes to {actual_sha256}, expected the frozen config hash "
                f"{config.dataset.csv_sha256}"
            )
        if actual_sha256 != assign_record["csv_sha256"]:
            problems.append(
                f"CSV at {csv_path} now hashes to {actual_sha256}, but the accepted assign record recorded "
                f"{assign_record['csv_sha256']}"
            )

    for path_key, record_hash_key, expected_sha256 in (
        ("component_membership_path", "component_membership_sha256", config.components_002b.membership_sha256),
        ("component_report_path", "component_report_sha256", config.components_002b.report_sha256),
        ("audit_json_path", "audit_json_sha256", config.dataset.audit_json_sha256),
        ("proteins_tsv_path", "proteins_tsv_sha256", config.dataset.proteins_tsv_sha256),
    ):
        path = Path(assign_record[path_key])
        if not path.is_file():
            problems.append(f"assign's {path_key} no longer exists at {path}")
            continue
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            problems.append(
                f"{path_key} at {path} now hashes to {actual_sha256}, expected the frozen config hash "
                f"{expected_sha256}"
            )
        if actual_sha256 != assign_record[record_hash_key]:
            problems.append(
                f"{path_key} at {path} now hashes to {actual_sha256}, but the accepted assign record recorded "
                f"{assign_record[record_hash_key]}"
            )

    if problems:
        raise StaleAssignmentInputError("current-assignment validation failed: " + "; ".join(problems))

    recomputed_fp = assign_fingerprint(
        config=config,
        csv_sha256=assign_record["csv_sha256"],
        membership_sha256=assign_record["component_membership_sha256"],
        component_report_sha256=assign_record["component_report_sha256"],
        audit_json_sha256=assign_record["audit_json_sha256"],
        proteins_tsv_sha256=assign_record["proteins_tsv_sha256"],
    )
    if recomputed_fp != assign_record["stage_fingerprint"]:
        raise StaleAssignmentInputError(
            f"assign record's stage_fingerprint {assign_record['stage_fingerprint']!r} does not reproduce from "
            f"its own recorded input hashes under the current config (recomputed {recomputed_fp!r})"
        )


class FastaValidationError(InputValidationError):
    """A strict FASTA read failed duplicate-header, width, alphabet, or
    universe validation (docs/reviews/002c1_partition_orchestration_correction_review.md,
    C3).
    """


def _read_fasta_strict(path: Path, *, expected_width: int, expected_ids: set[str]) -> dict[str, str]:
    """Strict, streaming FASTA reader (C3): rejects a duplicate header
    (never silently overwrites it), an empty or non-ACGT sequence, and any
    sequence whose length is not exactly ``expected_width``; then
    reconciles the complete read ID set against ``expected_ids`` (missing
    OR foreign is a hard failure) before returning.
    """
    sequences: dict[str, str] = {}
    current_id: str | None = None
    chunks: list[str] = []

    def _finish() -> None:
        nonlocal current_id, chunks
        if current_id is None:
            return
        if current_id in sequences:
            raise FastaValidationError(f"{path}: duplicate FASTA header {current_id!r}")
        seq = "".join(chunks)
        if not seq:
            raise FastaValidationError(f"{path}: {current_id!r} has an empty sequence")
        if len(seq) != expected_width:
            raise FastaValidationError(
                f"{path}: {current_id!r} has length {len(seq)}, expected exactly {expected_width}"
            )
        bad = sorted(set(seq) - _ACGT)
        if bad:
            raise FastaValidationError(f"{path}: {current_id!r} contains non-A/C/G/T character(s): {bad}")
        sequences[current_id] = seq

    with Path(path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if line.startswith(">"):
                _finish()
                current_id = line[1:].strip()
                chunks = []
            else:
                chunks.append(line)
        _finish()

    actual_ids = set(sequences)
    missing = expected_ids - actual_ids
    foreign = actual_ids - expected_ids
    if missing or foreign:
        problems = []
        if missing:
            problems.append(f"missing {len(missing)} expected ID(s), e.g. {sorted(missing)[:5]}")
        if foreign:
            problems.append(f"contains {len(foreign)} foreign ID(s), e.g. {sorted(foreign)[:5]}")
        raise FastaValidationError(f"{path}: FASTA universe reconciliation failed: " + "; ".join(problems))
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


def _deterministic_probe_split(
    sequences: dict[str, str], sample_size: int, seed: int
) -> tuple[dict[str, str], dict[str, str]]:
    """F1 (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md):
    ``audit_probe`` uses ONE deterministic, documented query/target sample
    covering the intended command/resource shape -- never a
    partition-directed pair. Ranks the WHOLE width universe by the same
    label-blind deterministic rank already used for subsetting, then splits
    the first ``2 * sample_size`` ranked IDs into two disjoint halves (query,
    then target); when the universe is too small for two full
    ``sample_size`` halves, falls back to an even split of whatever is
    available, so both sides are always non-empty for a non-trivial universe.
    """
    ranked = sorted(sequences, key=lambda sid: (label_blind_rank(seed, sid), sid))
    query_ids = ranked[:sample_size]
    target_ids = ranked[sample_size : sample_size * 2]
    if not target_ids:
        half = len(ranked) // 2
        query_ids, target_ids = ranked[:half], ranked[half:]
    return (
        {sid: sequences[sid] for sid in query_ids},
        {sid: sequences[sid] for sid in target_ids},
    )


def _read_assign_membership_rows(assign_record: dict) -> list[tuple[str, str, str]]:
    """Streams the ``assign`` generation's own three-column membership
    artifact fresh from disk (docs/reviews/002c1_partition_orchestration_correction_review.md,
    C2: "keeping large maps in inventoried generation artifacts and storing
    only paths/hashes/counts/digests in the selected record"). The selected
    ``assign`` record itself never embeds the 361,180-entry
    sample-to-component or 173,465-entry component-to-partition maps --
    every downstream stage streams/revalidates this artifact instead.
    """
    return splits_output.read_membership_gzip(Path(assign_record["membership_path"]))


def _sample_to_partition(assign_record: dict) -> dict[str, str]:
    return {sample_id: partition for sample_id, _component_id, partition in _read_assign_membership_rows(assign_record)}


# --------------------------------------------------------------------------
# assign
# --------------------------------------------------------------------------


def assign_fingerprint(
    *,
    config: SplitsConfig002C,
    csv_sha256: str,
    membership_sha256: str,
    component_report_sha256: str,
    audit_json_sha256: str,
    proteins_tsv_sha256: str,
) -> str:
    """Binds the config hash plus ALL FIVE frozen inputs' current content
    hashes (docs/reviews/002c1_partition_orchestration_correction_review.md,
    C1: "the configured ``dataset_audit.json``, ``proteins.tsv``, and
    accepted Task 002B component-report hashes are never checked").
    """
    return content_fingerprint(
        "assign", config.content_hash, csv_sha256, membership_sha256, component_report_sha256,
        audit_json_sha256, proteins_tsv_sha256,
    )


def stage_assign(
    *,
    config: SplitsConfig002C,
    csv_path: Path,
    membership_path: Path,
    component_report_path: Path,
    audit_json_path: Path,
    proteins_tsv_path: Path,
    output_dir: Path,
    dry_run: bool = False,
) -> dict:
    if dry_run:
        return {
            "dry_run": True, "stage": "assign",
            "would_read": {
                "csv": str(csv_path), "component_membership": str(membership_path),
                "component_report": str(component_report_path), "audit_json": str(audit_json_path),
                "proteins_tsv": str(proteins_tsv_path),
            },
        }

    # C1: bind and revalidate ALL FIVE frozen inputs before any assignment
    # -- never only the CSV and the raw two-column membership.
    audit_json_sha256 = _verify_frozen_file(audit_json_path, expected_sha256=config.dataset.audit_json_sha256, label="dataset_audit.json")
    proteins_tsv_sha256 = _verify_frozen_file(proteins_tsv_path, expected_sha256=config.dataset.proteins_tsv_sha256, label="proteins.tsv")
    component_report_sha256 = ingestion.verify_component_report_file(
        component_report_path,
        expected_sha256=config.components_002b.report_sha256,
        expected_byte_size=config.components_002b.report_byte_size,
    )
    component_report = ingestion.load_component_report(
        component_report_path,
        expected_row_count=config.dataset.expected_row_count,
        expected_component_count=config.components_002b.expected_component_count,
    )
    membership_sha256 = ingestion.verify_component_membership_file(
        membership_path,
        expected_sha256=config.components_002b.membership_sha256,
        expected_byte_size=config.components_002b.membership_byte_size,
    )
    # C1: the membership-derived component-size map is compared EXACTLY
    # (byte-for-byte) against the accepted Task 002B report's own map -- a
    # membership with the right row/component counts but the wrong size
    # distribution can no longer pass.
    universe = ingestion.load_component_membership(
        membership_path,
        expected_sample_count=config.dataset.expected_row_count,
        expected_component_count=config.components_002b.expected_component_count,
        expected_component_sizes=component_report.component_sizes,
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
        max_repair_proposals=config.assignment.max_repair_proposals,
        row_fraction_repair_limit_pct=config.assignment.row_fraction_repair_limit_pct,
        row_dimension_weight=config.assignment.row_dimension_weight,
        protein_class_dimension_weight=config.assignment.protein_class_dimension_weight,
        balance_deviation_flag_pct=config.assignment.balance_deviation_flag_pct,
        # C2: the frozen protein/class universe (1..122 in production), not
        # merely the protein IDs actually observed in this CSV -- a protein
        # with zero total known labels anywhere must surface as an explicit
        # AssignmentInfeasibleError (evaluation_floor > 0) rather than
        # silently vanishing from the floor check.
        protein_ids=list(range(config.dataset.protein_id_min, config.dataset.protein_id_max + 1)),
    )

    total_rows = sum(assignment_result.partition_row_counts.values())
    balance = splits_audit.balance_report(
        assignment_result.partition_row_counts, TARGET_FRACTIONS, total_rows,
        flag_threshold_pct=config.assignment.balance_deviation_flag_pct,
    )
    per_protein_balance = splits_audit.per_protein_balance_report(
        assignment_result.partition_label_counts, TARGET_FRACTIONS,
        flag_threshold_pct=config.assignment.balance_deviation_flag_pct,
    )
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
        # C2: the large sample-to-component / component-to-partition maps
        # live ONLY in this immutable generation's membership artifact, never
        # duplicated a second time inline in the selected record below.
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
        input_hashes = {
            "csv_sha256": csv_sha256,
            "component_membership_sha256": membership_sha256,
            "component_report_sha256": component_report_sha256,
            "audit_json_sha256": audit_json_sha256,
            "proteins_tsv_sha256": proteins_tsv_sha256,
        }
        manifest = {
            "schema_version": 2,
            "checkpoint": "002C-1-assign",
            "config_hash": config.content_hash,
            "input_hashes": input_hashes,
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

        # C2: the sample-to-component / component-to-partition maps are also
        # inventoried here (as the generation's own membership artifact),
        # never duplicated inline into the selected record -- downstream
        # stages must stream/revalidate this artifact instead.
        artifacts = restart.inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            "assign_generation", str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = assign_fingerprint(
            config=config, csv_sha256=csv_sha256, membership_sha256=membership_sha256,
            component_report_sha256=component_report_sha256, audit_json_sha256=audit_json_sha256,
            proteins_tsv_sha256=proteins_tsv_sha256,
        )
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
            "component_report_path": str(component_report_path),
            "component_report_sha256": component_report_sha256,
            "audit_json_path": str(audit_json_path),
            "audit_json_sha256": audit_json_sha256,
            "proteins_tsv_path": str(proteins_tsv_path),
            "proteins_tsv_sha256": proteins_tsv_sha256,
            "input_hashes": input_hashes,
            # C2: the sample-to-component and component-to-partition maps
            # are deliberately ABSENT here -- they already live, in full,
            # exactly once, in the immutable generation's own
            # ``membership_path`` gzip artifact (inventoried/hashed above).
            # Every downstream stage streams/revalidates that artifact via
            # :func:`_sample_to_partition`/:func:`_sample_to_component`
            # instead of trusting a second inline copy in this record.
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


def legacy_diagnostic_fingerprint(
    *,
    config: SplitsConfig002C,
    csv_sha256: str,
    assign_stage_fingerprint: str,
    assign_generation_digest: str,
    decode_generation_digest: str,
    edges_evidence: dict[str, dict],
) -> str:
    # F4: bind EACH edge file's own (key, size, hash) triple, sorted by key
    # -- never a flat, bare-hash list sorted on its own values, which loses
    # which file a hash belongs to.
    edges_terms = tuple(
        (key, entry["byte_size"], entry["sha256"]) for key, entry in sorted(edges_evidence.items())
    )
    return content_fingerprint(
        "legacy_diagnostic", config.content_hash, csv_sha256, assign_stage_fingerprint, assign_generation_digest,
        decode_generation_digest, *edges_terms,
    )


def stage_legacy_diagnostic(
    *,
    config: SplitsConfig002C,
    csv_path: Path,
    output_dir: Path,
    assign_record: dict,
    similarity_edges_dir: Path,
    decode_manifest_path: Path,
    dry_run: bool = False,
) -> dict:
    if dry_run:
        return {"dry_run": True, "stage": "legacy_diagnostic", "would_read": {"csv": str(csv_path)}}

    # F4: the accepted assign record's five frozen inputs must still be
    # current before any downstream real stage runs.
    _verify_current_assignment(config=config, assign_record=assign_record)

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

    fold_result = splits_legacy_diagnostic.run_legacy_fold(
        signed_labels_by_row, protein_ids=protein_ids,
        n_splits=config.legacy_diagnostic.n_splits, shuffle=config.legacy_diagnostic.shuffle,
        random_state=config.legacy_diagnostic.random_state, fold_index=config.legacy_diagnostic.fold_index,
    )

    membership_rows = _read_assign_membership_rows(assign_record)
    sample_to_component = {sample_id: component_id for sample_id, component_id, _p in membership_rows}
    sample_to_partition = {sample_id: partition for sample_id, _c, partition in membership_rows}

    # F2/F4: pinned decode-evidence manifest -- the accepted per-width
    # duplicate-edge (exact/RC) provenance is auto-extracted from it, never
    # hand-typed.
    decode_generation_digest, _fasta_evidence, duplicate_edges_evidence = _load_decode_manifest(
        decode_manifest_path, expected_sha256=config.decode_002b2.manifest_sha256
    )
    canonical_ids = splits_legacy_edges.canonical_sample_ids(config.dataset.expected_row_count)

    # C6/F4: hash-bound, provenance-pinned, endpoint-reconciled evidence is
    # REQUIRED for all three protected widths -- a missing, foreign-endpoint,
    # or unbound (hash not matching its pinned provenance) edges/exact-RC
    # file is a hard failure, never a silently narrower diagnostic, and a
    # bare operator-authored JSON (even an empty list) can no longer qualify
    # merely because its own current hash is recorded.
    similarity_edges_by_width: dict[int, list[tuple[str, str]]] = {}
    exact_rc_edges_by_width: dict[int, list[tuple[str, str]]] = {}
    edges_evidence: dict[str, dict] = {}
    edges_provenance: dict[str, str] = {}
    for width in config.protected_widths:
        edges_path = Path(similarity_edges_dir) / f"edges_{width}.json"
        exact_rc_path = Path(similarity_edges_dir) / f"exact_rc_edges_{width}.json"

        similarity_expected = config.legacy_edges.similarity_edges.get(width)
        if similarity_expected is None:
            raise InputValidationError(f"config has no pinned legacy_edges.similarity_edges entry for width {width}")
        try:
            similarity_edges_by_width[width] = splits_legacy_edges.verify_and_parse_edges(
                edges_path, expected_sha256=similarity_expected.sha256, expected_byte_size=similarity_expected.byte_size,
                canonical_ids=canonical_ids, label=f"similarity edges width {width}",
            )
        except splits_legacy_edges.EdgeProvenanceError as exc:
            raise InputValidationError(str(exc)) from exc
        edges_evidence[f"{width}_similarity"] = splits_legacy_edges.bind_edge_evidence(
            width=width, evidence_kind="similarity", path=edges_path, sha256=similarity_expected.sha256,
            byte_size=similarity_expected.byte_size,
        )

        duplicate_expected = duplicate_edges_evidence.get(width)
        if duplicate_expected is None:
            raise DecodeManifestError(f"decode evidence manifest has no accepted duplicate_edges entry for width {width}")
        try:
            exact_rc_edges_by_width[width] = splits_legacy_edges.verify_and_parse_edges(
                exact_rc_path, expected_sha256=duplicate_expected.sha256, expected_byte_size=duplicate_expected.byte_size,
                canonical_ids=canonical_ids, label=f"exact/RC duplicate edges width {width}",
            )
        except splits_legacy_edges.EdgeProvenanceError as exc:
            raise InputValidationError(str(exc)) from exc
        edges_evidence[f"{width}_exact_rc"] = splits_legacy_edges.bind_edge_evidence(
            width=width, evidence_kind="exact_rc", path=exact_rc_path, sha256=duplicate_expected.sha256,
            byte_size=duplicate_expected.byte_size,
        )

        edges_provenance[f"edges_{width}_path"] = str(edges_path)
        edges_provenance[f"edges_{width}_sha256"] = similarity_expected.sha256
        edges_provenance[f"exact_rc_edges_{width}_path"] = str(exact_rc_path)
        edges_provenance[f"exact_rc_edges_{width}_sha256"] = duplicate_expected.sha256

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
        restart.atomic_write_json(manifest_path, {**report, "edges_provenance": edges_provenance})

        artifacts = restart.inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            "legacy_diagnostic_generation", str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = legacy_diagnostic_fingerprint(
            config=config, csv_sha256=csv_sha256, assign_stage_fingerprint=assign_record["stage_fingerprint"],
            assign_generation_digest=assign_record["generation_digest"], decode_generation_digest=decode_generation_digest,
            edges_evidence=edges_evidence,
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
            # C6: finalization must include the COMPLETE sanitized legacy
            # diagnostic, not only its two index-set digests.
            "report": report,
            "edges_provenance": edges_provenance,
            # F4: explicit (width, evidence kind, size, hash) bindings for
            # all six edge files, never a flat sorted-away hash list.
            "edges_evidence": edges_evidence,
            "upstream": {
                "assign_stage_fingerprint": assign_record["stage_fingerprint"],
                "assign_generation_digest": assign_record["generation_digest"],
                "decode_generation_digest": decode_generation_digest,
            },
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


def exact_audit_fingerprint(
    *,
    width: int,
    config: SplitsConfig002C,
    assign_stage_fingerprint: str,
    assign_generation_digest: str,
    fasta_sha256: str,
    decode_generation_digest: str,
) -> str:
    return content_fingerprint(
        "exact_audit", width, config.content_hash, assign_stage_fingerprint, assign_generation_digest, fasta_sha256,
        decode_generation_digest,
    )


def stage_exact_audit(
    *,
    width: int,
    config: SplitsConfig002C,
    output_dir: Path,
    decode_fasta_dir: Path,
    decode_manifest_path: Path,
    assign_record: dict,
    dry_run: bool = False,
) -> dict:
    if width not in config.protected_widths:
        raise StageValidationError(f"width {width!r} is not one of the protected widths {config.protected_widths}")
    if dry_run:
        return {"dry_run": True, "stage": "exact_audit", "width": width}

    # F4: the accepted assign record's five frozen inputs must still be
    # current before any downstream real stage runs.
    _verify_current_assignment(config=config, assign_record=assign_record)

    # F2: bind this width's decode FASTA to the accepted Task 002B-2
    # decode-evidence manifest.
    decode_generation_digest, fasta_evidence, _duplicate_edges_evidence = _load_decode_manifest(
        decode_manifest_path, expected_sha256=config.decode_002b2.manifest_sha256
    )

    fasta_path = Path(decode_fasta_dir) / DECODE_FASTA_FILENAME_TEMPLATE.format(width=width)
    if not fasta_path.is_file():
        raise InputValidationError(f"decode FASTA not found at {fasta_path}")
    sample_to_partition = _sample_to_partition(assign_record)
    # C3: strict, streaming FASTA validation -- unique canonical IDs, exact
    # requested width, nonempty A/C/G/T-only sequence, and the COMPLETE
    # assigned universe reconciled before any hash group is computed.
    sequences = _read_fasta_strict(fasta_path, expected_width=width, expected_ids=set(sample_to_partition))
    # F2: a syntactically valid but non-accepted FASTA fails closed here.
    fasta_sha256 = _verify_decode_fasta(fasta_path, width=width, fasta_evidence=fasta_evidence)

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
            config=config, width=width, assign_stage_fingerprint=assign_record["stage_fingerprint"],
            assign_generation_digest=assign_record["generation_digest"], fasta_sha256=fasta_sha256,
            decode_generation_digest=decode_generation_digest,
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
            "upstream": {
                "assign_stage_fingerprint": assign_record["stage_fingerprint"],
                "assign_generation_digest": assign_record["generation_digest"],
                "decode_generation_digest": decode_generation_digest,
            },
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


def audit_probe_fingerprint(
    *, width: int, config: SplitsConfig002C, assign_stage_fingerprint: str, assign_generation_digest: str,
    fasta_sha256: str, decode_generation_digest: str, mmseqs_bin: str,
) -> str:
    binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    return content_fingerprint(
        "audit_probe", width, config.content_hash, assign_stage_fingerprint, assign_generation_digest, fasta_sha256,
        decode_generation_digest, binary.sha256 or "MISSING", mmseqs_bin,
    )


def audit_search_fingerprint(
    *, width: int, query_partition: str, target_partition: str, config: SplitsConfig002C,
    assign_stage_fingerprint: str, assign_generation_digest: str, fasta_sha256: str, decode_generation_digest: str,
    mmseqs_bin: str, probe_generation_digest: str,
) -> str:
    binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    # C4: binds the specific probe GENERATION that authorized this search,
    # so a rebuilt (even byte-identical) probe generation still invalidates
    # a search accepted against the old one.
    return content_fingerprint(
        "audit_search", width, query_partition, target_partition, config.content_hash, assign_stage_fingerprint,
        assign_generation_digest, fasta_sha256, decode_generation_digest, binary.sha256 or "MISSING", mmseqs_bin,
        probe_generation_digest,
    )


def _resolve_and_verify_mmseqs_binary(mmseqs_bin: str, *, config: SplitsConfig002C, stage_name: str):
    live_binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    if live_binary.resolved_path is None:
        raise InputValidationError(f"mmseqs binary {mmseqs_bin!r} not found on PATH")
    if live_binary.version != splits_commands.PINNED_VERSION:
        raise InputValidationError(f"mmseqs version {live_binary.version!r} != pinned {splits_commands.PINNED_VERSION!r}")
    if live_binary.sha256 != config.binary.mmseqs_sha256:
        raise InputValidationError(
            f"mmseqs binary SHA-256 {live_binary.sha256!r} != accepted {config.binary.mmseqs_sha256!r} for stage {stage_name!r}"
        )
    return live_binary


def _launch_guarded_mmseqs(command, *, config: SplitsConfig002C, output_dir: Path, log_dir: Path, label: str) -> dict:
    """F3 (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md):
    recheck installed RAM, live available memory, and free disk IMMEDIATELY
    before THIS individual MMseqs2 subprocess launch -- never only once
    before a whole multi-command directed-audit attempt. If memory is
    sufficient for an earlier command in the same attempt but insufficient
    here, this command never launches; the caller's ``except Exception``
    discards the whole candidate generation without touching any prior
    accepted evidence.
    """
    guarded_exec.check_installed_ram_or_fail(min_installed_ram_gib=config.audit.min_installed_ram_gib)
    guarded_exec.check_available_memory_before_launch_or_fail(
        min_available_memory_gib_before_launch=config.audit.min_available_memory_gib_before_launch, label=label
    )
    guarded_exec.check_free_disk_or_fail(disk_path=output_dir, min_free_disk_gib=config.audit.min_free_disk_gib, label=label)
    return guarded_exec.run_guarded_mmseqs(
        command, log_dir=log_dir, timeout_seconds=config.audit.timeout_seconds, output_dir=output_dir,
        max_new_disk_gib=config.audit.max_new_disk_gib, min_free_disk_gib=config.audit.min_free_disk_gib,
        poll_interval=config.audit.resource_poll_interval_seconds,
    )


def _run_mmseqs_pipeline(
    *, width: int, query_seqs: dict[str, str], target_seqs: dict[str, str], config: SplitsConfig002C,
    output_dir: Path, generation_dir: Path, mmseqs_bin: str, label: str,
) -> tuple[Path, list[dict], int]:
    """The shared ``createdb`` (x2) / ``search`` / ``createtsv`` subprocess
    pipeline used by both ``audit_probe`` and ``audit_search``, with F3's
    per-launch resource gate immediately before EACH of the four commands.
    """
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

    executed: list[dict] = []
    executed.append(_launch_guarded_mmseqs(
        splits_commands.with_threads(splits_commands.createdb_command(query_fasta, query_db, mmseqs_bin=mmseqs_bin), threads),
        config=config, output_dir=output_dir, log_dir=log_dir, label=f"{label}:createdb(query)",
    ))
    executed.append(_launch_guarded_mmseqs(
        splits_commands.with_threads(splits_commands.createdb_command(target_fasta, target_db, mmseqs_bin=mmseqs_bin), threads),
        config=config, output_dir=output_dir, log_dir=log_dir, label=f"{label}:createdb(target)",
    ))
    search_cmd = splits_commands.with_threads(
        splits_commands.audit_search_command(query_db, target_db, result_prefix, tmp_dir, width=width, mmseqs_bin=mmseqs_bin), threads
    )
    executed.append(_launch_guarded_mmseqs(search_cmd, config=config, output_dir=output_dir, log_dir=log_dir, label=f"{label}:search"))
    hits_tsv = generation_dir / "hits.tsv"
    executed.append(_launch_guarded_mmseqs(
        splits_commands.with_threads(
            splits_commands.createtsv_search_command(query_db, target_db, result_prefix, hits_tsv, mmseqs_bin=mmseqs_bin), threads
        ),
        config=config, output_dir=output_dir, log_dir=log_dir, label=f"{label}:createtsv",
    ))
    return hits_tsv, executed, threads


def stage_audit_probe(
    *,
    width: int,
    config: SplitsConfig002C,
    output_dir: Path,
    decode_fasta_dir: Path,
    decode_manifest_path: Path,
    assign_record: dict,
    authorize: bool,
    mmseqs_bin: str = "mmseqs",
    dry_run: bool = False,
) -> dict:
    """F1: ``audit_probe`` is WIDTH-scoped only -- exactly one deterministic
    bounded resource probe per protected width, never direction-scoped.
    """
    if width not in config.protected_widths:
        raise StageValidationError(f"width {width!r} is not one of the protected widths {config.protected_widths}")
    if dry_run:
        return {"dry_run": True, "stage": "audit_probe", "width": width, "would_authorize_mmseqs": authorize}
    if not authorize:
        raise AuthorizationError("stage 'audit_probe' launches MMseqs2 and requires --authorize-mmseqs")

    _verify_current_assignment(config=config, assign_record=assign_record)

    decode_generation_digest, fasta_evidence, _duplicate_edges_evidence = _load_decode_manifest(
        decode_manifest_path, expected_sha256=config.decode_002b2.manifest_sha256
    )

    fasta_path = Path(decode_fasta_dir) / DECODE_FASTA_FILENAME_TEMPLATE.format(width=width)
    if not fasta_path.is_file():
        raise InputValidationError(f"decode FASTA not found at {fasta_path}")
    sample_to_partition = _sample_to_partition(assign_record)
    # C3: reconcile the COMPLETE FASTA universe before ever subsetting the
    # deterministic probe sample.
    sequences = _read_fasta_strict(fasta_path, expected_width=width, expected_ids=set(sample_to_partition))
    fasta_sha256 = _verify_decode_fasta(fasta_path, width=width, fasta_evidence=fasta_evidence)

    _resolve_and_verify_mmseqs_binary(mmseqs_bin, config=config, stage_name="audit_probe")

    base_dir = output_dir / "audit_probe" / str(width)
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix="audit_probe")
    try:
        # F1: one deterministic, documented query/target sample covering the
        # intended command/resource shape -- never a partition-directed pair.
        query_seqs, target_seqs = _deterministic_probe_split(sequences, config.audit.probe_sample_size, config.seed)

        hits_tsv, executed, threads = _run_mmseqs_pipeline(
            width=width, query_seqs=query_seqs, target_seqs=target_seqs, config=config, output_dir=output_dir,
            generation_dir=generation_dir, mmseqs_bin=mmseqs_bin, label="audit_probe",
        )

        # C5: peak RSS across this whole guarded attempt, measured once after
        # every subprocess above has been reaped.
        peak_rss_kib = peak_rss_kib_of_children()
        probe_memory = guarded_exec.check_probe_memory_gates_or_fail(
            peak_rss_kib=peak_rss_kib, max_peak_memory_gib=config.audit.probe_max_peak_memory_gib,
            min_available_memory_gib_before_next_stage=config.audit.probe_min_available_memory_gib_before_next_stage,
            label="audit_probe",
        )

        hits = mmseqs_audit.parse_search_hits(hits_tsv)
        guarded_exec.check_combined_ceiling_or_discard(output_dir=output_dir, max_new_disk_gib=config.audit.max_new_disk_gib)

        report = {
            "width": width,
            "query_sample_count": len(query_seqs),
            "target_sample_count": len(target_seqs),
            "hit_count": len(hits),
        }
        manifest_path = generation_dir / "audit_probe_report.json"
        restart.atomic_write_json(manifest_path, report)

        artifacts = restart.inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            "audit_probe_generation", width, str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = audit_probe_fingerprint(
            width=width, config=config, assign_stage_fingerprint=assign_record["stage_fingerprint"],
            assign_generation_digest=assign_record["generation_digest"], fasta_sha256=fasta_sha256,
            decode_generation_digest=decode_generation_digest, mmseqs_bin=mmseqs_bin,
        )
        record = {
            "stage": "audit_probe",
            "executed": True,
            "width": width,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "manifest_path": str(manifest_path),
            "hits_tsv": str(hits_tsv),
            "fasta_sha256": fasta_sha256,
            "hit_count": len(hits),
            "query_sample_count": len(query_seqs),
            "target_sample_count": len(target_seqs),
            "upstream": {
                "assign_stage_fingerprint": assign_record["stage_fingerprint"],
                "assign_generation_digest": assign_record["generation_digest"],
                "decode_generation_digest": decode_generation_digest,
            },
            "mmseqs_bin": mmseqs_bin,
            "threads": threads,
            "peak_rss_kib_of_children": peak_rss_kib,
            "available_memory_gib_after": probe_memory["available_memory_gib_after"],
            "tool_provenance": executed,
            "artifacts": artifacts,
        }
        restart.atomic_write_json(restart.selected_record_path(output_dir, mmseqs_audit.probe_selection_key(width)), record)
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
    return record


def stage_audit_search(
    *,
    width: int,
    query_partition: str,
    target_partition: str,
    config: SplitsConfig002C,
    output_dir: Path,
    decode_fasta_dir: Path,
    decode_manifest_path: Path,
    assign_record: dict,
    authorize: bool,
    mmseqs_bin: str = "mmseqs",
    dry_run: bool = False,
) -> dict:
    mmseqs_audit.validate_direction(query_partition, target_partition)
    if width not in config.protected_widths:
        raise StageValidationError(f"width {width!r} is not one of the protected widths {config.protected_widths}")
    if dry_run:
        return {
            "dry_run": True, "stage": "audit_search", "width": width, "query_partition": query_partition,
            "target_partition": target_partition, "would_authorize_mmseqs": authorize,
        }
    if not authorize:
        raise AuthorizationError("stage 'audit_search' launches MMseqs2 and requires --authorize-mmseqs")

    _verify_current_assignment(config=config, assign_record=assign_record)

    # F1: audit_search binds the SAME current width probe generation (not a
    # per-direction probe -- there is only one, width-scoped).
    probe_record = restart.require_accepted(output_dir, mmseqs_audit.probe_selection_key(width))

    decode_generation_digest, fasta_evidence, _duplicate_edges_evidence = _load_decode_manifest(
        decode_manifest_path, expected_sha256=config.decode_002b2.manifest_sha256
    )

    fasta_path = Path(decode_fasta_dir) / DECODE_FASTA_FILENAME_TEMPLATE.format(width=width)
    if not fasta_path.is_file():
        raise InputValidationError(f"decode FASTA not found at {fasta_path}")
    sample_to_partition = _sample_to_partition(assign_record)
    # C3: reconcile the COMPLETE FASTA universe before ever subsetting a
    # directed query/target pair -- a decode/assignment mismatch fails
    # closed here, never silently narrows the audited universe.
    sequences = _read_fasta_strict(fasta_path, expected_width=width, expected_ids=set(sample_to_partition))
    fasta_sha256 = _verify_decode_fasta(fasta_path, width=width, fasta_evidence=fasta_evidence)

    _resolve_and_verify_mmseqs_binary(mmseqs_bin, config=config, stage_name="audit_search")

    base_dir = output_dir / "audit_search" / str(width) / f"{query_partition}_to_{target_partition}"
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix="audit_search")
    try:
        query_seqs = mmseqs_audit.build_partition_fasta_subset(sequences, sample_to_partition, query_partition)
        target_seqs = mmseqs_audit.build_partition_fasta_subset(sequences, sample_to_partition, target_partition)

        hits_tsv, executed, threads = _run_mmseqs_pipeline(
            width=width, query_seqs=query_seqs, target_seqs=target_seqs, config=config, output_dir=output_dir,
            generation_dir=generation_dir, mmseqs_bin=mmseqs_bin, label="audit_search",
        )

        peak_rss_kib = peak_rss_kib_of_children()
        hits = mmseqs_audit.parse_search_hits(hits_tsv)
        directed_result = mmseqs_audit.reconcile_directed_hits(
            hits, width=width, query_partition=query_partition, target_partition=target_partition,
            query_universe=list(query_seqs), target_universe=list(target_seqs),
        )

        guarded_exec.check_combined_ceiling_or_discard(output_dir=output_dir, max_new_disk_gib=config.audit.max_new_disk_gib)

        manifest_path = generation_dir / "audit_search_report.json"
        restart.atomic_write_json(manifest_path, directed_result.to_dict())

        artifacts = restart.inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            "audit_search_generation", width, query_partition, target_partition, str(generation_dir),
            *((e["path"], e["sha256"]) for e in artifacts),
        )
        probe_generation_digest = probe_record["generation_digest"]
        stage_fp = audit_search_fingerprint(
            width=width, query_partition=query_partition, target_partition=target_partition, config=config,
            assign_stage_fingerprint=assign_record["stage_fingerprint"],
            assign_generation_digest=assign_record["generation_digest"], fasta_sha256=fasta_sha256,
            decode_generation_digest=decode_generation_digest, mmseqs_bin=mmseqs_bin,
            probe_generation_digest=probe_generation_digest,
        )
        record = {
            "stage": "audit_search",
            "executed": True,
            "width": width,
            "query_partition": query_partition,
            "target_partition": target_partition,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "manifest_path": str(manifest_path),
            "hits_tsv": str(hits_tsv),
            "fasta_sha256": fasta_sha256,
            "hit_count": directed_result.hit_count,
            "violation_count": len(directed_result.violations),
            "passed": directed_result.passed,
            "upstream": {
                "assign_stage_fingerprint": assign_record["stage_fingerprint"],
                "assign_generation_digest": assign_record["generation_digest"],
                "decode_generation_digest": decode_generation_digest,
                "probe_generation_digest": probe_generation_digest,
            },
            "mmseqs_bin": mmseqs_bin,
            "threads": threads,
            "peak_rss_kib_of_children": peak_rss_kib,
            "tool_provenance": executed,
            "artifacts": artifacts,
        }
        restart.atomic_write_json(
            restart.selected_record_path(output_dir, mmseqs_audit.selection_key("audit_search", width, query_partition, target_partition)),
            record,
        )
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
    return record


# --------------------------------------------------------------------------
# finalize
# --------------------------------------------------------------------------


def _independently_recompute_summary(*, config: SplitsConfig002C, assign_record: dict, final_rows: list[tuple[str, str, str]]) -> dict:
    """Re-derives the complete scientific summary FROM SCRATCH off the final
    membership rows plus a fresh CSV stream, rather than trusting the
    ``assign`` record's own cached ``balance_report``/``minimum_count_report``
    fields (docs/reviews/002c1_partition_orchestration_correction_review.md,
    C4: "independently re-reading the final membership and recomputing the
    complete ID universe, component indivisibility, partition counts, row
    deviations, all 244 evaluation-floor counts, and audit completeness
    before promotion").
    """
    expected_ids = {f"row_{i}" for i in range(config.dataset.expected_row_count)}
    actual_ids = {row[0] for row in final_rows}
    problems: list[str] = []
    missing = expected_ids - actual_ids
    foreign = actual_ids - expected_ids
    if missing:
        problems.append(f"final membership is missing {len(missing)} expected ID(s), e.g. {sorted(missing)[:5]}")
    if foreign:
        problems.append(f"final membership contains {len(foreign)} foreign ID(s), e.g. {sorted(foreign)[:5]}")

    component_partitions: dict[str, set[str]] = {}
    sample_to_partition: dict[str, str] = {}
    partition_row_counts: dict[str, int] = {p: 0 for p in assignment.PARTITIONS}
    for sample_id, component_id, partition in final_rows:
        component_partitions.setdefault(component_id, set()).add(partition)
        sample_to_partition[sample_id] = partition
        partition_row_counts[partition] = partition_row_counts.get(partition, 0) + 1

    divided = sorted(cid for cid, partitions in component_partitions.items() if len(partitions) > 1)
    if divided:
        problems.append(f"{len(divided)} component(s) span more than one partition, e.g. {divided[:5]}")

    total_rows = len(final_rows)
    balance = splits_audit.balance_report(
        partition_row_counts, assignment.TARGET_FRACTIONS, total_rows,
        flag_threshold_pct=config.assignment.balance_deviation_flag_pct,
    )

    csv_path = Path(assign_record["csv_path"])
    current_csv_sha256 = _verify_csv(csv_path, config)
    if current_csv_sha256 != assign_record["csv_sha256"]:
        problems.append(
            f"CSV at {csv_path} now hashes to {current_csv_sha256}, but the accepted assign record validated "
            f"{assign_record['csv_sha256']!r}"
        )

    partition_pos: dict[tuple[str, int], int] = {}
    partition_neg: dict[tuple[str, int], int] = {}
    for _row_index, sample_id, labels in ingestion.iter_csv_component_label_rows(
        csv_path, protein_id_min=config.dataset.protein_id_min, protein_id_max=config.dataset.protein_id_max
    ):
        partition = sample_to_partition.get(sample_id)
        if partition is None:
            continue
        for protein_id, sign in labels.items():
            key = (partition, protein_id)
            if sign > 0:
                partition_pos[key] = partition_pos.get(key, 0) + 1
            else:
                partition_neg[key] = partition_neg.get(key, 0) + 1

    protein_ids = list(range(config.dataset.protein_id_min, config.dataset.protein_id_max + 1))
    partition_label_counts = {
        p: {pid: (partition_pos.get((p, pid), 0), partition_neg.get((p, pid), 0)) for pid in protein_ids}
        for p in assignment.PARTITIONS
    }
    minimum_count_report = splits_audit.minimum_count_check(partition_label_counts, floor=config.assignment.evaluation_floor)

    return {
        "problems": problems,
        "total_rows": total_rows,
        "partition_row_counts": partition_row_counts,
        "balance_report": balance,
        "minimum_count_report": minimum_count_report,
    }


def stage_finalize(*, config: SplitsConfig002C, output_dir: Path, dry_run: bool = False) -> dict:
    if dry_run:
        return {"dry_run": True, "stage": "finalize"}

    assign_record = restart.require_accepted(output_dir, "assign")
    # F4: the accepted assign record's five frozen inputs must still be
    # current before finalization.
    _verify_current_assignment(config=config, assign_record=assign_record)

    legacy_record = restart.require_accepted(output_dir, "legacy_diagnostic")
    exact_audit_records = {
        width: restart.require_accepted(output_dir, f"exact_audit_{width}") for width in config.protected_widths
    }
    # F1: finalization requires exactly THREE width-scoped probes (not 18)
    # plus all 18 directed searches.
    probe_records: dict[str, dict] = {
        mmseqs_audit.probe_selection_key(width): restart.require_accepted(output_dir, mmseqs_audit.probe_selection_key(width))
        for width in config.protected_widths
    }
    search_records: dict[str, dict] = {}
    for width in config.protected_widths:
        for query_partition, target_partition in mmseqs_audit.ORDERED_PARTITION_PAIRS:
            search_key = mmseqs_audit.selection_key("audit_search", width, query_partition, target_partition)
            search_records[search_key] = restart.require_accepted(output_dir, search_key)

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
        # F1/C4: bind every accepted search to the SAME width probe
        # generation currently accepted, not merely to whichever probe
        # happened to exist when the search first ran.
        expected_probe_key = mmseqs_audit.probe_selection_key(record["width"])
        current_probe_generation_digest = probe_records[expected_probe_key]["generation_digest"]
        recorded_probe_generation_digest = record.get("upstream", {}).get("probe_generation_digest")
        if recorded_probe_generation_digest != current_probe_generation_digest:
            problems.append(
                f"{key}: was accepted against a different probe generation than the currently accepted "
                f"{expected_probe_key!r}; rerun and accept audit_search"
            )

    if problems:
        raise FinalizationRefusedError("finalize refused: " + "; ".join(problems))

    rows = splits_output.read_membership_gzip(Path(assign_record["membership_path"]))

    # C4: independently RECOMPUTE the complete ID universe, component
    # indivisibility, partition counts, row deviations, and all 244
    # evaluation-floor counts from the final membership plus a fresh CSV
    # stream -- rather than trusting the assign record's own cached copies.
    recomputed = _independently_recompute_summary(config=config, assign_record=assign_record, final_rows=rows)
    if recomputed["problems"]:
        raise FinalizationRefusedError(
            "finalize refused: independent recomputation disagrees with accepted evidence: "
            + "; ".join(recomputed["problems"])
        )
    if recomputed["partition_row_counts"] != dict(assign_record["partition_row_counts"]):
        raise FinalizationRefusedError(
            "finalize refused: independently recomputed partition row counts "
            f"{recomputed['partition_row_counts']} disagree with the accepted assign record "
            f"{assign_record['partition_row_counts']}"
        )
    if not recomputed["minimum_count_report"]["passed"]:
        raise FinalizationRefusedError(
            "finalize refused: independently recomputed evaluation-floor counts report a violation the accepted "
            "assign record's cached summary did not"
        )

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
            "assign_generation_digest": assign_record["generation_digest"],
            "legacy_diagnostic_stage_fingerprint": legacy_record["stage_fingerprint"],
            "legacy_diagnostic_generation_digest": legacy_record["generation_digest"],
        }
        for width, record in exact_audit_records.items():
            upstream_digests[f"exact_audit_{width}_stage_fingerprint"] = record["stage_fingerprint"]
            upstream_digests[f"exact_audit_{width}_generation_digest"] = record["generation_digest"]
        for key, record in probe_records.items():
            upstream_digests[f"{key}_stage_fingerprint"] = record["stage_fingerprint"]
            upstream_digests[f"{key}_generation_digest"] = record["generation_digest"]
        for key, record in search_records.items():
            upstream_digests[f"{key}_stage_fingerprint"] = record["stage_fingerprint"]
            upstream_digests[f"{key}_generation_digest"] = record["generation_digest"]

        manifest = {
            "schema_version": 2,
            "checkpoint": "002C-1-finalize",
            "config_hash": config.content_hash,
            "partition_row_counts": recomputed["partition_row_counts"],
            "minimum_count_report": recomputed["minimum_count_report"],
            "balance_report": recomputed["balance_report"],
            "exact_audit_summary": {
                str(width): {"passed": record["passed"], "violation_count": record.get("violation_count")}
                for width, record in exact_audit_records.items()
            },
            # F1: probes carry no "passed"/cross-partition semantics -- the
            # deterministic query/target split is not partition-directed.
            "audit_probe_summary": {
                key: {"hit_count": record.get("hit_count")}
                for key, record in probe_records.items()
            },
            "audit_search_summary": {
                key: {"passed": record["passed"], "hit_count": record.get("hit_count")}
                for key, record in search_records.items()
            },
            # C6: the COMPLETE sanitized legacy diagnostic, not only its two
            # index-set digests.
            "legacy_diagnostic": legacy_record.get("report", {
                "train_digest": legacy_record["train_digest"], "holdout_digest": legacy_record["holdout_digest"],
            }),
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
    parser.add_argument("--component-report", type=Path, default=None)
    parser.add_argument("--audit-json", type=Path, default=None)
    parser.add_argument("--proteins-tsv", type=Path, default=None)
    parser.add_argument("--decode-fasta-dir", type=Path, default=None)
    parser.add_argument("--decode-manifest", type=Path, default=None)
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

    if args.stage == "legacy_diagnostic" and args.similarity_edges_dir is None and not args.dry_run:
        raise StageValidationError("stage 'legacy_diagnostic' requires --similarity-edges-dir")

    config = load_config_002c(args.config)
    output_dir = args.output_dir
    repo_root = _repo_root(args.config, args.repo_root)
    audit_json_path = args.audit_json if args.audit_json is not None else _resolve(repo_root, config.dataset.audit_json_path)
    proteins_tsv_path = args.proteins_tsv if args.proteins_tsv is not None else _resolve(repo_root, config.dataset.proteins_tsv_path)
    decode_manifest_path = (
        args.decode_manifest if args.decode_manifest is not None else _resolve(repo_root, config.decode_002b2.manifest_path)
    )

    if args.stage == "assign":
        if args.dry_run:
            result = stage_assign(
                config=config, csv_path=args.csv, membership_path=args.component_membership,
                component_report_path=args.component_report, audit_json_path=audit_json_path,
                proteins_tsv_path=proteins_tsv_path, output_dir=output_dir, dry_run=True,
            )
        else:
            def _hash_or_missing(p: Path | None) -> str:
                return sha256_file(Path(p)) if p and Path(p).is_file() else "MISSING"

            csv_sha256 = _hash_or_missing(args.csv)
            membership_sha256 = _hash_or_missing(args.component_membership)
            component_report_sha256 = _hash_or_missing(args.component_report)
            audit_json_sha256 = _hash_or_missing(audit_json_path)
            proteins_tsv_sha256 = _hash_or_missing(proteins_tsv_path)
            current_fp = assign_fingerprint(
                config=config, csv_sha256=csv_sha256, membership_sha256=membership_sha256,
                component_report_sha256=component_report_sha256, audit_json_sha256=audit_json_sha256,
                proteins_tsv_sha256=proteins_tsv_sha256,
            )
            prior = None if args.force else restart.load_accepted(output_dir, "assign")
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_assign(
                    config=config, csv_path=args.csv, membership_path=args.component_membership,
                    component_report_path=args.component_report, audit_json_path=audit_json_path,
                    proteins_tsv_path=proteins_tsv_path, output_dir=output_dir,
                )

    elif args.stage == "legacy_diagnostic":
        if args.dry_run:
            result = stage_legacy_diagnostic(
                config=config, csv_path=args.csv, output_dir=output_dir, assign_record={},
                similarity_edges_dir=args.similarity_edges_dir, decode_manifest_path=decode_manifest_path, dry_run=True,
            )
        else:
            assign_record = restart.require_accepted(output_dir, "assign")
            _verify_current_assignment(config=config, assign_record=assign_record)
            csv_sha256 = sha256_file(Path(args.csv)) if args.csv and Path(args.csv).is_file() else "MISSING"
            decode_generation_digest = "MISSING"
            edges_evidence: dict[str, dict] = {}
            if decode_manifest_path.is_file():
                decode_generation_digest, _fasta_evidence, duplicate_edges_evidence = _load_decode_manifest(
                    decode_manifest_path, expected_sha256=config.decode_002b2.manifest_sha256
                )
                for width in config.protected_widths:
                    similarity_expected = config.legacy_edges.similarity_edges.get(width)
                    edges_path = Path(args.similarity_edges_dir) / f"edges_{width}.json"
                    if similarity_expected is not None:
                        edges_evidence[f"{width}_similarity"] = splits_legacy_edges.bind_edge_evidence(
                            width=width, evidence_kind="similarity", path=edges_path,
                            sha256=similarity_expected.sha256, byte_size=similarity_expected.byte_size,
                        )
                    duplicate_expected = duplicate_edges_evidence.get(width)
                    exact_rc_path = Path(args.similarity_edges_dir) / f"exact_rc_edges_{width}.json"
                    if duplicate_expected is not None:
                        edges_evidence[f"{width}_exact_rc"] = splits_legacy_edges.bind_edge_evidence(
                            width=width, evidence_kind="exact_rc", path=exact_rc_path,
                            sha256=duplicate_expected.sha256, byte_size=duplicate_expected.byte_size,
                        )
            current_fp = legacy_diagnostic_fingerprint(
                config=config, csv_sha256=csv_sha256, assign_stage_fingerprint=assign_record["stage_fingerprint"],
                assign_generation_digest=assign_record["generation_digest"],
                decode_generation_digest=decode_generation_digest, edges_evidence=edges_evidence,
            )
            prior = None if args.force else restart.load_accepted(output_dir, "legacy_diagnostic")
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_legacy_diagnostic(
                    config=config, csv_path=args.csv, output_dir=output_dir, assign_record=assign_record,
                    similarity_edges_dir=args.similarity_edges_dir, decode_manifest_path=decode_manifest_path,
                )

    elif args.stage == "exact_audit":
        if args.dry_run:
            result = stage_exact_audit(
                width=args.width, config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir,
                decode_manifest_path=decode_manifest_path, assign_record={}, dry_run=True,
            )
        else:
            assign_record = restart.require_accepted(output_dir, "assign")
            _verify_current_assignment(config=config, assign_record=assign_record)
            fasta_path = (
                Path(args.decode_fasta_dir) / DECODE_FASTA_FILENAME_TEMPLATE.format(width=args.width)
                if args.decode_fasta_dir else None
            )
            fasta_sha256 = sha256_file(fasta_path) if fasta_path and fasta_path.is_file() else "MISSING"
            decode_generation_digest = "MISSING"
            if decode_manifest_path.is_file():
                decode_generation_digest, _fasta_evidence, _dup = _load_decode_manifest(
                    decode_manifest_path, expected_sha256=config.decode_002b2.manifest_sha256
                )
            key = f"exact_audit_{args.width}"
            current_fp = exact_audit_fingerprint(
                config=config, width=args.width, assign_stage_fingerprint=assign_record["stage_fingerprint"],
                assign_generation_digest=assign_record["generation_digest"], fasta_sha256=fasta_sha256,
                decode_generation_digest=decode_generation_digest,
            )
            prior = None if args.force else restart.load_accepted(output_dir, key)
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_exact_audit(
                    width=args.width, config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir,
                    decode_manifest_path=decode_manifest_path, assign_record=assign_record,
                )

    elif args.stage == "audit_probe":
        if args.dry_run:
            result = stage_audit_probe(
                width=args.width, config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir,
                decode_manifest_path=decode_manifest_path, assign_record={}, authorize=args.authorize_mmseqs,
                mmseqs_bin=args.mmseqs_bin, dry_run=True,
            )
        else:
            assign_record = restart.require_accepted(output_dir, "assign")
            _verify_current_assignment(config=config, assign_record=assign_record)
            key = mmseqs_audit.probe_selection_key(args.width)
            fasta_path = (
                Path(args.decode_fasta_dir) / DECODE_FASTA_FILENAME_TEMPLATE.format(width=args.width)
                if args.decode_fasta_dir else None
            )
            fasta_sha256 = sha256_file(fasta_path) if fasta_path and fasta_path.is_file() else "MISSING"
            decode_generation_digest = "MISSING"
            if decode_manifest_path.is_file():
                decode_generation_digest, _fasta_evidence, _dup = _load_decode_manifest(
                    decode_manifest_path, expected_sha256=config.decode_002b2.manifest_sha256
                )
            current_fp = audit_probe_fingerprint(
                width=args.width, config=config, assign_stage_fingerprint=assign_record["stage_fingerprint"],
                assign_generation_digest=assign_record["generation_digest"], fasta_sha256=fasta_sha256,
                decode_generation_digest=decode_generation_digest, mmseqs_bin=args.mmseqs_bin,
            )
            prior = None if args.force else restart.load_accepted(output_dir, key)
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_audit_probe(
                    width=args.width, config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir,
                    decode_manifest_path=decode_manifest_path, assign_record=assign_record,
                    authorize=args.authorize_mmseqs, mmseqs_bin=args.mmseqs_bin,
                )

    elif args.stage == "audit_search":
        if args.dry_run:
            result = stage_audit_search(
                width=args.width, query_partition=args.query_partition, target_partition=args.target_partition,
                config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir,
                decode_manifest_path=decode_manifest_path, assign_record={}, authorize=args.authorize_mmseqs,
                mmseqs_bin=args.mmseqs_bin, dry_run=True,
            )
        else:
            assign_record = restart.require_accepted(output_dir, "assign")
            _verify_current_assignment(config=config, assign_record=assign_record)
            key = mmseqs_audit.selection_key("audit_search", args.width, args.query_partition, args.target_partition)
            fasta_path = (
                Path(args.decode_fasta_dir) / DECODE_FASTA_FILENAME_TEMPLATE.format(width=args.width)
                if args.decode_fasta_dir else None
            )
            fasta_sha256 = sha256_file(fasta_path) if fasta_path and fasta_path.is_file() else "MISSING"
            decode_generation_digest = "MISSING"
            if decode_manifest_path.is_file():
                decode_generation_digest, _fasta_evidence, _dup = _load_decode_manifest(
                    decode_manifest_path, expected_sha256=config.decode_002b2.manifest_sha256
                )
            probe_key = mmseqs_audit.probe_selection_key(args.width)
            probe_record = restart.load_accepted(output_dir, probe_key)
            probe_generation_digest = probe_record["generation_digest"] if probe_record is not None else "MISSING"
            current_fp = audit_search_fingerprint(
                width=args.width, query_partition=args.query_partition, target_partition=args.target_partition,
                config=config, assign_stage_fingerprint=assign_record["stage_fingerprint"],
                assign_generation_digest=assign_record["generation_digest"], fasta_sha256=fasta_sha256,
                decode_generation_digest=decode_generation_digest, mmseqs_bin=args.mmseqs_bin,
                probe_generation_digest=probe_generation_digest,
            )
            prior = None if args.force else restart.load_accepted(output_dir, key)
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_audit_search(
                    width=args.width, query_partition=args.query_partition, target_partition=args.target_partition,
                    config=config, output_dir=output_dir, decode_fasta_dir=args.decode_fasta_dir,
                    decode_manifest_path=decode_manifest_path, assign_record=assign_record,
                    authorize=args.authorize_mmseqs, mmseqs_bin=args.mmseqs_bin,
                )

    elif args.stage == "finalize":
        result = stage_finalize(config=config, output_dir=output_dir, dry_run=args.dry_run)

    else:  # pragma: no cover - argparse choices already excludes this
        raise StageValidationError(f"unknown stage {args.stage!r}")

    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
