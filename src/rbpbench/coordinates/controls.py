"""Deterministic dinucleotide-preserving shuffled negative controls.

Uses the Altschul-Erdos idea in its simplest correct form: the dinucleotide
multiset of a sequence is exactly its edge multiset in a directed graph over
{A, C, G, T}, and the source sequence itself is a witness that an Eulerian
path from ``sequence[0]`` to ``sequence[-1]`` exists in that graph. Hierholzer's
algorithm reconstructs *some* Eulerian path from any edge-visitation order, so
shuffling each vertex's outgoing-edge order with a seeded RNG and then running
Hierholzer's algorithm always yields a sequence with an identical
dinucleotide composition, without needing the classical last-edge trick.
"""

from __future__ import annotations

import random
from collections import Counter


def dinucleotide_counts(sequence: str) -> Counter:
    return Counter(zip(sequence, sequence[1:]))


def _build_adjacency(sequence: str) -> dict[str, list[str]]:
    adjacency: dict[str, list[str]] = {}
    for a, b in zip(sequence, sequence[1:]):
        adjacency.setdefault(a, []).append(b)
    return adjacency


def _eulerian_path(adjacency: dict[str, list[str]], start: str) -> list[str]:
    local = {vertex: list(neighbors) for vertex, neighbors in adjacency.items()}
    stack = [start]
    path: list[str] = []
    while stack:
        vertex = stack[-1]
        neighbors = local.get(vertex)
        if neighbors:
            stack.append(neighbors.pop())
        else:
            path.append(stack.pop())
    path.reverse()
    return path


def dinucleotide_shuffle(sequence: str, rng: random.Random) -> str:
    """Return a random re-ordering of ``sequence`` with identical dinucleotide counts."""
    if len(sequence) < 3:
        return sequence
    adjacency = _build_adjacency(sequence)
    for neighbors in adjacency.values():
        rng.shuffle(neighbors)
    path = _eulerian_path(adjacency, sequence[0])
    shuffled = "".join(path)
    assert len(shuffled) == len(sequence)
    return shuffled


def generate_control(
    sequence: str,
    *,
    seed_fn,
    max_attempts: int = 50,
) -> str:
    """Produce a shuffled control that differs from ``sequence``.

    ``seed_fn(attempt: int) -> int`` supplies a deterministic RNG seed per
    attempt (see :func:`rbpbench.coordinates.hashing.control_seed`). Raises
    ``RuntimeError`` rather than silently returning an identical sequence.
    """
    for attempt in range(max_attempts):
        rng = random.Random(seed_fn(attempt))
        shuffled = dinucleotide_shuffle(sequence, rng)
        if shuffled != sequence:
            return shuffled
    raise RuntimeError(
        f"could not produce a dinucleotide-preserving shuffle that differs "
        f"from the source sequence within {max_attempts} attempts"
    )
