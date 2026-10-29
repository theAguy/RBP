"""Training-bound deterministic GC-matched evaluation subsets."""

from __future__ import annotations

import hashlib
import numpy as np


class GCMatchError(ValueError):
    pass


def gc_bin_edges(fitting_gc) -> np.ndarray:
    values = np.asarray(fitting_gc, dtype=np.float64)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise GCMatchError("fitting GC values must be a non-empty finite vector")
    quantiles = np.quantile(values, np.linspace(0, 1, 11), method="linear")
    return np.unique(quantiles)


def assign_bins(values, edges: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    edges = np.asarray(edges, dtype=np.float64)
    if edges.ndim != 1 or not len(edges) or np.any(np.diff(edges) <= 0):
        if len(edges) == 1:
            return np.zeros(len(values), dtype=np.int16)
        raise GCMatchError("edges must be unique and increasing")
    internal = edges[1:-1]
    return np.searchsorted(internal, values, side="left").astype(np.int16)


def _key(seed: int, sample_id: str, protein_id: int, width: int) -> bytes:
    return hashlib.sha256(f"{seed}\0{sample_id}\0{protein_id}\0{width}".encode()).digest()


def matched_indices_with_edges(
    *, edges, evaluation_gc, labels, sample_ids, seed: int, protein_id: int, width: int
) -> np.ndarray:
    """Return the deterministic class-balanced evaluation subset for frozen edges.

    Phase A derives the GC quantiles from fitting rows and persists them.  Phase
    B must consume those exact edges rather than deriving anything from test.
    """
    labels = np.asarray(labels, dtype=np.int8)
    evaluation_gc = np.asarray(evaluation_gc, dtype=np.float64)
    edges = np.asarray(edges, dtype=np.float64)
    sample_ids = list(sample_ids)
    if (
        len(labels) != len(evaluation_gc)
        or len(labels) != len(sample_ids)
        or not np.isin(labels, [0, 1]).all()
        or not np.isfinite(evaluation_gc).all()
    ):
        raise GCMatchError("evaluation arrays must align with binary labels")
    if len(sample_ids) != len(set(sample_ids)):
        raise GCMatchError("sample IDs must be unique")
    bins = assign_bins(evaluation_gc, edges)
    selected: list[int] = []
    for bin_id in sorted(set(map(int, bins))):
        by_class = []
        for label in (0, 1):
            candidates = [index for index in np.flatnonzero((bins == bin_id) & (labels == label))]
            candidates.sort(key=lambda index: _key(seed, sample_ids[index], protein_id, width))
            by_class.append(candidates)
        count = min(map(len, by_class))
        selected.extend(by_class[0][:count])
        selected.extend(by_class[1][:count])
    selected_array = np.asarray(sorted(selected), dtype=np.int64)
    if not len(selected_array) or len(set(labels[selected_array])) != 2:
        raise GCMatchError("GC matching retained fewer than two classes")
    if int(labels[selected_array].sum()) * 2 != len(selected_array):
        raise GCMatchError("GC matching did not retain equal class counts")
    return selected_array


def matched_indices(*, fitting_gc, evaluation_gc, labels, sample_ids, seed: int, protein_id: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    edges = gc_bin_edges(fitting_gc)
    selected = matched_indices_with_edges(
        edges=edges, evaluation_gc=evaluation_gc, labels=labels,
        sample_ids=sample_ids, seed=seed, protein_id=protein_id, width=width,
    )
    return selected, edges
