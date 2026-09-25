"""Cluster-membership parsing with complete/unique ID reconciliation.

Parses ``mmseqs createtsv`` output (``representative<TAB>member`` rows) into
a membership mapping, and reconciles it against the exact expected universe
of sample IDs: a missing, duplicated, or foreign ID is always a hard
failure, never silently dropped or ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


class MembershipReconciliationError(ValueError):
    """A cluster TSV's member IDs do not exactly match the expected
    universe, or the same member ID appears more than once."""


def parse_cluster_tsv_lines(lines: Iterable[str]) -> dict[str, str]:
    """Parses ``representative<TAB>member`` lines into
    ``{member_id: representative_id}``.

    Every member ID must appear on exactly one line: a repeated member
    (even under the same representative -- a corrupted or doubly-generated
    TSV should never be silently trusted) raises
    :class:`MembershipReconciliationError`.
    """
    membership: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise MembershipReconciliationError(f"malformed cluster TSV line (expected 2 columns): {line!r}")
        representative, member = parts
        if member in membership:
            raise MembershipReconciliationError(f"member {member!r} appears more than once in cluster TSV")
        membership[member] = representative
    return membership


def parse_cluster_tsv(path: Path) -> dict[str, str]:
    with Path(path).open() as handle:
        return parse_cluster_tsv_lines(handle)


def reconcile_membership(membership: dict[str, str], expected_ids: Iterable[str]) -> None:
    """Confirms ``membership``'s member-ID set is EXACTLY ``expected_ids``.

    Raises :class:`MembershipReconciliationError` naming every missing
    and/or foreign ID; never silently repairs or ignores a discrepancy.
    """
    expected = set(expected_ids)
    actual = set(membership.keys())
    missing = expected - actual
    foreign = actual - expected
    problems = []
    if missing:
        problems.append(f"missing {len(missing)} expected ID(s): {sorted(missing)}")
    if foreign:
        problems.append(f"contains {len(foreign)} foreign ID(s): {sorted(foreign)}")
    if problems:
        raise MembershipReconciliationError("cluster TSV reconciliation failed: " + "; ".join(problems))


def membership_edges(membership: dict[str, str]) -> list[tuple[str, str]]:
    """``(member, representative)`` edges suitable for union-find: unioning
    every member with its own cluster representative transitively unions
    every member of the same cluster together, regardless of how MMseqs2
    itself ordered the TSV.
    """
    return [(member, representative) for member, representative in membership.items()]


__all__ = [
    "MembershipReconciliationError",
    "parse_cluster_tsv_lines",
    "parse_cluster_tsv",
    "reconcile_membership",
    "membership_edges",
]
