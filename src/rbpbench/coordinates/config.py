"""Load the frozen, human-readable Task 001 coordinate-feasibility configuration.

Every seed, threshold, tool version, contig-policy entry, resource limit, and
output path lives in ``configs/coordinate_feasibility.toml`` (never as a
hard-coded literal in pipeline code), so a reviewer can audit the whole
scientific contract in one file.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from rbpbench.coordinates.alignment import ClassificationThresholds


@dataclass(frozen=True)
class SamplingConfig:
    seed: int
    total_size: int
    representative_size: int
    min_positive_per_protein: int
    min_negative_per_protein: int
    num_proteins: int


@dataclass(frozen=True)
class ControlsConfig:
    count: int
    max_shuffle_attempts: int


@dataclass(frozen=True)
class ToolsConfig:
    bwa_version: str
    minimap2_version: str
    seqkit_version: str


@dataclass(frozen=True)
class ResourceLimits:
    max_threads: int
    max_new_disk_gib: float
    min_free_disk_gib: float
    min_ram_gib_for_mapping: float


@dataclass(frozen=True)
class ContigPolicy:
    include_categories: tuple[str, ...]
    exclude_categories: tuple[str, ...]


@dataclass(frozen=True)
class OutputPaths:
    sample_ids_tsv: str
    mappings_tsv_gz: str
    report_json: str
    report_md: str
    dry_run_json: str


@dataclass(frozen=True)
class FeasibilityConfig:
    sequence_length_nt: int
    sampling: SamplingConfig
    controls: ControlsConfig
    thresholds: ClassificationThresholds
    near_tied_fractions: tuple[float, ...]
    tools: ToolsConfig
    resources: ResourceLimits
    contig_policy: ContigPolicy
    outputs: OutputPaths


def load_config(path: Path) -> FeasibilityConfig:
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)

    sampling_raw = raw["sampling"]
    controls_raw = raw["controls"]
    thresholds_raw = raw["thresholds"]
    tools_raw = raw["tools"]
    resources_raw = raw["resources"]
    contig_raw = raw["contig_policy"]
    outputs_raw = raw["outputs"]

    return FeasibilityConfig(
        sequence_length_nt=raw["sequence_length_nt"],
        sampling=SamplingConfig(
            seed=sampling_raw["seed"],
            total_size=sampling_raw["total_size"],
            representative_size=sampling_raw["representative_size"],
            min_positive_per_protein=sampling_raw["min_positive_per_protein"],
            min_negative_per_protein=sampling_raw["min_negative_per_protein"],
            num_proteins=sampling_raw["num_proteins"],
        ),
        controls=ControlsConfig(
            count=controls_raw["count"],
            max_shuffle_attempts=controls_raw["max_shuffle_attempts"],
        ),
        thresholds=ClassificationThresholds(
            high_conf_min_coverage=thresholds_raw["high_conf_min_coverage"],
            high_conf_min_identity=thresholds_raw["high_conf_min_identity"],
            secondary_min_coverage=thresholds_raw["secondary_min_coverage"],
            secondary_min_identity=thresholds_raw["secondary_min_identity"],
        ),
        near_tied_fractions=tuple(thresholds_raw["near_tied_fractions"]),
        tools=ToolsConfig(
            bwa_version=tools_raw["bwa_version"],
            minimap2_version=tools_raw["minimap2_version"],
            seqkit_version=tools_raw["seqkit_version"],
        ),
        resources=ResourceLimits(
            max_threads=resources_raw["max_threads"],
            max_new_disk_gib=resources_raw["max_new_disk_gib"],
            min_free_disk_gib=resources_raw["min_free_disk_gib"],
            min_ram_gib_for_mapping=resources_raw["min_ram_gib_for_mapping"],
        ),
        contig_policy=ContigPolicy(
            include_categories=tuple(contig_raw["include_categories"]),
            exclude_categories=tuple(contig_raw["exclude_categories"]),
        ),
        outputs=OutputPaths(
            sample_ids_tsv=outputs_raw["sample_ids_tsv"],
            mappings_tsv_gz=outputs_raw["mappings_tsv_gz"],
            report_json=outputs_raw["report_json"],
            report_md=outputs_raw["report_md"],
            dry_run_json=outputs_raw["dry_run_json"],
        ),
    )
