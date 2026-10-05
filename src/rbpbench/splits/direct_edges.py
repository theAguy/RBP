"""Strict parsing/normalization of components-v2 DIRECT-search edges.

Input is a two-column ``mmseqs createtsv`` rendering of an all-vs-all
direct search result (``query<TAB>target``). This is NOT the v1 cluster
membership TSV (``representative<TAB>member``; see
:mod:`rbpbench.splits.membership`): cluster co-membership may omit a
qualifying direct pair, so nothing here is shared with, or accepts, that
parser's output implicitly.

Normalized edge artifact: one ``min_id<TAB>max_id`` line per distinct
pair, sorted, ``\\n``-terminated, no header, no sequences or labels. Its
content SHA-256 is the artifact identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rbpbench.splits.commands import UnknownWidthError, _WIDTH_COVERAGE


class DirectEdgeError(ValueError):
    """Malformed, foreign, or inconsistent direct-edge evidence."""


def validate_universe(ids: Iterable[str]) -> frozenset[str]:
    """Canonical-ID universe: every ID non-empty, tab/newline-free, and
    present exactly once."""
    seen: set[str] = set()
    for sample_id in ids:
        if not isinstance(sample_id, str) or not sample_id or any(c in sample_id for c in "\t\r\n"):
            raise DirectEdgeError(f"invalid canonical ID in universe: {sample_id!r}")
        if sample_id in seen:
            raise DirectEdgeError(f"duplicate canonical ID in universe: {sample_id!r}")
        seen.add(sample_id)
    if not seen:
        raise DirectEdgeError("canonical-ID universe is empty")
    return frozenset(seen)


def _check_width(width: int) -> None:
    if width not in _WIDTH_COVERAGE:
        raise UnknownWidthError(f"width {width!r} is not one of the frozen protected widths {sorted(_WIDTH_COVERAGE)}")


def edges_sha256(edges: Iterable[tuple[str, str]]) -> str:
    """SHA-256 of the sorted two-column serialization of already-normalized edges."""
    return hashlib.sha256(_serialize(edges)).hexdigest()


def _serialize(edges: Iterable[tuple[str, str]]) -> bytes:
    return "".join(f"{a}\t{b}\n" for a, b in edges).encode("utf-8")


@dataclass(frozen=True)
class DirectEdgeSet:
    """Normalized direct edges for one width. ``edges`` is sorted, unique,
    and every pair satisfies ``a < b``."""

    width: int
    edges: tuple[tuple[str, str], ...]
    raw_rows: int
    self_pairs_discarded: int
    duplicates_collapsed: int
    sha256: str

    def metadata(self) -> dict:
        return {
            "width": self.width,
            "normalized_edge_count": len(self.edges),
            "raw_rows": self.raw_rows,
            "self_pairs_discarded": self.self_pairs_discarded,
            "duplicates_collapsed": self.duplicates_collapsed,
            "sha256": self.sha256,
        }


def parse_direct_edge_lines(lines: Iterable[str], *, width: int, universe: Iterable[str]) -> DirectEdgeSet:
    """Streams ``query<TAB>target`` lines into a :class:`DirectEdgeSet`.

    Every row must be exactly two non-empty tab-separated IDs, both in
    ``universe``; blank lines are malformed (not skipped). Self-pairs are
    discarded; remaining pairs are canonicalized to ``(min, max)`` and
    duplicate/reversed pairs collapsed.
    """
    _check_width(width)
    ids = validate_universe(universe)
    pairs: set[tuple[str, str]] = set()
    raw = selfs = 0
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line[:-1] if raw_line.endswith("\n") else raw_line
        parts = line.split("\t")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise DirectEdgeError(f"malformed direct-edge row {lineno} (expected 2 non-empty columns): {line!r}")
        a, b = parts
        for endpoint in (a, b):
            if endpoint not in ids:
                raise DirectEdgeError(f"row {lineno}: endpoint {endpoint!r} is outside the canonical-ID universe")
        raw += 1
        if a == b:
            selfs += 1
            continue
        pairs.add((a, b) if a < b else (b, a))
    edges = tuple(sorted(pairs))
    return DirectEdgeSet(
        width=width,
        edges=edges,
        raw_rows=raw,
        self_pairs_discarded=selfs,
        duplicates_collapsed=raw - selfs - len(edges),
        sha256=hashlib.sha256(_serialize(edges)).hexdigest(),
    )


def parse_direct_edge_tsv(path: Path, *, width: int, universe: Iterable[str]) -> DirectEdgeSet:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return parse_direct_edge_lines(handle, width=width, universe=universe)


def write_normalized_edges(edge_set: DirectEdgeSet, path: Path) -> str:
    """Writes the deterministic normalized artifact; returns its SHA-256."""
    Path(path).write_bytes(_serialize(edge_set.edges))
    return edge_set.sha256


def read_normalized_edges(path: Path, *, width: int, universe: Iterable[str]) -> DirectEdgeSet:
    """Strictly reads a normalized artifact: rows must already be
    ``a < b``, sorted, and unique, so any hand-edited or non-normalized
    file fails closed instead of being silently repaired."""
    _check_width(width)
    ids = validate_universe(universe)
    data = Path(path).read_bytes()
    text = data.decode("utf-8")
    if text and not text.endswith("\n"):
        raise DirectEdgeError("normalized edge artifact lacks a trailing newline")
    parsed = parse_direct_edge_lines(text.splitlines(), width=width, universe=ids)
    if parsed.self_pairs_discarded or parsed.duplicates_collapsed:
        raise DirectEdgeError("normalized edge artifact contains self-pairs or duplicates")
    if _serialize(parsed.edges) != data:
        raise DirectEdgeError("normalized edge artifact is not canonical (unsorted or reversed pair)")
    return parsed


def verify_edge_set(edge_set: DirectEdgeSet, universe: frozenset[str]) -> None:
    """Re-checks an in-memory edge set's internal consistency."""
    _check_width(edge_set.width)
    previous = None
    for edge in edge_set.edges:
        if len(edge) != 2 or not edge[0] < edge[1] or edge[0] not in universe or edge[1] not in universe:
            raise DirectEdgeError(f"width {edge_set.width}: invalid normalized edge {edge!r}")
        if previous is not None and not previous < edge:
            raise DirectEdgeError(f"width {edge_set.width}: edges are unsorted or duplicated")
        previous = edge
    if hashlib.sha256(_serialize(edge_set.edges)).hexdigest() != edge_set.sha256:
        raise DirectEdgeError(f"width {edge_set.width}: edge-set hash does not match its edges")


__all__ = [
    "DirectEdgeError",
    "DirectEdgeSet",
    "validate_universe",
    "parse_direct_edge_lines",
    "parse_direct_edge_tsv",
    "write_normalized_edges",
    "read_normalized_edges",
    "verify_edge_set",
    "edges_sha256",
]
