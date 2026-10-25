"""E4: components v2 with separately labelled protected relations.

Relations, applied in this canonical order for contribution accounting:

1. normalized direct-search edges at 500, 251 and 101 nt (E1–E3);
2. accepted exact/reverse-complement edges;
3. protected v1 co-membership (C3): every member of every accepted v1
   component is joined to that component's smallest member — recorded as
   ``v1_protected_joins``, never as direct alignment edges; and
4. (remediation cycle only) audit-discovered direct edges from the first
   complete 18-search audit.

The closure therefore may merge v1 components but can never split one; the
split count is still recomputed and must be zero.  Component IDs are
hashes of sorted member IDs.  :func:`bfs_partition` is a separate
breadth-first implementation used by final verification instead of the
production union-find.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from rbpbench.splits.audit import giant_component_gate
from rbpbench.splits.components import UnionFind, component_id
from rbpbench.splits.direct_edges import DirectEdgeSet, edges_sha256
from rbpbench.splits.r3r5.contract import Contract
from rbpbench.splits.r3r5.stops import IntegrityStop, ScientificStop


@dataclass(frozen=True)
class RelationInputs:
    universe: tuple[str, ...]
    direct: Mapping[int, DirectEdgeSet]
    exact_rc: Mapping[int, Sequence[tuple[str, str]]]
    v1_membership: Mapping[str, str]
    discovered: Sequence[tuple[str, str]] = ()


@dataclass(frozen=True)
class ComponentsResult:
    membership: dict[str, str]
    summary: dict
    metadata: dict


def normalize_pairs(pairs: Iterable[Sequence[str]], universe: frozenset[str], *, label: str) -> list[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for pair in pairs:
        if len(pair) != 2:
            raise IntegrityStop(f"{label}: malformed pair {pair!r}")
        a, b = str(pair[0]), str(pair[1])
        if a not in universe or b not in universe:
            raise IntegrityStop(f"{label}: endpoint outside the canonical universe in {pair!r}")
        if a != b:
            out.add((a, b) if a < b else (b, a))
    return sorted(out)


def _v1_groups(v1_membership: Mapping[str, str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for sample_id, cid in v1_membership.items():
        groups.setdefault(cid, []).append(sample_id)
    return sorted((sorted(members) for members in groups.values()), key=lambda m: m[0])


def _relations(inputs: RelationInputs, widths: Sequence[int]) -> list[tuple[str, list[tuple[str, str]]]]:
    universe = frozenset(inputs.universe)
    relations: list[tuple[str, list[tuple[str, str]]]] = []
    for width in widths:
        relations.append((f"direct_{width}", list(inputs.direct[width].edges)))
    for width in widths:
        relations.append((f"exact_rc_{width}", normalize_pairs(inputs.exact_rc[width], universe, label=f"exact/RC {width}")))
    v1_pairs: list[tuple[str, str]] = []
    for members in _v1_groups(inputs.v1_membership):
        representative = members[0]
        v1_pairs.extend((representative, member) for member in members[1:])
    relations.append(("v1_protected_co_membership", v1_pairs))
    relations.append(("audit_discovered_direct", normalize_pairs(inputs.discovered, universe, label="audit-discovered")))
    return relations


def build_components(inputs: RelationInputs, contract: Contract, *, reverse_order: bool = False) -> ComponentsResult:
    universe = list(inputs.universe)
    universe_set = frozenset(universe)
    if len(universe_set) != len(universe) or len(universe) != contract.row_count:
        raise IntegrityStop("component universe must be the complete canonical universe exactly once")
    if set(inputs.v1_membership) != universe_set:
        raise IntegrityStop("v1 component membership does not cover exactly the canonical universe")
    for width in contract.widths:
        edge_set = inputs.direct[width]
        if edge_set.width != width or edges_sha256(edge_set.edges) != edge_set.sha256:
            raise IntegrityStop(f"direct edge set for width {width} is inconsistent")
    relations = _relations(inputs, contract.widths)
    union_find = UnionFind(reversed(universe) if reverse_order else universe)
    contribution: dict[str, dict] = {}
    ordered = list(reversed(relations)) if reverse_order else relations
    for name, pairs in ordered:
        merges = 0
        for a, b in (reversed(pairs) if reverse_order else pairs):
            if union_find.find(a) != union_find.find(b):
                merges += 1
            union_find.union(a, b)
        contribution[name] = {"pair_count": len(pairs), "merging_unions_in_application_order": merges,
                              "sha256": edges_sha256(sorted(pairs))}
    membership: dict[str, str] = {}
    for members in union_find.groups().values():
        cid = component_id(members)
        for member in members:
            membership[member] = cid
    membership = dict(sorted(membership.items()))
    sizes: dict[str, int] = {}
    for cid in membership.values():
        sizes[cid] = sizes.get(cid, 0) + 1
    distribution: dict[int, int] = {}
    for size in sizes.values():
        distribution[size] = distribution.get(size, 0) + 1
    gate = giant_component_gate(sizes, len(universe))
    gate["single_component_threshold"] = contract.giant_single_fraction
    gate["top20_threshold"] = contract.giant_top20_fraction
    gate["single_component_gate_tripped"] = gate["largest_component_fraction"] > contract.giant_single_fraction
    gate["top20_gate_tripped"] = gate["top20_component_fraction"] > contract.giant_top20_fraction
    v1 = compare_with_v1(membership, inputs.v1_membership)
    summary = {
        "universe_size": len(universe),
        "component_count": len(sizes),
        "singleton_count": distribution.get(1, 0),
        "largest_component_size": max(sizes.values()),
        "size_distribution": {str(k): distribution[k] for k in sorted(distribution)},
        "giant_component_gate": gate,
        "v1_comparison": v1,
    }
    metadata = {
        "relations": {name: contribution[name] for name, _ in relations},
        "direct_edges_by_width": {str(w): inputs.direct[w].metadata() for w in contract.widths},
        "relation_application_order": [name for name, _ in ordered],
        "v1_relation_kind": "protected co-membership (never a direct alignment edge)",
    }
    return ComponentsResult(membership=membership, summary=summary, metadata=metadata)


def compare_with_v1(membership: Mapping[str, str], v1_membership: Mapping[str, str]) -> dict:
    v1_to_v2: dict[str, set[str]] = {}
    v2_to_v1: dict[str, set[str]] = {}
    v1_sizes: dict[str, int] = {}
    for sample_id, v1_cid in v1_membership.items():
        v2_cid = membership[sample_id]
        v1_to_v2.setdefault(v1_cid, set()).add(v2_cid)
        v2_to_v1.setdefault(v2_cid, set()).add(v1_cid)
        v1_sizes[v1_cid] = v1_sizes.get(v1_cid, 0) + 1
    split = sorted(cid for cid, targets in v1_to_v2.items() if len(targets) > 1)
    merged_v2 = [v2 for v2, sources in v2_to_v1.items() if len(sources) > 1]
    merged_v1 = sum(len(v2_to_v1[v2]) for v2 in merged_v2)
    rows_in_merges = sum(v1_sizes[v1] for v2 in merged_v2 for v1 in v2_to_v1[v2])
    return {
        "v1_component_count": len(v1_sizes),
        "v1_components_split_by_v2": len(split),
        "v1_split_component_ids": split[:50],
        "v1_components_merged_by_v2": merged_v1,
        "v2_components_formed_by_merging_v1": len(merged_v2),
        "rows_in_merged_v1_components": rows_in_merges,
    }


def enforce_gates(result: ComponentsResult) -> None:
    v1 = result.summary["v1_comparison"]
    if v1["v1_components_split_by_v2"] != 0:
        raise IntegrityStop(f"components v2 split {v1['v1_components_split_by_v2']} protected v1 component(s)")
    gate = result.summary["giant_component_gate"]
    if gate["single_component_gate_tripped"] or gate["top20_gate_tripped"]:
        raise ScientificStop(
            "giant-component gate tripped: largest component "
            f"{gate['largest_component_fraction']:.4%} (limit {gate['single_component_threshold']:.0%}), top 20 "
            f"{gate['top20_component_fraction']:.4%} (limit {gate['top20_threshold']:.0%})",
            details={"giant_component_gate": gate},
        )


def same_result(a: ComponentsResult, b: ComponentsResult) -> bool:
    return a.membership == b.membership and a.summary == b.summary


def bfs_partition(universe: Iterable[str], relations: Iterable[Iterable[tuple[str, str]]]) -> set[frozenset[str]]:
    """Independent breadth-first closure (no union-find)."""
    adjacency: dict[str, list[str]] = {sample_id: [] for sample_id in universe}
    for pairs in relations:
        for a, b in pairs:
            if a not in adjacency or b not in adjacency:
                raise IntegrityStop(f"BFS verifier: endpoint outside the universe in ({a!r}, {b!r})")
            adjacency[a].append(b)
            adjacency[b].append(a)
    seen: set[str] = set()
    groups: set[frozenset[str]] = set()
    for start in adjacency:
        if start in seen:
            continue
        seen.add(start)
        queue, members = deque([start]), [start]
        while queue:
            node = queue.popleft()
            for neighbour in adjacency[node]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    members.append(neighbour)
                    queue.append(neighbour)
        groups.add(frozenset(members))
    return groups


def verify_membership_by_bfs(membership: Mapping[str, str], universe: Sequence[str], relations) -> dict:
    expected = bfs_partition(universe, relations)
    production: dict[str, set[str]] = {}
    for sample_id, cid in membership.items():
        production.setdefault(cid, set()).add(sample_id)
    observed = {frozenset(members) for members in production.values()}
    if observed != expected:
        raise IntegrityStop("breadth-first verification disagrees with the production component membership")
    for cid, members in production.items():
        if component_id(members) != cid:
            raise IntegrityStop(f"component id {cid} is not the hash of its sorted members")
    return {"bfs_component_count": len(expected), "matches_production": True}


__all__ = [
    "RelationInputs", "ComponentsResult", "normalize_pairs", "build_components", "compare_with_v1",
    "enforce_gates", "same_result", "bfs_partition", "verify_membership_by_bfs",
]
