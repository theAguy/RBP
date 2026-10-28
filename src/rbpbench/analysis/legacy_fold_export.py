"""Reproduce the former notebook fold in its pinned legacy environment.

The row-level export is scratch evidence for Task 003A and is deliberately not
included in the sanitized final report package.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

from rbpbench.analysis.split_validation import ROW_COUNT, parse_labels
from rbpbench.splits.legacy_diagnostic import require_pinned_versions, run_legacy_fold


PINNED = {
    "python_version": "3.12",
    "numpy_version": "2.0.2",
    "scipy_version": "1.16.1",
    "scikit_learn_version": "1.6.1",
    "iterative_stratification_version": "0.1.9",
}
EXPECTED_TRAIN_DIGEST = "61dc839539f47be30380059036cb803388fdb282f50b5f983d4e60109bfbd611"
EXPECTED_HOLDOUT_DIGEST = "6ee6917ac3e1fad42563a7317e39e9c3988ce9256543ef29fb481a4855bd8e6c"


def export_fold(csv_path: Path, output_tsv_gz: Path) -> dict:
    labels = []
    with Path(csv_path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["sequence", "labels"]:
            raise RuntimeError(f"unexpected CSV header: {reader.fieldnames}")
        for row in reader:
            labels.append(parse_labels(row["labels"]))
    if len(labels) != ROW_COUNT:
        raise RuntimeError(f"CSV contains {len(labels)} rows; expected {ROW_COUNT}")
    result = run_legacy_fold(labels, protein_ids=range(1, 123))
    require_pinned_versions(result.dependency_versions, expected=PINNED)
    if result.train_digest != EXPECTED_TRAIN_DIGEST or result.holdout_digest != EXPECTED_HOLDOUT_DIGEST:
        raise RuntimeError("legacy fold index digests do not reproduce the accepted evidence")

    fold = bytearray([255]) * ROW_COUNT
    for index in result.train_indices:
        fold[index] = 0
    for index in result.holdout_indices:
        if fold[index] != 255:
            raise RuntimeError(f"row_{index} appears in both legacy partitions")
        fold[index] = 1
    if any(code == 255 for code in fold):
        raise RuntimeError("legacy fold is incomplete")
    output_tsv_gz.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_tsv_gz, "wt", encoding="utf-8", newline="") as handle:
        handle.write("sample_id\tlegacy_partition\n")
        for index, code in enumerate(fold):
            handle.write(f"row_{index}\t{'train' if code == 0 else 'holdout'}\n")
    metadata = result.to_dict()
    metadata.update({"status": "reproduced", "row_count": ROW_COUNT})
    output_tsv_gz.with_suffix(".json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    export_fold(args.csv, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
