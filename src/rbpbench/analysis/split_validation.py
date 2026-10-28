"""Core calculations for the Task 003A split-validation report.

The functions in this module are deliberately independent of plotting.  Every
figure is rendered from versioned tables produced here, so captions and plots
cannot silently drift away from the numerical source of truth.
"""

from __future__ import annotations

from array import array
from collections import Counter
from dataclasses import dataclass
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator, Mapping, Sequence, TextIO
import zipfile


ROW_COUNT = 361_180
PARTITIONS = ("train", "validation", "test")
PARTITION_CODE = {name: i for i, name in enumerate(PARTITIONS)}
TARGET_FRACTION = {"train": 0.70, "validation": 0.15, "test": 0.15}
WIDTHS = (500, 251, 101)
SMD_NOTABLE_THRESHOLD = 0.10


class ValidationError(RuntimeError):
    """Accepted evidence or a derived reconciliation failed closed."""


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_file(path: Path, *, size: int | None = None, sha256: str | None = None) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ValidationError(f"required file is missing: {path}")
    actual_size = path.stat().st_size
    if size is not None and actual_size != size:
        raise ValidationError(f"{path} is {actual_size} bytes; expected {size}")
    actual_hash = sha256_file(path)
    if sha256 is not None and actual_hash != sha256:
        raise ValidationError(f"{path} SHA-256 {actual_hash}; expected {sha256}")
    return {"path": str(path), "byte_size": actual_size, "sha256": actual_hash}


def parse_row_id(sample_id: str, *, row_count: int = ROW_COUNT) -> int:
    if not sample_id.startswith("row_") or not sample_id[4:].isdigit():
        raise ValidationError(f"non-canonical sample ID: {sample_id!r}")
    index = int(sample_id[4:])
    if index < 0 or index >= row_count or sample_id != f"row_{index}":
        raise ValidationError(f"sample ID outside canonical universe: {sample_id!r}")
    return index


def parse_labels(raw: str, *, protein_count: int = 122) -> dict[int, int]:
    """Parse the frozen label grammar: unsigned/+k positive, -k negative."""
    result: dict[int, int] = {}
    if not raw.strip():
        return result
    for token in raw.split(";"):
        token = token.strip()
        if not token:
            raise ValidationError(f"empty token in labels field {raw!r}")
        sign = -1 if token.startswith("-") else 1
        digits = token[1:] if token[:1] in "+-" else token
        if not digits.isdigit():
            raise ValidationError(f"malformed label token {token!r}")
        protein_id = int(digits)
        if not 1 <= protein_id <= protein_count:
            raise ValidationError(f"protein ID out of range in token {token!r}")
        if protein_id in result:
            raise ValidationError(f"duplicate/contradictory protein {protein_id} in {raw!r}")
        result[protein_id] = sign
    return result


@dataclass
class Membership:
    row_component: array
    component_sizes: list[int]
    component_ids: list[str]
    row_partition: bytearray | None = None

    @property
    def component_count(self) -> int:
        return len(self.component_sizes)


def _read_membership_rows(lines: Iterable[str], *, with_partition: bool, row_count: int = ROW_COUNT) -> Membership:
    iterator = iter(lines)
    expected_header = "sample_id\tcomponent_id\tpartition" if with_partition else "sample_id\tcomponent_id"
    try:
        header = next(iterator).rstrip("\r\n")
    except StopIteration as exc:
        raise ValidationError("membership is empty") from exc
    if header != expected_header:
        raise ValidationError(f"membership header {header!r}; expected {expected_header!r}")

    sentinel = 0xFFFFFFFF
    row_component = array("I", [sentinel]) * row_count
    row_partition = bytearray([255]) * row_count if with_partition else None
    component_index: dict[str, int] = {}
    component_ids: list[str] = []
    component_sizes: list[int] = []
    seen = 0
    for line_number, line in enumerate(iterator, 2):
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) != (3 if with_partition else 2):
            raise ValidationError(f"membership line {line_number} has {len(fields)} fields")
        row = parse_row_id(fields[0], row_count=row_count)
        if row_component[row] != sentinel:
            raise ValidationError(f"duplicate membership row {fields[0]}")
        component_id = fields[1]
        if len(component_id) != 64 or any(ch not in "0123456789abcdef" for ch in component_id):
            raise ValidationError(f"invalid component ID on line {line_number}")
        comp = component_index.get(component_id)
        if comp is None:
            comp = len(component_ids)
            component_index[component_id] = comp
            component_ids.append(component_id)
            component_sizes.append(0)
        row_component[row] = comp
        component_sizes[comp] += 1
        if with_partition:
            partition = fields[2]
            if partition not in PARTITION_CODE:
                raise ValidationError(f"unknown partition {partition!r}")
            row_partition[row] = PARTITION_CODE[partition]
        seen += 1
    if seen != row_count or any(value == sentinel for value in row_component):
        raise ValidationError(f"membership contains {seen} rows; expected {row_count}")
    if with_partition and any(value == 255 for value in row_partition):
        raise ValidationError("membership has unassigned rows")
    return Membership(row_component, component_sizes, component_ids, row_partition)


