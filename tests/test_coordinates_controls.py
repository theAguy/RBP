import random
import unittest

from rbpbench.coordinates.controls import dinucleotide_counts, dinucleotide_shuffle, generate_control
from rbpbench.coordinates.hashing import control_seed


SEQUENCE = "ACGTACGGTTACAGCTAGCATCGATCGATCGTAGCTAGCTGATCGATCGTAGCATCGTA"


class ControlsTests(unittest.TestCase):
    def test_shuffle_preserves_dinucleotide_composition(self):
        shuffled = dinucleotide_shuffle(SEQUENCE, random.Random(42))
        self.assertEqual(dinucleotide_counts(shuffled), dinucleotide_counts(SEQUENCE))

    def test_shuffle_preserves_first_and_last_base(self):
        shuffled = dinucleotide_shuffle(SEQUENCE, random.Random(7))
        self.assertEqual(shuffled[0], SEQUENCE[0])
        self.assertEqual(shuffled[-1], SEQUENCE[-1])

    def test_shuffle_changes_the_sequence(self):
        shuffled = dinucleotide_shuffle(SEQUENCE, random.Random(7))
        self.assertNotEqual(shuffled, SEQUENCE)

    def test_generate_control_is_reproducible(self):
        seed_fn = lambda attempt: control_seed(20260916, "row_1", attempt)
        first = generate_control(SEQUENCE, seed_fn=seed_fn)
        second = generate_control(SEQUENCE, seed_fn=seed_fn)
        self.assertEqual(first, second)
        self.assertNotEqual(first, SEQUENCE)
        self.assertEqual(dinucleotide_counts(first), dinucleotide_counts(SEQUENCE))

    def test_generate_control_fails_closed_when_no_shuffle_differs(self):
        # A homopolymer's only Eulerian path is itself: must raise, not
        # silently accept an identical "control".
        with self.assertRaises(RuntimeError):
            generate_control("AAAAAAAAAA", seed_fn=lambda attempt: attempt, max_attempts=5)


if __name__ == "__main__":
    unittest.main()
