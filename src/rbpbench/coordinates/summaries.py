"""Per-build and cross-build report summaries required before Task 001B.

Operates on already-persisted, plain string-valued mapping rows (as read
back from a build's ``mappings.tsv.gz``) and sample metadata, never on
in-memory pipeline state, so the combined-report stage can run as its own
process after every build's ``align``/``exact_match``/``report`` stage and
still see every prior build's results — the same resume-safety requirement
the rest of the runner already follows.

Every table here is a descriptive summary or a gross-failure screen. None of
them compute the Phase 2 recommendation (see ``rbpbench.coordinates.report``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Sequence

from rbpbench.coordinates.alignment import is_usable_unique
from rbpbench.coordinates.sequence_stats import gc_decile, low_complexity_decile
from rbpbench.coordinates.stats import ConfidenceInterval, wilson_confidence_interval

USABLE_PRIMARY_CATEGORIES = frozenset({"exact_unique", "high_conf_unique"})
SPLICE_RESCUE_CATEGORY = "spliced_unique"
SEVERE_RETENTION_FLOOR = 0.50
SEVERE_GAP_POINTS = 0.40


def _is_control(row: dict) -> bool:
    return str(row.get("is_control", "")).strip().lower() in ("true", "1", "yes")


def _float_or_none(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def index_rows_by_sample(rows: Sequence[dict], *, mode: str) -> dict[str, dict]:
    return {row["sample_id"]: row for row in rows if row.get("mode") == mode}


def rate_with_ci(successes: int, total: int) -> dict:
    ci: ConfidenceInterval = wilson_confidence_interval(successes, total)
    return {"successes": successes, "total": total, **ci.to_dict()}


def usable_unique_rate(
    primary_by_id: dict[str, dict],
    splice_by_id: dict[str, dict],
    *,
    sample_ids: Sequence[str],
) -> dict:
    """Usable-unique rate under the primary-plus-splice-rescue definition,
    over exactly the given (non-control) sample IDs — pass the representative
    stratum's IDs for the headline gate.
    """
    total = 0
    usable = 0
    for sample_id in sample_ids:
        primary_row = primary_by_id.get(sample_id)
        if primary_row is None:
            continue
        total += 1
        splice_category = splice_by_id.get(sample_id, {}).get("category")
        if is_usable_unique(primary_row["category"], splice_category):
            usable += 1
    return rate_with_ci(usable, total)


def category_rate(rows_by_id: dict[str, dict], *, sample_ids: Sequence[str], categories: frozenset) -> dict:
    total = 0
    hits = 0
    for sample_id in sample_ids:
        row = rows_by_id.get(sample_id)
        if row is None:
            continue
        total += 1
        if row["category"] in categories:
            hits += 1
    return rate_with_ci(hits, total)


def contiguous_vs_splice_rescued(
    primary_by_id: dict[str, dict], splice_by_id: dict[str, dict], *, sample_ids: Sequence[str]
) -> dict:
    """Partition rows into contiguous-usable, splice-rescued-only, and
    still-unmapped(-or-unusable), per the parent task's optional headline
    diagnostic. Splice rescue only ever applies when the primary mode itself
    is not usable, matching ``is_usable_unique``.
    """
    counts = Counter()
    total = 0
    for sample_id in sample_ids:
        primary_row = primary_by_id.get(sample_id)
        if primary_row is None:
            continue
        total += 1
        primary_category = primary_row["category"]
        splice_category = splice_by_id.get(sample_id, {}).get("category")
        if primary_category in USABLE_PRIMARY_CATEGORIES:
            counts["contiguous_usable"] += 1
        elif splice_category == SPLICE_RESCUE_CATEGORY:
            counts["splice_rescued"] += 1
        else:
            counts["still_unusable"] += 1
    return {"total": total, "counts": dict(counts)}


def quality_distribution(rows_by_id: dict[str, dict], *, field: str) -> dict[int, int]:
    """Decile histogram (0..9, equal-width over [0, 1]) of ``field``
    (``"coverage"`` or ``"identity"``) among rows that actually mapped.
    """
    from rbpbench.coordinates.sequence_stats import decile_index

    histogram: Counter = Counter()
    for row in rows_by_id.values():
        value = _float_or_none(row.get(field))
        if value is None:
            continue
        histogram[decile_index(value, max_value=1.0)] += 1
    return dict(sorted(histogram.items()))


def strand_locus_summary(rows_by_id: dict[str, dict]) -> dict:
    strand_counts: Counter = Counter()
    locus_counts: Counter = Counter()
    for row in rows_by_id.values():
        chrom = row.get("chrom") or ""
        if not chrom:
            continue
        strand_counts[row.get("strand") or "?"] += 1
        locus_counts[(chrom, row.get("start"), row.get("end"), row.get("strand"))] += 1
    rows_per_locus = list(locus_counts.values())
    return {
        "forward_strand": strand_counts.get("+", 0),
        "reverse_strand": strand_counts.get("-", 0),
        "distinct_loci": len(locus_counts),
        "max_rows_per_locus": max(rows_per_locus) if rows_per_locus else 0,
        "mean_rows_per_locus": (sum(rows_per_locus) / len(rows_per_locus)) if rows_per_locus else 0.0,
    }


def near_tied_sensitivity_summary(rows_by_id: dict[str, dict], *, fractions: Sequence[float]) -> dict:
    """Fraction of mapped rows whose secondary is near-tied at each
    configured score-gap fraction (tool-specific diagnostic; see
    ``rbpbench.coordinates.alignment.near_tied_secondary_fractions``).
    """
    total = len(rows_by_id)
    result: dict[str, dict] = {}
    for fraction in fractions:
        key = f"{fraction:g}"
        triggered = sum(
            1
            for row in rows_by_id.values()
            if key in (row.get("near_tied_fractions") or "").split(";")
        )
        result[key] = {"triggered": triggered, "total": total}
    return result


def control_alert(rows_by_id: dict[str, dict], *, usable_categories: frozenset) -> dict:
    """Controls classified usable-unique are never silently discarded: the
    parent task requires flagging them for manual pipeline-misconfiguration
    inspection.
    """
    flagged = sorted(
        sample_id for sample_id, row in rows_by_id.items() if row["category"] in usable_categories
    )
    return {"alert": bool(flagged), "flagged_sample_ids": flagged}


def parse_labels(label_field: str) -> tuple[int, ...]:
    if not label_field:
        return ()
    return tuple(int(v) for v in label_field.split(";") if v != "")


def retention_by_protein_class(
    sample_meta: Sequence[dict],
    primary_by_id: dict[str, dict],
    splice_by_id: dict[str, dict],
) -> dict:
    """Per-protein/class usable-unique retention over label observations
    (a row with labels for several proteins contributes to each), plus the
    overall positive-minus-negative gap and a severe-alert flag per the
    parent task's gross-failure-screen definition.
    """
    per_group: dict[tuple[int, str], list[bool]] = defaultdict(list)
    overall: dict[str, list[bool]] = defaultdict(list)

    for entry in sample_meta:
        sample_id = entry["sample_id"]
        primary_row = primary_by_id.get(sample_id)
        if primary_row is None:
            continue
        splice_category = splice_by_id.get(sample_id, {}).get("category")
        usable = is_usable_unique(primary_row["category"], splice_category)
        for value in parse_labels(entry.get("labels", "")):
            protein = abs(value)
            class_label = "positive" if value > 0 else "negative"
            per_group[(protein, class_label)].append(usable)
            overall[class_label].append(usable)

    groups: dict[str, dict] = {}
    severe_alerts: list[dict] = []
    per_protein_gaps: list[float] = []
    for (protein, class_label), flags in sorted(per_group.items()):
        rate = rate_with_ci(sum(flags), len(flags))
        groups[f"{protein}:{class_label}"] = rate
        if rate["point_estimate"] < SEVERE_RETENTION_FLOOR:
            severe_alerts.append(
                {
                    "protein": protein,
                    "class": class_label,
                    "reason": "retention_below_50pct",
                    "retention": rate["point_estimate"],
                }
            )

    proteins = sorted({protein for protein, _ in per_group})
    for protein in proteins:
        pos = per_group.get((protein, "positive"), [])
        neg = per_group.get((protein, "negative"), [])
        if not pos or not neg:
            continue
        pos_rate = sum(pos) / len(pos)
        neg_rate = sum(neg) / len(neg)
        gap = abs(pos_rate - neg_rate)
        per_protein_gaps.append(gap)
        if gap >= SEVERE_GAP_POINTS:
            severe_alerts.append(
                {"protein": protein, "class": None, "reason": "retention_gap_ge_40pts", "gap": gap}
            )

    overall_pos = overall.get("positive", [])
    overall_neg = overall.get("negative", [])
    overall_gap = (
        abs(sum(overall_pos) / len(overall_pos) - sum(overall_neg) / len(overall_neg))
        if overall_pos and overall_neg
        else None
    )

    return {
        "overall": {label: rate_with_ci(sum(flags), len(flags)) for label, flags in overall.items()},
        "overall_positive_negative_gap": overall_gap,
        "per_protein_class": groups,
        "per_protein_gap_distribution": per_protein_gaps,
        "severe_alerts": severe_alerts,
    }


def retention_by_decile(
    sample_sequences: dict[str, str],
    primary_by_id: dict[str, dict],
    splice_by_id: dict[str, dict],
    *,
    decile_fn,
) -> dict:
    groups: dict[int, list[bool]] = defaultdict(list)
    for sample_id, sequence in sample_sequences.items():
        primary_row = primary_by_id.get(sample_id)
        if primary_row is None:
            continue
        splice_category = splice_by_id.get(sample_id, {}).get("category")
        usable = is_usable_unique(primary_row["category"], splice_category)
        groups[decile_fn(sequence)].append(usable)
    return {str(decile): rate_with_ci(sum(flags), len(flags)) for decile, flags in sorted(groups.items())}


def retention_by_gc_decile(sample_sequences, primary_by_id, splice_by_id) -> dict:
    return retention_by_decile(sample_sequences, primary_by_id, splice_by_id, decile_fn=gc_decile)


def retention_by_low_complexity_decile(sample_sequences, primary_by_id, splice_by_id) -> dict:
    return retention_by_decile(sample_sequences, primary_by_id, splice_by_id, decile_fn=low_complexity_decile)


def build_per_build_summary(
    *,
    build: str,
    primary_rows: Sequence[dict],
    splice_rows: Sequence[dict],
    representative_ids: Sequence[str],
    all_sample_ids: Sequence[str],
    sample_meta: Sequence[dict],
    sample_sequences: dict[str, str],
    near_tied_fractions: Sequence[float],
) -> dict:
    primary_by_id = index_rows_by_sample(primary_rows, mode="primary")
    splice_by_id = index_rows_by_sample(splice_rows, mode="splice")
    primary_control_by_id = {
        row["sample_id"]: row for row in primary_rows if row.get("mode") == "primary" and _is_control(row)
    }
    splice_control_by_id = {
        row["sample_id"]: row for row in splice_rows if row.get("mode") == "splice" and _is_control(row)
    }

    return {
        "build": build,
        "representative_stratum_gate": {
            "usable_unique_rate": usable_unique_rate(primary_by_id, splice_by_id, sample_ids=representative_ids),
            "exact_unique_rate": category_rate(
                primary_by_id, sample_ids=representative_ids, categories=frozenset({"exact_unique"})
            ),
            "ambiguous_rate": category_rate(
                primary_by_id, sample_ids=representative_ids, categories=frozenset({"ambiguous"})
            ),
            "unmapped_rate": category_rate(
                primary_by_id, sample_ids=representative_ids, categories=frozenset({"unmapped"})
            ),
        },
        "contiguous_vs_splice_rescued": {
            "representative": contiguous_vs_splice_rescued(
                primary_by_id, splice_by_id, sample_ids=representative_ids
            ),
            "all_sampled": contiguous_vs_splice_rescued(primary_by_id, splice_by_id, sample_ids=all_sample_ids),
        },
        "quality_distributions": {
            "primary_coverage_decile": quality_distribution(primary_by_id, field="coverage"),
            "primary_identity_decile": quality_distribution(primary_by_id, field="identity"),
            "splice_coverage_decile": quality_distribution(splice_by_id, field="coverage"),
            "splice_identity_decile": quality_distribution(splice_by_id, field="identity"),
        },
        "strand_and_locus": {
            "primary": strand_locus_summary(primary_by_id),
            "splice": strand_locus_summary(splice_by_id),
        },
        "near_tied_sensitivity": {
            "primary": near_tied_sensitivity_summary(primary_by_id, fractions=near_tied_fractions),
            "splice": near_tied_sensitivity_summary(splice_by_id, fractions=near_tied_fractions),
        },
        "control_alerts": {
            "primary": control_alert(primary_control_by_id, usable_categories=USABLE_PRIMARY_CATEGORIES),
            "splice": control_alert(splice_control_by_id, usable_categories=frozenset({SPLICE_RESCUE_CATEGORY})),
        },
        "retention": {
            "by_protein_class": retention_by_protein_class(sample_meta, primary_by_id, splice_by_id),
            "by_gc_decile": retention_by_gc_decile(sample_sequences, primary_by_id, splice_by_id),
            "by_low_complexity_decile": retention_by_low_complexity_decile(
                sample_sequences, primary_by_id, splice_by_id
            ),
        },
    }


def _locus_key(row: dict) -> tuple | None:
    chrom = row.get("chrom") or ""
    if not chrom:
        return None
    return (chrom, row.get("start"), row.get("end"), row.get("strand"))


def compare_builds(build_summaries: dict[str, dict], build_primary_rows: dict[str, dict[str, dict]]) -> dict:
    """Label-blind comparison across exactly the builds given, per the parent
    task's "Compare builds without outcome leakage" mapping-first criteria.
    """
    builds = sorted(build_summaries)
    comparison: dict = {
        "builds_compared": builds,
        "usable_unique_rate_by_build": {
            b: build_summaries[b]["representative_stratum_gate"]["usable_unique_rate"]["point_estimate"]
            for b in builds
        },
        "exact_unique_rate_by_build": {
            b: build_summaries[b]["representative_stratum_gate"]["exact_unique_rate"]["point_estimate"]
            for b in builds
        },
    }
    if len(builds) == 2:
        b1, b2 = builds
        rate1 = comparison["usable_unique_rate_by_build"][b1]
        rate2 = comparison["usable_unique_rate_by_build"][b2]
        comparison["usable_unique_rate_gap_points"] = abs(rate1 - rate2) * 100
        shared_ids = set(build_primary_rows[b1]) & set(build_primary_rows[b2])
        changed = 0
        for sample_id in shared_ids:
            row1, row2 = build_primary_rows[b1][sample_id], build_primary_rows[b2][sample_id]
            key1, key2 = _locus_key(row1), _locus_key(row2)
            if key1 is not None and key2 is not None and key1 != key2:
                changed += 1
        comparison["loci_changed_between_builds"] = changed
        comparison["loci_compared"] = len(shared_ids)
    return comparison


__all__ = [
    "USABLE_PRIMARY_CATEGORIES",
    "SPLICE_RESCUE_CATEGORY",
    "index_rows_by_sample",
    "rate_with_ci",
    "usable_unique_rate",
    "category_rate",
    "contiguous_vs_splice_rescued",
    "quality_distribution",
    "strand_locus_summary",
    "near_tied_sensitivity_summary",
    "control_alert",
    "retention_by_protein_class",
    "retention_by_gc_decile",
    "retention_by_low_complexity_decile",
    "build_per_build_summary",
    "compare_builds",
]
