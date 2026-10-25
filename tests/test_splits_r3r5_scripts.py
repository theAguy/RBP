"""Darwin operator scripts with fake sbatch/sinfo/squeue (single job, chain,
refusals, single submission, quota attestation, resume gate)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "hpc" / "darwin" / "002c_r3r5"

FAKE_SBATCH = """#!/usr/bin/env bash
n=$(( $(cat "$FAKE_STATE/count" 2>/dev/null || echo 0) + 1 )); echo $n > "$FAKE_STATE/count"
printf '%s\\n' "$@" > "$FAKE_STATE/sbatch_$n.args"
if [[ -n "${FAKE_SBATCH_FAIL_AT:-}" && "$n" == "$FAKE_SBATCH_FAIL_AT" ]]; then echo "sbatch: error: Invalid account" >&2; exit 1; fi
echo "$((1000 + n));darwin"
"""
FAKE_SINFO = """#!/usr/bin/env bash
echo "${FAKE_PARTITION_MAX:-7-00:00:00}"
"""
FAKE_SQUEUE = """#!/usr/bin/env bash
printf '%s' "${FAKE_SQUEUE_OUT:-}"
"""
FAKE_PY = """#!/usr/bin/env bash
cmd="$3"
case "$cmd" in
  verify-environment) exit "${FAKE_ENV_STATUS:-0}" ;;
  quota-probe) echo '{}'; exit "${FAKE_QUOTA_STATUS:-0}" ;;
  attest-quota) out=""; while [[ $# -gt 0 ]]; do [[ "$1" == --output ]] && out="$2"; shift; done; echo '{"statement":"x"}' > "$out" ;;
  resume-check) echo '{"action":"x"}'; exit "${FAKE_RESUME_STATUS:-0}" ;;
  *) exit 9 ;;
