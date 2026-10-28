"""Strict configuration loading for Task 003B."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any


class BaselineConfigError(ValueError):
    pass


FROZEN_WINDOWS = (500, 251, 101)
FROZEN_BASELINES = ("prevalence", "gc", "3mer", "6mer")
FROZEN_DEVELOPMENT_PROTEINS = (33, 53, 82, 84, 85, 86, 107, 112)
FROZEN_C_GRID = (0.01, 0.1, 1.0, 10.0)
FROZEN_SEED = 20261028
FROZEN_INPUTS = {
    "csv_sha256": "982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945",
    "dataset_audit_sha256": "e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c",
    "proteins_sha256": "374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9",
    "decode_manifest_sha256": "d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3",
    "partition_manifest_sha256": "b6f6f16fab4e6afc23c16a8dc5b3476130719d579f637cd3cf18002cc7fb7419",
    "membership_sha256": "ca527da4f0c0615bcb9d31c6fc705523238e8fb8f4751473ccc2af3ee0aecddb",
    "fasta_500_sha256": "0849d4f8aceaed37c3dc7fec69056f38ae344338aa4adf321a3e11c4a72df0b0",
    "fasta_251_sha256": "f4f436ef2eb0f17409c5145507991b688e49965a09c346ddd380942a5b1d5b5c",
    "fasta_101_sha256": "60be2b211923d303570974fced0f85e546ceb4b5b5182d2cd0a9f72f483b08b1",
}


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class BaselineConfig:
    source: Path
    raw: dict[str, Any]
    config_sha256: str
    semantic_sha256: str
    seed: int
    windows: tuple[int, ...]
    baselines: tuple[str, ...]
    development_protein_ids: tuple[int, ...]
    c_grid: tuple[float, ...]
    max_iter: int
    tol: float


def load_config(path: Path) -> BaselineConfig:
    raw_bytes = path.read_bytes()
    raw = tomllib.loads(raw_bytes.decode())
    required = {"schema_version", "seed", "windows", "baselines", "development_protein_ids", "c_grid", "logistic_regression", "features", "gc_matching", "inputs"}
    missing = sorted(required - raw.keys())
    if missing:
        raise BaselineConfigError(f"missing configuration sections: {missing}")
    if raw["schema_version"] != "task003b_simple_baselines_v1":
        raise BaselineConfigError("unexpected schema_version")
    checks = (
        (int(raw["seed"]), FROZEN_SEED, "seed"),
        (tuple(map(int, raw["windows"])), FROZEN_WINDOWS, "windows"),
        (tuple(map(str, raw["baselines"])), FROZEN_BASELINES, "baselines"),
        (tuple(map(int, raw["development_protein_ids"])), FROZEN_DEVELOPMENT_PROTEINS, "development proteins"),
        (tuple(map(float, raw["c_grid"])), FROZEN_C_GRID, "C grid"),
    )
    for actual, expected, label in checks:
        if actual != expected:
            raise BaselineConfigError(f"{label} drift: {actual!r} != {expected!r}")
    logistic = raw["logistic_regression"]
    expected_logistic = {
        "penalty": "l2", "solver": "liblinear", "fit_intercept": True,
        "class_weight": "none", "max_iter": 2000, "tol": 1e-6,
        "intercept_scaling": 1.0,
    }
    if logistic != expected_logistic:
        raise BaselineConfigError("logistic-regression contract drift")
    features = raw["features"]
    if features != {
        "alphabet": "ACGT",
        "kmer_normalization": "overlapping_count_divided_by_L_minus_k_plus_1",
        "reverse_complement_collapse": False,
        "gc_scaler": "standard_train_mean_sd",
        "kmer_scaler": "standard_train_sd_without_centering",
    }:
        raise BaselineConfigError("feature contract drift")
    matching = raw["gc_matching"]
    if matching != {
        "quantile_probabilities": [i / 10 for i in range(11)],
        "quantile_method": "linear", "duplicate_edges": "collapse",
        "bin_closure": "right", "no_replacement": True,
    }:
        raise BaselineConfigError("GC-matching contract drift")
    if raw["inputs"] != FROZEN_INPUTS:
        raise BaselineConfigError("frozen input hashes drift")
    return BaselineConfig(
        source=path,
        raw=raw,
        config_sha256=sha256_bytes(raw_bytes),
        semantic_sha256=sha256_bytes(canonical_json(raw)),
        seed=int(raw["seed"]),
        windows=tuple(map(int, raw["windows"])),
        baselines=tuple(map(str, raw["baselines"])),
        development_protein_ids=tuple(map(int, raw["development_protein_ids"])),
        c_grid=tuple(map(float, raw["c_grid"])),
        max_iter=int(logistic["max_iter"]),
        tol=float(logistic["tol"]),
    )
