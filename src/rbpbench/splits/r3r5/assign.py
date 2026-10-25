"""E5: deterministic whole-component assignment on components v2.

Reuses the accepted label-aware assignment (:mod:`rbpbench.splits.
assignment`) unchanged.  Labels are aggregated only after component
membership is frozen; they can never create, merge or split a component.
Every component's label-count dictionary is built in ascending protein-ID
order before any floating-point objective evaluation, so the reordered
repeat cannot reach a different rounding tie through dictionary order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from rbpbench.splits import audit as splits_audit
from rbpbench.splits import ingestion
from rbpbench.splits.assignment import ComponentLabelCounts, PartitionAssignment, assign_partitions
from rbpbench.splits.r3r5.contract import PARTITIONS, Contract
from rbpbench.splits.r3r5.stops import IntegrityStop, ScientificStop


def aggregate_component_labels(csv_path: Path, membership: Mapping[str, str], contract: Contract) -> list[ComponentLabelCounts]:
    sizes: dict[str, int] = {}
    for cid in membership.values():
        sizes[cid] = sizes.get(cid, 0) + 1
    universe = ingestion.ComponentUniverse(sample_to_component=dict(membership), component_sizes=sizes)
    a = contract.assignment
    aggregates = ingestion.stream_component_label_aggregates(
        csv_path, universe, protein_id_min=a.protein_id_min, protein_id_max=a.protein_id_max
    )
    components = []
    for cid in sorted(aggregates):
        aggregate = aggregates[cid]
        ordered = {pid: (aggregate.label_counts[pid][0], aggregate.label_counts[pid][1]) for pid in sorted(aggregate.label_counts)}
        components.append(ComponentLabelCounts(component_id=cid, size=aggregate.size, label_counts=ordered))
    return components


def assert_fixed_protein_order(components: Sequence[ComponentLabelCounts]) -> None:
    for component in components:
        keys = list(component.label_counts)
        if keys != sorted(keys):
            raise IntegrityStop(f"component {component.component_id} label counts are not in fixed protein order")


def run_assignment(components: Sequence[ComponentLabelCounts], contract: Contract) -> PartitionAssignment:
    assert_fixed_protein_order(components)
    a = contract.assignment
    return assign_partitions(
        list(components),
        seed=contract.seed,
        evaluation_floor=a.evaluation_floor,
        max_repair_passes=a.max_repair_passes,
        max_repair_proposals=a.max_repair_proposals,
        row_fraction_repair_limit_pct=a.row_fraction_repair_limit_pct,
        row_dimension_weight=a.row_dimension_weight,
        protein_class_dimension_weight=a.protein_class_dimension_weight,
        balance_deviation_flag_pct=a.balance_deviation_flag_pct,
        protein_ids=list(range(a.protein_id_min, a.protein_id_max + 1)),
    )


def reordered(components: Sequence[ComponentLabelCounts]) -> list[ComponentLabelCounts]:
    """Deterministic alternative input order for the independent repeat."""
    return sorted(components, key=lambda c: (c.component_id[::-1], c.component_id), reverse=True)


def membership_rows(membership: Mapping[str, str], assignment: PartitionAssignment) -> list[tuple[str, str, str]]:
    return sorted((sid, cid, assignment.component_to_partition[cid]) for sid, cid in membership.items())


def scientific_summary(membership: Mapping[str, str], assignment: PartitionAssignment, contract: Contract) -> dict:
    a = contract.assignment
    total = sum(assignment.partition_row_counts.values())
    fractions = a.fractions()
    balance = splits_audit.balance_report(assignment.partition_row_counts, fractions, total,
                                          flag_threshold_pct=a.balance_deviation_flag_pct)
    per_protein = splits_audit.per_protein_balance_report(assignment.partition_label_counts, fractions,
                                                          flag_threshold_pct=a.balance_deviation_flag_pct)
    minimum = splits_audit.minimum_count_check(assignment.partition_label_counts, floor=a.evaluation_floor)
    deviations = {p: abs(assignment.partition_row_counts.get(p, 0) / total - fractions[p]) * 100 for p in PARTITIONS}
    return {
        "total_rows": total,
        "component_count": len(set(membership.values())),
        "partition_row_counts": {p: assignment.partition_row_counts.get(p, 0) for p in PARTITIONS},
        "row_fraction_deviation_pp": deviations,
        "partition_label_counts": {
            p: {str(pid): list(counts) for pid, counts in sorted(per.items())}
            for p, per in assignment.partition_label_counts.items()
        },
        "balance_report": balance,
        "per_protein_balance_report": {str(pid): v for pid, v in sorted(per_protein.items())},
        "minimum_count_report": minimum,
        "repair_step_count": len(assignment.repair_steps),
        "repair_steps": list(assignment.repair_steps),
    }


def enforce_acceptance(membership: Mapping[str, str], assignment: PartitionAssignment, summary: dict, contract: Contract) -> None:
    universe = set(contract.universe())
    if set(membership) != universe:
        raise IntegrityStop("assignment membership does not cover exactly the canonical universe")
    partitions = set(assignment.component_to_partition.values())
    if not partitions <= set(PARTITIONS):
        raise IntegrityStop(f"assignment produced unknown partitions {sorted(partitions - set(PARTITIONS))}")
    if set(assignment.component_to_partition) != set(membership.values()):
        raise IntegrityStop("assignment does not map exactly the frozen v2 components")
    for p, deviation in summary["row_fraction_deviation_pp"].items():
        if deviation > contract.assignment.row_fraction_acceptance_pct:
            raise ScientificStop(f"{p} row fraction deviates {deviation:.3f} pp (> {contract.assignment.row_fraction_acceptance_pct})")
    if not summary["minimum_count_report"]["passed"]:
        raise ScientificStop("evaluation floors are not met", details={"violations": summary["minimum_count_report"]["violations"]})
    expected = set(range(contract.assignment.protein_id_min, contract.assignment.protein_id_max + 1))
    for partition in ("validation", "test"):
        seen = {int(pid) for pid in summary["partition_label_counts"].get(partition, {})}
        if seen != expected:
            raise ScientificStop(f"{partition} does not report every protein in the frozen universe")


__all__ = [
    "aggregate_component_labels", "assert_fixed_protein_order", "run_assignment", "reordered",
    "membership_rows", "scientific_summary", "enforce_acceptance",
]
