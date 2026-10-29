"""Exact submitted masked BCE and auditable component decomposition."""

from __future__ import annotations

from dataclasses import dataclass
import math

import torch
import torch.nn.functional as F


class ResCNNLossError(ValueError):
    pass


@dataclass(frozen=True)
class LossBreakdown:
    total: torch.Tensor
    known_weighted: torch.Tensor
    unknown_negative: torch.Tensor
    known_count: int
    unknown_count: int
    positive_multiplier: float
    unknown_negative_coefficient: float


def _validate(outputs, targets, masks, positive_multiplier, unknown_negative_coefficient) -> None:
    if outputs.shape != targets.shape or outputs.shape != masks.shape or outputs.ndim != 2:
        raise ResCNNLossError("outputs, targets and masks must be aligned rank-two tensors")
    if not torch.is_floating_point(outputs) or not torch.is_floating_point(targets) or not torch.is_floating_point(masks):
        raise ResCNNLossError("outputs, targets and masks must be floating-point tensors")
    if not bool(torch.all((targets == 0) | (targets == 1))):
        raise ResCNNLossError("targets must be binary")
    if not bool(torch.all((masks == 0) | (masks == 1))):
        raise ResCNNLossError("masks must be binary")
    if not math.isfinite(float(positive_multiplier)) or positive_multiplier <= 0:
        raise ResCNNLossError("positive_multiplier must be finite and positive")
    if not math.isfinite(float(unknown_negative_coefficient)) or unknown_negative_coefficient < 0:
        raise ResCNNLossError("unknown_negative_coefficient must be finite and non-negative")
    if int(masks.sum().item()) == 0:
        raise ResCNNLossError("known-label denominator is zero")
    if int((1 - masks).sum().item()) == 0:
        raise ResCNNLossError("unknown-label denominator is zero")


def decomposed_masked_bce(
    outputs,
    targets,
    masks,
    *,
    positive_multiplier: float,
    unknown_negative_coefficient: float,
) -> LossBreakdown:
    _validate(outputs, targets, masks, positive_multiplier, unknown_negative_coefficient)
    bce = F.binary_cross_entropy_with_logits(outputs, targets, reduction="none")
    positive_weight = (targets == 1).float() * positive_multiplier + (targets == 0).float()
    known_count_tensor = masks.sum()
    known_weighted = (positive_weight * bce * masks).sum() / known_count_tensor

    unknown_mask = (1 - masks).float()
    zero_targets = torch.zeros_like(targets)
    unknown_bce = F.binary_cross_entropy_with_logits(outputs, zero_targets, reduction="none")
    unknown_count_tensor = unknown_mask.sum()
    unknown_negative = (unknown_bce * unknown_mask).sum() / unknown_count_tensor
    total = known_weighted + unknown_negative_coefficient * unknown_negative
    return LossBreakdown(
        total=total,
        known_weighted=known_weighted,
        unknown_negative=unknown_negative,
        known_count=int(known_count_tensor.item()),
        unknown_count=int(unknown_count_tensor.item()),
        positive_multiplier=float(positive_multiplier),
        unknown_negative_coefficient=float(unknown_negative_coefficient),
    )


def masked_bce_with_soft_neg(outputs, targets, masks, lambda_unknown=1.0, lambda_pos=2.0):
    """Notebook-compatible public function; parameters intentionally retain its defaults."""
    return decomposed_masked_bce(
        outputs,
        targets,
        masks,
        positive_multiplier=lambda_pos,
        unknown_negative_coefficient=lambda_unknown,
    ).total
