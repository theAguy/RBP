import tempfile
import unittest
from pathlib import Path

from rbpbench.splits.config import load_config


_TOML = """
seed = 20260925
protected_widths = [500, 251, 101]

[dataset]
csv_filename = "tiny.csv"
csv_sha256 = "deadbeef"
csv_byte_size = 123
expected_row_count = 4
audit_json_path = "audit.json"
audit_json_sha256 = "beadfeed"
proteins_tsv_path = "proteins.tsv"
proteins_tsv_sha256 = "cafef00d"

[resources]
max_threads = 4
timeout_seconds = 60
max_new_disk_gib = 1.0
min_free_disk_gib = 0.001

[probe]
sample_size = 2
max_peak_memory_gib = 10.0
min_available_memory_gib_before_next_stage = 0.001

[gate]
giant_single_component_fraction = 0.05
giant_top20_fraction = 0.20
"""


class LoadConfigTests(unittest.TestCase):
    def test_loads_every_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.toml"
            path.write_text(_TOML)
            config = load_config(path)
            self.assertEqual(config.seed, 20260925)
            self.assertEqual(config.protected_widths, (500, 251, 101))
            self.assertEqual(config.dataset.csv_filename, "tiny.csv")
            self.assertEqual(config.dataset.expected_row_count, 4)
            self.assertEqual(config.resources.max_threads, 4)
            self.assertEqual(config.probe.sample_size, 2)
            self.assertEqual(config.gate.giant_top20_fraction, 0.20)

    def test_content_hash_changes_when_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.toml"
            path.write_text(_TOML)
            first = load_config(path)
            path.write_text(_TOML.replace("sample_size = 2", "sample_size = 3"))
            second = load_config(path)
            self.assertNotEqual(first.content_hash, second.content_hash)

    def test_no_scientific_identity_or_coverage_fields_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.toml"
            path.write_text(_TOML)
            config = load_config(path)
            for forbidden in ("min_seq_id", "coverage", "max_seqs", "cov_mode"):
                self.assertFalse(hasattr(config, forbidden))
                self.assertFalse(hasattr(config.resources, forbidden))


if __name__ == "__main__":
    unittest.main()
