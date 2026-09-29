"""Deterministic whole-component 70/15/15 train/validation/test assignment.

Grouping is entirely label-blind (see :mod:`rbpbench.splits.components`);
only AFTER components are frozen may known positive/known-negative label
counts be used, and only to balance whole, already-fixed components across
partitions -- never to split or redefine one
(``docs/tasks/002_sequence_clustered_partitions.md``, "Scientific
boundary"). A component is always assigned in full; nothing here ever moves
individual members between partitions.

Task 002C correction (``docs/tasks/002c_partition_assignment_and_audit.md``,
"Frozen assignment contract"; ``docs/reviews/002c_partition_assignment_reconciliation.md``):
a real-data feasibility pass showed the original raw-absolute-row-deficit
objective lets a component's much larger row count dominate its much
smaller per-protein/class deficits, producing near-exact row totals but
failing several 30-known-positive/30-known-negative validation/test
floors. The objective below instead normalizes every dimension by that
partition's own target count and gives the single row-count dimension the
same AGGREGATE weight as all 244 protein/class dimensions combined, so
neither can silently dominate the other; a deterministic bounded
whole-component repair then closes any remaining evaluation-floor
violation without ever splitting a component.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from rbpbench.coordinates.hashing import stable_hash_rank
from rbpbench.splits import audit as splits_audit

PARTITIONS: tuple[str, ...] = ("train", "validation", "test")
TARGET_FRACTIONS: dict[str, float] = {"train": 0.70, "validation": 0.15, "test": 0.15}
EVALUATION_PARTITIONS: tuple[str, ...] = ("validation", "test")

# The single row-count objective is given the SAME aggregate weight as all
# 244 separate protein/class objectives (122 proteins x {known_positive,
# known_negative}) combined. Task 002C-1 correction
# (docs/reviews/002c1_partition_orchestration_correction_review.md, C1):
# ``configs/splits/sequence_partitions_002c_v1.toml``'s own
# ``assignment.row_dimension_weight``/``protein_class_dimension_weight``
# fields now genuinely DRIVE :func:`assign_partitions` (threaded through as
# real parameters, defaulting to these same frozen constants below) --
# :func:`rbpbench.splits.config_002c.validate_frozen_invariants` is a SECOND,
# independent line of defense that additionally fails closed if a config
# edit ever tried to diverge from them, so this remains, in practice, never
# a silently caller-configurable value.
ROW_DIMENSION_WEIGHT = 244
PROTEIN_CLASS_DIMENSION_WEIGHT = 1
DEFAULT_MAX_REPAIR_PASSES = 5000
# C2: a separate, generous bound on every tested move/swap PROPOSAL
# (accepted or rejected) -- distinct from DEFAULT_MAX_REPAIR_PASSES, which
# bounds only ACCEPTED passes. Exhausting it is a hard, fail-closed stop
# (:class:`AssignmentInfeasibleError`), never a silent early return with a
# remaining violation.
DEFAULT_MAX_REPAIR_PROPOSALS = 2_000_000
DEFAULT_ROW_FRACTION_REPAIR_LIMIT_PCT = 3.0


@dataclass
class _ProposalBudget:
    """Counts every tested whole-component move/swap PROPOSAL (accepted or
    rejected) against a fixed bound, so the deterministic bounded repair can
    never silently perform unbounded work even when a full sweep over many
    candidates never finds an improving move
    (docs/reviews/002c1_partition_orchestration_correction_review.md, C2).
    """

    remaining: int
    exhausted: bool = False

    def consume(self) -> bool:
        if self.remaining <= 0:
            self.exhausted = True
            return False
        self.remaining -= 1
        return True


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
    # Every accepted whole-component move/swap the deterministic bounded
    # repair pass applied, in application order (empty when the initial
    # greedy placement already cleared every evaluation floor).
    repair_steps: tuple[Mapping[str, object], ...] = ()


class AssignmentInfeasibleError(RuntimeError):
    """Deterministic bounded whole-component repair could not clear every
    evaluation-floor violation without splitting a component, lowering
    another evaluation class below the floor, or moving a partition's row
    fraction outside the configured repair limit of its target -- whether
    because the configured pass bound was exhausted or because a full sweep
    found no valid, strictly-improving move or swap. Always a hard stop:
    never silently accepted with a remaining violation, and never a signal
    to split a component or weaken a floor.
    """


def _max_dimension_share(
    component: ComponentLabelCounts, grand_size: int, grand_pos: Mapping[int, int], grand_neg: Mapping[int, int]
) -> float:
    """The component's largest share of any single global dimension: its
    own row-count share of the total, or its share of any protein/class
    total it contributes to. Used only to ORDER components by placement
    difficulty, never to weight the placement objective itself.
    """
    shares = [component.size / grand_size] if grand_size else [0.0]
    for protein_id, (pos, neg) in component.label_counts.items():
        if pos:
            total = grand_pos.get(protein_id, 0)
            if total:
                shares.append(pos / total)
        if neg:
            total = grand_neg.get(protein_id, 0)
            if total:
                shares.append(neg / total)
    return max(shares)


def _ordered_components(
    components: Sequence[ComponentLabelCounts], seed: int, grand_size: int, grand_pos: Mapping[int, int], grand_neg: Mapping[int, int]
) -> list[ComponentLabelCounts]:
    """Frozen difficulty order (docs/tasks/002c_partition_assignment_and_audit.md,
    "Deterministic objective", step 3): decreasing maximum share of any
    global row/protein/class total, then decreasing component size, then a
    frozen seeded-hash tie-break -- so the processing order (and therefore
    the whole assignment) never depends on ``components``' own input order.
    """
    return sorted(
        components,
        key=lambda c: (
            -_max_dimension_share(c, grand_size, grand_pos, grand_neg),
            -c.size,
            stable_hash_rank(seed, "component_order", c.component_id),
        ),
    )


def _partition_delta(
    *,
    running_size: Mapping[str, int],
    running_pos: Mapping[tuple[str, int], int],
    running_neg: Mapping[tuple[str, int], int],
    target_size: Mapping[str, float],
    target_pos: Mapping[tuple[str, int], float],
    target_neg: Mapping[tuple[str, int], float],
    partition: str,
    component: ComponentLabelCounts,
    row_dimension_weight: int = ROW_DIMENSION_WEIGHT,
    protein_class_dimension_weight: int = PROTEIN_CLASS_DIMENSION_WEIGHT,
) -> float:
    """The increase in the normalized squared-deficit objective (only
    ``partition``'s own terms change; every other partition's target counts
    and running counts are unaffected by placing ``component`` here) if
    ``component`` were placed into ``partition`` right now.
    """
    delta = 0.0
    target = target_size[partition]
    if target:
        old = running_size[partition]
        new = old + component.size
        delta += row_dimension_weight * (((new - target) / target) ** 2 - ((old - target) / target) ** 2)
    for protein_id, (pos, neg) in component.label_counts.items():
        if pos:
            target = target_pos[(partition, protein_id)]
            if target:
                old = running_pos.get((partition, protein_id), 0)
                new = old + pos
                delta += protein_class_dimension_weight * (((new - target) / target) ** 2 - ((old - target) / target) ** 2)
        if neg:
            target = target_neg[(partition, protein_id)]
            if target:
                old = running_neg.get((partition, protein_id), 0)
                new = old + neg
                delta += protein_class_dimension_weight * (((new - target) / target) ** 2 - ((old - target) / target) ** 2)
    return delta


def assign_partitions(
    components: Sequence[ComponentLabelCounts],
    *,
    seed: int,
    evaluation_floor: int = splits_audit.EVALUATION_FLOOR,
    max_repair_passes: int = DEFAULT_MAX_REPAIR_PASSES,
    max_repair_proposals: int = DEFAULT_MAX_REPAIR_PROPOSALS,
    row_fraction_repair_limit_pct: float = DEFAULT_ROW_FRACTION_REPAIR_LIMIT_PCT,
    row_dimension_weight: int = ROW_DIMENSION_WEIGHT,
    protein_class_dimension_weight: int = PROTEIN_CLASS_DIMENSION_WEIGHT,
    balance_deviation_flag_pct: float = splits_audit.BALANCE_DEVIATION_FLAG_PCT,
    protein_ids: Sequence[int] | None = None,
) -> PartitionAssignment:
    """Assigns each whole component to whichever partition minimizes the
    increase in a normalized squared-deficit objective (docs/tasks/002c_partition_assignment_and_audit.md,
    "Frozen assignment contract"): every row/protein/class dimension is
    normalized by that partition's own target count for that dimension, so
    an abundant dimension (total rows) can never dominate a rare one (one
    protein's known-negative count) purely because its raw counts are
    larger. The single row dimension carries :data:`ROW_DIMENSION_WEIGHT`
    (244), the same aggregate weight as all 244 separate protein/class
    dimensions combined (each weighted 1). Partition ties break on the
    fixed order :data:`PARTITIONS` (``train``, ``validation``, ``test``).

    If any protein ends up below ``evaluation_floor`` known positives/
    negatives in validation or test, a deterministic bounded whole-component
    repair (:func:`_repair_floor_violations`) then applies a sequence of
    moves/swaps that each strictly improve the lexicographic tuple (total
    floor deficit, violation count, worst row-fraction deviation, count of
    protein/class deviations over ``row_fraction_repair_limit_pct``, total
    normalized squared error) without ever splitting a component, lowering
    another evaluation class below the floor, or moving a partition's row
    fraction outside ``row_fraction_repair_limit_pct`` of its target.
    Raises :class:`AssignmentInfeasibleError` (never silently accepts a
    remaining violation) if the bound is exhausted or no valid improving
    move/swap remains.

    Deterministic: :func:`_ordered_components`'s fixed processing order and
    the fixed partition tie-break together mean re-running -- even with
    ``components`` supplied in a different order -- reproduces the
    identical assignment and repair sequence.

    ``protein_ids`` is the FROZEN protein/class universe to check (the real
    run must pass the complete configured ``1..122`` range, not merely the
    protein IDs actually observed in the input --
    docs/reviews/002c1_partition_orchestration_correction_review.md, C2:
    "Missing totals must cause an explicit infeasibility or frozen-input
    error rather than disappearing from the floor check"). Defaults to the
    protein IDs actually observed in ``components`` only for direct,
    lower-level callers (e.g. unit tests) that never declare a wider
    universe explicitly.
    """
    grand_size = sum(c.size for c in components)
    if protein_ids is None:
        protein_ids = sorted({pid for c in components for pid in c.label_counts})
    else:
        protein_ids = sorted(set(protein_ids))
    grand_pos = {pid: sum(c.label_counts.get(pid, (0, 0))[0] for c in components) for pid in protein_ids}
    grand_neg = {pid: sum(c.label_counts.get(pid, (0, 0))[1] for c in components) for pid in protein_ids}

    ordered = _ordered_components(components, seed, grand_size, grand_pos, grand_neg)

    target_size = {p: TARGET_FRACTIONS[p] * grand_size for p in PARTITIONS}
    target_pos = {(p, pid): TARGET_FRACTIONS[p] * grand_pos[pid] for p in PARTITIONS for pid in protein_ids}
    target_neg = {(p, pid): TARGET_FRACTIONS[p] * grand_neg[pid] for p in PARTITIONS for pid in protein_ids}

    running_size: dict[str, int] = {p: 0 for p in PARTITIONS}
    running_pos: dict[tuple[str, int], int] = {}
    running_neg: dict[tuple[str, int], int] = {}
    component_to_partition: dict[str, str] = {}

    for component in ordered:
        best_partition = PARTITIONS[0]
        best_delta: float | None = None
        for partition in PARTITIONS:
            delta = _partition_delta(
                running_size=running_size, running_pos=running_pos, running_neg=running_neg,
                target_size=target_size, target_pos=target_pos, target_neg=target_neg,
                partition=partition, component=component,
                row_dimension_weight=row_dimension_weight, protein_class_dimension_weight=protein_class_dimension_weight,
            )
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_partition = partition
        component_to_partition[component.component_id] = best_partition
        running_size[best_partition] += component.size
        for protein_id, (pos, neg) in component.label_counts.items():
            if pos:
                running_pos[(best_partition, protein_id)] = running_pos.get((best_partition, protein_id), 0) + pos
            if neg:
                running_neg[(best_partition, protein_id)] = running_neg.get((best_partition, protein_id), 0) + neg

    components_by_id = {c.component_id: c for c in components}
    repair_steps = _repair_floor_violations(
        component_to_partition=component_to_partition,
        components_by_id=components_by_id,
        running_size=running_size,
        running_pos=running_pos,
        running_neg=running_neg,
        protein_ids=protein_ids,
        grand_size=grand_size,
        target_size=target_size,
        target_pos=target_pos,
        target_neg=target_neg,
        evaluation_floor=evaluation_floor,
        row_fraction_repair_limit_pct=row_fraction_repair_limit_pct,
        max_repair_passes=max_repair_passes,
        max_repair_proposals=max_repair_proposals,
        row_dimension_weight=row_dimension_weight,
        protein_class_dimension_weight=protein_class_dimension_weight,
        balance_deviation_flag_pct=balance_deviation_flag_pct,
    )

    partition_label_counts = {
        p: {pid: (running_pos.get((p, pid), 0), running_neg.get((p, pid), 0)) for pid in protein_ids}
        for p in PARTITIONS
    }
    return PartitionAssignment(
        component_to_partition=component_to_partition,
        partition_row_counts=dict(running_size),
        partition_label_counts=partition_label_counts,
        repair_steps=tuple(repair_steps),
    )


# --------------------------------------------------------------------------
# Deterministic bounded whole-component floor repair.
# --------------------------------------------------------------------------


def _partition_label_counts_view(
    running_pos: Mapping[tuple[str, int], int], running_neg: Mapping[tuple[str, int], int], protein_ids: Sequence[int]
) -> dict[str, dict[int, tuple[int, int]]]:
    return {
        p: {pid: (running_pos.get((p, pid), 0), running_neg.get((p, pid), 0)) for pid in protein_ids}
        for p in PARTITIONS
    }


def _floor_violation_set(
    running_pos: Mapping[tuple[str, int], int],
    running_neg: Mapping[tuple[str, int], int],
    protein_ids: Sequence[int],
    evaluation_floor: int,
) -> set[tuple[str, int, str]]:
    violations = set()
    for partition in EVALUATION_PARTITIONS:
        for protein_id in protein_ids:
            if running_pos.get((partition, protein_id), 0) < evaluation_floor:
                violations.add((partition, protein_id, "known_positive"))
            if running_neg.get((partition, protein_id), 0) < evaluation_floor:
                violations.add((partition, protein_id, "known_negative"))
    return violations


def _row_fractions_within_limit(running_size: Mapping[str, int], grand_size: int, limit_pct: float) -> bool:
    if not grand_size:
        return True
    for partition in PARTITIONS:
        achieved = running_size[partition] / grand_size
        deviation_pct = abs((achieved - TARGET_FRACTIONS[partition]) * 100)
        if deviation_pct > limit_pct:
            return False
    return True


def _normalized_squared_error(
    running_size: Mapping[str, int],
    running_pos: Mapping[tuple[str, int], int],
    running_neg: Mapping[tuple[str, int], int],
    protein_ids: Sequence[int],
    target_size: Mapping[str, float],
    target_pos: Mapping[tuple[str, int], float],
    target_neg: Mapping[tuple[str, int], float],
    row_dimension_weight: int = ROW_DIMENSION_WEIGHT,
    protein_class_dimension_weight: int = PROTEIN_CLASS_DIMENSION_WEIGHT,
) -> float:
    total = 0.0
    for partition in PARTITIONS:
        target = target_size[partition]
        if target:
            total += row_dimension_weight * ((running_size[partition] - target) / target) ** 2
    for partition in PARTITIONS:
        for protein_id in protein_ids:
            for running_map, target_map in ((running_pos, target_pos), (running_neg, target_neg)):
                target = target_map[(partition, protein_id)]
                if target:
                    total += protein_class_dimension_weight * ((running_map.get((partition, protein_id), 0) - target) / target) ** 2
    return total


def _lexicographic_tuple(
    *,
    running_size: Mapping[str, int],
    running_pos: Mapping[tuple[str, int], int],
    running_neg: Mapping[tuple[str, int], int],
    protein_ids: Sequence[int],
    grand_size: int,
    target_size: Mapping[str, float],
    target_pos: Mapping[tuple[str, int], float],
    target_neg: Mapping[tuple[str, int], float],
    evaluation_floor: int,
    row_dimension_weight: int = ROW_DIMENSION_WEIGHT,
    protein_class_dimension_weight: int = PROTEIN_CLASS_DIMENSION_WEIGHT,
    balance_deviation_flag_pct: float = splits_audit.BALANCE_DEVIATION_FLAG_PCT,
) -> tuple[int, int, float, int, float]:
    """The repair-acceptance tuple (docs/reviews/002c_partition_assignment_reconciliation.md,
    "Bounded repair must exercise a multi-step feasible case"): total floor
    deficit, number of floor violations, worst absolute row-fraction
    deviation, number of protein/class deviations flagged over
    ``balance_deviation_flag_pct`` percentage points, then total normalized
    squared error. Smaller is always strictly better in ordinary tuple
    comparison. Reuses :mod:`rbpbench.splits.audit`'s own disclosure
    functions so this tuple's "violation"/"flagged" definitions can never
    silently diverge from what the accepted manifest itself discloses.
    """
    partition_label_counts = _partition_label_counts_view(running_pos, running_neg, protein_ids)
    min_count_report = splits_audit.minimum_count_check(
        partition_label_counts, evaluation_partitions=EVALUATION_PARTITIONS, floor=evaluation_floor
    )
    total_floor_deficit = sum(v["floor"] - v["count"] for v in min_count_report["violations"])
    num_floor_violations = len(min_count_report["violations"])

    balance = splits_audit.balance_report(
        dict(running_size), TARGET_FRACTIONS, grand_size, flag_threshold_pct=balance_deviation_flag_pct
    )
    max_abs_row_deviation = max((abs(entry["deviation_percentage_points"]) for entry in balance.values()), default=0.0)

    per_protein = splits_audit.per_protein_balance_report(
        partition_label_counts, TARGET_FRACTIONS, flag_threshold_pct=balance_deviation_flag_pct
    )
    num_over_threshold = sum(
        1
        for protein_entry in per_protein.values()
        for partition_entry in protein_entry.values()
        for class_entry in partition_entry.values()
        if class_entry["flagged"]
    )

    nse = _normalized_squared_error(
        running_size, running_pos, running_neg, protein_ids, target_size, target_pos, target_neg,
        row_dimension_weight=row_dimension_weight, protein_class_dimension_weight=protein_class_dimension_weight,
    )
    return (total_floor_deficit, num_floor_violations, max_abs_row_deviation, num_over_threshold, nse)


def _apply_move(
    component: ComponentLabelCounts,
    from_partition: str,
    to_partition: str,
    running_size: dict[str, int],
    running_pos: dict[tuple[str, int], int],
    running_neg: dict[tuple[str, int], int],
) -> None:
    running_size[from_partition] -= component.size
    running_size[to_partition] += component.size
    for protein_id, (pos, neg) in component.label_counts.items():
        if pos:
            running_pos[(from_partition, protein_id)] = running_pos.get((from_partition, protein_id), 0) - pos
            running_pos[(to_partition, protein_id)] = running_pos.get((to_partition, protein_id), 0) + pos
        if neg:
            running_neg[(from_partition, protein_id)] = running_neg.get((from_partition, protein_id), 0) - neg
            running_neg[(to_partition, protein_id)] = running_neg.get((to_partition, protein_id), 0) + neg


# C2 (docs/reviews/002c1_partition_orchestration_correction_review.md): a
# fixed, deterministic cap on how many outgoing swap partners are considered
# per incoming candidate. The sort key (ascending contribution, then size,
# then ID) always places the "cheapest to give up" members first, so a
# genuinely useful partner is found near the front of this list; capping it
# bounds per-attempt work without an unbounded scan of an entire (possibly
# ~121K-component) partition for every incoming candidate.
_MAX_OUTGOING_SWAP_CANDIDATES = 500


def _build_contributors_index(
    components_by_id: Mapping[str, ComponentLabelCounts],
) -> dict[tuple[int, str], list[str]]:
    """Deterministic inverted index, built ONCE per :func:`assign_partitions`
    call: ``(protein_id, class_label) -> [component_id, ...]`` for every
    component with a POSITIVE contribution to that dimension, ordered
    largest-contribution-first then smallest-size then component ID.

    Replaces scanning every one of the (real-scale: 173,465) components for
    every evaluation-floor violation (docs/reviews/002c1_partition_orchestration_correction_review.md,
    C2, "building deterministic inverted indexes for label-carrying repair
    candidates instead of scanning all components for every violation") with
    one lookup into the small subset of components that actually carry that
    protein/class label at all.
    """
    ranked: dict[tuple[int, str], list[tuple[int, int, str]]] = {}
    for component_id, component in components_by_id.items():
        for protein_id, (pos, neg) in component.label_counts.items():
            if pos:
                ranked.setdefault((protein_id, "known_positive"), []).append((-pos, component.size, component_id))
            if neg:
                ranked.setdefault((protein_id, "known_negative"), []).append((-neg, component.size, component_id))
    return {key: [cid for _, _, cid in sorted(entries)] for key, entries in ranked.items()}


def _candidate_components_for(
    protein_id: int,
    class_label: str,
    exclude_partition: str,
    component_to_partition: Mapping[str, str],
    components_by_id: Mapping[str, ComponentLabelCounts],
    contributors_index: Mapping[tuple[int, str], list[str]] | None = None,
) -> list[ComponentLabelCounts]:
    """Components NOT currently in ``exclude_partition`` with a positive
    contribution to ``(protein_id, class_label)``, ordered deterministically:
    largest contribution first (fixes the most deficit per move), then
    smallest total size (least collateral row-fraction movement), then
    component ID.

    When ``contributors_index`` is supplied (the production repair loop
    always builds one once via :func:`_build_contributors_index`), this is a
    lookup into the precomputed label-carrier list rather than a fresh scan
    of every component; a caller that omits it (e.g. a direct unit-test
    call) gets the identical result computed on the fly.
    """
    idx = 0 if class_label == "known_positive" else 1
    if contributors_index is not None:
        candidate_ids = contributors_index.get((protein_id, class_label), ())
        return [
            components_by_id[component_id]
            for component_id in candidate_ids
            if component_to_partition[component_id] != exclude_partition
        ]
    ranked = []
    for component_id, partition in component_to_partition.items():
        if partition == exclude_partition:
            continue
        component = components_by_id[component_id]
        contribution = component.label_counts.get(protein_id, (0, 0))[idx]
        if contribution > 0:
            ranked.append((-contribution, component.size, component_id))
    ranked.sort()
    return [components_by_id[component_id] for _, _, component_id in ranked]


def _try_single_moves(
    *, ordered_violations, component_to_partition, components_by_id, running_size, running_pos, running_neg,
    protein_ids, grand_size, target_size, target_pos, target_neg, evaluation_floor, row_fraction_repair_limit_pct,
    old_violations, current_tuple, contributors_index=None, proposal_budget=None,
    row_dimension_weight=ROW_DIMENSION_WEIGHT, protein_class_dimension_weight=PROTEIN_CLASS_DIMENSION_WEIGHT,
    balance_deviation_flag_pct=splits_audit.BALANCE_DEVIATION_FLAG_PCT,
):
    for partition, protein_id, class_label in ordered_violations:
        for component in _candidate_components_for(
            protein_id, class_label, partition, component_to_partition, components_by_id, contributors_index
        ):
            if proposal_budget is not None and not proposal_budget.consume():
                return None
            from_partition = component_to_partition[component.component_id]
            _apply_move(component, from_partition, partition, running_size, running_pos, running_neg)
            within_limit = _row_fractions_within_limit(running_size, grand_size, row_fraction_repair_limit_pct)
            new_violations = _floor_violation_set(running_pos, running_neg, protein_ids, evaluation_floor)
            introduced = new_violations - old_violations
            if within_limit and not introduced:
                new_tuple = _lexicographic_tuple(
                    running_size=running_size, running_pos=running_pos, running_neg=running_neg,
                    protein_ids=protein_ids, grand_size=grand_size, target_size=target_size,
                    target_pos=target_pos, target_neg=target_neg, evaluation_floor=evaluation_floor,
                    row_dimension_weight=row_dimension_weight, protein_class_dimension_weight=protein_class_dimension_weight,
                    balance_deviation_flag_pct=balance_deviation_flag_pct,
                )
                if new_tuple < current_tuple:
                    component_to_partition[component.component_id] = partition
                    return {"kind": "move", "component_id": component.component_id, "from": from_partition, "to": partition}
            _apply_move(component, partition, from_partition, running_size, running_pos, running_neg)
    return None


def _try_swaps(
    *, ordered_violations, component_to_partition, components_by_id, running_size, running_pos, running_neg,
    protein_ids, grand_size, target_size, target_pos, target_neg, evaluation_floor, row_fraction_repair_limit_pct,
    old_violations, current_tuple, contributors_index=None, proposal_budget=None,
    row_dimension_weight=ROW_DIMENSION_WEIGHT, protein_class_dimension_weight=PROTEIN_CLASS_DIMENSION_WEIGHT,
    balance_deviation_flag_pct=splits_audit.BALANCE_DEVIATION_FLAG_PCT,
):
    for partition, protein_id, class_label in ordered_violations:
        idx = 0 if class_label == "known_positive" else 1
        incoming_candidates = _candidate_components_for(
            protein_id, class_label, partition, component_to_partition, components_by_id, contributors_index
        )
        for incoming in incoming_candidates:
            source_partition = component_to_partition[incoming.component_id]
            outgoing_candidates = sorted(
                (
                    components_by_id[component_id]
                    for component_id, p in component_to_partition.items()
                    if p == partition and component_id != incoming.component_id
                ),
                key=lambda c: (c.label_counts.get(protein_id, (0, 0))[idx], c.size, c.component_id),
            )[:_MAX_OUTGOING_SWAP_CANDIDATES]
            for outgoing in outgoing_candidates:
                if proposal_budget is not None and not proposal_budget.consume():
                    return None
                _apply_move(incoming, source_partition, partition, running_size, running_pos, running_neg)
                _apply_move(outgoing, partition, source_partition, running_size, running_pos, running_neg)
                within_limit = _row_fractions_within_limit(running_size, grand_size, row_fraction_repair_limit_pct)
                new_violations = _floor_violation_set(running_pos, running_neg, protein_ids, evaluation_floor)
                introduced = new_violations - old_violations
                if within_limit and not introduced:
                    new_tuple = _lexicographic_tuple(
                        running_size=running_size, running_pos=running_pos, running_neg=running_neg,
                        protein_ids=protein_ids, grand_size=grand_size, target_size=target_size,
                        target_pos=target_pos, target_neg=target_neg, evaluation_floor=evaluation_floor,
                        row_dimension_weight=row_dimension_weight, protein_class_dimension_weight=protein_class_dimension_weight,
                        balance_deviation_flag_pct=balance_deviation_flag_pct,
                    )
                    if new_tuple < current_tuple:
                        component_to_partition[incoming.component_id] = partition
                        component_to_partition[outgoing.component_id] = source_partition
                        return {
                            "kind": "swap",
                            "component_in": incoming.component_id,
                            "component_out": outgoing.component_id,
                            "partition_a": source_partition,
                            "partition_b": partition,
                        }
                _apply_move(outgoing, source_partition, partition, running_size, running_pos, running_neg)
                _apply_move(incoming, partition, source_partition, running_size, running_pos, running_neg)
    return None


def _repair_floor_violations(
    *, component_to_partition, components_by_id, running_size, running_pos, running_neg, protein_ids,
    grand_size, target_size, target_pos, target_neg, evaluation_floor, row_fraction_repair_limit_pct, max_repair_passes,
    max_repair_proposals: int = DEFAULT_MAX_REPAIR_PROPOSALS,
    row_dimension_weight: int = ROW_DIMENSION_WEIGHT,
    protein_class_dimension_weight: int = PROTEIN_CLASS_DIMENSION_WEIGHT,
    balance_deviation_flag_pct: float = splits_audit.BALANCE_DEVIATION_FLAG_PCT,
) -> list[dict]:
    """Applies at most ``max_repair_passes`` accepted whole-component
    moves/swaps (one per pass, the first strictly-improving, constraint-
    satisfying operation found in the deterministic search order), each
    recomputed against fresh current state, until zero evaluation-floor
    violations remain. Raises :class:`AssignmentInfeasibleError` -- never
    splits a component or weakens a floor -- if the bound is exhausted or a
    full sweep finds no valid move/swap while a violation remains.

    Builds the label-carrier inverted index (:func:`_build_contributors_index`)
    and the proposal budget (:class:`_ProposalBudget`, counting every TESTED
    move/swap, accepted or not, across the whole repair -- not merely every
    accepted pass) exactly ONCE, up front, so real-scale repair search never
    re-scans the full component universe per violation
    (docs/reviews/002c1_partition_orchestration_correction_review.md, C2).
    """
    repair_steps: list[dict] = []
    if not _floor_violation_set(running_pos, running_neg, protein_ids, evaluation_floor):
        return repair_steps

    contributors_index = _build_contributors_index(components_by_id)
    proposal_budget = _ProposalBudget(remaining=max_repair_proposals)

    for _pass_index in range(max_repair_passes):
        old_violations = _floor_violation_set(running_pos, running_neg, protein_ids, evaluation_floor)
        if not old_violations:
            return repair_steps

        current_tuple = _lexicographic_tuple(
            running_size=running_size, running_pos=running_pos, running_neg=running_neg, protein_ids=protein_ids,
            grand_size=grand_size, target_size=target_size, target_pos=target_pos, target_neg=target_neg,
            evaluation_floor=evaluation_floor, row_dimension_weight=row_dimension_weight,
            protein_class_dimension_weight=protein_class_dimension_weight,
            balance_deviation_flag_pct=balance_deviation_flag_pct,
        )
        ordered_violations = sorted(old_violations)

        shared_kwargs = dict(
            ordered_violations=ordered_violations, component_to_partition=component_to_partition,
            components_by_id=components_by_id, running_size=running_size, running_pos=running_pos,
            running_neg=running_neg, protein_ids=protein_ids, grand_size=grand_size, target_size=target_size,
            target_pos=target_pos, target_neg=target_neg, evaluation_floor=evaluation_floor,
            row_fraction_repair_limit_pct=row_fraction_repair_limit_pct, old_violations=old_violations,
            current_tuple=current_tuple, contributors_index=contributors_index, proposal_budget=proposal_budget,
            row_dimension_weight=row_dimension_weight, protein_class_dimension_weight=protein_class_dimension_weight,
            balance_deviation_flag_pct=balance_deviation_flag_pct,
        )
        accepted = _try_single_moves(**shared_kwargs)
        if accepted is None:
            accepted = _try_swaps(**shared_kwargs)
        if accepted is None:
            if proposal_budget.exhausted:
                raise AssignmentInfeasibleError(
                    f"deterministic bounded repair exhausted its {max_repair_proposals} configured proposal(s) "
                    f"with {len(old_violations)} evaluation-floor violation(s) remaining"
                )
            raise AssignmentInfeasibleError(
                f"deterministic bounded repair found no valid whole-component move or swap that improves the "
                f"remaining {len(old_violations)} evaluation-floor violation(s) without splitting a component, "
                "lowering another evaluation class below the floor, or exceeding the row-fraction repair limit"
            )
        repair_steps.append(accepted)

    remaining = _floor_violation_set(running_pos, running_neg, protein_ids, evaluation_floor)
    if remaining:
        raise AssignmentInfeasibleError(
            f"deterministic bounded repair exhausted its {max_repair_passes} configured pass(es) with "
            f"{len(remaining)} evaluation-floor violation(s) remaining"
        )
    return repair_steps


__all__ = [
    "PARTITIONS",
    "TARGET_FRACTIONS",
    "EVALUATION_PARTITIONS",
    "ROW_DIMENSION_WEIGHT",
    "PROTEIN_CLASS_DIMENSION_WEIGHT",
    "DEFAULT_MAX_REPAIR_PASSES",
    "DEFAULT_MAX_REPAIR_PROPOSALS",
    "DEFAULT_ROW_FRACTION_REPAIR_LIMIT_PCT",
    "ComponentLabelCounts",
    "PartitionAssignment",
    "AssignmentInfeasibleError",
    "assign_partitions",
]
