"""Deterministic ``mtime=0`` gzip membership output and sanitized
manifest/report generation.

The compressed membership file contains only ``sample_id``, ``component_id``,
``partition`` -- never a sequence or label value
(``docs/tasks/002_sequence_clustered_partitions.md``, "Outputs"). Every
manifest/report builder here follows the same rule: hashes, counts, and IDs
only.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Iterable, Mapping

MEMBERSHIP_HEADER: tuple[str, ...] = ("sample_id", "component_id", "partition")


def _atomic_write_bytes(output_path: Path, write_fn) -> None:
    """Writes via ``write_fn(tmp_path)`` then atomically replaces
    ``output_path``, so a crash mid-write can never leave a truncated file
    at ``output_path``, and a prior accepted file there is never partially
    overwritten.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    write_fn(tmp_path)
    tmp_path.replace(output_path)


def write_deterministic_membership_gzip(
    rows: Iterable[tuple[str, str, str]], output_path: Path
) -> None:
    """Writes ``sample_id\\tcomponent_id\\tpartition`` rows as a gzip file
    with ``mtime=0`` and no embedded filename, so two runs over the
    identical logical membership -- regardless of the caller's row order --
    produce byte-identical compressed output.
    """

    def _write(tmp_path: Path) -> None:
        with open(tmp_path, "wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
                gz.write(("\t".join(MEMBERSHIP_HEADER) + "\n").encode("utf-8"))
                for sample_id, cid, partition in sorted(rows):
                    gz.write(f"{sample_id}\t{cid}\t{partition}\n".encode("utf-8"))

    _atomic_write_bytes(Path(output_path), _write)


def read_membership_gzip(path: Path) -> list[tuple[str, str, str]]:
    with gzip.open(path, "rt") as handle:
        lines = [line.rstrip("\n") for line in handle]
    if not lines or tuple(lines[0].split("\t")) != MEMBERSHIP_HEADER:
        raise ValueError(f"{path}: missing or unexpected membership header")
    return [tuple(line.split("\t")) for line in lines[1:] if line]


def build_report(
    *,
    total_rows: int,
    component_sizes: Mapping[str, int],
    partition_row_counts: Mapping[str, int],
    partition_label_counts: Mapping[str, Mapping[int, tuple[int, int]]],
    target_fractions: Mapping[str, float],
    protected_widths: tuple[int, ...],
    giant_component_gate: dict,
    minimum_count_report: dict,
    cross_partition_audit: dict,
    input_hashes: Mapping[str, str],
    config: Mapping[str, object],
    tool_provenance: list[dict] | None = None,
) -> dict:
    """Sanitized summary manifest: component sizes, partition/protein
    counts, gate results, tool provenance, and hashes only -- never a
    sequence or label value.
    """
    return {
        "schema_version": 1,
        "config": dict(config),
        "protected_widths": list(protected_widths),
        "notes": {
            "protected_widths_only": (
                "Only the planned 500/251/101-nt model input widths are "
                "explicitly protected by this grouping; an unplanned future "
                "width is not guaranteed leakage-free."
            ),
        },
        "input_hashes": dict(input_hashes),
        "total_rows": total_rows,
        "component_count": len(component_sizes),
        "component_sizes": dict(sorted(component_sizes.items())),
        "target_fractions": dict(target_fractions),
        "partition_row_counts": dict(partition_row_counts),
        "partition_label_counts": {
            partition: {str(pid): list(counts) for pid, counts in per_protein.items()}
            for partition, per_protein in partition_label_counts.items()
        },
        "giant_component_gate": giant_component_gate,
        "minimum_count_report": minimum_count_report,
        "cross_partition_audit": cross_partition_audit,
        "tool_provenance": tool_provenance or [],
    }


def write_manifest_json(manifest: dict, output_path: Path) -> None:
    def _write(tmp_path: Path) -> None:
        tmp_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    _atomic_write_bytes(Path(output_path), _write)


__all__ = [
    "MEMBERSHIP_HEADER",
    "write_deterministic_membership_gzip",
    "read_membership_gzip",
    "build_report",
    "write_manifest_json",
]
