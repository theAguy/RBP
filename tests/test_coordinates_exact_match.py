import unittest
from pathlib import Path

from rbpbench.coordinates.exact_match import (
    exact_occurrence_count,
    exact_unique_confirmed,
    merge_both_strand_hits,
    parse_seqkit_bed,
)

FIXTURE = Path(__file__).parent / "fixtures" / "coordinates" / "tiny_seqkit_hits.bed"


class ExactMatchTests(unittest.TestCase):
    def test_parse_seqkit_bed_groups_by_sample_id(self):
        occurrences = parse_seqkit_bed(FIXTURE.read_text().splitlines())
        self.assertEqual(exact_occurrence_count(occurrences, "row_1"), 1)
        self.assertEqual(exact_occurrence_count(occurrences, "row_2"), 2)
        self.assertEqual(exact_occurrence_count(occurrences, "row_missing"), 0)

    def test_merge_both_strand_hits_deduplicates(self):
        forward = {"row_1": {("chr1", 100, 120, "+")}}
        reverse = {"row_1": {("chr1", 100, 120, "+")}, "row_2": {("chr9", 1, 20, "-")}}
        merged = merge_both_strand_hits(forward, reverse)
        self.assertEqual(exact_occurrence_count(merged, "row_1"), 1)
        self.assertEqual(exact_occurrence_count(merged, "row_2"), 1)

    def test_exact_unique_requires_primary_agreement(self):
        self.assertTrue(exact_unique_confirmed(primary_is_perfect_unique=True, occurrence_count=1))
        self.assertFalse(exact_unique_confirmed(primary_is_perfect_unique=True, occurrence_count=2))
        self.assertFalse(exact_unique_confirmed(primary_is_perfect_unique=False, occurrence_count=1))

    def test_malformed_line_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_seqkit_bed(["chr1\t100\t120"])


if __name__ == "__main__":
    unittest.main()
