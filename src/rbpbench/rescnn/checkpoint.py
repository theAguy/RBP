"""Atomic epoch evidence and final-epoch model restoration checks."""

from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path
import uuid

import torch

from rbpbench.rescnn.fidelity import canonical_state_hash


class ResCNNCheckpointError(RuntimeError):
    pass


SCHEMA_VERSION = "task004a_checkpoint_v1"
FORMER_CHECKPOINT_SHA256 = "9c036fceab966442d3cea40146a757114d8b23711c41cba227c3dafd24ff27c3"
REQUIRED_IDENTITY_KEYS = frozenset(
    {"source_sha256", "config_sha256", "environment_sha256", "seed", "config_id"}
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_save_checkpoint(
    path: Path,
    *,
    model,
    optimizer,
    scheduler,
    epoch: int,
    source_sha256: str,
    config_sha256: str,
    environment_sha256: str,
    seed: int,
    config_id: str,
) -> dict[str, object]:
    if epoch < 1 or not config_id:
        raise ResCNNCheckpointError("invalid checkpoint identity")
    for name, value in (
        ("source_sha256", source_sha256),
        ("config_sha256", config_sha256),
        ("environment_sha256", environment_sha256),
    ):
        if len(value) != 64 or set(value) - set("0123456789abcdef"):
            raise ResCNNCheckpointError(f"{name} is not a lowercase SHA-256")
    state_hash = canonical_state_hash(model.state_dict())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "epoch": epoch,
        "seed": seed,
        "config_id": config_id,
        "source_sha256": source_sha256,
        "config_sha256": config_sha256,
        "environment_sha256": environment_sha256,
        "model_state_sha256": state_hash,
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict(),
        "rng_state_included": False,
        "mid_run_resume_supported": False,
    }
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
        "model_state_sha256": state_hash,
        "epoch": epoch,
    }


def load_final_model_checkpoint(
    path: Path,
    *,
    model,
    expected_epoch: int,
    expected_sha256: str,
    expected_identity: dict[str, object],
) -> dict:
    # This loader accepts only a checkpoint produced inside the current trusted
    # run. Former/untrusted pickle artifacts are never routed through it.
    actual_sha256 = sha256_file(Path(path))
    if actual_sha256 == FORMER_CHECKPOINT_SHA256:
        raise ResCNNCheckpointError("former checkpoint is forbidden in the Task 004A loader")
    if actual_sha256 != expected_sha256:
        raise ResCNNCheckpointError("checkpoint file SHA-256 mismatch before deserialization")
    if set(expected_identity) != REQUIRED_IDENTITY_KEYS:
        raise ResCNNCheckpointError(
            f"checkpoint identity must contain exactly {sorted(REQUIRED_IDENTITY_KEYS)!r}"
        )
    for key in ("source_sha256", "config_sha256", "environment_sha256"):
        value = expected_identity[key]
        if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
            raise ResCNNCheckpointError(f"expected {key} is not a lowercase SHA-256")
    if expected_identity["seed"] not in (20261029, 20261030, 20261031):
        raise ResCNNCheckpointError("expected seed is outside the frozen Task 004A set")
    if expected_identity["config_id"] not in (
        "submitted", "submitted_no_unknown", "joint_standard"
    ):
        raise ResCNNCheckpointError("expected config_id is outside the frozen Task 004A set")
    load_arguments = {"map_location": "cpu"}
    if "weights_only" in inspect.signature(torch.load).parameters:
        load_arguments["weights_only"] = True
    payload = torch.load(Path(path), **load_arguments)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ResCNNCheckpointError("checkpoint schema mismatch")
    if payload.get("epoch") != expected_epoch:
        raise ResCNNCheckpointError("checkpoint is not the expected final epoch")
    if payload.get("mid_run_resume_supported") is not False or payload.get("rng_state_included") is not False:
        raise ResCNNCheckpointError("checkpoint incorrectly advertises mid-run resume")
    for key, expected in expected_identity.items():
        if payload.get(key) != expected:
            raise ResCNNCheckpointError(f"checkpoint identity mismatch: {key}")
    if canonical_state_hash(payload["model_state"]) != payload.get("model_state_sha256"):
        raise ResCNNCheckpointError("checkpoint model state hash mismatch")
    model.load_state_dict(payload["model_state"], strict=True)
    if canonical_state_hash(model.state_dict()) != payload["model_state_sha256"]:
        raise ResCNNCheckpointError("restored model state hash mismatch")
    return payload
