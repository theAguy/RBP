from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from rbpbench.splits import resource_probe_r2 as probe


class LinuxMonitorTests(unittest.TestCase):
    def test_linux_swap_parses_used_bytes(self):
        text = "MemTotal: 100 kB\nSwapTotal: 4096 kB\nSwapFree: 1024 kB\n"
        with patch.object(Path, "read_text", return_value=text):
            raw, used = probe.linux_swap_used_bytes()
        self.assertEqual(raw, text)
        self.assertEqual(used, 3072 * 1024)

    def test_linux_swap_fails_closed_on_missing_or_impossible_values(self):
        with patch.object(Path, "read_text", return_value="SwapTotal: 1 kB\n"):
            self.assertIsNone(probe.linux_swap_used_bytes()[1])
        with patch.object(Path, "read_text", return_value="SwapTotal: 1 kB\nSwapFree: 2 kB\n"):
            self.assertIsNone(probe.linux_swap_used_bytes()[1])

    def test_linux_pressure_requires_memavailable_and_retains_psi(self):
        with patch.object(probe, "detect_available_memory_gib", return_value=88.5), patch.object(
            Path, "read_text", return_value="some avg10=0.00"
        ):
            raw, state = probe.linux_memory_pressure()
        self.assertEqual(state, "normal")
        self.assertIn("MemAvailableGiB=88.500000", raw)
        self.assertIn("some avg10=0.00", raw)
        with patch.object(probe, "detect_available_memory_gib", return_value=None):
            self.assertEqual(probe.linux_memory_pressure(), ("", None))
        with patch.object(probe, "detect_available_memory_gib", return_value=23.0), patch.object(
            Path, "read_text", return_value="some avg10=0.00"
        ):
            self.assertEqual(probe.linux_memory_pressure()[1], "warn")

    def test_dispatches_linux_monitors(self):
        with patch.object(probe.platform, "system", return_value="Linux"), patch.object(
            probe, "linux_swap_used_bytes", return_value=("linux-swap", 1)
        ), patch.object(probe, "linux_memory_pressure", return_value=("linux-pressure", "normal")):
            self.assertEqual(probe.swap_used_bytes(), ("linux-swap", 1))
            self.assertEqual(probe.memory_pressure(), ("linux-pressure", "normal"))

if __name__ == "__main__":
    unittest.main()
