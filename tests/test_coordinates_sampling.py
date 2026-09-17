import unittest

from rbpbench.coordinates.sampling import DatasetRow, FILLER, QUOTA, REPRESENTATIVE, build_sample

# Mirrors tests/fixtures/coordinates/tiny_coordinates_dataset.csv: 26 rows,
# 2 proteins, with generous label coverage so quotas are always satisfiable
# regardless of which rows the label-blind hash puts in the representative
# stratum.
_LABEL_PLAN = [
    (1, 2), (-1,), (-2,), (1,), (-1, 2), (), (1, -2), (-1,), (2,), (1,),
    (-1, -2), (), (1, 2), (-1,), (-2,), (1,), (-1, 2), (), (1, -2), (-1,),
    (2,), (1,), (-1, -2), (), (1, 2), (-1,),
]

ROWS = [DatasetRow(row_index=i, labels=labels) for i, labels in enumerate(_LABEL_PLAN)]


def build(seed=20260916):
    return build_sample(
        ROWS,
        seed=seed,
        num_proteins=2,
        representative_size=10,
        total_size=20,
        min_positive_per_protein=2,
        min_negative_per_protein=2,
    )


class SamplingTests(unittest.TestCase):
    def test_exact_size_and_uniqueness(self):
        result = build()
        self.assertEqual(len(result.assignments), 20)
        ids = [a.sample_id for a in result.assignments]
        self.assertEqual(len(set(ids)), 20)

    def test_representative_stratum_size(self):
        result = build()
        self.assertEqual(len(result.representative_ids), 10)
        representative_from_assignments = sum(1 for a in result.assignments if a.stratum == REPRESENTATIVE)
        self.assertEqual(representative_from_assignments, 10)

    def test_stratum_partition_covers_every_assignment(self):
        result = build()
        strata = {a.stratum for a in result.assignments}
        self.assertTrue(strata <= {REPRESENTATIVE, QUOTA, FILLER})
        self.assertEqual(
            len(result.representative_ids) + len(result.quota_ids) + len(result.filler_ids),
            len(result.assignments),
        )

    def test_quota_coverage_is_satisfied_on_this_fixture(self):
        result = build()
        self.assertEqual(result.unsatisfied_quotas, ())

    def test_determinism_same_seed_same_sample(self):
        first = build()
        second = build()
        self.assertEqual(first.assignments, second.assignments)

    def test_different_seed_can_change_the_sample(self):
        first = build(seed=20260916)
        other = build(seed=1)
        self.assertNotEqual(
            [a.sample_id for a in first.assignments],
            [a.sample_id for a in other.assignments],
        )

    def test_rejects_insufficient_rows(self):
        with self.assertRaises(ValueError):
            build_sample(
                ROWS[:5],
                seed=1,
                num_proteins=2,
                representative_size=3,
                total_size=20,
                min_positive_per_protein=1,
                min_negative_per_protein=1,
            )


if __name__ == "__main__":
    unittest.main()
