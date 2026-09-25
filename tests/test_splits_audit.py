import unittest

from rbpbench.splits.assignment import TARGET_FRACTIONS
from rbpbench.splits.audit import (
    ForeignAuditEndpointError,
    balance_report,
    cross_partition_violations,
    giant_component_gate,
    minimum_count_check,
    per_protein_balance_report,
)


class GiantComponentGateTests(unittest.TestCase):
    def test_no_gate_trips_under_a_well_spread_distribution(self):
        sizes = {f"c{i}": 1 for i in range(100)}
        report = giant_component_gate(sizes, total_rows=100)
        self.assertFalse(report["single_component_gate_tripped"])
        self.assertFalse(report["top20_gate_tripped"])

    def test_single_component_gate_trips_over_5_percent_with_diagnostics(self):
        sizes = {"giant": 6, **{f"c{i}": 1 for i in range(94)}}
        report = giant_component_gate(sizes, total_rows=100)
        self.assertTrue(report["single_component_gate_tripped"])
        self.assertEqual(report["largest_component_id"], "giant")
        self.assertAlmostEqual(report["largest_component_fraction"], 0.06)

    def test_top20_gate_trips_over_20_percent_with_diagnostics(self):
        # 20 components at 1.1% each = 22% > 20%, but each individually well
        # under the 5% single-component threshold.
        sizes = {f"c{i}": 11 for i in range(20)}
        sizes.update({f"filler{i}": 1 for i in range(780)})
        report = giant_component_gate(sizes, total_rows=1000)
        self.assertFalse(report["single_component_gate_tripped"])
        self.assertTrue(report["top20_gate_tripped"])
        self.assertEqual(len(report["top20_components"]), 20)

    def test_rejects_non_positive_total(self):
        with self.assertRaises(ValueError):
            giant_component_gate({}, total_rows=0)


class BalanceReportTests(unittest.TestCase):
    def test_exact_target_is_not_flagged(self):
        counts = {"train": 700, "validation": 150, "test": 150}
        report = balance_report(counts, TARGET_FRACTIONS, total_rows=1000)
        for entry in report.values():
            self.assertFalse(entry["flagged"])

    def test_deviation_over_3pp_is_disclosed_and_flagged(self):
        counts = {"train": 650, "validation": 175, "test": 175}
        report = balance_report(counts, TARGET_FRACTIONS, total_rows=1000)
        self.assertTrue(report["train"]["flagged"])
        self.assertAlmostEqual(report["train"]["deviation_percentage_points"], -5.0)

    def test_deviation_within_3pp_is_disclosed_but_not_flagged(self):
        counts = {"train": 680, "validation": 160, "test": 160}
        report = balance_report(counts, TARGET_FRACTIONS, total_rows=1000)
        self.assertIn("deviation_percentage_points", report["train"])
        self.assertFalse(report["train"]["flagged"])


class PerProteinBalanceReportTests(unittest.TestCase):
    def test_flags_a_protein_class_skewed_into_one_partition(self):
        partition_label_counts = {
            "train": {1: (100, 0)},
            "validation": {1: (0, 0)},
            "test": {1: (0, 0)},
        }
        report = per_protein_balance_report(partition_label_counts, TARGET_FRACTIONS)
        self.assertTrue(report[1]["train"]["known_positive"]["flagged"])
        self.assertTrue(report[1]["validation"]["known_positive"]["flagged"])

    def test_well_balanced_protein_is_not_flagged(self):
        partition_label_counts = {
            "train": {1: (70, 70)},
            "validation": {1: (15, 15)},
            "test": {1: (15, 15)},
        }
        report = per_protein_balance_report(partition_label_counts, TARGET_FRACTIONS)
        for partition_entry in report[1].values():
            self.assertFalse(partition_entry["known_positive"]["flagged"])
            self.assertFalse(partition_entry["known_negative"]["flagged"])


