"""Regression coverage for review item 6 (report-schema completeness) and
review item 3 (scientific-report corrections): the combined two-build report
must carry every prespecified scientific table — mapping rates, the
representative-stratum gate inputs, build comparison, contiguous/splice
rescue, quality distributions, strand/locus summaries, near-tied-score
sensitivity, control alerts, exact-match discordance, and mode-specific
(combined/primary/splice) retention analyses by protein/class, GC, low
complexity, and (when supplied) contig category — with controls excluded
from every scientific denominator and retained only in control_alerts, and
signed positive-minus-negative gaps preserved alongside absolute-gap alerts.
These are schema + basic-correctness assertions on
:mod:`rbpbench.coordinates.summaries`, which backs the runner's
``combined_report`` stage.
"""

from __future__ import annotations

import unittest

from rbpbench.coordinates import summaries
from rbpbench.coordinates.sequence_stats import gc_decile, low_complexity_decile


def _row(sample_id, mode, category, *, is_control=False, chrom="chr1", start="0", end="20", strand="+",
         coverage="1.000000", identity="1.000000", near_tied_fractions="",
         exact_occurrence_count="", bwa_best_is_perfect="", bwa_perfect_unique_candidate=""):
    return {
        "sample_id": sample_id,
        "is_control": str(is_control),
        "mode": mode,
        "category": category,
        "chrom": chrom,
        "start": start,
        "end": end,
        "strand": strand,
        "coverage": coverage,
        "identity": identity,
        "near_tied_fractions": near_tied_fractions,
        "exact_occurrence_count": exact_occurrence_count,
        "bwa_best_is_perfect": str(bwa_best_is_perfect) if bwa_best_is_perfect != "" else "",
        "bwa_perfect_unique_candidate": (
            str(bwa_perfect_unique_candidate) if bwa_perfect_unique_candidate != "" else ""
        ),
    }


PRIMARY_ROWS = [
    _row("row_0", "primary", "exact_unique", start="0", end="20", coverage="1.0", identity="1.0",
         exact_occurrence_count="1", bwa_best_is_perfect=True, bwa_perfect_unique_candidate=True),
    _row("row_1", "primary", "low_quality", start="100", end="120", coverage="0.5", identity="0.9"),
    _row("row_2", "primary", "ambiguous", start="200", end="220", coverage="0.95", identity="0.96",
         near_tied_fractions="0.05;0.1"),
    _row("row_3", "primary", "unmapped", chrom="", start="", end="", strand="", coverage="", identity=""),
    _row("control_row_0", "primary", "exact_unique", is_control=True, start="300", end="320",
         exact_occurrence_count="1", bwa_best_is_perfect=True, bwa_perfect_unique_candidate=True),
]

SPLICE_ROWS = [
    _row("row_0", "splice", "unspliced_unique", start="0", end="20"),
    _row("row_1", "splice", "spliced_unique", start="150", end="220"),
    _row("row_2", "splice", "unspliced_unique", start="200", end="220"),
    _row("row_3", "splice", "unmapped", chrom="", start="", end="", strand="", coverage="", identity=""),
    _row("control_row_0", "splice", "unspliced_unique", is_control=True, start="300", end="320"),
]

SAMPLE_META = [
    {"sample_id": "row_0", "labels": "1"},
    {"sample_id": "row_1", "labels": "-1"},
    {"sample_id": "row_2", "labels": "2"},
    {"sample_id": "row_3", "labels": "-2"},
]

SAMPLE_SEQUENCES = {
    "row_0": "GCGCGCGCGCGCGCGCGCGC",  # high GC, high complexity (2 bases)
    "row_1": "AAAAAAAAAAAAAAAAAAAA",  # low GC, low complexity (homopolymer)
    "row_2": "ACGTACGTACGTACGTACGT",  # ~50% GC, high complexity
    "row_3": "ATATATATATATATATATAT",  # low GC, low complexity
}

REPRESENTATIVE_IDS = ["row_0", "row_1", "row_2", "row_3"]
ALL_SAMPLE_IDS = ["row_0", "row_1", "row_2", "row_3"]
NEAR_TIED_FRACTIONS = (0.02, 0.05, 0.10)
RETENTION_SCOPES = ("combined", "primary", "splice")


