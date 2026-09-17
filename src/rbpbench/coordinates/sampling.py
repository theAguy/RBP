"""Deterministic three-stratum sampling: representative, quota, filler.

Mirrors the Task 001 sampling design: a 5,000-row label-blind representative
stratum drives the headline gate, a per-protein quota supplement guarantees a
gross-failure screening floor, and a filler stratum fills any remaining
positions. All stratum membership is decided by SHA-256 stable hash rank
(:mod:`rbpbench.coordinates.hashing`), never by labels for the
representative/filler strata and never by Python's process-randomized
``hash()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from rbpbench.coordinates.hashing import label_blind_rank, quota_rank

REPRESENTATIVE = "representative"
QUOTA = "quota"
FILLER = "filler"


@dataclass(frozen=True)
class DatasetRow:
    """One source row: a stable row index and its signed labels.

    A positive entry ``k`` means known positive for protein ``k``; a negative
    entry ``-k`` means known negative for protein ``k``; absence means unknown.
    """

    row_index: int
    labels: tuple[int, ...]

    @property
    def sample_id(self) -> str:
        return f"row_{self.row_index}"


@dataclass(frozen=True)
class SampleAssignment:
    sample_id: str
    row_index: int
    stratum: str
    labels: tuple[int, ...]


@dataclass(frozen=True)
class SamplingResult:
    assignments: tuple[SampleAssignment, ...]
    representative_ids: frozenset
    quota_ids: frozenset
    filler_ids: frozenset
    # Always empty: build_sample stops immediately (raises ValueError) on the
    # first unsatisfiable protein/class quota rather than deferring it here.
    unsatisfied_quotas: tuple[tuple[int, str], ...]


def _label_counts(row_ids: Sequence[str], by_id: dict, num_proteins: int) -> tuple[list[int], list[int]]:
    positive = [0] * (num_proteins + 1)
    negative = [0] * (num_proteins + 1)
    for row_id in row_ids:
        for value in by_id[row_id].labels:
            protein = abs(value)
            if protein > num_proteins:
                continue
            if value > 0:
                positive[protein] += 1
            else:
                negative[protein] += 1
    return positive, negative


def build_sample(
    rows: Sequence[DatasetRow],
    *,
    seed: int,
    num_proteins: int,
    representative_size: int,
    total_size: int,
    min_positive_per_protein: int,
    min_negative_per_protein: int,
) -> SamplingResult:
    """Assemble the deterministic representative/quota/filler sample.

    Raises ``ValueError`` if the dataset cannot supply ``total_size`` distinct
    rows, or if quota selection alone would exceed ``total_size`` (a
    misconfiguration for the given dataset size, not something to repair
    silently).
    """
    if total_size < representative_size:
        raise ValueError("total_size must be >= representative_size")

    by_id = {row.sample_id: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("duplicate row_index values in input rows")
    if len(by_id) < total_size:
        raise ValueError(f"only {len(by_id)} rows available; need {total_size}")

    all_ids = list(by_id.keys())
    ranked_all = sorted(all_ids, key=lambda rid: label_blind_rank(seed, rid))

    representative_ids = ranked_all[:representative_size]
    selected = set(representative_ids)

    positive_counts, negative_counts = _label_counts(representative_ids, by_id, num_proteins)

    quota_ids: list[str] = []

    for protein in range(1, num_proteins + 1):
        for class_label, sign, counts, minimum in (
            ("positive", 1, positive_counts, min_positive_per_protein),
            ("negative", -1, negative_counts, min_negative_per_protein),
        ):
            needed = minimum - counts[protein]
            if needed <= 0:
                continue
            candidates = [
                row_id
                for row_id in all_ids
                if row_id not in selected and (sign * protein) in by_id[row_id].labels
            ]
            candidates.sort(key=lambda rid: quota_rank(seed, rid, protein, class_label))
            chosen = candidates[:needed]
            if len(chosen) < needed:
                # Stop immediately: an unsatisfiable quota is a dataset/config
                # problem to surface now, not a gap to defer to later
                # reporting while sampling continues to build an unreliable
                # per-protein screening floor.
                raise ValueError(
                    f"quota unsatisfied for protein {protein} class {class_label!r}: "
                    f"needed {needed} more, only {len(chosen)} candidate rows available"
                )
            for row_id in chosen:
                selected.add(row_id)
                quota_ids.append(row_id)
                for value in by_id[row_id].labels:
                    p = abs(value)
                    if p > num_proteins:
                        continue
                    if value > 0:
                        positive_counts[p] += 1
                    else:
                        negative_counts[p] += 1

    if len(selected) > total_size:
        raise ValueError(
            f"representative ({representative_size}) plus quota ({len(quota_ids)}) "
            f"selections ({len(selected)}) exceed total_size ({total_size})"
        )

    remaining = total_size - len(selected)
    filler_pool = [row_id for row_id in ranked_all if row_id not in selected]
    if len(filler_pool) < remaining:
        raise ValueError("not enough remaining rows to fill the sample to total_size")
    filler_ids = filler_pool[:remaining]
    selected.update(filler_ids)

    stratum_of = {row_id: REPRESENTATIVE for row_id in representative_ids}
    for row_id in quota_ids:
        stratum_of.setdefault(row_id, QUOTA)
    for row_id in filler_ids:
        stratum_of[row_id] = FILLER

    ordered = sorted(selected, key=lambda rid: by_id[rid].row_index)
    assignments = tuple(
        SampleAssignment(
            sample_id=row_id,
            row_index=by_id[row_id].row_index,
            stratum=stratum_of[row_id],
            labels=by_id[row_id].labels,
        )
        for row_id in ordered
    )

    return SamplingResult(
        assignments=assignments,
        representative_ids=frozenset(representative_ids),
        quota_ids=frozenset(quota_ids),
        filler_ids=frozenset(filler_ids),
        unsatisfied_quotas=(),
    )
