"""Streaming, deterministic assembly-report/FASTA derivation.

Implements the frozen contig policy from
``docs/tasks/001b_coordinate_feasibility_execution.md``: include
``assembled-molecule``/``unlocalized-scaffold``/``unplaced-scaffold`` from
the ``Primary Assembly`` unit, plus the mitochondrial ``assembled-molecule``
from the ``non-nuclear`` unit; exclude everything else (alternate loci,
patches, decoys, separately packaged HLA contigs). The source accession is
preserved as the FASTA identifier verbatim — never a UCSC/convenience alias,
an inferred substitute, or a combination of RefSeq and GenBank packages.

B3B-1 accession-policy correction: this module distinguishes four distinct
outcomes for an assembly-report row that a reviewer/test must never conflate:

1. **category-ineligible** — the row's Sequence-Role/Assembly-Unit is outside
   the frozen contig policy (see :func:`contig_category` returning ``None``);
   not reported as an exclusion at all, it simply never enters selection.
2. **source-namespace-unrepresented** — the row IS category-eligible, but has
   no usable accession in the caller's configured
   ``DerivedReferencePolicy.accession_preference`` namespace(s) (see
   :func:`selected_accession` returning ``None``). This is an explicit,
   reported exclusion (``excluded_records``/``exclusion_summary`` on
   :class:`ReferenceDerivation`) — never inferred by scanning the FASTA for
   absent headers, and never a corrupt-source or parser-failure diagnosis.
3. **selected** — a category-eligible row with a usable in-namespace
   accession; it must then occur exactly once in the source FASTA at the
   assembly-report length, or derivation fails closed (outcome 4).
4. **hard missing/duplicate/length-mismatched selected accession** — a
   *selected* accession absent, duplicated, or length-discordant in the
   source FASTA. This is always a hard :class:`DerivationError`, never an
   inferred exclusion of any kind — accession-namespace policy only ever
   decides which rows are *candidates* for selection, never whether an
   already-selected accession's presence in the FASTA is optional.

Both the assembly-report parse and the FASTA filter are single sequential
passes: neither loads a multi-gigabyte reference into memory, so this scales
to a real hg38/hg19 source FASTA. B1/B3B-1 exercise this only against tiny
synthetic fixtures mirroring NCBI's real column layout.
"""

from __future__ import annotations

import gzip
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from rbpbench.coordinates.execution_sources import DerivedReferencePolicy, validate_derived_reference_policy
from rbpbench.coordinates.provenance import current_git_commit
from rbpbench.data.audit import sha256_file

_DEFAULT_ASSEMBLY_REPORT_COLUMNS = (
    "Sequence-Name",
    "Sequence-Role",
    "Assigned-Molecule",
    "Assigned-Molecule-Location/Type",
    "GenBank-Accn",
    "Relationship",
    "RefSeq-Accn",
    "Assembly-Unit",
    "Sequence-Length",
    "UCSC-style-name",
)

PRIMARY_ASSEMBLY_UNIT = "Primary Assembly"
NON_NUCLEAR_UNIT = "non-nuclear"
INCLUDED_PRIMARY_ROLES = ("assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold")

CATEGORY_CHROMOSOME = "chromosome"
CATEGORY_MITOCHONDRION = "mitochondrion"
CATEGORY_UNLOCALIZED = "unlocalized_scaffold"
CATEGORY_UNPLACED = "unplaced_scaffold"

# B3B-1: the one recognized exclusion reason -- a category-eligible row with
# no usable accession in the configured source namespace(s).
EXCLUSION_REASON_SOURCE_NAMESPACE_UNREPRESENTED = "source_namespace_unrepresented"

_NAMESPACE_ACCESSION_FIELD = {
    "refseq": lambda record: record.refseq_accession,
    "genbank": lambda record: record.genbank_accession,
}


@dataclass(frozen=True)
class AssemblyReportRecord:
    sequence_name: str
    sequence_role: str
    assigned_molecule: str
    genbank_accession: str
    refseq_accession: str
    assembly_unit: str
    sequence_length: int


