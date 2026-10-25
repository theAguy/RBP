"""Frozen Task 002C-R3–R5 contract.

Every scientific, resource, input, and environment value used by the
workflow lives here as a reviewed constant.  ``configs/splits/
sequence_partitions_002c_v2.toml`` repeats them for review; the production
loader refuses that file unless every value is identical.  MMseqs2
scientific flags are not part of the contract at all: they are hard-coded
in :mod:`rbpbench.splits.commands` and cannot be supplied by a caller.

Tests use :func:`fixture_contract`, which may shrink the row universe,
input table, label range, evaluation floor, and timeouts for tiny fixtures.
A fixture contract is marked ``mode="fixture"``; the Darwin launcher only
accepts :func:`load_production_contract`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Mapping

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

CHECKPOINT = "002C-R3R5"
SCHEMA_VERSION = 1
CONFIG_REL = Path("configs/splits/sequence_partitions_002c_v2.toml")
WIDTHS: tuple[int, ...] = (500, 251, 101)
PARTITIONS: tuple[str, ...] = ("train", "validation", "test")
ORDERED_DIRECTIONS: tuple[tuple[str, str], ...] = (
    ("train", "validation"),
    ("validation", "train"),
    ("train", "test"),
    ("test", "train"),
    ("validation", "test"),
    ("test", "validation"),
)
GIB = 1024**3
HOUR = 3600.0


class ContractError(ValueError):
    """The supplied configuration differs from the reviewed contract."""


@dataclass(frozen=True)
class InputSpec:
    role: str
    path: str
    sha256: str
    byte_size: int | None = None


@dataclass(frozen=True)
class AssignmentContract:
    target_fractions: tuple[tuple[str, float], ...] = (("train", 0.70), ("validation", 0.15), ("test", 0.15))
    evaluation_floor: int = 30
    balance_deviation_flag_pct: float = 3.0
    row_dimension_weight: int = 244
    protein_class_dimension_weight: int = 1
    max_repair_passes: int = 5000
    max_repair_proposals: int = 2_000_000
    row_fraction_repair_limit_pct: float = 3.0
    row_fraction_acceptance_pct: float = 3.0
    protein_id_min: int = 1
    protein_id_max: int = 122

    def fractions(self) -> dict[str, float]:
        return dict(self.target_fractions)


@dataclass(frozen=True)
class ResourceContract:
    min_installed_or_allocated_ram_gib: float = 64.0
    min_slurm_memory_gib: float = 64.0
    min_available_ram_gib: float = 24.0
    live_free_floor_gib: float = 80.0
    min_quota_headroom_gib: float = 80.0
    max_swap_increase_gib: float = 2.0
    job_owned_ceiling_gib: tuple[tuple[int, float], ...] = ((500, 60.0), (251, 25.0), (101, 15.0))
    construction_timeout_hours: tuple[tuple[int, float], ...] = ((500, 18.0), (251, 4.0), (101, 2.0))
    audit_search_budget_hours: tuple[tuple[int, float], ...] = ((500, 10.0), (251, 3.0), (101, 1.0))
    auxiliary_child_timeout_hours: float = 2.0
    min_allocation_hours: float = 48.0
    min_chain_job_hours: float = 20.0
    packaging_reserve_hours: float = 2.0
    poll_interval_seconds: float = 5.0

    def ceiling_gib(self, width: int) -> float:
        return dict(self.job_owned_ceiling_gib)[width]

    def launch_free_gib(self, width: int) -> float:
        """C1: live free space before a width = 80-GiB floor + that width's ceiling."""
        return self.live_free_floor_gib + self.ceiling_gib(width)

    def construction_timeout_seconds(self, width: int) -> float:
        return dict(self.construction_timeout_hours)[width] * HOUR

    def audit_budget_seconds(self, width: int) -> float:
        return dict(self.audit_search_budget_hours)[width] * HOUR


@dataclass(frozen=True)
class EnvironmentContract:
    mmseqs_version: str = "18.8cc5c"
    mmseqs_conda_build: str = "hd6d6fdc_0"
    mmseqs_sha256: str = "d6d1bf1b50c095eb0cb66f685a7fb1d9b8b69497e1e88416fd48f28e313cc773"
    explicit_lock_sha256: str = "d9f9e7549a6bff75e55bf7f0693789c572817b9208a7127ee7714fcb0b0bce21"
    package_list_sha256: str = "14ecdd533f6390c5a1616c640a356df145eb0198bf75fc7558979f58ee349d6f"
    runtime_receipt_sha256: str = "ec64969ca0d3936fc5b2d5cdbc301e9613ae644e1a7b59be41118fe73d008dd9"


