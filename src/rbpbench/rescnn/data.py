"""Compact sequence tensors and a partition-first access boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset

from rbpbench.baselines.data import BaselineDataError, parse_labels


class ResCNNDataError(ValueError):
    pass


ALPHABET = "ACGT"
BASE_CODE = {base: index for index, base in enumerate(ALPHABET)}
ALLOWED_PARTITIONS = frozenset({"train", "validation"})


@dataclass(frozen=True)
class Membership:
    sample_id: str
    component_id: str
    partition: str


@dataclass(frozen=True)
class DeferredRawRow:
    """Suppliers make forbidden test-field interpretation directly testable."""

    sample_id: str
    labels: Callable[[], str]
    sequence: Callable[[], str]


@dataclass(frozen=True)
class CompactRecord:
    sample_id: str
    component_id: str
    partition: str
    base_codes: tuple[int, ...]
    targets: tuple[float, ...]
    masks: tuple[float, ...]


def encode_sequence(sequence: str, *, width: int = 500) -> tuple[int, ...]:
    if len(sequence) != width:
        raise ResCNNDataError(f"sequence length {len(sequence)} != {width}")
    try:
        return tuple(BASE_CODE[base] for base in sequence)
    except KeyError as exc:
        raise ResCNNDataError(f"non-ACGT base: {exc.args[0]!r}") from exc


def targets_and_masks(raw_labels: str, *, output_count: int = 122) -> tuple[tuple[float, ...], tuple[float, ...]]:
    try:
        parsed = parse_labels(raw_labels, protein_count=output_count)
    except BaselineDataError as exc:
        raise ResCNNDataError(str(exc)) from exc
    targets = [0.0] * output_count
    masks = [0.0] * output_count
    for protein_id, label in parsed.items():
        targets[protein_id - 1] = float(label)
        masks[protein_id - 1] = 1.0
    return tuple(targets), tuple(masks)


def build_allowed_records(
    rows: Sequence[DeferredRawRow],
    membership: Mapping[str, Membership],
    *,
    width: int = 500,
    output_count: int = 122,
) -> tuple[tuple[CompactRecord, ...], dict[str, int]]:
    seen: set[str] = set()
    retained: list[CompactRecord] = []
    skipped = {"test": 0}
    for row in rows:
        if row.sample_id in seen:
            raise ResCNNDataError(f"duplicate raw sample ID: {row.sample_id}")
        seen.add(row.sample_id)
        member = membership.get(row.sample_id)
        if member is None or member.sample_id != row.sample_id:
            raise ResCNNDataError(f"missing membership for {row.sample_id}")
        if member.partition == "test":
            skipped["test"] += 1
            continue
        if member.partition not in ALLOWED_PARTITIONS:
            raise ResCNNDataError(f"invalid development partition: {member.partition!r}")
        # Suppliers are invoked only after the partition gate above.
        targets, masks = targets_and_masks(row.labels(), output_count=output_count)
        codes = encode_sequence(row.sequence(), width=width)
        retained.append(
            CompactRecord(
                sample_id=row.sample_id,
                component_id=member.component_id,
                partition=member.partition,
                base_codes=codes,
                targets=targets,
                masks=masks,
            )
        )
    if seen != set(membership):
        missing = sorted(set(membership) - seen)[:5]
        raise ResCNNDataError(f"raw/membership universe mismatch; missing {missing}")
    return tuple(retained), skipped


class CompactSequenceDataset(Dataset):
    def __init__(self, records: Sequence[CompactRecord]):
        if not records:
            raise ResCNNDataError("dataset cannot be empty")
        self.records = tuple(records)
        self.base_codes = torch.tensor([record.base_codes for record in records], dtype=torch.uint8)
        self.targets = torch.tensor([record.targets for record in records], dtype=torch.float32)
        self.masks = torch.tensor([record.masks for record in records], dtype=torch.float32)

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        sequence = F.one_hot(self.base_codes[index].long(), num_classes=4).to(torch.float32)
        return sequence, self.targets[index], self.masks[index]

    @property
    def sample_ids(self) -> tuple[str, ...]:
        return tuple(record.sample_id for record in self.records)


def assert_no_test_records(records: Sequence[CompactRecord]) -> None:
    offenders = [record.sample_id for record in records if record.partition == "test"]
    if offenders:
        raise ResCNNDataError(f"test records entered development cache: {offenders[:5]}")
