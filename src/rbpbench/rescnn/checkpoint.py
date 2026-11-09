"""Authenticated final and smoke checkpoint roles for Task 004A."""

from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path
import uuid

import torch

from rbpbench.rescnn.config import Task004AConfig, validate_config_object
from rbpbench.rescnn.fidelity import canonical_state_hash


class ResCNNCheckpointError(RuntimeError):
    pass


FINAL_SCHEMA_VERSION = "task004a_checkpoint_v2"
SMOKE_SCHEMA_VERSION = "task004a_smoke_checkpoint_v1"
RESOURCE_SMOKE_SCHEMA_VERSION = "task004a3_resource_checkpoint_v1"
FINAL_ROLE = "final_epoch_model"
SMOKE_ROLE = "local_data_contract_after_one_update"
RESOURCE_SMOKE_ROLE = "gpu_resource_smoke_after_one_epoch"
FORMER_CHECKPOINT_SHA256 = "9c036fceab966442d3cea40146a757114d8b23711c41cba227c3dafd24ff27c3"
REQUIRED_IDENTITY_KEYS = frozenset(
    {"source_sha256", "config_sha256", "environment_sha256", "seed", "config_id"}
)
FROZEN_SEEDS = (20261029, 20261030, 20261031)
FROZEN_CONFIG_IDS = ("submitted", "submitted_no_unknown", "joint_standard")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_identity(identity: dict[str, object]) -> None:
    if set(identity) != REQUIRED_IDENTITY_KEYS:
        raise ResCNNCheckpointError(
            f"checkpoint identity must contain exactly {sorted(REQUIRED_IDENTITY_KEYS)!r}"
        )
    for key in ("source_sha256", "config_sha256", "environment_sha256"):
        value = identity[key]
        if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
            raise ResCNNCheckpointError(f"expected {key} is not a lowercase SHA-256")
    if identity["seed"] not in FROZEN_SEEDS:
        raise ResCNNCheckpointError("expected seed is outside the frozen Task 004A set")
    if identity["config_id"] not in FROZEN_CONFIG_IDS:
        raise ResCNNCheckpointError("expected config_id is outside the frozen Task 004A set")


def _payload(
    *, schema_version: str, artifact_role: str, epoch: int | None,
    training_step: int | None, model, optimizer, scheduler,
    identity: dict[str, object],
) -> dict[str, object]:
    _validate_identity(identity)
    state_hash = canonical_state_hash(model.state_dict())
    return {
        "schema_version": schema_version,
        "artifact_role": artifact_role,
        "epoch": epoch,
        "training_step": training_step,
        **identity,
        "model_state_sha256": state_hash,
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict(),
        "rng_state_included": False,
        "mid_run_resume_supported": False,
        "weights_only_required": True,
    }


def _atomic_save(path: Path, payload: dict[str, object]) -> dict[str, object]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        torch.save(payload, temporary)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "path": path.name,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "model_state_sha256": payload["model_state_sha256"],
        "artifact_role": payload["artifact_role"],
        "epoch": payload["epoch"],
        "training_step": payload["training_step"],
    }


def atomic_save_final_checkpoint(
    path: Path, *, model, optimizer, scheduler,
    config: Task004AConfig, identity: dict[str, object],
) -> dict[str, object]:
    validate_config_object(config)
    return _atomic_save(path, _payload(
        schema_version=FINAL_SCHEMA_VERSION, artifact_role=FINAL_ROLE,
        epoch=config.epochs, training_step=None, model=model,
        optimizer=optimizer, scheduler=scheduler, identity=identity,
    ))


def atomic_save_smoke_checkpoint(
    path: Path, *, model, optimizer, scheduler, identity: dict[str, object],
) -> dict[str, object]:
    return _atomic_save(path, _payload(
        schema_version=SMOKE_SCHEMA_VERSION, artifact_role=SMOKE_ROLE,
        epoch=None, training_step=1, model=model, optimizer=optimizer,
        scheduler=scheduler, identity=identity,
    ))


def atomic_save_resource_smoke_checkpoint(
    path: Path, *, model, optimizer, scheduler, identity: dict[str, object],
    training_steps: int,
) -> dict[str, object]:
    if training_steps != 32:
        raise ResCNNCheckpointError("resource smoke requires exactly 32 training steps")
    return _atomic_save(path, _payload(
        schema_version=RESOURCE_SMOKE_SCHEMA_VERSION,
        artifact_role=RESOURCE_SMOKE_ROLE, epoch=1,
        training_step=training_steps, model=model, optimizer=optimizer,
        scheduler=scheduler, identity=identity,
    ))


