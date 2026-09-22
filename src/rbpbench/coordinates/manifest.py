"""Reference and generated-artifact manifest schema.

Reuses the project's existing SHA-256 helper rather than duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rbpbench.data.audit import sha256_file

SCHEMA_VERSION = 1

REQUIRED_REFERENCE_MANIFEST_FIELDS = (
    "build_id",
    "assembly_accession",
    "source_url",
    "contig_categories_included",
    "byte_size",
    "sha256",
)


def validate_reference_manifest(manifest: dict, *, build: str, reference: Path) -> tuple[str, ...]:
    """Validate a supplied reference-manifest dict against the real reference
    file before real mapping/exact-match is allowed to use it.

    A manifest is not merely present-or-absent evidence: its declared
    ``build_id``, ``byte_size``, and ``sha256`` must actually match the
    reference file this run is about to submit to the mapper, so a stale or
    mismatched manifest cannot be silently attributed to the wrong reference.
    Returns an empty tuple when the manifest is valid, else the violations.
    """
    violations: list[str] = []
    for field_name in REQUIRED_REFERENCE_MANIFEST_FIELDS:
        if field_name not in manifest or manifest[field_name] in (None, ""):
            violations.append(f"reference manifest missing required field {field_name!r}")
    if violations:
        return tuple(violations)

    if manifest["build_id"] != build:
        violations.append(
            f"reference manifest build_id {manifest['build_id']!r} does not match requested build {build!r}"
        )

    reference = Path(reference)
    if not reference.is_file():
        violations.append(f"reference file not found at {reference}")
        return tuple(violations)

    actual_size = reference.stat().st_size
    if manifest["byte_size"] != actual_size:
        violations.append(
            f"reference manifest byte_size {manifest['byte_size']} does not match actual size {actual_size}"
        )
    actual_sha256 = sha256_file(reference)
    if manifest["sha256"] != actual_sha256:
        violations.append(
            f"reference manifest sha256 {manifest['sha256']!r} does not match actual hash {actual_sha256!r}"
        )
    return tuple(violations)


@dataclass(frozen=True)
class ReferenceManifestEntry:
    build_id: str  # e.g. "hg38" or "hg19"
    assembly_accession: str
    source_url: str
    contig_categories_included: tuple[str, ...]
    byte_size: int
    sha256: str
    contigs: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "build_id": self.build_id,
            "assembly_accession": self.assembly_accession,
            "source_url": self.source_url,
            "contig_categories_included": list(self.contig_categories_included),
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "contigs": list(self.contigs),
        }


@dataclass(frozen=True)
class GeneratedArtifactEntry:
    path: str
    byte_size: int
    sha256: str
    produced_by_command: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "produced_by_command": self.produced_by_command,
        }


def hash_generated_artifact(path: Path, *, produced_by_command: str, root: Path) -> GeneratedArtifactEntry:
    resolved = Path(path)
    return GeneratedArtifactEntry(
        path=resolved.relative_to(root).as_posix(),
        byte_size=resolved.stat().st_size,
        sha256=sha256_file(resolved),
        produced_by_command=produced_by_command,
    )


def build_manifest(
    *,
    references: list[ReferenceManifestEntry],
    generated_artifacts: list[GeneratedArtifactEntry],
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "references": [entry.to_dict() for entry in references],
        "generated_artifacts": [entry.to_dict() for entry in generated_artifacts],
    }
