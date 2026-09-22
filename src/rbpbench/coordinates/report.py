"""Report-table generation and count reconciliation.

This module produces descriptive tables and reconciliation pass/fail checks
only. It deliberately does not compute a Phase-2 recommendation: the parent
task is explicit that "[t]he final decision is made from the full report. It
is not encoded as a script that silently advances the project." Task 001B's
human-authored report fills that field in after inspecting the full output.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from rbpbench.coordinates.alignment import PRIMARY_CATEGORIES, SPLICE_CATEGORIES, is_usable_unique
from rbpbench.coordinates.sampling import FILLER, QUOTA, REPRESENTATIVE, SampleAssignment

ALLOWED_CATEGORIES = frozenset(PRIMARY_CATEGORIES) | frozenset(SPLICE_CATEGORIES)


@dataclass(frozen=True)
class MappingResult:
    sample_id: str
    is_control: bool
    build: str  # e.g. "hg38", "hg19"
    mode: str  # "primary" | "splice"
    category: str


@dataclass(frozen=True)
class ReconciliationIssue:
    check: str
    detail: str


@dataclass(frozen=True)
class ReconciliationReport:
    issues: tuple[ReconciliationIssue, ...]
    # False when mapping (align/exact_match) was never actually executed, e.g.
    # a dry run or a run that stopped at planning. In that case reconciliation
    # of mapping-derived counts has nothing to check and must say so plainly
    # rather than reporting a hollow "passed".
    mapping_evaluated: bool = True

    @property
    def status(self) -> str:
        if not self.mapping_evaluated:
            return "not_evaluated"
        return "passed" if not self.issues else "failed"

    @property
    def passed(self) -> bool:
        return self.mapping_evaluated and len(self.issues) == 0


def stratum_counts(assignments: Sequence[SampleAssignment]) -> Counter:
    return Counter(assignment.stratum for assignment in assignments)


def label_observation_counts(assignments: Sequence[SampleAssignment]) -> dict[tuple[int, str], int]:
    counts: dict[tuple[int, str], int] = {}
    for assignment in assignments:
        for value in assignment.labels:
            key = (abs(value), "positive" if value > 0 else "negative")
            counts[key] = counts.get(key, 0) + 1
    return counts


def category_table(results: Sequence[MappingResult]) -> dict[tuple[str, str, bool], Counter]:
    """Category counts keyed by (build, mode, is_control)."""
    table: dict[tuple[str, str, bool], Counter] = {}
    for result in results:
        key = (result.build, result.mode, result.is_control)
        table.setdefault(key, Counter())[result.category] += 1
    return table


def usable_unique_rate(
    primary_results: Sequence[MappingResult],
    splice_by_sample: dict[str, str],
    *,
    build: str,
) -> float | None:
    """Fraction of non-control, primary-build rows that are usable unique."""
    relevant = [r for r in primary_results if r.build == build and r.mode == "primary" and not r.is_control]
    if not relevant:
        return None
    usable = sum(
        1
        for r in relevant
        if is_usable_unique(r.category, splice_by_sample.get(r.sample_id))
    )
    return usable / len(relevant)


def reconcile_counts(
    assignments: Sequence[SampleAssignment],
    mapping_results: Sequence[MappingResult],
    *,
    expected_total: int,
    expected_representative: int,
    expected_controls: int,
    mapping_evaluated: bool = True,
    expected_control_ids: Sequence[str] = (),
    expected_builds: Sequence[str] = (),
    expected_modes: Sequence[str] = (),
) -> ReconciliationReport:
    """Check sample/stratum counts, and (when ``mapping_evaluated``) mapping
    counts, for internal consistency.

    ``mapping_evaluated=False`` marks a run where align/exact_match were
    never actually executed (a dry run, or a run that stopped at planning):
    the returned report's ``status`` is ``"not_evaluated"`` rather than a
    potentially-misleading ``"passed"`` derived from an empty result set.

    When ``mapping_evaluated`` is True, mapping-derived checks are
    unconditional: zero controls or zero mapping rows are failures whenever
    results were expected, never silently skipped. Passing
    ``expected_builds``/``expected_modes``/``expected_control_ids`` also
    requires every expected build x mode x biological/control combination to
    be present with no missing sample IDs, not merely the combinations that
    happen to appear in ``mapping_results``.
    """
    issues: list[ReconciliationIssue] = []

    if len(assignments) != expected_total:
        issues.append(
            ReconciliationIssue(
                "sample_total",
                f"expected {expected_total} sampled rows, found {len(assignments)}",
            )
        )

    sample_ids = [a.sample_id for a in assignments]
    if len(set(sample_ids)) != len(sample_ids):
        issues.append(ReconciliationIssue("sample_uniqueness", "duplicate sample IDs in the assembled sample"))

    counts = stratum_counts(assignments)
    if counts.get(REPRESENTATIVE, 0) != expected_representative:
        issues.append(
            ReconciliationIssue(
                "representative_count",
                f"expected {expected_representative} representative rows, found {counts.get(REPRESENTATIVE, 0)}",
            )
        )
    if counts.get(REPRESENTATIVE, 0) + counts.get(QUOTA, 0) + counts.get(FILLER, 0) != len(assignments):
        issues.append(ReconciliationIssue("stratum_partition", "stratum counts do not sum to the total sample"))

    if not mapping_evaluated:
        return ReconciliationReport(issues=tuple(issues), mapping_evaluated=False)

    if (expected_total or expected_controls) and not mapping_results:
        issues.append(
            ReconciliationIssue(
                "empty_mapping_results",
                "mapping was evaluated but produced zero rows, though results were expected",
            )
        )

    invalid_categories = {r.category for r in mapping_results} - ALLOWED_CATEGORIES
    if invalid_categories:
        issues.append(
            ReconciliationIssue(
                "invalid_category",
                f"unrecognized category name(s): {sorted(invalid_categories)}",
            )
        )

    control_ids = {r.sample_id for r in mapping_results if r.is_control}
    if len(control_ids) != expected_controls:
        issues.append(
            ReconciliationIssue(
                "control_count",
                f"expected {expected_controls} distinct controls, found {len(control_ids)}",
            )
        )

    biological_ids = set(sample_ids)
    result_biological_ids = {r.sample_id for r in mapping_results if not r.is_control}
    unknown_ids = result_biological_ids - biological_ids
    if unknown_ids:
        issues.append(
            ReconciliationIssue(
                "unknown_sample_ids",
                f"{len(unknown_ids)} mapping results reference sample IDs outside the assembled sample",
            )
        )

    table = category_table(mapping_results)
    present_builds = {build for build, _mode, _is_control in table}
    present_modes = {mode for _build, mode, _is_control in table}
    builds = tuple(expected_builds) or tuple(sorted(present_builds))
    modes = tuple(expected_modes) or tuple(sorted(present_modes))
    control_id_universe = set(expected_control_ids) or control_ids

    for build in builds:
        for mode in modes:
            for is_control, expected_ids in ((False, biological_ids), (True, control_id_universe)):
                category_counter = table.get((build, mode, is_control), Counter())
                total = sum(category_counter.values())
                distinct_ids = {
                    r.sample_id
                    for r in mapping_results
                    if r.build == build and r.mode == mode and r.is_control == is_control
                }
                if len(distinct_ids) != total:
                    issues.append(
                        ReconciliationIssue(
                            "one_category_per_row",
                            f"{build}/{mode}/control={is_control}: {total} category rows but {len(distinct_ids)} distinct sample IDs",
                        )
                    )
                missing_ids = expected_ids - distinct_ids
                if missing_ids:
                    issues.append(
                        ReconciliationIssue(
                            "missing_mapping_ids",
                            f"{build}/{mode}/control={is_control}: {len(missing_ids)} of {len(expected_ids)} expected sample IDs have no mapping row",
                        )
                    )
                expected_rows = len(control_id_universe) if is_control else expected_total
                if total != expected_rows:
                    issues.append(
                        ReconciliationIssue(
                            "category_row_count",
                            f"{build}/{mode}/control={is_control}: expected {expected_rows} classified rows, found {total}",
                        )
                    )

    return ReconciliationReport(issues=tuple(issues), mapping_evaluated=True)


def build_report(
    assignments: Sequence[SampleAssignment],
    mapping_results: Sequence[MappingResult],
    *,
    reconciliation: ReconciliationReport,
) -> dict:
    return {
        "schema_version": 1,
        "sample": {
            "total": len(assignments),
            "by_stratum": dict(stratum_counts(assignments)),
        },
        "label_observations": {
            f"{protein_id}:{label}": count
            for (protein_id, label), count in sorted(label_observation_counts(assignments).items())
        },
        "category_counts": {
            f"{build}|{mode}|control={is_control}": dict(counter)
            for (build, mode, is_control), counter in category_table(mapping_results).items()
        },
        "reconciliation": {
            "status": reconciliation.status,
            "passed": reconciliation.passed,
            "issues": [
                {"check": issue.check, "detail": issue.detail} for issue in reconciliation.issues
            ],
        },
        "phase2_recommendation": None,
    }


def build_combined_report(builds: Sequence[str], per_build: dict, build_comparison: dict) -> dict:
    """Assemble the final two-build combined report (parent task's required
    output/report path before Task 001B). Per-build reconciliation/category
    tables already exist in each build's own ``report.json``; this is the
    single report a human reviewer reads to set the Phase 2 recommendation,
    never computed here (see module docstring).
    """
    return {
        "schema_version": 1,
        "builds": list(builds),
        "per_build": per_build,
        "build_comparison": build_comparison,
        "phase2_recommendation": None,
    }


def _render_rate(rate: dict) -> str:
    return (
        f"{rate['point_estimate']:.4f} "
        f"(95% CI {rate['lower']:.4f}-{rate['upper']:.4f}, n={rate['total']})"
    )


def render_combined_report_markdown(report: dict) -> str:
    lines = ["# Coordinate feasibility — combined two-build report", ""]
    lines.append(f"Builds compared: {', '.join(report['builds'])}")
    lines.append("")

    for build in report["builds"]:
        summary = report["per_build"].get(build)
        if summary is None:
            continue
        lines.append(f"## Build: {build}")
        lines.append("")
        if not summary.get("mapping_evaluated", True):
            lines.append("Mapping was not evaluated for this build (dry run, or mapping never authorized).")
            lines.append("")
            continue
        lines.append("### Representative-stratum gate (headline)")
        gate = summary["representative_stratum_gate"]
        for key, rate in gate.items():
            lines.append(f"- {key}: {_render_rate(rate)}")
        lines.append("")
        lines.append("### Contiguous vs. splice-rescued")
        for scope, payload in summary["contiguous_vs_splice_rescued"].items():
            lines.append(f"- {scope}: {payload['counts']} (of {payload['total']})")
        lines.append("")
        lines.append("### Quality distributions (decile histograms)")
        for key, histogram in summary["quality_distributions"].items():
            lines.append(f"- {key}: {histogram}")
        lines.append("")
        lines.append("### Strand and locus summary")
        for mode, payload in summary["strand_and_locus"].items():
            lines.append(f"- {mode}: {payload}")
        lines.append("")
        lines.append("### Near-tied score-gap sensitivity (tool-specific diagnostic)")
        for mode, payload in summary["near_tied_sensitivity"].items():
            lines.append(f"- {mode}: {payload}")
        lines.append("")
        lines.append("### Control alerts")
        for mode, payload in summary["control_alerts"].items():
            marker = "ALERT" if payload["alert"] else "ok"
            lines.append(f"- {mode}: {marker} — {payload['flagged_sample_ids']}")
        lines.append("")
        lines.append("### Exact-match discordance (BWA-MEM vs. SeqKit)")
        discordance = summary["exact_match_discordance"]
        lines.append(
            f"- {discordance['discordant_count']} of {discordance['total_bwa_perfect_unique']} "
            "BWA-perfect-unique rows disagree with SeqKit's exact-occurrence count"
        )
        if discordance["discordant_sample_ids"]:
            lines.append(f"  - discordant: {discordance['discordant_sample_ids']}")
        lines.append("")
        lines.append("### Retention audit (signed positive-minus-negative gaps; alerts use absolute gaps)")
        for scope in ("combined", "primary", "splice"):
            by_protein_class = summary["retention"][scope]["by_protein_class"]
            overall_gap = by_protein_class["overall_positive_negative_gap"]
            severe = by_protein_class["severe_alerts"]
            lines.append(f"- **{scope}** mode: overall positive/negative retention gap: {overall_gap}")
            lines.append(f"  - severe per-protein/class alerts: {len(severe)}")
            for alert in severe:
                lines.append(f"    - {alert}")
        lines.append("")

    lines.append("## Build comparison (label-blind)")
    for key, value in report["build_comparison"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append(
        "## Phase 2 recommendation\n\n"
        "Not computed by this pipeline. The parent task requires a human "
        "reviewer to set this from the full report, not an automated rule."
    )
    return "\n".join(lines) + "\n"


def render_markdown(report: dict) -> str:
    lines = ["# Coordinate feasibility report", ""]
    lines.append(f"Total sampled rows: {report['sample']['total']}")
    lines.append("")
    lines.append("## Stratum counts")
    for stratum, count in report["sample"]["by_stratum"].items():
        lines.append(f"- {stratum}: {count}")
    lines.append("")
    lines.append("## Category counts")
    for key, counter in report["category_counts"].items():
        lines.append(f"### {key}")
        for category, count in counter.items():
            lines.append(f"- {category}: {count}")
    lines.append("")
    lines.append("## Reconciliation")
    lines.append(f"Status: {report['reconciliation']['status']}")
    lines.append(f"Passed: {report['reconciliation']['passed']}")
    for issue in report["reconciliation"]["issues"]:
        lines.append(f"- **{issue['check']}**: {issue['detail']}")
    lines.append("")
    lines.append(
        "## Phase 2 recommendation\n\n"
        "Not computed by this pipeline. The parent task requires a human "
        "reviewer to set this from the full report, not an automated rule."
    )
    return "\n".join(lines) + "\n"
