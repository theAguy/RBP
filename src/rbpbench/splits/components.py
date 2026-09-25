"""Deterministic union-find across window-size representations plus
exact/reverse-complement duplicate edges.

Component IDs are deterministic hashes of the sorted member sample IDs
(``docs/tasks/002_sequence_clustered_partitions.md``: "Component IDs are
deterministic hashes of the sorted canonical row IDs, not tool-generated
serial numbers"), so identical membership always yields the identical ID
regardless of union-find call order, edge-source order, or input row order.
"""

from __future__ import annotations

from typing import Iterable

from rbpbench.coordinates.hashing import content_fingerprint


class UnionFind:
    """Disjoint-set over a fixed universe of string IDs with deterministic
    tie-breaking (lexicographically smaller root always wins), so the final
    partition into sets never depends on the order ``union`` was called.
    """

    def __init__(self, ids: Iterable[str]):
        self._parent: dict[str, str] = {i: i for i in ids}

    def find(self, x: str) -> str:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return
        if root_b < root_a:
            root_a, root_b = root_b, root_a
        self._parent[root_b] = root_a

    def groups(self) -> dict[str, list[str]]:
        buckets: dict[str, list[str]] = {}
        for member in self._parent:
            root = self.find(member)
            buckets.setdefault(root, []).append(member)
        return {root: sorted(members) for root, members in buckets.items()}


def component_id(member_ids: Iterable[str]) -> str:
    """Deterministic hash of the sorted member IDs."""
    return content_fingerprint("sequence_partition_component", *sorted(member_ids))


def build_components(
    sample_ids: Iterable[str], edge_groups: Iterable[Iterable[tuple[str, str]]]
) -> dict[str, str]:
    """Unions ``sample_ids`` across every edge list in ``edge_groups`` (one
    per window-size clustering, plus one for canonical-hash exact/reverse-
    complement duplicates at each width) and returns
    ``{sample_id: component_id}``.

    Input order -- of ``sample_ids`` itself, of edges within one group, and
    of the groups relative to each other -- never affects the result: a
    singleton sample ID with no edges becomes its own one-member component.
    """
    ids = list(sample_ids)
    union_find = UnionFind(ids)
    for edges in edge_groups:
        for a, b in edges:
            union_find.union(a, b)
    groups = union_find.groups()
    assignment: dict[str, str] = {}
    for members in groups.values():
        cid = component_id(members)
        for member in members:
            assignment[member] = cid
    return assignment


def component_sizes(sample_to_component: dict[str, str]) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for cid in sample_to_component.values():
        sizes[cid] = sizes.get(cid, 0) + 1
    return sizes


def component_members(sample_to_component: dict[str, str]) -> dict[str, list[str]]:
    members: dict[str, list[str]] = {}
    for sample_id, cid in sample_to_component.items():
        members.setdefault(cid, []).append(sample_id)
    return {cid: sorted(ids) for cid, ids in members.items()}


__all__ = [
    "UnionFind",
    "component_id",
    "build_components",
    "component_sizes",
    "component_members",
]
