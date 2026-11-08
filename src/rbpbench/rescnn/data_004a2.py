"""Streaming, test-blind real-data contract used by Task 004A-2.

The functions accept text iterables so every behavior is testable with tiny
synthetic fixtures. Opening and hash-binding real paths belongs to the runner.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import heapq
import re
from itertools import zip_longest
from typing import Iterable, Iterator, Mapping, Sequence

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset

from rbpbench.baselines.data import BaselineDataError, parse_labels


PARTITIONS = ("train", "validation", "test")
DEVELOPMENT_PARTITIONS = ("train", "validation")
SAMPLE_ID = re.compile(r"row_(0|[1-9][0-9]*)")
BIT_TO_BASE = {"1000": ("A", 0), "0100": ("C", 1), "0010": ("G", 2), "0001": ("T", 3)}
_MISSING = object()


class ResCNN004A2DataError(ValueError):
    pass


@dataclass
class AccessCounters:
    test_rows_seen: int = 0
    test_label_supplier_calls: int = 0
    test_csv_sequence_supplier_calls: int = 0
    test_fasta_sequence_interpretations: int = 0
    test_tensor_rows: int = 0
    test_prediction_rows: int = 0

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "test_rows_seen": self.test_rows_seen,
            "test_label_supplier_calls": self.test_label_supplier_calls,
            "test_csv_sequence_supplier_calls": self.test_csv_sequence_supplier_calls,
            "test_fasta_sequence_interpretations": self.test_fasta_sequence_interpretations,
            "test_tensor_rows": self.test_tensor_rows,
            "test_prediction_rows": self.test_prediction_rows,
            "test_accessed": any((
                self.test_label_supplier_calls,
                self.test_csv_sequence_supplier_calls,
                self.test_fasta_sequence_interpretations,
                self.test_tensor_rows,
                self.test_prediction_rows,
            )),
        }

    def require_blind(self) -> None:
        evidence = self.as_dict()
        if evidence["test_accessed"]:
            raise ResCNN004A2DataError(f"test-field access occurred: {evidence!r}")


@dataclass(frozen=True)
class MembershipRow:
    sample_id: str
    component_id: str
    partition: str


@dataclass(frozen=True)
class SampleCandidate:
    sample_id: str
    component_id: str
    partition: str
    content_sha256: str

    @property
    def row_index(self) -> int:
        match = SAMPLE_ID.fullmatch(self.sample_id)
        if match is None:
            raise ResCNN004A2DataError(f"noncanonical sample ID: {self.sample_id!r}")
        return int(match.group(1))


@dataclass(frozen=True)
class DevelopmentCounts:
    rows: Mapping[str, int]
    positive: Mapping[str, tuple[int, ...]]
    negative: Mapping[str, tuple[int, ...]]

    @property
    def output_count(self) -> int:
        return len(self.positive["train"])

    def unknown(self, partition: str) -> tuple[int, ...]:
        return tuple(
            self.rows[partition] - positive - negative
            for positive, negative in zip(self.positive[partition], self.negative[partition])
        )

    def matrix(self) -> dict[str, dict[str, tuple[int, ...] | int]]:
        return {
            partition: {
                "rows": self.rows[partition],
                "positive": self.positive[partition],
                "negative": self.negative[partition],
                "unknown": self.unknown(partition),
            }
            for partition in DEVELOPMENT_PARTITIONS
        }

    def combined_bounds(self) -> dict[str, int]:
        known = []
        positive = []
        negative = []
        for index in range(self.output_count):
            pos = sum(self.positive[p][index] for p in DEVELOPMENT_PARTITIONS)
            neg = sum(self.negative[p][index] for p in DEVELOPMENT_PARTITIONS)
            positive.append(pos)
            negative.append(neg)
            known.append(pos + neg)
        return {
            "train_plus_validation_rows": sum(self.rows.values()),
            "known_labels_per_protein_min": min(known),
            "known_labels_per_protein_max": max(known),
            "positive_labels_per_protein_min": min(positive),
            "negative_labels_per_protein_min": min(negative),
        }


class _CountAccumulator:
    def __init__(self, output_count: int):
        self.rows = {partition: 0 for partition in DEVELOPMENT_PARTITIONS}
        self.positive = {partition: [0] * output_count for partition in DEVELOPMENT_PARTITIONS}
        self.negative = {partition: [0] * output_count for partition in DEVELOPMENT_PARTITIONS}

    def add(self, partition: str, labels: Mapping[int, int]) -> None:
        if partition not in DEVELOPMENT_PARTITIONS:
            raise ResCNN004A2DataError("attempted to count a non-development partition")
        self.rows[partition] += 1
        for protein_id, label in labels.items():
            target = self.positive if label == 1 else self.negative
            target[partition][protein_id - 1] += 1

    def freeze(self) -> DevelopmentCounts:
        return DevelopmentCounts(
            rows=dict(self.rows),
            positive={key: tuple(value) for key, value in self.positive.items()},
            negative={key: tuple(value) for key, value in self.negative.items()},
        )


def decode_one_hot_bits(bits: str, *, width: int) -> tuple[str, tuple[int, ...]]:
    if len(bits) != width * 4:
        raise ResCNN004A2DataError(f"sequence has {len(bits)} bits; expected {width * 4}")
    bases: list[str] = []
    codes: list[int] = []
    for offset in range(0, len(bits), 4):
        group = bits[offset:offset + 4]
        value = BIT_TO_BASE.get(group)
        if value is None:
            raise ResCNN004A2DataError(f"invalid one-hot group at nucleotide {offset // 4}: {group!r}")
        base, code = value
        bases.append(base)
        codes.append(code)
    return "".join(bases), tuple(codes)


def encode_fasta_sequence(sequence: str, *, width: int) -> tuple[int, ...]:
    if len(sequence) != width:
        raise ResCNN004A2DataError(f"FASTA sequence length {len(sequence)} != {width}")
    lookup = {"A": 0, "C": 1, "G": 2, "T": 3}
    try:
        return tuple(lookup[base] for base in sequence)
    except KeyError as exc:
        raise ResCNN004A2DataError(f"FASTA contains non-ACGT base: {exc.args[0]!r}") from exc


def _parse_labels_primary(raw: str, output_count: int) -> dict[int, int]:
    try:
        return parse_labels(raw, protein_count=output_count)
    except BaselineDataError as exc:
        raise ResCNN004A2DataError(str(exc)) from exc


def _parse_labels_independent(raw: str, output_count: int) -> dict[int, int]:
    if raw == "":
        return {}
    result: dict[int, int] = {}
    for token in raw.split(";"):
        match = re.fullmatch(r"([+-]?)([1-9][0-9]*)", token)
        if match is None:
            raise ResCNN004A2DataError(f"malformed independent label token: {token!r}")
        protein_id = int(match.group(2))
        if not 1 <= protein_id <= output_count:
            raise ResCNN004A2DataError(f"protein ID outside 1..{output_count}: {protein_id}")
        if protein_id in result:
            raise ResCNN004A2DataError(f"duplicate/contradictory protein label: {protein_id}")
        result[protein_id] = 0 if match.group(1) == "-" else 1
    return result


def _targets_masks(labels: Mapping[int, int], output_count: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    targets = [0] * output_count
    masks = [0] * output_count
    for protein_id, label in labels.items():
        targets[protein_id - 1] = label
        masks[protein_id - 1] = 1
    return tuple(targets), tuple(masks)


def canonical_content_sha256(
    *,
    sample_id: str,
    component_id: str,
    partition: str,
    base_codes: Sequence[int],
    targets: Sequence[int],
    masks: Sequence[int],
) -> str:
    digest = hashlib.sha256()
    for value in (sample_id, component_id, partition):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    for values in (base_codes, targets, masks):
        raw = bytes(values)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def aggregate_candidate_digest(candidates: Sequence[SampleCandidate]) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(candidates, key=lambda row: row.row_index):
        digest.update(candidate.sample_id.encode("ascii"))
        digest.update(bytes.fromhex(candidate.content_sha256))
    return digest.hexdigest()


def _rank(seed: int, *parts: object) -> int:
    payload = "\0".join(("task004a2-rank-v1", str(seed), *(str(part) for part in parts)))
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest(), "big")


class CoverageSampler:
    """Order-independent bounded quota plus filler selection."""

    def __init__(self, *, output_count: int, sample_size: int, seed: int):
        if output_count <= 0 or sample_size < output_count * 2:
            raise ResCNN004A2DataError("sample cannot cover every protein/class quota")
        self.output_count = output_count
        self.sample_size = sample_size
        self.seed = seed
        self._quota: dict[tuple[str, int, int], tuple[int, int, SampleCandidate]] = {}
        self._fillers: dict[str, list[tuple[int, int, str, SampleCandidate]]] = {
            partition: [] for partition in DEVELOPMENT_PARTITIONS
        }

    def observe(self, candidate: SampleCandidate, labels: Mapping[int, int]) -> None:
        if candidate.partition not in DEVELOPMENT_PARTITIONS:
            raise ResCNN004A2DataError("sampler received a non-development row")
        index = candidate.row_index
        filler_rank = _rank(self.seed, candidate.partition, "filler", candidate.sample_id)
        entry = (-filler_rank, -index, candidate.sample_id, candidate)
        heap = self._fillers[candidate.partition]
        if len(heap) < self.sample_size:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            heapq.heapreplace(heap, entry)
        for protein_id, label in labels.items():
            key = (candidate.partition, protein_id, label)
            rank = _rank(
                self.seed, candidate.partition, protein_id, label, candidate.sample_id,
            )
            current = self._quota.get(key)
            value = (rank, index, candidate)
            if current is None or value[:2] < current[:2]:
                self._quota[key] = value

    def finalize(self) -> dict[str, tuple[SampleCandidate, ...]]:
        expected = {
            (partition, protein_id, label)
            for partition in DEVELOPMENT_PARTITIONS
            for protein_id in range(1, self.output_count + 1)
            for label in (0, 1)
        }
        missing = sorted(expected - self._quota.keys())
        if missing:
            raise ResCNN004A2DataError(f"unsatisfied protein/class quotas: {missing[:5]!r}")
        selected: dict[str, dict[str, SampleCandidate]] = {
            partition: {} for partition in DEVELOPMENT_PARTITIONS
        }
        for (partition, _protein, _label), (_rank_value, _index, candidate) in self._quota.items():
            selected[partition][candidate.sample_id] = candidate
        for partition in DEVELOPMENT_PARTITIONS:
            fillers = sorted(
                (
                    (-neg_rank, -neg_index, sample_id, candidate)
                    for neg_rank, neg_index, sample_id, candidate in self._fillers[partition]
                ),
                key=lambda row: (row[0], row[1]),
            )
            for _rank_value, _index, _sample_id, candidate in fillers:
                if len(selected[partition]) >= self.sample_size:
                    break
                selected[partition].setdefault(candidate.sample_id, candidate)
            if len(selected[partition]) != self.sample_size:
                raise ResCNN004A2DataError(
                    f"{partition} selected {len(selected[partition])} rows; expected {self.sample_size}"
                )
        return {
            partition: tuple(sorted(rows.values(), key=lambda row: row.row_index))
            for partition, rows in selected.items()
        }


def _membership_rows(lines: Iterable[str]) -> Iterator[MembershipRow]:
    reader = csv.reader(lines, delimiter="\t")
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ResCNN004A2DataError("membership is empty") from exc
    if header != ["sample_id", "component_id", "partition"]:
        raise ResCNN004A2DataError(f"unexpected membership header: {header!r}")
    for row in reader:
        if len(row) != 3:
            raise ResCNN004A2DataError(f"malformed membership row: {row!r}")
        yield MembershipRow(*row)


def _csv_rows(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    reader = csv.reader(lines)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ResCNN004A2DataError("CSV is empty") from exc
    if header != ["sequence", "labels"]:
        raise ResCNN004A2DataError(f"unexpected CSV header: {header!r}")
    for row in reader:
        if len(row) != 2:
            raise ResCNN004A2DataError(f"malformed CSV row with {len(row)} columns")
        yield row[0], row[1]


def _fasta_rows(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    header: str | None = None
    sequence: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if line.startswith(">"):
            if header is not None:
                yield header, "".join(sequence)
            header = line[1:]
            sequence = []
        else:
            if header is None:
                raise ResCNN004A2DataError("FASTA sequence appeared before a header")
            sequence.append(line)
    if header is None:
        raise ResCNN004A2DataError("FASTA is empty")
    yield header, "".join(sequence)


def _validate_join_identity(index: int, member: MembershipRow, fasta_id: str) -> None:
    expected = f"row_{index}"
    if member.sample_id != expected or fasta_id != expected:
        raise ResCNN004A2DataError(
            f"lockstep ID mismatch at {index}: {member.sample_id!r}, {fasta_id!r}, expected {expected!r}"
        )
    if not member.component_id or member.partition not in PARTITIONS:
        raise ResCNN004A2DataError(f"invalid membership row for {expected}")


@dataclass(frozen=True)
class AuditResult:
    row_count: int
    component_count: int
    partition_rows: Mapping[str, int]
    counts: DevelopmentCounts
    selected: Mapping[str, tuple[SampleCandidate, ...]]
    selected_content_sha256: str
    access: Mapping[str, int | bool]


def audit_streams(
    membership_lines: Iterable[str],
    csv_lines: Iterable[str],
    fasta_lines: Iterable[str],
    *,
    width: int,
    output_count: int,
    sample_size: int,
    seed: int,
    expected_partition_rows: Mapping[str, int] | None = None,
    expected_component_count: int | None = None,
) -> AuditResult:
    counters = AccessCounters()
    counts = _CountAccumulator(output_count)
    sampler = CoverageSampler(output_count=output_count, sample_size=sample_size, seed=seed)
    partition_rows = {partition: 0 for partition in PARTITIONS}
    component_partitions: dict[str, str] = {}
    row_count = 0
    streams = zip_longest(
        _membership_rows(membership_lines), _csv_rows(csv_lines), _fasta_rows(fasta_lines),
        fillvalue=_MISSING,
    )
    for index, triple in enumerate(streams):
        member, csv_row, fasta_row = triple
        if any(value is _MISSING for value in triple):
            raise ResCNN004A2DataError("membership/CSV/FASTA row counts differ")
        assert isinstance(member, MembershipRow)
        assert isinstance(csv_row, tuple) and isinstance(fasta_row, tuple)
        fasta_id, raw_fasta_sequence = fasta_row
        _validate_join_identity(index, member, fasta_id)
        prior = component_partitions.setdefault(member.component_id, member.partition)
        if prior != member.partition:
            raise ResCNN004A2DataError(f"component {member.component_id} crosses partitions")
        partition_rows[member.partition] += 1
        row_count += 1
        if member.partition == "test":
            counters.test_rows_seen += 1
            continue

        raw_bits, raw_labels = csv_row
        labels = _parse_labels_primary(raw_labels, output_count)
        decoded, codes = decode_one_hot_bits(raw_bits, width=width)
        fasta_codes = encode_fasta_sequence(raw_fasta_sequence, width=width)
        if decoded != raw_fasta_sequence or tuple(codes) != tuple(fasta_codes):
            raise ResCNN004A2DataError(f"CSV/FASTA sequence mismatch for {member.sample_id}")
        targets, masks = _targets_masks(labels, output_count)
        counts.add(member.partition, labels)
        content = canonical_content_sha256(
            sample_id=member.sample_id,
            component_id=member.component_id,
            partition=member.partition,
            base_codes=codes,
            targets=targets,
            masks=masks,
        )
        sampler.observe(
            SampleCandidate(member.sample_id, member.component_id, member.partition, content),
            labels,
        )
    counters.require_blind()
    if expected_partition_rows is not None and partition_rows != dict(expected_partition_rows):
        raise ResCNN004A2DataError(
            f"partition row counts drift: {partition_rows!r} != {dict(expected_partition_rows)!r}"
        )
    if expected_component_count is not None and len(component_partitions) != expected_component_count:
        raise ResCNN004A2DataError(
            f"component count {len(component_partitions)} != {expected_component_count}"
        )
    selected = sampler.finalize()
    all_selected = tuple(selected["train"] + selected["validation"])
    return AuditResult(
        row_count=row_count,
        component_count=len(component_partitions),
        partition_rows=partition_rows,
        counts=counts.freeze(),
        selected=selected,
        selected_content_sha256=aggregate_candidate_digest(all_selected),
        access=counters.as_dict(),
    )


@dataclass(frozen=True)
class CacheRecord:
    sample_id: str
    component_id: str
    partition: str
    base_codes: tuple[int, ...]
    targets: tuple[int, ...]
    masks: tuple[int, ...]
    content_sha256: str


class CompactSampleCache(Dataset):
    def __init__(self, records: Sequence[CacheRecord]):
        if not records:
            raise ResCNN004A2DataError("compact cache cannot be empty")
        self.sample_ids = tuple(record.sample_id for record in records)
        self.component_ids = tuple(record.component_id for record in records)
        self.partitions = tuple(record.partition for record in records)
        self.content_sha256 = tuple(record.content_sha256 for record in records)
        self.base_codes = torch.tensor([record.base_codes for record in records], dtype=torch.uint8)
        self.targets = torch.tensor([record.targets for record in records], dtype=torch.uint8)
        self.masks = torch.tensor([record.masks for record in records], dtype=torch.uint8)
        if any(partition == "test" for partition in self.partitions):
            raise ResCNN004A2DataError("test row entered compact cache")

    def __len__(self) -> int:
        return len(self.sample_ids)

    def __getitem__(self, index: int):
        sequence = F.one_hot(self.base_codes[index].long(), num_classes=4).to(torch.float32)
        return sequence, self.targets[index].to(torch.float32), self.masks[index].to(torch.float32)

    def indices(self, partition: str) -> tuple[int, ...]:
        if partition not in DEVELOPMENT_PARTITIONS:
            raise ResCNN004A2DataError("cache partition must be train or validation")
        return tuple(index for index, value in enumerate(self.partitions) if value == partition)

    def retained_bytes(self) -> int:
        return sum(tensor.numel() * tensor.element_size() for tensor in (
            self.base_codes, self.targets, self.masks,
        ))


@dataclass(frozen=True)
class CacheBuildResult:
    cache: CompactSampleCache
    counts: DevelopmentCounts
    selected_content_sha256: str
    access: Mapping[str, int | bool]


def build_cache_streams(
    membership_lines: Iterable[str],
    csv_lines: Iterable[str],
    fasta_lines: Iterable[str],
    *,
    selected: Mapping[str, Sequence[SampleCandidate]],
    width: int,
    output_count: int,
) -> CacheBuildResult:
    expected = {
        candidate.sample_id: candidate
        for partition in DEVELOPMENT_PARTITIONS
        for candidate in selected[partition]
    }
    if len(expected) != sum(len(selected[p]) for p in DEVELOPMENT_PARTITIONS):
        raise ResCNN004A2DataError("selected IDs are duplicated across partitions")
    counters = AccessCounters()
    counts = _CountAccumulator(output_count)
    records: list[CacheRecord] = []
    streams = zip_longest(
        _membership_rows(membership_lines), _csv_rows(csv_lines), _fasta_rows(fasta_lines),
        fillvalue=_MISSING,
    )
    for index, triple in enumerate(streams):
        member, csv_row, fasta_row = triple
        if any(value is _MISSING for value in triple):
            raise ResCNN004A2DataError("membership/CSV/FASTA row counts differ on cache pass")
        assert isinstance(member, MembershipRow)
        assert isinstance(csv_row, tuple) and isinstance(fasta_row, tuple)
        fasta_id, raw_fasta_sequence = fasta_row
        _validate_join_identity(index, member, fasta_id)
        if member.partition == "test":
            counters.test_rows_seen += 1
            continue
        raw_bits, raw_labels = csv_row
        labels = _parse_labels_independent(raw_labels, output_count)
        counts.add(member.partition, labels)
        candidate = expected.get(member.sample_id)
        if candidate is None:
            continue
        if candidate.partition != member.partition or candidate.component_id != member.component_id:
            raise ResCNN004A2DataError(f"selected membership drift for {member.sample_id}")
        decoded, codes = decode_one_hot_bits(raw_bits, width=width)
        fasta_codes = encode_fasta_sequence(raw_fasta_sequence, width=width)
        if decoded != raw_fasta_sequence or tuple(codes) != tuple(fasta_codes):
            raise ResCNN004A2DataError(f"CSV/FASTA sequence mismatch for {member.sample_id}")
        targets, masks = _targets_masks(labels, output_count)
        content = canonical_content_sha256(
            sample_id=member.sample_id,
            component_id=member.component_id,
            partition=member.partition,
            base_codes=codes,
            targets=targets,
            masks=masks,
        )
        if content != candidate.content_sha256:
            raise ResCNN004A2DataError(f"Gate A/Gate B content drift for {member.sample_id}")
        records.append(CacheRecord(
            member.sample_id, member.component_id, member.partition,
            tuple(codes), targets, masks, content,
        ))
    counters.require_blind()
    if {record.sample_id for record in records} != set(expected):
        missing = sorted(set(expected) - {record.sample_id for record in records})[:5]
        raise ResCNN004A2DataError(f"selected rows missing from cache pass: {missing!r}")
    records.sort(key=lambda row: int(row.sample_id.removeprefix("row_")))
    candidates = tuple(
        SampleCandidate(row.sample_id, row.component_id, row.partition, row.content_sha256)
        for row in records
    )
    cache_digest = aggregate_candidate_digest(candidates)
    expected_digest = aggregate_candidate_digest(tuple(expected.values()))
    if cache_digest != expected_digest:
        raise ResCNN004A2DataError("Gate A/Gate B aggregate content digest mismatch")
    return CacheBuildResult(
        cache=CompactSampleCache(records),
        counts=counts.freeze(),
        selected_content_sha256=cache_digest,
        access=counters.as_dict(),
    )


def require_count_reconciliation(
    gate_a: DevelopmentCounts,
    gate_b: DevelopmentCounts,
    *,
    expected_bounds: Mapping[str, int] | None = None,
) -> None:
    if gate_a.matrix() != gate_b.matrix():
        raise ResCNN004A2DataError("independent train/validation count matrices differ")
    if expected_bounds is not None and gate_a.combined_bounds() != dict(expected_bounds):
        raise ResCNN004A2DataError(
            f"development-only count bounds drift: {gate_a.combined_bounds()!r}"
        )
