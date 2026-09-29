"""Strict streaming ingestion of the accepted Task 002B component membership
and the Task 002 CSV's signed protein labels, for Task 002C partition
assignment.

Grouping (component membership) is treated as immutable and label-blind;
this module only ever reads labels AFTER reconciling the frozen component
universe, and only to aggregate whole-component counts -- it never
redefines or splits a component
(``docs/tasks/002c_partition_assignment_and_audit.md``, "Frozen assignment
contract"). Both the membership reconciliation and the label parser are
strict: a missing, duplicated, foreign, or malformed value is always a hard
failure, never silently dropped or repaired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping

from rbpbench.data.audit import sha256_file
from rbpbench.splits import output as splits_output

_HEX_DIGITS = frozenset("0123456789abcdef")


class ComponentIngestionError(ValueError):
    """The Task 002B component membership file failed strict hash/size or
    universe/ID-shape reconciliation. Never silently repaired or partially
    accepted.
    """


class LabelParseError(ValueError):
    """One CSV row's ``labels`` field violated the strict signed
    protein-ID contract (docs/DATA.md): a malformed/out-of-range/zero ID, a
    same-sign repeat, or a contradictory ``+k``/``-k`` pair in one row.
    """


def verify_component_membership_file(path: Path, *, expected_sha256: str, expected_byte_size: int) -> str:
    """Confirms the accepted Task 002B membership file's exact byte size and
    SHA-256 BEFORE it is ever parsed. A production config's real expected
    hash/size can never be satisfied by a tiny fixture file, so a fixture
    can never slip through a production invocation by construction.
    """
    path = Path(path)
    if not path.is_file():
        raise ComponentIngestionError(f"component membership file not found at {path}")
    actual_size = path.stat().st_size
    if actual_size != expected_byte_size:
        raise ComponentIngestionError(
            f"component membership file {path} is {actual_size} bytes, expected exactly {expected_byte_size}"
        )
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ComponentIngestionError(
            f"component membership file {path} hashes to {actual_sha256}, expected exactly {expected_sha256}"
        )
    return actual_sha256


@dataclass(frozen=True)
class ComponentUniverse:
    sample_to_component: Mapping[str, str]
    component_sizes: Mapping[str, int]


def load_component_membership(
    path: Path,
    *,
    expected_sample_count: int,
    expected_component_count: int,
    expected_component_sizes: Mapping[str, int] | None = None,
) -> ComponentUniverse:
    """Streams the accepted Task 002B ``sample_id,component_id`` gzip
    (:func:`rbpbench.splits.output.read_component_membership_gzip`) and
    reconciles it: the canonical ``row_0..row_{expected_sample_count - 1}``
    universe must appear exactly once each, every component ID must be a
    lowercase 64-hex digest, the component count must match exactly, and
    (when supplied) the derived component-size map must match the accepted
    Task 002B report byte-for-byte. Never silently drops or repairs a
    discrepancy; every problem found is named in one raised error.
    """
    rows = splits_output.read_component_membership_gzip(Path(path))

    sample_to_component: dict[str, str] = {}
    component_sizes: dict[str, int] = {}
    problems: list[str] = []
    duplicates: list[str] = []
    bad_ids: list[str] = []
    for sample_id, component_id in rows:
        if sample_id in sample_to_component:
            duplicates.append(sample_id)
            continue
        if not (len(component_id) == 64 and set(component_id) <= _HEX_DIGITS):
            bad_ids.append(component_id)
        sample_to_component[sample_id] = component_id
        component_sizes[component_id] = component_sizes.get(component_id, 0) + 1

    if duplicates:
        problems.append(f"{len(duplicates)} duplicate sample_id(s), e.g. {sorted(duplicates)[:5]}")
    if bad_ids:
        problems.append(f"{len(bad_ids)} component_id(s) are not lowercase 64-hex digests, e.g. {sorted(bad_ids)[:5]}")

    expected_ids = {f"row_{i}" for i in range(expected_sample_count)}
    actual_ids = set(sample_to_component)
    missing = expected_ids - actual_ids
    foreign = actual_ids - expected_ids
    if missing:
        problems.append(f"missing {len(missing)} expected sample ID(s), e.g. {sorted(missing)[:5]}")
    if foreign:
        problems.append(f"contains {len(foreign)} foreign sample ID(s), e.g. {sorted(foreign)[:5]}")
    if len(component_sizes) != expected_component_count:
        problems.append(f"component count {len(component_sizes)} != expected exactly {expected_component_count}")
    if expected_component_sizes is not None and component_sizes != dict(expected_component_sizes):
        problems.append("derived component-size map does not exactly match the accepted Task 002B report")

    if problems:
        raise ComponentIngestionError("component membership reconciliation failed: " + "; ".join(problems))

    return ComponentUniverse(sample_to_component=sample_to_component, component_sizes=component_sizes)


def parse_signed_labels(raw_field: str, *, protein_id_min: int = 1, protein_id_max: int = 122) -> dict[int, int]:
    """Parses a semicolon-separated signed-protein-ID field (docs/DATA.md)
    into ``{protein_id: +1 or -1}``.

    Strict: every token must carry an explicit ``+``/``-`` sign; rejects an
    ID of zero, a malformed or non-numeric ID, an ID outside
    ``[protein_id_min, protein_id_max]``, the same protein repeated with the
    same sign, and a protein appearing as both ``+k`` and ``-k`` in one row.
    A protein absent from the field is unknown -- it simply never appears
    in the returned mapping, and never contributes to any count.
    """
    raw_field = raw_field.strip()
    result: dict[int, int] = {}
    if not raw_field:
        return result
    for token in raw_field.split(";"):
        token = token.strip()
        if not token:
            raise LabelParseError(f"empty signed-ID token in labels field {raw_field!r}")
        if token[0] not in "+-":
            raise LabelParseError(f"signed-ID token {token!r} in {raw_field!r} is missing an explicit sign")
        sign = 1 if token[0] == "+" else -1
        digits = token[1:]
        if not digits.isdigit():
            raise LabelParseError(f"malformed protein ID in token {token!r} (labels field {raw_field!r})")
        protein_id = int(digits)
        if protein_id == 0 or not (protein_id_min <= protein_id <= protein_id_max):
            raise LabelParseError(
                f"protein ID {protein_id} in token {token!r} is out of range "
                f"[{protein_id_min}, {protein_id_max}] (labels field {raw_field!r})"
            )
        if protein_id in result:
            if result[protein_id] == sign:
                raise LabelParseError(f"protein {protein_id} repeated with the same sign in {raw_field!r}")
            raise LabelParseError(
                f"protein {protein_id} appears as both +{protein_id} and -{protein_id} in {raw_field!r}"
            )
        result[protein_id] = sign
    return result


def iter_csv_component_label_rows(
    csv_path: Path, *, protein_id_min: int = 1, protein_id_max: int = 122
) -> Iterator[tuple[int, str, dict[int, int]]]:
    """Streams ``(row_index, sample_id, signed_label_map)`` triples from the
    ``sequence,labels`` CSV without materializing the file or any dense
    label matrix; ``sequence`` is intentionally never read here (label
    ingestion is independent of decode).
    """
    import csv

    with Path(csv_path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row_index, row in enumerate(reader):
            sample_id = f"row_{row_index}"
            try:
                labels = parse_signed_labels(row["labels"], protein_id_min=protein_id_min, protein_id_max=protein_id_max)
            except LabelParseError as exc:
                raise LabelParseError(f"{sample_id}: {exc}") from exc
            yield row_index, sample_id, labels


@dataclass
class ComponentAggregate:
    size: int = 0
    # protein_id -> [known_positive_count, known_negative_count]
    label_counts: dict[int, list[int]] = field(default_factory=dict)


def stream_component_label_aggregates(
    csv_path: Path, universe: ComponentUniverse, *, protein_id_min: int = 1, protein_id_max: int = 122
) -> dict[str, ComponentAggregate]:
    """Single streaming pass over ``csv_path`` aggregating each accepted
    component's row count and per-protein known-positive/known-negative
    counts, without ever materializing a dense row-by-protein label matrix.

    Every CSV row must belong to the frozen ``universe``, and every
    universe sample ID must be seen exactly once in the CSV; either
    discrepancy is a hard failure (never a silent skip), as is any
    aggregated component size disagreeing with the accepted universe's own
    component-size map.
    """
    aggregates: dict[str, ComponentAggregate] = {}
    seen_ids: set[str] = set()
    for row_index, sample_id, labels in iter_csv_component_label_rows(
        csv_path, protein_id_min=protein_id_min, protein_id_max=protein_id_max
    ):
        component_id = universe.sample_to_component.get(sample_id)
        if component_id is None:
            raise ComponentIngestionError(f"{sample_id} (CSV row {row_index}) is absent from the component universe")
        if sample_id in seen_ids:
            raise ComponentIngestionError(f"{sample_id} appears more than once in the CSV")
        seen_ids.add(sample_id)
        aggregate = aggregates.setdefault(component_id, ComponentAggregate())
        aggregate.size += 1
        for protein_id, sign in labels.items():
            counts = aggregate.label_counts.setdefault(protein_id, [0, 0])
            if sign > 0:
                counts[0] += 1
            else:
                counts[1] += 1

    missing = set(universe.sample_to_component) - seen_ids
    if missing:
        raise ComponentIngestionError(
            f"CSV is missing {len(missing)} expected sample ID(s) present in the component universe, "
            f"e.g. {sorted(missing)[:5]}"
        )
    for component_id, expected_size in universe.component_sizes.items():
        actual_size = aggregates.get(component_id, ComponentAggregate()).size
        if actual_size != expected_size:
            raise ComponentIngestionError(
                f"component {component_id!r} aggregated size {actual_size} != accepted component size {expected_size}"
            )
    return aggregates


def to_component_label_counts(aggregates: Mapping[str, ComponentAggregate]) -> list:
    """Converts streamed aggregates into
    :class:`rbpbench.splits.assignment.ComponentLabelCounts` records ready
    for :func:`rbpbench.splits.assignment.assign_partitions`.
    """
    from rbpbench.splits.assignment import ComponentLabelCounts

    return [
        ComponentLabelCounts(
            component_id=component_id,
            size=aggregate.size,
            label_counts={pid: (counts[0], counts[1]) for pid, counts in aggregate.label_counts.items()},
        )
        for component_id, aggregate in aggregates.items()
    ]


__all__ = [
    "ComponentIngestionError",
    "LabelParseError",
    "ComponentUniverse",
    "ComponentAggregate",
    "verify_component_membership_file",
    "load_component_membership",
    "parse_signed_labels",
    "iter_csv_component_label_rows",
    "stream_component_label_aggregates",
    "to_component_label_counts",
]
