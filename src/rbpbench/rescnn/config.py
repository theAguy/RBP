"""Frozen configuration contract for Task 004A."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


class ResCNNConfigError(ValueError):
    """The Task 004A configuration drifted from the reviewed contract."""


@dataclass(frozen=True)
class LossConfig:
    config_id: str
    positive_multiplier: float
    unknown_negative_coefficient: float


@dataclass(frozen=True)
class Task004AConfig:
    schema_version: str
    window: int
    output_count: int
    train_row_count: int
    validation_row_count: int
    batch_size: int
    train_drop_last: bool
    validation_drop_last: bool
    epochs: int
    seeds: tuple[int, ...]
    development_protein_ids: tuple[int, ...]
    architecture: Mapping[str, object]
    label_contract: Mapping[str, object]
    input_encoding: Mapping[str, object]
    inputs: Mapping[str, str]
    optimizer: Mapping[str, object]
    scheduler: Mapping[str, object]
    determinism: Mapping[str, object]
    loss_configs: tuple[LossConfig, ...]
    collapse: Mapping[str, float]


EXPECTED_SCALARS = {
    "schema_version": "task004a_rescnn_v1",
    "window": 500,
    "output_count": 122,
    "train_row_count": 246017,
    "validation_row_count": 57565,
    "batch_size": 256,
    "train_drop_last": True,
    "validation_drop_last": False,
    "epochs": 30,
}
EXPECTED_SEEDS = (20261029, 20261030, 20261031)
EXPECTED_DEVELOPMENT_IDS = (33, 53, 82, 84, 85, 86, 107, 112)
EXPECTED_ARCHITECTURE = {
    "input_layout": "batch,window,channel",
    "input_channels": 4,
    "block_channels": [64, 128, 256],
    "kernel_sizes": [7, 7, 5],
    "conv_stride": 1,
    "conv_dilation": 1,
    "conv_groups": 1,
    "conv_padding": "same_floor_half_kernel",
    "conv_padding_mode": "zeros",
    "conv_bias": True,
    "batch_norm_epsilon": 1e-5,
    "batch_norm_momentum": 0.1,
    "batch_norm_affine": True,
    "batch_norm_track_running_stats": True,
    "relu_inplace": False,
    "pool_kernel": 2,
    "pool_stride": 2,
    "pool_padding": 0,
    "pool_dilation": 1,
    "pool_ceil_mode": False,
    "post_pool_length": 62,
    "flattened_features": 15_872,
    "dense_features": [512, 256, 122],
    "dense_bias": True,
    "dropout_probabilities": [0.4, 0.3],
    "dropout_inplace": False,
    "learnable_parameter_count": 9_029_562,
}
EXPECTED_LABEL_CONTRACT = {
    "protein_id_minimum": 1,
    "protein_id_maximum": 122,
    "output_column_rule": "protein_id_minus_one",
    "unsigned_token": "known_positive",
    "explicit_plus_token": "known_positive",
    "negative_token": "known_negative",
    "absent_token": "unknown",
    "target_dtype": "float32",
    "mask_dtype": "float32",
}
EXPECTED_INPUT_ENCODING = {
    "alphabet": "ACGT",
    "channel_order": ["A", "C", "G", "T"],
    "retained_dtype": "uint8",
    "batch_dtype": "float32",
    "orientation": "supplied",
    "one_hot_shape": [500, 4],
}
EXPECTED_LOSSES = (
    LossConfig("submitted", 15.0, 1.0),
    LossConfig("submitted_no_unknown", 15.0, 0.0),
    LossConfig("joint_standard", 1.0, 0.0),
)
EXPECTED_OPTIMIZER = {
    "name": "Adam", "learning_rate": 0.001, "betas": [0.9, 0.999],
    "epsilon": 1e-8, "weight_decay": 0.0, "amsgrad": False,
}
EXPECTED_SCHEDULER = {
    "name": "ReduceLROnPlateau", "mode": "max", "factor": 0.5,
    "patience": 2, "threshold": 0.0001, "threshold_mode": "rel",
    "cooldown": 0, "minimum_learning_rate": 0.0, "epsilon": 1e-8,
}
EXPECTED_DETERMINISM = {
    "cublas_workspace_config": ":4096:8",
    "cudnn_allow_tf32": False,
    "cuda_matmul_allow_tf32": False,
    "float32_matmul_precision": "highest",
    "deterministic_algorithms": True,
    "cudnn_deterministic": True,
    "cudnn_benchmark": False,
    "seed_derivation": "sha256-labelled-u63-v1",
}
EXPECTED_INPUTS = {
    "csv_sha256": "982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945",
    "dataset_audit_sha256": "e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c",
    "proteins_sha256": "374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9",
    "decode_manifest_sha256": "d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3",
    "partition_manifest_sha256": "b6f6f16fab4e6afc23c16a8dc5b3476130719d579f637cd3cf18002cc7fb7419",
    "membership_sha256": "ca527da4f0c0615bcb9d31c6fc705523238e8fb8f4751473ccc2af3ee0aecddb",
    "fasta_500_sha256": "0849d4f8aceaed37c3dc7fec69056f38ae344338aa4adf321a3e11c4a72df0b0",
    "notebook_sha256": "9a04f551ed9e5420c720074bf57f41f1c93ab92acc37c3b8ff44868e6b021b84",
    "checkpoint_sha256": "9c036fceab966442d3cea40146a757114d8b23711c41cba227c3dafd24ff27c3",
    "architecture_cell_sha256": "2bc4917653698b2c38e690c184924b46c222ea2ebe632d7bf225993b6fff1e0c",
    "loss_cell_sha256": "dbb61960cb79ee5bc727b03d7f3703a857a3f61a02899cd8af250d362a312f5a",
    "hyperparameter_cell_sha256": "b8fa0fadfd365e5ade84dffdda4d055018405132705dc44ca38524824644a3b4",
}

EXPECTED_TOP_LEVEL_KEYS = {
    *EXPECTED_SCALARS,
    "seeds",
    "development_protein_ids",
    "architecture",
    "label_contract",
    "input_encoding",
    "inputs",
    "optimizer",
    "scheduler",
    "determinism",
    "loss_configs",
    "collapse",
}


def _require_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise ResCNNConfigError(f"{label} drift: {actual!r} != {expected!r}")


def _parse_loss_config(row: object, index: int) -> LossConfig:
    expected_keys = {"config_id", "positive_multiplier", "unknown_negative_coefficient"}
    if not isinstance(row, dict) or set(row) != expected_keys:
        raise ResCNNConfigError(
            f"loss_configs[{index}] keys drift: "
            f"{sorted(row) if isinstance(row, dict) else type(row).__name__!r}"
        )
    try:
        return LossConfig(
            str(row["config_id"]),
            float(row["positive_multiplier"]),
            float(row["unknown_negative_coefficient"]),
        )
    except (TypeError, ValueError) as exc:
        raise ResCNNConfigError(f"loss_configs[{index}] contains invalid values") from exc


def validate_config_object(config: Task004AConfig) -> None:
    """Reject hand-built dataclasses that bypass the TOML loader's contract."""

    if not isinstance(config, Task004AConfig):
        raise ResCNNConfigError("expected a Task004AConfig")
    for key, expected in EXPECTED_SCALARS.items():
        _require_equal(getattr(config, key), expected, key)
    _require_equal(tuple(config.seeds), EXPECTED_SEEDS, "seeds")
    _require_equal(
        tuple(config.development_protein_ids), EXPECTED_DEVELOPMENT_IDS,
        "development_protein_ids",
    )
    _require_equal(tuple(config.loss_configs), EXPECTED_LOSSES, "loss_configs")
    _require_equal(dict(config.architecture), EXPECTED_ARCHITECTURE, "architecture")
    _require_equal(dict(config.label_contract), EXPECTED_LABEL_CONTRACT, "label_contract")
    _require_equal(dict(config.input_encoding), EXPECTED_INPUT_ENCODING, "input_encoding")
    _require_equal(dict(config.optimizer), EXPECTED_OPTIMIZER, "optimizer")
    _require_equal(dict(config.scheduler), EXPECTED_SCHEDULER, "scheduler")
    _require_equal(dict(config.determinism), EXPECTED_DETERMINISM, "determinism")
    _require_equal(dict(config.inputs), EXPECTED_INPUTS, "inputs")
    _require_equal(
        dict(config.collapse),
        {"saturation_lower": 1e-6, "saturation_upper": 0.999999},
        "collapse thresholds",
    )


