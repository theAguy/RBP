"""Frozen loss, optimizer and scheduler construction for Task 004A-2."""

from __future__ import annotations

import hashlib

import torch

from rbpbench.rescnn.config import (
    EXPECTED_OPTIMIZER,
    EXPECTED_SCHEDULER,
    LossConfig,
    Task004AConfig,
    require_loss_config,
    validate_config_object,
)
from rbpbench.rescnn.loss import LossBreakdown, decomposed_masked_bce


class ResCNNFactoryError(RuntimeError):
    pass


def configured_loss(
    outputs: torch.Tensor,
    targets: torch.Tensor,
    masks: torch.Tensor,
    *,
    config: Task004AConfig,
    loss_config: LossConfig,
) -> LossBreakdown:
    frozen = require_loss_config(config, loss_config)
    return decomposed_masked_bce(
        outputs,
        targets,
        masks,
        positive_multiplier=frozen.positive_multiplier,
        unknown_negative_coefficient=frozen.unknown_negative_coefficient,
    )


def build_adam(model: torch.nn.Module, config: Task004AConfig) -> torch.optim.Adam:
    validate_config_object(config)
    values = config.optimizer
    if dict(values) != EXPECTED_OPTIMIZER:
        raise ResCNNFactoryError("optimizer values differ from frozen constants")
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=float(values["learning_rate"]),
        betas=tuple(float(value) for value in values["betas"]),
        eps=float(values["epsilon"]),
        weight_decay=float(values["weight_decay"]),
        amsgrad=bool(values["amsgrad"]),
    )
    group = optimizer.param_groups[0]
    effective = {
        "name": "Adam",
        "learning_rate": float(group["lr"]),
        "betas": list(group["betas"]),
        "epsilon": float(group["eps"]),
        "weight_decay": float(group["weight_decay"]),
        "amsgrad": bool(group["amsgrad"]),
    }
    if effective != EXPECTED_OPTIMIZER:
        raise ResCNNFactoryError(f"effective Adam settings drifted: {effective!r}")
    return optimizer


def build_scheduler(
    optimizer: torch.optim.Optimizer,
    config: Task004AConfig,
) -> torch.optim.lr_scheduler.ReduceLROnPlateau:
    validate_config_object(config)
    values = config.scheduler
    if dict(values) != EXPECTED_SCHEDULER:
        raise ResCNNFactoryError("scheduler values differ from frozen constants")
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode=str(values["mode"]),
        factor=float(values["factor"]),
        patience=int(values["patience"]),
        threshold=float(values["threshold"]),
        threshold_mode=str(values["threshold_mode"]),
        cooldown=int(values["cooldown"]),
        min_lr=float(values["minimum_learning_rate"]),
        eps=float(values["epsilon"]),
    )
    effective = {
        "name": "ReduceLROnPlateau",
        "mode": scheduler.mode,
        "factor": float(scheduler.factor),
        "patience": int(scheduler.patience),
        "threshold": float(scheduler.threshold),
        "threshold_mode": scheduler.threshold_mode,
        "cooldown": int(scheduler.cooldown),
        "minimum_learning_rate": float(scheduler.min_lrs[0]),
        "epsilon": float(scheduler.eps),
    }
    if effective != EXPECTED_SCHEDULER:
        raise ResCNNFactoryError(f"effective scheduler settings drifted: {effective!r}")
    return scheduler


def sigmoid_float32(logits: torch.Tensor) -> torch.Tensor:
    if logits.dtype != torch.float32:
        raise ResCNNFactoryError("Task 004A scores require float32 logits")
    scores = torch.sigmoid(logits)
    if scores.dtype != torch.float32 or not bool(torch.isfinite(scores).all()):
        raise ResCNNFactoryError("float32 sigmoid produced invalid scores")
    return scores


def gradient_sha256(model: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    found = False
    for name, parameter in model.named_parameters():
        if parameter.grad is None:
            continue
        found = True
        gradient = parameter.grad.detach().cpu().contiguous()
        for value in (name, str(gradient.dtype), ",".join(map(str, gradient.shape))):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        raw = gradient.numpy().tobytes(order="C")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    if not found:
        raise ResCNNFactoryError("model has no gradients")
    return digest.hexdigest()
