"""Bounded paired one-update smoke for Task 004A-2.

The engine consumes only the compact 513+513 cache.  It is deliberately
independent of path discovery and full-data streaming so synthetic tests can
exercise the complete model/loss/checkpoint contract without real inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from itertools import combinations
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import torch

from rbpbench.rescnn.checkpoint import (
    atomic_save_smoke_checkpoint,
    load_smoke_model_checkpoint,
)
from rbpbench.rescnn.config import Task004AConfig, validate_config_object
from rbpbench.rescnn.data_004a2 import CompactSampleCache
from rbpbench.rescnn.factories_004a2 import (
    build_adam,
    build_scheduler,
    configured_loss,
    gradient_sha256,
    sigmoid_float32,
)
from rbpbench.rescnn.fidelity import canonical_state_hash
from rbpbench.rescnn.metrics import evaluate_known_outputs
from rbpbench.rescnn.reproducibility import (
    epoch_order,
    initialize_paired_model,
    require_paired_orders,
)


class ResCNNSmokeError(RuntimeError):
    pass


def _tensor_sha256(tensor: torch.Tensor) -> str:
    value = tensor.detach().cpu().contiguous()
    digest = hashlib.sha256()
    for item in (str(value.dtype), ",".join(map(str, value.shape))):
        encoded = item.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    raw = value.numpy().tobytes(order="C")
    digest.update(len(raw).to_bytes(8, "big"))
    digest.update(raw)
    return digest.hexdigest()


def _indices_sha256(indices: Sequence[int]) -> str:
    digest = hashlib.sha256()
    for index in indices:
        digest.update(int(index).to_bytes(8, "big"))
    return digest.hexdigest()


def _batch(cache: CompactSampleCache, indices: Sequence[int]):
    sequences = torch.stack([cache[index][0] for index in indices])
    targets = torch.stack([cache[index][1] for index in indices])
    masks = torch.stack([cache[index][2] for index in indices])
    return sequences, targets, masks


def _validation(
    model: torch.nn.Module,
    cache: CompactSampleCache,
    indices: Sequence[int],
    *,
    batch_size: int,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, tuple[int, ...]]:
    logits: list[torch.Tensor] = []
    targets: list[torch.Tensor] = []
    masks: list[torch.Tensor] = []
    sizes: list[int] = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(indices), batch_size):
            batch_indices = indices[start:start + batch_size]
            sequences, batch_targets, batch_masks = _batch(cache, batch_indices)
            batch_logits = model(sequences)
            if batch_logits.dtype != torch.float32:
                raise ResCNNSmokeError("validation logits are not float32")
            logits.append(batch_logits.detach().cpu())
            targets.append(batch_targets.detach().cpu())
            masks.append(batch_masks.detach().cpu())
            sizes.append(len(batch_indices))
    return (
        torch.cat(logits), torch.cat(targets), torch.cat(masks), tuple(sizes),
    )


@dataclass(frozen=True)
class ConfigSmokeResult:
    config_id: str
    evidence: Mapping[str, object]
    validation_logits: torch.Tensor
    validation_scores: torch.Tensor


@dataclass(frozen=True)
class PairedSmokeResult:
    evidence: Mapping[str, object]
    by_config: Mapping[str, ConfigSmokeResult]


def run_paired_smoke(
    cache: CompactSampleCache,
    *,
    config: Task004AConfig,
    output_dir: Path,
    source_sha256: str,
    config_sha256: str,
    environment_sha256: str,
    model_factory: Callable[[], torch.nn.Module],
    master_seed: int | None = None,
) -> PairedSmokeResult:
    """Run exactly one paired update per frozen loss configuration."""

    validate_config_object(config)
    seed = config.seeds[0] if master_seed is None else master_seed
    if seed not in config.seeds:
        raise ResCNNSmokeError("master seed is outside the frozen configuration")
    for label, digest in (
        ("source_sha256", source_sha256),
        ("config_sha256", config_sha256),
        ("environment_sha256", environment_sha256),
    ):
        if len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            raise ResCNNSmokeError(f"{label} is not a lowercase SHA-256")

    train_indices = cache.indices("train")
    validation_indices = cache.indices("validation")
    if len(train_indices) != 513 or len(validation_indices) != 513:
        raise ResCNNSmokeError("paired smoke requires exactly 513 train and 513 validation rows")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    results: dict[str, ConfigSmokeResult] = {}
    orders = []
    initial_hashes: list[str] = []
    pre_logits: list[torch.Tensor] = []
    known_terms: dict[str, torch.Tensor] = {}
    unknown_terms: dict[str, torch.Tensor] = {}
    totals: dict[str, torch.Tensor] = {}

    for loss_config in config.loss_configs:
        start = initialize_paired_model(seed, model_factory)
        initial_hashes.append(start.initial_state_sha256)
        if initial_hashes[0] != start.initial_state_sha256:
            raise ResCNNSmokeError("paired configurations did not share initial model state")
        order = epoch_order(
            len(train_indices), batch_size=config.batch_size,
            loader_seed=start.streams.loader, epoch=0,
            drop_last=config.train_drop_last,
        )
        orders.append(order)
        if tuple(len(batch) for batch in order.batches) != (256, 256):
            raise ResCNNSmokeError("training order did not contain two admitted 256-row batches")
        if len(order.dropped_indices) != 1:
            raise ResCNNSmokeError("training order did not drop exactly one row")
        first_global = tuple(train_indices[index] for index in order.batches[0])
        sequences, targets, masks = _batch(cache, first_global)
        if not bool(((targets == 1) & (masks == 1)).any()):
            raise ResCNNSmokeError("first admitted training batch has no known positive")

        model = start.model
        model.train()
        logits = model(sequences)
        if tuple(logits.shape) != (config.batch_size, config.output_count):
            raise ResCNNSmokeError(f"unexpected training-logit shape: {tuple(logits.shape)}")
        if logits.dtype != torch.float32:
            raise ResCNNSmokeError("training logits are not float32")
        pre_logits.append(logits.detach().cpu().clone())

        optimizer = build_adam(model, config)
        scheduler = build_scheduler(optimizer, config)
        optimizer.zero_grad(set_to_none=True)
        breakdown = configured_loss(
            logits, targets, masks, config=config, loss_config=loss_config,
        )
        reconstructed = (
            breakdown.known_weighted
            + loss_config.unknown_negative_coefficient * breakdown.unknown_negative
        )
        if not torch.equal(breakdown.total, reconstructed):
            raise ResCNNSmokeError("loss decomposition is not exact")
        breakdown.total.backward()
        gradient = gradient_sha256(model)
        known_terms[loss_config.config_id] = breakdown.known_weighted.detach().cpu()
        unknown_terms[loss_config.config_id] = breakdown.unknown_negative.detach().cpu()
        totals[loss_config.config_id] = breakdown.total.detach().cpu()
        optimizer.step()

        validation_logits, validation_targets, validation_masks, validation_batches = _validation(
            model, cache, validation_indices, batch_size=config.batch_size,
        )
        if validation_batches != (256, 256, 1):
            raise ResCNNSmokeError(f"validation tail drifted: {validation_batches!r}")
        validation_scores = sigmoid_float32(validation_logits)
        metric_rows, metric_summary = evaluate_known_outputs(
            validation_targets.numpy(), validation_scores.numpy(), validation_masks.numpy(),
            expected_output_count=config.output_count,
        )
        if metric_summary["eligible_output_count"] != 122 or len(metric_rows) != 122:
            raise ResCNNSmokeError("coverage fixture did not exercise all 122 outputs")
        scheduler.step(float(metric_summary["macro_auroc"]))

        identity = {
            "source_sha256": source_sha256,
            "config_sha256": config_sha256,
            "environment_sha256": environment_sha256,
            "seed": seed,
            "config_id": loss_config.config_id,
        }
        checkpoint_path = output_dir / f"{loss_config.config_id}.pt"
        checkpoint = atomic_save_smoke_checkpoint(
            checkpoint_path, model=model, optimizer=optimizer,
            scheduler=scheduler, identity=identity,
        )
        fresh_model = model_factory()
        loaded = load_smoke_model_checkpoint(
            checkpoint_path, model=fresh_model,
            expected_sha256=str(checkpoint["sha256"]), expected_identity=identity,
        )
        reloaded_logits, _, _, reloaded_batches = _validation(
            fresh_model, cache, validation_indices, batch_size=config.batch_size,
        )
        reloaded_scores = sigmoid_float32(reloaded_logits)
        if reloaded_batches != validation_batches:
            raise ResCNNSmokeError("reloaded validation order changed")
        if not torch.equal(validation_logits, reloaded_logits):
            raise ResCNNSmokeError("validation logits changed after checkpoint reload")
        if not torch.equal(validation_scores, reloaded_scores):
            raise ResCNNSmokeError("validation predictions changed after checkpoint reload")

        evidence = {
            "config_id": loss_config.config_id,
            "initial_model_state_sha256": start.initial_state_sha256,
            "order_sha256": order.order_sha256,
            "dropped_sha256": order.dropped_sha256,
            "training_batch_sizes": [len(batch) for batch in order.batches],
            "dropped_row_count": len(order.dropped_indices),
            "first_batch_has_known_positive": True,
            "pre_update_logits_sha256": _tensor_sha256(logits),
            "loss": {
                "known_weighted": float(breakdown.known_weighted.detach()),
                "unknown_negative": float(breakdown.unknown_negative.detach()),
                "total": float(breakdown.total.detach()),
                "positive_multiplier": loss_config.positive_multiplier,
                "unknown_negative_coefficient": loss_config.unknown_negative_coefficient,
                "known_count": breakdown.known_count,
                "unknown_count": breakdown.unknown_count,
                "decomposition_exact": True,
            },
            "gradient_sha256": gradient,
            "updated_model_state_sha256": canonical_state_hash(model.state_dict()),
            "validation_order_sha256": _indices_sha256(validation_indices),
            "validation_batch_sizes": list(validation_batches),
            "validation_logits_sha256": _tensor_sha256(validation_logits),
            "validation_scores_sha256": _tensor_sha256(validation_scores),
            "metrics": dict(metric_summary),
            "checkpoint": checkpoint,
            "reloaded_model_state_sha256": loaded["model_state_sha256"],
            "weights_only_used": loaded["weights_only_used"],
        }
        results[loss_config.config_id] = ConfigSmokeResult(
            config_id=loss_config.config_id,
            evidence=evidence,
            validation_logits=validation_logits,
            validation_scores=validation_scores,
        )

    require_paired_orders(orders)
    for value in pre_logits[1:]:
        if not torch.equal(pre_logits[0], value):
            raise ResCNNSmokeError("paired configurations did not share dropout/logits")
    if not torch.equal(known_terms["submitted"], known_terms["submitted_no_unknown"]):
        raise ResCNNSmokeError("positive-multiplier peers changed their known term")
    reference_unknown = unknown_terms["submitted"]
    if any(not torch.equal(reference_unknown, value) for value in unknown_terms.values()):
        raise ResCNNSmokeError("uncoefficiented unknown term changed across configurations")
    for left, right in combinations(results, 2):
        if torch.equal(totals[left], totals[right]):
            raise ResCNNSmokeError(f"paired total losses are equal: {left}, {right}")
        if results[left].evidence["gradient_sha256"] == results[right].evidence["gradient_sha256"]:
            raise ResCNNSmokeError(f"paired gradient hashes are equal: {left}, {right}")

    paired = {
        "master_seed": seed,
        "config_ids": list(results),
        "shared_initial_model_state_sha256": next(iter(results.values())).evidence[
            "initial_model_state_sha256"
        ],
        "all_initial_model_state_hashes_equal": len(set(initial_hashes)) == 1,
        "shared_order_sha256": orders[0].order_sha256,
        "shared_dropped_sha256": orders[0].dropped_sha256,
        "shared_pre_update_logits_sha256": _tensor_sha256(pre_logits[0]),
        "all_pair_losses_distinct": True,
        "all_pair_gradients_distinct": True,
        "validation_order_unshuffled": True,
        "test_prediction_rows": 0,
        "test_accessed": False,
    }
    return PairedSmokeResult(evidence=paired, by_config=results)


def scientific_signature(result: PairedSmokeResult) -> dict[str, object]:
    """Return runtime-independent evidence for primary/repeat comparison."""

    return {
        "paired": dict(result.evidence),
        "configs": {
            config_id: {
                key: value
                for key, value in config_result.evidence.items()
                if key != "checkpoint"
            }
            for config_id, config_result in result.by_config.items()
        },
    }