PRODUCTION_INPUTS: tuple[InputSpec, ...] = (
    InputSpec("dataset_csv", "inputs/dataset/dataset_K562_multilabel_with_NEGs.csv",
              "982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945", 724_425_277),
    InputSpec("dataset_audit", "manifests/dataset_audit.json",
              "e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c"),
    InputSpec("proteins_tsv", "configs/proteins.tsv",
              "374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9"),
    InputSpec("decode_manifest", "manifests/sequence_decode_002b2.json",
              "d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3"),
    InputSpec("fasta_500", "inputs/decode/sequence_partitions_width_500.fasta",
              "0849d4f8aceaed37c3dc7fec69056f38ae344338aa4adf321a3e11c4a72df0b0", 185_174_230),
    InputSpec("fasta_251", "inputs/decode/sequence_partitions_width_251.fasta",
              "f4f436ef2eb0f17409c5145507991b688e49965a09c346ddd380942a5b1d5b5c", 95_240_410),
    InputSpec("fasta_101", "inputs/decode/sequence_partitions_width_101.fasta",
              "60be2b211923d303570974fced0f85e546ceb4b5b5182d2cd0a9f72f483b08b1", 41_063_410),
    InputSpec("exact_rc_500", "inputs/decode/duplicate_edges_500.json",
              "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945", 2),
    InputSpec("exact_rc_251", "inputs/decode/duplicate_edges_251.json",
              "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945", 2),
    InputSpec("exact_rc_101", "inputs/decode/duplicate_edges_101.json",
              "9e3e12c9ba46196b3bfc6f01034922438481b529880190fc29189823f3d64282", 59),
    InputSpec("r2_return_manifest", "manifests/sequence_r2_darwin_convergence_return.json",
              "3a275d538f2167ed6a1a01b80bfb34295890ac1f5d30611fb5e34bf2e5d02123", 5_001),
    InputSpec("v1_component_membership", "inputs/v1/component_membership.tsv.gz",
              "6000c340056ba8204432e7f4c417fb811f8a3d1a5b1c091dea98461862c7b692", 14_578_797),
    InputSpec("v1_component_report", "inputs/v1/component_report.json",
              "b8b5872a4cc5061c562de871ec4500876fcdb72afcab069b21ab2bb44cb3e186", 13_036_977),
)
REQUIRED_INPUT_ROLES: frozenset[str] = frozenset(spec.role for spec in PRODUCTION_INPUTS)


@dataclass(frozen=True)
class Contract:
    mode: str = "production"
    checkpoint: str = CHECKPOINT
    schema_version: int = SCHEMA_VERSION
    seed: int = 20260925
    row_count: int = 361_180
    widths: tuple[int, ...] = WIDTHS
    mmseqs_threads: int = 4
    max_audit_cycles: int = 2
    v1_expected_component_count: int = 173_465
    giant_single_fraction: float = 0.05
    giant_top20_fraction: float = 0.20
    positive_control_self_hits: int = 100
    positive_control_max_edges: int = 100
    membership_limit_bytes: int = 128 * 1024**2
    report_or_log_limit_bytes: int = 64 * 1024**2
    aggregate_log_limit_bytes: int = 2 * GIB
    assignment: AssignmentContract = field(default_factory=AssignmentContract)
    resources: ResourceContract = field(default_factory=ResourceContract)
    environment: EnvironmentContract = field(default_factory=EnvironmentContract)
    inputs: tuple[InputSpec, ...] = PRODUCTION_INPUTS

    def input(self, role: str) -> InputSpec:
        for spec in self.inputs:
            if spec.role == role:
                return spec
        raise ContractError(f"contract has no input role {role!r}")

    def universe(self) -> list[str]:
        return [f"row_{i}" for i in range(self.row_count)]

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self)))

    @property
    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


PRODUCTION = Contract()


def fixture_contract(**overrides) -> Contract:
    """Tiny-fixture contract for tests.  Never accepted by the Darwin launcher."""
    assignment_overrides = overrides.pop("assignment", {})
    resource_overrides = overrides.pop("resources", {})
    environment_overrides = overrides.pop("environment", {})
    base = replace(
        PRODUCTION,
        mode="fixture",
        assignment=replace(PRODUCTION.assignment, **assignment_overrides),
        resources=replace(PRODUCTION.resources, **resource_overrides),
        environment=replace(PRODUCTION.environment, **environment_overrides),
    )
    return replace(base, **overrides)


def _pairs(mapping: Mapping[str, float]) -> tuple[tuple[int, float], ...]:
    return tuple(sorted(((int(k), float(v)) for k, v in mapping.items()), key=lambda kv: WIDTHS.index(kv[0])))


