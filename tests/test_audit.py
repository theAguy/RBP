import tempfile
import unittest
from pathlib import Path

from rbpbench.data.audit import audit_dataset, gc_fraction, parse_labels, rank_auc


FIXTURE = Path(__file__).parent / "fixtures" / "tiny_dataset.csv"


class AuditTests(unittest.TestCase):
    def test_parse_labels_preserves_three_state_contract(self):
        self.assertEqual(parse_labels("1;-2", 2), [1, -2])
        with self.assertRaises(ValueError):
            parse_labels("1;-1", 2)

    def test_gc_fraction_from_acgt_one_hot(self):
        # A=1000, C=0100, so one of two nucleotides is GC.
        self.assertEqual(gc_fraction("10000100", 0, 2), 0.5)

    def test_rank_auc(self):
        self.assertEqual(rank_auc([0, 1], [0.1, 0.9]), 1.0)
        self.assertEqual(rank_auc([0, 1], [0.9, 0.1]), 0.0)
        self.assertEqual(rank_auc([0, 1], [0.5, 0.5]), 0.5)

    def test_tiny_dataset_audit(self):
        report = audit_dataset(
            FIXTURE,
            num_proteins=2,
            sequence_length=2,
            center_length=2,
            strict_group_rows=10,
        )
        self.assertEqual(report["summary"]["rows"], 2)
        self.assertEqual(report["summary"]["known_labels"], 4)
        self.assertEqual(report["per_protein"][0]["positive_count"], 1)
        self.assertEqual(report["per_protein"][0]["negative_count"], 1)


if __name__ == "__main__":
    unittest.main()
