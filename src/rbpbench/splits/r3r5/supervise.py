"""Supervised MMseqs2 child execution with typed stop classes.

One child at a time runs in its own session/process group with
``shell=False``.  Before launch: installed RAM, available RAM (24 GiB),
the 80-GiB live free-space floor, memory state, and a measurable swap
baseline.  While running, every poll re-samples process-tree RSS,
available memory, swap growth, free space, the job-owned directory size,
and the deadline.  Any violation kills the whole process group exactly once
and raises a typed :mod:`rbpbench.splits.r3r5.stops` exception:

* job-owned ceiling crossed, stage timeout, or exhausted audit budget →
  :class:`ResourceLimitStop` (terminal);
* deadline imposed by the packaging reserve → :class:`SchedulerTimeStop`;
* free space, available memory, swap, memory state, or an unavailable
  measurement → :class:`ExternalResourceStop`;
* non-zero exit or a fatal MMseqs2 diagnostic → :class:`ToolFailureStop`.

Live measurements reuse the accepted R2 monitors
(:class:`rbpbench.splits.resource_probe_r2.ResourceMonitors`).
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from rbpbench.coordinates.commands import ToolCommand, format_command
from rbpbench.data.audit import sha256_file
from rbpbench.splits.guarded_exec import _kill_process_group
from rbpbench.splits.r3r5.contract import GIB, Contract
from rbpbench.splits.r3r5.stops import (
    ExternalResourceStop,
    ResourceLimitStop,
    SchedulerTimeStop,
    ToolFailureStop,
)
from rbpbench.splits.resource_probe_r2 import ResourceMonitors, classify_mmseqs_diagnostics

DEADLINE_STAGE = "stage_timeout"
DEADLINE_BUDGET = "audit_budget"
DEADLINE_RESERVE = "packaging_reserve"
_MAX_SAMPLES_RETAINED = 4000


@dataclass(frozen=True)
class Deadline:
    """Monotonic deadline plus which limit makes it binding."""

    at: float
    kind: str

    def stop(self, message: str):
        if self.kind == DEADLINE_RESERVE:
            return SchedulerTimeStop(message)
        return ResourceLimitStop(message)


def pre_launch_checks(contract: Contract, monitors: ResourceMonitors, *, label: str, disk_path: Path) -> dict:
    r = contract.resources
    installed = monitors.installed_ram_gib()
    if installed is None:
        raise ExternalResourceStop(f"installed RAM is unmeasurable before {label}")
    if installed < r.min_installed_or_allocated_ram_gib:
        raise ExternalResourceStop(f"installed RAM {installed:.1f} GiB < {r.min_installed_or_allocated_ram_gib} before {label}")
    available = monitors.available_ram_gib()
    if available is None or available < r.min_available_ram_gib:
        raise ExternalResourceStop(f"available RAM {available!r} GiB < {r.min_available_ram_gib} before {label}")
    free = monitors.free_disk_gib(disk_path)
    if free < r.live_free_floor_gib:
        raise ExternalResourceStop(f"free space {free:.2f} GiB < live floor {r.live_free_floor_gib} before {label}")
    raw_pressure, state = monitors.memory_pressure()
    if state != "normal":
        raise ExternalResourceStop(f"memory state before {label} is {state!r} ({raw_pressure!r})")
    return {"installed_ram_gib": installed, "available_ram_gib": available, "free_disk_gib": free}


def run_child(
    command: ToolCommand,
    *,
    contract: Contract,
    monitors: ResourceMonitors,
    log_dir: Path,
    owned_dir: Path,
    width: int,
    deadline: Deadline,
    binary: dict,
    poll_interval: float | None = None,
) -> dict:
    """Runs one MMseqs2 child under live supervision and returns evidence."""
    r = contract.resources
    ceiling_bytes = r.ceiling_gib(width) * GIB
    poll = r.poll_interval_seconds if poll_interval is None else poll_interval
    log_dir.mkdir(parents=True, exist_ok=True)
    owned_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:12]
    out_path = log_dir / f"{command.tool}.{token}.stdout.log"
    err_path = log_dir / f"{command.tool}.{token}.stderr.log"
    pre = pre_launch_checks(contract, monitors, label=command.tool, disk_path=owned_dir)
    swap_raw0, swap0 = monitors.swap_used_bytes()
    if swap0 is None:
        raise ExternalResourceStop(f"swap use is unmeasurable before {command.tool}")
    if monitors.clock() >= deadline.at:
        raise deadline.stop(f"{command.tool}: no time remains before the {deadline.kind} deadline")
    start = monitors.clock()
    ev: dict = {
        "pre_launch": pre, "swap_raw_start": swap_raw0, "peak_rss_kib": 0, "min_free_disk_gib": pre["free_disk_gib"],
        "peak_owned_bytes": 0, "max_swap_increase_bytes": 0, "min_available_ram_gib": pre["available_ram_gib"],
        "samples": [], "sample_count": 0, "deadline_kind": deadline.kind,
        "deadline_seconds_from_start": deadline.at - start,
    }

    def check(pid: int | None) -> Exception | None:
        rss = monitors.process_tree_rss_kib(pid) if pid is not None else 0
        free = monitors.free_disk_gib(owned_dir)
        size = monitors.dir_size_bytes(owned_dir)
        available = monitors.available_ram_gib()
        swap_raw, swap = monitors.swap_used_bytes()
        p_raw, p_state = monitors.memory_pressure()
        now = monitors.clock()
        sample = {"t": now - start, "rss_kib": rss, "free_disk_gib": free, "owned_bytes": size,
                  "available_ram_gib": available, "swap_raw": swap_raw[-200:] if swap_raw else swap_raw,
                  "pressure_state": p_state}
        ev["sample_count"] += 1
        if len(ev["samples"]) < _MAX_SAMPLES_RETAINED:
            ev["samples"].append(sample)
        else:  # keep a bounded, evenly thinned record; extrema are kept separately
            ev["samples"][ev["sample_count"] % _MAX_SAMPLES_RETAINED] = sample
        if rss is None or swap is None or available is None:
            return ExternalResourceStop(f"{command.tool}: a live RSS/swap/available-memory measurement is unavailable")
        ev["peak_rss_kib"] = max(ev["peak_rss_kib"], rss)
        ev["min_free_disk_gib"] = min(ev["min_free_disk_gib"], free)
        ev["peak_owned_bytes"] = max(ev["peak_owned_bytes"], size)
        ev["min_available_ram_gib"] = min(ev["min_available_ram_gib"], available)
        ev["max_swap_increase_bytes"] = max(ev["max_swap_increase_bytes"], swap - swap0)
        if size > ceiling_bytes:
            return ResourceLimitStop(
                f"{command.tool}: job-owned output {size / GIB:.2f} GiB exceeds the {r.ceiling_gib(width)}-GiB width-{width} ceiling"
            )
        if free < r.live_free_floor_gib:
            return ExternalResourceStop(f"{command.tool}: free space fell to {free:.2f} GiB (< {r.live_free_floor_gib})")
        if available < r.min_available_ram_gib:
            return ExternalResourceStop(f"{command.tool}: available RAM fell to {available:.2f} GiB (< {r.min_available_ram_gib})")
        if p_state != "normal":
            return ExternalResourceStop(f"{command.tool}: memory state {p_state!r} ({p_raw!r})")
        if swap - swap0 > r.max_swap_increase_gib * GIB:
            return ExternalResourceStop(f"{command.tool}: swap grew {(swap - swap0) / GIB:.2f} GiB (> {r.max_swap_increase_gib})")
        if now > deadline.at:
            return deadline.stop(f"{command.tool}: {deadline.kind} deadline reached after {now - start:.1f}s")
        return None

    with out_path.open("w") as so, err_path.open("w") as se:
        proc = subprocess.Popen(list(command.argv), shell=False, stdout=so, stderr=se, text=True, start_new_session=True)
        rc: int | None = None
        try:
            while rc is None:
                try:
                    rc = proc.wait(timeout=poll)
                except subprocess.TimeoutExpired:
                    pass
                if rc is None:
                    violation = check(proc.pid)
                    if violation is not None:
                        _kill_process_group(proc)
                        raise violation
        except BaseException:
            # A signal, violation, or any other interruption terminates the
            # complete process group exactly once before propagating.
            if proc.poll() is None:
                _kill_process_group(proc)
            raise
    elapsed = monitors.clock() - start
    final = check(None)
    if final is not None:
        raise final
    if rc != 0:
        kind = "killed by signal (possible OOM)" if rc < 0 else f"exited {rc}"
        raise ToolFailureStop(f"{command.tool} {kind}: {format_command(command.argv)}; see {err_path.name}")
    child_peak = monitors.children_peak_rss_kib()
    if child_peak is None:
        raise ExternalResourceStop(f"{command.tool}: post-run child peak RSS is unavailable")
    ev["peak_rss_kib"] = max(ev["peak_rss_kib"], child_peak)
    diagnostics = classify_mmseqs_diagnostics(err_path.read_text(errors="replace") + "\n" + out_path.read_text(errors="replace"))
    if diagnostics["fatal"]:
        raise ToolFailureStop(f"{command.tool} emitted fatal MMseqs2 diagnostics: {diagnostics['fatal'][:3]}")
    return {
        "tool": command.tool,
        "argv": list(command.argv),
        "command_text": format_command(command.argv),
        "returncode": rc,
        "elapsed_seconds": elapsed,
        "stdout_log": out_path.name, "stdout_sha256": sha256_file(out_path),
        "stderr_log": err_path.name, "stderr_sha256": sha256_file(err_path),
        "advisory_diagnostics": diagnostics["advisory"],
        "binary": binary,
        **ev,
    }


__all__ = ["Deadline", "DEADLINE_STAGE", "DEADLINE_BUDGET", "DEADLINE_RESERVE", "pre_launch_checks", "run_child"]