def contract_from_toml(data: Mapping) -> Contract:
    """Parses the TOML layout into a :class:`Contract` without validating it."""
    a, r, e = data["assignment"], data["resources"], data["environment"]
    inputs = tuple(
        InputSpec(role, spec["path"], spec["sha256"], spec.get("byte_size"))
        for role, spec in data["inputs"].items()
    )
    order = {spec.role: i for i, spec in enumerate(PRODUCTION_INPUTS)}
    inputs = tuple(sorted(inputs, key=lambda s: order.get(s.role, len(order))))
    tf = a["target_fractions"]
    return Contract(
        mode=data["mode"],
        checkpoint=data["checkpoint"],
        schema_version=data["schema_version"],
        seed=data["seed"],
        row_count=data["row_count"],
        widths=tuple(data["protected_widths"]),
        mmseqs_threads=data["mmseqs_threads"],
        max_audit_cycles=data["max_audit_cycles"],
        v1_expected_component_count=data["v1_protected_relation"]["expected_component_count"],
        giant_single_fraction=data["giant_gate"]["single_component_fraction"],
        giant_top20_fraction=data["giant_gate"]["top20_fraction"],
        positive_control_self_hits=data["positive_control"]["self_hits"],
        positive_control_max_edges=data["positive_control"]["max_construction_edges"],
        membership_limit_bytes=data["return_limits"]["membership_decompressed_mib"] * 1024**2,
        report_or_log_limit_bytes=data["return_limits"]["report_or_log_mib"] * 1024**2,
        aggregate_log_limit_bytes=data["return_limits"]["aggregate_log_gib"] * GIB,
        assignment=AssignmentContract(
            target_fractions=(("train", tf["train"]), ("validation", tf["validation"]), ("test", tf["test"])),
            evaluation_floor=a["evaluation_floor"],
            balance_deviation_flag_pct=a["balance_deviation_flag_pct"],
            row_dimension_weight=a["row_dimension_weight"],
            protein_class_dimension_weight=a["protein_class_dimension_weight"],
            max_repair_passes=a["max_repair_passes"],
            max_repair_proposals=a["max_repair_proposals"],
            row_fraction_repair_limit_pct=a["row_fraction_repair_limit_pct"],
            row_fraction_acceptance_pct=a["row_fraction_acceptance_pct"],
            protein_id_min=a["protein_id_min"],
            protein_id_max=a["protein_id_max"],
        ),
        resources=ResourceContract(
            min_installed_or_allocated_ram_gib=r["min_installed_or_allocated_ram_gib"],
            min_slurm_memory_gib=r["min_slurm_memory_gib"],
            min_available_ram_gib=r["min_available_ram_gib"],
            live_free_floor_gib=r["live_free_floor_gib"],
            min_quota_headroom_gib=r["min_quota_headroom_gib"],
            max_swap_increase_gib=r["max_swap_increase_gib"],
            job_owned_ceiling_gib=_pairs(r["job_owned_ceiling_gib"]),
            construction_timeout_hours=_pairs(r["construction_timeout_hours"]),
            audit_search_budget_hours=_pairs(r["audit_search_budget_hours"]),
            auxiliary_child_timeout_hours=r["auxiliary_child_timeout_hours"],
            min_allocation_hours=r["min_allocation_hours"],
            min_chain_job_hours=r["min_chain_job_hours"],
            packaging_reserve_hours=r["packaging_reserve_hours"],
            poll_interval_seconds=r["poll_interval_seconds"],
        ),
        environment=EnvironmentContract(**e),
        inputs=inputs,
    )


def load_production_contract(config_path: Path) -> Contract:
    """Loads the versioned TOML and requires it to equal the reviewed constants."""
    try:
        data = tomllib.loads(Path(config_path).read_text())
        parsed = contract_from_toml(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError(f"{config_path}: malformed R3–R5 configuration: {exc}") from exc
    if parsed != PRODUCTION:
        differing = sorted(
            key for key, value in parsed.to_dict().items() if PRODUCTION.to_dict().get(key) != value
        )
        raise ContractError(f"{config_path} differs from the reviewed R3–R5 contract in: {differing}")
    return parsed


__all__ = [
    "CHECKPOINT", "CONFIG_REL", "WIDTHS", "PARTITIONS", "ORDERED_DIRECTIONS", "GIB", "HOUR",
    "ContractError", "InputSpec", "AssignmentContract", "ResourceContract", "EnvironmentContract",
    "Contract", "PRODUCTION", "PRODUCTION_INPUTS", "REQUIRED_INPUT_ROLES",
    "fixture_contract", "contract_from_toml", "load_production_contract",
]
