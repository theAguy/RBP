import unittest
from pathlib import Path

from rbpbench.splits.config_002c import load_config_002c

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "splits" / "sequence_partitions_002c_v1.toml"


class LoadConfig002CTests(unittest.TestCase):
    def test_loads_every_required_section(self):
        config = load_config_002c(_CONFIG_PATH)
        self.assertEqual(config.seed, 20260925)
        self.assertEqual(config.protected_widths, (500, 251, 101))
        self.assertEqual(config.dataset.expected_row_count, 361180)
        self.assertEqual(config.components_002b.expected_component_count, 173465)
        self.assertEqual(config.assignment.evaluation_floor, 30)
        self.assertEqual(config.assignment.row_dimension_weight, 244)
        self.assertEqual(config.assignment.protein_class_dimension_weight, 1)
        self.assertGreater(config.assignment.max_repair_passes, 0)
        self.assertEqual(config.legacy_diagnostic.n_splits, 5)
        self.assertTrue(config.legacy_diagnostic.shuffle)
        self.assertEqual(config.legacy_diagnostic.random_state, 42)
        self.assertEqual(config.legacy_diagnostic.fold_index, 0)
        self.assertEqual(config.audit.max_threads, 4)
        self.assertEqual(config.binary.mmseqs_sha256, "44afaca1d6d8a4c7709177782aa37203cd52651563c778d75f9ae2ee98bed635")

    def test_content_hash_is_stable_across_loads(self):
        first = load_config_002c(_CONFIG_PATH)
        second = load_config_002c(_CONFIG_PATH)
        self.assertEqual(first.content_hash, second.content_hash)

    def test_target_fractions_sum_to_one(self):
        config = load_config_002c(_CONFIG_PATH)
        self.assertAlmostEqual(sum(config.assignment.target_fractions.values()), 1.0)

    def test_never_shares_a_config_file_with_task_002b(self):
        task_002b_path = _CONFIG_PATH.parent / "sequence_partitions_v1.toml"
        self.assertNotEqual(_CONFIG_PATH, task_002b_path)
        self.assertTrue(task_002b_path.is_file())  # Task 002B's own config remains untouched/present


if __name__ == "__main__":
    unittest.main()
