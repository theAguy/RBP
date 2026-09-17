import unittest

from rbpbench.coordinates.alignment import (
    ClassificationThresholds,
    build_candidate_loci,
    classify_primary,
    classify_splice,
    is_usable_unique,
    near_tied_secondary_fractions,
    parse_sam_line,
)

THRESHOLDS = ClassificationThresholds(
    high_conf_min_coverage=0.98,
    high_conf_min_identity=0.99,
    secondary_min_coverage=0.90,
    secondary_min_identity=0.95,
)


def sam(qname, flag, rname, pos1, mapq, cigar, nm=None, as_score=None):
    tags = []
    if nm is not None:
        tags.append(f"NM:i:{nm}")
    if as_score is not None:
        tags.append(f"AS:i:{as_score}")
    return "\t".join([qname, str(flag), rname, str(pos1), str(mapq), cigar, "*", "0", "0", "*", "*", *tags])


class SamParsingTests(unittest.TestCase):
    def test_header_line_is_ignored(self):
        self.assertIsNone(parse_sam_line("@HD\tVN:1.6\tSO:coordinate"))

    def test_unmapped_flag_yields_none(self):
        self.assertIsNone(parse_sam_line(sam("read1", 4, "*", 0, 0, "*")))

    def test_mapped_record_parses_strand_and_nm(self):
        record = parse_sam_line(sam("read1", 16, "chr1", 101, 60, "20=", nm=1))
        self.assertEqual(record.chrom, "chr1")
        self.assertEqual(record.pos0, 100)
        self.assertEqual(record.strand, "-")
        self.assertEqual(record.nm, 1)


class ClassifyPrimaryTests(unittest.TestCase):
    def test_perfect_unique_is_exact_when_confirmed(self):
        record = parse_sam_line(sam("read1", 0, "chr1", 101, 60, "20="))
        loci = build_candidate_loci([record], total_query_bases=20)
        self.assertEqual(classify_primary(loci, THRESHOLDS, exact_confirmed=True), "exact_unique")

    def test_perfect_unique_without_exact_confirmation_is_high_conf(self):
        record = parse_sam_line(sam("read1", 0, "chr1", 101, 60, "20="))
        loci = build_candidate_loci([record], total_query_bases=20)
        self.assertEqual(classify_primary(loci, THRESHOLDS, exact_confirmed=False), "high_conf_unique")

    def test_boundary_identity_is_high_conf_not_exact(self):
        # 99/100 identity, 100% coverage: meets high-conf exactly, not exact.
        record = parse_sam_line(sam("read2", 0, "chr1", 201, 60, "99=1X"))
        loci = build_candidate_loci([record], total_query_bases=100)
        self.assertEqual(classify_primary(loci, THRESHOLDS, exact_confirmed=True), "high_conf_unique")

    def test_plausible_distinct_secondary_yields_ambiguous(self):
        best = parse_sam_line(sam("read3", 0, "chr1", 301, 60, "99=1X"))
        secondary = parse_sam_line(sam("read3", 256, "chr5", 501, 10, "90=10S"))
        loci = build_candidate_loci([best, secondary], total_query_bases=100)
        self.assertEqual(classify_primary(loci, THRESHOLDS, exact_confirmed=False), "ambiguous")

    def test_below_high_conf_threshold_is_low_quality(self):
        record = parse_sam_line(sam("read4", 0, "chr1", 401, 60, "80=20S"))
        loci = build_candidate_loci([record], total_query_bases=100)
        self.assertEqual(classify_primary(loci, THRESHOLDS, exact_confirmed=False), "low_quality")

    def test_no_alignment_is_unmapped(self):
        self.assertEqual(classify_primary([], THRESHOLDS, exact_confirmed=False), "unmapped")

    def test_hard_clipped_supplementary_blocks_merge_when_collinear(self):
        primary = parse_sam_line(sam("read6", 0, "chr2", 1000, 60, "50=50S"))
        supplementary = parse_sam_line(sam("read6", 2048, "chr2", 1101, 60, "50H50="))
        loci = build_candidate_loci([primary, supplementary], total_query_bases=100)
        self.assertEqual(len(loci), 1)
        self.assertEqual(loci[0].block_count, 2)
        self.assertEqual(loci[0].coverage, 1.0)
        self.assertEqual(loci[0].identity, 1.0)
        self.assertEqual(classify_primary(loci, THRESHOLDS, exact_confirmed=True), "exact_unique")

    def test_non_collinear_blocks_are_not_merged(self):
        # Second block's query span overlaps the first's almost entirely and
        # its reference position runs backwards: not a valid split read.
        primary = parse_sam_line(sam("read7", 0, "chr2", 1000, 60, "50=50S"))
        overlapping = parse_sam_line(sam("read7", 2048, "chr2", 900, 60, "50H50="))
        loci = build_candidate_loci([primary, overlapping], total_query_bases=100)
        self.assertEqual(len(loci), 2)

    def test_reverse_strand_template_coordinates_are_flipped(self):
        record = parse_sam_line(sam("read8", 16, "chr1", 501, 60, "10S10="))
        loci = build_candidate_loci([record], total_query_bases=20)
        block = loci[0].blocks[0]
        self.assertEqual((block.template_query_start, block.template_query_end), (0, 10))


