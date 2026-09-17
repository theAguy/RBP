"""Stream and validate the sparse multi-label RBP dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable, Sequence


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_labels(raw: str, num_proteins: int) -> list[int]:
    labels: list[int] = []
    seen: set[int] = set()
    for token in raw.split(";"):
        token = token.strip()
        if not token:
            continue
        value = int(token)
        if value == 0 or abs(value) > num_proteins:
            raise ValueError(f"label {value} is outside ±1..±{num_proteins}")
        if abs(value) in seen:
            raise ValueError(f"protein {abs(value)} appears twice in one row")
        seen.add(abs(value))
        labels.append(value)
    return labels


def validate_one_hot(sequence: str, sequence_length: int, strict_groups: bool) -> None:
    expected = sequence_length * 4
    if len(sequence) != expected:
        raise ValueError(f"sequence has {len(sequence)} bits; expected {expected}")
    if sequence.count("1") != sequence_length or sequence.count("0") != expected - sequence_length:
        raise ValueError("sequence is not a valid one-hot bit vector")
    if strict_groups and any(sequence[i : i + 4].count("1") != 1 for i in range(0, expected, 4)):
        raise ValueError("a nucleotide group is not one-hot encoded")


def gc_fraction(sequence: str, start_nt: int, length_nt: int) -> float:
    start = start_nt * 4
    stop = (start_nt + length_nt) * 4
    window = sequence[start:stop]
    gc = window[1::4].count("1") + window[2::4].count("1")
    return gc / length_nt


def rank_auc(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    """AUROC via average ranks, including exact handling of tied scores."""
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None

    order = sorted(range(len(scores)), key=scores.__getitem__)
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and scores[order[j]] == scores[order[i]]:
            j += 1
        average_rank = (i + 1 + j) / 2.0
        for index in order[i:j]:
            ranks[index] = average_rank
        i = j

    positive_rank_sum = sum(rank for rank, label in zip(ranks, labels) if label == 1)
    return (positive_rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def mean(values: Iterable[float]) -> float | None:
    collected = list(values)
    return sum(collected) / len(collected) if collected else None


def audit_dataset(
    csv_path: Path,
    *,
    num_proteins: int = 122,
    sequence_length: int = 500,
    center_length: int = 101,
    strict_group_rows: int = 10_000,
) -> dict:
    positive_counts = [0] * num_proteins
    negative_counts = [0] * num_proteins
    labels_by_protein: list[list[int]] = [[] for _ in range(num_proteins)]
    gc500_by_protein: list[list[float]] = [[] for _ in range(num_proteins)]
    gc101_by_protein: list[list[float]] = [[] for _ in range(num_proteins)]
    positive_gc500: list[float] = []
    negative_gc500: list[float] = []
    positive_gc101: list[float] = []
    negative_gc101: list[float] = []
    row_count = 0
    known_label_count = 0
    multi_positive_rows = 0
    center_start = (sequence_length - center_length) // 2

    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["sequence", "labels"]:
            raise ValueError(f"unexpected CSV columns: {reader.fieldnames}")

        for row_index, row in enumerate(reader):
            sequence = row["sequence"]
            validate_one_hot(sequence, sequence_length, row_index < strict_group_rows)
            labels = parse_labels(row["labels"], num_proteins)
            gc500 = gc_fraction(sequence, 0, sequence_length)
            gc101 = gc_fraction(sequence, center_start, center_length)
            positive_in_row = 0

            for value in labels:
                protein_index = abs(value) - 1
                target = int(value > 0)
                labels_by_protein[protein_index].append(target)
                gc500_by_protein[protein_index].append(gc500)
                gc101_by_protein[protein_index].append(gc101)
                known_label_count += 1
                if target:
                    positive_counts[protein_index] += 1
                    positive_gc500.append(gc500)
                    positive_gc101.append(gc101)
                    positive_in_row += 1
                else:
                    negative_counts[protein_index] += 1
                    negative_gc500.append(gc500)
                    negative_gc101.append(gc101)

            if positive_in_row >= 2:
                multi_positive_rows += 1
            row_count += 1

    per_protein = []
    direct_auc_500 = []
    direct_auc_101 = []
    oriented_auc_500 = []
    oriented_auc_101 = []
    for index in range(num_proteins):
        auc500 = rank_auc(labels_by_protein[index], gc500_by_protein[index])
        auc101 = rank_auc(labels_by_protein[index], gc101_by_protein[index])
        if auc500 is not None:
            direct_auc_500.append(auc500)
            oriented_auc_500.append(max(auc500, 1.0 - auc500))
        if auc101 is not None:
            direct_auc_101.append(auc101)
            oriented_auc_101.append(max(auc101, 1.0 - auc101))
        per_protein.append(
            {
                "protein_id": index + 1,
                "positive_count": positive_counts[index],
                "negative_count": negative_counts[index],
                "known_count": positive_counts[index] + negative_counts[index],
                "direct_gc_auc_500": auc500,
                "direct_gc_auc_101": auc101,
            }
        )

    return {
        "schema_version": 1,
        "source": {
            "path": csv_path.name,
            "size_bytes": csv_path.stat().st_size,
            "sha256": sha256_file(csv_path),
        },
        "encoding": {
            "sequence_length_nt": sequence_length,
            "one_hot_order": "ACGT",
            "num_proteins": num_proteins,
            "center_window_length_nt": center_length,
            "center_window_start_zero_based": center_start,
        },
        "summary": {
            "rows": row_count,
            "known_labels": known_label_count,
            "mean_known_labels_per_row": known_label_count / row_count,
            "rows_with_at_least_two_positives": multi_positive_rows,
            "positive_labels": sum(positive_counts),
            "negative_labels": sum(negative_counts),
        },
        "gc_descriptive": {
            "mean_positive_gc_500": mean(positive_gc500),
            "mean_negative_gc_500": mean(negative_gc500),
            "mean_positive_gc_101": mean(positive_gc101),
            "mean_negative_gc_101": mean(negative_gc101),
            "macro_direct_gc_auc_500": mean(direct_auc_500),
            "macro_direct_gc_auc_101": mean(direct_auc_101),
            "macro_orientation_adjusted_gc_auc_500": mean(oriented_auc_500),
            "macro_orientation_adjusted_gc_auc_101": mean(oriented_auc_101),
        },
        "per_protein": per_protein,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True, help="Input sparse-label CSV")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON manifest")
    parser.add_argument("--num-proteins", type=int, default=122)
    parser.add_argument("--sequence-length", type=int, default=500)
    parser.add_argument("--center-length", type=int, default=101)
    parser.add_argument(
        "--strict-group-rows",
        type=int,
        default=10_000,
        help="Rows receiving the slower per-nucleotide one-hot group check",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = audit_dataset(
        args.csv,
        num_proteins=args.num_proteins,
        sequence_length=args.sequence_length,
        center_length=args.center_length,
        strict_group_rows=args.strict_group_rows,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
