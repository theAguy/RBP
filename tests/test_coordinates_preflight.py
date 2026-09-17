import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.config import ResourceLimits
from rbpbench.coordinates.preflight import APPROVED_MAC, DEV_VM, run_preflight

RESOURCES = ResourceLimits(
    max_threads=4, max_new_disk_gib=30, min_free_disk_gib=80, min_ram_gib_for_mapping=16
)


class PreflightTests(unittest.TestCase):
    def test_no_violations_when_mapping_not_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_preflight(
                host_role=DEV_VM, resources=RESOURCES, disk_path=Path(tmp), allow_mapping=False
            )
            self.assertTrue(report.ok)
            self.assertEqual(report.host_role, DEV_VM)

    def test_fails_closed_when_mapping_requested_off_approved_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_preflight(
                host_role=DEV_VM, resources=RESOURCES, disk_path=Path(tmp), allow_mapping=True
            )
            self.assertFalse(report.ok)
            self.assertTrue(any("approved_mac" in v for v in report.violations))

    def test_rejects_unknown_host_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_preflight(host_role="laptop", resources=RESOURCES, disk_path=Path(tmp), allow_mapping=False)

    def test_records_tool_versions_dict_even_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_preflight(
                host_role=APPROVED_MAC, resources=RESOURCES, disk_path=Path(tmp), allow_mapping=False
            )
            self.assertIn("bwa", report.tool_versions)
            self.assertIn("minimap2", report.tool_versions)
            self.assertIn("seqkit", report.tool_versions)


if __name__ == "__main__":
    unittest.main()
