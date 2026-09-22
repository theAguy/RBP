import unittest

from rbpbench.coordinates.decode import (
    decode_and_validate,
    decode_sequence,
    encode_sequence,
    fasta_record,
    reverse_complement,
)


class DecodeTests(unittest.TestCase):
    def test_decode_basic(self):
        # A=1000, C=0100, G=0010, T=0001
        self.assertEqual(decode_sequence("1000010000100001"), "ACGT")

    def test_round_trip_is_confirmed(self):
        bits = "1000010000100001"
        self.assertEqual(decode_and_validate(bits), "ACGT")
        self.assertEqual(encode_sequence("ACGT"), bits)

    def test_rejects_invalid_length(self):
        with self.assertRaises(ValueError):
            decode_sequence("100")

    def test_rejects_non_binary_character(self):
        with self.assertRaises(ValueError):
            decode_sequence("1000X100")

    def test_rejects_non_one_hot_group(self):
        with self.assertRaises(ValueError):
            decode_sequence("11000000")  # two 1s in the first group

    def test_never_repairs_silently(self):
        # A group with zero 1s must raise, not default to some base.
        with self.assertRaises(ValueError):
            decode_sequence("00000000")

    def test_reverse_complement(self):
        self.assertEqual(reverse_complement("ACGT"), "ACGT")
        self.assertEqual(reverse_complement("AACG"), "CGTT")

    def test_fasta_record_uses_only_canonical_id(self):
        self.assertEqual(fasta_record("row_7", "ACGT"), ">row_7\nACGT\n")


if __name__ == "__main__":
    unittest.main()
