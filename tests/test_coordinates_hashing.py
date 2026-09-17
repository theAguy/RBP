import unittest

from rbpbench.coordinates.hashing import control_seed, label_blind_rank, quota_rank, stable_hash_rank


class HashingTests(unittest.TestCase):
    def test_stable_hash_rank_is_deterministic_across_calls(self):
        self.assertEqual(stable_hash_rank(20260916, "row_1"), stable_hash_rank(20260916, "row_1"))

    def test_stable_hash_rank_distinguishes_field_boundaries(self):
        # Naive concatenation would collide "a"+"bc" with "ab"+"c"; the unit
        # separator must keep them distinct.
        self.assertNotEqual(stable_hash_rank("a", "bc"), stable_hash_rank("ab", "c"))

    def test_label_blind_rank_ignores_extraneous_state(self):
        self.assertEqual(label_blind_rank(1, "row_5"), label_blind_rank(1, "row_5"))
        self.assertNotEqual(label_blind_rank(1, "row_5"), label_blind_rank(2, "row_5"))

    def test_quota_rank_depends_on_protein_and_class(self):
        a = quota_rank(1, "row_5", 3, "positive")
        b = quota_rank(1, "row_5", 3, "negative")
        c = quota_rank(1, "row_5", 4, "positive")
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)

    def test_control_seed_varies_by_attempt(self):
        seeds = {control_seed(1, "row_1", attempt) for attempt in range(5)}
        self.assertEqual(len(seeds), 5)


if __name__ == "__main__":
    unittest.main()
