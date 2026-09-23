"""Streaming, deterministic assembly-report/FASTA derivation.

Implements the frozen contig policy from
``docs/tasks/001b_coordinate_feasibility_execution.md``: include
``assembled-molecule``/``unlocalized-scaffold``/``unplaced-scaffold`` from
the ``Primary Assembly`` unit, plus the mitochondrial ``assembled-molecule``
from the ``non-nuclear`` unit; exclude everything else (alternate loci,
patches, decoys, separately packaged HLA contigs). The source accession
(RefSeq when present, else GenBank) is preserved as the FASTA identifier —
never a convenience alias.

Both the assembly-report parse and the FASTA filter are single sequential
passes: neither loads a multi-gigabyte reference into memory, so this scales
to a real hg38/hg19 source FASTA. B1 exercises this only against tiny
synthetic fixtures mirroring NCBI's real column layout.
"""

from __future__ import annotations

import gzip
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import IO

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
            line = raw_line.rstrip("\n")
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


def selected_accession(record: AssemblyReportRecord) -> str:
    """RefSeq accession when present and not the NCBI ``na`` sentinel, else GenBank."""
    refseq = record.refseq_accession.strip()
    if refseq and refseq.lower() != "na":
        return refseq
    return record.genbank_accession.strip()


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
) -> ReferenceDerivation:
    """Stream ``source_fasta`` (plain or ``.gz``) once, writing only the
    accessions selected by :func:`contig_category`/:func:`selected_accession`
    to ``output_fasta`` in source-encounter order (so repeated derivation
    over unchanged inputs is byte-for-byte reproducible), and verify:

    1. every selected accession occurs exactly once in the source;
    2. no unselected accession appears in the derived FASTA;
    3. every derived sequence length equals the assembly-report length.

    Never loads the source FASTA whole: one line is held at a time. Writes to
    an attempt-specific temporary file and only atomically promotes it onto
    ``output_fasta`` after every verification check passes (B1-R7): a failed
    derivation (a verification violation, or any exception mid-stream) must
    never destroy a prior valid ``output_fasta`` left over from an earlier
    successful derivation.
    """
    records = parse_assembly_report(assembly_report)
    selected: dict[str, AssemblyReportRecord] = {}
    category_of: dict[str, str] = {}
    chrom_name_of: dict[str, str] = {}
    for record in records:
        category = contig_category(record)
        if category is None:
            continue
        accession = selected_accession(record)
        if not accession:
            raise DerivationError(f"assembly-report record {record.sequence_name!r} has no usable accession")
        if accession in selected:
            raise DerivationError(f"duplicate accession {accession!r} selected from the assembly report")
        selected[accession] = record
        category_of[accession] = category
        chrom_name_of[accession] = record.sequence_name

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
                line = raw_line.rstrip("\n")
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
        if violations:
            raise DerivationError("derived-reference verification failed: " + "; ".join(violations))
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
    )


def current_git_commit(*, cwd: Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False, cwd=cwd
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


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
    identifier, an accession-to-assembly-chromosome-name table, and masking
    base counts/status.
    """
    source_fasta_compressed = Path(source_fasta_compressed)
    assembly_report = Path(assembly_report)
    return {
        "schema_version": 2,
        "build_id": build_id,
        "assembly_accession": assembly_accession,
        "source_url": source_url,
        "contig_categories_included": sorted(set(derivation.category_counts)),
        "byte_size": derivation.output_fasta_byte_size,
        "sha256": derivation.output_fasta_sha256,
        "contigs": list(derivation.contigs),
        "contig_categories": dict(derivation.contig_categories),
        "category_counts": dict(derivation.category_counts),
        "accession_to_assembly_chrom_name": dict(derivation.accession_to_assembly_chrom_name),
        "masking": dict(derivation.masking),
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
    "current_git_commit",
    "build_reference_manifest",
    "CATEGORY_CHROMOSOME",
    "CATEGORY_MITOCHONDRION",
    "CATEGORY_UNLOCALIZED",
    "CATEGORY_UNPLACED",
]
