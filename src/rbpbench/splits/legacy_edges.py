"""Deterministic preparation/validation of the Task 002C legacy-diagnostic
edge evidence (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md,
F4): every one of the six per-width edge files ``legacy_diagnostic``
consumes -- ``edges_<width>.json`` (Task 002B similarity/cluster edges) and
``exact_rc_edges_<width>.json`` (Task 002B decode exact/reverse-complement
duplicate edges) -- must be bound to explicit, pinned
``(width, evidence kind, size, hash)`` provenance and have every parsed
endpoint reconciled against the closed canonical ``row_0..row_{N-1}``
sample universe before use. A bare, operator-authored JSON file (even an
empty list) can no longer qualify merely because ITS OWN current hash
happens to be recorded.

``exact_rc_edges_<width>.json`` is never hand-authored: its pinned
expectation is auto-extracted from the already committed, sanitized
``manifests/sequence_decode_002b2.json`` (the same accepted Task 002B
decode-duplicate-edge artifacts F2 binds the decode FASTAs to), never a
second, independently hard-coded copy of that hash. ``edges_<width>.json``
(the Task 002B similarity/cluster edges) is pinned directly in the 002C
config's ``[legacy_edges]`` table, mirroring how ``dataset_audit.json``/
``proteins.tsv`` are pinned without a separate derivation manifest -- no
sanitized per-width cluster-edge manifest is committed yet, and producing
one would require opening the real, ignored Task 002B cluster generation
directory, which is out of scope for this bounded correction.
"""

from __future__ import annotations

import json
from pathlib import Path

from rbpbench.data.audit import sha256_file


class EdgeProvenanceError(ValueError):
    """A legacy-diagnostic edge file failed pinned hash/size verification,
    contained a malformed entry, or named an endpoint outside the closed
    canonical sample universe. Never silently repaired or partially
    accepted.
    """


def canonical_sample_ids(expected_row_count: int) -> frozenset[str]:
    """The closed ``row_0..row_{expected_row_count - 1}`` canonical sample
    universe every edge endpoint must resolve inside.
    """
    return frozenset(f"row_{i}" for i in range(expected_row_count))


def verify_and_parse_edges(
    path: Path,
    *,
    expected_sha256: str,
    expected_byte_size: int,
    canonical_ids: frozenset[str],
    label: str,
) -> list[tuple[str, str]]:
    """Hash/size-verifies ``path`` against its PINNED ``(size, hash)``
    expectation before ever parsing it -- a bare operator-authored JSON
    file, even an empty list, can no longer qualify merely because its own
    current hash is recorded -- then parses it as a JSON list of two-element
    ``[sample_id, sample_id]`` pairs and reconciles every endpoint against
    ``canonical_ids`` (a foreign endpoint is a hard failure, never silently
    dropped).
    """
    path = Path(path)
    if not path.is_file():
        raise EdgeProvenanceError(f"{label} not found at {path}")
    actual_size = path.stat().st_size
    if actual_size != expected_byte_size:
        raise EdgeProvenanceError(
            f"{label} at {path} is {actual_size} bytes, expected exactly {expected_byte_size} per its pinned "
            "provenance"
        )
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise EdgeProvenanceError(
            f"{label} at {path} hashes to {actual_sha256}, expected exactly {expected_sha256} per its pinned "
            "provenance"
        )

    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise EdgeProvenanceError(f"{label} at {path}: expected a JSON list of [sample_id, sample_id] pairs")

    pairs: list[tuple[str, str]] = []
    foreign: list[str] = []
    for entry in raw:
        if not (isinstance(entry, list) and len(entry) == 2 and all(isinstance(x, str) for x in entry)):
            raise EdgeProvenanceError(f"{label} at {path}: malformed edge entry {entry!r}")
        a, b = entry
        if a not in canonical_ids:
            foreign.append(a)
        if b not in canonical_ids:
            foreign.append(b)
        pairs.append((a, b))
    if foreign:
        raise EdgeProvenanceError(
            f"{label} at {path}: {len(foreign)} endpoint occurrence(s) outside the closed canonical sample "
            f"universe, e.g. {sorted(set(foreign))[:5]}"
        )
    return pairs


def bind_edge_evidence(*, width: int, evidence_kind: str, path: Path, sha256: str, byte_size: int) -> dict:
    """One explicit ``(width, evidence kind, size, hash)`` binding -- never
    a bare hash string folded into a flat, sortable list that loses which
    file it belongs to.
    """
    return {
        "width": width,
        "evidence_kind": evidence_kind,
        "path": str(path),
        "sha256": sha256,
        "byte_size": byte_size,
    }


__all__ = [
    "EdgeProvenanceError",
    "canonical_sample_ids",
    "verify_and_parse_edges",
    "bind_edge_evidence",
]