def require_loss_config(config: Task004AConfig, loss_config: LossConfig) -> LossConfig:
    validate_config_object(config)
    if loss_config not in config.loss_configs or loss_config not in EXPECTED_LOSSES:
        raise ResCNNConfigError("loss configuration is outside the frozen Task 004A set")
    return loss_config


def load_config(path: Path) -> Task004AConfig:
    raw = tomllib.loads(Path(path).read_text())
    _require_equal(set(raw), EXPECTED_TOP_LEVEL_KEYS, "top-level keys")
    for key, expected in EXPECTED_SCALARS.items():
        _require_equal(raw.get(key), expected, key)
    seeds = tuple(raw.get("seeds", ()))
    development_ids = tuple(raw.get("development_protein_ids", ()))
    _require_equal(seeds, EXPECTED_SEEDS, "seeds")
    _require_equal(development_ids, EXPECTED_DEVELOPMENT_IDS, "development_protein_ids")
    losses = tuple(
        _parse_loss_config(row, index)
        for index, row in enumerate(raw.get("loss_configs", ()))
    )
    _require_equal(losses, EXPECTED_LOSSES, "loss_configs")
    _require_equal(raw.get("architecture"), EXPECTED_ARCHITECTURE, "architecture")
    _require_equal(raw.get("label_contract"), EXPECTED_LABEL_CONTRACT, "label_contract")
    _require_equal(raw.get("input_encoding"), EXPECTED_INPUT_ENCODING, "input_encoding")
    _require_equal(raw.get("optimizer"), EXPECTED_OPTIMIZER, "optimizer")
    _require_equal(raw.get("scheduler"), EXPECTED_SCHEDULER, "scheduler")
    _require_equal(raw.get("determinism"), EXPECTED_DETERMINISM, "determinism")
    inputs = raw.get("inputs")
    if not isinstance(inputs, dict):
        raise ResCNNConfigError("inputs must be a table")
    _require_equal(inputs, EXPECTED_INPUTS, "inputs")
    for name, digest in inputs.items():
        if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            raise ResCNNConfigError(f"inputs.{name} is not a lowercase SHA-256")
    collapse = raw.get("collapse")
    if collapse != {"saturation_lower": 1e-6, "saturation_upper": 0.999999}:
        raise ResCNNConfigError("collapse thresholds drift")
    config = Task004AConfig(
        schema_version=raw["schema_version"], window=raw["window"], output_count=raw["output_count"],
        train_row_count=raw["train_row_count"], validation_row_count=raw["validation_row_count"],
        batch_size=raw["batch_size"], train_drop_last=raw["train_drop_last"],
        validation_drop_last=raw["validation_drop_last"], epochs=raw["epochs"], seeds=seeds,
        development_protein_ids=development_ids, architecture=dict(raw["architecture"]),
        label_contract=dict(raw["label_contract"]), input_encoding=dict(raw["input_encoding"]),
        inputs=dict(inputs), optimizer=dict(raw["optimizer"]),
        scheduler=dict(raw["scheduler"]), determinism=dict(raw["determinism"]),
        loss_configs=losses, collapse=dict(collapse),
    )
    validate_config_object(config)
    return config