class BuildPerBuildSummarySchemaTests(unittest.TestCase):
    def setUp(self):
        self.summary = summaries.build_per_build_summary(
            build="hg38",
            primary_rows=PRIMARY_ROWS,
            splice_rows=SPLICE_ROWS,
            representative_ids=REPRESENTATIVE_IDS,
            all_sample_ids=ALL_SAMPLE_IDS,
            sample_meta=SAMPLE_META,
            sample_sequences=SAMPLE_SEQUENCES,
            near_tied_fractions=NEAR_TIED_FRACTIONS,
        )

    def test_top_level_schema_has_every_required_table(self):
        for key in (
            "build",
            "representative_stratum_gate",
            "contiguous_vs_splice_rescued",
            "quality_distributions",
            "strand_and_locus",
            "near_tied_sensitivity",
            "control_alerts",
            "exact_match_discordance",
            "retention",
        ):
            self.assertIn(key, self.summary)

    def test_representative_stratum_gate_has_prespecified_mapping_rates(self):
        gate = self.summary["representative_stratum_gate"]
        for key in ("usable_unique_rate", "exact_unique_rate", "ambiguous_rate", "unmapped_rate"):
            self.assertIn(key, gate)
            for ci_key in ("point_estimate", "lower", "upper", "successes", "total"):
                self.assertIn(ci_key, gate[key])
        # row_0 exact_unique + row_1 (low_quality primary, spliced_unique
        # rescue) = 2 of 4 usable. Controls never enter this denominator.
        self.assertAlmostEqual(gate["usable_unique_rate"]["point_estimate"], 0.5)
        self.assertEqual(gate["usable_unique_rate"]["total"], 4)
        self.assertAlmostEqual(gate["exact_unique_rate"]["point_estimate"], 0.25)

    def test_contiguous_vs_splice_rescued_table(self):
        payload = self.summary["contiguous_vs_splice_rescued"]
        self.assertIn("representative", payload)
        self.assertIn("all_sampled", payload)
        counts = payload["representative"]["counts"]
        self.assertEqual(counts.get("contiguous_usable"), 1)  # row_0
        self.assertEqual(counts.get("splice_rescued"), 1)  # row_1
        self.assertEqual(counts.get("still_unusable"), 2)  # row_2, row_3

    def test_quality_distribution_table_covers_both_modes(self):
        distributions = self.summary["quality_distributions"]
        for key in (
            "primary_coverage_decile",
            "primary_identity_decile",
            "splice_coverage_decile",
            "splice_identity_decile",
        ):
            self.assertIn(key, distributions)

    def test_quality_distribution_excludes_controls(self):
        # 3 mapped, non-control primary rows (row_0, row_1, row_2); the
        # mapped control (control_row_0) must not inflate this histogram.
        histogram = self.summary["quality_distributions"]["primary_coverage_decile"]
        self.assertEqual(sum(histogram.values()), 3)

    def test_strand_and_locus_table_excludes_controls(self):
        payload = self.summary["strand_and_locus"]
        self.assertIn("primary", payload)
        self.assertIn("splice", payload)
        for mode_payload in payload.values():
            for key in ("forward_strand", "reverse_strand", "distinct_loci", "max_rows_per_locus", "mean_rows_per_locus"):
                self.assertIn(key, mode_payload)
        # row_0, row_1, row_2 mapped (chrom set), row_3 unmapped: 3 distinct
        # loci. control_row_0's locus must not be counted here (review item
        # 3: controls excluded from every scientific strand/locus table).
        self.assertEqual(payload["primary"]["distinct_loci"], 3)

    def test_near_tied_sensitivity_table_excludes_controls(self):
        payload = self.summary["near_tied_sensitivity"]
        for mode in ("primary", "splice"):
            for fraction in NEAR_TIED_FRACTIONS:
                key = f"{fraction:g}"
                self.assertIn(key, payload[mode])
                self.assertIn("triggered", payload[mode][key])
                self.assertIn("total", payload[mode][key])
        # row_2's primary row declared near_tied_fractions "0.05;0.1". The
        # "total" denominator is every non-control row evaluated in that
        # mode (row_0..row_3 = 4), regardless of mapped status; the control
        # row must not inflate it to 5.
        self.assertEqual(payload["primary"]["0.05"]["triggered"], 1)
        self.assertEqual(payload["primary"]["0.02"]["triggered"], 0)
        self.assertEqual(payload["primary"]["0.05"]["total"], 4)

    def test_control_alert_flags_a_usable_unique_control(self):
        payload = self.summary["control_alerts"]
        self.assertTrue(payload["primary"]["alert"])
        self.assertIn("control_row_0", payload["primary"]["flagged_sample_ids"])
        # The control's splice category (unspliced_unique) does not count as
        # the splice-rescue category, so no splice-mode alert.
        self.assertFalse(payload["splice"]["alert"])

    def test_exact_match_discordance_excludes_controls_and_flags_mismatch(self):
        primary_rows = PRIMARY_ROWS + [
            _row("row_4", "primary", "high_conf_unique", start="400", end="420", coverage="1.0", identity="1.0",
                 exact_occurrence_count="2", bwa_best_is_perfect=True, bwa_perfect_unique_candidate=True),
        ]
        summary = summaries.build_per_build_summary(
            build="hg38",
            primary_rows=primary_rows,
            splice_rows=SPLICE_ROWS,
            representative_ids=REPRESENTATIVE_IDS,
            all_sample_ids=ALL_SAMPLE_IDS,
            sample_meta=SAMPLE_META,
            sample_sequences=SAMPLE_SEQUENCES,
            near_tied_fractions=NEAR_TIED_FRACTIONS,
        )
        discordance = summary["exact_match_discordance"]
        # row_0 (occurrence_count=1, concordant) and row_4 (occurrence_count=2,
        # discordant) are BWA-perfect-unique *candidates*; the control is
        # excluded even though it is also a perfect-unique candidate.
        self.assertEqual(discordance["total_bwa_perfect_unique_candidates"], 2)
        self.assertEqual(discordance["discordant_count"], 1)
        self.assertEqual(discordance["discordant_sample_ids"], ["row_4"])

    def test_two_perfect_bwa_loci_is_ambiguous_not_a_discordance_candidate(self):
        # Regression: a read with two perfect (100% coverage/identity) BWA
        # loci is classified ambiguous (a plausible distinct secondary
        # exists), so bwa_best_is_perfect=True must NOT count it as a
        # perfect-unique *candidate* for discordance purposes, regardless of
        # what SeqKit reports.
        primary_rows = PRIMARY_ROWS + [
            _row("row_5", "primary", "ambiguous", start="500", end="520", coverage="1.0", identity="1.0",
                 exact_occurrence_count="2", bwa_best_is_perfect=True, bwa_perfect_unique_candidate=False),
        ]
        summary = summaries.build_per_build_summary(
            build="hg38",
            primary_rows=primary_rows,
            splice_rows=SPLICE_ROWS,
            representative_ids=REPRESENTATIVE_IDS,
            all_sample_ids=ALL_SAMPLE_IDS,
            sample_meta=SAMPLE_META,
            sample_sequences=SAMPLE_SEQUENCES,
            near_tied_fractions=NEAR_TIED_FRACTIONS,
        )
        discordance = summary["exact_match_discordance"]
        self.assertNotIn("row_5", discordance["discordant_sample_ids"])
        # Only row_0 and the control are true candidates (2, after control
        # exclusion only row_0 counts); row_5 must not inflate the total.
        self.assertEqual(discordance["total_bwa_perfect_unique_candidates"], 1)

    def test_retention_reported_separately_for_combined_primary_and_splice(self):
        retention = self.summary["retention"]
        for scope in RETENTION_SCOPES:
            self.assertIn(scope, retention)
            for key in ("by_protein_class", "by_gc_decile", "by_low_complexity_decile", "by_contig_category"):
                self.assertIn(key, retention[scope])

        # protein 1: row_0 (primary exact_unique) positive; row_1 (primary
        # low_quality, splice-rescued) negative.
        # combined mode (rescue-aware): both retained.
        combined_pc = retention["combined"]["by_protein_class"]["per_protein_class"]
        self.assertEqual(combined_pc["1:positive"]["point_estimate"], 1.0)
        self.assertEqual(combined_pc["1:negative"]["point_estimate"], 1.0)
        # primary-mode-only: row_1 is NOT primary-usable (low_quality), so
        # its retention must drop to 0 even though the combined gate rescues
        # it via splice.
        primary_pc = retention["primary"]["by_protein_class"]["per_protein_class"]
        self.assertEqual(primary_pc["1:positive"]["point_estimate"], 1.0)
        self.assertEqual(primary_pc["1:negative"]["point_estimate"], 0.0)
        # splice-mode-only: row_1's splice category is spliced_unique
        # (splice-mode usable), row_0's is unspliced_unique (also usable).
        splice_pc = retention["splice"]["by_protein_class"]["per_protein_class"]
        self.assertEqual(splice_pc["1:positive"]["point_estimate"], 1.0)
        self.assertEqual(splice_pc["1:negative"]["point_estimate"], 1.0)

        gc_bucket = gc_decile(SAMPLE_SEQUENCES["row_0"])
        self.assertIn(str(gc_bucket), retention["combined"]["by_gc_decile"])
        complexity_bucket = low_complexity_decile(SAMPLE_SEQUENCES["row_1"])
        self.assertIn(str(complexity_bucket), retention["combined"]["by_low_complexity_decile"])

    def test_retention_by_contig_category_is_none_when_not_supplied(self):
        for scope in RETENTION_SCOPES:
            self.assertIsNone(self.summary["retention"][scope]["by_contig_category"])

    def test_retention_by_contig_category_reported_when_supplied(self):
        summary = summaries.build_per_build_summary(
            build="hg38",
            primary_rows=PRIMARY_ROWS,
            splice_rows=SPLICE_ROWS,
            representative_ids=REPRESENTATIVE_IDS,
            all_sample_ids=ALL_SAMPLE_IDS,
            sample_meta=SAMPLE_META,
            sample_sequences=SAMPLE_SEQUENCES,
            near_tied_fractions=NEAR_TIED_FRACTIONS,
            contig_categories={"chr1": "chromosome"},
        )
        by_contig = summary["retention"]["combined"]["by_contig_category"]
        self.assertIsNotNone(by_contig)
        self.assertIn("chromosome", by_contig)

    def test_signed_gap_is_preserved_alongside_absolute_alert_threshold(self):
        primary_rows = [
            _row("pos_1", "primary", "exact_unique"),
            _row("neg_1", "primary", "unmapped", chrom="", start="", end="", strand=""),
        ]
        splice_rows = [
            _row("pos_1", "splice", "unmapped", chrom="", start="", end="", strand=""),
            _row("neg_1", "splice", "unmapped", chrom="", start="", end="", strand=""),
        ]
        sample_meta = [
            {"sample_id": "pos_1", "labels": "9"},
            {"sample_id": "neg_1", "labels": "-9"},
        ]
        retention = summaries.retention_by_protein_class(
            sample_meta,
            summaries.index_rows_by_sample(primary_rows, mode="primary"),
            summaries.index_rows_by_sample(splice_rows, mode="splice"),
        )
        # Positive retains 100%, negative retains 0%: signed gap is +1.0,
        # not abs(+1.0) collapsed to look identical to a -1.0 case.
        self.assertEqual(retention["per_protein_gap_distribution"], [1.0])
        self.assertEqual(retention["overall_positive_negative_gap"], 1.0)

        # Now flip which class is retained: signed gap must be -1.0.
        primary_rows_flipped = [
            _row("pos_1", "primary", "unmapped", chrom="", start="", end="", strand=""),
            _row("neg_1", "primary", "exact_unique"),
        ]
        retention_flipped = summaries.retention_by_protein_class(
            sample_meta,
            summaries.index_rows_by_sample(primary_rows_flipped, mode="primary"),
            summaries.index_rows_by_sample(splice_rows, mode="splice"),
        )
        self.assertEqual(retention_flipped["per_protein_gap_distribution"], [-1.0])
        self.assertEqual(retention_flipped["overall_positive_negative_gap"], -1.0)

        # Both directions trigger the severe alert (which uses the absolute
        # gap only for the threshold decision) but preserve their own sign.
        for r in (retention, retention_flipped):
            alerts = [a for a in r["severe_alerts"] if a["reason"] == "retention_gap_ge_40pts"]
            self.assertEqual(len(alerts), 1)
        self.assertEqual(
            [a["gap"] for a in retention["severe_alerts"] if a["reason"] == "retention_gap_ge_40pts"], [1.0]
        )
        self.assertEqual(
            [a["gap"] for a in retention_flipped["severe_alerts"] if a["reason"] == "retention_gap_ge_40pts"], [-1.0]
        )

    def test_severe_alert_triggers_below_50pct_class_retention(self):
        # A protein/class with zero usable observations must be flagged.
        primary_rows = [
            _row("row_a", "primary", "unmapped", chrom="", start="", end="", strand=""),
            _row("row_b", "primary", "unmapped", chrom="", start="", end="", strand=""),
        ]
        splice_rows = [
            _row("row_a", "splice", "unmapped", chrom="", start="", end="", strand=""),
            _row("row_b", "splice", "unmapped", chrom="", start="", end="", strand=""),
        ]
        sample_meta = [
            {"sample_id": "row_a", "labels": "5"},
            {"sample_id": "row_b", "labels": "5"},
        ]
        retention = summaries.retention_by_protein_class(
            sample_meta,
            summaries.index_rows_by_sample(primary_rows, mode="primary"),
            summaries.index_rows_by_sample(splice_rows, mode="splice"),
        )
        self.assertTrue(
            any(alert["reason"] == "retention_below_50pct" and alert["protein"] == 5 for alert in retention["severe_alerts"])
        )


