import random
import unittest

from rbpbench.coordinates.decode import reverse_complement
from rbpbench.splits.hashing import (
    canonical_orientation,
    canonical_sequence_hash,
    duplicate_edges,
    group_by_canonical_hash,
)


def _random_seq(seed: int, width: int = 80) -> str:
    rng = random.Random(seed)
    return "".join(rng.choice("ACGT") for _ in range(width))


class CanonicalOrientationTests(unittest.TestCase):
    def test_sequence_and_its_reverse_complement_share_canonical_form(self):
        seq = _random_seq(1)
        rc = reverse_complement(seq)
        self.assertNotEqual(seq, rc)  # non-palindromic fixture
        self.assertEqual(canonical_orientation(seq), canonical_orientation(rc))

    def test_canonical_hash_is_identical_for_exact_and_reverse_complement_duplicates(self):
        seq = _random_seq(2)
        rc = reverse_complement(seq)
        self.assertEqual(canonical_sequence_hash(seq), canonical_sequence_hash(rc))
        self.assertEqual(canonical_sequence_hash(seq), canonical_sequence_hash(seq))

    def test_unrelated_sequences_hash_differently(self):
        self.assertNotEqual(canonical_sequence_hash(_random_seq(3)), canonical_sequence_hash(_random_seq(4)))


class GroupByCanonicalHashTests(unittest.TestCase):
    def test_exact_and_reverse_complement_duplicates_group_together_at_every_width(self):
        for width in (500, 251, 101):
            seq = _random_seq(10, width)
            rc = reverse_complement(seq)
            other = _random_seq(20, width)
            sequences = {
                "row_0": seq,
                "row_1_exact_dup": seq,
                "row_2_rc_dup": rc,
                "row_3_unrelated": other,
            }
            groups = group_by_canonical_hash(sequences)
            # Exactly two groups: {row_0, row_1, row_2} and {row_3}.
            sizes = sorted(len(members) for members in groups.values())
            self.assertEqual(sizes, [1, 3])
            triple = next(members for members in groups.values() if len(members) == 3)
            self.assertEqual(triple, ["row_0", "row_1_exact_dup", "row_2_rc_dup"])

    def test_grouping_is_independent_of_input_order(self):
        seq = _random_seq(11)
        rc = reverse_complement(seq)
        forward_order = {"row_a": seq, "row_b": rc, "row_c": _random_seq(12)}
        reverse_order = {"row_c": _random_seq(12), "row_b": rc, "row_a": seq}
        self.assertEqual(group_by_canonical_hash(forward_order), group_by_canonical_hash(reverse_order))

    def test_unrelated_rows_remain_separable(self):
        sequences = {f"row_{i}": _random_seq(100 + i) for i in range(5)}
        groups = group_by_canonical_hash(sequences)
        self.assertEqual(len(groups), 5)
        self.assertTrue(all(len(members) == 1 for members in groups.values()))


class DuplicateEdgesTests(unittest.TestCase):
    def test_edges_connect_a_full_duplicate_group_transitively(self):
        seq = _random_seq(30)
        rc = reverse_complement(seq)
        sequences = {"row_x": seq, "row_y": seq, "row_z": rc}
        edges = duplicate_edges(sequences)
        # Union-find over these edges must connect all three members.
        parent = {sid: sid for sid in sequences}

        def find(a):
            while parent[a] != a:
                a = parent[a]
            return a

        for a, b in edges:
            parent[find(a)] = find(b)
        roots = {find(sid) for sid in sequences}
        self.assertEqual(len(roots), 1)

    def test_no_edges_for_an_all_unique_universe(self):
        sequences = {f"row_{i}": _random_seq(200 + i) for i in range(4)}
        self.assertEqual(duplicate_edges(sequences), [])


if __name__ == "__main__":
    unittest.main()
