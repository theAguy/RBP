"""Directed cross-partition MMseqs2 audit-search orchestration primitives.

For every protected width and every unordered partition pair, BOTH ordered
query/target directions are required (18 directed searches total for the
three widths x three unordered pairs;
``docs/reviews/002c_partition_assignment_reconciliation.md``, "Both MMseqs2
search directions are required"). This module holds the pure, directly
testable logic: building a directed pair's per-partition FASTA subsets,
selection-record/fingerprint keys that always include width + direction,
and closed-universe hit reconciliation. Subprocess/generation-directory
orchestration lives in :mod:`rbpbench.splits.runner_002c`, reusing
:mod:`rbpbench.splits.commands` and :mod:`rbpbench.splits.guarded_exec`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

ORDERED_PARTITION_PAIRS: tuple[tuple[str, str], ...] = (
    ("train", "validation"),
    ("validation", "train"),
    ("train", "test"),
    ("test", "train"),
    ("validation", "test"),
    ("test", "validation"),
)


class InvalidDirectionError(ValueError):
    """The query/target partitions are not distinct, or not both selected
    from ``train``/``validation``/``test``.
    """


def validate_direction(query_partition: str, target_partition: str) -> None:
    allowed = ("train", "validation", "test")
    if query_partition not in allowed or target_partition not in allowed:
        raise InvalidDirectionError(
            f"query/target partitions must both be one of {allowed}; got "
            f"({query_partition!r}, {target_partition!r})"
        )
    if query_partition == target_partition:
        raise InvalidDirectionError(
            f"query and target partitions must be distinct; both were {query_partition!r}"
        )


def selection_key(stage: str, width: int, query_partition: str, target_partition: str) -> str:
    """Every audit-search selection-record key and restart fingerprint
    includes width, query partition, and target partition
    (docs/handoffs/002c1_partition_orchestration_claude_handoff.md, item 1):
    e.g. ``audit_search_500_train_to_validation`` and
    ``audit_search_500_validation_to_train`` are independent requirements.

    ``audit_probe`` is WIDTH-scoped only (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md,
    F1) -- use :func:`probe_selection_key` for it instead.
    """
    validate_direction(query_partition, target_partition)
    return f"{stage}_{width}_{query_partition}_to_{target_partition}"


def probe_selection_key(width: int) -> str:
    """The ``audit_probe`` selection-record key: exactly one deterministic
    bounded resource probe per protected width (F1) -- e.g.
    ``audit_probe_500``, never direction-scoped like ``audit_search``.
    """
    return f"audit_probe_{width}"


def build_partition_fasta_subset(
    sequences_by_id: Mapping[str, str], sample_to_partition: Mapping[str, str], partition: str
) -> dict[str, str]:
    """The subset of ``sequences_by_id`` whose sample ID is assigned to
    ``partition`` in the frozen assignment.
    """
    return {
        sample_id: sequence
        for sample_id, sequence in sequences_by_id.items()
        if sample_to_partition.get(sample_id) == partition
    }


def parse_search_hits(path: Path) -> list[tuple[str, str]]:
    """Parses ``mmseqs createtsv`` audit-search output
    (``query<TAB>target`` rows) into ``(query_id, target_id)`` pairs.
    A malformed line (not at least two tab-separated columns) is a hard
    failure, never a silent skip.
    """
    hits: list[tuple[str, str]] = []
    with Path(path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                raise ValueError(f"malformed audit-search hit line (expected >=2 tab columns): {line!r}")
            hits.append((parts[0], parts[1]))
    return hits


class ForeignAuditSearchEndpointError(ValueError):
    """A parsed audit-search hit named an endpoint outside its
    direction-specific closed query/target universe.
    """


class SelfHitCorruptionError(ValueError):
    """A hit's query and target sample ID were identical. The two
    partition universes for a real directed search are disjoint by
    construction, so this can only mean corrupted evidence (a decode/
    assignment/generation bug) -- never an ordinary same-database self-hit
    to discard
    (``docs/tasks/002c_partition_assignment_and_audit.md``, "Fresh
    directed MMseqs2 audit orchestration").
    """


@dataclass(frozen=True)
class DirectedAuditResult:
    width: int
    query_partition: str
    target_partition: str
    hit_count: int
    violations: tuple[dict, ...]
    passed: bool

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "query_partition": self.query_partition,
            "target_partition": self.target_partition,
            "hit_count": self.hit_count,
            "violations": list(self.violations),
            "passed": self.passed,
        }


def reconcile_directed_hits(
    hits: Sequence[tuple[str, str]],
    *,
    width: int,
    query_partition: str,
    target_partition: str,
    query_universe: Sequence[str],
    target_universe: Sequence[str],
    allow_self_hit_removal_test_only: bool = False,
) -> DirectedAuditResult:
    """Reconciles parsed hits against the closed, direction-specific query
    and target universes. Every hit whose endpoints both resolve inside
    their own universe is a qualifying cross-partition violation (the two
    universes are disjoint by construction for a real directed search, so
    ANY surviving hit is one). A same-ID query/target pair raises
    :class:`SelfHitCorruptionError` unless
    ``allow_self_hit_removal_test_only`` is explicitly set -- reserved for a
    same-database parser fixture, never a production cross-partition
    invocation.
    """
    validate_direction(query_partition, target_partition)
    query_set = set(query_universe)
    target_set = set(target_universe)

    violations = []
    for query_id, target_id in hits:
        if query_id == target_id:
            if allow_self_hit_removal_test_only:
                continue
            raise SelfHitCorruptionError(
                f"audit-search hit ({query_id!r}, {target_id!r}) has an identical query/target ID; the "
                f"{query_partition!r}->{target_partition!r} universes are disjoint by construction, so this is "
                "evidence corruption, never an ordinary self-hit"
            )
        if query_id not in query_set:
            raise ForeignAuditSearchEndpointError(
                f"hit query ID {query_id!r} is outside the closed {query_partition!r} query universe "
                f"(width {width}, {query_partition!r}->{target_partition!r})"
            )
        if target_id not in target_set:
            raise ForeignAuditSearchEndpointError(
                f"hit target ID {target_id!r} is outside the closed {target_partition!r} target universe "
                f"(width {width}, {query_partition!r}->{target_partition!r})"
            )
        violations.append({"query_id": query_id, "target_id": target_id})

    return DirectedAuditResult(
        width=width,
        query_partition=query_partition,
        target_partition=target_partition,
        hit_count=len(hits),
        violations=tuple(violations),
        passed=len(violations) == 0,
    )


__all__ = [
    "ORDERED_PARTITION_PAIRS",
    "InvalidDirectionError",
    "validate_direction",
    "selection_key",
    "probe_selection_key",
    "build_partition_fasta_subset",
    "parse_search_hits",
    "ForeignAuditSearchEndpointError",
    "SelfHitCorruptionError",
    "DirectedAuditResult",
    "reconcile_directed_hits",
]