def parse_assembly_report(path: Path) -> tuple[AssemblyReportRecord, ...]:
    """Single sequential pass over an NCBI-style assembly report.

    The header is read from the last ``#``-prefixed line before the first
    data line when it names ``Sequence-Name`` (real NCBI reports do this);
    otherwise the standard NCBI column order is assumed. Never loads
    anything beyond one line at a time.
    """
    columns = _DEFAULT_ASSEMBLY_REPORT_COLUMNS
    last_comment: str | None = None
    records: list[AssemblyReportRecord] = []
    with Path(path).open() as handle:
        for raw_line in handle:
            # B3A-A4: strip both LF and CRLF line endings so a CRLF-sourced
            # assembly report is handled safely -- a bare rstrip("\n") would
            # leave a trailing "\r" attached to the last column of every row
            # (silently corrupting e.g. Sequence-Length parsing or accession
            # strings) without ever raising.
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            if line.startswith("#"):
                last_comment = line
                continue
            if last_comment is not None and "Sequence-Name" in last_comment:
                columns = tuple(last_comment.lstrip("#").strip().split("\t"))
                last_comment = None
            fields = line.split("\t")
            row = dict(zip(columns, fields))
            records.append(
                AssemblyReportRecord(
                    sequence_name=row.get("Sequence-Name", ""),
                    sequence_role=row.get("Sequence-Role", ""),
                    assigned_molecule=row.get("Assigned-Molecule", ""),
                    genbank_accession=row.get("GenBank-Accn", ""),
                    refseq_accession=row.get("RefSeq-Accn", ""),
                    assembly_unit=row.get("Assembly-Unit", ""),
                    sequence_length=int(row.get("Sequence-Length", "0") or 0),
                )
            )
    return tuple(records)


def contig_category(record: AssemblyReportRecord) -> str | None:
    """Map one assembly-report record to a study contig category, or
    ``None`` to exclude it (alternate loci, patches, decoys, separately
    packaged HLA contigs, and anything else outside the frozen policy).
    """
    role = record.sequence_role.strip().lower()
    unit = record.assembly_unit.strip()
    if unit == PRIMARY_ASSEMBLY_UNIT:
        if role == "assembled-molecule":
            return CATEGORY_CHROMOSOME
        if role == "unlocalized-scaffold":
            return CATEGORY_UNLOCALIZED
        if role == "unplaced-scaffold":
            return CATEGORY_UNPLACED
        return None
    if unit == NON_NUCLEAR_UNIT and role == "assembled-molecule":
        return CATEGORY_MITOCHONDRION
    return None


def _valid_raw_accession(value: str) -> str:
    """A raw assembly-report accession field, or ``""`` if it is empty or the
    NCBI ``na`` sentinel.
    """
    value = value.strip()
    if not value or value.lower() == "na":
        return ""
    return value


def selected_accession(record: AssemblyReportRecord, policy: DerivedReferencePolicy) -> str | None:
    """B3B-1: policy-driven accession-namespace selection.

    Returns the first usable accession found, in ``policy.accession_preference``
    order, among ONLY the explicitly configured namespaces — never a
    namespace absent from the policy, even when the record has a usable
    accession there (e.g. under a RefSeq-only policy, a present GenBank
    accession is never used as a silent fallback; it must be named
    ``"genbank"`` in the policy for that to happen). ``None`` means this
    record has no usable accession in any configured namespace — an explicit
    ``source_namespace_unrepresented`` exclusion, not a fallback trigger and
    not an error by itself (see the module docstring).

    Callers must validate ``policy`` with
    :func:`rbpbench.coordinates.execution_sources.validate_derived_reference_policy`
    before calling this — it trusts ``policy.accession_preference`` to name
    only supported namespaces.
    """
    for namespace in policy.accession_preference:
        raw = _NAMESPACE_ACCESSION_FIELD[namespace](record)
        candidate = _valid_raw_accession(raw)
        if candidate:
            return candidate
    return None


