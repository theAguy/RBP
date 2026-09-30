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

# The frozen scientific/protocol invariants every real run's config MUST
# match exactly (docs/reviews/002c1_partition_orchestration_correction_review.md,
# C1: "A config field must either drive the implementation or be checked
# against the reviewed code constant; it may not be silently dead."). Every
# one of these fields ALSO genuinely drives the implementation (threaded
# through :func:`rbpbench.splits.assignment.assign_partitions` and
# :func:`rbpbench.splits.legacy_diagnostic.run_legacy_fold`); this table is
# an independent cross-check that a config edit can never silently drift
# from the reviewed contract those modules' own docstrings freeze.
FROZEN_PROTECTED_WIDTHS: tuple[int, ...] = (500, 251, 101)


class FrozenInvariantError(ValueError):
    """A configured value that must match a reviewed, frozen scientific
    constant does not. Raised at config-load time, before any real stage
    can run with a silently drifted value.
    """


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
    max_repair_proposals: int
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
class Decode002BExpectations:
    """Pins the already committed, sanitized Task 002B-2 decode-evidence
    manifest (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md,
    F2) -- the per-width accepted ``sequence_partitions_width_<width>.fasta``
    byte size/SHA-256 and the accepted decode-duplicate-edge artifacts
    (F4) are auto-extracted from this manifest at run time, never a second,
    independently hard-coded copy of those values here.
    """

    manifest_path: str
    manifest_sha256: str


@dataclass(frozen=True)
class ReturnBundleFileExpectation:
    """Pinned provenance for one small file at the root of the accepted
    Task 002B return bundle (``RETURN_MANIFEST.json``/``RETURN_INVENTORY.json``),
    resolved only as a pinned child beneath the portable return root -- never
    a hard-coded collaborator absolute path
    (docs/handoffs/002c2a_legacy_cluster_evidence_claude_handoff.md).
    """

    relative_path: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class ClusterMembershipFileExpectation:
    """Pinned per-width provenance for one accepted Task 002B connected-
    component cluster-membership TSV (``mmseqs createtsv`` output) and its
    own selected record, resolved only as pinned children beneath the
    portable Task 002B return root. A membership row is cluster
    co-membership -- direct or transitive -- never a direct pairwise
    similarity edge (docs/tasks/002c2a_legacy_cluster_evidence.md).
    """

    membership_relative_path: str
    membership_byte_size: int
    membership_sha256: str
    selected_record_relative_path: str
    selected_record_byte_size: int
    selected_record_sha256: str
    expected_generation_digest: str
    expected_member_count: int
    expected_cluster_count: int
    expected_largest_cluster_size: int
    evidence_kind: str


@dataclass(frozen=True)
class LegacyClusterEvidenceConfig:
    """Pinned provenance for the legacy-diagnostic's accepted cluster-
    membership evidence (Task 002C-2A correction, replacing the retired
    ``[legacy_edges.similarity_edges]`` impossible placeholder). Binds the
    accepted Task 002B return's ``RETURN_MANIFEST.json``/``RETURN_INVENTORY.json``
    plus, per protected width, the accepted membership TSV and its selected
    record. ``exact_rc_edges_<width>.json`` is never pinned here -- it is
    still auto-extracted from the decode-evidence manifest's own accepted
    duplicate-edge artifacts (see :class:`Decode002BExpectations`) and stays
    independently bound, unchanged.
    """

    return_manifest: ReturnBundleFileExpectation
    return_inventory: ReturnBundleFileExpectation
    cluster_membership: dict[int, ClusterMembershipFileExpectation]


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
    decode_002b2: Decode002BExpectations
    legacy_edges: LegacyClusterEvidenceConfig
    source_path: str
    content_hash: str


