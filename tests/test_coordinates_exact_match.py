import unittest
from pathlib import Path

from rbpbench.coordinates.exact_match import (
    exact_occurrence_count,
    exact_unique_confirmed,
    parse_seqkit_bed,
)

FIXTURE = Path(__file__).parent / "fixtures" / "coordinates" / "tiny_seqkit_hits.bed"


class ExactMatchTests(unittest.TestCase):
    def test_parse_seqkit_bed_groups_by_sample_id(self):
        occurrences = parse_seqkit_bed(FIXTURE.read_text().splitlines())
        self.assertEqual(exact_occurrence_count(occurrences, "row_1"), 1)
        self.assertEqual(exact_occurrence_count(occurrences, "row_2"), 2)
        self.assertEqual(exact_occurrence_count(occurrences, "row_missing"), 0)

    def test_single_invocation_minus_strand_hit_is_one_occurrence(self):
        # Regression for review R6: a single genomic occurrence found only on
        # the reference's minus strand must count as exactly one occurrence,
        # from one seqkit invocation's both-strand-labeled BED output.
        occurrences = parse_seqkit_bed(["chr3\t500\t520\trow_9\t.\t-"])
        self.assertEqual(exact_occurrence_count(occurrences, "row_9"), 1)

    def test_double_invocation_pattern_would_wrongly_double_count(self):
        # Documents exactly the bug this module no longer permits: unioning a
        # forward-query BED result with a second reverse-complemented-query
        # BED result for the same real occurrence yields two strand-distinct
        # tuples instead of one. There is no merge helper in this module
        # precisely because that second invocation must never be made; this
        # test guards the reasoning, not a code path.
        forward_query_hit = parse_seqkit_bed(["chr1\t100\t120\trow_1\t.\t-"])
        revcomp_query_hit = parse_seqkit_bed(["chr1\t100\t120\trow_1\t.\t+"])
        naive_union = forward_query_hit["row_1"] | revcomp_query_hit["row_1"]
        self.assertEqual(len(naive_union), 2)
        self.assertEqual(exact_occurrence_count(forward_query_hit, "row_1"), 1)

    def test_exact_unique_requires_primary_agreement(self):
        self.assertTrue(exact_unique_confirmed(primary_is_perfect_unique=True, occurrence_count=1))
        self.assertFalse(exact_unique_confirmed(primary_is_perfect_unique=True, occurrence_count=2))
        self.assertFalse(exact_unique_confirmed(primary_is_perfect_unique=False, occurrence_count=1))

    def test_malformed_line_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_seqkit_bed(["chr1\t100\t120"])


if __name__ == "__main__":
    unittest.main()