def _raw_identifying_accession(record: AssemblyReportRecord) -> str:
    """The best available raw accession for identifying a
    source-namespace-unrepresented row in exclusion evidence — independent of
    ``policy`` (a row can be unrepresented in the configured namespace while
    still carrying a real accession in a different namespace, and that is
    exactly the identifier a reviewer needs to see).
    """
    for value in (record.refseq_accession, record.genbank_accession):
        candidate = _valid_raw_accession(value)
        if candidate:
            return candidate
    return ""


class DerivationError(ValueError):
    """Raised when the streaming derivation's own consistency checks fail."""


@dataclass(frozen=True)
class ReferenceDerivation:
    output_fasta: Path
    output_fasta_sha256: str
    output_fasta_byte_size: int
    contigs: tuple[str, ...]
    contig_categories: dict[str, str]
    category_counts: dict[str, int]
    accession_to_assembly_chrom_name: dict[str, str]
    masking: dict
    # B3A-A2: per-accession sequence lengths, keyed identically to
    # ``contigs`` -- required so B3 can deterministically select and prove
    # the largest included contig from the accepted manifest alone, without
    # re-deriving or re-scanning the reference FASTA.
    contig_lengths: dict[str, int] = field(default_factory=dict)
    # B3B-1: the exact canonical policy this derivation was run under (see
    # ``DerivedReferencePolicy``, serialized to plain JSON-safe types), and
    # structured evidence for every category-eligible row explicitly excluded
    # as source-namespace-unrepresented -- never a selected missing FASTA
    # record, and never inferred by scanning for absent FASTA headers.
    effective_policy: dict = field(default_factory=dict)
    excluded_records: tuple[dict, ...] = field(default_factory=tuple)
    exclusion_summary: dict = field(default_factory=dict)


def largest_contig(contig_lengths: dict[str, int]) -> str:
    """B3A-A2: the deterministic largest-included-contig rule -- greatest
    length first, then accession lexicographic order as the ONLY tie-break.

    Tie-break convention (a genuine ambiguity in the reconciled plan text,
    resolved here explicitly): among contigs tied for the greatest length,
    the one that sorts FIRST in ascending accession lexicographic order
    wins (e.g. ``NC_TEST1.1`` before ``NC_TEST2.1``) -- the ordinary reading
    of "alphabetically first" -- not the lexicographically greatest. A pure
    function over already-validated ``contig_lengths`` so the B3 probe stage
    (and its tests) can select/prove the same contig independent of any file
    I/O.
    """
    if not contig_lengths:
        raise DerivationError("largest_contig: contig_lengths is empty")
    return min(contig_lengths.items(), key=lambda item: (-item[1], item[0]))[0]


def validate_contig_lengths(
    contig_lengths: dict[str, int], *, contigs: tuple[str, ...], assembly_report_lengths: dict[str, int], total_emitted_bases: int
) -> tuple[str, ...]:
    """B3A-A2 fail-closed validation of accepted ``contig_lengths`` evidence:
    exact key equality with ``contigs``, positive integer lengths, agreement
    with the assembly report's own declared length for that accession, and
    that the lengths sum to the total emitted FASTA base count. Returns the
    violations (empty means valid).
    """
    violations: list[str] = []
    if set(contig_lengths) != set(contigs):
        violations.append(
            f"contig_lengths keys {sorted(contig_lengths)} do not exactly equal contigs {sorted(contigs)}"
        )
    for accession, length in contig_lengths.items():
        if not isinstance(length, int) or length <= 0:
            violations.append(f"contig_lengths[{accession!r}] = {length!r} is not a positive integer")
            continue
        expected = assembly_report_lengths.get(accession)
        if expected is not None and length != expected:
            violations.append(
                f"contig_lengths[{accession!r}] = {length} does not agree with assembly-report length {expected}"
            )
    observed_total = sum(v for v in contig_lengths.values() if isinstance(v, int) and v > 0)
    if observed_total != total_emitted_bases:
        violations.append(
            f"sum(contig_lengths.values()) = {observed_total} does not agree with the total emitted FASTA base "
            f"count {total_emitted_bases}"
        )
    return tuple(violations)


