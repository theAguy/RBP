from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rbpbench.splits import newton_002c_r2 as newton


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NewtonConfigTests(unittest.TestCase):
    def test_config_has_no_stage_or_scientific_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = {
                "schema_version": 1,
                "checkpoint": newton.CHECKPOINT,
                "seed": 20260925,
                "decode_manifest_sha256": "a" * 64,
                "sample_size": 10000,
                "expected_row_count": 361180,
                "expected_mmseqs_version": "18.8cc5c",
                "expected_mmseqs_conda_build": "hd6d6fdc_0",
                "stages": ["probe_500", "probe_251", "probe_101"],
                "source_commit": "abc",
            }
            (root / newton.CONFIG_REL).write_text(json.dumps(value))
            self.assertEqual(newton.load_config(root)["seed"], 20260925)
            for changed in (
                {"sample_size": 9999},
                {"stages": ["probe_500"]},
                {"expected_mmseqs_version": "other"},
            ):
                (root / newton.CONFIG_REL).write_text(json.dumps(value | changed))
                with self.assertRaises(newton.NewtonR2Error):
                    newton.load_config(root)

    def test_slurm_memory_parser(self):
        self.assertEqual(newton._slurm_memory_mib({"SLURM_MEM_PER_NODE": "98304"}), 98304)
        self.assertEqual(newton._slurm_memory_mib({"SLURM_MEM_PER_NODE": "96G"}), 98304)
        self.assertEqual(
            newton._slurm_memory_mib({"SLURM_MEM_PER_CPU": "24576", "SLURM_CPUS_PER_TASK": "4"}),
            98304,
        )
        self.assertIsNone(newton._slurm_memory_mib({}))


class RuntimeReceiptTests(unittest.TestCase):
    def test_receipt_binds_python_mmseqs_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / "python"
            mmseqs = root / "mmseqs"
            lock = root / "lock.txt"
            for path, content in ((python, b"python"), (mmseqs, b"mmseqs"), (lock, b"lock")):
                path.write_bytes(content)
            mmseqs.chmod(0o755)
            receipt = root / "receipt.json"
            value = {
                "schema_version": 1,
                "platform": "linux-64",
                "python_executable": str(python),
                "mmseqs_executable": str(mmseqs),
                "mmseqs_sha256": digest(mmseqs),
                "mmseqs_conda_build": "hd6d6fdc_0",
                "explicit_lock": str(lock),
                "explicit_lock_sha256": digest(lock),
            }
            receipt.write_text(json.dumps(value))
            receipt.with_suffix(".json.sha256").write_text(f"{digest(receipt)}  receipt.json\n")
            with patch.object(newton.sys, "executable", str(python)), patch.object(
                newton, "_mmseqs_version", return_value="18.8cc5c"
            ):
                loaded = newton.load_runtime_receipt(receipt)
            self.assertEqual(loaded["mmseqs_sha256"], digest(mmseqs))
            mmseqs.write_bytes(b"changed")
            with patch.object(newton.sys, "executable", str(python)), patch.object(
                newton, "_mmseqs_version", return_value="18.8cc5c"
            ), self.assertRaises(newton.NewtonR2Error):
                newton.load_runtime_receipt(receipt)


class SlurmGateTests(unittest.TestCase):
    def runtime(self, root: Path) -> dict:
        mmseqs = root / "mmseqs"
        mmseqs.write_bytes(b"x")
        return {
            "python_executable": "/env/python",
            "mmseqs_executable": str(mmseqs),
            "mmseqs_version": "18.8cc5c",
            "mmseqs_sha256": digest(mmseqs),
        }

    def test_requires_slurm_exact_threads_and_memory(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(newton.platform, "system", return_value="Linux"), patch.object(
            newton.platform, "machine", return_value="x86_64"
        ), patch.object(newton, "detect_physical_ram_gib", return_value=128.0), patch.object(
            newton, "detect_available_memory_gib", return_value=96.0
        ), patch.object(newton, "snapshot") as snap, patch.object(newton.subprocess, "run") as run:
            snap.return_value.free_gib = 200.0
            run.return_value.returncode = 1
            run.return_value.stdout = ""
            root = Path(tmp)
            runtime = self.runtime(root)
            base = {"SLURM_JOB_ID": "1", "SLURM_CPUS_PER_TASK": "4", "SLURM_MEM_PER_NODE": "98304"}
            self.assertEqual(newton.check_newton_job(root, runtime, base)["slurm_memory_mib"], 98304)
            for bad in ({}, base | {"SLURM_CPUS_PER_TASK": "8"}, base | {"SLURM_MEM_PER_NODE": "32000"}):
                with self.assertRaises(newton.NewtonR2Error):
                    newton.check_newton_job(root, runtime, bad)


class ReturnPackageTests(unittest.TestCase):
    def test_stopped_return_is_small_checksum_complete_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination, archive, effective = newton.package_return(
                root,
                status="STOPPED",
                started="2026-01-01T00:00:00Z",
                input_verification={"manifest_sha256": "a" * 64, "hashes": {"secret": "x"}},
                runtime=None,
                host=None,
                failure={"type": "SyntheticStop", "message": "test"},
            )
            self.assertEqual(effective, "STOPPED")
            self.assertTrue(archive.is_file())
            self.assertTrue(archive.with_name(archive.name + ".sha256").is_file())
            self.assertEqual(json.loads((destination / "STATUS.json").read_text())["status"], "STOPPED")
            self.assertNotIn("secret", (destination / "STATUS.json").read_text())

    def test_sanitation_failure_forces_minimal_stopped_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = 0

            def guard(_path):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise newton.package.PortableR2Error("synthetic unsafe content")

            with patch.object(newton.package, "assert_return_clean", side_effect=guard):
                destination, archive, effective = newton.package_return(
                    root,
                    status="SUCCESS",
                    started="2026-01-01T00:00:00Z",
                    input_verification=None,
                    runtime=None,
                    host=None,
                    failure=None,
                )
            self.assertEqual(effective, "STOPPED")
            self.assertTrue(archive.is_file())
            status = json.loads((destination / "STATUS.json").read_text())
            self.assertTrue(status["minimal_return"])
            self.assertEqual(status["failure"]["status_before_return_guard"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
