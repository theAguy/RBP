import unittest
from pathlib import Path

from rbpbench.coordinates.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_loads_frozen_project_config(self):
        cfg = load_config(REPO_ROOT / "configs" / "coordinate_feasibility.toml")
        self.assertEqual(cfg.sampling.seed, 20260916)
        self.assertEqual(cfg.sampling.total_size, 10000)
        self.assertEqual(cfg.sampling.representative_size, 5000)
        self.assertEqual(cfg.controls.count, 100)
        self.assertEqual(cfg.tools.bwa_version, "0.7.19")
        self.assertEqual(cfg.tools.minimap2_version, "2.31")
        self.assertEqual(cfg.tools.seqkit_version, "2.13.0")
        self.assertEqual(cfg.thresholds.high_conf_min_coverage, 0.98)
        self.assertEqual(cfg.near_tied_fractions, (0.02, 0.05, 0.10))
        self.assertEqual(cfg.resources.max_threads, 4)
        self.assertIn("alt_haplotype", cfg.contig_policy.exclude_categories)

    def test_loads_tiny_fixture_config(self):
        cfg = load_config(REPO_ROOT / "tests" / "fixtures" / "coordinates" / "tiny_coordinate_feasibility.toml")
        self.assertEqual(cfg.sampling.total_size, 20)
        self.assertEqual(cfg.sequence_length_nt, 20)


if __name__ == "__main__":
    unittest.main()
