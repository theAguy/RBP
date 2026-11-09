"""Fail-closed GPU identity and resource gates for Task 004A-3."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import resource
import shutil
import time


SHA256 = re.compile(r"[0-9a-f]{64}")


class ResCNN004A3RuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeIdentity:
    gpu_name: str
    gpu_uuid: str
    runtime_manifest_sha256: str


@dataclass(frozen=True)
class ResourceUse:
    physical_gpu_bytes: int
    peak_gpu_reserved_bytes: int
    requested_ram_bytes: int
    peak_rss_bytes: int


def require_identity_match(primary: RuntimeIdentity, repeat: RuntimeIdentity) -> None:
    for value in (
        primary.gpu_name, primary.gpu_uuid, repeat.gpu_name, repeat.gpu_uuid,
    ):
        if not value or "\n" in value:
            raise ResCNN004A3RuntimeError("GPU identity is empty or malformed")
    for digest in (primary.runtime_manifest_sha256, repeat.runtime_manifest_sha256):
        if SHA256.fullmatch(digest) is None:
            raise ResCNN004A3RuntimeError("runtime-manifest digest is malformed")
    if primary != repeat:
        raise ResCNN004A3RuntimeError("primary/repeat GPU or runtime identity mismatch")


def require_memory_headroom(resource: ResourceUse) -> None:
    for value in resource.__dict__.values():
        if not isinstance(value, int) or value <= 0:
            raise ResCNN004A3RuntimeError("resource readings must be positive integers")
    if resource.peak_gpu_reserved_bytes > resource.physical_gpu_bytes * 0.8:
        raise ResCNN004A3RuntimeError("peak GPU reserved memory exceeds 80%")
    if resource.peak_rss_bytes > resource.requested_ram_bytes * 0.8:
        raise ResCNN004A3RuntimeError("peak RSS exceeds 80% of requested RAM")


def require_discovery_install_policy(payload: dict) -> str:
    reachable = payload.get("compute_node_required_channels_reachable")
    location = payload.get("site_approved_install_location")
    if reachable not in (True, False):
        raise ResCNN004A3RuntimeError("discovery lacks compute-node channel reachability")
    if location not in ("login_node", "cpu_job"):
        raise ResCNN004A3RuntimeError("discovery lacks an approved install location")
    return str(location)


@dataclass
class LiveResourceMonitor:
    physical_gpu_bytes: int
    requested_ram_bytes: int
    output_path: Path
    minimum_free_disk_bytes: int
    deadline_monotonic: float
    gpu_reserved_reader: object
    rss_reader: object
    disk_free_reader: object = None
    clock: object = time.monotonic
    peak_gpu_reserved_bytes: int = 0
    peak_rss_bytes: int = 0

    def __post_init__(self):
        if self.disk_free_reader is None:
            self.disk_free_reader = lambda path: shutil.disk_usage(path).free

    def observe(self) -> dict[str, int]:
        if self.clock() > self.deadline_monotonic:
            raise ResCNN004A3RuntimeError("resource-smoke deadline exceeded")
        gpu = int(self.gpu_reserved_reader())
        rss = int(self.rss_reader())
        free = int(self.disk_free_reader(self.output_path))
        self.peak_gpu_reserved_bytes = max(self.peak_gpu_reserved_bytes, gpu)
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
        require_memory_headroom(ResourceUse(
            self.physical_gpu_bytes, self.peak_gpu_reserved_bytes,
            self.requested_ram_bytes, self.peak_rss_bytes,
        ))
        if free < self.minimum_free_disk_bytes:
            raise ResCNN004A3RuntimeError("free disk fell below the reviewed floor")
        return {
            "peak_gpu_reserved_bytes": self.peak_gpu_reserved_bytes,
            "peak_rss_bytes": self.peak_rss_bytes,
            "free_disk_bytes": free,
        }


def linux_peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
