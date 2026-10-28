from array import array
import gzip
import hashlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zipfile

from reportlab.graphics import renderSVG

from rbpbench.analysis.figures import figure1_process
from rbpbench.analysis.reporting import build_markdown
from rbpbench.analysis.split_validation import (
    Membership,
    ValidationError,
    _read_membership_rows,
    balance_cell,
    composition_analysis,
    component_distribution,
    crossing_report,
    edge_overlap_counts,
    encoded_edge,
    ks_distance,
    parse_labels,
    read_edge_set_from_zip,
    sequence_metrics,
    standardized_mean_difference,
    strict_fasta_records,
    summarize_protein_balance,
    write_tsv,
    read_tsv,
    verify_return_archive,
)
from rbpbench.analysis.task003a import atomic_write, audit_matrix


class LabelContractTests(unittest.TestCase):
    def test_unsigned_and_explicit_plus_are_positive(self):
        self.assertEqual(parse_labels("7;+18;-3"), {7: 1, 18: 1, 3: -1})

    def test_unknown_is_absence(self):
        self.assertEqual(parse_labels(""), {})

    def test_rejects_malformed_duplicate_and_out_of_range(self):
        for raw in ("0", "123", "x", "7;7", "7;-7", "1;;2"):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                parse_labels(raw)


class CompositionFormulaTests(unittest.TestCase):
    def test_gc_entropy_and_homopolymer(self):
        gc, entropy, run = sequence_metrics("AAAACCGGTT")
        self.assertAlmostEqual(gc, 0.4)
        expected = -sum(p * math.log2(p) for p in (0.4, 0.2, 0.2, 0.2)) / 2
        self.assertAlmostEqual(entropy, expected)
        self.assertEqual(run, 4)

    def test_uniform_sequence_endpoints(self):
        self.assertEqual(sequence_metrics("AAAA"), (0.0, 0.0, 4))
        self.assertEqual(sequence_metrics("ACGT")[2], 1)

    def test_rejects_non_acgt(self):
        with self.assertRaises(ValidationError):
            sequence_metrics("ACNT")

    def test_strict_fasta_multiline(self):
        records = list(strict_fasta_records(io.StringIO(">row_0\nAC\nGT\n>row_1\nAAAA\n"), width=4))
        self.assertEqual(records, [(0, "ACGT"), (1, "AAAA")])

    def test_strict_fasta_rejects_wrong_width(self):
        with self.assertRaises(ValidationError):
            list(strict_fasta_records(io.StringIO(">row_0\nACG\n"), width=4))


class ComponentTests(unittest.TestCase):
    def test_tiny_membership_reconstruction(self):
        a, b = "a" * 64, "b" * 64
        membership = _read_membership_rows(
            [
                "sample_id\tcomponent_id\tpartition\n",
                f"row_0\t{a}\ttrain\n",
                f"row_1\t{a}\ttrain\n",
                f"row_2\t{b}\ttest\n",
            ],
            with_partition=True,
            row_count=3,
        )
        self.assertEqual(membership.component_sizes, [2, 1])
        self.assertEqual(list(membership.row_partition), [0, 0, 2])

    def test_membership_rejects_duplicate_missing_and_foreign_ids(self):
        component = "a" * 64
        cases = {
            "duplicate": ["sample_id\tcomponent_id\n", f"row_0\t{component}\n", f"row_0\t{component}\n"],
            "missing": ["sample_id\tcomponent_id\n", f"row_0\t{component}\n"],
            "foreign": ["sample_id\tcomponent_id\n", f"row_0\t{component}\n", f"row_2\t{component}\n"],
        }
        for name, lines in cases.items():
            with self.subTest(name=name), self.assertRaises(ValidationError):
                _read_membership_rows(lines, with_partition=False, row_count=2)

    def test_crossing_report(self):
        membership = Membership(
            row_component=array("I", [0, 0, 1, 2, 2]),
            component_sizes=[2, 1, 2],
            component_ids=["a", "b", "c"],
        )
        report = crossing_report(membership, bytearray([0, 1, 1, 0, 0]))
        self.assertEqual(report["components_represented_in_holdout"], 2)
        self.assertEqual(report["crossing_component_count"], 1)
        self.assertEqual(report["crossing_holdout_row_count"], 1)
        self.assertEqual(report["crossing_train_row_count"], 1)

    def test_component_distribution_ccdf(self):
        rows = component_distribution([1, 1, 2, 4], "v2")
        by_size = {row["component_size"]: row for row in rows}
        self.assertEqual(by_size[2]["components_ge_size"], 2)
        self.assertEqual(by_size[2]["rows_ge_size"], 6)
        self.assertEqual(by_size[1]["components_ge_size"], 4)


