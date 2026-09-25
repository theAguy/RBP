"""Exact and reverse-complement canonical sequence hashing at each protected
width.

Independent of the MMseqs2 clustering workflow: exact duplicates and
reverse-complement duplicates at each of the 500/251/101-nt representations
must always land in the same component even if the external tool omits an
edge (``docs/tasks/002_sequence_clustered_partitions.md``). This module is
pure Python and never shells out, so it can supply edges the external tool
is not trusted to guarantee, and can independently audit that tool's output
after the fact.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from rbpbench.coordinates.decode import reverse_complement
from rbpbench.coordinates.hashing import content_fingerprint


def canonical_orientation(sequence: str) -> str:
    """The lexicographically smaller of ``sequence`` and its reverse
    complement.

    Hashing THIS (rather than ``sequence`` itself) is what makes an exact
    duplicate and a reverse-complement duplicate collide to the identical
    hash: whichever orientation either copy was stored in, both resolve to
    the same canonical string.
    """
    rc = reverse_complement(sequence)
    return sequence if sequence <= rc else rc


def canonical_sequence_hash(sequence: str) -> str:
    """SHA-256 content fingerprint of ``sequence``'s canonical orientation."""
    return content_fingerprint("canonical_sequence", canonical_orientation(sequence))


def group_by_canonical_hash(sequences_by_id: Mapping[str, str]) -> dict[str, list[str]]:
    """Groups sample IDs whose sequence is an exact or reverse-complement
    duplicate of another's, keyed by canonical hash. Each group's ID list is
    sorted, so the grouping never depends on ``sequences_by_id``'s iteration
    order.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for sample_id, sequence in sequences_by_id.items():
        groups[canonical_sequence_hash(sequence)].append(sample_id)
    return {digest: sorted(ids) for digest, ids in groups.items()}


def duplicate_edges(sequences_by_id: Mapping[str, str]) -> list[tuple[str, str]]:
    """Pairwise edges connecting every exact/reverse-complement duplicate
    group, ready to feed straight into a union-find.

    Consecutive pairs within each (sorted) group are enough to connect the
    whole group transitively -- no need for the O(n^2) all-pairs edge set a
    naive implementation might reach for.
    """
    edges: list[tuple[str, str]] = []
    for ids in group_by_canonical_hash(sequences_by_id).values():
        for a, b in zip(ids, ids[1:]):
            edges.append((a, b))
    return edges