def read_gzip_membership(path: Path, *, with_partition: bool = False) -> Membership:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return _read_membership_rows(handle, with_partition=with_partition)


def read_zip_membership(archive: zipfile.ZipFile, member: str, *, with_partition: bool = True) -> Membership:
    with archive.open(member) as raw, gzip.open(raw, "rt", encoding="utf-8", newline="") as handle:
        return _read_membership_rows(handle, with_partition=with_partition)


def verify_component_partition_integrity(membership: Membership) -> dict:
    if membership.row_partition is None:
        raise ValidationError("partition integrity requires partition membership")
    component_partition = bytearray([255]) * membership.component_count
    split_components: set[int] = set()
    partition_rows = Counter()
    for row, comp in enumerate(membership.row_component):
        part = membership.row_partition[row]
        partition_rows[PARTITIONS[part]] += 1
        prior = component_partition[comp]
        if prior == 255:
            component_partition[comp] = part
        elif prior != part:
            split_components.add(comp)
    return {
        "partition_rows": dict(partition_rows),
        "split_component_count": len(split_components),
        "component_count": membership.component_count,
    }


def component_distribution(sizes: Sequence[int], grouping: str) -> list[dict]:
    counts = Counter(int(size) for size in sizes)
    running_components = 0
    running_rows = 0
    rows: list[dict] = []
    total_components = len(sizes)
    total_rows = sum(sizes)
    for size in sorted(counts, reverse=True):
        count = counts[size]
        running_components += count
        running_rows += size * count
        rows.append(
            {
                "grouping": grouping,
                "component_size": size,
                "component_count": count,
                "row_count": size * count,
                "components_ge_size": running_components,
                "rows_ge_size": running_rows,
                "component_fraction_ge_size": running_components / total_components,
                "row_fraction_ge_size": running_rows / total_rows,
            }
        )
    rows.reverse()
    return rows


def crossing_report(membership: Membership, fold_codes: bytearray) -> dict:
    """Crossing report for fold code 0=train, 1=holdout."""
    if len(fold_codes) != len(membership.row_component):
        raise ValidationError("legacy fold length mismatch")
    comp_mask = bytearray(membership.component_count)
    for row, comp in enumerate(membership.row_component):
        code = fold_codes[row]
        if code not in (0, 1):
            raise ValidationError(f"invalid legacy fold code {code}")
        comp_mask[comp] |= 1 << code
    crossing = sum(mask == 3 for mask in comp_mask)
    holdout_represented = sum(mask & 2 != 0 for mask in comp_mask)
    affected_train = 0
    affected_holdout = 0
    for row, comp in enumerate(membership.row_component):
        if comp_mask[comp] == 3:
            if fold_codes[row] == 0:
                affected_train += 1
            else:
                affected_holdout += 1
    train_total = fold_codes.count(0)
    holdout_total = fold_codes.count(1)
    return {
        "total_components": membership.component_count,
        "components_represented_in_holdout": holdout_represented,
        "crossing_component_count": crossing,
        "crossing_component_rate_over_holdout_components": crossing / holdout_represented,
        "crossing_holdout_row_count": affected_holdout,
        "holdout_count": holdout_total,
        "crossing_holdout_row_rate": affected_holdout / holdout_total,
        "crossing_train_row_count": affected_train,
        "train_count": train_total,
        "crossing_train_row_rate": affected_train / train_total,
    }


