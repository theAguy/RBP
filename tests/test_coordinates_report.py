import unittest

from rbpbench.coordinates.report import (
    MappingResult,
    build_report,
    category_table,
    label_observation_counts,
    reconcile_counts,
    render_markdown,
    stratum_counts,
    usable_unique_rate,
)
from rbpbench.coordinates.sampling import FILLER, QUOTA, REPRESENTATIVE, SampleAssignment

ASSIGNMENTS = (
    SampleAssignment("row_0", 0, REPRESENTATIVE, (1, -2)),
    SampleAssignment("row_1", 1, REPRESENTATIVE, (-1,)),
    SampleAssignment("row_2", 2, QUOTA, (2,)),
    SampleAssignment("row_3", 3, FILLER, ()),
)

PRIMARY_RESULTS = (
    MappingResult("row_0", False, "hg38", "primary", "exact_unique"),
    MappingResult("row_1", False, "hg38", "primary", "low_quality"),
    MappingResult("row_2", False, "hg38", "primary", "ambiguous"),
    MappingResult("row_3", False, "hg38", "primary", "unmapped"),
    MappingResult("control_row_0", True, "hg38", "primary", "high_conf_unique"),
)


class ReportTablesTests(unittest.TestCase):
    def test_stratum_counts(self):
        counts = stratum_counts(ASSIGNMENTS)
        self.assertEqual(counts[REPRESENTATIVE], 2)
        self.assertEqual(counts[QUOTA], 1)
        self.assertEqual(counts[FILLER], 1)

    def test_label_observation_counts(self):
        counts = label_observation_counts(ASSIGNMENTS)
        self.assertEqual(counts[(1, "positive")], 1)
        self.assertEqual(counts[(2, "negative")], 1)
        self.assertEqual(counts[(2, "positive")], 1)
        self.assertEqual(counts[(1, "negative")], 1)

    def test_category_table_separates_controls(self):
        table = category_table(PRIMARY_RESULTS)
        self.assertEqual(table[("hg38", "primary", False)]["exact_unique"], 1)
        self.assertEqual(table[("hg38", "primary", True)]["high_conf_unique"], 1)

    def test_usable_unique_rate_excludes_controls(self):
        rate = usable_unique_rate(PRIMARY_RESULTS, {}, build="hg38")
        # exact_unique + low_quality + ambiguous + unmapped, 1 of 4 usable, controls excluded
        self.assertAlmostEqual(rate, 0.25)


class ReconciliationTests(unittest.TestCase):
    def test_passes_on_consistent_counts(self):
        report = reconcile_counts(
            ASSIGNMENTS, PRIMARY_RESULTS, expected_total=4, expected_representative=2, expected_controls=1
        )
        self.assertTrue(report.passed)

    def test_flags_wrong_total(self):
        report = reconcile_counts(
            ASSIGNMENTS, PRIMARY_RESULTS, expected_total=10, expected_representative=2, expected_controls=1
        )
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.check == "sample_total" for issue in report.issues))

    def test_flags_unknown_sample_id(self):
        extra = PRIMARY_RESULTS + (MappingResult("row_999", False, "hg38", "primary", "unmapped"),)
        report = reconcile_counts(
            ASSIGNMENTS, extra, expected_total=4, expected_representative=2, expected_controls=1
        )
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.check == "unknown_sample_ids" for issue in report.issues))

    def test_flags_wrong_control_count(self):
        report = reconcile_counts(
            ASSIGNMENTS, PRIMARY_RESULTS, expected_total=4, expected_representative=2, expected_controls=5
        )
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.check == "control_count" for issue in report.issues))


class ReportRenderingTests(unittest.TestCase):
    def test_build_report_never_computes_a_recommendation(self):
        reconciliation = reconcile_counts(
            ASSIGNMENTS, PRIMARY_RESULTS, expected_total=4, expected_representative=2, expected_controls=1
        )
        report = build_report(ASSIGNMENTS, PRIMARY_RESULTS, reconciliation=reconciliation)
        self.assertIsNone(report["phase2_recommendation"])

    def test_markdown_mentions_recommendation_is_manual(self):
        reconciliation = reconcile_counts(
            ASSIGNMENTS, PRIMARY_RESULTS, expected_total=4, expected_representative=2, expected_controls=1
        )
        report = build_report(ASSIGNMENTS, PRIMARY_RESULTS, reconciliation=reconciliation)
        markdown = render_markdown(report)
        self.assertIn("human reviewer", markdown)


if __name__ == "__main__":
    unittest.main()
