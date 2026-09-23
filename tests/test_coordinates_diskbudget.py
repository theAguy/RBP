import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.diskbudget import (
    DiskSnapshot,
    check_projected_peak,
    snapshot,
    start_ledger,
)


def _fake_disk_usage(free_gib: float, total_gib: float = 500.0):
    gib = 1024**3
    used_gib = total_gib - free_gib

    class _Usage:
        free = int(free_gib * gib)
        total = int(total_gib * gib)
        used = int(used_gib * gib)

    return _Usage()


class DiskBudgetLedgerTests(unittest.TestCase):
    def test_snapshot_reads_real_disk_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = snapshot(Path(tmp))
            self.assertIsInstance(snap, DiskSnapshot)
            self.assertGreater(snap.total_gib, 0)

    def test_projected_peak_passes_when_well_under_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=_fake_disk_usage(200.0)):
                ledger = start_ledger(Path(tmp))
                check = check_projected_peak(ledger, next_step_allowance_gib=2.0, disk_path=Path(tmp))
                self.assertTrue(check.ok)
                self.assertEqual(check.violations, ())

    def test_projected_peak_fails_closed_when_new_disk_would_exceed_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=_fake_disk_usage(200.0)):
                ledger = start_ledger(Path(tmp))
                # Simulate 25 GiB already observed as new since baseline.
                ledger.entries.append({"label": "prior_step", "free_gib_now": 175.0, "new_gib_since_baseline": 25.0})
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=_fake_disk_usage(175.0)):
                check = check_projected_peak(
                    ledger, next_step_allowance_gib=7.0, disk_path=Path(tmp), max_new_disk_gib=30.0
                )
                self.assertFalse(check.ok)
                self.assertTrue(any("exceed the 30" in v for v in check.violations))

    def test_projected_peak_fails_closed_when_free_disk_too_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=_fake_disk_usage(90.0)):
                ledger = start_ledger(Path(tmp))
                check = check_projected_peak(
                    ledger, next_step_allowance_gib=15.0, disk_path=Path(tmp), min_free_disk_gib=80.0
                )
                self.assertFalse(check.ok)
                self.assertTrue(any("80" in v for v in check.violations))

    def test_free_disk_already_below_minimum_is_a_violation_even_with_zero_allowance(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=_fake_disk_usage(50.0)):
                ledger = start_ledger(Path(tmp))
                check = check_projected_peak(
                    ledger, next_step_allowance_gib=0.0, disk_path=Path(tmp), min_free_disk_gib=80.0
                )
                self.assertFalse(check.ok)

    def test_record_step_tracks_observed_new_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=_fake_disk_usage(200.0)):
                ledger = start_ledger(Path(tmp))
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=_fake_disk_usage(195.0)):
                entry = ledger.record_step("bwa_index:hg38", path=Path(tmp))
            self.assertAlmostEqual(entry["new_gib_since_baseline"], 5.0, places=6)
            self.assertAlmostEqual(ledger.observed_new_gib, 5.0, places=6)


if __name__ == "__main__":
    unittest.main()
