"""Frozen 004A-4 time and storage projections derived by Task 004A-3."""

from __future__ import annotations

from dataclasses import dataclass
import math


TRAIN_BATCHES = 961
VALIDATION_BATCHES = 225
EPOCHS = 30
CONFIGS = 3
CHECKPOINT_COUNT = EPOCHS * CONFIGS
FULL_RUN_PROCESSES = 1
SAFETY_FACTOR = 1.5
# The public Newton partition reports MaxTime=UNLIMITED.  The project keeps a
# finite ceiling of its own for the later single-seed 004A-4 job.  This is an
# operational stop limit, not an estimate of expected runtime.
PROJECT_004A4_SLURM_LIMIT_SECONDS = 12 * 60 * 60


class ResCNN004A3ProjectionError(RuntimeError):
    pass


def reviewed_slurm_limit_seconds(bundle_config: dict) -> int:
    value = bundle_config.get("slurm_limit_seconds")
    if not isinstance(value, int) or value <= 0:
        raise ResCNN004A3ProjectionError(
            "bundle lacks a positive reviewed 004A-4 Slurm limit"
        )
    return value


@dataclass(frozen=True)
class TimeInputs:
    train_batch_p95_seconds: float
    validation_batch_p95_seconds: float
    full_metrics_p95_seconds: float
    scheduler_p95_seconds: float
    checkpoint_p95_seconds: float
    startup_seconds_per_process: float
    inventory_hash_seconds_per_byte: float
    projected_inventory_bytes: int


@dataclass(frozen=True)
class StorageInputs:
    checkpoint_bytes: int
    noncheckpoint_bytes_per_epoch: int
    largest_atomic_temporary_bytes: int
    environment_bytes: int
    bundle_bytes: int
    return_bytes: int


def _finite_nonnegative(values) -> None:
    if any(not math.isfinite(float(value)) or float(value) < 0 for value in values):
        raise ResCNN004A3ProjectionError("projection inputs must be finite and non-negative")


def project_wall_seconds(inputs: TimeInputs) -> dict[str, float | int]:
    _finite_nonnegative(inputs.__dict__.values())
    per_epoch = (
        TRAIN_BATCHES * inputs.train_batch_p95_seconds
        + VALIDATION_BATCHES * inputs.validation_batch_p95_seconds
        + inputs.full_metrics_p95_seconds
        + inputs.scheduler_p95_seconds
        + inputs.checkpoint_p95_seconds
    )
    inventory_hashing = inputs.inventory_hash_seconds_per_byte * inputs.projected_inventory_bytes
    raw = (
        FULL_RUN_PROCESSES * inputs.startup_seconds_per_process
        + CONFIGS * EPOCHS * per_epoch
        + inventory_hashing
    )
    return {
        "train_batches_per_epoch": TRAIN_BATCHES,
        "validation_batches_per_epoch": VALIDATION_BATCHES,
        "epochs": EPOCHS,
        "configs": CONFIGS,
        "runner_processes": FULL_RUN_PROCESSES,
        "per_epoch_seconds": per_epoch,
        "inventory_hash_seconds": inventory_hashing,
        "raw_seconds": raw,
        "safety_factor": SAFETY_FACTOR,
        "projected_seconds": raw * SAFETY_FACTOR,
    }


def project_storage_bytes(inputs: StorageInputs) -> dict[str, float | int]:
    values = inputs.__dict__.values()
    if any(not isinstance(value, int) or value < 0 for value in values):
        raise ResCNN004A3ProjectionError("storage inputs must be non-negative integers")
    raw = (
        CHECKPOINT_COUNT * inputs.checkpoint_bytes
        + CHECKPOINT_COUNT * inputs.noncheckpoint_bytes_per_epoch
        + inputs.largest_atomic_temporary_bytes
        + inputs.environment_bytes + inputs.bundle_bytes + inputs.return_bytes
    )
    return {
        "checkpoint_count": CHECKPOINT_COUNT,
        "raw_bytes": raw,
        "safety_factor": SAFETY_FACTOR,
        "projected_bytes": math.ceil(raw * SAFETY_FACTOR),
    }


def require_projection_limits(
    *,
    projected_wall_seconds: float,
    slurm_limit_seconds: int,
    projected_storage_bytes: int,
    free_bytes: int,
    quota_available_bytes: int | None,
) -> None:
    if not isinstance(slurm_limit_seconds, int) or slurm_limit_seconds <= 0:
        raise ResCNN004A3ProjectionError("reviewed Slurm limit must be positive")
    if quota_available_bytes is None:
        raise ResCNN004A3ProjectionError("machine-readable quota evidence is required")
    if projected_wall_seconds > slurm_limit_seconds:
        raise ResCNN004A3ProjectionError("projected wall time exceeds reviewed Slurm limit")
    if projected_storage_bytes > free_bytes:
        raise ResCNN004A3ProjectionError("projected storage exceeds free space")
    if projected_storage_bytes > quota_available_bytes:
        raise ResCNN004A3ProjectionError("projected storage exceeds user quota")
