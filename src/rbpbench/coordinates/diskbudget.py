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

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

GIB = 1024**3


class DiskBudgetExceeded(RuntimeError):
    """Raised when a writer's output grows past its enforced build-output
    allowance while a subprocess is still running (B1-R4): the process is
    terminated before the caller ever sees a truncated-but-accepted file.
    """

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

    ``state_path``, when set, makes every :meth:`record_step` call durably
    persist the ledger (baseline + entries) so the 30-GiB B6 peak ceiling is
    enforced across *separate* B1-B6 checkpoint invocations (each its own
    process), not merely within one process's lifetime (B1-R4).
    """

    baseline: DiskSnapshot
    entries: list[dict] = field(default_factory=list)
    state_path: Path | None = None

    @property
    def observed_new_gib(self) -> float:
        """The conservative current peak: the *maximum* single observed
        new-bytes-since-baseline reading, never the sum of every entry.

        Each entry already measures cumulative growth *since the same fixed
        baseline*, so summing successive entries double- (triple-, ...)
        counts every earlier step's bytes on top of later ones. Using the
        maximum is the "current/latest (or maximum conservative) delta"
        the reconciled task requires (B1-R4): it never under-reports a true
        peak even if a later step's free-disk reading is noisy or a later
        cleanup step reduces usage again.
        """
        if not self.entries:
            return 0.0
        return max(entry["new_gib_since_baseline"] for entry in self.entries)

    def record_step(self, label: str, *, path: Path) -> dict:
        current = snapshot(path)
        new_gib = self.baseline.free_gib - current.free_gib
        entry = {
            "label": label,
            "free_gib_now": current.free_gib,
            "new_gib_since_baseline": new_gib,
        }
        self.entries.append(entry)
        if self.state_path is not None:
            save_ledger(self, self.state_path)
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


def save_ledger(ledger: DiskBudgetLedger, state_path: Path) -> None:
    """Atomically persist ``ledger``'s baseline/entries to ``state_path``."""
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_name(state_path.name + f".tmp{os.getpid()}")
    tmp_path.write_text(
        json.dumps({"baseline": ledger.baseline.to_dict(), "entries": ledger.entries}, indent=2, sort_keys=True)
        + "\n"
    )
    os.replace(tmp_path, state_path)


def load_ledger(state_path: Path) -> DiskBudgetLedger:
    """Reload a previously persisted ledger's exact baseline and entries."""
    payload = json.loads(Path(state_path).read_text())
    baseline_dict = payload["baseline"]
    baseline = DiskSnapshot(
        path=baseline_dict["path"],
        free_gib=baseline_dict["free_gib"],
        total_gib=baseline_dict["total_gib"],
        used_gib=baseline_dict["used_gib"],
    )
    return DiskBudgetLedger(baseline=baseline, entries=list(payload.get("entries", [])), state_path=Path(state_path))


def start_ledger(path: Path, *, state_path: Path | None = None) -> DiskBudgetLedger:
    """Start a new ledger, or resume one already persisted at ``state_path``.

    A real B1-B6 study spans several *separate* runner invocations (one per
    checkpoint); reloading the persisted baseline/entries here (rather than
    re-baselining from the current free-disk reading every time) is what
    makes the 30-GiB ceiling apply across the whole study instead of
    resetting at each invocation (B1-R4).
    """
    if state_path is not None and Path(state_path).is_file():
        return load_ledger(Path(state_path))
    ledger = DiskBudgetLedger(baseline=snapshot(path), state_path=Path(state_path) if state_path is not None else None)
    if state_path is not None:
        save_ledger(ledger, Path(state_path))
    return ledger


def volume_id(path: Path) -> int | None:
    """``st_dev`` of the nearest existing ancestor of ``path``, or ``None``
    when nothing along the path exists yet (nothing has been placed there
    yet to check).
    """
    current = Path(path)
    for _ in range(64):
        if current.exists():
            return os.stat(current).st_dev
        if current.parent == current:
            return None
        current = current.parent
    return None


def check_pinned_volumes(paths: dict[str, Path], *, primary: Path) -> tuple[str, ...]:
    """Fail-closed cross-volume check (B1-R4): every pinned output/reference/
    index path must resolve onto the same filesystem volume as the
    disk-budget ledger's own baseline path, unless separately budgeted. A
    path that does not exist yet is skipped (nothing has been placed there
    to check); this is re-checked before every expensive step, so a path
    that starts existing later is still caught before it is used.
    """
    primary_dev = volume_id(primary)
    if primary_dev is None:
        return ()
    violations: list[str] = []
    for label, path in paths.items():
        dev = volume_id(path)
        if dev is not None and dev != primary_dev:
            violations.append(
                f"{label} ({path}) is on a different filesystem volume than the disk-budget baseline "
                f"({primary}); cross-volume placement is not separately budgeted"
            )
    return tuple(violations)


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
    "DiskBudgetExceeded",
    "DiskSnapshot",
    "snapshot",
    "DiskBudgetLedger",
    "save_ledger",
    "load_ledger",
    "start_ledger",
    "volume_id",
    "check_pinned_volumes",
    "ProjectedPeakCheck",
    "check_projected_peak",
]
