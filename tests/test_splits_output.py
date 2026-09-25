import gzip
import json
import tempfile
import unittest
from pathlib import Path

from rbpbench.splits.output import (
    MEMBERSHIP_HEADER,
    build_report,
    read_membership_gzip,
    write_deterministic_membership_gzip,
    write_manifest_json,
)


class DeterministicMembershipGzipTests(unittest.TestCase):
    def test_round_trips_rows(self):
        rows = [("row_0", "cAAA", "train"), ("row_1", "cAAA", "train"), ("row_2", "cBBB", "test")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            write_deterministic_membership_gzip(rows, path)
            read_back = read_membership_gzip(path)
        self.assertEqual(read_back, sorted(rows))

    def test_header_only_no_sequence_or_label_values(self):
        rows = [("row_0", "cAAA", "train")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            write_deterministic_membership_gzip(rows, path)
            with gzip.open(path, "rt") as handle:
                header = handle.readline().rstrip("\n").split("\t")
        self.assertEqual(tuple(header), MEMBERSHIP_HEADER)

    def test_byte_identical_across_two_runs_regardless_of_row_order(self):
        rows_a = [("row_0", "c1", "train"), ("row_1", "c2", "validation")]
        rows_b = list(reversed(rows_a))
        with tempfile.TemporaryDirectory() as tmp:
            path_a = Path(tmp) / "a.tsv.gz"
            path_b = Path(tmp) / "b.tsv.gz"
            write_deterministic_membership_gzip(rows_a, path_a)
            write_deterministic_membership_gzip(rows_b, path_b)
            self.assertEqual(path_a.read_bytes(), path_b.read_bytes())

    def test_two_executions_reproduce_identical_bytes(self):
        rows = [("row_0", "c1", "train"), ("row_1", "c2", "test")]
        with tempfile.TemporaryDirectory() as tmp:
            path1 = Path(tmp) / "run1.tsv.gz"
            path2 = Path(tmp) / "run2.tsv.gz"
            write_deterministic_membership_gzip(rows, path1)
            write_deterministic_membership_gzip(rows, path2)
            self.assertEqual(path1.read_bytes(), path2.read_bytes())

    def test_rewrite_does_not_leave_a_stray_tmp_file(self):
        rows = [("row_0", "c1", "train")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            write_deterministic_membership_gzip(rows, path)
            write_deterministic_membership_gzip(rows, path)
            leftovers = list(Path(tmp).glob("*.tmp"))
            self.assertEqual(leftovers, [])

    def test_missing_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.tsv.gz"
            with gzip.open(path, "wt") as handle:
                handle.write("row_0\tc1\ttrain\n")
            with self.assertRaises(ValueError):
                read_membership_gzip(path)


class ManifestJsonTests(unittest.TestCase):
    def test_build_report_never_includes_sequence_or_label_fields(self):
        report = build_report(
            total_rows=4,
            component_sizes={"c1": 2, "c2": 2},
            partition_row_counts={"train": 2, "validation": 1, "test": 1},
            partition_label_counts={"train": {1: (1, 0)}, "validation": {1: (0, 0)}, "test": {1: (0, 0)}},
            target_fractions={"train": 0.70, "validation": 0.15, "test": 0.15},
            protected_widths=(500, 251, 101),
            giant_component_gate={"single_component_gate_tripped": False},
            minimum_count_report={"passed": True},
            cross_partition_audit={"violations": []},
            input_hashes={"input.csv": "deadbeef"},
            config={"seed": 1},
        )
        serialized = json.dumps(report)
        for forbidden in ("sequence", "ACGT", "labels"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(report["total_rows"], 4)
        self.assertEqual(report["protected_widths"], [500, 251, 101])

    def test_atomic_write_and_read_back(self):
        report = build_report(
            total_rows=1,
            component_sizes={"c1": 1},
            partition_row_counts={"train": 1, "validation": 0, "test": 0},
            partition_label_counts={"train": {}, "validation": {}, "test": {}},
            target_fractions={"train": 0.70, "validation": 0.15, "test": 0.15},
            protected_widths=(500, 251, 101),
            giant_component_gate={},
            minimum_count_report={},
            cross_partition_audit={},
            input_hashes={},
            config={},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            write_manifest_json(report, path)
            reloaded = json.loads(path.read_text())
            self.assertEqual(reloaded["total_rows"], 1)
            leftovers = list(Path(tmp).glob("*.tmp"))
            self.assertEqual(leftovers, [])

    def test_input_output_hashes_are_bound_into_the_manifest(self):
        report = build_report(
            total_rows=1,
            component_sizes={},
            partition_row_counts={"train": 0, "validation": 0, "test": 0},
            partition_label_counts={"train": {}, "validation": {}, "test": {}},
            target_fractions={"train": 0.70, "validation": 0.15, "test": 0.15},
            protected_widths=(500, 251, 101),
            giant_component_gate={},
            minimum_count_report={},
            cross_partition_audit={},
            input_hashes={"dataset.csv": "abc123", "membership.tsv.gz": "def456"},
            config={"seed": 20260925},
        )
        self.assertEqual(report["input_hashes"]["dataset.csv"], "abc123")
        self.assertEqual(report["input_hashes"]["membership.tsv.gz"], "def456")
        self.assertEqual(report["config"]["seed"], 20260925)


if __name__ == "__main__":
    unittest.main()
