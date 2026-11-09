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


DISCOVERY_COMMAND_FIELDS = (
    "slurm_partition_detail", "sinfo_gpu_inventory", "os_release",
    "uname_kernel", "glibc_version", "conda_command", "conda_version",
    "conda_info", "module_avail",
    "python3_version", "quota_s", "lfs_quota", "df_home",
)


def _require_command_evidence(payload: dict, key: str) -> None:
    evidence = payload.get(key)
    if not isinstance(evidence, dict):
        raise ResCNN004A3RuntimeError(f"discovery lacks command evidence: {key}")
    if set(evidence) != {"available", "returncode", "stdout", "stderr"}:
        raise ResCNN004A3RuntimeError(f"discovery command evidence is malformed: {key}")
    if not isinstance(evidence["available"], bool):
        raise ResCNN004A3RuntimeError(f"discovery availability is malformed: {key}")
    if evidence["returncode"] is not None and not isinstance(evidence["returncode"], int):
        raise ResCNN004A3RuntimeError(f"discovery return code is malformed: {key}")
    if not isinstance(evidence["stdout"], str) or not isinstance(evidence["stderr"], str):
        raise ResCNN004A3RuntimeError(f"discovery output is malformed: {key}")


def require_discovery_payload(payload: dict) -> dict:
    """Validate the complete data-free evidence needed by 004A-3C."""

    required = {
        "schema_version", "host", "system", "machine", "allocated_cpus",
        "slurm_job_id", "slurm_partition", "installed_ram_bytes",
        "available_ram_bytes", "free_disk_bytes", "quota_available_bytes",
        "operator_quota_available_bytes", "slurm_limit_seconds",
        "compute_node_required_channels_reachable",
        "site_approved_install_location", "gpu_csv", "nvidia_smi",
        "requires_owner_review_before_lock",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ResCNN004A3RuntimeError(f"discovery payload is incomplete: {missing!r}")
    if payload["schema_version"] != "task004a3_discovery_v2":
        raise ResCNN004A3RuntimeError("discovery schema mismatch")
    for key in ("host", "system", "machine", "slurm_job_id", "slurm_partition"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ResCNN004A3RuntimeError(f"discovery identity is empty: {key}")
    if payload["requires_owner_review_before_lock"] is not True:
        raise ResCNN004A3RuntimeError("discovery does not require owner review before lock")
    for key in DISCOVERY_COMMAND_FIELDS:
        _require_command_evidence(payload, key)
    for key in (
        "slurm_partition_detail", "sinfo_gpu_inventory", "os_release",
        "uname_kernel", "glibc_version", "python3_version", "df_home",
    ):
        evidence = payload[key]
        if (
            evidence["available"] is not True
            or evidence["returncode"] != 0
            or not (evidence["stdout"] or evidence["stderr"]).strip()
        ):
            raise ResCNN004A3RuntimeError(
                f"required discovery command did not complete cleanly: {key}"
            )
    for key in (
        "allocated_cpus", "installed_ram_bytes", "available_ram_bytes",
        "free_disk_bytes", "quota_available_bytes",
        "operator_quota_available_bytes", "slurm_limit_seconds",
    ):
        if not isinstance(payload[key], int) or payload[key] <= 0:
            raise ResCNN004A3RuntimeError(f"discovery value must be positive: {key}")
    if payload["quota_available_bytes"] != payload["operator_quota_available_bytes"]:
        raise ResCNN004A3RuntimeError("discovery quota fields disagree")
    if not isinstance(payload["gpu_csv"], str) or not payload["gpu_csv"].strip():
        raise ResCNN004A3RuntimeError("discovery GPU evidence is empty")
    if not isinstance(payload["nvidia_smi"], str) or not payload["nvidia_smi"].strip():
        raise ResCNN004A3RuntimeError("discovery nvidia-smi evidence is empty")
    require_discovery_install_policy(payload)
    return payload


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
    if torch_gpu_uuid is not None and str(torch_gpu_uuid) != allocated_gpu_uuid:
        raise ResCNN004A3RuntimeError("PyTorch GPU UUID does not match allocated GPU UUID")
    return actual_gpu_name, allocated_gpu_uuid


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
