"""SAM parsing, collinear-block construction, and mapping classification.

Scope note: these 500-nt windows are single-end queries, so there is no
paired-end insert logic here. Coverage and identity are always computed from
CIGAR/NM alignment operations, never from MAPQ; MAPQ and alignment score (AS)
are retained as reported diagnostics and as best-candidate selection/tie-break
evidence, never as classification-threshold inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from rbpbench.coordinates.reference import intron_junction_motif, is_canonical_junction

ReferenceLookup = Callable[[str, int, int], str]

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
    as_score: int | None = None

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
    def is_primary(self) -> bool:
        return not (self.is_secondary or self.is_supplementary)

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
    as_score = None
    for tag in fields[11:]:
        if tag.startswith("NM:i:"):
            nm = int(tag[len("NM:i:") :])
        elif tag.startswith("AS:i:"):
            as_score = int(tag[len("AS:i:") :])
    return AlignmentRecord(
        query_name=query_name,
        flag=flag,
        chrom=rname,
        pos0=int(pos_s) - 1,
        mapq=int(mapq_s),
        cigar=cigar,
        nm=nm,
        as_score=as_score,
    )


def _per_op_match_mismatch(ops: Sequence[tuple[int, str]], nm: int | None) -> list[tuple[int, int]]:
    """Per-op (matches, mismatches) counts, aligned by index with ``ops``.

    Extended CIGAR ('=' and 'X') is used directly when present. Otherwise
    (plain 'M', the common BWA-MEM case) a bare 'M' op does not itself
    distinguish matches from mismatches, so the record's NM edit distance
    (mismatches + inserted + deleted bases, per the SAM spec) is distributed
    across the 'M' ops by base count. For the common single-M-op record this
    reduces to an exact computation; the proportional split is an
    approximation only for the rare multi-block plain-CIGAR record.
    """
    has_extended = any(op in ("=", "X") for _, op in ops)
    result = [(0, 0)] * len(ops)
    if has_extended:
        for index, (length, op) in enumerate(ops):
            if op == "=":
                result[index] = (length, 0)
            elif op == "X":
                result[index] = (0, length)
        return result

    total_m = sum(length for length, op in ops if op == "M")
    total_i = sum(length for length, op in ops if op == "I")
    total_d = sum(length for length, op in ops if op == "D")
    edit_distance = nm if nm is not None else 0
    mismatches_total = min(max(edit_distance - total_i - total_d, 0), total_m)

    consumed = 0
    assigned = 0
    for index, (length, op) in enumerate(ops):
        if op != "M":
            continue
        consumed += length
        target = round(consumed * mismatches_total / total_m) if total_m else 0
        op_mismatches = target - assigned
        assigned = target
        result[index] = (length - op_mismatches, op_mismatches)
    return result


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
    insertions: int
    deletions: int
    mapq: int
    as_score: int | None
    is_primary: bool
    record_id: int
    # Length of the 'N' CIGAR op immediately preceding this block within the
    # *same originating record* (None for a record's first block, or when the
    # predecessor came from a different record entirely, e.g. a
    # supplementary alignment merged in only by build_candidate_loci's
    # collinearity grouping). This is the only evidence build_candidate_loci
    # is allowed to treat as a real intron: two supplementary blocks that
    # happen to be collinear are not spliced evidence by themselves.
    intron_length_before: int | None = None


def blocks_from_record(record: AlignmentRecord) -> list[AlignedBlock]:
    """Split one record's CIGAR into blocks at intron ('N') boundaries.

    Query coordinates are normalized into original-template (forward-read)
    orientation: a '-' strand record's own CIGAR is reported in
    reverse-complement order per the SAM spec, so its leading clip
    corresponds to the *end* of the original template.
    """
    ops = cigar_ops(record.cigar)
    per_op = _per_op_match_mismatch(ops, record.nm)
    total_len = sum(n for n, op in ops if op in _TEMPLATE_LENGTH_OPS)
    record_id = id(record)

    blocks: list[AlignedBlock] = []
    ref_pos = record.pos0
    read_pos = 0  # position within this record's own (possibly rev-comp) CIGAR
    block_ref_start: int | None = None
    block_read_start = 0
    block_aligned = 0
    block_matches = 0
    block_mismatches = 0
    block_insertions = 0
    block_deletions = 0
    block_intron_before: int | None = None
    pending_intron_length: int | None = None

    def flush(read_end: int, ref_end: int) -> None:
        nonlocal block_ref_start, block_aligned, block_matches, block_mismatches
        nonlocal block_insertions, block_deletions, block_intron_before
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
                insertions=block_insertions,
                deletions=block_deletions,
                mapq=record.mapq,
                as_score=record.as_score,
                is_primary=record.is_primary,
                record_id=record_id,
                intron_length_before=block_intron_before,
            )
        )
        block_ref_start = None
        block_aligned = 0
        block_matches = 0
        block_mismatches = 0
        block_insertions = 0
        block_deletions = 0
        block_intron_before = None

    for index, (length, op) in enumerate(ops):
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
            pending_intron_length = length
            continue
        if block_ref_start is None:
            block_ref_start = ref_pos
            block_read_start = read_pos
            if pending_intron_length is not None:
                block_intron_before = pending_intron_length
                pending_intron_length = None
        if op in ("M", "=", "X"):
            matches, mismatches = per_op[index]
            block_aligned += length
            block_matches += matches
            block_mismatches += mismatches
            ref_pos += length
            read_pos += length
        elif op == "I":
            block_aligned += length
            block_insertions += length
            read_pos += length
        elif op == "D":
            block_deletions += length
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
    mapq: int
    as_score: int | None
    is_primary: bool
    # Real intron evidence only: lengths of 'N' CIGAR gaps between two blocks
    # that came from the *same* originating alignment record, in genomic
    # order. A locus assembled from several collinear but N-free records
    # (e.g. two supplementary alignments) has an empty tuple here even
    # though it has multiple blocks.
    intron_lengths: tuple[int, ...] = ()
    # Parallel to intron_lengths: True/False when a reference lookup was
    # supplied and the junction's donor/acceptor dinucleotides were checked,
    # None when no reference sequence was available to check against.
    junction_is_canonical: tuple[bool | None, ...] = ()

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def has_intron(self) -> bool:
        """True only when at least one block boundary is real 'N' evidence.

        Multiple blocks alone (e.g. a primary plus a collinear supplementary
        record, neither containing an 'N' op) are not splice evidence; see
        ``intron_lengths``.
        """
        return len(self.intron_lengths) > 0


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


def _trimmed_contribution(prev_end: int, block: AlignedBlock) -> tuple[int, int, int, int, int]:
    """Scale down a block's summed contribution by its query-space overlap
    with the previous block in the group, so two collinear records (e.g. a
    primary plus its supplementary) that redundantly cover the same few query
    bases within the collinearity tolerance are not double-counted.
    """
    span = block.template_query_end - block.template_query_start
    overlap = min(max(0, prev_end - block.template_query_start), span)
    if overlap == 0:
        return (
            block.aligned_query_bases,
            block.matches,
            block.mismatches,
            block.insertions,
            block.deletions,
        )
    if span == 0:
        return 0, 0, 0, 0, 0
    fraction = (span - overlap) / span
    return (
        round(block.aligned_query_bases * fraction),
        round(block.matches * fraction),
        round(block.mismatches * fraction),
        round(block.insertions * fraction),
        round(block.deletions * fraction),
    )


def _intron_evidence(
    group: Sequence[AlignedBlock], reference_lookup: ReferenceLookup | None
) -> tuple[tuple[int, ...], tuple[bool | None, ...]]:
    """Real intron gaps in a locus's blocks, in genomic order.

    A gap only counts when both sides came from the *same* originating SAM
    record and the later one recorded an 'N'-op length immediately before it
    (see ``AlignedBlock.intron_length_before``); collinear blocks merged from
    two different records (e.g. a primary plus an unrelated supplementary
    alignment, neither containing 'N') never contribute an entry here. Genomic
    order is used for adjacency (not template/query order) because it matches
    the CIGAR's own left-to-right reference traversal regardless of strand.
    """
    genomic_ordered = sorted(group, key=lambda b: b.ref_start)
    intron_lengths: list[int] = []
    canonical: list[bool | None] = []
    for prev, cur in zip(genomic_ordered, genomic_ordered[1:]):
        if cur.record_id != prev.record_id or cur.intron_length_before is None:
            continue
        intron_lengths.append(cur.intron_length_before)
        if reference_lookup is None:
            canonical.append(None)
        else:
            donor, acceptor = intron_junction_motif(
                reference_lookup, prev.chrom, prev.ref_end, cur.ref_start, prev.strand
            )
            canonical.append(is_canonical_junction(donor, acceptor))
    return tuple(intron_lengths), tuple(canonical)


def build_candidate_loci(
    records: Iterable[AlignmentRecord],
    total_query_bases: int,
    *,
    reference_lookup: ReferenceLookup | None = None,
) -> list[CandidateLocus]:
    """Combine all alignment records for one query into candidate loci.

    Supplementary/secondary records sharing a chromosome and strand are
    collapsed into a single candidate only when their blocks are collinear;
    overlapping query bases between merged blocks are counted once. Loci are
    ranked with primary/alignment-score (AS) evidence first and coverage/
    identity only as a tie-break, per the parent task's requirement that the
    best candidate not be chosen from coverage alone.

    ``reference_lookup``, when supplied, is a ``(chrom, start, end) -> bases``
    callable (see :mod:`rbpbench.coordinates.reference`) used to check each
    real intron's donor/acceptor motif; omitted, canonical-junction status is
    reported as unknown (``None``) rather than guessed.
    """
    all_blocks: list[AlignedBlock] = []
    for record in records:
        all_blocks.extend(blocks_from_record(record))

    loci: list[CandidateLocus] = []
    for group in group_collinear_blocks(all_blocks):
        ordered = sorted(group, key=lambda b: b.template_query_start)
        aligned = matches = mismatches = insertions = deletions = 0
        prev_end: int | None = None
        for block in ordered:
            if prev_end is None:
                a, m, mm, ins, dele = (
                    block.aligned_query_bases,
                    block.matches,
                    block.mismatches,
                    block.insertions,
                    block.deletions,
                )
            else:
                a, m, mm, ins, dele = _trimmed_contribution(prev_end, block)
            aligned += a
            matches += m
            mismatches += mm
            insertions += ins
            deletions += dele
            prev_end = block.template_query_end if prev_end is None else max(prev_end, block.template_query_end)

        denom = matches + mismatches + insertions + deletions
        identity = matches / denom if denom else 0.0
        coverage = aligned / total_query_bases if total_query_bases else 0.0
        as_scores = [b.as_score for b in group if b.as_score is not None]
        intron_lengths, junction_is_canonical = _intron_evidence(group, reference_lookup)
        loci.append(
            CandidateLocus(
                chrom=group[0].chrom,
                strand=group[0].strand,
                blocks=tuple(ordered),
                coverage=coverage,
                identity=identity,
                aligned_query_bases=aligned,
                total_query_bases=total_query_bases,
                mapq=max(b.mapq for b in group),
                as_score=max(as_scores) if as_scores else None,
                is_primary=any(b.is_primary for b in group),
                intron_lengths=intron_lengths,
                junction_is_canonical=junction_is_canonical,
            )
        )
    loci.sort(
        key=lambda locus: (
            locus.is_primary,
            locus.as_score if locus.as_score is not None else float("-inf"),
            locus.coverage,
            locus.identity,
        ),
        reverse=True,
    )
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


def has_plausible_distinct_secondary(
    best: CandidateLocus, candidates: Sequence[CandidateLocus], thresholds: ClassificationThresholds
) -> bool:
    """Whether any of ``candidates`` is a plausible distinct secondary locus
    relative to ``best``. Shared by ``classify_primary``/``classify_splice``
    and by callers that need the same "is this locus actually unambiguous"
    evidence outside classification itself (e.g. deciding whether a BWA-MEM
    perfect locus is a genuine exact-uniqueness *candidate*, not merely the
    best of several perfect loci — see
    ``rbpbench.coordinates.runner.build_mapping_rows``).
    """
    return any(_is_plausible_distinct_secondary(best, candidate, thresholds) for candidate in candidates)


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
    if has_plausible_distinct_secondary(best, loci[1:], thresholds):
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
    has_secondary = has_plausible_distinct_secondary(best, loci[1:], thresholds)
    spliced = best.has_intron
    if spliced:
        return "spliced_ambiguous" if has_secondary else "spliced_unique"
    return "unspliced_ambiguous" if has_secondary else "unspliced_unique"


def is_usable_unique(primary_category: str, splice_category: str | None) -> bool:
    """Gate rule: usable unique = primary exact/high-conf, or splice rescue only otherwise."""
    if primary_category in ("exact_unique", "high_conf_unique"):
        return True
    return splice_category == "spliced_unique"


def near_tied_secondary_fractions(
    loci: Sequence[CandidateLocus], fractions: Sequence[float]
) -> dict[float, bool]:
    """Tool-specific, diagnostic-only sensitivity output (parent task R5).

    For each configured fraction, report whether any secondary locus's
    alignment score (AS) is within that fraction of the best locus's AS.
    Never used as a classification criterion and never compared across
    mapping tools, since AS is not on a shared scale between them.
    """
    if len(loci) < 2 or loci[0].as_score is None:
        return {fraction: False for fraction in fractions}
    best_as = loci[0].as_score
    result: dict[float, bool] = {}
    for fraction in fractions:
        threshold = best_as * (1 - fraction)
        result[fraction] = any(
            locus.as_score is not None and locus.as_score >= threshold for locus in loci[1:]
        )
    return result
