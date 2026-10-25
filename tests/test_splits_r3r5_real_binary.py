"""Real-MMseqs2 tiny smoke suite for Task 002C-R3–R5 (resource-gated).

Runs only when ``RBP_R3R5_MMSEQS_BIN`` names the pinned linux-64 MMseqs2
18.8cc5c binary (SHA-256 ``d6d1bf1b…``).  Every search uses the unchanged
frozen command on generated sequences only.  The ``-k 15`` nucleotide
prefilter needs roughly 9.3 GiB of RAM even for a few sequences, so run it
on a Darwin compute allocation with at least 16 GiB, e.g.::

    srun --cpus-per-task=4 --mem=16G --time=02:00:00 \\
      env RBP_R3R5_MMSEQS_BIN=$ENV/bin/mmseqs PYTHONPATH=src \\
      $ENV/bin/python -m unittest tests.test_splits_r3r5_real_binary -v

It must report every test as run, none skipped.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from rbpbench.data.audit import sha256_file
from rbpbench.splits.r3r5 import engine, returns, state
from rbpbench.splits.r3r5.contract import PRODUCTION
from tests import r3r5_support as S

BINARY = os.environ.get("RBP_R3R5_MMSEQS_BIN", "")
SKIP = "set RBP_R3R5_MMSEQS_BIN to the pinned MMseqs2 18.8cc5c binary (needs >= ~10 GiB RAM)"


def _usable() -> bool:
    return bool(BINARY) and Path(BINARY).is_file() and sha256_file(Path(BINARY)) == PRODUCTION.environment.mmseqs_sha256


@unittest.skipUnless(_usable(), SKIP)
class RealBinarySmokeTests(unittest.TestCase):
    def runtime(self, root: Path, contract, bundle_root: Path):
        ws = state.Workspace(root / "work")
        ws.create()
        return engine.Runtime(contract=contract, bundle_root=bundle_root, workspace=ws, mmseqs_bin=BINARY,
                              binary={"sha256": sha256_file(Path(BINARY)), "version": "18.8cc5c"},
                              monitors=S.fake_monitors(), allocation_deadline=time.monotonic() + 48 * 3600,
                              quota_check=lambda p, w: {"mode": "test"}, poll_interval=0.5)

    def test_e0_smoke_reproduces_rc_identity_and_width_specific_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = S.write_fixture(Path(tmp) / "b")
            rt = self.runtime(Path(tmp), fx["contract"], Path(tmp) / "b")
            record = engine.Workflow(rt).stage_smoke()
            self.assertTrue(record["payload"]["passed"], record["payload"]["results"])
            for width in (500, 251, 101):
                self.assertEqual(record["payload"]["results"][str(width)]["missing"], [])
                self.assertEqual(record["payload"]["results"][str(width)]["unexpected"], [])

    def test_tiny_end_to_end_pipeline_with_the_real_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = S.Harness(Path(tmp))
            harness.fake = Path(BINARY)
            code, archive, final_state = harness.launch("execute")
            self.assertEqual((code, final_state), (0, "SUCCESS"), harness.last_log[-3000:])
            series = returns.verify_return_series(harness.bundle / "returns")
            self.assertEqual(series["current_state"], "SUCCESS")
            self.assertIn("final", harness.selected())


if __name__ == "__main__":
    unittest.main()