def _masking_status(counts: dict[str, int]) -> str:
    """``soft`` when any lowercase base is present (NCBI RefSeq genomic
    FASTA soft-masks repeats in lowercase); ``none_detected`` otherwise.

    B1-R9: a high ``N`` (ambiguous-symbol) fraction never by itself
    establishes ``hard`` masking — assembly gaps produce the same base-count
    signature as hard-masked repeats, so an uppercase assembly with ordinary
    gaps must not be mislabeled ``hard`` from base counts alone. ``hard``
    would require authoritative source metadata (not available to B1's
    streaming derivation) to actually confirm; until such metadata is wired
    in, this heuristic only ever reports ``soft`` or ``none_detected``. Raw
    upper/lower/ambiguous counts are always retained (see ``masking`` in the
    returned manifest) so a reviewer can inspect the evidence directly rather
    than trusting this label alone.
    """
    if counts.get("lower", 0) > 0:
        return "soft"
    return "none_detected"


def _open_text(path: Path) -> IO[str]:
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt")
    return Path(path).open("rt")


def derive_reference_fasta(
    *,
    source_fasta: Path,
    assembly_report: Path,
    output_fasta: Path,
    policy: DerivedReferencePolicy,
) -> ReferenceDerivation:
    """Stream ``source_fasta`` (plain or ``.gz``) once, writing only the
    accessions selected by :func:`contig_category`/:func:`selected_accession`
    (deterministically, from ``policy``) to ``output_fasta`` in
    source-encounter order (so repeated derivation over unchanged inputs is
    byte-for-byte reproducible), and verify:

    1. every selected accession occurs exactly once in the source;
    2. no unselected accession appears in the derived FASTA;
    3. every derived sequence length equals the assembly-report length.

    A category-eligible row with no accession in ``policy``'s configured
    source namespace(s) is an explicit ``source_namespace_unrepresented``
    exclusion (recorded in the returned ``excluded_records``/
    ``exclusion_summary``), never a selected-but-missing FASTA record and
    never inferred by scanning for absent FASTA headers — see the module
    docstring for the full eligible/unrepresented/selected/hard-failure
    distinction.

    Never loads the source FASTA whole: one line is held at a time. Writes to
    an attempt-specific temporary file and only atomically promotes it onto
    ``output_fasta`` after every verification check passes (B1-R7/B3B-1): a
    failed derivation (a policy violation, an occurrence/length verification
    violation, or any exception mid-stream) must never destroy a prior valid
    ``output_fasta`` left over from an earlier successful derivation.
    """
    policy_violations = validate_derived_reference_policy(policy)
    if policy_violations:
        raise DerivationError(
            "derived-reference policy validation failed (before any source data access): "
            + "; ".join(policy_violations)
        )

    records = parse_assembly_report(assembly_report)
    selected: dict[str, AssemblyReportRecord] = {}
    category_of: dict[str, str] = {}
    chrom_name_of: dict[str, str] = {}
    excluded_records: list[dict] = []
    for record in records:
        category = contig_category(record)
        if category is None:
            continue
        accession = selected_accession(record, policy)
        if accession is None:
            excluded_records.append(
                {
                    "accession": _raw_identifying_accession(record),
                    "category": category,
                    "sequence_name": record.sequence_name,
                    "length": record.sequence_length,
                    "reason": EXCLUSION_REASON_SOURCE_NAMESPACE_UNREPRESENTED,
                }
            )
            continue
        if accession in selected:
            raise DerivationError(f"duplicate accession {accession!r} selected from the assembly report")
        selected[accession] = record
        category_of[accession] = category
        chrom_name_of[accession] = record.sequence_name

    # Deterministic ordering independent of assembly-report encounter order.
    excluded_records.sort(key=lambda r: (r["category"], r["sequence_name"], r["accession"]))
    exclusion_summary = {
        "count": len(excluded_records),
        "total_bases": sum(r["length"] for r in excluded_records),
        "reason_counts": dict(Counter(r["reason"] for r in excluded_records)),
        "category_counts": dict(Counter(r["category"] for r in excluded_records)),
    }
    effective_policy = {
        "include_sequence_roles_primary_assembly": list(policy.include_sequence_roles_primary_assembly),
        "include_non_nuclear_assembled_molecule": policy.include_non_nuclear_assembled_molecule,
        "accession_preference": list(policy.accession_preference),
    }

    seen_counts: Counter = Counter()
    written_lengths: dict[str, int] = {}
    mask_counts = {"upper": 0, "lower": 0, "ambiguous": 0}

    output_fasta = Path(output_fasta)
    output_fasta.parent.mkdir(parents=True, exist_ok=True)
    tmp_fasta = output_fasta.with_name(output_fasta.name + f".tmp{os.getpid()}")
    try:
        with _open_text(Path(source_fasta)) as src, tmp_fasta.open("w") as dst:
            current: str | None = None
            writing = False
            for raw_line in src:
                # B3A-A4: CRLF-safe -- a bare rstrip("\n") would leave a
                # trailing "\r" as part of the last written base of every
                # sequence line (and, on a header line, part of the parsed
                # accession), silently corrupting derived length/base counts
                # for a CRLF-sourced FASTA while never raising. Ordinary LF
                # input is unaffected: rstrip("\r\n") strips nothing extra.
                line = raw_line.rstrip("\r\n")
                if line.startswith(">"):
                    current = line[1:].split()[0]
                    seen_counts[current] += 1
                    writing = current in selected
                    if writing:
                        written_lengths.setdefault(current, 0)
                        dst.write(f">{current}\n")
                    continue
                if writing and current is not None:
                    dst.write(line + "\n")
                    written_lengths[current] += len(line)
                    for ch in line:
                        if ch in "ACGT":
                            mask_counts["upper"] += 1
                        elif ch in "acgt":
                            mask_counts["lower"] += 1
                        else:
                            mask_counts["ambiguous"] += 1

        violations: list[str] = []
        for accession in selected:
            count = seen_counts.get(accession, 0)
            if count != 1:
                violations.append(f"accession {accession!r} occurs {count} time(s) in source FASTA (expected exactly 1)")
        for accession in written_lengths:
            if accession not in selected:
                violations.append(f"unselected accession {accession!r} appeared in the derived FASTA")
        for accession, record in selected.items():
            actual = written_lengths.get(accession, 0)
            if actual != record.sequence_length:
                violations.append(
                    f"{accession}: derived length {actual} != assembly-report length {record.sequence_length}"
                )
        # B3A-A2: contig_lengths must key-match `contigs`/agree with the
        # assembly report/sum to the total emitted base count before this
        # derivation is accepted -- the same "verification violation ->
        # never promote" fail-closed shape as the checks above.
        contig_lengths = {accession: written_lengths.get(accession, 0) for accession in selected}
        total_emitted_bases = mask_counts["upper"] + mask_counts["lower"] + mask_counts["ambiguous"]
        length_violations = validate_contig_lengths(
            contig_lengths,
            contigs=tuple(sorted(selected)),
            assembly_report_lengths={accession: record.sequence_length for accession, record in selected.items()},
            total_emitted_bases=total_emitted_bases,
        )
        # B3B-1 fix: the occurrence/unselected/length `violations` built
        # above were previously never raised (only `length_violations` was),
        # so a duplicated selected accession in the source FASTA could
        # silently promote a candidate despite the check existing. Both
        # violation lists must be aggregated and raised together before any
        # promotion.
        all_violations = list(violations) + list(length_violations)
        if all_violations:
            raise DerivationError("derived-reference verification failed: " + "; ".join(all_violations))
    except BaseException:
        if tmp_fasta.exists():
            tmp_fasta.unlink()
        raise

    os.replace(tmp_fasta, output_fasta)

    contigs = tuple(sorted(selected))
    category_counts = dict(Counter(category_of.values()))

    return ReferenceDerivation(
        output_fasta=output_fasta,
        output_fasta_sha256=sha256_file(output_fasta),
        output_fasta_byte_size=output_fasta.stat().st_size,
        contigs=contigs,
        contig_categories={accession: category_of[accession] for accession in contigs},
        category_counts=category_counts,
        accession_to_assembly_chrom_name={accession: chrom_name_of[accession] for accession in contigs},
        masking={**mask_counts, "status": _masking_status(mask_counts)},
        contig_lengths=contig_lengths,
        effective_policy=effective_policy,
        excluded_records=tuple(excluded_records),
        exclusion_summary=exclusion_summary,
    )