class CompareBuildsSchemaTests(unittest.TestCase):
    def test_compare_builds_reports_required_fields_without_raw_coordinate_comparison(self):
        summary_hg38 = summaries.build_per_build_summary(
            build="hg38",
            primary_rows=PRIMARY_ROWS,
            splice_rows=SPLICE_ROWS,
            representative_ids=REPRESENTATIVE_IDS,
            all_sample_ids=ALL_SAMPLE_IDS,
            sample_meta=SAMPLE_META,
            sample_sequences=SAMPLE_SEQUENCES,
            near_tied_fractions=NEAR_TIED_FRACTIONS,
        )
        # hg19 differs only in row_0's category (ambiguous instead of
        # exact_unique): a category change should be detected. Raw
        # coordinates are deliberately NOT compared across builds (review
        # item 3: no liftover, so no defensible coordinate equivalence).
        primary_rows_hg19 = [
            _row("row_0", "primary", "ambiguous", chrom="chr9", start="0", end="20"),
            *PRIMARY_ROWS[1:],
        ]
        summary_hg19 = summaries.build_per_build_summary(
            build="hg19",
            primary_rows=primary_rows_hg19,
            splice_rows=SPLICE_ROWS,
            representative_ids=REPRESENTATIVE_IDS,
            all_sample_ids=ALL_SAMPLE_IDS,
            sample_meta=SAMPLE_META,
            sample_sequences=SAMPLE_SEQUENCES,
            near_tied_fractions=NEAR_TIED_FRACTIONS,
        )
        comparison = summaries.compare_builds(
            {"hg38": summary_hg38, "hg19": summary_hg19},
            {
                "hg38": summaries.exclude_controls(summaries.index_rows_by_sample(PRIMARY_ROWS, mode="primary")),
                "hg19": summaries.exclude_controls(summaries.index_rows_by_sample(primary_rows_hg19, mode="primary")),
            },
        )
        for key in (
            "builds_compared",
            "usable_unique_rate_by_build",
            "exact_unique_rate_by_build",
            "usable_unique_rate_gap_points",
            "primary_category_changed_between_builds",
            "primary_category_compared",
            "coordinate_comparison_note",
        ):
            self.assertIn(key, comparison)
        self.assertEqual(comparison["primary_category_changed_between_builds"], 1)
        self.assertNotIn("loci_changed_between_builds", comparison)
        self.assertNotIn("loci_compared", comparison)

    def test_compare_builds_excludes_controls_from_category_comparison(self):
        # Only the control's category differs between builds; it must not
        # be counted as a build-comparison change.
        primary_rows_hg19 = [
            *PRIMARY_ROWS[:-1],
            _row("control_row_0", "primary", "ambiguous", is_control=True, start="300", end="320"),
        ]
        summary_hg38 = summaries.build_per_build_summary(
            build="hg38", primary_rows=PRIMARY_ROWS, splice_rows=SPLICE_ROWS,
            representative_ids=REPRESENTATIVE_IDS, all_sample_ids=ALL_SAMPLE_IDS,
            sample_meta=SAMPLE_META, sample_sequences=SAMPLE_SEQUENCES, near_tied_fractions=NEAR_TIED_FRACTIONS,
        )
        summary_hg19 = summaries.build_per_build_summary(
            build="hg19", primary_rows=primary_rows_hg19, splice_rows=SPLICE_ROWS,
            representative_ids=REPRESENTATIVE_IDS, all_sample_ids=ALL_SAMPLE_IDS,
            sample_meta=SAMPLE_META, sample_sequences=SAMPLE_SEQUENCES, near_tied_fractions=NEAR_TIED_FRACTIONS,
        )
        comparison = summaries.compare_builds(
            {"hg38": summary_hg38, "hg19": summary_hg19},
            {
                "hg38": summaries.exclude_controls(summaries.index_rows_by_sample(PRIMARY_ROWS, mode="primary")),
                "hg19": summaries.exclude_controls(summaries.index_rows_by_sample(primary_rows_hg19, mode="primary")),
            },
        )
        self.assertEqual(comparison["primary_category_changed_between_builds"], 0)


if __name__ == "__main__":
    unittest.main()
