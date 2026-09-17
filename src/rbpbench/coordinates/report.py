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

from rbpbench.coordinates.alignment import is_usable_unique
from rbpbench.coordinates.sampling import FILLER, QUOTA, REPRESENTATIVE, SampleAssignment


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

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0


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
) -> ReconciliationReport:
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

    control_ids = {r.sample_id for r in mapping_results if r.is_control}
    if control_ids and len(control_ids) != expected_controls:
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
    for (build, mode, is_control), category_counter in table.items():
        total = sum(category_counter.values())
        expected_rows = expected_controls if is_control else expected_total
        distinct_ids = {r.sample_id for r in mapping_results if r.build == build and r.mode == mode and r.is_control == is_control}
        if len(distinct_ids) != total:
            issues.append(
                ReconciliationIssue(
                    "one_category_per_row",
                    f"{build}/{mode}/control={is_control}: {total} category rows but {len(distinct_ids)} distinct sample IDs",
                )
            )
        if not is_control and total != expected_rows:
            issues.append(
                ReconciliationIssue(
                    "category_row_count",
                    f"{build}/{mode}: expected {expected_rows} classified rows, found {total}",
                )
            )

    return ReconciliationReport(issues=tuple(issues))


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
            "passed": reconciliation.passed,
            "issues": [
                {"check": issue.check, "detail": issue.detail} for issue in reconciliation.issues
            ],
        },
        "phase2_recommendation": None,
    }


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
