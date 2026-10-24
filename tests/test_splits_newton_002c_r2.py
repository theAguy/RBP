from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
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
                "decode_manifest_sha256": newton.FROZEN_DECODE_MANIFEST_SHA256,
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
                {"seed": 1},
                {"decode_manifest_sha256": "a" * 64},
                {"expected_row_count": 1},
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

    def test_sigterm_uses_stopped_return_path_and_second_signal_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "seed": newton.FROZEN_SEED,
                "sample_size": 10_000,
                "expected_row_count": newton.FROZEN_ROW_COUNT,
            }

            def terminate(*_args, **_kwargs):
                os.kill(os.getpid(), signal.SIGTERM)

            real_package_return = newton.package_return

            def package_after_second_signal(*args, **kwargs):
                os.kill(os.getpid(), signal.SIGTERM)
                return real_package_return(*args, **kwargs)

            with patch.object(newton.package, "verify_inventory", return_value={"hashes": {}}), patch.object(
                newton, "load_config", return_value=config
            ), patch.object(newton, "load_runtime_receipt", return_value={
                "mmseqs_executable": "/fake/mmseqs", "mmseqs_sha256": "a" * 64,
                "mmseqs_version": newton.FROZEN_MMSEQS_VERSION,
            }), patch.object(newton, "check_newton_job", return_value={"synthetic": True}), patch.object(
                newton.package, "bind_decode_manifest_and_fastas", return_value={500: Path("fake")}
            ), patch.object(newton.package, "load_universe", return_value=[]), patch.object(
                newton.probe, "run_probe", side_effect=terminate
            ), patch.object(
                newton, "package_return", side_effect=package_after_second_signal
            ):
                code, archive = newton.execute(root, root / "receipt.json")
            self.assertEqual(code, 1)
            self.assertTrue(archive.is_file())
            status_paths = list((root / "return").glob("RBP_002C_R2_NEWTON_RETURN_*/STATUS.json"))
            self.assertEqual(len(status_paths), 1)
            status = json.loads(status_paths[0].read_text())
            self.assertEqual(status["status"], "STOPPED")
            self.assertEqual(status["failure"]["type"], "NewtonR2Signal")


class SubmitWrapperTests(unittest.TestCase):
    def fixture(self, parent: Path) -> tuple[Path, dict, Path]:
        bundle = parent / "bundle"
        script_dir = bundle / "hpc" / "newton" / "002c_r2"
        script_dir.mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / "hpc" / "newton" / "002c_r2" / "02_SUBMIT_R2_PROBE.sh"
        shutil.copy2(source, script_dir / source.name)
        (script_dir / "RUN_R2_PROBE.sbatch").write_text("#!/usr/bin/env bash\n")
        for name in ("R2_INPUT_MANIFEST.json", "R2_INPUT_MANIFEST.sha256", "R2_NEWTON_CONFIG.json"):
            (bundle / name).write_text("{}\n")
        env_prefix = parent / "env"
        env_prefix.mkdir()
        (env_prefix / "newton_runtime_receipt.json").write_text("{}\n")
        (env_prefix / "newton_runtime_receipt.json.sha256").write_text("0\n")
        fake_bin = parent / "bin"
        fake_bin.mkdir()
        fake_log = parent / "sbatch.log"
        sbatch = fake_bin / "sbatch"
        sbatch.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"$FAKE_SBATCH_LOG\"\n"
            "if [[ -n \"${FAKE_SBATCH_FAIL:-}\" ]]; then\n"
            "  printf 'Invalid account\\n' >&2\n"
            "  exit 1\n"
            "fi\n"
            "printf '12345;newton\\n'\n"
        )
        sbatch.chmod(0o755)
        env = os.environ.copy() | {
            "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
            "RBP_NEWTON_ENV_PREFIX": str(env_prefix),
            "FAKE_SBATCH_LOG": str(fake_log),
        }
        return bundle, env, fake_log

    def run_submit(self, bundle: Path, env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(bundle / "hpc/newton/002c_r2/02_SUBMIT_R2_PROBE.sh")],
            env=env, capture_output=True, text=True, check=False,
        )

    def test_downward_memory_and_time_overrides_are_refused(self):
        for override in ({"NEWTON_MEMORY": "8G"}, {"NEWTON_TIME_LIMIT": "00:10:00"}):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as tmp:
                bundle, env, fake_log = self.fixture(Path(tmp))
                done = self.run_submit(bundle, env | override)
                self.assertNotEqual(done.returncode, 0)
                self.assertFalse(fake_log.exists())
                self.assertFalse(Path(str(bundle) + ".slurm_submission").exists())

    def test_submit_is_single_use_and_parsable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle, env, fake_log = self.fixture(Path(tmp))
            first = self.run_submit(bundle, env)
            second = self.run_submit(bundle, env)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertNotEqual(second.returncode, 0)
            calls = fake_log.read_text().splitlines()
            self.assertEqual(len(calls), 1)
            self.assertIn("--parsable", calls[0])
            self.assertIn("--signal=B:USR1@600", calls[0])
            receipt = Path(str(bundle) + ".slurm_submission/submission.txt")
            self.assertEqual(receipt.read_text(), "12345;newton\n")

    def test_optional_email_notifications_are_fixed_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle, env, fake_log = self.fixture(Path(tmp))
            done = self.run_submit(bundle, env | {"RBP_SLURM_MAIL_USER": "researcher@example.org"})
            self.assertEqual(done.returncode, 0, done.stderr)
            call = fake_log.read_text()
            self.assertIn("--mail-type=BEGIN,END,FAIL", call)
            self.assertIn("--mail-user=researcher@example.org", call)

        for bad in ("not-an-email", "a@b", "a@example.org,b@example.org", "a@example.org\n--gres=gpu:1"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                bundle, env, fake_log = self.fixture(Path(tmp))
                done = self.run_submit(bundle, env | {"RBP_SLURM_MAIL_USER": bad})
                self.assertNotEqual(done.returncode, 0)
                self.assertFalse(fake_log.exists())
                self.assertFalse(Path(str(bundle) + ".slurm_submission").exists())

    def test_scheduler_rejection_leaves_auditable_recovery_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle, env, fake_log = self.fixture(Path(tmp))
            failed = self.run_submit(bundle, env | {"FAKE_SBATCH_FAIL": "1"})
            self.assertNotEqual(failed.returncode, 0)
            receipt_dir = Path(str(bundle) + ".slurm_submission")
            failure_receipt = receipt_dir / "SUBMIT_FAILED.txt"
            self.assertTrue(failure_receipt.is_file())
            self.assertIn("Invalid account", failure_receipt.read_text())
            self.assertFalse((receipt_dir / "submission.txt").exists())
            self.assertIn("squeue --me --name=rbp-r2-probe", failed.stderr)
            self.assertIn("rmdir", failed.stderr)

            # The wrapper itself will not silently reuse the failed receipt.
            blocked = self.run_submit(bundle, env)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(len(fake_log.read_text().splitlines()), 1)

            # Follow the printed recovery only after the synthetic scheduler
            # has established that nothing was queued, then submit once.
            failure_receipt.unlink()
            receipt_dir.rmdir()
            accepted = self.run_submit(bundle, env)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(len(fake_log.read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
