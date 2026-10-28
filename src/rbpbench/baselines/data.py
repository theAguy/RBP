"""Strict label and accepted-membership handling for Task 003B."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import re
from typing import Iterable, Sequence


class BaselineDataError(ValueError):
    pass


PARTITIONS = ("train", "validation", "test")
TOKEN = re.compile(r"^([+-]?)([1-9][0-9]*)$")


def parse_labels(raw: str, *, protein_count: int = 122) -> dict[int, int]:
    if raw == "":
        return {}
    result: dict[int, int] = {}
    for token in raw.split(";"):
        match = TOKEN.fullmatch(token)
        if not match:
            raise BaselineDataError(f"malformed label token: {token!r}")
        protein_id = int(match.group(2))
        if not 1 <= protein_id <= protein_count:
            raise BaselineDataError(f"protein ID out of range: {protein_id}")
        label = 0 if match.group(1) == "-" else 1
        if protein_id in result:
            raise BaselineDataError(f"duplicate or contradictory protein label: {protein_id}")
        result[protein_id] = label
    return result


@dataclass(frozen=True)
class MembershipRow:
    sample_id: str
    component_id: str
    partition: str


def read_membership(lines: Iterable[str], *, expected_rows: int | None = None) -> list[MembershipRow]:
    reader = csv.DictReader(lines, delimiter="\t")
    if reader.fieldnames != ["sample_id", "component_id", "partition"]:
        raise BaselineDataError(f"unexpected membership header: {reader.fieldnames}")
    result = []
    components: dict[str, str] = {}
    for index, row in enumerate(reader):
        expected_id = f"row_{index}"
        if row["sample_id"] != expected_id:
            raise BaselineDataError(f"membership ID {row['sample_id']!r} != {expected_id!r}")
        component_id = row["component_id"]
        partition = row["partition"]
        if not component_id or partition not in PARTITIONS:
            raise BaselineDataError("invalid component or partition")
        prior = components.setdefault(component_id, partition)
        if prior != partition:
            raise BaselineDataError(f"component {component_id} is split")
        result.append(MembershipRow(expected_id, component_id, partition))
    if expected_rows is not None and len(result) != expected_rows:
        raise BaselineDataError(f"membership has {len(result)} rows, expected {expected_rows}")
    return result


@dataclass
class LabelIndex:
    sample_ids: dict[tuple[int, str], list[str]]
    labels: dict[tuple[int, str], list[int]]
    skipped_partition_rows: dict[str, int]


def build_label_index(
    csv_lines: Iterable[str],
    membership: Sequence[MembershipRow],
    *,
    protein_ids: Sequence[int],
    allowed_partitions: set[str],
) -> LabelIndex:
    if not allowed_partitions <= set(PARTITIONS):
        raise BaselineDataError("unknown allowed partition")
    protein_ids = tuple(protein_ids)
    if len(protein_ids) != len(set(protein_ids)) or any(not 1 <= value <= 122 for value in protein_ids):
        raise BaselineDataError("invalid protein IDs")
    reader = csv.DictReader(csv_lines)
    if reader.fieldnames is None or "labels" not in reader.fieldnames:
        raise BaselineDataError("CSV is missing labels column")
    ids: dict[tuple[int, str], list[str]] = {}
    labels: dict[tuple[int, str], list[int]] = {}
    skipped = {partition: 0 for partition in PARTITIONS}
    row_count = 0
    for row_count, row in enumerate(reader, 1):
        index = row_count - 1
        if index >= len(membership):
            raise BaselineDataError("CSV has more rows than membership")
        member = membership[index]
        if member.partition not in allowed_partitions:
            skipped[member.partition] += 1
            continue
        parsed = parse_labels(row["labels"])
        for protein_id in protein_ids:
            if protein_id not in parsed:
                continue
            key = (protein_id, member.partition)
            ids.setdefault(key, []).append(member.sample_id)
            labels.setdefault(key, []).append(parsed[protein_id])
    if row_count != len(membership):
        raise BaselineDataError(f"CSV/membership row mismatch: {row_count} != {len(membership)}")
    return LabelIndex(ids, labels, skipped)


def known_counts(index: LabelIndex) -> dict[tuple[int, str], tuple[int, int]]:
    result = {}
    for key, labels in index.labels.items():
        positives = sum(labels)
        result[key] = (positives, len(labels) - positives)
    return result
