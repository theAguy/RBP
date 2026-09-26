"""Load the frozen Task 002 sequence-partition configuration.

Mirrors ``rbpbench.coordinates.config``'s pattern: every seed, resource
limit, protected width, and fixed real-input expectation lives in
``configs/splits/sequence_partitions_v1.toml`` (never a hard-coded literal in
runner code), so a reviewer can audit the whole operational contract in one
file. Scientific identity/coverage/``--max-seqs`` values are NOT loaded from
here -- they are hardcoded in :mod:`rbpbench.splits.commands`, which accepts
no caller-configurable override, so this loader cannot become a back door for
a scientific-threshold change.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from rbpbench.coordinates.hashing import content_fingerprint


@dataclass(frozen=True)
class DatasetExpectations:
    csv_filename: str
    csv_sha256: str
    csv_byte_size: int
    expected_row_count: int
    audit_json_path: str
    audit_json_sha256: str
    proteins_tsv_path: str
    proteins_tsv_sha256: str


@dataclass(frozen=True)
class ResourceLimits:
    max_threads: int
    timeout_seconds: int
    max_new_disk_gib: float
    min_free_disk_gib: float
    min_installed_ram_gib: float
    min_available_memory_gib_before_launch: float
    resource_poll_interval_seconds: float


@dataclass(frozen=True)
class ProbeConfig:
    sample_size: int
    max_peak_memory_gib: float
    min_available_memory_gib_before_next_stage: float


@dataclass(frozen=True)
class GateConfig:
    giant_single_component_fraction: float
    giant_top20_fraction: float


@dataclass(frozen=True)
class BinaryExpectations:
    mmseqs_sha256: str


@dataclass(frozen=True)
class SplitsConfig:
    seed: int
    protected_widths: tuple[int, ...]
    dataset: DatasetExpectations
    resources: ResourceLimits
    probe: ProbeConfig
    gate: GateConfig
    binary: BinaryExpectations
    source_path: str
    content_hash: str


def load_config(path: Path) -> SplitsConfig:
    path = Path(path)
    raw_text = path.read_text()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    dataset_raw = raw["dataset"]
    resources_raw = raw["resources"]
    probe_raw = raw["probe"]
    gate_raw = raw["gate"]
    binary_raw = raw["binary"]

    return SplitsConfig(
        seed=raw["seed"],
        protected_widths=tuple(raw["protected_widths"]),
        dataset=DatasetExpectations(
            csv_filename=dataset_raw["csv_filename"],
            csv_sha256=dataset_raw["csv_sha256"],
            csv_byte_size=dataset_raw["csv_byte_size"],
            expected_row_count=dataset_raw["expected_row_count"],
            audit_json_path=dataset_raw["audit_json_path"],
            audit_json_sha256=dataset_raw["audit_json_sha256"],
            proteins_tsv_path=dataset_raw["proteins_tsv_path"],
            proteins_tsv_sha256=dataset_raw["proteins_tsv_sha256"],
        ),
        resources=ResourceLimits(
            max_threads=resources_raw["max_threads"],
            timeout_seconds=resources_raw["timeout_seconds"],
            max_new_disk_gib=resources_raw["max_new_disk_gib"],
            min_free_disk_gib=resources_raw["min_free_disk_gib"],
            min_installed_ram_gib=resources_raw["min_installed_ram_gib"],
            min_available_memory_gib_before_launch=resources_raw["min_available_memory_gib_before_launch"],
            resource_poll_interval_seconds=resources_raw["resource_poll_interval_seconds"],
        ),
        probe=ProbeConfig(
            sample_size=probe_raw["sample_size"],
            max_peak_memory_gib=probe_raw["max_peak_memory_gib"],
            min_available_memory_gib_before_next_stage=probe_raw["min_available_memory_gib_before_next_stage"],
        ),
        gate=GateConfig(
            giant_single_component_fraction=gate_raw["giant_single_component_fraction"],
            giant_top20_fraction=gate_raw["giant_top20_fraction"],
        ),
        binary=BinaryExpectations(mmseqs_sha256=binary_raw["mmseqs_sha256"]),
        source_path=str(path),
        content_hash=content_fingerprint("splits_config_v1", raw_text),
    )


__all__ = [
    "DatasetExpectations",
    "ResourceLimits",
    "ProbeConfig",
    "GateConfig",
    "BinaryExpectations",
    "SplitsConfig",
    "load_config",
]
