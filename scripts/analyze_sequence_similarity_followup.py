#!/usr/bin/env python3
"""Independent follow-up audit of the accepted Task 002C similarity evidence.

This script does not rerun MMseqs2.  It re-reads the accepted normalized edge
sets and decoded FASTAs, then separates exact duplicates, exact reverse
complements, and exact shifted overlaps from the broader MMseqs2 relation.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import zipfile
from array import array
from collections import Counter, defaultdict
from pathlib import Path


UNIVERSE_SIZE = 361_180
WIDTHS = (500, 251, 101)
COVERAGE = {500: 0.80, 251: 0.95, 101: 0.95}
COMPLEMENT = str.maketrans("ACGT", "TGCA")


def reverse_complement(sequence: str) -> str:
    return sequence.translate(COMPLEMENT)[::-1]


def row_index(row_id: str) -> int:
    if not row_id.startswith("row_"):
        raise ValueError(f"non-canonical row ID: {row_id!r}")
    value = int(row_id[4:])
    if row_id != f"row_{value}" or not 0 <= value < UNIVERSE_SIZE:
        raise ValueError(f"non-canonical row ID: {row_id!r}")
    return value


def load_fasta(path: Path, width: int) -> list[str]:
    sequences: list[str] = []
    expected = 0
    current_id: str | None = None
    chunks: list[str] = []

    def finish() -> None:
        nonlocal expected, current_id, chunks
        if current_id is None:
            return
        if current_id != f"row_{expected}":
            raise ValueError(
                f"{path}: expected row_{expected}, found {current_id}"
            )
        sequence = "".join(chunks)
        if len(sequence) != width or set(sequence) - set("ACGT"):
            raise ValueError(f"{path}: invalid sequence for {current_id}")
        sequences.append(sequence)
        expected += 1

    with path.open() as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith(">"):
                finish()
                current_id = line[1:]
                chunks = []
            elif line:
                chunks.append(line)
    finish()
    if len(sequences) != UNIVERSE_SIZE:
        raise ValueError(f"{path}: expected {UNIVERSE_SIZE} rows")
    return sequences


def exact_sequence_summary(sequences: list[str]) -> dict[str, object]:
    first_by_sequence: dict[str, int] = {}
    forward_pairs: list[list[str]] = []
    for index, sequence in enumerate(sequences):
        previous = first_by_sequence.get(sequence)
        if previous is not None:
            forward_pairs.append([f"row_{previous}", f"row_{index}"])
        else:
            first_by_sequence[sequence] = index

    reverse_pairs: list[list[str]] = []
    for index, sequence in enumerate(sequences):
        partner = first_by_sequence.get(reverse_complement(sequence))
        if partner is not None and index < partner:
            reverse_pairs.append([f"row_{index}", f"row_{partner}"])

    return {
        "unique_forward_sequences": len(first_by_sequence),
        "forward_duplicate_pair_count": len(forward_pairs),
        "forward_duplicate_pairs": forward_pairs,
        "exact_reverse_complement_pair_count": len(reverse_pairs),
        "exact_reverse_complement_pairs": reverse_pairs,
    }


def exact_shift_offsets(
    a: str, b: str, minimum_overlap: int
) -> tuple[list[int], list[int]]:
    """Return exact shifted-overlap evidence in forward and RC orientations.

    This is deliberately a lower-bound diagnostic: it recognizes an exact
    ungapped overlap of at least the frozen minimum coverage, but does not try
    to reproduce MMseqs2's mismatched or gapped alignment.
    """

    forward: list[int] = []
    position = a.find(b[:minimum_overlap])
    if position >= 0:
        forward.append(position)
    position = b.find(a[:minimum_overlap])
    if position >= 0:
        forward.append(-position)
    rb = reverse_complement(b)
    reverse: list[int] = []
    position = a.find(rb[:minimum_overlap])
    if position >= 0:
        reverse.append(position)
    position = rb.find(a[:minimum_overlap])
    if position >= 0:
        reverse.append(-position)
    return forward, reverse


def edge_summary(
    archive: zipfile.ZipFile,
    root: str,
    width: int,
    sequences: list[str],
) -> tuple[dict[str, object], set[int]]:
    member = f"{root}/edges/normalized_edges_{width}.tsv.gz"
    minimum_overlap = math.ceil(width * COVERAGE[width])
    degrees = array("I", [0]) * UNIVERSE_SIZE
    touched = bytearray(UNIVERSE_SIZE)
    encoded_edges: set[int] = set()
    categories = Counter()
    exact_shift_distances = Counter()
    examples: dict[str, list[dict[str, object]]] = defaultdict(list)

    with gzip.open(io.BytesIO(archive.read(member)), "rt") as handle:
        for raw in handle:
            left, right = raw.rstrip("\n").split("\t")
            a_index = row_index(left)
            b_index = row_index(right)
            if a_index == b_index:
                raise ValueError(f"self edge survived normalization: {left}, {right}")
            lower, upper = sorted((a_index, b_index))
            encoded_edges.add(lower * UNIVERSE_SIZE + upper)
            degrees[a_index] += 1
            degrees[b_index] += 1
            touched[a_index] = touched[b_index] = 1

            a = sequences[a_index]
            b = sequences[b_index]
            if a == b:
                kind = "exact_forward_duplicate"
            elif a == reverse_complement(b):
                kind = "exact_reverse_complement"
            else:
                forward, reverse = exact_shift_offsets(a, b, minimum_overlap)
                if forward and reverse:
                    kind = "exact_shift_both_orientations"
                elif forward:
                    kind = "exact_shift_forward"
                elif reverse:
                    kind = "exact_shift_reverse_complement"
                else:
                    kind = "requires_mismatch_gap_or_other_mmseqs_alignment"
                if forward or reverse:
                    exact_shift_distances[
                        min(abs(value) for value in forward + reverse)
                    ] += 1
            categories[kind] += 1
            if len(examples[kind]) < 3:
                examples[kind].append({"left": left, "right": right})

    degree_values = sorted(value for value in degrees if value)

    def percentile(q: float) -> int:
        if not degree_values:
            return 0
        return degree_values[round((len(degree_values) - 1) * q)]

    return (
        {
            "width": width,
            "minimum_coverage": COVERAGE[width],
            "minimum_exact_overlap_bases": minimum_overlap,
            "edge_count": len(encoded_edges),
            "rows_with_at_least_one_edge": sum(touched),
            "rows_without_edges": UNIVERSE_SIZE - sum(touched),
            "degree_among_connected_rows": {
                "median": percentile(0.50),
                "p95": percentile(0.95),
                "p99": percentile(0.99),
                "max": degree_values[-1] if degree_values else 0,
            },
            "relationship_categories": dict(sorted(categories.items())),
            "exact_shift_distance_bases": {
                str(distance): count
                for distance, count in sorted(exact_shift_distances.items())
            },
            "examples": dict(examples),
            "diagnostic_limit": (
                "Exact-shift categories are rigorous lower bounds. The remaining "
                "category requires the retained raw MMseqs2 alignment columns to "
                "separate mismatches, indels, orientation, identity, and coverage."
            ),
        },
        encoded_edges,
    )


def component_summary(payload: dict[str, object]) -> dict[str, object]:
    summary = payload["summary"]
    distribution = {
        int(size): int(count) for size, count in summary["size_distribution"].items()
    }
    bins = [
        ("1", 1, 1),
        ("2", 2, 2),
        ("3-5", 3, 5),
        ("6-10", 6, 10),
        ("11-25", 11, 25),
        ("26-100", 26, 100),
        (">100", 101, 10**9),
    ]
    grouped = []
    for label, lower, upper in bins:
        component_count = sum(
            count for size, count in distribution.items() if lower <= size <= upper
        )
        row_count = sum(
            size * count
            for size, count in distribution.items()
            if lower <= size <= upper
        )
        grouped.append(
            {
                "size_bin": label,
                "component_count": component_count,
                "row_count": row_count,
                "row_fraction": row_count / UNIVERSE_SIZE,
            }
        )
    return {
        "component_count": summary["component_count"],
        "singleton_count": summary["singleton_count"],
        "largest_component_size": summary["largest_component_size"],
        "largest_component_fraction": summary["giant_component_gate"][
            "largest_component_fraction"
        ],
        "top20_component_fraction": summary["giant_component_gate"][
            "top20_component_fraction"
        ],
        "size_bins": grouped,
    }


def extract_sequences(sequences: list[str], ids: list[str]) -> dict[str, str]:
    return {row_id: sequences[row_index(row_id)] for row_id in ids}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--return-zip", type=Path, required=True)
    parser.add_argument("--fasta-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result: dict[str, object] = {
        "scope": "independent local follow-up on accepted Task 002C evidence",
        "universe_size": UNIVERSE_SIZE,
        "widths": list(WIDTHS),
        "mmseqs_rule": {
            "minimum_sequence_identity": 0.90,
            "coverage": {str(k): v for k, v in COVERAGE.items()},
            "both_strands": True,
        },
        "important_limit": (
            "The sanitized return retains normalized endpoints but not raw per-edge "
            "MMseqs2 identity, coverage, alignment coordinates, or strand. Exact "
            "identity/coverage/strand distributions require the raw TSVs or a rerun."
        ),
    }

    with zipfile.ZipFile(args.return_zip) as archive:
        roots = {name.split("/", 1)[0] for name in archive.namelist() if "/" in name}
        if len(roots) != 1:
            raise ValueError("return ZIP must contain exactly one root directory")
        root = next(iter(roots))
        component_member = f"{root}/reports/cycle1_components/components_report.json"
        result["components"] = component_summary(
            json.loads(archive.read(component_member))
        )

        edge_sets: dict[int, set[int]] = {}
        width_results: dict[str, object] = {}
        row0_ids = ["row_0", "row_142347", "row_204689"]
        row0_example: dict[str, object] = {
            "component_members": row0_ids,
            "explanation": (
                "A concrete three-row component. The sequences are shifted windows "
                "of the same underlying stretch, not full-length duplicates."
            ),
            "by_width": {},
        }
        for width in WIDTHS:
            fasta = args.fasta_dir / f"sequence_partitions_width_{width}.fasta"
            sequences = load_fasta(fasta, width)
            exact = exact_sequence_summary(sequences)
            edges, encoded = edge_summary(archive, root, width, sequences)
            width_results[str(width)] = {"exact_uniqueness": exact, "edges": edges}
            edge_sets[width] = encoded
            row0_example["by_width"][str(width)] = extract_sequences(
                sequences, row0_ids
            )
        result["by_width"] = width_results
        result["edge_set_overlap"] = {
            "500_and_251": len(edge_sets[500] & edge_sets[251]),
            "500_and_101": len(edge_sets[500] & edge_sets[101]),
            "251_and_101": len(edge_sets[251] & edge_sets[101]),
            "all_three": len(edge_sets[500] & edge_sets[251] & edge_sets[101]),
            "500_only": len(edge_sets[500] - edge_sets[251] - edge_sets[101]),
            "251_only": len(edge_sets[251] - edge_sets[500] - edge_sets[101]),
            "101_only": len(edge_sets[101] - edge_sets[500] - edge_sets[251]),
        }
        result["worked_example"] = row0_example

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