def _authenticated_load(
    path: Path, *, expected_sha256: str,
    expected_identity: dict[str, object],
) -> dict:
    actual_sha256 = sha256_file(Path(path))
    if actual_sha256 == FORMER_CHECKPOINT_SHA256:
        raise ResCNNCheckpointError("former checkpoint is forbidden in the Task 004A loader")
    if actual_sha256 != expected_sha256:
        raise ResCNNCheckpointError("checkpoint file SHA-256 mismatch before deserialization")
    _validate_identity(expected_identity)
    if "weights_only" not in inspect.signature(torch.load).parameters:
        raise ResCNNCheckpointError("installed PyTorch does not support weights_only=True")
    payload = torch.load(Path(path), map_location="cpu", weights_only=True)
    if not isinstance(payload, dict):
        raise ResCNNCheckpointError("checkpoint payload is not a dictionary")
    for key, expected in expected_identity.items():
        if payload.get(key) != expected:
            raise ResCNNCheckpointError(f"checkpoint identity mismatch: {key}")
    if payload.get("weights_only_required") is not True:
        raise ResCNNCheckpointError("checkpoint does not require safe loading")
    return payload


def _restore_model(payload: dict, model) -> None:
    if payload.get("mid_run_resume_supported") is not False or payload.get("rng_state_included") is not False:
        raise ResCNNCheckpointError("checkpoint incorrectly advertises mid-run resume")
    if canonical_state_hash(payload["model_state"]) != payload.get("model_state_sha256"):
        raise ResCNNCheckpointError("checkpoint model state hash mismatch")
    model.load_state_dict(payload["model_state"], strict=True)
    if canonical_state_hash(model.state_dict()) != payload["model_state_sha256"]:
        raise ResCNNCheckpointError("restored model state hash mismatch")


def load_final_model_checkpoint(
    path: Path, *, model, config: Task004AConfig,
    expected_sha256: str, expected_identity: dict[str, object],
) -> dict:
    validate_config_object(config)
    payload = _authenticated_load(
        path, expected_sha256=expected_sha256,
        expected_identity=expected_identity,
    )
    if payload.get("schema_version") != FINAL_SCHEMA_VERSION or payload.get("artifact_role") != FINAL_ROLE:
        raise ResCNNCheckpointError("checkpoint is not a final-model artifact")
    if payload.get("epoch") != config.epochs or payload.get("training_step") is not None:
        raise ResCNNCheckpointError("checkpoint is not the frozen final epoch")
    _restore_model(payload, model)
    result = dict(payload)
    result["weights_only_used"] = True
    return result


def load_smoke_model_checkpoint(
    path: Path, *, model, expected_sha256: str,
    expected_identity: dict[str, object],
) -> dict:
    payload = _authenticated_load(
        path, expected_sha256=expected_sha256,
        expected_identity=expected_identity,
    )
    if payload.get("schema_version") != SMOKE_SCHEMA_VERSION or payload.get("artifact_role") != SMOKE_ROLE:
        raise ResCNNCheckpointError("checkpoint is not a local smoke artifact")
    if payload.get("epoch") is not None or payload.get("training_step") != 1:
        raise ResCNNCheckpointError("smoke checkpoint step identity drifted")
    _restore_model(payload, model)
    result = dict(payload)
    result["weights_only_used"] = True
    return result


def load_resource_smoke_model_checkpoint(
    path: Path, *, model, expected_sha256: str,
    expected_identity: dict[str, object],
) -> dict:
    payload = _authenticated_load(
        path, expected_sha256=expected_sha256,
        expected_identity=expected_identity,
    )
    if (
        payload.get("schema_version") != RESOURCE_SMOKE_SCHEMA_VERSION
        or payload.get("artifact_role") != RESOURCE_SMOKE_ROLE
    ):
        raise ResCNNCheckpointError("checkpoint is not a GPU resource-smoke artifact")
    if payload.get("epoch") != 1 or payload.get("training_step") != 32:
        raise ResCNNCheckpointError("resource-smoke checkpoint step identity drifted")
    _restore_model(payload, model)
    result = dict(payload)
    result["weights_only_used"] = True
    return result