class EdgeTests(unittest.TestCase):
    def test_canonical_edge_encoding(self):
        self.assertEqual(encoded_edge("row_2", "row_1"), encoded_edge("row_1", "row_2"))
        self.assertIsNone(encoded_edge("row_3", "row_3"))

    def test_exact_overlap_categories(self):
        a = encoded_edge("row_0", "row_1")
        b = encoded_edge("row_1", "row_2")
        c = encoded_edge("row_2", "row_3")
        rows = edge_overlap_counts({500: {a, b}, 251: {b, c}, 101: {b}})
        counts = {row["mask"]: row["edge_count"] for row in rows}
        self.assertEqual(counts, {1: 1, 2: 1, 3: 0, 4: 0, 5: 0, 6: 0, 7: 1})

    def test_normalized_edge_reader_rejects_reversed_duplicate_and_self(self):
        for name, text in {
            "reversed_duplicate": "row_0\trow_1\nrow_1\trow_0\n",
            "self": "row_0\trow_0\n",
        }.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                archive_path = Path(tmp) / "edges.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr("edges.tsv.gz", gzip.compress(text.encode(), mtime=0))
                with zipfile.ZipFile(archive_path) as archive, self.assertRaises(ValidationError):
                    read_edge_set_from_zip(archive, "edges.tsv.gz")


class EffectSizeTests(unittest.TestCase):
    def test_smd_zero_for_equal_samples(self):
        self.assertEqual(standardized_mean_difference([1, 2, 3], [1, 2, 3]), 0.0)

    def test_ks_distance(self):
        self.assertAlmostEqual(ks_distance([0, 0], [1, 1]), 1.0)
        self.assertAlmostEqual(ks_distance([0, 1], [0, 1]), 0.0)


class BalanceSummaryTests(unittest.TestCase):
    def test_cell_denominator_and_strict_flag_boundary(self):
        fraction, deviation, flagged = balance_cell(18, 100, "validation")
        self.assertEqual(fraction, 0.18)
        self.assertAlmostEqual(deviation, 3.0)
        self.assertFalse(flagged)
        _, deviation, flagged = balance_cell(181, 1000, "validation")
        self.assertAlmostEqual(deviation, 3.1)
        self.assertTrue(flagged)

    def test_summary_uses_evaluation_only_separately(self):
        rows = []
        for pid, name in ((1, "A"), (2, "B")):
            for label_class in ("positive", "negative"):
                for partition, deviation, flagged in (("train", 4.0 if pid == 1 else 0.0, pid == 1), ("validation", 2.0, False), ("test", -2.0, False)):
                    rows.append({"protein_id": pid, "protein_name": name, "label_class": label_class, "partition": partition, "deviation_percentage_points": deviation, "protein_class_total": 100, "flagged_gt_3pp": flagged})
        result = {row["protein_id"]: row for row in summarize_protein_balance(rows)}
        self.assertTrue(result[1]["flagged_any"])
        self.assertFalse(result[1]["flagged_evaluation"])
        self.assertEqual(result[1]["max_abs_deviation_pp_evaluation"], 2.0)


class TableTests(unittest.TestCase):
    def test_tsv_round_trip_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.tsv"
            rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
            write_tsv(path, rows)
            first = path.read_bytes()
            write_tsv(path, rows)
            self.assertEqual(path.read_bytes(), first)
            self.assertEqual(read_tsv(path), [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}])

    def test_figure_source_is_deterministic(self):
        first = renderSVG.drawToString(figure1_process())
        second = renderSVG.drawToString(figure1_process())
        self.assertEqual(
            hashlib.sha256(first.encode()).digest(),
            hashlib.sha256(second.encode()).digest(),
        )


class CompositionStreamingTests(unittest.TestCase):
    def test_streaming_result_matches_tiny_in_memory_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            fasta = Path(tmp) / "tiny.fasta"
            fasta.write_text(">row_0\nAAAA\n>row_1\nAAAA\n>row_2\nACGT\n>row_3\nACGT\n>row_4\nGGGG\n>row_5\nGGGG\n")
            with mock.patch("rbpbench.analysis.split_validation.ROW_COUNT", 6):
                summaries, effects = composition_analysis(
                    fasta,
                    width=4,
                    row_partition=bytearray([0, 0, 1, 1, 2, 2]),
                )
        medians = {(row["partition"], row["metric"]): row["median"] for row in summaries}
        self.assertEqual(medians[("train", "gc_fraction")], 0.0)
        self.assertEqual(medians[("validation", "normalized_entropy")], 1.0)
        self.assertEqual(medians[("test", "max_homopolymer")], 4.0)
        self.assertEqual(len(effects), 9)


