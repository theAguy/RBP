"""Environment preflight: report host facts and fail closed on rule violations.

The parent task binds real mapping to one named host (local 16-GiB macOS
x86_64) and forbids it on Claude's constrained execution environment. Because
this module cannot trust a hostname, the caller must declare which role it is
running as; the preflight then fails closed rather than trusting detected
resources alone.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rbpbench.coordinates.commands import resolve_version
from rbpbench.coordinates.config import ResourceLimits

DEV_VM = "dev_vm"
APPROVED_MAC = "approved_mac"
HOST_ROLES = (DEV_VM, APPROVED_MAC)


def detect_physical_ram_gib() -> float | None:
    system = platform.system()
    try:
        if system == "Linux":
            with open("/proc/meminfo") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        kib = int(line.split()[1])
                        return kib / (1024 * 1024)
            return None
        if system == "Darwin":
            completed = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10, check=False
            )
            if completed.returncode == 0 and completed.stdout.strip():
                return int(completed.stdout.strip()) / (1024**3)
            return None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return None


def detect_free_disk_gib(path: Path) -> float:
    usage = shutil.disk_usage(path)
    return usage.free / (1024**3)


@dataclass(frozen=True)
class PreflightReport:
    host_role: str
    os_name: str
    architecture: str
    cpu_count: int | None
    physical_ram_gib: float | None
    free_disk_gib: float
    tool_versions: dict
    input_hashes: dict
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0

    def to_dict(self) -> dict:
        return {
            "host_role": self.host_role,
            "os_name": self.os_name,
            "architecture": self.architecture,
            "cpu_count": self.cpu_count,
            "physical_ram_gib": self.physical_ram_gib,
            "free_disk_gib": self.free_disk_gib,
            "tool_versions": self.tool_versions,
            "input_hashes": self.input_hashes,
            "violations": list(self.violations),
        }


def run_preflight(
    *,
    host_role: str,
    resources: ResourceLimits,
    disk_path: Path,
    input_hashes: dict | None = None,
    allow_mapping: bool,
) -> PreflightReport:
    if host_role not in HOST_ROLES:
        raise ValueError(f"unknown host_role {host_role!r}; expected one of {HOST_ROLES}")

    physical_ram_gib = detect_physical_ram_gib()
    free_disk_gib = detect_free_disk_gib(disk_path)
    tool_versions = {
        "bwa": resolve_version(["bwa"]),
        "minimap2": resolve_version(["minimap2", "--version"]),
        "seqkit": resolve_version(["seqkit", "version"]),
    }

    violations: list[str] = []

    if allow_mapping and host_role != APPROVED_MAC:
        violations.append(
            f"mapping was requested on host_role={host_role!r}; only {APPROVED_MAC!r} may run real mapping"
        )

    if allow_mapping and host_role == APPROVED_MAC:
        if physical_ram_gib is not None and physical_ram_gib < resources.min_ram_gib_for_mapping:
            violations.append(
                f"detected {physical_ram_gib:.1f} GiB RAM, below the required "
                f"{resources.min_ram_gib_for_mapping} GiB for mapping"
            )
        if free_disk_gib < resources.min_free_disk_gib:
            violations.append(
                f"detected {free_disk_gib:.1f} GiB free disk, below the required "
                f"{resources.min_free_disk_gib} GiB before a mapping run"
            )

    return PreflightReport(
        host_role=host_role,
        os_name=platform.system(),
        architecture=platform.machine(),
        cpu_count=os.cpu_count(),
        physical_ram_gib=physical_ram_gib,
        free_disk_gib=free_disk_gib,
        tool_versions=tool_versions,
        input_hashes=dict(input_hashes or {}),
        violations=tuple(violations),
    )


__all__ = [
    "DEV_VM",
    "APPROVED_MAC",
    "HOST_ROLES",
    "PreflightReport",
    "run_preflight",
    "detect_physical_ram_gib",
    "detect_free_disk_gib",
]
