import tempfile
import unittest
from pathlib import Path

from rbpbench.data.inventory import build_inventory, read_path_list


class InventoryTests(unittest.TestCase):
    def test_inventory_is_complete_and_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text("content")
            listing = root / "files.txt"
            listing.write_text("# comment\nsource.txt\n")
            paths = read_path_list(listing)
            report = build_inventory(paths, root)
            self.assertEqual(report["files"][0]["path"], "source.txt")
            self.assertEqual(report["files"][0]["size_bytes"], 7)
            self.assertEqual(len(report["files"][0]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
