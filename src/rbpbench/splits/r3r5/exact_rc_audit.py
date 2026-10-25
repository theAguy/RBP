"""E6: independent exact/reverse-complement audit.

Deliberately self-contained: it imports neither the construction
canonicalization helper (``rbpbench.splits.hashing``) nor the decoder's
reverse-complement function, and it never reads the construction edge
files to decide groups.  It rereads each accepted FASTA, groups identical
canonical orientations by its own SHA-256 key, requires zero groups that
span partitions, and separately checks that its grouping reproduces the
connectivity of the accepted exact/RC construction evidence.
"""

from __future__ import annotations

import hashlib
from collections import deque
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from rbpbench.splits.r3r5.stops import IntegrityStop

_PAIRING = {"A": "T", "C": "G", "G": "C", "T": "A"}


def reverse_complement(sequence: str) -> str:
    try:
        return "".join(_PAIRING[base] for base in reversed(sequence))
    except KeyError as exc:
        raise IntegrityStop(f"non-ACGT base {exc.args[0]!r} in exact/RC audit input") from None


def orientation_key(sequence: str) -> str:
    other = reverse_complement(sequence)
    chosen = sequence if sequence <= other else other
    return hashlib.sha256(chosen.encode("ascii")).hexdigest()


def read_fasta_records(path: Path, *, width: int, expected_ids: frozenset[str]) -> dict[str, str]:
    records: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []

    def close() -> None:
        if current is None:
            return
        sequence = "".join(chunks)
        if current in records:
            raise IntegrityStop(f"{Path(path).name}: duplicate header {current!r}")
        if len(sequence) != width or set(sequence) - set(_PAIRING):
            raise IntegrityStop(f"{Path(path).name}: record {current!r} is not a {width}-nt ACGT sequence")
        records[current] = sequence

    with Path(path).open() as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith(">"):
                close()
                current, chunks = line[1:].strip(), []
            elif current is None:
                raise IntegrityStop(f"{Path(path).name}: sequence text before the first header")
            else:
                chunks.append(line)
        close()
    if set(records) != expected_ids:
        raise IntegrityStop(f"{Path(path).name}: exact/RC audit universe does not equal the frozen membership")
    return records


def duplicate_groups(records: Mapping[str, str]) -> list[tuple[str, ...]]:
    buckets: dict[str, list[str]] = {}
    for sample_id, sequence in records.items():
        buckets.setdefault(orientation_key(sequence), []).append(sample_id)
    return sorted(tuple(sorted(ids)) for ids in buckets.values() if len(ids) > 1)


def _groups_from_edges(edges: Iterable[Sequence[str]]) -> set[frozenset[str]]:
    adjacency: dict[str, set[str]] = {}
    for a, b in edges:
        if a == b:
            continue
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    seen: set[str] = set()
    groups: set[frozenset[str]] = set()
    for start in sorted(adjacency):
        if start in seen:
            continue
        queue, members = deque([start]), {start}
        seen.add(start)
        while queue:
            for neighbour in adjacency[queue.popleft()]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    members.add(neighbour)
                    queue.append(neighbour)
        groups.add(frozenset(members))
    return groups


def audit_width(
    records: Mapping[str, str], sample_to_partition: Mapping[str, str], accepted_edges: Iterable[Sequence[str]], *, width: int
) -> dict:
    groups = duplicate_groups(records)
    violations = []
    for group in groups:
        partitions = sorted({sample_to_partition[sample_id] for sample_id in group})
        if len(partitions) > 1:
            violations.append({"width": width, "members": list(group), "partitions": partitions})
    independent = {frozenset(group) for group in groups}
    accepted = _groups_from_edges(accepted_edges)
    return {
        "width": width,
        "duplicate_group_count": len(groups),
        "max_duplicate_group_size": max((len(g) for g in groups), default=0),
        "cross_partition_group_count": len(violations),
        "violations": violations,
        "matches_accepted_construction_evidence": independent == accepted,
        "accepted_evidence_group_count": len(accepted),
        "passed": not violations and independent == accepted,
    }


__all__ = ["reverse_complement", "orientation_key", "read_fasta_records", "duplicate_groups", "audit_width"]
