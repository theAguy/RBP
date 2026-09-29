import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rbpbench.splits.config_002c import FrozenInvariantError, load_config_002c

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
        self.assertGreater(config.assignment.max_repair_proposals, 0)
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


class FrozenInvariantValidationTests(unittest.TestCase):
    """Proves every "must drive or be checked" field
    (docs/reviews/002c1_partition_orchestration_correction_review.md, C1)
    is actually enforced at load time, not silently dead.
    """

    def _write_with_replacement(self, old: str, new: str) -> Path:
        text = _CONFIG_PATH.read_text()
        self.assertIn(old, text, f"fixture assumption broken: {old!r} not found in the real config")
        text = text.replace(old, new)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "drifted.toml"
        path.write_text(text)
        return path

    def test_wrong_row_dimension_weight_is_rejected(self):
        path = self._write_with_replacement("row_dimension_weight = 244", "row_dimension_weight = 1")
        with self.assertRaises(FrozenInvariantError):
            load_config_002c(path)

    def test_wrong_protein_class_dimension_weight_is_rejected(self):
        path = self._write_with_replacement("protein_class_dimension_weight = 1", "protein_class_dimension_weight = 2")
        with self.assertRaises(FrozenInvariantError):
            load_config_002c(path)

    def test_wrong_balance_deviation_flag_pct_is_rejected(self):
        path = self._write_with_replacement("balance_deviation_flag_pct = 3.0", "balance_deviation_flag_pct = 5.0")
        with self.assertRaises(FrozenInvariantError):
            load_config_002c(path)

    def test_wrong_legacy_n_splits_is_rejected(self):
        path = self._write_with_replacement("n_splits = 5", "n_splits = 10")
        with self.assertRaises(FrozenInvariantError):
            load_config_002c(path)

    def test_wrong_legacy_random_state_is_rejected(self):
        path = self._write_with_replacement("random_state = 42", "random_state = 7")
        with self.assertRaises(FrozenInvariantError):
            load_config_002c(path)

    def test_wrong_protected_widths_is_rejected(self):
        path = self._write_with_replacement(
            "protected_widths = [500, 251, 101]", "protected_widths = [500, 251, 100]"
        )
        with self.assertRaises(FrozenInvariantError):
            load_config_002c(path)


if __name__ == "__main__":
    unittest.main()
