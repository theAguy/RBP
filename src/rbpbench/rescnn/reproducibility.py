"""Paired random streams, strict numerical settings and epoch-order evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import random
from typing import Callable, Iterable, Iterator, Sequence

import numpy as np
import torch

from rbpbench.rescnn.fidelity import canonical_state_hash


class DeterminismError(RuntimeError):
    pass


@dataclass(frozen=True)
class SeedStreams:
    master: int
    initialization: int
    loader: int
    model_stochasticity: int


@dataclass(frozen=True)
class EpochOrder:
    epoch: int
    batches: tuple[tuple[int, ...], ...]
    dropped_indices: tuple[int, ...]
    order_sha256: str
    dropped_sha256: str


@dataclass(frozen=True)
class PairedModelStart:
    model: torch.nn.Module
    streams: SeedStreams
    initial_state_sha256: str


def derive_seed(master_seed: int, label: str) -> int:
    if not isinstance(master_seed, int) or master_seed < 0 or not label:
        raise DeterminismError("seed derivation requires a non-negative integer and non-empty label")
    raw = f"sha256-labelled-u63-v1\0{master_seed}\0{label}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") & ((1 << 63) - 1)


def seed_streams(master_seed: int) -> SeedStreams:
    return SeedStreams(
        master=master_seed,
        initialization=derive_seed(master_seed, "initialization"),
        loader=derive_seed(master_seed, "loader"),
        model_stochasticity=derive_seed(master_seed, "model-stochasticity"),
    )


def reset_random_state(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def initialize_paired_model(
    master_seed: int,
    model_factory: Callable[[], torch.nn.Module],
) -> PairedModelStart:
    """Build one config's model without allowing config identity into its RNG.

    Every paired configuration must call this same sequence immediately before
    its first training-mode forward: reset the initialization stream, construct
    the model, hash its complete state, then reset the model-stochastic stream.
    """

    streams = seed_streams(master_seed)
    reset_random_state(streams.initialization)
    model = model_factory()
    if not isinstance(model, torch.nn.Module):
        raise DeterminismError("model_factory did not return a torch module")
    initial_state_sha256 = canonical_state_hash(model.state_dict())
    reset_random_state(streams.model_stochasticity)
    return PairedModelStart(
        model=model,
        streams=streams,
        initial_state_sha256=initial_state_sha256,
    )


def configure_strict_float32(*, require_cuda: bool) -> dict[str, object]:
    if require_cuda and not torch.cuda.is_available():
        raise DeterminismError("CUDA was required but is unavailable")
    if require_cuda and os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
        raise DeterminismError("CUBLAS_WORKSPACE_CONFIG must be :4096:8 before CUDA initialization")
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")
    torch.use_deterministic_algorithms(True, warn_only=False)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    evidence = {
        "cuda_available": bool(torch.cuda.is_available()),
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
        "cudnn_allow_tf32": bool(torch.backends.cudnn.allow_tf32),
        "cuda_matmul_allow_tf32": bool(torch.backends.cuda.matmul.allow_tf32),
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "deterministic_algorithms": bool(torch.are_deterministic_algorithms_enabled()),
        "cudnn_deterministic": bool(torch.backends.cudnn.deterministic),
        "cudnn_benchmark": bool(torch.backends.cudnn.benchmark),
    }
    expected = {
        "cudnn_allow_tf32": False,
        "cuda_matmul_allow_tf32": False,
        "float32_matmul_precision": "highest",
        "deterministic_algorithms": True,
        "cudnn_deterministic": True,
        "cudnn_benchmark": False,
    }
    for key, value in expected.items():
        if evidence[key] != value:
            raise DeterminismError(f"strict setting did not take effect: {key}={evidence[key]!r}")
    return evidence


def _hash_indices(indices: Iterable[int]) -> str:
    digest = hashlib.sha256()
    for index in indices:
        if index < 0:
            raise DeterminismError("indices must be non-negative")
        digest.update(int(index).to_bytes(8, "big"))
    return digest.hexdigest()


def epoch_order(
    size: int,
    *,
    batch_size: int,
    loader_seed: int,
    epoch: int,
    drop_last: bool,
) -> EpochOrder:
    if size <= 0 or batch_size <= 0 or epoch < 0:
        raise DeterminismError("invalid epoch-order dimensions")
    generator = torch.Generator()
    generator.manual_seed(derive_seed(loader_seed, f"epoch:{epoch}"))
    permutation = torch.randperm(size, generator=generator).tolist()
    full_count = (size // batch_size) * batch_size if drop_last else size
    used = permutation[:full_count]
    dropped = permutation[full_count:]
    batches = tuple(tuple(used[start:start + batch_size]) for start in range(0, len(used), batch_size))
    if not batches:
        raise DeterminismError("epoch contains no complete batch")
    return EpochOrder(
        epoch=epoch,
        batches=batches,
        dropped_indices=tuple(dropped),
        order_sha256=_hash_indices(used),
        dropped_sha256=_hash_indices(dropped),
    )


class FixedEpochBatchSampler:
    """A DataLoader batch sampler backed by already-hashed epoch evidence."""

    def __init__(self, evidence: EpochOrder):
        self.evidence = evidence

    def __iter__(self) -> Iterator[list[int]]:
        for batch in self.evidence.batches:
            yield list(batch)

    def __len__(self) -> int:
        return len(self.evidence.batches)


def require_paired_orders(orders: Sequence[EpochOrder]) -> None:
    if not orders:
        raise DeterminismError("no epoch orders supplied")
    reference = orders[0]
    for order in orders[1:]:
        if (
            order.epoch != reference.epoch
            or order.order_sha256 != reference.order_sha256
            or order.dropped_sha256 != reference.dropped_sha256
        ):
            raise DeterminismError("paired configurations have different epoch order or dropped row")
