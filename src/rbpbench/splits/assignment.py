"""Deterministic whole-component 70/15/15 train/validation/test assignment.

Grouping is entirely label-blind (see :mod:`rbpbench.splits.components`);
only AFTER components are frozen may known positive/known-negative label
counts be used, and only to balance whole, already-fixed components across
partitions -- never to split or redefine one
(``docs/tasks/002_sequence_clustered_partitions.md``, "Scientific
boundary"). A component is always assigned in full; nothing here ever moves
individual members between partitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from rbpbench.coordinates.hashing import stable_hash_rank

PARTITIONS: tuple[str, ...] = ("train", "validation", "test")
TARGET_FRACTIONS: dict[str, float] = {"train": 0.70, "validation": 0.15, "test": 0.15}


@dataclass(frozen=True)
class ComponentLabelCounts:
    component_id: str
    size: int
    # protein_id -> (known_positive_count, known_negative_count); a protein
    # absent from this mapping has zero known positives/negatives in this
    # component (unknown labels never enter these counts).
    label_counts: Mapping[int, tuple[int, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class PartitionAssignment:
    component_to_partition: Mapping[str, str]
    partition_row_counts: Mapping[str, int]
    partition_label_counts: Mapping[str, Mapping[int, tuple[int, int]]]


def _ordered_components(components: Sequence[ComponentLabelCounts], seed: int) -> list[ComponentLabelCounts]:
    """Largest components first (hardest to place well without overshooting
    a target), with a seeded-hash tie-break among equal sizes -- so the
    processing order (and therefore the whole assignment) is fully
    deterministic and never depends on ``components``' own input order.
    """
    return sorted(
        components,
        key=lambda c: (-c.size, stable_hash_rank(seed, "component_order", c.component_id)),
    )


def assign_partitions(components: Sequence[ComponentLabelCounts], *, seed: int) -> PartitionAssignment:
    """Greedily assigns each whole component to whichever partition is
    currently furthest below its 70/15/15 target -- combining the total-row
    dimension with every known protein-label dimension the component
    carries, each weighted equally in absolute-count terms, so a
    component's raw size and its rare-protein label counts both pull
    assignment toward whichever partition needs them most.

    Deterministic: components are visited in :func:`_ordered_components`'s
    fixed order, and partition ties break on a fixed ``PARTITIONS`` order,
    so re-running -- even with ``components`` supplied in a different order
    -- reproduces the identical assignment.
    """
    ordered = _ordered_components(components, seed)

    grand_size = sum(c.size for c in components)
    protein_ids = sorted({pid for c in components for pid in c.label_counts})
    grand_pos = {pid: sum(c.label_counts.get(pid, (0, 0))[0] for c in components) for pid in protein_ids}
    grand_neg = {pid: sum(c.label_counts.get(pid, (0, 0))[1] for c in components) for pid in protein_ids}

    target_size = {p: TARGET_FRACTIONS[p] * grand_size for p in PARTITIONS}
    target_pos = {(p, pid): TARGET_FRACTIONS[p] * grand_pos[pid] for p in PARTITIONS for pid in protein_ids}
    target_neg = {(p, pid): TARGET_FRACTIONS[p] * grand_neg[pid] for p in PARTITIONS for pid in protein_ids}

    running_size: dict[str, int] = {p: 0 for p in PARTITIONS}
    running_pos: dict[tuple[str, int], int] = {}
    running_neg: dict[tuple[str, int], int] = {}
    component_to_partition: dict[str, str] = {}

    for component in ordered:
        best_partition = PARTITIONS[0]
        best_score: tuple[float, int] | None = None
        for rank, partition in enumerate(PARTITIONS):
            deficit = target_size[partition] - running_size[partition]
            for protein_id, (pos, neg) in component.label_counts.items():
                if pos:
                    deficit += target_pos[(partition, protein_id)] - running_pos.get((partition, protein_id), 0)
                if neg:
                    deficit += target_neg[(partition, protein_id)] - running_neg.get((partition, protein_id), 0)
            score = (deficit, -rank)
            if best_score is None or score > best_score:
                best_score = score
                best_partition = partition
        component_to_partition[component.component_id] = best_partition
        running_size[best_partition] += component.size
        for protein_id, (pos, neg) in component.label_counts.items():
            if pos:
                running_pos[(best_partition, protein_id)] = running_pos.get((best_partition, protein_id), 0) + pos
            if neg:
                running_neg[(best_partition, protein_id)] = running_neg.get((best_partition, protein_id), 0) + neg

    partition_label_counts = {
        p: {pid: (running_pos.get((p, pid), 0), running_neg.get((p, pid), 0)) for pid in protein_ids}
        for p in PARTITIONS
    }
    return PartitionAssignment(
        component_to_partition=component_to_partition,
        partition_row_counts=running_size,
        partition_label_counts=partition_label_counts,
    )


__all__ = [
    "PARTITIONS",
    "TARGET_FRACTIONS",
    "ComponentLabelCounts",
    "PartitionAssignment",
    "assign_partitions",
]
