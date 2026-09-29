"""Load the Task 002C-specific partition-assignment/audit configuration.

Deliberately a SEPARATE loader/file from :mod:`rbpbench.splits.config`
(Task 002B's own ``sequence_partitions_v1.toml``): Task 002C must never
mutate Task 002B's accepted config in a way that could invalidate its
accepted selected records
(``docs/handoffs/002c1_partition_orchestration_claude_handoff.md``, item 1).
Every seed, weight, floor, threshold, and resource limit used by the Task
002C runner lives in ``configs/splits/sequence_partitions_002c_v1.toml``,
never a hard-coded literal in runner/assignment code, so a reviewer can
audit the whole operational contract in one file. As with the 002B loader,
scientific MMseqs2 identity/coverage/``--max-seqs`` flags are NOT loaded
from here -- they stay hardcoded in :mod:`rbpbench.splits.commands`.
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
class DatasetExpectations002C:
    csv_filename: str
    csv_sha256: str
    csv_byte_size: int
    expected_row_count: int
    audit_json_path: str
    audit_json_sha256: str
    proteins_tsv_path: str
    proteins_tsv_sha256: str
    protein_id_min: int
    protein_id_max: int


@dataclass(frozen=True)
class Components002BExpectations:
    membership_byte_size: int
    membership_sha256: str
    report_byte_size: int
    report_sha256: str
    expected_component_count: int


@dataclass(frozen=True)
class AssignmentConfig:
    target_fractions: dict[str, float]
    evaluation_floor: int
    balance_deviation_flag_pct: float
    row_dimension_weight: int
    protein_class_dimension_weight: int
    max_repair_passes: int
    row_fraction_repair_limit_pct: float


@dataclass(frozen=True)
class LegacyDiagnosticConfig:
    python_version: str
    numpy_version: str
    scipy_version: str
    scikit_learn_version: str
    iterative_stratification_version: str
    n_splits: int
    shuffle: bool
    random_state: int
    fold_index: int


@dataclass(frozen=True)
class AuditResourceConfig:
    max_threads: int
    timeout_seconds: int
    max_new_disk_gib: float
    min_free_disk_gib: float
    min_installed_ram_gib: float
    min_available_memory_gib_before_launch: float
    resource_poll_interval_seconds: float
    probe_sample_size: int
    probe_max_peak_memory_gib: float
    probe_min_available_memory_gib_before_next_stage: float


@dataclass(frozen=True)
class BinaryExpectations002C:
    mmseqs_sha256: str


@dataclass(frozen=True)
class SplitsConfig002C:
    seed: int
    protected_widths: tuple[int, ...]
    dataset: DatasetExpectations002C
    components_002b: Components002BExpectations
    assignment: AssignmentConfig
    legacy_diagnostic: LegacyDiagnosticConfig
    audit: AuditResourceConfig
    binary: BinaryExpectations002C
    source_path: str
    content_hash: str


def load_config_002c(path: Path) -> SplitsConfig002C:
    path = Path(path)
    raw_text = path.read_text()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    dataset_raw = raw["dataset"]
    components_raw = raw["components_002b"]
    assignment_raw = raw["assignment"]
    legacy_raw = raw["legacy_diagnostic"]
    audit_raw = raw["audit"]
    binary_raw = raw["binary"]

    return SplitsConfig002C(
        seed=raw["seed"],
        protected_widths=tuple(raw["protected_widths"]),
        dataset=DatasetExpectations002C(
            csv_filename=dataset_raw["csv_filename"],
            csv_sha256=dataset_raw["csv_sha256"],
            csv_byte_size=dataset_raw["csv_byte_size"],
            expected_row_count=dataset_raw["expected_row_count"],
            audit_json_path=dataset_raw["audit_json_path"],
            audit_json_sha256=dataset_raw["audit_json_sha256"],
            proteins_tsv_path=dataset_raw["proteins_tsv_path"],
            proteins_tsv_sha256=dataset_raw["proteins_tsv_sha256"],
            protein_id_min=dataset_raw["protein_id_min"],
            protein_id_max=dataset_raw["protein_id_max"],
        ),
        components_002b=Components002BExpectations(
            membership_byte_size=components_raw["membership_byte_size"],
            membership_sha256=components_raw["membership_sha256"],
            report_byte_size=components_raw["report_byte_size"],
            report_sha256=components_raw["report_sha256"],
            expected_component_count=components_raw["expected_component_count"],
        ),
        assignment=AssignmentConfig(
            target_fractions=dict(assignment_raw["target_fractions"]),
            evaluation_floor=assignment_raw["evaluation_floor"],
            balance_deviation_flag_pct=assignment_raw["balance_deviation_flag_pct"],
            row_dimension_weight=assignment_raw["row_dimension_weight"],
            protein_class_dimension_weight=assignment_raw["protein_class_dimension_weight"],
            max_repair_passes=assignment_raw["max_repair_passes"],
            row_fraction_repair_limit_pct=assignment_raw["row_fraction_repair_limit_pct"],
        ),
        legacy_diagnostic=LegacyDiagnosticConfig(
            python_version=legacy_raw["python_version"],
            numpy_version=legacy_raw["numpy_version"],
            scipy_version=legacy_raw["scipy_version"],
            scikit_learn_version=legacy_raw["scikit_learn_version"],
            iterative_stratification_version=legacy_raw["iterative_stratification_version"],
            n_splits=legacy_raw["n_splits"],
            shuffle=legacy_raw["shuffle"],
            random_state=legacy_raw["random_state"],
            fold_index=legacy_raw["fold_index"],
        ),
        audit=AuditResourceConfig(
            max_threads=audit_raw["max_threads"],
            timeout_seconds=audit_raw["timeout_seconds"],
            max_new_disk_gib=audit_raw["max_new_disk_gib"],
            min_free_disk_gib=audit_raw["min_free_disk_gib"],
            min_installed_ram_gib=audit_raw["min_installed_ram_gib"],
            min_available_memory_gib_before_launch=audit_raw["min_available_memory_gib_before_launch"],
            resource_poll_interval_seconds=audit_raw["resource_poll_interval_seconds"],
            probe_sample_size=audit_raw["probe_sample_size"],
            probe_max_peak_memory_gib=audit_raw["probe_max_peak_memory_gib"],
            probe_min_available_memory_gib_before_next_stage=audit_raw["probe_min_available_memory_gib_before_next_stage"],
        ),
        binary=BinaryExpectations002C(mmseqs_sha256=binary_raw["mmseqs_sha256"]),
        source_path=str(path),
        content_hash=content_fingerprint("splits_config_002c_v1", raw_text),
    )


__all__ = [
    "DatasetExpectations002C",
    "Components002BExpectations",
    "AssignmentConfig",
    "LegacyDiagnosticConfig",
    "AuditResourceConfig",
    "BinaryExpectations002C",
    "SplitsConfig002C",
    "load_config_002c",
]
