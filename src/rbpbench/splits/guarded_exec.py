"""Live-guarded MMseqs2 subprocess execution for the Task 002C audit
stages.

Deliberately DUPLICATED (never imported) from
:mod:`rbpbench.splits.runner`'s private helpers of the same shape (process-
group-wide live timeout/disk polling, unconditional final ceiling/floor
recheck), so extending Task 002C's audit orchestration can never
destabilize the already-accepted Task 002B runner module.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from pathlib import Path

from rbpbench.coordinates.commands import format_command
from rbpbench.coordinates.diskbudget import GIB, snapshot
from rbpbench.coordinates.preflight import detect_available_memory_gib, detect_physical_ram_gib
from rbpbench.coordinates.provenance import peak_rss_kib_of_children
from rbpbench.data.audit import sha256_file
from rbpbench.splits import commands as splits_commands


class ResourceGateExceededError(RuntimeError):
    """A resource ceiling/floor was crossed; the candidate generation for
    this attempt is discarded and any prior accepted selection is
    untouched.
    """


def check_installed_ram_or_fail(*, min_installed_ram_gib: float) -> float:
    """Task 002C-1 correction, C5 (docs/reviews/002c1_partition_orchestration_correction_review.md):
    fails closed when installed RAM cannot be measured OR falls below the
    configured minimum -- mirrors the already-established Task 002B
    semantics (``rbpbench.splits.runner._recheck_installed_ram_and_disk_now``),
    duplicated (never imported) here so extending Task 002C can never
    destabilize the accepted Task 002B runner.
    """
    installed_ram_gib = detect_physical_ram_gib()
    if installed_ram_gib is None or installed_ram_gib < min_installed_ram_gib:
        raise ResourceGateExceededError(
            f"installed RAM {installed_ram_gib!r} GiB is below the required {min_installed_ram_gib:.2f} GiB "
            "minimum (None is a hard failure)"
        )
    return installed_ram_gib


def check_available_memory_before_launch_or_fail(*, min_available_memory_gib_before_launch: float, label: str) -> float:
    """A numeric available/reclaimable-memory measurement is required
    immediately before EVERY MMseqs2 subprocess launch; an undetectable
    (``None``) reading is a hard failure, never a silent pass (C5).
    """
    available_before = detect_available_memory_gib()
    if available_before is None or available_before < min_available_memory_gib_before_launch:
        raise ResourceGateExceededError(
            f"available memory before launching {label!r} is {available_before!r} GiB, below the required "
            f"{min_available_memory_gib_before_launch:.2f} GiB launch gate (None is a hard failure)"
        )
    return available_before


def check_probe_memory_gates_or_fail(
    *,
    peak_rss_kib: int,
    max_peak_memory_gib: float,
    min_available_memory_gib_before_next_stage: float,
    label: str,
) -> dict:
    """The width-probe-specific post-run gates (C5): fails the probe if
    peak RSS exceeded ``max_peak_memory_gib`` (the 10-GiB probe peak gate)
    or the post-probe available memory fell below
    ``min_available_memory_gib_before_next_stage`` (the 10-GiB post-probe
    gate) -- both checked, never only one.
    """
    peak_gib = peak_rss_kib / (1024**2)
    if peak_gib > max_peak_memory_gib:
        raise ResourceGateExceededError(
            f"{label} peak RSS {peak_gib:.2f} GiB exceeded the {max_peak_memory_gib:.2f} GiB probe-peak gate"
        )
    available_after = detect_available_memory_gib()
    if available_after is None or available_after < min_available_memory_gib_before_next_stage:
        raise ResourceGateExceededError(
            f"available memory after {label!r} is {available_after!r} GiB, below the required "
            f"{min_available_memory_gib_before_next_stage:.2f} GiB gate required before the next stage "
            "(None is a hard failure)"
        )
    return {"peak_rss_gib": peak_gib, "available_memory_gib_after": available_after}


class ResourceTerminatedError(RuntimeError):
    """A live disk/timeout guard killed an MMseqs2 subprocess's entire
    process group before natural completion.
    """


def directory_size_bytes(root: Path) -> int:
    root = Path(root)
    if not root.exists():
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            candidate = Path(dirpath) / name
            if candidate.is_file():
                total += candidate.stat().st_size
    return total


def nearest_existing_ancestor(path: Path) -> Path:
    current = Path(path)
    for _ in range(64):
        if current.exists():
            return current
        if current.parent == current:
            return current
        current = current.parent
    return current


def check_free_disk_or_fail(*, disk_path: Path, min_free_disk_gib: float, label: str) -> dict:
    current = snapshot(nearest_existing_ancestor(disk_path))
    if current.free_gib < min_free_disk_gib:
        raise ResourceGateExceededError(
            f"free disk is {current.free_gib:.2f} GiB before {label!r}, below the required "
            f"{min_free_disk_gib:.2f} GiB floor"
        )
    return current.to_dict()


def check_combined_ceiling_or_discard(*, output_dir: Path, max_new_disk_gib: float) -> dict:
    total_gib = directory_size_bytes(output_dir) / GIB
    if total_gib > max_new_disk_gib:
        raise ResourceGateExceededError(
            f"combined Task 002C artifact directory reached {total_gib:.2f} GiB, over the "
            f"{max_new_disk_gib:.2f} GiB ceiling"
        )
    return {"combined_output_gib": total_gib}


def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_guarded_mmseqs(
    command,
    *,
    log_dir: Path,
    timeout_seconds: float,
    output_dir: Path,
    max_new_disk_gib: float,
    min_free_disk_gib: float,
    poll_interval: float,
    binary=None,
) -> dict:
    """Runs ``command.argv`` (``shell=False``) as its own process group,
    polling every ``poll_interval`` seconds WHILE it runs for elapsed time
    past ``timeout_seconds``, combined ``output_dir`` size past
    ``max_new_disk_gib``, and free disk below ``min_free_disk_gib``. Any
    violation kills the WHOLE process group and raises
    :class:`ResourceTerminatedError`. An unconditional final ceiling/floor
    recheck runs once immediately after every exit, whether or not the live
    polling branch above ever triggered.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    invocation_id = uuid.uuid4().hex[:16]
    stdout_path = log_dir / f"{command.tool}.{invocation_id}.stdout.log"
    stderr_path = log_dir / f"{command.tool}.{invocation_id}.stderr.log"
    if binary is None:
        binary = splits_commands.resolve_mmseqs_binary_provenance(command.argv[0])

    start = time.monotonic()
    with stdout_path.open("w") as out_handle, stderr_path.open("w") as err_handle:
        process = subprocess.Popen(
            list(command.argv), shell=False, stdout=out_handle, stderr=err_handle, text=True, start_new_session=True
        )
        returncode: int | None = None
        while returncode is None:
            try:
                returncode = process.wait(timeout=poll_interval)
                break
            except subprocess.TimeoutExpired:
                pass

            elapsed = time.monotonic() - start
            violation: str | None = None
            if elapsed > timeout_seconds:
                violation = f"timed out after {timeout_seconds}s"
            else:
                total_gib = directory_size_bytes(output_dir) / GIB
                if total_gib > max_new_disk_gib:
                    violation = f"combined output directory reached {total_gib:.2f} GiB, over the {max_new_disk_gib:.2f} GiB ceiling"
                else:
                    free_gib = snapshot(nearest_existing_ancestor(output_dir)).free_gib
                    if free_gib < min_free_disk_gib:
                        violation = f"free disk fell to {free_gib:.2f} GiB, below the {min_free_disk_gib:.2f} GiB floor"
            if violation is not None:
                _kill_process_group(process)
                raise ResourceTerminatedError(
                    f"{command.tool} {violation}: {format_command(command.argv)} (process group terminated)"
                )
    elapsed_total = time.monotonic() - start
    if returncode != 0:
        raise splits_commands.MmseqsExecutionError(
            f"{command.tool} exited {returncode}: {format_command(command.argv)}; see {stderr_path}"
        )
    total_gib_at_finish = directory_size_bytes(output_dir) / GIB
    if total_gib_at_finish > max_new_disk_gib:
        raise ResourceGateExceededError(
            f"{command.tool} final combined output directory reached {total_gib_at_finish:.2f} GiB, over the "
            f"{max_new_disk_gib:.2f} GiB ceiling immediately after exit: {format_command(command.argv)}"
        )
    finish_disk = snapshot(nearest_existing_ancestor(output_dir))
    if finish_disk.free_gib < min_free_disk_gib:
        raise ResourceGateExceededError(
            f"{command.tool} final free disk is {finish_disk.free_gib:.2f} GiB, below the required "
            f"{min_free_disk_gib:.2f} GiB floor immediately after exit: {format_command(command.argv)}"
        )
    return {
        "tool": command.tool,
        "command_text": format_command(command.argv),
        "elapsed_seconds": elapsed_total,
        "stdout_path": str(stdout_path),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_path": str(stderr_path),
        "stderr_sha256": sha256_file(stderr_path),
        "binary": binary.to_dict(),
        "output_dir_gib_at_finish": total_gib_at_finish,
        "free_disk_gib_at_finish": finish_disk.free_gib,
    }


__all__ = [
    "ResourceGateExceededError",
    "ResourceTerminatedError",
    "directory_size_bytes",
    "nearest_existing_ancestor",
    "check_free_disk_or_fail",
    "check_combined_ceiling_or_discard",
    "check_installed_ram_or_fail",
    "check_available_memory_before_launch_or_fail",
    "check_probe_memory_gates_or_fail",
    "run_guarded_mmseqs",
]
