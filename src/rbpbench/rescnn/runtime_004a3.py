"""Fail-closed GPU identity and resource gates for Task 004A-3."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import resource
import shutil
import time

from rbpbench.discovery_004a3 import (
    DISCOVERY_COMMAND_FIELDS,
    ResCNN004A3RuntimeError,
    _require_command_evidence,
    require_discovery_install_policy,
    require_discovery_payload,
)

SHA256 = re.compile(r"[0-9a-f]{64}")


def require_allocated_gpu(
    *, required_gpu_name: str, allocated_gpu_uuid: str,
    actual_gpu_name: str, torch_gpu_uuid: str | None,
) -> tuple[str, str]:
    """Bind the CUDA process to the reviewed model policy and allocation UUID."""

    for name, value in (
        ("required GPU name", required_gpu_name),
        ("allocated GPU UUID", allocated_gpu_uuid),
        ("actual GPU name", actual_gpu_name),
    ):
        if not isinstance(value, str) or not value or "\n" in value:
            raise ResCNN004A3RuntimeError(f"{name} is empty or malformed")
    if required_gpu_name != "RECORD_ONLY" and actual_gpu_name != required_gpu_name:
        raise ResCNN004A3RuntimeError("allocated GPU model does not match reviewed policy")
    normalized_allocated_uuid = _normalize_gpu_uuid(allocated_gpu_uuid)
    if torch_gpu_uuid is not None and _normalize_gpu_uuid(str(torch_gpu_uuid)) != normalized_allocated_uuid:
        raise ResCNN004A3RuntimeError("PyTorch GPU UUID does not match allocated GPU UUID")
    return actual_gpu_name, normalized_allocated_uuid


def _normalize_gpu_uuid(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ResCNN004A3RuntimeError("GPU UUID is empty or malformed")
    normalized = value.strip().lower()
    if normalized.startswith("gpu-"):
        normalized = normalized[4:]
    if re.fullmatch(
        r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", normalized,
    ) is None:
        raise ResCNN004A3RuntimeError("GPU UUID is empty or malformed")
    return normalized


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
