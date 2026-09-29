import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rbpbench.splits.mmseqs_audit import (
    ORDERED_PARTITION_PAIRS,
    DirectedAuditResult,
    ForeignAuditSearchEndpointError,
    InvalidDirectionError,
    SelfHitCorruptionError,
    build_partition_fasta_subset,
    parse_search_hits,
    reconcile_directed_hits,
    selection_key,
    validate_direction,
)


class ValidateDirectionTests(unittest.TestCase):
    def test_distinct_valid_partitions_are_accepted(self):
        validate_direction("train", "validation")  # should not raise

    def test_same_partition_twice_is_rejected(self):
        with self.assertRaises(InvalidDirectionError):
            validate_direction("train", "train")

    def test_unknown_partition_is_rejected(self):
        with self.assertRaises(InvalidDirectionError):
            validate_direction("train", "holdout")


class SelectionKeyTests(unittest.TestCase):
    def test_key_includes_width_and_both_directions_distinctly(self):
        forward = selection_key("audit_search", 500, "train", "validation")
        backward = selection_key("audit_search", 500, "validation", "train")
        self.assertEqual(forward, "audit_search_500_train_to_validation")
        self.assertEqual(backward, "audit_search_500_validation_to_train")
        self.assertNotEqual(forward, backward)

    def test_all_18_directed_keys_are_distinct(self):
        keys = {
            selection_key("audit_search", width, query, target)
            for width in (500, 251, 101)
            for query, target in ORDERED_PARTITION_PAIRS
        }
        self.assertEqual(len(keys), 18)

    def test_ordered_partition_pairs_cover_both_directions_of_every_unordered_pair(self):
        unordered = {frozenset(pair) for pair in ORDERED_PARTITION_PAIRS}
        self.assertEqual(unordered, {frozenset(("train", "validation")), frozenset(("train", "test")), frozenset(("validation", "test"))})
        self.assertEqual(len(ORDERED_PARTITION_PAIRS), 6)


class BuildPartitionFastaSubsetTests(unittest.TestCase):
    def test_selects_only_the_named_partitions_members(self):
        sequences = {"row_0": "AAAA", "row_1": "CCCC", "row_2": "GGGG"}
        partitions = {"row_0": "train", "row_1": "validation", "row_2": "train"}
        subset = build_partition_fasta_subset(sequences, partitions, "train")
        self.assertEqual(set(subset), {"row_0", "row_2"})


class ParseSearchHitsTests(unittest.TestCase):
    def test_parses_query_target_columns(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "hits.tsv"
            path.write_text("row_0\trow_5\nrow_1\trow_6\n")
            hits = parse_search_hits(path)
            self.assertEqual(hits, [("row_0", "row_5"), ("row_1", "row_6")])

    def test_blank_lines_are_skipped(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "hits.tsv"
            path.write_text("row_0\trow_5\n\nrow_1\trow_6\n")
            hits = parse_search_hits(path)
            self.assertEqual(len(hits), 2)

    def test_malformed_line_raises(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "hits.tsv"
            path.write_text("row_0_only_one_column\n")
            with self.assertRaises(ValueError):
                parse_search_hits(path)


class ReconcileDirectedHitsTests(unittest.TestCase):
    def test_no_hits_passes(self):
        result = reconcile_directed_hits(
            [], width=500, query_partition="train", target_partition="validation",
            query_universe=["row_0"], target_universe=["row_1"],
        )
        self.assertIsInstance(result, DirectedAuditResult)
        self.assertTrue(result.passed)
        self.assertEqual(result.hit_count, 0)

    def test_a_qualifying_hit_between_disjoint_universes_is_a_violation(self):
        result = reconcile_directed_hits(
            [("row_0", "row_1")], width=500, query_partition="train", target_partition="validation",
            query_universe=["row_0"], target_universe=["row_1"],
        )
        self.assertFalse(result.passed)
        self.assertEqual(len(result.violations), 1)

    def test_query_endpoint_outside_query_universe_raises(self):
        with self.assertRaises(ForeignAuditSearchEndpointError):
            reconcile_directed_hits(
                [("row_99", "row_1")], width=500, query_partition="train", target_partition="validation",
                query_universe=["row_0"], target_universe=["row_1"],
            )

    def test_target_endpoint_outside_target_universe_raises(self):
        with self.assertRaises(ForeignAuditSearchEndpointError):
            reconcile_directed_hits(
                [("row_0", "row_99")], width=500, query_partition="train", target_partition="validation",
                query_universe=["row_0"], target_universe=["row_1"],
            )

    def test_identical_query_and_target_id_raises_self_hit_corruption_by_default(self):
        with self.assertRaises(SelfHitCorruptionError):
            reconcile_directed_hits(
                [("row_0", "row_0")], width=500, query_partition="train", target_partition="validation",
                query_universe=["row_0"], target_universe=["row_0"],
            )

    def test_self_hit_removal_is_opt_in_and_test_only(self):
        result = reconcile_directed_hits(
            [("row_0", "row_0")], width=500, query_partition="train", target_partition="validation",
            query_universe=["row_0"], target_universe=["row_0"],
            allow_self_hit_removal_test_only=True,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.hit_count, 1)  # counted in hit_count, but not a violation
        self.assertEqual(len(result.violations), 0)

    def test_invalid_direction_raises_before_any_hit_processing(self):
        with self.assertRaises(InvalidDirectionError):
            reconcile_directed_hits(
                [("row_0", "row_1")], width=500, query_partition="train", target_partition="train",
                query_universe=["row_0"], target_universe=["row_1"],
            )


if __name__ == "__main__":
    unittest.main()