class ClassifySpliceTests(unittest.TestCase):
    def test_two_block_intron_gap_is_spliced_unique(self):
        record = parse_sam_line(sam("read9", 0, "chr3", 2001, 60, "50=200N50="))
        loci = build_candidate_loci([record], total_query_bases=100)
        self.assertEqual(loci[0].block_count, 2)
        self.assertEqual(classify_splice(loci, THRESHOLDS), "spliced_unique")

    def test_single_block_is_unspliced_unique(self):
        record = parse_sam_line(sam("read10", 0, "chr3", 3001, 60, "100="))
        loci = build_candidate_loci([record], total_query_bases=100)
        self.assertEqual(classify_splice(loci, THRESHOLDS), "unspliced_unique")

    def test_splice_never_reports_exact_unique(self):
        record = parse_sam_line(sam("read11", 0, "chr3", 4001, 60, "100="))
        loci = build_candidate_loci([record], total_query_bases=100)
        self.assertNotEqual(classify_splice(loci, THRESHOLDS), "exact_unique")

    def test_no_alignment_is_unmapped(self):
        self.assertEqual(classify_splice([], THRESHOLDS), "unmapped")


class BwaPlainCigarIdentityTests(unittest.TestCase):
    """Regression coverage for the real BWA-MEM 'M'+NM output shape (review R1):
    a bare 'M' CIGAR does not itself distinguish matches from mismatches, so
    identity/coverage must be derived from NM, insertions, and deletions
    rather than defaulting to zero when no extended ('=/X') CIGAR is present.
    """

    def test_perfect_500m_with_nm_zero_is_full_identity(self):
        record = parse_sam_line(sam("read1", 0, "chr1", 1, 60, "500M", nm=0))
        loci = build_candidate_loci([record], total_query_bases=500)
        self.assertEqual(loci[0].coverage, 1.0)
        self.assertEqual(loci[0].identity, 1.0)
        self.assertEqual(classify_primary(loci, THRESHOLDS, exact_confirmed=True), "exact_unique")

    def test_plain_m_with_mismatches_reduces_identity_not_to_zero(self):
        # 500M with NM:i:5 (5 substitutions, no indels): identity 495/500.
        record = parse_sam_line(sam("read2", 0, "chr1", 1, 60, "500M", nm=5))
        loci = build_candidate_loci([record], total_query_bases=500)
        self.assertAlmostEqual(loci[0].identity, 495 / 500)
        self.assertEqual(loci[0].coverage, 1.0)

    def test_plain_m_with_insertion_counts_indel_in_identity_denominator(self):
        # 480M20I, NM:i:20 (20 inserted bases, 0 mismatches): coverage stays
        # 1.0 (all query bases aligned or inserted) but identity drops
        # because the insertion enters the identity denominator.
        record = parse_sam_line(sam("read3", 0, "chr1", 1, 60, "480M20I", nm=20))
        loci = build_candidate_loci([record], total_query_bases=500)
        self.assertEqual(loci[0].coverage, 1.0)
        self.assertAlmostEqual(loci[0].identity, 480 / 500)

    def test_plain_m_with_deletion_counts_indel_in_identity_denominator(self):
        # 250M20D250M, NM:i:20 (20 deleted reference bases, 0 mismatches):
        # coverage is unaffected (deletions do not consume query bases) but
        # identity drops because the deletion enters the denominator.
        record = parse_sam_line(sam("read4", 0, "chr1", 1, 60, "250M20D250M", nm=20))
        loci = build_candidate_loci([record], total_query_bases=500)
        self.assertEqual(loci[0].coverage, 1.0)
        self.assertAlmostEqual(loci[0].identity, 500 / 520)

    def test_plain_m_with_soft_clip_reduces_coverage_not_identity(self):
        # 50S450M, NM:i:0: 450/500 query bases aligned (coverage 0.9), but
        # the aligned portion is a perfect match (identity 1.0).
        record = parse_sam_line(sam("read5", 0, "chr1", 1, 60, "50S450M", nm=0))
        loci = build_candidate_loci([record], total_query_bases=500)
        self.assertAlmostEqual(loci[0].coverage, 0.9)
        self.assertEqual(loci[0].identity, 1.0)
        self.assertEqual(classify_primary(loci, THRESHOLDS, exact_confirmed=True), "low_quality")


