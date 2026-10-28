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
SAMPLE_ID = re.compile(r"^row_(0|[1-9][0-9]*)$")


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
    rows_by_index: dict[int, MembershipRow] = {}
    components: dict[str, str] = {}
    for row in reader:
        match = SAMPLE_ID.fullmatch(row["sample_id"])
        if not match:
            raise BaselineDataError(f"invalid membership sample ID: {row['sample_id']!r}")
        index = int(match.group(1))
        if index in rows_by_index:
            raise BaselineDataError(f"duplicate membership sample ID: row_{index}")
        if expected_rows is not None and index >= expected_rows:
            raise BaselineDataError(f"foreign membership sample ID: row_{index}")
        component_id = row["component_id"]
        partition = row["partition"]
        if not component_id or partition not in PARTITIONS:
            raise BaselineDataError("invalid component or partition")
        prior = components.setdefault(component_id, partition)
        if prior != partition:
            raise BaselineDataError(f"component {component_id} is split")
        rows_by_index[index] = MembershipRow(f"row_{index}", component_id, partition)
    row_count = expected_rows if expected_rows is not None else len(rows_by_index)
    if len(rows_by_index) != row_count or set(rows_by_index) != set(range(row_count)):
        missing = sorted(set(range(row_count)) - rows_by_index.keys())[:5]
        raise BaselineDataError(f"membership universe mismatch: {len(rows_by_index)} rows; missing {missing}")
    return [rows_by_index[index] for index in range(row_count)]


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