def validate_frozen_invariants(config: "SplitsConfig002C") -> None:
    """Fails closed if any configured value that is supposed to reproduce a
    reviewed, frozen scientific/protocol constant has drifted from it
    (docs/reviews/002c1_partition_orchestration_correction_review.md, C1).

    Every field checked here ALSO genuinely drives real behavior (it is not
    validated INSTEAD of being used) -- see
    :mod:`rbpbench.splits.assignment` and
    :mod:`rbpbench.splits.legacy_diagnostic` -- so this is a second,
    independent line of defense, not a substitute for wiring the config
    through.
    """
    from rbpbench.splits import assignment as splits_assignment
    from rbpbench.splits import audit as splits_audit
    from rbpbench.splits import legacy_diagnostic as splits_legacy_diagnostic

    problems: list[str] = []
    if config.protected_widths != FROZEN_PROTECTED_WIDTHS:
        problems.append(f"protected_widths {config.protected_widths} != frozen {FROZEN_PROTECTED_WIDTHS}")
    if dict(config.assignment.target_fractions) != dict(splits_assignment.TARGET_FRACTIONS):
        problems.append(
            f"assignment.target_fractions {config.assignment.target_fractions} != frozen "
            f"{splits_assignment.TARGET_FRACTIONS}"
        )
    if config.assignment.row_dimension_weight != splits_assignment.ROW_DIMENSION_WEIGHT:
        problems.append(
            f"assignment.row_dimension_weight {config.assignment.row_dimension_weight} != frozen "
            f"{splits_assignment.ROW_DIMENSION_WEIGHT}"
        )
    if config.assignment.protein_class_dimension_weight != splits_assignment.PROTEIN_CLASS_DIMENSION_WEIGHT:
        problems.append(
            f"assignment.protein_class_dimension_weight {config.assignment.protein_class_dimension_weight} != "
            f"frozen {splits_assignment.PROTEIN_CLASS_DIMENSION_WEIGHT}"
        )
    if config.assignment.balance_deviation_flag_pct != splits_audit.BALANCE_DEVIATION_FLAG_PCT:
        problems.append(
            f"assignment.balance_deviation_flag_pct {config.assignment.balance_deviation_flag_pct} != frozen "
            f"{splits_audit.BALANCE_DEVIATION_FLAG_PCT}"
        )
    legacy = config.legacy_diagnostic
    if legacy.n_splits != splits_legacy_diagnostic.N_SPLITS:
        problems.append(f"legacy_diagnostic.n_splits {legacy.n_splits} != frozen {splits_legacy_diagnostic.N_SPLITS}")
    if legacy.shuffle != splits_legacy_diagnostic.SHUFFLE:
        problems.append(f"legacy_diagnostic.shuffle {legacy.shuffle} != frozen {splits_legacy_diagnostic.SHUFFLE}")
    if legacy.random_state != splits_legacy_diagnostic.RANDOM_STATE:
        problems.append(
            f"legacy_diagnostic.random_state {legacy.random_state} != frozen {splits_legacy_diagnostic.RANDOM_STATE}"
        )
    if legacy.fold_index != splits_legacy_diagnostic.FOLD_INDEX:
        problems.append(
            f"legacy_diagnostic.fold_index {legacy.fold_index} != frozen {splits_legacy_diagnostic.FOLD_INDEX}"
        )
    if problems:
        raise FrozenInvariantError(
            f"{config.source_path}: configured value(s) diverge from the reviewed frozen contract: " + "; ".join(problems)
        )


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
    decode_002b2_raw = raw["decode_002b2"]
    legacy_edges_raw = raw["legacy_edges"]

    config = SplitsConfig002C(
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
            max_repair_proposals=assignment_raw["max_repair_proposals"],
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
        decode_002b2=Decode002BExpectations(
            manifest_path=decode_002b2_raw["manifest_path"],
            manifest_sha256=decode_002b2_raw["manifest_sha256"],
        ),
        legacy_edges=LegacyClusterEvidenceConfig(
            return_manifest=ReturnBundleFileExpectation(
                relative_path=legacy_edges_raw["return_manifest_relative_path"],
                byte_size=legacy_edges_raw["return_manifest_byte_size"],
                sha256=legacy_edges_raw["return_manifest_sha256"],
            ),
            return_inventory=ReturnBundleFileExpectation(
                relative_path=legacy_edges_raw["return_inventory_relative_path"],
                byte_size=legacy_edges_raw["return_inventory_byte_size"],
                sha256=legacy_edges_raw["return_inventory_sha256"],
            ),
            cluster_membership={
                int(width): ClusterMembershipFileExpectation(
                    membership_relative_path=entry["membership_relative_path"],
                    membership_byte_size=entry["membership_byte_size"],
                    membership_sha256=entry["membership_sha256"],
                    selected_record_relative_path=entry["selected_record_relative_path"],
                    selected_record_byte_size=entry["selected_record_byte_size"],
                    selected_record_sha256=entry["selected_record_sha256"],
                    expected_generation_digest=entry["expected_generation_digest"],
                    expected_member_count=entry["expected_member_count"],
                    expected_cluster_count=entry["expected_cluster_count"],
                    expected_largest_cluster_size=entry["expected_largest_cluster_size"],
                    evidence_kind=entry["evidence_kind"],
                )
                for width, entry in legacy_edges_raw["cluster_membership"].items()
            },
        ),
        source_path=str(path),
        content_hash=content_fingerprint("splits_config_002c_v1", raw_text),
    )
    validate_frozen_invariants(config)
    return config


__all__ = [
    "FROZEN_PROTECTED_WIDTHS",
    "FrozenInvariantError",
    "DatasetExpectations002C",
    "Components002BExpectations",
    "AssignmentConfig",
    "LegacyDiagnosticConfig",
    "AuditResourceConfig",
    "BinaryExpectations002C",
    "Decode002BExpectations",
    "ReturnBundleFileExpectation",
    "ClusterMembershipFileExpectation",
    "LegacyClusterEvidenceConfig",
    "SplitsConfig002C",
    "validate_frozen_invariants",
    "load_config_002c",
]