def read_fold_codes(path: Path) -> tuple[bytearray, dict]:
    metadata_path = path.with_suffix(".json")
    if not metadata_path.is_file():
        raise ValidationError(f"legacy-fold metadata missing: {metadata_path}")
    metadata = json.loads(metadata_path.read_text())
    codes = bytearray([255]) * ROW_COUNT
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != ["sample_id", "legacy_partition"]:
            raise ValidationError("legacy-fold TSV header mismatch")
        for row in reader:
            index = parse_row_id(row["sample_id"])
            if codes[index] != 255:
                raise ValidationError(f"duplicate legacy fold row {row['sample_id']}")
            value = row["legacy_partition"]
            if value not in ("train", "holdout"):
                raise ValidationError(f"invalid legacy fold value {value!r}")
            codes[index] = 0 if value == "train" else 1
    if any(value == 255 for value in codes):
        raise ValidationError("legacy fold is incomplete")
    return codes, metadata


def encoded_edge(a: str, b: str) -> int | None:
    ia, ib = parse_row_id(a), parse_row_id(b)
    if ia == ib:
        return None
    if ia > ib:
        ia, ib = ib, ia
    return (ia << 20) | ib


def read_edge_set_from_zip(archive: zipfile.ZipFile, member: str) -> set[int]:
    result: set[int] = set()
    with archive.open(member) as raw, gzip.open(raw, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 2:
                raise ValidationError(f"edge line {line_number} in {member} is malformed")
            edge = encoded_edge(fields[0], fields[1])
            if edge is None:
                raise ValidationError(f"self-edge in normalized edge file {member}")
            if edge in result:
                raise ValidationError(f"duplicate edge in normalized edge file {member}")
            result.add(edge)
    return result


def edge_overlap_counts(edge_sets: Mapping[int, set[int]]) -> list[dict]:
    if set(edge_sets) != set(WIDTHS):
        raise ValidationError("edge overlap requires exactly 500/251/101 sets")
    sets = [edge_sets[500], edge_sets[251], edge_sets[101]]
    counts = Counter()
    for edge in sets[0]:
        mask = 1 | (2 if edge in sets[1] else 0) | (4 if edge in sets[2] else 0)
        counts[mask] += 1
    for edge in sets[1]:
        if edge not in sets[0]:
            counts[2 | (4 if edge in sets[2] else 0)] += 1
    for edge in sets[2]:
        if edge not in sets[0] and edge not in sets[1]:
            counts[4] += 1
    labels = {1: "500 only", 2: "251 only", 4: "101 only", 3: "500 & 251", 5: "500 & 101", 6: "251 & 101", 7: "all three"}
    return [
        {
            "mask": mask,
            "widths": ",".join(str(width) for bit, width in zip((1, 2, 4), WIDTHS) if mask & bit),
            "category": labels[mask],
            "edge_count": counts[mask],
        }
        for mask in range(1, 8)
    ]


def read_proteins(path: Path) -> dict[int, str]:
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        result = {int(row["protein_id"]): row["protein_name"] for row in reader}
    if set(result) != set(range(1, 123)):
        raise ValidationError("protein registry does not contain IDs 1..122 exactly")
    return result


def balance_cell(count: int, total: int, partition: str) -> tuple[float, float, bool]:
    """Return fraction, percentage-point deviation, and strict >3-pp flag."""
    if partition not in TARGET_FRACTION:
        raise ValidationError(f"unknown partition {partition!r}")
    if total <= 0 or count < 0 or count > total:
        raise ValidationError(f"invalid balance cell count={count}, total={total}")
    fraction = count / total
    deviation_pp = 100 * (fraction - TARGET_FRACTION[partition])
    return fraction, deviation_pp, abs(deviation_pp) > 3.0


def stream_label_counts(csv_path: Path, row_partition: bytearray, proteins: Mapping[int, str]) -> tuple[list[dict], dict]:
    counts = [[[0, 0] for _ in range(123)] for _ in PARTITIONS]
    with Path(csv_path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["sequence", "labels"]:
            raise ValidationError(f"unexpected CSV header: {reader.fieldnames}")
        row_count = 0
        for row_index, row in enumerate(reader):
            if row_index >= ROW_COUNT:
                raise ValidationError("CSV has more rows than expected")
            partition = row_partition[row_index]
            for protein_id, sign in parse_labels(row["labels"]).items():
                counts[partition][protein_id][0 if sign > 0 else 1] += 1
            row_count += 1
    if row_count != ROW_COUNT:
        raise ValidationError(f"CSV has {row_count} rows; expected {ROW_COUNT}")

    rows: list[dict] = []
    flagged_cells = 0
    flagged_eval_cells = 0
    flagged_proteins: set[int] = set()
    flagged_eval_proteins: set[int] = set()
    minima = {"positive": (10**9, None, None), "negative": (10**9, None, None)}
    for protein_id in range(1, 123):
        for class_index, label_class in enumerate(("positive", "negative")):
            total = sum(counts[p][protein_id][class_index] for p in range(3))
            if total <= 0:
                raise ValidationError(f"protein {protein_id} has no known {label_class}s")
            for partition_index, partition in enumerate(PARTITIONS):
                count = counts[partition_index][protein_id][class_index]
                fraction, deviation_pp, flagged = balance_cell(count, total, partition)
                if flagged:
                    flagged_cells += 1
                    flagged_proteins.add(protein_id)
                    if partition != "train":
                        flagged_eval_cells += 1
                        flagged_eval_proteins.add(protein_id)
                # Preserve the accepted deterministic tie-break: later
                # evaluation partition order (test after validation) wins.
                if partition != "train" and count <= minima[label_class][0]:
                    minima[label_class] = (count, protein_id, partition)
                rows.append(
                    {
                        "protein_id": protein_id,
                        "protein_name": proteins[protein_id],
                        "label_class": label_class,
                        "partition": partition,
                        "count": count,
                        "protein_class_total": total,
                        "fraction": fraction,
                        "target_fraction": TARGET_FRACTION[partition],
                        "deviation_percentage_points": deviation_pp,
                        "flagged_gt_3pp": flagged,
                    }
                )
    summary = {
        "threshold_percentage_points": 3.0,
        "proteins_flagged_any_partition": len(flagged_proteins),
        "cells_flagged_any_partition": flagged_cells,
        "proteins_flagged_validation_or_test": len(flagged_eval_proteins),
        "cells_flagged_validation_or_test": flagged_eval_cells,
        "minimum_known_positive": {"count": minima["positive"][0], "protein_id": minima["positive"][1], "partition": minima["positive"][2]},
        "minimum_known_negative": {"count": minima["negative"][0], "protein_id": minima["negative"][1], "partition": minima["negative"][2]},
    }
    return rows, summary


def summarize_protein_balance(rows: Sequence[Mapping]) -> list[dict]:
    grouped: dict[int, list[Mapping]] = {}
    for row in rows:
        grouped.setdefault(int(row["protein_id"]), []).append(row)
    result = []
    for protein_id in sorted(grouped):
        items = grouped[protein_id]
        result.append(
            {
                "protein_id": protein_id,
                "protein_name": items[0]["protein_name"],
                "max_abs_deviation_pp_all": max(abs(float(r["deviation_percentage_points"])) for r in items),
                "max_abs_deviation_pp_evaluation": max(abs(float(r["deviation_percentage_points"])) for r in items if r["partition"] != "train"),
                "positive_total": next(int(r["protein_class_total"]) for r in items if r["label_class"] == "positive"),
                "negative_total": next(int(r["protein_class_total"]) for r in items if r["label_class"] == "negative"),
                "flagged_any": any(bool(r["flagged_gt_3pp"]) for r in items),
                "flagged_evaluation": any(bool(r["flagged_gt_3pp"]) for r in items if r["partition"] != "train"),
            }
        )
    return result


def sequence_metrics(sequence: str) -> tuple[float, float, int]:
    sequence = sequence.strip().upper()
    if not sequence or any(base not in "ACGT" for base in sequence):
        raise ValidationError("sequence is empty or contains non-ACGT symbols")
    length = len(sequence)
    counts = [sequence.count(base) for base in "ACGT"]
    gc_fraction = (counts[1] + counts[2]) / length
    entropy = -sum((count / length) * math.log2(count / length) for count in counts if count) / 2.0
    longest = 1
    run = 1
    previous = sequence[0]
    for base in sequence[1:]:
        if base == previous:
            run += 1
            if run > longest:
                longest = run
        else:
            previous = base
            run = 1
    return gc_fraction, entropy, longest


def strict_fasta_records(handle: TextIO, *, width: int) -> Iterator[tuple[int, str]]:
    sample_id: str | None = None
    pieces: list[str] = []
    for line_number, line in enumerate(handle, 1):
        line = line.rstrip("\r\n")
        if line.startswith(">"):
            if sample_id is not None:
                sequence = "".join(pieces)
                if len(sequence) != width:
                    raise ValidationError(f"{sample_id} has length {len(sequence)}; expected {width}")
                yield parse_row_id(sample_id), sequence
            sample_id = line[1:]
            if not sample_id or any(ch.isspace() for ch in sample_id):
                raise ValidationError(f"invalid FASTA header at line {line_number}")
            pieces = []
        else:
            if sample_id is None:
                raise ValidationError("FASTA sequence appears before first header")
            pieces.append(line)
    if sample_id is not None:
        sequence = "".join(pieces)
        if len(sequence) != width:
            raise ValidationError(f"{sample_id} has length {len(sequence)}; expected {width}")
        yield parse_row_id(sample_id), sequence


def ks_distance(x, y) -> float:
    """Two-sample KS D without an inferential p-value."""
    import numpy as np

    x = np.sort(np.asarray(x, dtype=float))
    y = np.sort(np.asarray(y, dtype=float))
    if not len(x) or not len(y):
        raise ValidationError("KS distance requires non-empty samples")
    values = np.concatenate((x, y))
    cdf_x = np.searchsorted(x, values, side="right") / len(x)
    cdf_y = np.searchsorted(y, values, side="right") / len(y)
    return float(np.max(np.abs(cdf_x - cdf_y)))


def standardized_mean_difference(x, y) -> float:
    import numpy as np

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    variance = ((len(x) - 1) * x.var(ddof=1) + (len(y) - 1) * y.var(ddof=1)) / (len(x) + len(y) - 2)
    pooled = math.sqrt(float(variance))
    if pooled == 0:
        return 0.0 if float(x.mean()) == float(y.mean()) else math.copysign(math.inf, float(x.mean() - y.mean()))
    return float((x.mean() - y.mean()) / pooled)


def summarize_values(values, *, width: int, partition: str, metric: str) -> dict:
    import numpy as np

    values = np.asarray(values, dtype=float)
    quantiles = np.quantile(values, [0.05, 0.25, 0.5, 0.75, 0.95])
    return {
        "width": width,
        "partition": partition,
        "metric": metric,
        "n": len(values),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=1)),
        "minimum": float(values.min()),
        "q05": float(quantiles[0]),
        "q25": float(quantiles[1]),
        "median": float(quantiles[2]),
        "q75": float(quantiles[3]),
        "q95": float(quantiles[4]),
        "maximum": float(values.max()),
    }


