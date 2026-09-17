"""Reference and generated-artifact manifest schema.

Reuses the project's existing SHA-256 helper rather than duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rbpbench.data.audit import sha256_file

SCHEMA_VERSION = 1


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