def build_reference_manifest(
    derivation: ReferenceDerivation,
    *,
    build_id: str,
    assembly_accession: str,
    source_url: str,
    source_fasta_compressed: Path,
    source_fasta_compressed_upstream_md5: str,
    assembly_report: Path,
    assembly_report_upstream_md5: str,
    derivation_command: str,
    git_commit: str | None,
) -> dict:
    """Assemble the full reference manifest.

    Satisfies :data:`rbpbench.coordinates.manifest.REQUIRED_REFERENCE_MANIFEST_FIELDS`
    (``build_id``/``assembly_accession``/``source_url``/
    ``contig_categories_included``/``byte_size``/``sha256``) at the top level
    — directly usable as the runner's ``--reference-manifest`` input — plus
    the additional Task 001B fields: source compressed size/SHA-256/upstream
    MD5, assembly-report hash/upstream MD5, derivation command and Git
    commit, the complete contig list, ``contig_categories`` keyed by FASTA
    identifier, an accession-to-assembly-chromosome-name table, masking
    base counts/status, and (B3B-1) the effective derived-reference policy
    plus structured source-namespace-unrepresented exclusion evidence.
    """
    source_fasta_compressed = Path(source_fasta_compressed)
    assembly_report = Path(assembly_report)
    return {
        "schema_version": 3,
        "build_id": build_id,
        "assembly_accession": assembly_accession,
        "source_url": source_url,
        "contig_categories_included": sorted(set(derivation.category_counts)),
        "byte_size": derivation.output_fasta_byte_size,
        "sha256": derivation.output_fasta_sha256,
        "contigs": list(derivation.contigs),
        "contig_categories": dict(derivation.contig_categories),
        "contig_lengths": dict(derivation.contig_lengths),
        "category_counts": dict(derivation.category_counts),
        "accession_to_assembly_chrom_name": dict(derivation.accession_to_assembly_chrom_name),
        "masking": dict(derivation.masking),
        "effective_policy": dict(derivation.effective_policy),
        "excluded_records": [dict(r) for r in derivation.excluded_records],
        "exclusion_summary": dict(derivation.exclusion_summary),
        "source": {
            "fasta_compressed_path": str(source_fasta_compressed),
            "fasta_compressed_byte_size": source_fasta_compressed.stat().st_size
            if source_fasta_compressed.is_file()
            else None,
            "fasta_compressed_sha256": sha256_file(source_fasta_compressed)
            if source_fasta_compressed.is_file()
            else None,
            "fasta_compressed_upstream_md5": source_fasta_compressed_upstream_md5,
            "assembly_report_path": str(assembly_report),
            "assembly_report_sha256": sha256_file(assembly_report) if assembly_report.is_file() else None,
            "assembly_report_upstream_md5": assembly_report_upstream_md5,
        },
        "derivation_command": derivation_command,
        "derivation_git_commit": git_commit,
    }


__all__ = [
    "AssemblyReportRecord",
    "parse_assembly_report",
    "contig_category",
    "selected_accession",
    "DerivationError",
    "ReferenceDerivation",
    "derive_reference_fasta",
    "largest_contig",
    "validate_contig_lengths",
    "current_git_commit",
    "build_reference_manifest",
    "CATEGORY_CHROMOSOME",
    "CATEGORY_MITOCHONDRION",
    "CATEGORY_UNLOCALIZED",
    "CATEGORY_UNPLACED",
    "EXCLUSION_REASON_SOURCE_NAMESPACE_UNREPRESENTED",
]
