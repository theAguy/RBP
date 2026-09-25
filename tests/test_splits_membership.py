import unittest

from rbpbench.splits.membership import (
    MembershipReconciliationError,
    membership_edges,
    parse_cluster_tsv_lines,
    reconcile_membership,
)


class ParseClusterTsvLinesTests(unittest.TestCase):
    def test_parses_representative_member_rows(self):
        lines = ["row_0\trow_0", "row_0\trow_1", "row_2\trow_2"]
        membership = parse_cluster_tsv_lines(lines)
        self.assertEqual(membership, {"row_0": "row_0", "row_1": "row_0", "row_2": "row_2"})

    def test_blank_lines_are_ignored(self):
        lines = ["row_0\trow_0", "", "row_0\trow_1", ""]
        membership = parse_cluster_tsv_lines(lines)
        self.assertEqual(membership, {"row_0": "row_0", "row_1": "row_0"})

    def test_malformed_line_raises(self):
        with self.assertRaises(MembershipReconciliationError):
            parse_cluster_tsv_lines(["row_0\trow_0\textra"])

    def test_duplicate_member_id_raises_even_under_same_representative(self):
        with self.assertRaises(MembershipReconciliationError):
            parse_cluster_tsv_lines(["row_0\trow_1", "row_0\trow_1"])

    def test_duplicate_member_id_raises_under_conflicting_representatives(self):
        with self.assertRaises(MembershipReconciliationError):
            parse_cluster_tsv_lines(["row_0\trow_1", "row_2\trow_1"])


class ReconcileMembershipTests(unittest.TestCase):
    def test_exact_match_passes(self):
        membership = {"row_0": "row_0", "row_1": "row_0", "row_2": "row_2"}
        reconcile_membership(membership, {"row_0", "row_1", "row_2"})  # no raise

    def test_missing_id_raises(self):
        membership = {"row_0": "row_0"}
        with self.assertRaises(MembershipReconciliationError) as ctx:
            reconcile_membership(membership, {"row_0", "row_1"})
        self.assertIn("missing", str(ctx.exception))

    def test_foreign_id_raises(self):
        membership = {"row_0": "row_0", "row_99": "row_0"}
        with self.assertRaises(MembershipReconciliationError) as ctx:
            reconcile_membership(membership, {"row_0"})
        self.assertIn("foreign", str(ctx.exception))

    def test_both_missing_and_foreign_are_reported_together(self):
        membership = {"row_0": "row_0", "row_99": "row_0"}
        with self.assertRaises(MembershipReconciliationError) as ctx:
            reconcile_membership(membership, {"row_0", "row_1"})
        message = str(ctx.exception)
        self.assertIn("missing", message)
        self.assertIn("foreign", message)


class MembershipEdgesTests(unittest.TestCase):
    def test_edges_connect_member_to_representative(self):
        membership = {"row_0": "row_0", "row_1": "row_0", "row_2": "row_2"}
        edges = membership_edges(membership)
        self.assertIn(("row_1", "row_0"), edges)
        self.assertIn(("row_2", "row_2"), edges)


if __name__ == "__main__":
    unittest.main()
