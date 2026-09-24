"""Checked-in Task 001B execution-source specification.

Loads ``configs/coordinate_execution_sources.toml`` (frozen four local-input
hashes, both NCBI RefSeq reference sources, and the derived-reference
policy — see ``docs/tasks/001b_coordinate_feasibility_execution.md``) and
implements the fail-closed comparison that must run before the real CSV can
be opened. B1 only implements and tests this against tiny fixture paths and
fixture hashes; it never opens the real 724-MB CSV and never requests either
reference source's URL (see ``rbpbench.coordinates.download`` for the
restart-safe downloader used only in later checkpoints).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from rbpbench.data.audit import sha256_file

LOCAL_INPUT_KEYS = ("dataset_csv", "dataset_audit", "proteins_config", "study_config")


@dataclass(frozen=True)
class LocalInputSpec:
    path: str
    sha256: str


@dataclass(frozen=True)
class ReferenceSourceSpec:
    build_id: str
    assembly: str
    refseq_assembly_accession: str
    fasta_url: str
    fasta_compressed_byte_size: int
    fasta_upstream_md5: str
    assembly_report_url: str
    assembly_report_md5: str
    md5checksums_url: str

    @property
    def fasta_remote_basename(self) -> str:
        """B3A-A1: the exact remote basename (e.g.
        ``GCF_000001405.40_GRCh38.p14_genomic.fna.gz``), derived from the
        frozen ``fasta_url``'s own final path segment -- never the shorter
        ``assembly`` label (``GRCh38.p14``), which real NCBI basenames do not
        match. Used for BOTH the local destination filename and the live
        ``md5checksums.txt`` lookup key, so the two can never silently
        diverge.
        """
        return Path(urlparse(self.fasta_url).path).name

    @property
    def assembly_report_remote_basename(self) -> str:
        """Same rule as :attr:`fasta_remote_basename`, for the assembly report."""
        return Path(urlparse(self.assembly_report_url).path).name


@dataclass(frozen=True)
class DerivedReferencePolicy:
    include_sequence_roles_primary_assembly: tuple[str, ...]
    include_non_nuclear_assembled_molecule: bool
    accession_preference: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionSourceSpec:
    git_base_commit: str
    local_inputs: dict[str, LocalInputSpec]
    reference_sources: dict[str, ReferenceSourceSpec]
    derived_reference_policy: DerivedReferencePolicy


def load_execution_sources(path: Path) -> ExecutionSourceSpec:
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)

    local_inputs = {
        key: LocalInputSpec(path=entry["path"], sha256=entry["sha256"])
        for key, entry in raw["local_inputs"].items()
    }
    reference_sources = {
        build: ReferenceSourceSpec(
            build_id=build,
            assembly=entry["assembly"],
            refseq_assembly_accession=entry["refseq_assembly_accession"],
            fasta_url=entry["fasta_url"],
            fasta_compressed_byte_size=entry["fasta_compressed_byte_size"],
            fasta_upstream_md5=entry["fasta_upstream_md5"],
            assembly_report_url=entry["assembly_report_url"],
            assembly_report_md5=entry["assembly_report_md5"],
            md5checksums_url=entry["md5checksums_url"],
        )
        for build, entry in raw["reference_sources"].items()
    }
    policy_raw = raw["derived_reference_policy"]
    policy = DerivedReferencePolicy(
        include_sequence_roles_primary_assembly=tuple(policy_raw["include_sequence_roles_primary_assembly"]),
        include_non_nuclear_assembled_molecule=bool(policy_raw["include_non_nuclear_assembled_molecule"]),
        accession_preference=tuple(policy_raw["accession_preference"]),
    )
    return ExecutionSourceSpec(
        git_base_commit=raw["git_base_commit"],
        local_inputs=local_inputs,
        reference_sources=reference_sources,
        derived_reference_policy=policy,
    )


@dataclass(frozen=True)
class LocalInputViolation:
    key: str
    detail: str


def verify_local_inputs(spec: ExecutionSourceSpec, *, paths: dict[str, Path]) -> tuple[LocalInputViolation, ...]:
    """Fail-closed expected-vs-observed hash comparison for the four frozen
    local inputs (dataset CSV, dataset audit, protein config, study config).

    ``paths`` maps each of :data:`LOCAL_INPUT_KEYS` to the real file this run
    is about to use. A missing spec entry, a missing path argument, a missing
    file, or a hash mismatch are all violations — nothing is silently
    skipped. This is a pure comparison function: computing hashes without
    checking them against ``spec`` is not sufficient (see the module
    docstring); callers must refuse to proceed (and, in particular, must not
    open the CSV for row-by-row reading) when this returns anything.
    """
    violations: list[LocalInputViolation] = []
    for key in LOCAL_INPUT_KEYS:
        expected = spec.local_inputs.get(key)
        if expected is None:
            violations.append(LocalInputViolation(key, "no expected hash recorded in the execution-source spec"))
            continue
        provided = paths.get(key)
        if provided is None:
            violations.append(LocalInputViolation(key, "no path supplied for this run"))
            continue
        provided = Path(provided)
        if not provided.is_file():
            violations.append(LocalInputViolation(key, f"file not found at {provided}"))
            continue
        observed = sha256_file(provided)
        if observed != expected.sha256:
            violations.append(
                LocalInputViolation(
                    key, f"expected sha256 {expected.sha256} but observed {observed} at {provided}"
                )
            )
    return tuple(violations)


__all__ = [
    "LOCAL_INPUT_KEYS",
    "LocalInputSpec",
    "ReferenceSourceSpec",
    "DerivedReferencePolicy",
    "ExecutionSourceSpec",
    "load_execution_sources",
    "LocalInputViolation",
    "verify_local_inputs",
]
