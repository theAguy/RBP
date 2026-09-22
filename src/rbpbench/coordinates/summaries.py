"""Per-build and cross-build report summaries required before Task 001B.

Operates on already-persisted, plain string-valued mapping rows (as read
back from a build's ``mappings.tsv.gz``) and sample metadata, never on
in-memory pipeline state, so the combined-report stage can run as its own
process after every build's ``align``/``exact_match``/``report`` stage and
still see every prior build's results — the same resume-safety requirement
the rest of the runner already follows.

Controls are diagnostic-only: they are excluded from every scientific
mapping-quality, strand/locus, near-tied, retention, and build-comparison
table here, and appear only in ``control_alert``'s dedicated tables (see
``build_per_build_summary``, which is the only place a control-including and
a control-excluding view of the same rows both exist side by side).

Every table here is a descriptive summary or a gross-failure screen. None of
them compute the Phase 2 recommendation (see ``rbpbench.coordinates.report``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Callable, Optional, Sequence

from rbpbench.coordinates.alignment import is_usable_unique
from rbpbench.coordinates.sequence_stats import decile_index, gc_decile, low_complexity_decile
from rbpbench.coordinates.stats import ConfidenceInterval, wilson_confidence_interval

USABLE_PRIMARY_CATEGORIES = frozenset({"exact_unique", "high_conf_unique"})
SPLICE_RESCUE_CATEGORY = "spliced_unique"
SPLICE_MODE_USABLE_CATEGORIES = frozenset({"spliced_unique", "unspliced_unique"})
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


def _int_or_none(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def index_rows_by_sample(rows: Sequence[dict], *, mode: str) -> dict[str, dict]:
    return {row["sample_id"]: row for row in rows if row.get("mode") == mode}


def exclude_controls(rows_by_id: dict[str, dict]) -> dict[str, dict]:
    """Biological-only view of a sample_id-keyed row dict.

    Every scientific mapping-quality, strand/locus, near-tied, retention, and
    build-comparison table must be computed from this, never from the raw
    (control-including) dict — controls remain visible only through
    ``control_alert``'s own dedicated, control-only tables.
    """
    return {sample_id: row for sample_id, row in rows_by_id.items() if not _is_control(row)}


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
    ``rows_by_id`` must already be control-excluded (see
    :func:`exclude_controls`).
    """
    histogram: Counter = Counter()
    for row in rows_by_id.values():
        value = _float_or_none(row.get(field))
        if value is None:
            continue
        histogram[decile_index(value, max_value=1.0)] += 1
    return dict(sorted(histogram.items()))


