"""Independent exact/reverse-complement cross-partition audit.

Regenerates each protected width's canonical exact/RC duplicate grouping
via :mod:`rbpbench.splits.hashing` (pure Python, independent of the
MMseqs2 clustering/audit workflow) and reconciles it against the frozen
partition assignment using :mod:`rbpbench.splits.audit`'s already-tested
closed-universe violation check
(``docs/tasks/002c_partition_assignment_and_audit.md``, "Independent
exact/reverse-complement audit"). The retained report contains IDs,
hashes, counts, denominators, and rates only -- never a sequence or label
value.
"""

from __future__ import annotations

from typing import Mapping

from rbpbench.splits import audit as splits_audit
from rbpbench.splits.hashing import duplicate_edges, group_by_canonical_hash


class ExactAuditUniverseError(ValueError):
    """The regenerated width's sequence universe does not exactly match the
    frozen partition assignment's sample-ID universe -- a decode/assignment
    mismatch, never a silently narrower or wider audit universe.
    """


def audit_width(sequences_by_id: Mapping[str, str], sample_to_partition: Mapping[str, str]) -> dict:
    """Independently regenerates canonical exact/RC duplicate groups for one
    width's ``sequences_by_id`` and reports every cross-partition group as a
    violation. Reconciles the complete ID universe FIRST (fail-closed on any
    missing/foreign ID) before ever computing a hash group.

    Reports the raw violating-PAIR count/rate (``violation_count``/
    ``violation_rate_over_rows``, kept for backward compatibility -- an edge
    count divided by total rows, NOT itself a row rate) alongside a
    SEPARATE, genuine affected-ROW count/rate (``affected_row_count``/
    ``affected_row_rate_over_rows``, the distinct sample IDs appearing in
    any violating pair, over total rows) -- docs/reviews/002c1_partition_orchestration_correction_review.md,
    C3: "Do not label an edge-count divided by total rows as a row rate."
    """
    foreign = sorted(set(sequences_by_id) - set(sample_to_partition))
    missing = sorted(set(sample_to_partition) - set(sequences_by_id))
    if foreign or missing:
        problems = []
        if missing:
            problems.append(f"missing {len(missing)} expected ID(s): {missing[:5]}")
        if foreign:
            problems.append(f"contains {len(foreign)} foreign ID(s): {foreign[:5]}")
        raise ExactAuditUniverseError("exact/RC audit universe reconciliation failed: " + "; ".join(problems))

    groups = group_by_canonical_hash(sequences_by_id)
    duplicate_sizes = [len(ids) for ids in groups.values() if len(ids) > 1]
    edges = duplicate_edges(sequences_by_id)
    # cross_partition_violations independently re-raises on any foreign edge
    # endpoint; the universe reconciliation above already ruled that out for
    # the CURRENT sequences_by_id, so this call only ever surfaces ordinary
    # violations here.
    violations = splits_audit.cross_partition_violations(sample_to_partition, edges)
    affected_rows = {sample_id for v in violations for sample_id in (v["sample_a"], v["sample_b"])}

    total_rows = len(sequences_by_id)
    return {
        "total_rows": total_rows,
        "duplicate_group_count": len(duplicate_sizes),
        "max_duplicate_group_size": max(duplicate_sizes) if duplicate_sizes else 0,
        "violation_count": len(violations),
        "violations": violations,
        "violation_rate_over_rows": (len(violations) / total_rows) if total_rows else 0.0,
        "affected_row_count": len(affected_rows),
        "affected_row_rate_over_rows": (len(affected_rows) / total_rows) if total_rows else 0.0,
        "passed": len(violations) == 0,
    }


def audit_all_widths(
    sequences_by_id_by_width: Mapping[int, Mapping[str, str]], sample_to_partition: Mapping[str, str]
) -> dict:
    per_width = {
        str(width): audit_width(sequences_by_id, sample_to_partition)
        for width, sequences_by_id in sequences_by_id_by_width.items()
    }
    return {"widths": per_width, "passed": all(report["passed"] for report in per_width.values())}


__all__ = ["ExactAuditUniverseError", "audit_width", "audit_all_widths"]
