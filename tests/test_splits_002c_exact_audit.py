import unittest

from rbpbench.splits.exact_audit import ExactAuditUniverseError, audit_all_widths, audit_width


class AuditWidthTests(unittest.TestCase):
    def test_no_duplicates_no_violations(self):
        # Canonical forms (min(seq, reverse_complement(seq))) are AAAA,
        # CCCC, and ACAC respectively -- all distinct, so no group forms.
        sequences = {"row_0": "AAAA", "row_1": "CCCC", "row_2": "ACAC"}
        partitions = {"row_0": "train", "row_1": "validation", "row_2": "test"}
        report = audit_width(sequences, partitions)
        self.assertTrue(report["passed"])
        self.assertEqual(report["violation_count"], 0)
        self.assertEqual(report["duplicate_group_count"], 0)

    def test_exact_duplicate_within_one_partition_is_not_a_violation(self):
        sequences = {"row_0": "AAAA", "row_1": "AAAA"}
        partitions = {"row_0": "train", "row_1": "train"}
        report = audit_width(sequences, partitions)
        self.assertTrue(report["passed"])
        self.assertEqual(report["duplicate_group_count"], 1)
        self.assertEqual(report["max_duplicate_group_size"], 2)

    def test_exact_duplicate_across_partitions_is_a_violation(self):
        sequences = {"row_0": "AAAA", "row_1": "AAAA"}
        partitions = {"row_0": "train", "row_1": "test"}
        report = audit_width(sequences, partitions)
        self.assertFalse(report["passed"])
        self.assertEqual(report["violation_count"], 1)
        self.assertEqual(
            {report["violations"][0]["sample_a"], report["violations"][0]["sample_b"]}, {"row_0", "row_1"}
        )

    def test_reverse_complement_across_partitions_is_a_violation(self):
        # AAAA's reverse complement is TTTT: same canonical hash.
        sequences = {"row_0": "AAAA", "row_1": "TTTT"}
        partitions = {"row_0": "train", "row_1": "validation"}
        report = audit_width(sequences, partitions)
        self.assertFalse(report["passed"])
        self.assertEqual(report["violation_count"], 1)

    def test_transitive_duplicate_group_all_pairs_checked(self):
        # row_0 == row_1 (exact), row_1 == row_2's RC -> one 3-member group;
        # row_2 in a third partition means at least one crossing pair.
        sequences = {"row_0": "AAAA", "row_1": "AAAA", "row_2": "TTTT"}
        partitions = {"row_0": "train", "row_1": "train", "row_2": "test"}
        report = audit_width(sequences, partitions)
        self.assertFalse(report["passed"])
        self.assertGreaterEqual(report["violation_count"], 1)

    def test_report_contains_no_sequence_or_label_values(self):
        sequences = {"row_0": "AAAA", "row_1": "AAAA"}
        partitions = {"row_0": "train", "row_1": "test"}
        report = audit_width(sequences, partitions)
        rendered = str(report)
        self.assertNotIn("AAAA", rendered)

    def test_foreign_id_in_sequences_raises_universe_error(self):
        sequences = {"row_0": "AAAA", "row_99": "CCCC"}
        partitions = {"row_0": "train"}
        with self.assertRaises(ExactAuditUniverseError):
            audit_width(sequences, partitions)

    def test_missing_id_from_sequences_raises_universe_error(self):
        sequences = {"row_0": "AAAA"}
        partitions = {"row_0": "train", "row_1": "test"}
        with self.assertRaises(ExactAuditUniverseError):
            audit_width(sequences, partitions)

    def test_denominators_and_rates_are_reported(self):
        sequences = {f"row_{i}": "A" * (i + 1) for i in range(10)}
        partitions = {f"row_{i}": "train" for i in range(10)}
        report = audit_width(sequences, partitions)
        self.assertEqual(report["total_rows"], 10)
        self.assertIn("violation_rate_over_rows", report)


class AuditAllWidthsTests(unittest.TestCase):
    def test_passes_when_every_width_passes(self):
        by_width = {
            500: {"row_0": "AAAA", "row_1": "CCCC"},
            251: {"row_0": "AAAA", "row_1": "CCCC"},
            101: {"row_0": "AAAA", "row_1": "CCCC"},
        }
        partitions = {"row_0": "train", "row_1": "validation"}
        result = audit_all_widths(by_width, partitions)
        self.assertTrue(result["passed"])
        self.assertEqual(set(result["widths"].keys()), {"500", "251", "101"})

    def test_fails_when_any_single_width_fails(self):
        by_width = {
            500: {"row_0": "AAAA", "row_1": "CCCC"},  # clean
            251: {"row_0": "GGGG", "row_1": "GGGG"},  # exact duplicate, crosses partitions
        }
        partitions = {"row_0": "train", "row_1": "test"}
        result = audit_all_widths(by_width, partitions)
        self.assertFalse(result["passed"])
        self.assertTrue(result["widths"]["500"]["passed"])
        self.assertFalse(result["widths"]["251"]["passed"])


if __name__ == "__main__":
    unittest.main()