class ArchiveValidationTests(unittest.TestCase):
    def _write_archive(self, root: Path, *, status: str = "STOPPED", corrupt_inventory: bool = False):
        archive_path = root / "return.zip"
        status_bytes = json.dumps({"status": status}, sort_keys=True).encode()
        manifest = {
            "status": status,
            "stop_class": status,
            "status_sha256": hashlib.sha256(status_bytes).hexdigest(),
            "return_index": 1,
            "predecessor": None,
        }
        payload = b"payload"
        inventory = {
            "entries": [
                {
                    "path": "payload.txt",
                    "byte_size": len(payload),
                    "sha256": "0" * 64 if corrupt_inventory else hashlib.sha256(payload).hexdigest(),
                }
            ]
        }
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("return/RETURN_MANIFEST.json", json.dumps(manifest))
            archive.writestr("return/RETURN_INVENTORY.json", json.dumps(inventory))
            archive.writestr("return/STATUS.json", status_bytes)
            archive.writestr("return/payload.txt", payload)
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        sidecar = root / "return.zip.sha256"
        sidecar.write_text(f"{digest}  return.zip\n")
        return archive_path, sidecar, digest

    def test_hash_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, sidecar, _ = self._write_archive(Path(tmp))
            with self.assertRaises(ValidationError):
                verify_return_archive(archive, expected_size=archive.stat().st_size, expected_sha256="0" * 64, sidecar=sidecar)

    def test_terminal_status_and_inventory_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, sidecar, digest = self._write_archive(Path(tmp), status="STOPPED")
            with self.assertRaisesRegex(ValidationError, "terminal SUCCESS"):
                verify_return_archive(archive, expected_size=archive.stat().st_size, expected_sha256=digest, sidecar=sidecar)
        with tempfile.TemporaryDirectory() as tmp:
            archive, sidecar, digest = self._write_archive(Path(tmp), status="SUCCESS", corrupt_inventory=True)
            with self.assertRaisesRegex(ValidationError, "inventory mismatch"):
                verify_return_archive(archive, expected_size=archive.stat().st_size, expected_sha256=digest, sidecar=sidecar)


class AuditMatrixTests(unittest.TestCase):
    def test_complete_unique_18_direction_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "audits.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for width in (500, 251, 101):
                    archive.writestr(
                        f"return/records/selected/cycle1_auditprep_{width}.json",
                        json.dumps({"payload": {"positive_control_passed": True, "partitions": {"train": 7, "validation": 2, "test": 3}}}),
                    )
                    for query, target in (("train", "validation"), ("validation", "train"), ("train", "test"), ("test", "train"), ("validation", "test"), ("test", "validation")):
                        archive.writestr(
                            f"return/records/selected/cycle1_audit_{width}_{query}_to_{target}.json",
                            json.dumps({"payload": {"cycle": 1, "query": query, "target": target, "violation_count": 0, "width": width}}),
                        )
            with zipfile.ZipFile(archive_path) as archive:
                rows = audit_matrix(archive, "return")
        keys = {(row["width"], row["query_partition"], row["target_partition"]) for row in rows}
        self.assertEqual(len(rows), 18)
        self.assertEqual(len(keys), 18)


class ReportingTests(unittest.TestCase):
    def _results(self):
        crossing = {"crossing_holdout_row_count": 2, "holdout_count": 4, "crossing_holdout_row_rate": 0.5, "crossing_train_row_count": 3, "train_count": 6, "crossing_train_row_rate": 0.5}
        return {
            "former_fold_v1": crossing,
            "former_fold_v2": crossing | {"crossing_holdout_row_count": 3, "crossing_holdout_row_rate": 0.75},
            "closure": {
                "universe": {"component_count": 5, "largest_component_size": 2, "largest_component_fraction": 0.2, "top20_component_fraction": 1.0},
                "partition_row_counts": {"train": 6, "validation": 2, "test": 2},
                "partition_fractions": {"train": 0.6, "validation": 0.2, "test": 0.2},
            },
            "balance": {"minimum_known_positive": {"count": 31}, "minimum_known_negative": {"count": 32}, "proteins_flagged_any_partition": 4, "cells_flagged_any_partition": 5, "proteins_flagged_validation_or_test": 2, "cells_flagged_validation_or_test": 3},
        }

    def test_caption_values_come_from_summaries(self):
        effects = [{"absolute_smd": 0.111, "standardized_mean_difference": -0.111, "metric": "gc_fraction", "width": 251, "partition_a": "train", "partition_b": "test", "smd_interpretation": "notable", "ks_d": 0.222}]
        report = build_markdown(self._results(), effects, {f"figure{i}": f"f{i}.svg" for i in range(1, 9)})
        self.assertIn("0.111", report)
        self.assertIn("0.222", report)
        self.assertIn("3/4 holdout rows (75.000%)", report)


class TransactionTests(unittest.TestCase):
    def test_failed_atomic_write_preserves_prior_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "selected.json"
            target.write_bytes(b"prior")
            with mock.patch("rbpbench.analysis.task003a.os.replace", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    atomic_write(target, b"new")
            self.assertEqual(target.read_bytes(), b"prior")
            self.assertEqual(list(Path(tmp).glob("*.tmp-*")), [])


if __name__ == "__main__":
    unittest.main()
