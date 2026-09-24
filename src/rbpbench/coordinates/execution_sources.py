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

import posixpath
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


class SourceUrlLayoutError(ValueError):
    """Raised when a source URL's scheme/authority/directory does not match
    the frozen ``md5checksums_url``'s own directory closely enough to derive
    a safe, unambiguous exact-relative-path checksum-listing target for it
    (B3B-1 checksum-path correction). This is a pure, local, network-free
    computation over the frozen spec's own URLs; it never depends on a live
    listing.
    """


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

    @property
    def fasta_expected_listing_path(self) -> str:
        """B3B-1: the exact, safe, root-relative ``md5checksums.txt`` entry
        path this source's FASTA must appear at -- derived purely from the
        frozen ``fasta_url`` relative to the frozen ``md5checksums_url``'s
        own directory (never from the shorter ``assembly`` label, and never
        by matching any listing entry's basename regardless of its
        directory). Raises :class:`SourceUrlLayoutError` if the FASTA URL's
        scheme/authority/directory does not exactly match the checksum
        listing's own -- an inconsistent, ambiguous, or escaping
        relationship must fail closed rather than guess a target path.
        """
        return self._expected_listing_path(self.fasta_url, label="fasta")

    @property
    def assembly_report_expected_listing_path(self) -> str:
        """Same rule as :attr:`fasta_expected_listing_path`, for the assembly report."""
        return self._expected_listing_path(self.assembly_report_url, label="assembly_report")

    def _expected_listing_path(self, source_url: str, *, label: str) -> str:
        md5_parsed = urlparse(self.md5checksums_url)
        src_parsed = urlparse(source_url)
        md5_authority = (md5_parsed.scheme, md5_parsed.netloc)
        src_authority = (src_parsed.scheme, src_parsed.netloc)
        if src_authority != md5_authority:
            raise SourceUrlLayoutError(
                f"{label} URL scheme/authority {src_authority!r} does not match the frozen "
                f"md5checksums_url's scheme/authority {md5_authority!r} ({source_url!r} vs "
                f"{self.md5checksums_url!r})"
            )
        md5_dir = posixpath.dirname(md5_parsed.path)
        src_dir = posixpath.dirname(src_parsed.path)
        if src_dir != md5_dir:
            raise SourceUrlLayoutError(
                f"{label} URL directory {src_dir!r} does not match the frozen md5checksums_url's "
                f"directory {md5_dir!r} ({source_url!r} vs {self.md5checksums_url!r}); only an exact "
                "root-relative target in the same directory as the checksum listing is accepted"
            )
        basename = posixpath.basename(src_parsed.path)
        if not basename:
            raise SourceUrlLayoutError(f"{label} URL has no basename: {source_url!r}")
        return basename


@dataclass(frozen=True)
class DerivedReferencePolicy:
    include_sequence_roles_primary_assembly: tuple[str, ...]
    include_non_nuclear_assembled_molecule: bool
    accession_preference: tuple[str, ...]


# B3B-1 accession-policy correction: the only source accession namespaces the
# derivation code understands how to read from an NCBI assembly-report row.
SUPPORTED_ACCESSION_NAMESPACES = ("refseq", "genbank")

# The NCBI Sequence-Role vocabulary values this study's derivation policy may
# name in ``include_sequence_roles_primary_assembly``. Not every value here is
# necessarily included by the frozen production policy -- this is the set of
# values ``contig_category`` (rbpbench.coordinates.derive_reference) knows how
# to map to a study contig category at all, so an unknown value can never be
# silently ignored as "just not included".
KNOWN_SEQUENCE_ROLES = (
    "assembled-molecule",
    "unlocalized-scaffold",
    "unplaced-scaffold",
)


def validate_derived_reference_policy(policy: DerivedReferencePolicy) -> tuple[str, ...]:
    """B3B-1: fail-closed validation of a loaded :class:`DerivedReferencePolicy`
    that MUST run before any source/reference/dataset data access (see the
    runner's execution-source loading, immediately after
    :func:`load_execution_sources` and before the CSV is opened).

    Checks: ``accession_preference`` is nonempty, names only namespaces in
    :data:`SUPPORTED_ACCESSION_NAMESPACES`, and has no duplicate entry;
    ``include_sequence_roles_primary_assembly`` is nonempty and names only
    nonempty strings from :data:`KNOWN_SEQUENCE_ROLES`, with no duplicate
    entry. An unknown, empty, or duplicate accession namespace, or a
    malformed/empty role list, must stop the run here -- never reach
    derivation and silently misinterpret it. Returns the violations (empty
    means valid).
    """
    violations: list[str] = []

    preference = policy.accession_preference
    if not preference:
        violations.append("derived_reference_policy.accession_preference is empty")
    else:
        seen_namespaces: set[str] = set()
        for namespace in preference:
            if namespace not in SUPPORTED_ACCESSION_NAMESPACES:
                violations.append(
                    f"derived_reference_policy.accession_preference names unsupported namespace {namespace!r} "
                    f"(supported: {SUPPORTED_ACCESSION_NAMESPACES})"
                )
            elif namespace in seen_namespaces:
                violations.append(
                    f"derived_reference_policy.accession_preference names duplicate namespace {namespace!r}"
                )
            seen_namespaces.add(namespace)

    roles = policy.include_sequence_roles_primary_assembly
    if not roles:
        violations.append("derived_reference_policy.include_sequence_roles_primary_assembly is empty")
    else:
        seen_roles: set[str] = set()
        for role in roles:
            if not isinstance(role, str) or not role.strip():
                violations.append(
                    "derived_reference_policy.include_sequence_roles_primary_assembly contains an empty/"
                    f"malformed role {role!r}"
                )
                continue
            if role not in KNOWN_SEQUENCE_ROLES:
                violations.append(
                    "derived_reference_policy.include_sequence_roles_primary_assembly names unknown role "
                    f"{role!r} (known: {KNOWN_SEQUENCE_ROLES})"
                )
            elif role in seen_roles:
                violations.append(
                    "derived_reference_policy.include_sequence_roles_primary_assembly names duplicate role "
                    f"{role!r}"
                )
            seen_roles.add(role)

    return tuple(violations)


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
    "SourceUrlLayoutError",
    "SUPPORTED_ACCESSION_NAMESPACES",
    "KNOWN_SEQUENCE_ROLES",
    "validate_derived_reference_policy",
]
