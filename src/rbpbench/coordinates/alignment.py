"""SAM parsing, collinear-block construction, and mapping classification.

Scope note: these 500-nt windows are single-end queries, so there is no
paired-end insert logic here. Coverage and identity are always computed from
CIGAR/NM alignment operations, never from MAPQ; MAPQ is retained purely as a
reported diagnostic per the parent task's contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

FLAG_REVERSE = 0x10
FLAG_SECONDARY = 0x100
FLAG_UNMAPPED = 0x4
FLAG_SUPPLEMENTARY = 0x800

_TEMPLATE_LENGTH_OPS = frozenset("MIS=XH")
_ALIGNED_QUERY_OPS = frozenset("MI=X")
_REF_CONSUMING_OPS = frozenset("MDN=X")
_CLIP_OPS = frozenset("SH")

PRIMARY_CATEGORIES = (
    "exact_unique",
    "high_conf_unique",
    "ambiguous",
    "low_quality",
    "unmapped",
)
SPLICE_CATEGORIES = (
    "spliced_unique",
    "spliced_ambiguous",
    "unspliced_unique",
    "unspliced_ambiguous",
    "low_quality",
    "unmapped",
)


def cigar_ops(cigar: str) -> list[tuple[int, str]]:
    if cigar in ("", "*"):
        return []
    ops: list[tuple[int, str]] = []
    number = ""
    for char in cigar:
        if char.isdigit():
            number += char
        else:
            if not number:
                raise ValueError(f"malformed CIGAR string: {cigar!r}")
            ops.append((int(number), char))
            number = ""
    if number:
        raise ValueError(f"malformed CIGAR string: {cigar!r}")
    return ops


@dataclass(frozen=True)
class AlignmentRecord:
    """One parsed SAM line (a header line or an unmapped record parses to None)."""

    query_name: str
    flag: int
    chrom: str
    pos0: int  # 0-based leftmost reference position
    mapq: int
    cigar: str
    nm: int | None

    @property
    def is_reverse(self) -> bool:
        return bool(self.flag & FLAG_REVERSE)

    @property
    def is_secondary(self) -> bool:
        return bool(self.flag & FLAG_SECONDARY)

    @property
    def is_supplementary(self) -> bool:
        return bool(self.flag & FLAG_SUPPLEMENTARY)

    @property
    def is_unmapped(self) -> bool:
        return bool(self.flag & FLAG_UNMAPPED)

    @property
    def strand(self) -> str:
        return "-" if self.is_reverse else "+"


def parse_sam_line(line: str) -> AlignmentRecord | None:
    """Parse one SAM record line. Header lines and unmapped reads yield None."""
    if not line or line.startswith("@"):
        return None
    fields = line.rstrip("\n").split("\t")
    if len(fields) < 11:
        raise ValueError(f"SAM line has fewer than 11 mandatory fields: {line!r}")
    query_name, flag_s, rname, pos_s, mapq_s, cigar = fields[:6]
    flag = int(flag_s)
    if flag & FLAG_UNMAPPED or rname == "*" or cigar == "*":
        return None
    nm = None
    for tag in fields[11:]:
        if tag.startswith("NM:i:"):
            nm = int(tag[len("NM:i:") :])
            break
    return AlignmentRecord(
        query_name=query_name,
        flag=flag,
        chrom=rname,
        pos0=int(pos_s) - 1,
        mapq=int(mapq_s),
        cigar=cigar,
        nm=nm,
    )


@dataclass(frozen=True)
class AlignmentStats:
    coverage: float
    identity: float
    aligned_query_bases: int
    total_query_bases: int


def compute_alignment_stats(cigar: str, nm: int | None) -> AlignmentStats:
    """Coverage/identity from CIGAR ops (using extended =/X when present, else M+NM)."""
    ops = cigar_ops(cigar)
    total_query = sum(n for n, op in ops if op in _TEMPLATE_LENGTH_OPS)
    aligned_query = sum(n for n, op in ops if op in _ALIGNED_QUERY_OPS)
    extended_matches = sum(n for n, op in ops if op == "=")
    extended_mismatches = sum(n for n, op in ops if op == "X")

    if extended_matches or extended_mismatches:
        denom = extended_matches + extended_mismatches
        identity = extended_matches / denom if denom else 0.0
    else:
        m_len = sum(n for n, op in ops if op == "M")
        indel = sum(n for n, op in ops if op in ("I", "D"))
        edit_distance = nm if nm is not None else 0
        estimated_mismatches = max(edit_distance - indel, 0)
        matches = max(m_len - estimated_mismatches, 0)
        identity = matches / m_len if m_len else 0.0

    coverage = aligned_query / total_query if total_query else 0.0
    return AlignmentStats(
        coverage=coverage,
        identity=identity,
        aligned_query_bases=aligned_query,
        total_query_bases=total_query,
    )


@dataclass(frozen=True)
class AlignedBlock:
    """One contiguous aligned segment (a spliced record yields several)."""

    chrom: str
    strand: str
    ref_start: int
    ref_end: int
    template_query_start: int
    template_query_end: int
    aligned_query_bases: int
    matches: int
    mismatches: int


def blocks_from_record(record: AlignmentRecord) -> list[AlignedBlock]:
    """Split one record's CIGAR into blocks at intron ('N') boundaries.

    Query coordinates are normalized into original-template (forward-read)
    orientation: a '-' strand record's own CIGAR is reported in
    reverse-complement order per the SAM spec, so its leading clip
    corresponds to the *end* of the original template.
    """
    ops = cigar_ops(record.cigar)
    total_len = sum(n for n, op in ops if op in _TEMPLATE_LENGTH_OPS)

    blocks: list[AlignedBlock] = []
    ref_pos = record.pos0
    read_pos = 0  # position within this record's own (possibly rev-comp) CIGAR
    block_ref_start: int | None = None
    block_read_start = 0
    block_aligned = 0
    block_matches = 0
    block_mismatches = 0

    def flush(read_end: int, ref_end: int) -> None:
        nonlocal block_ref_start, block_aligned, block_matches, block_mismatches
        if block_ref_start is None:
            return
        if record.strand == "+":
            t_start, t_end = block_read_start, read_end
        else:
            t_start, t_end = total_len - read_end, total_len - block_read_start
        blocks.append(
            AlignedBlock(
                chrom=record.chrom,
                strand=record.strand,
                ref_start=block_ref_start,
                ref_end=ref_end,
                template_query_start=t_start,
                template_query_end=t_end,
                aligned_query_bases=block_aligned,
                matches=block_matches,
                mismatches=block_mismatches,
            )
        )
        block_ref_start = None
        block_aligned = 0
        block_matches = 0
        block_mismatches = 0

    for length, op in ops:
        if op in _CLIP_OPS:
            # Clips are only legal at CIGAR boundaries, so any open block ends
            # here. Both S and H advance the conceptual query axis (H is
            # simply the part of it absent from this record's own SEQ), which
            # keeps template coordinates correct when a hard-clipped
            # supplementary record is later reconciled against its siblings.
            flush(read_pos, ref_pos)
            read_pos += length
            continue
        if op == "N":
            flush(read_pos, ref_pos)
            ref_pos += length
            block_read_start = read_pos
            continue
        if block_ref_start is None:
            block_ref_start = ref_pos
            block_read_start = read_pos
        if op in ("M", "=", "X"):
            block_aligned += length
            if op == "=":
                block_matches += length
            elif op == "X":
                block_mismatches += length
            ref_pos += length
            read_pos += length
        elif op == "I":
            block_aligned += length
            read_pos += length
        elif op == "D":
            ref_pos += length
        else:
            raise ValueError(f"unsupported CIGAR operation {op!r}")

    flush(read_pos, ref_pos)
    return blocks


@dataclass(frozen=True)
class CandidateLocus:
    chrom: str
    strand: str
    blocks: tuple[AlignedBlock, ...]
    coverage: float
    identity: float
    aligned_query_bases: int
    total_query_bases: int

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def has_intron(self) -> bool:
        return len(self.blocks) >= 2


_MAX_QUERY_OVERLAP = 5
_MAX_REF_OVERLAP = 5


def _blocks_collinear(prev: AlignedBlock, block: AlignedBlock) -> bool:
    if block.template_query_start < prev.template_query_end - _MAX_QUERY_OVERLAP:
        return False
    if prev.strand == "+":
        return block.ref_start >= prev.ref_end - _MAX_REF_OVERLAP
    return block.ref_end <= prev.ref_start + _MAX_REF_OVERLAP


def group_collinear_blocks(blocks: Sequence[AlignedBlock]) -> list[list[AlignedBlock]]:
    """Group same-(chrom, strand) blocks into collinear runs, in query order."""
    by_locus: dict[tuple[str, str], list[AlignedBlock]] = {}
    for block in blocks:
        by_locus.setdefault((block.chrom, block.strand), []).append(block)

    groups: list[list[AlignedBlock]] = []
    for locus_blocks in by_locus.values():
        ordered = sorted(locus_blocks, key=lambda b: b.template_query_start)
        current: list[AlignedBlock] = []
        for block in ordered:
            if current and not _blocks_collinear(current[-1], block):
                groups.append(current)
                current = []
            current.append(block)
        if current:
            groups.append(current)
    return groups


def build_candidate_loci(records: Iterable[AlignmentRecord], total_query_bases: int) -> list[CandidateLocus]:
    """Combine all alignment records for one query into candidate loci.

    Supplementary/secondary records sharing a chromosome and strand are
    collapsed into a single candidate only when their blocks are collinear.
    """
    all_blocks: list[AlignedBlock] = []
    for record in records:
        all_blocks.extend(blocks_from_record(record))

    loci: list[CandidateLocus] = []
    for group in group_collinear_blocks(all_blocks):
        aligned = sum(b.aligned_query_bases for b in group)
        matches = sum(b.matches for b in group)
        mismatches = sum(b.mismatches for b in group)
        denom = matches + mismatches
        identity = matches / denom if denom else 0.0
        coverage = aligned / total_query_bases if total_query_bases else 0.0
        loci.append(
            CandidateLocus(
                chrom=group[0].chrom,
                strand=group[0].strand,
                blocks=tuple(sorted(group, key=lambda b: b.template_query_start)),
                coverage=coverage,
                identity=identity,
                aligned_query_bases=aligned,
                total_query_bases=total_query_bases,
            )
        )
    loci.sort(key=lambda locus: (locus.coverage, locus.identity), reverse=True)
    return loci


@dataclass(frozen=True)
class ClassificationThresholds:
    high_conf_min_coverage: float
    high_conf_min_identity: float
    secondary_min_coverage: float
    secondary_min_identity: float


def _is_plausible_distinct_secondary(
    best: CandidateLocus, candidate: CandidateLocus, thresholds: ClassificationThresholds
) -> bool:
    if candidate.chrom == best.chrom and candidate.strand == best.strand and candidate.blocks == best.blocks:
        return False
    return (
        candidate.coverage >= thresholds.secondary_min_coverage
        and candidate.identity >= thresholds.secondary_min_identity
    )


def classify_primary(
    loci: Sequence[CandidateLocus],
    thresholds: ClassificationThresholds,
    *,
    exact_confirmed: bool,
) -> str:
    """Classify a primary contiguous-mode mapping into exactly one terminal category."""
    if not loci:
        return "unmapped"
    best = loci[0]
    meets_high_conf = best.coverage >= thresholds.high_conf_min_coverage and best.identity >= thresholds.high_conf_min_identity
    if not meets_high_conf:
        return "low_quality"
    has_plausible_secondary = any(_is_plausible_distinct_secondary(best, c, thresholds) for c in loci[1:])
    if has_plausible_secondary:
        return "ambiguous"
    if best.coverage == 1.0 and best.identity == 1.0 and exact_confirmed:
        return "exact_unique"
    return "high_conf_unique"


def classify_splice(loci: Sequence[CandidateLocus], thresholds: ClassificationThresholds) -> str:
    """Classify a splice-aware diagnostic mapping. Never yields ``exact_unique``."""
    if not loci:
        return "unmapped"
    best = loci[0]
    meets_high_conf = best.coverage >= thresholds.high_conf_min_coverage and best.identity >= thresholds.high_conf_min_identity
    if not meets_high_conf:
        return "low_quality"
    has_plausible_secondary = any(_is_plausible_distinct_secondary(best, c, thresholds) for c in loci[1:])
    spliced = best.has_intron
    if spliced:
        return "spliced_ambiguous" if has_plausible_secondary else "spliced_unique"
    return "unspliced_ambiguous" if has_plausible_secondary else "unspliced_unique"


def is_usable_unique(primary_category: str, splice_category: str | None) -> bool:
    """Gate rule: usable unique = primary exact/high-conf, or splice rescue only otherwise."""
    if primary_category in ("exact_unique", "high_conf_unique"):
        return True
    return splice_category == "spliced_unique"
