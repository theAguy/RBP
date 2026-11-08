"""Fail-closed local resource evidence for the Task 004A-2 CPU smoke."""

from __future__ import annotations

from dataclasses import dataclass
import os
import platform
import re
import resource
import shutil
import subprocess
from pathlib import Path


GIB = 1024 ** 3
NUMERICAL_THREADS = 4


class ResCNNResourceError(RuntimeError):
    pass


def normalize_ru_maxrss_bytes(value: int | float, system: str) -> int:
    if value is None or float(value) < 0:
        raise ResCNNResourceError("peak RSS reading is unavailable")
    if system == "Darwin":
        return int(value)
    if system == "Linux":
        return int(value) * 1024
    raise ResCNNResourceError(f"unsupported peak-RSS platform: {system}")


def parse_macos_available_memory_bytes(vm_stat: str) -> int:
    page_match = re.search(r"page size of\s+(\d+)\s+bytes", vm_stat)
    if not page_match:
        raise ResCNNResourceError("vm_stat did not report page size")
    page_size = int(page_match.group(1))
    values: dict[str, int] = {}
    for label, raw in re.findall(r"^(Pages free|Pages inactive|Pages speculative):\s+(\d+)\.", vm_stat, re.M):
        values[label] = int(raw)
    required = {"Pages free", "Pages inactive", "Pages speculative"}
    if set(values) != required:
        raise ResCNNResourceError("vm_stat is missing free/inactive/speculative pages")
    return sum(values.values()) * page_size


def detect_macos_available_memory_bytes() -> int:
    completed = subprocess.run(
        ["/usr/bin/vm_stat"], check=True, text=True, capture_output=True, timeout=10,
    )
    return parse_macos_available_memory_bytes(completed.stdout)


def configure_exact_threads(torch_module, *, count: int = NUMERICAL_THREADS) -> dict[str, object]:
    if count != NUMERICAL_THREADS:
        raise ResCNNResourceError("Task 004A-2 requires exactly four threads")
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = str(count)
    torch_module.set_num_threads(count)
    if int(torch_module.get_num_threads()) != count:
        raise ResCNNResourceError("PyTorch thread count did not take effect")
    return {
        "numerical_threads": count,
        "environment": {
            name: os.environ[name]
            for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")
        },
    }


@dataclass(frozen=True)
class ResourceSnapshot:
    system: str
    installed_ram_bytes: int
    available_ram_bytes: int
    free_disk_bytes: int
    peak_rss_bytes: int


def local_resource_snapshot(path: Path) -> ResourceSnapshot:
    system = platform.system()
    if system != "Darwin":
        raise ResCNNResourceError(f"Task 004A-2 local run requires macOS, got {system}")
    installed = int(subprocess.run(
        ["/usr/sbin/sysctl", "-n", "hw.memsize"],
        check=True, text=True, capture_output=True, timeout=10,
    ).stdout.strip())
    available = detect_macos_available_memory_bytes()
    free_disk = shutil.disk_usage(Path(path)).free
    peak = normalize_ru_maxrss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, system)
    return ResourceSnapshot(system, installed, available, free_disk, peak)


def require_local_resources(
    snapshot: ResourceSnapshot,
    *,
    minimum_installed: int = 16 * GIB,
    minimum_available: int = 4 * GIB,
    minimum_free_disk: int = 20 * GIB,
    maximum_peak_rss: int = 4 * GIB,
) -> None:
    if snapshot.installed_ram_bytes < minimum_installed:
        raise ResCNNResourceError("installed RAM is below 16 GiB")
    if snapshot.available_ram_bytes < minimum_available:
        raise ResCNNResourceError("available RAM is below 4 GiB")
    if snapshot.free_disk_bytes < minimum_free_disk:
        raise ResCNNResourceError("free disk is below 20 GiB")
    if snapshot.peak_rss_bytes > maximum_peak_rss:
        raise ResCNNResourceError("peak RSS exceeds 4 GiB")