def composition_analysis(fasta_path: Path, *, width: int, row_partition: bytearray) -> tuple[list[dict], list[dict]]:
    import numpy as np

    metrics = np.empty((ROW_COUNT, 3), dtype=np.float32)
    seen = np.zeros(ROW_COUNT, dtype=np.bool_)
    with Path(fasta_path).open("rt", encoding="utf-8", newline="") as handle:
        for row, sequence in strict_fasta_records(handle, width=width):
            if seen[row]:
                raise ValidationError(f"duplicate FASTA ID row_{row}")
            metrics[row] = sequence_metrics(sequence)
            seen[row] = True
    if not bool(seen.all()):
        raise ValidationError(f"width-{width} FASTA does not contain all canonical rows")
    partition_codes = np.frombuffer(row_partition, dtype=np.uint8)
    names = ("gc_fraction", "normalized_entropy", "max_homopolymer")
    by_partition: dict[tuple[str, str], object] = {}
    summaries: list[dict] = []
    for partition_index, partition in enumerate(PARTITIONS):
        mask = partition_codes == partition_index
        for metric_index, metric in enumerate(names):
            values = metrics[mask, metric_index]
            by_partition[(partition, metric)] = values
            summaries.append(summarize_values(values, width=width, partition=partition, metric=metric))
    effects: list[dict] = []
    for metric in names:
        for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
            x = by_partition[(left, metric)]
            y = by_partition[(right, metric)]
            smd = standardized_mean_difference(x, y)
            qx = np.quantile(x, [0.25, 0.5, 0.75])
            qy = np.quantile(y, [0.25, 0.5, 0.75])
            effects.append(
                {
                    "width": width,
                    "metric": metric,
                    "partition_a": left,
                    "partition_b": right,
                    "standardized_mean_difference": smd,
                    "absolute_smd": abs(smd),
                    "smd_interpretation": "notable" if abs(smd) >= SMD_NOTABLE_THRESHOLD else "negligible",
                    "ks_d": ks_distance(x, y),
                    "median_difference": float(qx[1] - qy[1]),
                    "iqr_a": float(qx[2] - qx[0]),
                    "iqr_b": float(qy[2] - qy[0]),
                }
            )
    return summaries, effects


