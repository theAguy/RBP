"""Direct, hash-bound notebook oracle extraction and tensor hashing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Type

import torch
import torch.nn as nn
import torch.nn.functional as F


NOTEBOOK_SHA256 = "9a04f551ed9e5420c720074bf57f41f1c93ab92acc37c3b8ff44868e6b021b84"
ARCHITECTURE_CELL_INDEX = 8
LOSS_CELL_INDEX = 11
HYPERPARAMETER_CELL_INDEX = 22
CELL_HASHES = {
    ARCHITECTURE_CELL_INDEX: "2bc4917653698b2c38e690c184924b46c222ea2ebe632d7bf225993b6fff1e0c",
    LOSS_CELL_INDEX: "dbb61960cb79ee5bc727b03d7f3703a857a3f61a02899cd8af250d362a312f5a",
    HYPERPARAMETER_CELL_INDEX: "b8fa0fadfd365e5ade84dffdda4d055018405132705dc44ca38524824644a3b4",
}


class NotebookFidelityError(RuntimeError):
    pass


@dataclass(frozen=True)
class NotebookOracles:
    residual_block_class: Type[nn.Module]
    model_class: Type[nn.Module]
    loss_function: Callable
    hyperparameters: Mapping[str, object]
    cell_hashes: Mapping[int, str]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cell_source(notebook: Mapping[str, object], index: int) -> str:
    try:
        cell = notebook["cells"][index]
        source = "".join(cell["source"])
    except (KeyError, IndexError, TypeError) as exc:
        raise NotebookFidelityError(f"notebook cell {index} is unavailable") from exc
    actual = sha256_bytes(source.encode("utf-8"))
    expected = CELL_HASHES[index]
    if actual != expected:
        raise NotebookFidelityError(f"notebook cell {index} hash {actual} != {expected}")
    return source


def load_notebook_oracles(path: Path) -> NotebookOracles:
    raw = Path(path).read_bytes()
    actual_notebook_hash = sha256_bytes(raw)
    if actual_notebook_hash != NOTEBOOK_SHA256:
        raise NotebookFidelityError(
            f"notebook hash {actual_notebook_hash} != frozen {NOTEBOOK_SHA256}"
        )
    notebook = json.loads(raw)
    architecture_source = _cell_source(notebook, ARCHITECTURE_CELL_INDEX)
    loss_source = _cell_source(notebook, LOSS_CELL_INDEX)
    hyperparameter_source = _cell_source(notebook, HYPERPARAMETER_CELL_INDEX)

    architecture_namespace = {"nn": nn}
    exec(compile(architecture_source, f"{path}:cell8", "exec"), architecture_namespace)
    loss_namespace = {"torch": torch, "F": F}
    exec(compile(loss_source, f"{path}:cell11", "exec"), loss_namespace)
    hyperparameter_namespace = {"__builtins__": {}}
    exec(compile(hyperparameter_source, f"{path}:cell22", "exec"), hyperparameter_namespace)
    hyperparameters = {
        name: hyperparameter_namespace[name]
        for name in ("num_epochs", "batch_size", "lr", "kfolds", "lambda_unknown", "lambda_pos")
    }
    if hyperparameters != {
        "num_epochs": 30, "batch_size": 256, "lr": 1e-3,
        "kfolds": 5, "lambda_unknown": 1, "lambda_pos": 15,
    }:
        raise NotebookFidelityError(f"notebook hyperparameters drifted: {hyperparameters!r}")
    return NotebookOracles(
        residual_block_class=architecture_namespace["ResidualBlock1D"],
        model_class=architecture_namespace["CNNMultiLabelResidual"],
        loss_function=loss_namespace["masked_bce_with_soft_neg"],
        hyperparameters=hyperparameters,
        cell_hashes=dict(CELL_HASHES),
    )


def canonical_state_hash(state: Mapping[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for key, tensor in state.items():
        if not isinstance(key, str) or not isinstance(tensor, torch.Tensor):
            raise NotebookFidelityError("state must map string keys to tensors")
        value = tensor.detach().cpu().contiguous()
        parts = (key, str(value.dtype), ",".join(str(item) for item in value.shape))
        for part in parts:
            encoded = part.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        raw = value.numpy().tobytes(order="C")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def require_identical_state(left: Mapping[str, torch.Tensor], right: Mapping[str, torch.Tensor]) -> None:
    if tuple(left) != tuple(right):
        raise NotebookFidelityError("state-dictionary keys or ordering differ")
    for key in left:
        if left[key].dtype != right[key].dtype or left[key].shape != right[key].shape:
            raise NotebookFidelityError(f"state tensor metadata differs: {key}")
        if not torch.equal(left[key], right[key]):
            raise NotebookFidelityError(f"state tensor values differ: {key}")