class MinimumCountCheckTests(unittest.TestCase):
    def test_passes_when_every_protein_clears_the_floor(self):
        partition_label_counts = {
            "train": {1: (100, 100)},
            "validation": {1: (30, 30)},
            "test": {1: (30, 30)},
        }
        report = minimum_count_check(partition_label_counts)
        self.assertTrue(report["passed"])
        self.assertEqual(report["violations"], [])

    def test_reports_but_does_not_repair_a_violation(self):
        partition_label_counts = {
            "train": {1: (100, 100)},
            "validation": {1: (29, 30)},
            "test": {1: (30, 30)},
        }
        report = minimum_count_check(partition_label_counts)
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["violations"]), 1)
        violation = report["violations"][0]
        self.assertEqual(violation["partition"], "validation")
        self.assertEqual(violation["class"], "known_positive")
        # The count itself is preserved verbatim in the report, not repaired.
        self.assertEqual(violation["count"], 29)

    def test_near_floor_proteins_are_flagged_for_confidence_interval_treatment(self):
        partition_label_counts = {
            "train": {1: (100, 100)},
            "validation": {1: (35, 35)},
            "test": {1: (35, 35)},
        }
        report = minimum_count_check(partition_label_counts)
        self.assertTrue(report["passed"])
        self.assertTrue(len(report["near_floor_flagged"]) > 0)


class CrossPartitionViolationsTests(unittest.TestCase):
    def test_no_violation_when_edge_endpoints_share_a_partition(self):
        assignment = {"row_0": "train", "row_1": "train"}
        violations = cross_partition_violations(assignment, [("row_0", "row_1")])
        self.assertEqual(violations, [])

    def test_violation_reported_when_edge_crosses_partitions(self):
        assignment = {"row_0": "train", "row_1": "test"}
        violations = cross_partition_violations(assignment, [("row_0", "row_1")])
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["partition_a"], "train")
        self.assertEqual(violations[0]["partition_b"], "test")

    def test_foreign_endpoint_in_the_second_position_raises_not_skips(self):
        assignment = {"row_0": "train"}
        with self.assertRaises(ForeignAuditEndpointError) as ctx:
            cross_partition_violations(assignment, [("row_0", "row_unknown")])
        self.assertIn("row_unknown", str(ctx.exception))

    def test_foreign_endpoint_in_the_first_position_raises_not_skips(self):
        assignment = {"row_1": "train"}
        with self.assertRaises(ForeignAuditEndpointError) as ctx:
            cross_partition_violations(assignment, [("row_unknown", "row_1")])
        self.assertIn("row_unknown", str(ctx.exception))

    def test_both_endpoints_foreign_raises_naming_both(self):
        assignment = {"row_0": "train"}
        with self.assertRaises(ForeignAuditEndpointError) as ctx:
            cross_partition_violations(assignment, [("row_unknown_a", "row_unknown_b")])
        message = str(ctx.exception)
        self.assertIn("row_unknown_a", message)
        self.assertIn("row_unknown_b", message)

    def test_a_foreign_edge_is_raised_before_later_clean_edges_are_reached(self):
        # Fail-closed: one corrupted edge must not be silently skipped while
        # ordinary same-/cross-partition edges elsewhere in the same audit
        # continue to be processed as if nothing were wrong.
        assignment = {"row_0": "train", "row_1": "train"}
        with self.assertRaises(ForeignAuditEndpointError):
            cross_partition_violations(assignment, [("row_unknown", "row_0"), ("row_0", "row_1")])

    def test_multiple_widths_worth_of_duplicate_edges_all_checked(self):
        assignment = {"row_0": "train", "row_1": "validation", "row_2": "train"}
        edges = [("row_0", "row_1"), ("row_0", "row_2")]  # one violating, one clean
        violations = cross_partition_violations(assignment, edges)
        self.assertEqual(len(violations), 1)
        self.assertEqual({violations[0]["sample_a"], violations[0]["sample_b"]}, {"row_0", "row_1"})


if __name__ == "__main__":
    unittest.main()
