"""SeqKit exact-occurrence parsing and the exact-uniqueness agreement rule.

``exact_unique`` must never be claimed from the primary mapper alone: the
parent task requires independent confirmation that SeqKit's FM-index exact
substring search also finds exactly one genomic occurrence, searched on both
strands.

``seqkit locate`` already searches both strands of the reference in a single
invocation and labels each hit's strand in its BED output, so one call per
query set (see :func:`rbpbench.coordinates.commands.seqkit_locate_command`)
is both necessary and sufficient. There is deliberately no "merge forward and
reverse-complemented query results" helper here: invoking SeqKit a second
time against a reverse-complemented query set would re-report every genuine
occurrence a second time under the mirrored strand label, turning one real
genomic occurrence into two strand-distinct ones.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable


def parse_seqkit_bed(lines: Iterable[str]) -> dict[str, set[tuple[str, int, int, str]]]:
    """Parse SeqKit ``locate --bed`` output into occurrences per sample ID.

    Expected columns (tab-separated, no header): chrom, start, end, name,
    score, strand, where ``name`` carries the query's canonical sample ID.
    Returns a mapping of sample_id -> set of distinct (chrom, start, end,
    strand) occurrences, already de-duplicated.
    """
    occurrences: dict[str, set[tuple[str, int, int, str]]] = defaultdict(set)
    for line in lines:
        line = line.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) < 6:
            raise ValueError(f"expected >=6 BED columns, got {len(fields)}: {line!r}")
        chrom, start_s, end_s, name, _score, strand = fields[:6]
        occurrences[name].add((chrom, int(start_s), int(end_s), strand))
    return occurrences


def exact_occurrence_count(occurrences: dict[str, set], sample_id: str) -> int:
    return len(occurrences.get(sample_id, ()))


def exact_unique_confirmed(*, primary_is_perfect_unique: bool, occurrence_count: int) -> bool:
    """``exact_unique`` requires agreement between the primary mapper and SeqKit."""
    return primary_is_perfect_unique and occurrence_count == 1