def write_tsv(path: Path, rows: Sequence[Mapping], fieldnames: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        if not rows:
            raise ValidationError(f"cannot infer TSV schema for empty table {path}")
        fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def verify_return_archive(path: Path, *, expected_size: int, expected_sha256: str, sidecar: Path) -> tuple[zipfile.ZipFile, str, dict]:
    require_file(path, size=expected_size, sha256=expected_sha256)
    sidecar_text = Path(sidecar).read_text().strip().split()
    if not sidecar_text or sidecar_text[0] != expected_sha256:
        raise ValidationError("production return sidecar does not match the frozen archive hash")
    archive = zipfile.ZipFile(path)
    names = archive.namelist()
    roots = {name.split("/", 1)[0] for name in names if "/" in name}
    if len(roots) != 1:
        archive.close()
        raise ValidationError("return archive does not have exactly one root directory")
    root = next(iter(roots))
    manifest = json.loads(archive.read(f"{root}/RETURN_MANIFEST.json"))
    if manifest.get("status") != "SUCCESS" or manifest.get("stop_class") != "SUCCESS":
        archive.close()
        raise ValidationError("production return is not terminal SUCCESS")
    inventory = json.loads(archive.read(f"{root}/RETURN_INVENTORY.json"))
    inventory_paths: set[str] = set()
    for item in inventory.get("entries", []):
        rel = item["path"]
        if rel in inventory_paths or rel.startswith("/") or ".." in Path(rel).parts:
            archive.close()
            raise ValidationError(f"unsafe or duplicate return inventory path {rel!r}")
        inventory_paths.add(rel)
        data = archive.read(f"{root}/{rel}")
        if len(data) != item["byte_size"] or sha256_bytes(data) != item["sha256"]:
            archive.close()
            raise ValidationError(f"return inventory mismatch for {rel}")
    actual_relative = {
        name[len(root) + 1 :]
        for name in names
        if name.startswith(root + "/") and not name.endswith("/")
    }
    unlisted = actual_relative - inventory_paths - {"RETURN_INVENTORY.json", "CHECKSUMS.sha256"}
    if unlisted:
        archive.close()
        raise ValidationError(f"return archive contains unlisted files: {sorted(unlisted)[:5]}")
    status_bytes = archive.read(f"{root}/STATUS.json")
    if manifest.get("status_sha256") != sha256_bytes(status_bytes):
        archive.close()
        raise ValidationError("return-series manifest does not bind STATUS.json")
    if manifest.get("return_index") != 1 or manifest.get("predecessor") is not None:
        archive.close()
        raise ValidationError("unexpected return-series position/predecessor")
    checksum_rows = archive.read(f"{root}/CHECKSUMS.sha256").decode().splitlines()
    checksum_map = {}
    for line in checksum_rows:
        digest, rel = line.split(maxsplit=1)
        checksum_map[rel.lstrip("* ")] = digest
    for rel in inventory_paths:
        if checksum_map.get(rel) != sha256_bytes(archive.read(f"{root}/{rel}")):
            archive.close()
            raise ValidationError(f"CHECKSUMS.sha256 mismatch for {rel}")
    final_member = f"{root}/final/membership.tsv.gz"
    final_hash = sha256_bytes(archive.read(final_member))
    if final_hash != "ca527da4f0c0615bcb9d31c6fc705523238e8fb8f4751473ccc2af3ee0aecddb":
        archive.close()
        raise ValidationError("final membership hash mismatch")
    return archive, root, inventory
