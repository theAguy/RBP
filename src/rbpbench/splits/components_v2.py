"""Components v2: connected components over the DIRECT-search relation.

Unlike v1 (which unioned MMseqs2 cluster co-membership), v2 unions the
normalized direct edges at all three protected widths plus separately
supplied exact/reverse-complement edges, so every pair the cross-partition
audit would flag is joined by construction. Component IDs are hashes of
sorted member IDs (never tool serials).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from rbpbench.splits.commands import _WIDTH_COVERAGE
from rbpbench.splits.components import UnionFind, component_id, component_members, component_sizes
from rbpbench.splits.direct_edges import DirectEdgeError, DirectEdgeSet, edges_sha256, validate_universe, verify_edge_set

REQUIRED_WIDTHS: tuple[int, ...] = tuple(sorted(_WIDTH_COVERAGE))


@dataclass(frozen=True)
class ComponentsV2Result:
    membership: dict[str, str]  # sample_id -> component_id
    summary: dict
    metadata: dict  # artifact hashes, per-width counts, exact/RC contribution


def _normalize_exact_rc(edges: Iterable[tuple[str, str]], universe: frozenset[str]) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, tuple) or len(edge) != 2:
            raise DirectEdgeError(f"malformed exact/RC edge: {edge!r}")
        a, b = edge
        for endpoint in (a, b):
            if endpoint not in universe:
                raise DirectEdgeError(f"exact/RC endpoint {endpoint!r} is outside the canonical-ID universe")
        if a != b:
            pairs.add((a, b) if a < b else (b, a))
    return sorted(pairs)


def build_components_v2(
    universe: Iterable[str],
    direct_edges_by_width: Mapping[int, DirectEdgeSet],
    exact_rc_edges: Iterable[tuple[str, str]],
) -> ComponentsV2Result:
    """Deterministic transitive closure over all three widths' direct edges
    and the exact/RC edges. Fails closed if the universe is invalid, the
    width set is not exactly {500, 251, 101}, an edge set is keyed under the
    wrong width or fails its own consistency/hash check, or any endpoint is
    outside the universe. Singletons are kept as one-member components.
    """
    ids = validate_universe(universe)
    if set(direct_edges_by_width) != set(REQUIRED_WIDTHS):
        raise DirectEdgeError(
            f"direct edges must be supplied for exactly widths {list(REQUIRED_WIDTHS)}, got {sorted(direct_edges_by_width)}"
        )
    exact = _normalize_exact_rc(exact_rc_edges, ids)
    union_find = UnionFind(sorted(ids))
    for width in REQUIRED_WIDTHS:
        edge_set = direct_edges_by_width[width]
        if edge_set.width != width:
            raise DirectEdgeError(f"edge set for width {edge_set.width} supplied under width {width}")
        verify_edge_set(edge_set, ids)
        for a, b in edge_set.edges:
            union_find.union(a, b)
    for a, b in exact:
        union_find.union(a, b)

    membership: dict[str, str] = {}
    for members in union_find.groups().values():
        cid = component_id(members)
        for member in members:
            membership[member] = cid
    membership = dict(sorted(membership.items()))
    sizes = component_sizes(membership)
    summary = {
        "universe_size": len(ids),
        "component_count": len(sizes),
        "singleton_count": sum(1 for n in sizes.values() if n == 1),
        "largest_component_size": max(sizes.values()),
    }
    metadata = {
        "direct_edges_by_width": {str(w): direct_edges_by_width[w].metadata() for w in REQUIRED_WIDTHS},
        "exact_rc_edge_count": len(exact),
        "exact_rc_edges_sha256": edges_sha256(exact),
    }
    return ComponentsV2Result(membership=membership, summary=summary, metadata=metadata)


__all__ = ["REQUIRED_WIDTHS", "ComponentsV2Result", "build_components_v2", "component_members"]
