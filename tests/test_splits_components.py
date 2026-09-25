import random
import unittest

from rbpbench.splits.components import UnionFind, build_components, component_id, component_members, component_sizes


class UnionFindTests(unittest.TestCase):
    def test_union_merges_two_singletons(self):
        uf = UnionFind(["a", "b", "c"])
        uf.union("a", "b")
        self.assertEqual(uf.find("a"), uf.find("b"))
        self.assertNotEqual(uf.find("a"), uf.find("c"))

    def test_transitive_a_b_c_never_splits_a_and_c(self):
        uf = UnionFind(["a", "b", "c", "d"])
        uf.union("a", "b")
        uf.union("b", "c")
        self.assertEqual(uf.find("a"), uf.find("c"))
        self.assertNotEqual(uf.find("a"), uf.find("d"))

    def test_root_choice_is_order_independent(self):
        uf1 = UnionFind(["x", "y", "z"])
        uf1.union("x", "y")
        uf1.union("y", "z")
        uf2 = UnionFind(["x", "y", "z"])
        uf2.union("z", "y")
        uf2.union("y", "x")
        self.assertEqual(uf1.groups(), uf2.groups())


class ComponentIdTests(unittest.TestCase):
    def test_id_depends_only_on_sorted_membership(self):
        self.assertEqual(component_id(["row_2", "row_0", "row_1"]), component_id(["row_0", "row_1", "row_2"]))

    def test_different_membership_yields_different_id(self):
        self.assertNotEqual(component_id(["row_0", "row_1"]), component_id(["row_0", "row_1", "row_2"]))

    def test_id_is_not_a_tool_serial_number(self):
        # A component ID must be a content hash, not e.g. "1"/"2"/"3".
        cid = component_id(["row_0", "row_1"])
        self.assertGreater(len(cid), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in cid))


class BuildComponentsTests(unittest.TestCase):
    def test_unions_across_multiple_edge_groups_including_transitive_chain(self):
        ids = ["row_a", "row_b", "row_c", "row_d", "row_e"]
        # width-500 clustering unions a-b; width-251 clustering unions b-c
        # (simulating a shifted-overlap match visible only at one crop);
        # canonical-hash duplicates union d-e independently.
        edge_groups = [
            [("row_a", "row_b")],
            [("row_b", "row_c")],
            [("row_d", "row_e")],
        ]
        assignment = build_components(ids, edge_groups)
        self.assertEqual(assignment["row_a"], assignment["row_c"])  # never split A and C
        self.assertEqual(assignment["row_a"], assignment["row_b"])
        self.assertEqual(assignment["row_d"], assignment["row_e"])
        self.assertNotEqual(assignment["row_a"], assignment["row_d"])

    def test_unrelated_rows_remain_singleton_components(self):
        ids = ["row_0", "row_1", "row_2"]
        assignment = build_components(ids, [[]])
        self.assertEqual(len({assignment[i] for i in ids}), 3)

    def test_memberships_and_component_ids_are_input_order_independent(self):
        ids = ["row_0", "row_1", "row_2", "row_3"]
        edge_groups = [[("row_0", "row_1")], [("row_2", "row_3")]]

        rng = random.Random(42)
        shuffled_ids = list(ids)
        rng.shuffle(shuffled_ids)
        shuffled_edges = [[(b, a) for a, b in group] for group in reversed(edge_groups)]

        first = build_components(ids, edge_groups)
        second = build_components(shuffled_ids, shuffled_edges)
        self.assertEqual(first, second)

    def test_no_component_splitting_when_edges_span_all_three_widths(self):
        # A single similarity component built from edges discovered at
        # different window sizes must remain one component, not three.
        ids = ["row_full_only", "row_251_only", "row_101_only"]
        edge_groups = [
            [("row_full_only", "row_251_only")],  # found only at 500 nt
            [("row_251_only", "row_101_only")],  # found only at 251 nt
            [],  # nothing new found at 101 nt
        ]
        assignment = build_components(ids, edge_groups)
        self.assertEqual(len({assignment[i] for i in ids}), 1)

    def test_component_sizes_and_members_helpers(self):
        ids = ["row_0", "row_1", "row_2"]
        assignment = build_components(ids, [[("row_0", "row_1")]])
        sizes = component_sizes(assignment)
        members = component_members(assignment)
        self.assertEqual(sizes[assignment["row_0"]], 2)
        self.assertEqual(sizes[assignment["row_2"]], 1)
        self.assertEqual(members[assignment["row_0"]], ["row_0", "row_1"])


if __name__ == "__main__":
    unittest.main()
