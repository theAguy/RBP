"""Disk-budget ledger for the Task 001B 30-GiB peak-new-disk ceiling.

The B6 peak ledger (docs/tasks/001b_coordinate_feasibility_execution.md,
"Disk-budget ledger") allocates conservative per-artifact allowances that
sum to 30 GiB. Checking free disk alone does not enforce that ceiling (a
volume can start with hundreds of GiB free); this module measures a
baseline, projects whether the next expensive step could exceed the
*remaining* budget before it runs, and records observed new bytes / free
space after each step so a later projection is corrected against reality
rather than only the static planning table.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

GIB = 1024**3

# Project-owner-approved planning allowances (conservative, not claims about
# final file sizes) from the B6 peak ledger table.
PLANNED_ALLOWANCES_GIB = {
    "source_packages_and_metadata": 2.0,
    "derived_references_and_indices": 6.5,
    "preserved_hg38_outputs": 4.0,
    "active_build_bwa_index": 5.5,
    "active_build_minimap2_index": 7.0,
    "active_hg19_outputs": 4.0,
    "environment_manifests_logs_margin": 1.0,
}
PROJECTED_PEAK_GIB = 30.0
MIN_FREE_DISK_GIB = 80.0
# The mapper/exact-match output writers' own combined stop allowance (hg38 or
# hg19 SAM/BED/report outputs), enforced independently of the whole-run ceiling.
BUILD_OUTPUT_ALLOWANCE_GIB = 4.0


@dataclass(frozen=True)
class DiskSnapshot:
    path: str
    free_gib: float
    total_gib: float
    used_gib: float

    def to_dict(self) -> dict:
        return {"path": self.path, "free_gib": self.free_gib, "total_gib": self.total_gib, "used_gib": self.used_gib}


def snapshot(path: Path) -> DiskSnapshot:
    usage = shutil.disk_usage(path)
    return DiskSnapshot(
        path=str(path), free_gib=usage.free / GIB, total_gib=usage.total / GIB, used_gib=usage.used / GIB
    )


@dataclass
class DiskBudgetLedger:
    """Tracks a baseline snapshot and every subsequent observed-new-bytes
    entry, so a projection can be corrected against measured reality rather
    than trusting only the static planning table.
    """

    baseline: DiskSnapshot
    entries: list[dict] = field(default_factory=list)

    @property
    def observed_new_gib(self) -> float:
        return sum(entry["new_gib_since_baseline"] for entry in self.entries)

    def record_step(self, label: str, *, path: Path) -> dict:
        current = snapshot(path)
        new_gib = self.baseline.free_gib - current.free_gib
        entry = {
            "label": label,
            "free_gib_now": current.free_gib,
            "new_gib_since_baseline": new_gib,
        }
        self.entries.append(entry)
        return entry

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "planned_allowances_gib": PLANNED_ALLOWANCES_GIB,
            "projected_peak_gib": PROJECTED_PEAK_GIB,
            "min_free_disk_gib": MIN_FREE_DISK_GIB,
            "entries": list(self.entries),
            "observed_new_gib": self.observed_new_gib,
        }


def start_ledger(path: Path) -> DiskBudgetLedger:
    return DiskBudgetLedger(baseline=snapshot(path))


@dataclass(frozen=True)
class ProjectedPeakCheck:
    ok: bool
    projected_total_new_gib: float
    remaining_budget_gib: float
    free_disk_gib: float
    violations: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "projected_total_new_gib": self.projected_total_new_gib,
            "remaining_budget_gib": self.remaining_budget_gib,
            "free_disk_gib": self.free_disk_gib,
            "violations": list(self.violations),
        }


def check_projected_peak(
    ledger: DiskBudgetLedger,
    *,
    next_step_allowance_gib: float,
    disk_path: Path,
    max_new_disk_gib: float = PROJECTED_PEAK_GIB,
    min_free_disk_gib: float = MIN_FREE_DISK_GIB,
) -> ProjectedPeakCheck:
    """Fail-closed check run before every download/derivation/indexing/
    mapping subprocess: would the observed new bytes so far plus the next
    step's planned allowance exceed the 30-GiB ceiling, or would projected
    free disk fall below 80 GiB? Never merely checks current free disk in
    isolation — that alone does not enforce a ceiling on *new* bytes.
    """
    projected_total = ledger.observed_new_gib + next_step_allowance_gib
    current = snapshot(disk_path)
    violations: list[str] = []
    if current.free_gib < min_free_disk_gib:
        violations.append(
            f"free disk is already {current.free_gib:.2f} GiB, below the required {min_free_disk_gib:.2f} GiB"
        )
    if projected_total > max_new_disk_gib:
        violations.append(
            f"projected new disk {projected_total:.2f} GiB (observed {ledger.observed_new_gib:.2f} + "
            f"next step {next_step_allowance_gib:.2f}) would exceed the {max_new_disk_gib:.2f} GiB ceiling"
        )
    projected_free_after = current.free_gib - next_step_allowance_gib
    if projected_free_after < min_free_disk_gib:
        violations.append(
            f"projected free disk after this step ({projected_free_after:.2f} GiB) would fall below the "
            f"required {min_free_disk_gib:.2f} GiB (currently {current.free_gib:.2f} GiB free)"
        )
    return ProjectedPeakCheck(
        ok=not violations,
        projected_total_new_gib=projected_total,
        remaining_budget_gib=max_new_disk_gib - ledger.observed_new_gib,
        free_disk_gib=current.free_gib,
        violations=tuple(violations),
    )


__all__ = [
    "GIB",
    "PLANNED_ALLOWANCES_GIB",
    "PROJECTED_PEAK_GIB",
    "MIN_FREE_DISK_GIB",
    "BUILD_OUTPUT_ALLOWANCE_GIB",
    "DiskSnapshot",
    "snapshot",
    "DiskBudgetLedger",
    "start_ledger",
    "ProjectedPeakCheck",
    "check_projected_peak",
]
