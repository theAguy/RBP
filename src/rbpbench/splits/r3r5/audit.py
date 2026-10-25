"""E7: fresh near-similarity audit evidence (C2) and violation handling.

Before any directed search, each partition's fresh FASTA and fresh type-2
database must be proven to contain exactly that partition:

1. strict FASTA parse — record count and exact ID set equal the accepted
   membership partition;
2. a streaming ``(ID, sequence SHA-256)`` inventory equal to the matching
   records of the accepted full-width FASTA;
3. the MMseqs2 ``.lookup`` ID list and count; and
4. a ``convert2fasta`` round trip that reproduces the same inventory.

A deterministic positive control (self-hits plus same-partition
construction edges) must be fully recovered under the frozen command, so an
empty, wrong, or insensitive audit cannot pass by returning zero hits.

Directed hits are reconciled with the accepted closed-universe logic in
:mod:`rbpbench.splits.mmseqs_audit` and normalized to ID pairs labelled
with width and direction.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from rbpbench.coordinates.commands import ToolCommand
from rbpbench.coordinates.hashing import stable_hash_rank
from rbpbench.splits import mmseqs_audit
from rbpbench.splits.commands import PINNED_VERSION
from rbpbench.splits.r3r5.stops import IntegrityStop

_ACGT = frozenset("ACGT")


def convert2fasta_command(db: Path, output_fasta: Path, *, mmseqs_bin: str) -> ToolCommand:
    """``mmseqs convert2fasta DB OUT`` — a format conversion, not a scientific flag."""
    return ToolCommand(tool="mmseqs_convert2fasta", argv=(mmseqs_bin, "convert2fasta", str(db), str(output_fasta)),
                       pinned_version=PINNED_VERSION)


def sequence_digest(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def fasta_inventory(path: Path, *, width: int, expected_ids: frozenset[str], label: str) -> dict[str, str]:
    """Strict streaming parse returning ``{id: sha256(sequence)}``."""
    inventory: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []

    def close() -> None:
        if current is None:
            return
        sequence = "".join(chunks)
        if not current or any(c in current for c in "\t\r "):
            raise IntegrityStop(f"{label}: invalid FASTA header {current!r}")
        if current in inventory:
            raise IntegrityStop(f"{label}: duplicate FASTA record {current!r}")
        if len(sequence) != width or set(sequence) - _ACGT:
            raise IntegrityStop(f"{label}: record {current!r} is not a {width}-nt ACGT sequence")
        inventory[current] = sequence_digest(sequence)

    with Path(path).open() as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith(">"):
                close()
                current, chunks = line[1:].strip(), []
            elif current is None:
                if line:
                    raise IntegrityStop(f"{label}: sequence text before the first header")
            else:
                chunks.append(line)
        close()
    if len(inventory) != len(expected_ids) or set(inventory) != expected_ids:
        missing = sorted(expected_ids - set(inventory))[:5]
        foreign = sorted(set(inventory) - expected_ids)[:5]
        raise IntegrityStop(
            f"{label}: {len(inventory)} records do not equal the {len(expected_ids)} expected IDs "
            f"(missing e.g. {missing}, foreign e.g. {foreign})"
        )
    return inventory


def write_partition_fasta(full_records: Mapping[str, str], partition_ids: frozenset[str], path: Path) -> int:
    count = 0
    with Path(path).open("w") as handle:
        for sample_id, sequence in full_records.items():
            if sample_id in partition_ids:
                handle.write(f">{sample_id}\n{sequence}\n")
                count += 1
    return count


def read_lookup_ids(db_prefix: Path, *, label: str) -> list[str]:
    lookup = Path(str(db_prefix) + ".lookup")
    if not lookup.is_file():
        raise IntegrityStop(f"{label}: MMseqs2 database has no .lookup file")
    ids: list[str] = []
    with lookup.open() as handle:
        for expected_index, raw in enumerate(handle):
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 2 or parts[0] != str(expected_index) or not parts[1]:
                raise IntegrityStop(f"{label}: malformed .lookup row {expected_index}: {raw[:80]!r}")
            ids.append(parts[1])
    return ids


def reconcile_partition_database(
    *, fasta_path: Path, db_prefix: Path, roundtrip_fasta: Path, partition_ids: frozenset[str],
    reference_inventory: Mapping[str, str], width: int, label: str,
) -> dict:
    """Checks 1–4 above; ``reference_inventory`` comes from the accepted full FASTA."""
    inventory = fasta_inventory(fasta_path, width=width, expected_ids=partition_ids, label=f"{label} FASTA")
    mismatched = [sid for sid, digest in inventory.items() if reference_inventory.get(sid) != digest]
    if mismatched:
        raise IntegrityStop(f"{label}: {len(mismatched)} partition records differ from the accepted full FASTA (e.g. {mismatched[:5]})")
    lookup_ids = read_lookup_ids(db_prefix, label=label)
    if len(lookup_ids) != len(partition_ids) or set(lookup_ids) != partition_ids or len(set(lookup_ids)) != len(lookup_ids):
        raise IntegrityStop(
            f"{label}: database .lookup lists {len(lookup_ids)} IDs; expected exactly the {len(partition_ids)} partition IDs"
        )
    roundtrip = fasta_inventory(roundtrip_fasta, width=width, expected_ids=partition_ids, label=f"{label} convert2fasta")
    if roundtrip != inventory:
        raise IntegrityStop(f"{label}: convert2fasta round trip does not reproduce the partition sequences")
    digest = hashlib.sha256("".join(f"{sid}\t{inventory[sid]}\n" for sid in sorted(inventory)).encode()).hexdigest()
    return {"records": len(inventory), "lookup_records": len(lookup_ids), "inventory_sha256": digest, "roundtrip_matches": True}


def select_positive_control(
    *, seed: int, width: int, cycle: int, partition_of: Mapping[str, str], construction_edges: Sequence[tuple[str, str]],
    self_hits: int, max_edges: int,
) -> dict:
    ids = sorted(partition_of)
    ranked_ids = sorted(ids, key=lambda s: (stable_hash_rank(seed, "r3r5_positive_control_self", width, cycle, s), s))
    selected_self = sorted(ranked_ids[: min(self_hits, len(ids))])
    same_partition = [(a, b) for a, b in construction_edges if partition_of[a] == partition_of[b]]
    if len(same_partition) != len(construction_edges):
        raise IntegrityStop(f"width {width}: a construction edge spans partitions before the audit")
    ranked_edges = sorted(
        same_partition, key=lambda e: (stable_hash_rank(seed, "r3r5_positive_control_edge", width, cycle, e[0], e[1]), e)
    )
    selected_edges = sorted(ranked_edges[: min(max_edges, len(ranked_edges))])
    members = sorted(set(selected_self) | {x for edge in selected_edges for x in edge})
    return {"self_ids": selected_self, "edges": [list(e) for e in selected_edges], "members": members}


def check_positive_control(hit_lines: Iterable[str], selection: Mapping, *, width: int) -> dict:
    members = set(selection["members"])
    found: set[tuple[str, str]] = set()
    rows = 0
    for lineno, raw in enumerate(hit_lines, start=1):
        parts = raw.rstrip("\n").split("\t")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise IntegrityStop(f"width {width}: malformed positive-control row {lineno}")
        if parts[0] not in members or parts[1] not in members:
            raise IntegrityStop(f"width {width}: positive-control row {lineno} names a foreign ID")
        found.add((parts[0], parts[1]))
        rows += 1
    missing_self = [s for s in selection["self_ids"] if (s, s) not in found]
    missing_edges = [e for e in selection["edges"] if (e[0], e[1]) not in found and (e[1], e[0]) not in found]
    if missing_self or missing_edges:
        raise IntegrityStop(
            f"width {width}: positive control failed — {len(missing_self)} self-hit(s) and {len(missing_edges)} "
            f"construction edge(s) were not recovered (e.g. {missing_self[:3]}, {missing_edges[:3]})",
            details={"missing_self": missing_self, "missing_edges": missing_edges},
        )
    return {"rows": rows, "self_hits_expected": len(selection["self_ids"]), "edges_expected": len(selection["edges"]),
            "all_recovered": True}


def directed_violations(
    tsv_path: Path, *, width: int, query_partition: str, target_partition: str,
    query_ids: frozenset[str], target_ids: frozenset[str],
) -> list[tuple[str, str]]:
    try:
        hits = mmseqs_audit.parse_search_hits(tsv_path)
        result = mmseqs_audit.reconcile_directed_hits(
            hits, width=width, query_partition=query_partition, target_partition=target_partition,
            query_universe=sorted(query_ids), target_universe=sorted(target_ids),
        )
    except ValueError as exc:  # malformed rows, foreign endpoints, self-hit corruption
        raise IntegrityStop(f"width {width} {query_partition}->{target_partition}: {exc}") from exc
    pairs = {(v["query_id"], v["target_id"]) for v in result.violations}
    return sorted({(a, b) if a < b else (b, a) for a, b in pairs})


def classify_cycle_violations(
    violations: Iterable[tuple[str, str]], *, protected_pairs: set[tuple[str, str]], v1_membership: Mapping[str, str],
) -> dict:
    """Splits violations into already-protected pairs (integrity failure) and
    audit-discovered direct edges (one remediation cycle)."""
    protected, discovered = [], []
    for a, b in sorted(set(violations)):
        if (a, b) in protected_pairs or v1_membership.get(a) == v1_membership.get(b):
            protected.append((a, b))
        else:
            discovered.append((a, b))
    return {"protected_but_split": protected, "audit_discovered": discovered}


__all__ = [
    "convert2fasta_command", "sequence_digest", "fasta_inventory", "write_partition_fasta", "read_lookup_ids",
    "reconcile_partition_database", "select_positive_control", "check_positive_control", "directed_violations",
    "classify_cycle_violations",
]
