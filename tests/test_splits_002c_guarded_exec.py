"""Unit tests for the Task 002C memory-gate helpers added by the C1-C7
correction pass (docs/reviews/002c1_partition_orchestration_correction_review.md,
C5: "guarded_exec.py enforces timeout and disk only ... The corresponding
config fields are currently unused").

Every gate is exercised by monkeypatching the underlying host-measurement
functions (never by actually starving the test host of memory), mirroring
how the already-accepted Task 002B suite tests the identical semantics.
"""

from __future__ import annotations

import unittest
from unittest import mock

from rbpbench.splits import guarded_exec


class InstalledRamGateTests(unittest.TestCase):
    def test_none_installed_ram_is_a_hard_failure(self):
        with mock.patch.object(guarded_exec, "detect_physical_ram_gib", return_value=None):
            with self.assertRaises(guarded_exec.ResourceGateExceededError):
                guarded_exec.check_installed_ram_or_fail(min_installed_ram_gib=16.0)

    def test_below_minimum_installed_ram_fails(self):
        with mock.patch.object(guarded_exec, "detect_physical_ram_gib", return_value=8.0):
            with self.assertRaises(guarded_exec.ResourceGateExceededError):
                guarded_exec.check_installed_ram_or_fail(min_installed_ram_gib=16.0)

    def test_sufficient_installed_ram_passes(self):
        with mock.patch.object(guarded_exec, "detect_physical_ram_gib", return_value=16.0):
            result = guarded_exec.check_installed_ram_or_fail(min_installed_ram_gib=16.0)
            self.assertEqual(result, 16.0)


class AvailableMemoryBeforeLaunchGateTests(unittest.TestCase):
    def test_none_available_memory_is_a_hard_failure(self):
        with mock.patch.object(guarded_exec, "detect_available_memory_gib", return_value=None):
            with self.assertRaises(guarded_exec.ResourceGateExceededError):
                guarded_exec.check_available_memory_before_launch_or_fail(
                    min_available_memory_gib_before_launch=10.0, label="audit_probe"
                )

    def test_below_minimum_available_memory_fails(self):
        with mock.patch.object(guarded_exec, "detect_available_memory_gib", return_value=5.0):
            with self.assertRaises(guarded_exec.ResourceGateExceededError):
                guarded_exec.check_available_memory_before_launch_or_fail(
                    min_available_memory_gib_before_launch=10.0, label="audit_probe"
                )

    def test_sufficient_available_memory_passes(self):
        with mock.patch.object(guarded_exec, "detect_available_memory_gib", return_value=20.0):
            result = guarded_exec.check_available_memory_before_launch_or_fail(
                min_available_memory_gib_before_launch=10.0, label="audit_probe"
            )
            self.assertEqual(result, 20.0)


class ProbeMemoryGatesTests(unittest.TestCase):
    def test_peak_rss_over_the_gate_fails_the_probe(self):
        # 11 GiB in KiB.
        peak_rss_kib = 11 * 1024 * 1024
        with mock.patch.object(guarded_exec, "detect_available_memory_gib", return_value=20.0):
            with self.assertRaises(guarded_exec.ResourceGateExceededError) as ctx:
                guarded_exec.check_probe_memory_gates_or_fail(
                    peak_rss_kib=peak_rss_kib, max_peak_memory_gib=10.0,
                    min_available_memory_gib_before_next_stage=10.0, label="audit_probe",
                )
            self.assertIn("peak RSS", str(ctx.exception))

    def test_low_post_probe_available_memory_fails_the_probe(self):
        peak_rss_kib = 1 * 1024 * 1024  # well under the peak gate
        with mock.patch.object(guarded_exec, "detect_available_memory_gib", return_value=5.0):
            with self.assertRaises(guarded_exec.ResourceGateExceededError) as ctx:
                guarded_exec.check_probe_memory_gates_or_fail(
                    peak_rss_kib=peak_rss_kib, max_peak_memory_gib=10.0,
                    min_available_memory_gib_before_next_stage=10.0, label="audit_probe",
                )
            self.assertIn("available memory", str(ctx.exception))

    def test_none_post_probe_available_memory_is_a_hard_failure(self):
        peak_rss_kib = 1 * 1024 * 1024
        with mock.patch.object(guarded_exec, "detect_available_memory_gib", return_value=None):
            with self.assertRaises(guarded_exec.ResourceGateExceededError):
                guarded_exec.check_probe_memory_gates_or_fail(
                    peak_rss_kib=peak_rss_kib, max_peak_memory_gib=10.0,
                    min_available_memory_gib_before_next_stage=10.0, label="audit_probe",
                )

    def test_both_gates_within_limits_pass(self):
        peak_rss_kib = 1 * 1024 * 1024
        with mock.patch.object(guarded_exec, "detect_available_memory_gib", return_value=20.0):
            result = guarded_exec.check_probe_memory_gates_or_fail(
                peak_rss_kib=peak_rss_kib, max_peak_memory_gib=10.0,
                min_available_memory_gib_before_next_stage=10.0, label="audit_probe",
            )
            self.assertAlmostEqual(result["peak_rss_gib"], 1.0)
            self.assertEqual(result["available_memory_gib_after"], 20.0)


if __name__ == "__main__":
    unittest.main()