esac
"""


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bundle = root / "bundle"
        shutil.copytree(SCRIPTS, self.bundle / "hpc" / "darwin" / "002c_r3r5")
        self.bin = root / "bin"
        self.bin.mkdir()
        for name, text in (("sbatch", FAKE_SBATCH), ("sinfo", FAKE_SINFO), ("squeue", FAKE_SQUEUE)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.env_prefix = root / "env"
        (self.env_prefix / "bin").mkdir(parents=True)
        (self.env_prefix / "bin" / "python").write_text(FAKE_PY)
        (self.env_prefix / "bin" / "python").chmod(0o755)
        self.state = root / "state"
        self.state.mkdir()
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(root), "FAKE_STATE": str(self.state),
                    "RBP_DARWIN_ENV_PREFIX": str(self.env_prefix), "RBP_SLURM_MAIL_USER": "op@example.org"}

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, script="02_SUBMIT_R3R5.sh", **env):
        return subprocess.run(["bash", str(self.bundle / "hpc/darwin/002c_r3r5" / script)], env={**self.env, **env},
                              capture_output=True, text=True)

    def calls(self):
        return [p.read_text().splitlines() for p in sorted(self.state.glob("sbatch_*.args"))]

    def receipt(self):
        return Path(str(self.bundle) + ".r3r5_submission")

    def test_single_48h_job_when_partition_allows(self):
        done = self.submit()
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        args = calls[0]
        for expected in ("--parsable", "--cpus-per-task=4", "--mem=96G", "--time=2-00:00:00", "--no-requeue",
                         "--signal=B:USR1@600", "--mail-user=op@example.org", "--partition=public"):
            self.assertIn(expected, args)
        export = next(a for a in args if a.startswith("--export="))
        self.assertIn("RBP_R3R5_MODE=execute", export)
        self.assertIn(f"RBP_JOB_TIME_LIMIT_SECONDS={48 * 3600}", export)
        self.assertNotIn("RBP_CHAIN_TOTAL_SECONDS", export)
        self.assertFalse([a for a in args if a.startswith("--gres") or "gpu" in a])
        self.assertEqual((self.receipt() / "submission.txt").read_text(), "1001 execute\n")

    def test_dependency_chain_when_partition_limit_is_between_20_and_48_hours(self):
        done = self.submit(FAKE_PARTITION_MAX="1-06:00:00")
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2)  # ceil(48 / 30)
        self.assertIn("--time=1-06:00:00", calls[0])
        self.assertIn("--dependency=afterany:1001", calls[1])
        self.assertIn("RBP_R3R5_MODE=resume", next(a for a in calls[1] if a.startswith("--export=")))
        self.assertIn(f"RBP_CHAIN_TOTAL_SECONDS={60 * 3600}", next(a for a in calls[0] if a.startswith("--export=")))

    def test_refusals(self):
        cases = [
            ({"FAKE_PARTITION_MAX": "19:59:00"}, "20 h"),
            ({"DARWIN_MEMORY": "64G"}, "96G"),
            ({"RBP_SLURM_MAIL_USER": ""}, "email"),
            ({"FAKE_ENV_STATUS": "1"}, "does not verify"),
            ({"FAKE_QUOTA_STATUS": "4"}, "RBP_CONFIRM_NO_QUOTA_BELOW_80GIB"),
        ]
        for env, message in cases:
            with self.subTest(env=env):
                done = self.submit(**env)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn(message, done.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.receipt().exists())

    def test_quota_attestation_is_recorded_and_exported(self):
        done = self.submit(FAKE_QUOTA_STATUS="4", RBP_CONFIRM_NO_QUOTA_BELOW_80GIB="yes")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.receipt() / "quota_attestation.json").is_file())
        # H5: the script binds the physical (pwd -P) path; compare resolved paths so
        # /var vs /private/var (macOS) or other symlinked temp roots cannot matter.
        export = next(a for a in self.calls()[0] if a.startswith("--export="))
        values = dict(item.split("=", 1) for item in export[len("--export="):].split(",") if "=" in item)
        exported = Path(values["RBP_QUOTA_ATTESTATION"])
        self.assertTrue(exported.is_absolute())
        self.assertEqual(exported.resolve(), (self.receipt() / "quota_attestation.json").resolve())
        self.assertEqual(Path(values["RBP_BUNDLE_ROOT"]).resolve(), self.bundle.resolve())
        self.assertEqual(Path(values["RBP_BUNDLE_ROOT"]), Path(values["RBP_BUNDLE_ROOT"]).resolve())  # physical path kept

    def test_quota_attestation_through_a_symlinked_bundle_path(self):
        link = Path(self.tmp.name) / "linked_root"
        link.symlink_to(self.bundle.parent, target_is_directory=True)
        script = link / "bundle" / "hpc/darwin/002c_r3r5/02_SUBMIT_R3R5.sh"
        done = subprocess.run(["bash", str(script)], env={**self.env, "FAKE_QUOTA_STATUS": "4",
                                                          "RBP_CONFIRM_NO_QUOTA_BELOW_80GIB": "yes"},
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        export = next(a for a in self.calls()[0] if a.startswith("--export="))
        values = dict(item.split("=", 1) for item in export[len("--export="):].split(",") if "=" in item)
        self.assertEqual(values["RBP_BUNDLE_ROOT"], str(self.bundle.resolve()))  # physical, not the symlink path
        self.assertEqual(Path(values["RBP_QUOTA_ATTESTATION"]).resolve(), (self.receipt() / "quota_attestation.json").resolve())

    def test_second_submission_and_reused_bundle_are_refused(self):
        self.assertEqual(self.submit().returncode, 0)
        again = self.submit()
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual(len(self.calls()), 1)
        shutil.rmtree(self.receipt())
        (self.bundle / "r3r5_work").mkdir()
        self.assertIn("reused bundle", self.submit().stderr)

    def test_failed_sbatch_records_recovery_without_retry(self):
        done = self.submit(FAKE_PARTITION_MAX="1-06:00:00", FAKE_SBATCH_FAIL_AT="2")
        self.assertNotEqual(done.returncode, 0)
        text = (self.receipt() / "SUBMIT_FAILED.txt").read_text()
        self.assertIn("1001", text)
        self.assertIn("scancel", text)
        self.assertNotEqual(self.submit().returncode, 0)

    def test_resume_script_obeys_the_decision_table(self):
        refused = self.submit("05_RESUME_R3R5.sh", FAKE_RESUME_STATUS="3")
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.calls(), [])
        busy = self.submit("05_RESUME_R3R5.sh", FAKE_SQUEUE_OUT="rbp-r3r5-1\n")
        self.assertNotEqual(busy.returncode, 0)
        ok = self.submit("05_RESUME_R3R5.sh")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        export = next(a for a in self.calls()[0] if a.startswith("--export="))
        self.assertIn("RBP_R3R5_MODE=resume", export)
        self.assertIn("--time=48:00:00", self.calls()[0])
        self.assertTrue(Path(str(self.bundle) + ".r3r5_resume_1").is_dir())

    def test_sbatch_wrapper_requires_wrapper_exports(self):
        done = subprocess.run(["bash", str(SCRIPTS / "RUN_R3R5.sbatch")], env={"PATH": "/usr/bin:/bin"},
                              capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("RBP_BUNDLE_ROOT", done.stderr)


if __name__ == "__main__":
    unittest.main()
