"""E1–E3: strict reconciliation of a full same-database direct search.

The raw ``mmseqs createtsv`` output of ``search DB DB`` is streamed once.
Columns 1–2 are the query/target endpoints; trailing MMseqs2 fields are
opaque evidence whose column-count histogram is recorded.  The stream must
be grouped by query; every one of the complete canonical universe must
appear as a query exactly in one group and must recover its own self-hit;
no query may reach the frozen ``--max-seqs`` result cap; every endpoint
must be a canonical ID; a target may appear only once per query.

Self-pairs are removed, the rest canonicalized to ``(min_id, max_id)`` and
collapsed, producing the accepted :class:`DirectEdgeSet` (R1 schema).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from rbpbench.splits.commands import FROZEN_MAX_SEQS
from rbpbench.splits.direct_edges import DirectEdgeSet, _serialize, edges_sha256, read_normalized_edges
from rbpbench.splits.r3r5.stops import IntegrityStop

RESULT_CAP = int(FROZEN_MAX_SEQS)


def _quantile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    index = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[index]


def reconcile_full_search(lines: Iterable[str], *, width: int, universe: frozenset[str]) -> tuple[DirectEdgeSet, dict]:
    counts: dict[str, int] = {}
    finished: set[str] = set()
    current: str | None = None
    group_targets: set[str] = set()
    self_hit: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    raw_rows = self_rows = raw_bytes = 0
    column_counts: dict[int, int] = {}
    distinct_targets: set[str] = set()
    for lineno, raw in enumerate(lines, start=1):
        raw_bytes += len(raw.encode("utf-8"))
        line = raw[:-1] if raw.endswith("\n") else raw
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise IntegrityStop(f"width {width}: malformed full-search row {lineno}: {line[:120]!r}")
        query, target = parts[0], parts[1]
        column_counts[len(parts)] = column_counts.get(len(parts), 0) + 1
        if query not in universe or target not in universe:
            raise IntegrityStop(f"width {width}: row {lineno} has a foreign endpoint ({query!r}, {target!r})")
        if query != current:
            if query in finished or query in counts:
                raise IntegrityStop(f"width {width}: query {query!r} reappears at row {lineno}; output is not grouped")
            if current is not None:
                finished.add(current)
            current, group_targets = query, set()
            counts[query] = 0
        if target in group_targets:
            raise IntegrityStop(f"width {width}: duplicate ({query}, {target}) row at {lineno}")
        group_targets.add(target)
        distinct_targets.add(target)
        counts[query] += 1
        raw_rows += 1
        if counts[query] >= RESULT_CAP:
            raise IntegrityStop(f"width {width}: query {query!r} reached the frozen {RESULT_CAP} result cap")
        if query == target:
            self_rows += 1
            self_hit.add(query)
            continue
        pairs.add((query, target) if query < target else (target, query))
    missing_queries = universe - set(counts)
    if missing_queries:
        raise IntegrityStop(
            f"width {width}: {len(missing_queries)} universe IDs never appear as a query (e.g. {sorted(missing_queries)[:5]})"
        )
    missing_self = universe - self_hit
    if missing_self:
        raise IntegrityStop(
            f"width {width}: {len(missing_self)} queries lost their self-hit (e.g. {sorted(missing_self)[:5]}); "
            "self-hit recovery must be 100%",
            details={"missing_self_hit_ids": sorted(missing_self)},
        )
    edges = tuple(sorted(pairs))
    edge_set = DirectEdgeSet(
        width=width,
        edges=edges,
        raw_rows=raw_rows,
        self_pairs_discarded=self_rows,
        duplicates_collapsed=raw_rows - self_rows - len(edges),
        sha256=edges_sha256(edges),
        raw_column_count_histogram=tuple(sorted(column_counts.items())),
    )
    ordered = sorted(counts.values())
    metrics = {
        "width": width,
        "raw_rows": raw_rows,
        "raw_bytes": raw_bytes,
        "distinct_queries": len(counts),
        "distinct_targets": len(distinct_targets),
        "self_hit_rate": len(self_hit) / len(universe),
        "self_rows": self_rows,
        "normalized_edge_count": len(edges),
        "duplicates_collapsed": edge_set.duplicates_collapsed,
        "per_query_rows": {
            "min": ordered[0], "median": _quantile(ordered, 0.5), "p95": _quantile(ordered, 0.95),
            "p99": _quantile(ordered, 0.99), "max": ordered[-1],
        },
        "result_cap": RESULT_CAP,
        "result_cap_reached": False,
        "column_count_histogram": {str(k): v for k, v in sorted(column_counts.items())},
        "endpoint_columns": [1, 2],
        "trailing_columns": "opaque raw MMseqs2 createtsv evidence",
    }
    return edge_set, metrics


def reconcile_full_search_file(path: Path, *, width: int, universe: frozenset[str]) -> tuple[DirectEdgeSet, dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return reconcile_full_search(handle, width=width, universe=universe)


def write_and_reread_normalized(edge_set: DirectEdgeSet, path: Path, *, universe: frozenset[str]) -> dict:
    """Writes the strict two-column artifact and independently rereads it."""
    data = _serialize(edge_set.edges)
    Path(path).write_bytes(data)
    reread = read_normalized_edges(path, width=edge_set.width, universe=universe)
    if reread.sha256 != edge_set.sha256 or len(reread.edges) != len(edge_set.edges):
        raise IntegrityStop(f"width {edge_set.width}: normalized edge reread does not reproduce count/hash")
    return {"path": Path(path).name, "edge_count": len(reread.edges), "sha256": reread.sha256, "byte_size": len(data)}


__all__ = ["RESULT_CAP", "reconcile_full_search", "reconcile_full_search_file", "write_and_reread_normalized"]
