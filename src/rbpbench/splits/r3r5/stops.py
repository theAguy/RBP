"""Terminal-state classes and the closed resume decision table (C5).

Every way the workflow can end is one :class:`StopClass`.  Only four are
resumable: a caught scheduler/termination signal, insufficient allocation
time before the packaging reserve, a corrected external resource condition
(free disk, available RAM, swap, quota, concurrency, unavailable live
measurement), or an interruption that left no stop record at all (an
uncatchable kill or node loss).  Scientific and integrity stops, frozen
resource-limit stops (job-owned ceiling, stage timeout or audit budget),
tool failures, and success are terminal.
"""

from __future__ import annotations

import errno
from enum import Enum


class StopClass(str, Enum):
    SUCCESS = "SUCCESS"
    SCIENTIFIC = "SCIENTIFIC_STOP"
    INTEGRITY = "INTEGRITY_STOP"
    RESOURCE_LIMIT = "RESOURCE_LIMIT_STOP"
    TOOL_FAILURE = "TOOL_FAILURE_STOP"
    RESOURCE_EXTERNAL = "RESOURCE_EXTERNAL_STOP"
    SCHEDULER_TIME = "SCHEDULER_TIME_STOP"
    SIGNAL = "SIGNAL_STOP"
    UNRECORDED_INTERRUPTION = "UNRECORDED_INTERRUPTION"


RESUMABLE: frozenset[StopClass] = frozenset({
    StopClass.RESOURCE_EXTERNAL,
    StopClass.SCHEDULER_TIME,
    StopClass.SIGNAL,
    StopClass.UNRECORDED_INTERRUPTION,
})
TERMINAL: frozenset[StopClass] = frozenset(set(StopClass) - RESUMABLE)

RESUME_DECISION_TABLE: dict[str, str] = {
    "no prior attempt": "refuse: use execute, never resume",
    StopClass.SUCCESS.value: "refuse: workflow already terminal (successor jobs become no-ops)",
    StopClass.SCIENTIFIC.value: "refuse: terminal scientific stop",
    StopClass.INTEGRITY.value: "refuse: terminal integrity stop",
    StopClass.RESOURCE_LIMIT.value: "refuse: frozen ceiling/timeout/budget exceeded; needs review",
    StopClass.TOOL_FAILURE.value: "refuse: MMseqs2 failed or emitted a fatal diagnostic; needs review",
    StopClass.RESOURCE_EXTERNAL.value: "allow after the external condition is corrected; all evidence re-verified",
    StopClass.SCHEDULER_TIME.value: "allow: insufficient allocation before the packaging reserve",
    StopClass.SIGNAL.value: "allow: caught USR1/TERM/INT; all evidence re-verified",
    StopClass.UNRECORDED_INTERRUPTION.value: "allow only when the recorded owner job is no longer running",
    "attempt still running": "refuse: another attempt holds the workflow lock",
}


class WorkflowStop(Exception):
    stop_class: StopClass = StopClass.INTEGRITY

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class ScientificStop(WorkflowStop):
    stop_class = StopClass.SCIENTIFIC


class IntegrityStop(WorkflowStop):
    stop_class = StopClass.INTEGRITY


class ResourceLimitStop(WorkflowStop):
    stop_class = StopClass.RESOURCE_LIMIT


class ToolFailureStop(WorkflowStop):
    stop_class = StopClass.TOOL_FAILURE


class ExternalResourceStop(WorkflowStop):
    stop_class = StopClass.RESOURCE_EXTERNAL


class SchedulerTimeStop(WorkflowStop):
    stop_class = StopClass.SCHEDULER_TIME


class SignalStop(WorkflowStop):
    stop_class = StopClass.SIGNAL


def classify_exception(exc: BaseException) -> StopClass:
    """Maps any exception to a stop class.  Unknown failures are integrity
    stops (contradictory state), never silently resumable."""
    if isinstance(exc, WorkflowStop):
        return exc.stop_class
    if isinstance(exc, KeyboardInterrupt):
        return StopClass.SIGNAL
    from rbpbench.splits.assignment import AssignmentInfeasibleError

    if isinstance(exc, AssignmentInfeasibleError):
        return StopClass.SCIENTIFIC
    if isinstance(exc, OSError) and exc.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", -1)}:
        return StopClass.RESOURCE_EXTERNAL
    return StopClass.INTEGRITY


def resume_allowed(last_stop: StopClass | None) -> tuple[bool, str]:
    if last_stop is None:
        return False, RESUME_DECISION_TABLE["no prior attempt"]
    return last_stop in RESUMABLE, RESUME_DECISION_TABLE[last_stop.value]


__all__ = [
    "StopClass", "RESUMABLE", "TERMINAL", "RESUME_DECISION_TABLE",
    "WorkflowStop", "ScientificStop", "IntegrityStop", "ResourceLimitStop", "ToolFailureStop",
    "ExternalResourceStop", "SchedulerTimeStop", "SignalStop", "classify_exception", "resume_allowed",
]
