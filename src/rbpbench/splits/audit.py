"""Component-size, balance, minimum-count, and cross-partition audit
helpers.

Every gate here reports a diagnostic composition alongside its pass/fail
verdict, and every deviation is disclosed rather than silently repaired
(``docs/tasks/002_sequence_clustered_partitions.md``, "Checkpoints" and
"Acceptance gate").
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

GIANT_SINGLE_COMPONENT_FRACTION = 0.05
GIANT_TOP20_FRACTION = 0.20
TOP20_COUNT = 20
BALANCE_DEVIATION_FLAG_PCT = 3.0
EVALUATION_FLOOR = 30


def giant_component_gate(component_sizes: Mapping[str, int], total_rows: int) -> dict:
    """5%/20% giant-component gate: a single component holding more than 5%
    of all rows, or the top 20 components together holding more than 20%,
    trips the gate -- reported WITH diagnostic composition (which
    components, their sizes/fractions), never a bare stop.
    """
    if total_rows <= 0:
        raise ValueError("total_rows must be positive")
    ranked = sorted(component_sizes.items(), key=lambda kv: (-kv[1], kv[0]))
    largest_id, largest_size = ranked[0] if ranked else (None, 0)
    largest_fraction = largest_size / total_rows
    top20 = ranked[:TOP20_COUNT]
    top20_fraction = sum(size for _, size in top20) / total_rows
    return {
        "single_component_gate_tripped": largest_fraction > GIANT_SINGLE_COMPONENT_FRACTION,
        "top20_gate_tripped": top20_fraction > GIANT_TOP20_FRACTION,
        "largest_component_id": largest_id,
        "largest_component_size": largest_size,
        "largest_component_fraction": largest_fraction,
        "top20_component_fraction": top20_fraction,
        "top20_components": [
            {"component_id": cid, "size": size, "fraction": size / total_rows} for cid, size in top20
        ],
    }


def balance_report(
    partition_row_counts: Mapping[str, int], target_fractions: Mapping[str, float], total_rows: int
) -> dict:
    """Achieved vs. target partition row-count fraction, flagging any
    deviation over :data:`BALANCE_DEVIATION_FLAG_PCT` percentage points.
    """
    report = {}
    for partition, target in target_fractions.items():
        achieved = partition_row_counts.get(partition, 0) / total_rows if total_rows else 0.0
        deviation_pct = (achieved - target) * 100
        report[partition] = {
            "target_fraction": target,
            "achieved_fraction": achieved,
            "deviation_percentage_points": deviation_pct,
            "flagged": abs(deviation_pct) > BALANCE_DEVIATION_FLAG_PCT,
        }
    return report


def per_protein_balance_report(
    partition_label_counts: Mapping[str, Mapping[int, tuple[int, int]]], target_fractions: Mapping[str, float]
) -> dict:
    """Per-protein, per-class (known-positive/known-negative) achieved vs.
    target fraction across partitions, flagging >3-percentage-point
    deviations at protein-class granularity (same rule as
    :func:`balance_report`, applied per protein/class instead of totals).
    """
    protein_ids = sorted({pid for counts in partition_label_counts.values() for pid in counts})
    report: dict[int, dict] = {}
    for protein_id in protein_ids:
        total_pos = sum(partition_label_counts[p].get(protein_id, (0, 0))[0] for p in partition_label_counts)
        total_neg = sum(partition_label_counts[p].get(protein_id, (0, 0))[1] for p in partition_label_counts)
        per_partition = {}
        for partition, target in target_fractions.items():
            pos, neg = partition_label_counts.get(partition, {}).get(protein_id, (0, 0))
            entry = {}
            for cls, count, total in (
                ("known_positive", pos, total_pos),
                ("known_negative", neg, total_neg),
            ):
                achieved = count / total if total else 0.0
                deviation_pct = (achieved - target) * 100
                entry[cls] = {
                    "count": count,
                    "achieved_fraction": achieved,
                    "target_fraction": target,
                    "deviation_percentage_points": deviation_pct,
                    "flagged": bool(total) and abs(deviation_pct) > BALANCE_DEVIATION_FLAG_PCT,
                }
            per_partition[partition] = entry
        report[protein_id] = per_partition
    return report


def minimum_count_check(
    partition_label_counts: Mapping[str, Mapping[int, tuple[int, int]]],
    *,
    evaluation_partitions: Sequence[str] = ("validation", "test"),
    floor: int = EVALUATION_FLOOR,
) -> dict:
    """Every protein must retain at least ``floor`` known positives AND
    ``floor`` known negatives in every evaluation partition (validation and
    test by default). A viability floor, not a precision guarantee: proteins
    within 2x the floor are separately flagged as ``near_floor`` for later
    confidence-interval treatment, never silently repaired by moving rows
    across a frozen component boundary.
    """
    protein_ids = sorted({pid for counts in partition_label_counts.values() for pid in counts})
    violations = []
    near_floor = []
    for partition in evaluation_partitions:
        counts = partition_label_counts.get(partition, {})
        for protein_id in protein_ids:
            pos, neg = counts.get(protein_id, (0, 0))
            for cls, value in (("known_positive", pos), ("known_negative", neg)):
                if value < floor:
                    violations.append(
                        {"partition": partition, "protein_id": protein_id, "class": cls, "count": value, "floor": floor}
                    )
                elif value < floor * 2:
                    near_floor.append(
                        {"partition": partition, "protein_id": protein_id, "class": cls, "count": value, "floor": floor}
                    )
    return {"floor": floor, "passed": len(violations) == 0, "violations": violations, "near_floor_flagged": near_floor}


class ForeignAuditEndpointError(ValueError):
    """A closed-universe cross-partition audit edge named a sample ID absent
    from the assignment mapping. The final audit universe is the complete,
    fixed 361,180-row dataset, so an unrecognized endpoint is evidence
    corruption (a decode/ID bug, a stale assignment, or a corrupted audit
    input) -- never a legitimately wider sample universe to silently skip
    past (docs/reviews/002a_sequence_partition_pipeline_review.md).
    """


def cross_partition_violations(
    sample_to_partition: Mapping[str, str], edges: Iterable[tuple[str, str]]
) -> list[dict]:
    """Any edge (an exact/reverse-complement canonical-hash duplicate, or a
    fresh independent audit-search hit) whose two endpoints landed in
    different partitions is a hard failure. Returns the qualifying
    violations (empty when none).

    The audit universe is CLOSED: an edge endpoint absent from
    ``sample_to_partition`` raises :class:`ForeignAuditEndpointError`
    (naming both the edge and which endpoint(s) are foreign) rather than
    being silently skipped -- for the final closed 361,180-row audit, an
    endpoint outside the assignment mapping can only mean corrupted
    evidence, not a wider legitimate universe.
    """
    violations = []
    for a, b in edges:
        partition_a = sample_to_partition.get(a)
        partition_b = sample_to_partition.get(b)
        foreign = [sample_id for sample_id, partition in ((a, partition_a), (b, partition_b)) if partition is None]
        if foreign:
            raise ForeignAuditEndpointError(
                f"audit edge ({a!r}, {b!r}) references sample ID(s) absent from the assignment "
                f"mapping (foreign endpoint(s): {foreign})"
            )
        if partition_a != partition_b:
            violations.append({"sample_a": a, "sample_b": b, "partition_a": partition_a, "partition_b": partition_b})
    return violations


__all__ = [
    "GIANT_SINGLE_COMPONENT_FRACTION",
    "GIANT_TOP20_FRACTION",
    "BALANCE_DEVIATION_FLAG_PCT",
    "EVALUATION_FLOOR",
    "giant_component_gate",
    "balance_report",
    "per_protein_balance_report",
    "minimum_count_check",
    "ForeignAuditEndpointError",
    "cross_partition_violations",
]