class CandidateSelectionEvidenceTests(unittest.TestCase):
    """Coverage for review R2: preserve AS/MAPQ/primary-secondary-supplementary
    status, select the best candidate with primary/AS evidence rather than
    coverage alone, and never double-count overlapping supplementary blocks.
    """

    def test_blocks_and_loci_retain_mapq_as_and_primary_flag(self):
        record = parse_sam_line(sam("read1", 0, "chr1", 1, 45, "100M", nm=0, as_score=98))
        loci = build_candidate_loci([record], total_query_bases=100)
        self.assertEqual(loci[0].mapq, 45)
        self.assertEqual(loci[0].as_score, 98)
        self.assertTrue(loci[0].is_primary)
        self.assertEqual(loci[0].blocks[0].mapq, 45)
        self.assertEqual(loci[0].blocks[0].as_score, 98)

    def test_best_selection_prefers_primary_flag_over_raw_coverage(self):
        # The secondary record has slightly higher coverage than the primary
        # one; primary/AS evidence must still win the "best" slot, not the
        # naive higher-coverage candidate.
        primary = parse_sam_line(sam("read2", 0, "chr1", 1, 60, "95M5S", nm=0, as_score=90))
        secondary = parse_sam_line(sam("read2", 256, "chr9", 1, 60, "100M", nm=0, as_score=85))
        loci = build_candidate_loci([primary, secondary], total_query_bases=100)
        self.assertTrue(loci[0].is_primary)
        self.assertEqual(loci[0].chrom, "chr1")

    def test_best_selection_breaks_ties_by_alignment_score(self):
        # Both records are flagged primary-eligible (neither secondary nor
        # supplementary) with identical coverage/identity; the one with the
        # higher AS must be selected as best.
        low_as = parse_sam_line(sam("read3", 0, "chr1", 1, 60, "100M", nm=0, as_score=80))
        high_as = parse_sam_line(sam("read3", 0, "chr2", 1, 60, "100M", nm=0, as_score=95))
        loci = build_candidate_loci([low_as, high_as], total_query_bases=100)
        self.assertEqual(loci[0].chrom, "chr2")
        self.assertEqual(loci[0].as_score, 95)

    def test_overlapping_supplementary_blocks_are_not_double_counted(self):
        # Primary covers query [0,60); supplementary (collinear, within the
        # 5nt tolerance) covers [55,100), overlapping the primary by 5nt.
        # Total aligned query bases must be 100, not 105.
        primary = parse_sam_line(sam("read4", 0, "chr1", 1, 60, "60M40S", nm=0))
        supplementary = parse_sam_line(sam("read4", 2048, "chr1", 56, 60, "55H45M", nm=0))
        loci = build_candidate_loci([primary, supplementary], total_query_bases=100)
        self.assertEqual(len(loci), 1)
        self.assertEqual(loci[0].aligned_query_bases, 100)
        self.assertEqual(loci[0].coverage, 1.0)
        self.assertLessEqual(loci[0].identity, 1.0)

    def test_near_tied_score_gap_sensitivity_reports_each_configured_fraction(self):
        best = parse_sam_line(sam("read5", 0, "chr1", 1, 60, "100M", nm=0, as_score=100))
        near = parse_sam_line(sam("read5", 256, "chr2", 1, 60, "100M", nm=0, as_score=93))
        loci = build_candidate_loci([best, near], total_query_bases=100)
        result = near_tied_secondary_fractions(loci, (0.02, 0.05, 0.10))
        # 93 is a 7% gap from 100: not near-tied at 2% or 5%, but is at 10%.
        self.assertEqual(result, {0.02: False, 0.05: False, 0.10: True})

    def test_near_tied_sensitivity_is_false_without_scores(self):
        record = parse_sam_line(sam("read6", 0, "chr1", 1, 60, "100M", nm=0))
        loci = build_candidate_loci([record], total_query_bases=100)
        result = near_tied_secondary_fractions(loci, (0.02, 0.05, 0.10))
        self.assertEqual(result, {0.02: False, 0.05: False, 0.10: False})


class UsableUniqueGateTests(unittest.TestCase):
    def test_primary_exact_or_high_conf_is_usable(self):
        self.assertTrue(is_usable_unique("exact_unique", None))
        self.assertTrue(is_usable_unique("high_conf_unique", "low_quality"))

    def test_splice_rescue_only_applies_when_primary_unusable(self):
        self.assertTrue(is_usable_unique("low_quality", "spliced_unique"))
        self.assertTrue(is_usable_unique("ambiguous", "spliced_unique"))

    def test_unspliced_unique_never_rescues(self):
        self.assertFalse(is_usable_unique("low_quality", "unspliced_unique"))

    def test_unmapped_without_rescue_is_not_usable(self):
        self.assertFalse(is_usable_unique("unmapped", "unmapped"))


if __name__ == "__main__":
    unittest.main()
