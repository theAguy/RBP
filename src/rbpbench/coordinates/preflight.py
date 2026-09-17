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
from rbpbench.coordinates.config import ResourceLimits, ToolsConfig
from rbpbench.data.audit import sha256_file

DEV_VM = "dev_vm"
APPROVED_MAC = "approved_mac"
HOST_ROLES = (DEV_VM, APPROVED_MAC)

APPROVED_OS = "Darwin"
APPROVED_ARCH = "x86_64"


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
    allow_mapping: bool,
    tools: ToolsConfig | None = None,
    threads: int = 1,
    required_input_paths: dict[str, Path] | None = None,
) -> PreflightReport:
    """Report host facts and fail closed before any real mapping is allowed.

    A caller declaring ``host_role=approved_mac`` is not, by itself, evidence
    that mapping may proceed: when ``allow_mapping`` is set, every one of the
    following must be independently verified from detected/measured facts, or
    the report fails closed with ``ok=False``:

    - detected OS/architecture match the one approved host (Darwin/x86_64);
    - physical RAM is *known* (never treated as passing when undetectable,
      e.g. on Linux without ``/proc/meminfo`` or an unrecognized platform)
      and meets ``resources.min_ram_gib_for_mapping``;
    - free disk meets ``resources.min_free_disk_gib``;
    - the requested thread count does not exceed ``resources.max_threads``;
    - ``bwa``, ``minimap2``, and ``seqkit`` are all present on PATH *and*
      report the pinned versions from ``tools``;
    - every path in ``required_input_paths`` (references and reads) exists
      and its SHA-256 hash is computed and recorded, never merely assumed.
    """
    if host_role not in HOST_ROLES:
        raise ValueError(f"unknown host_role {host_role!r}; expected one of {HOST_ROLES}")

    physical_ram_gib = detect_physical_ram_gib()
    free_disk_gib = detect_free_disk_gib(disk_path)
    os_name = platform.system()
    architecture = platform.machine()
    tool_versions = {
        "bwa": resolve_version(["bwa"]),
        "minimap2": resolve_version(["minimap2", "--version"]),
        "seqkit": resolve_version(["seqkit", "version"]),
    }
    required_input_paths = required_input_paths or {}
    input_hashes: dict[str, str] = {}

    violations: list[str] = []

    if allow_mapping and host_role != APPROVED_MAC:
        violations.append(
            f"mapping was requested on host_role={host_role!r}; only {APPROVED_MAC!r} may run real mapping"
        )

    if allow_mapping and host_role == APPROVED_MAC:
        if os_name != APPROVED_OS or architecture != APPROVED_ARCH:
            violations.append(
                f"detected {os_name}/{architecture}, but only {APPROVED_OS}/{APPROVED_ARCH} "
                "is the approved mapping host; host_role alone is not evidence"
            )
        if physical_ram_gib is None:
            violations.append("physical RAM could not be determined; refusing to assume it is sufficient")
        elif physical_ram_gib < resources.min_ram_gib_for_mapping:
            violations.append(
                f"detected {physical_ram_gib:.1f} GiB RAM, below the required "
                f"{resources.min_ram_gib_for_mapping} GiB for mapping"
            )
        if free_disk_gib < resources.min_free_disk_gib:
            violations.append(
                f"detected {free_disk_gib:.1f} GiB free disk, below the required "
                f"{resources.min_free_disk_gib} GiB before a mapping run"
            )
        if threads > resources.max_threads:
            violations.append(f"requested {threads} threads exceeds the max of {resources.max_threads}")

        if tools is None:
            violations.append("no pinned tool versions supplied to verify against")
        else:
            pinned = {
                "bwa": tools.bwa_version,
                "minimap2": tools.minimap2_version,
                "seqkit": tools.seqkit_version,
            }
            for tool, expected_version in pinned.items():
                detected = tool_versions.get(tool)
                if detected is None:
                    violations.append(f"required tool {tool!r} was not found on PATH")
                elif expected_version not in detected:
                    violations.append(
                        f"{tool} version mismatch: expected {expected_version!r}, detected {detected!r}"
                    )

        if not required_input_paths:
            violations.append("no required input/reference paths supplied to hash-verify")
        for name, path in required_input_paths.items():
            path = Path(path)
            if not path.is_file():
                violations.append(f"required input {name!r} not found at {path}")
                continue
            input_hashes[name] = sha256_file(path)

    return PreflightReport(
        host_role=host_role,
        os_name=os_name,
        architecture=architecture,
        cpu_count=os.cpu_count(),
        physical_ram_gib=physical_ram_gib,
        free_disk_gib=free_disk_gib,
        tool_versions=tool_versions,
        input_hashes=input_hashes,
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