def strand_locus_summary(rows_by_id: dict[str, dict]) -> dict:
    """``rows_by_id`` must already be control-excluded (see
    :func:`exclude_controls`)."""
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
    ``rows_by_id`` must already be control-excluded (see
    :func:`exclude_controls`).
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
    inspection. This is the one table controls are deliberately retained in.
    """
    flagged = sorted(
        sample_id for sample_id, row in rows_by_id.items() if row["category"] in usable_categories
    )
    return {"alert": bool(flagged), "flagged_sample_ids": flagged}


def exact_match_discordance(primary_by_id: dict[str, dict]) -> dict:
    """BWA-MEM-vs-SeqKit exact-match discordance (parent task: "Report
    discordance between BWA-MEM and the exact matcher"). A row is discordant
    when BWA-MEM's best primary alignment is a genuine exact-uniqueness
    *candidate* (100% coverage/identity AND no plausible distinct secondary
    locus — ``bwa_perfect_unique_candidate``, never merely
    ``bwa_best_is_perfect``: a read with two perfect BWA loci is
    ``ambiguous``, not a uniqueness candidate, regardless of what SeqKit
    reports) but SeqKit's independent exact-substring search found other
    than exactly one genomic occurrence. ``primary_by_id`` must already be
    control-excluded (see :func:`exclude_controls`).
    """
    total_bwa_perfect_unique_candidates = 0
    discordant: list[dict] = []
    for sample_id, row in primary_by_id.items():
        if str(row.get("bwa_perfect_unique_candidate", "")).strip().lower() != "true":
            continue
        total_bwa_perfect_unique_candidates += 1
        occurrence_count = _int_or_none(row.get("exact_occurrence_count"))
        if occurrence_count is not None and occurrence_count != 1:
            discordant.append({"sample_id": sample_id, "exact_occurrence_count": occurrence_count})
    return {
        "total_bwa_perfect_unique_candidates": total_bwa_perfect_unique_candidates,
        "discordant_count": len(discordant),
        "discordant_sample_ids": sorted(d["sample_id"] for d in discordant),
    }


def parse_labels(label_field: str) -> tuple[int, ...]:
    if not label_field:
        return ()
    return tuple(int(v) for v in label_field.split(";") if v != "")


def _usable_combined(primary_row: dict | None, splice_row: dict | None) -> bool:
    primary_category = primary_row["category"] if primary_row is not None else "unmapped"
    splice_category = splice_row["category"] if splice_row is not None else None
    return is_usable_unique(primary_category, splice_category)


def _usable_primary_mode(primary_row: dict | None, splice_row: dict | None) -> bool:
    return primary_row is not None and primary_row["category"] in USABLE_PRIMARY_CATEGORIES


def _usable_splice_mode(primary_row: dict | None, splice_row: dict | None) -> bool:
    return splice_row is not None and splice_row["category"] in SPLICE_MODE_USABLE_CATEGORIES


UsableFn = Callable[[Optional[dict], Optional[dict]], bool]


def retention_by_protein_class(
    sample_meta: Sequence[dict],
    primary_by_id: dict[str, dict],
    splice_by_id: dict[str, dict],
    *,
    usable_fn: UsableFn = _usable_combined,
) -> dict:
    """Per-protein/class retention over label observations (a row with
    labels for several proteins contributes to each), plus the *signed*
    overall positive-minus-negative gap and per-protein gap distribution,
    and a severe-alert flag using the *absolute* gap only for that
    threshold decision (the parent task's gross-failure-screen definition).
    ``primary_by_id``/``splice_by_id`` must already be control-excluded.
    """
    per_group: dict[tuple[int, str], list[bool]] = defaultdict(list)
    overall: dict[str, list[bool]] = defaultdict(list)

    for entry in sample_meta:
        sample_id = entry["sample_id"]
        primary_row = primary_by_id.get(sample_id)
        splice_row = splice_by_id.get(sample_id)
        if primary_row is None and splice_row is None:
            continue
        usable = usable_fn(primary_row, splice_row)
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
        # Signed gap is preserved in the reported distribution; only the
        # *absolute* gap decides the severe-alert threshold.
        signed_gap = pos_rate - neg_rate
        per_protein_gaps.append(signed_gap)
        if abs(signed_gap) >= SEVERE_GAP_POINTS:
            severe_alerts.append(
                {"protein": protein, "class": None, "reason": "retention_gap_ge_40pts", "gap": signed_gap}
            )

    overall_pos = overall.get("positive", [])
    overall_neg = overall.get("negative", [])
    overall_gap = (
        (sum(overall_pos) / len(overall_pos) - sum(overall_neg) / len(overall_neg))
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
    usable_fn: UsableFn = _usable_combined,
) -> dict:
    groups: dict[int, list[bool]] = defaultdict(list)
    for sample_id, sequence in sample_sequences.items():
        primary_row = primary_by_id.get(sample_id)
        splice_row = splice_by_id.get(sample_id)
        if primary_row is None and splice_row is None:
            continue
        usable = usable_fn(primary_row, splice_row)
        groups[decile_fn(sequence)].append(usable)
    return {str(decile): rate_with_ci(sum(flags), len(flags)) for decile, flags in sorted(groups.items())}


def retention_by_gc_decile(sample_sequences, primary_by_id, splice_by_id, *, usable_fn: UsableFn = _usable_combined) -> dict:
    return retention_by_decile(sample_sequences, primary_by_id, splice_by_id, decile_fn=gc_decile, usable_fn=usable_fn)


def retention_by_low_complexity_decile(
    sample_sequences, primary_by_id, splice_by_id, *, usable_fn: UsableFn = _usable_combined
) -> dict:
    return retention_by_decile(
        sample_sequences, primary_by_id, splice_by_id, decile_fn=low_complexity_decile, usable_fn=usable_fn
    )


def retention_by_contig_category(
    primary_by_id: dict[str, dict],
    splice_by_id: dict[str, dict],
    contig_categories: dict[str, str] | None,
    *,
    usable_fn: UsableFn = _usable_combined,
) -> dict | None:
    """Retention stratified by repeat/contig category, reported only when
    the reference manifest supplies a per-contig category mapping (parent
    task: "when the selected reference supplies the necessary metadata").
    Returns ``None`` — not an empty table — when no mapping was supplied.
    ``primary_by_id``/``splice_by_id`` must already be control-excluded.
    """
    if not contig_categories:
        return None
    groups: dict[str, list[bool]] = defaultdict(list)
    all_ids = set(primary_by_id) | set(splice_by_id)
    for sample_id in all_ids:
        primary_row = primary_by_id.get(sample_id)
        splice_row = splice_by_id.get(sample_id)
        chrom = (primary_row or {}).get("chrom") or (splice_row or {}).get("chrom")
        category = contig_categories.get(chrom) if chrom else None
        if not category:
            continue
        groups[category].append(usable_fn(primary_row, splice_row))
    return {category: rate_with_ci(sum(flags), len(flags)) for category, flags in sorted(groups.items())}


def _mode_retention_tables(
    *,
    usable_fn: UsableFn,
    sample_meta: Sequence[dict],
    primary_by_id: dict[str, dict],
    splice_by_id: dict[str, dict],
    sample_sequences: dict[str, str],
    contig_categories: dict[str, str] | None,
) -> dict:
    return {
        "by_protein_class": retention_by_protein_class(sample_meta, primary_by_id, splice_by_id, usable_fn=usable_fn),
        "by_gc_decile": retention_by_gc_decile(sample_sequences, primary_by_id, splice_by_id, usable_fn=usable_fn),
        "by_low_complexity_decile": retention_by_low_complexity_decile(
            sample_sequences, primary_by_id, splice_by_id, usable_fn=usable_fn
        ),
        "by_contig_category": retention_by_contig_category(
            primary_by_id, splice_by_id, contig_categories, usable_fn=usable_fn
        ),
    }


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
    contig_categories: dict[str, str] | None = None,
) -> dict:
    # Two views of the same rows: the raw (control-including) dicts are used
    # only to build control_alert's own tables; every scientific table below
    # uses the control-excluded view.
    primary_by_id_raw = index_rows_by_sample(primary_rows, mode="primary")
    splice_by_id_raw = index_rows_by_sample(splice_rows, mode="splice")
    primary_control_by_id = {sid: row for sid, row in primary_by_id_raw.items() if _is_control(row)}
    splice_control_by_id = {sid: row for sid, row in splice_by_id_raw.items() if _is_control(row)}
    primary_by_id = exclude_controls(primary_by_id_raw)
    splice_by_id = exclude_controls(splice_by_id_raw)

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
        "exact_match_discordance": exact_match_discordance(primary_by_id),
        "retention": {
            "combined": _mode_retention_tables(
                usable_fn=_usable_combined,
                sample_meta=sample_meta,
                primary_by_id=primary_by_id,
                splice_by_id=splice_by_id,
                sample_sequences=sample_sequences,
                contig_categories=contig_categories,
            ),
            "primary": _mode_retention_tables(
                usable_fn=_usable_primary_mode,
                sample_meta=sample_meta,
                primary_by_id=primary_by_id,
                splice_by_id=splice_by_id,
                sample_sequences=sample_sequences,
                contig_categories=contig_categories,
            ),
            "splice": _mode_retention_tables(
                usable_fn=_usable_splice_mode,
                sample_meta=sample_meta,
                primary_by_id=primary_by_id,
                splice_by_id=splice_by_id,
                sample_sequences=sample_sequences,
                contig_categories=contig_categories,
            ),
        },
    }


def compare_builds(build_summaries: dict[str, dict], build_primary_rows: dict[str, dict[str, dict]]) -> dict:
    """Label-blind comparison across exactly the builds given, per the parent
    task's "Compare builds without outcome leakage" mapping-first criteria.

    ``build_primary_rows`` must already be control-excluded. Raw genomic
    coordinates are never compared across builds here: hg19 and hg38
    coordinates are not directly comparable without a liftover (or another
    defensible equivalence) step, which this pipeline does not perform.
    Instead, "category changed" (the terminal classification, which is
    build-coordinate-independent) is reported as the liftover-free
    build-comparison signal.
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
        category_changed = 0
        for sample_id in shared_ids:
            cat1 = build_primary_rows[b1][sample_id]["category"]
            cat2 = build_primary_rows[b2][sample_id]["category"]
            if cat1 != cat2:
                category_changed += 1
        comparison["primary_category_changed_between_builds"] = category_changed
        comparison["primary_category_compared"] = len(shared_ids)
        comparison["coordinate_comparison_note"] = (
            "Raw genomic coordinates are not compared across builds: hg19 "
            "and hg38 coordinates are not directly comparable without a "
            "liftover (or another defensible equivalence) step, which this "
            "pipeline does not perform. 'primary_category_changed_between_"
            "builds' compares terminal classification instead, which is "
            "build-coordinate-independent."
        )
    return comparison


__all__ = [
    "USABLE_PRIMARY_CATEGORIES",
    "SPLICE_RESCUE_CATEGORY",
    "SPLICE_MODE_USABLE_CATEGORIES",
    "index_rows_by_sample",
    "exclude_controls",
    "rate_with_ci",
    "usable_unique_rate",
    "category_rate",
    "contiguous_vs_splice_rescued",
    "quality_distribution",
    "strand_locus_summary",
    "near_tied_sensitivity_summary",
    "control_alert",
    "exact_match_discordance",
    "retention_by_protein_class",
    "retention_by_gc_decile",
    "retention_by_low_complexity_decile",
    "retention_by_contig_category",
    "build_per_build_summary",
    "compare_builds",
]
