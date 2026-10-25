"""Return sanitation/series, launcher rules, and portable builder (tests 15, 17, 21, 22)."""

from __future__ import annotations

import gzip
import json
import shutil
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from rbpbench.splits.r3r5 import bundle, darwin, engine, returns, state
from rbpbench.splits.r3r5.contract import PRODUCTION, fixture_contract
from rbpbench.splits.r3r5.stops import (
    RESUME_DECISION_TABLE,
    ExternalResourceStop,
    IntegrityStop,
    StopClass,
    resume_allowed,
)
from tests import r3r5_support as S

ROW = "row_{}"


def gz(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as h:
        h.writelines(lines)


class SanitationTests(unittest.TestCase):
    contract = fixture_contract(row_count=10)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "ret"
        self.dir.mkdir()
        (self.dir / "STATUS.json").write_text("{}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_large_named_edge_artifact_over_64_mib_is_admitted_by_schema(self):
        path = self.dir / "edges" / "normalized_edges_500.tsv.gz"
        pairs = (tuple(sorted((f"row_{i}", f"row_{i + 4000000}"))) for i in range(3_400_000))
        gz(path, (f"{a}\t{b}\n" for a, b in sorted(pairs)))
        with gzip.open(path, "rb") as h:
            size = sum(len(chunk) for chunk in iter(lambda: h.read(1 << 20), b""))
        self.assertGreater(size, 64 * 1024**2)
        roles = returns.sanitize(self.dir, self.contract)
        self.assertEqual(roles["edges/normalized_edges_500.tsv.gz"], "normalized_edges_500")

    def test_violation_pairs_are_parsed_completely(self):
        lines = ["width\tdirection\tsample_a\tsample_b\n"] + [f"500\ttrain_to_test\t{a}\t{b}\n" for a, b in (sorted((f"row_{i}", f"row_{i + 100000}")) for i in range(50000))]
        gz(self.dir / "audit" / "violations_cycle1.tsv.gz", lines)
        self.assertEqual(returns.sanitize(self.dir, self.contract)["audit/violations_cycle1.tsv.gz"], "audit_violations")

    def test_unpermitted_or_malformed_content_is_rejected(self):
        cases = {
            "partition_train.fasta": ">row_1\nACGT\n",
            "edges/raw_full_search_500.tsv": "row_1\trow_2\t0\n",
            "reports/x/leak.json": json.dumps({"s": "ACGT" * 20}),
            "logs/x/leak.log": "ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\n",
            "edges/normalized_edges_251.tsv.gz": None,
            "final/membership.tsv.gz": None,
            "dataset.csv": "sequence,labels\n",
        }
        for rel, content in cases.items():
            with self.subTest(rel=rel):
                target = self.dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if rel.endswith("normalized_edges_251.tsv.gz"):
                    gz(target, ["row_2\trow_1\n"])  # not normalized
                elif rel == "final/membership.tsv.gz":
                    gz(target, ["sample_id\tcomponent_id\tpartition\n", f"row_1\t{'a' * 64}\tholdout\n"])
                else:
                    target.write_text(content)
                with self.assertRaises(returns.SanitationError):
                    returns.sanitize(self.dir, self.contract)
                target.unlink()

    def test_oversized_log_is_excerpted_explicitly(self):
        source = Path(self.tmp.name) / "big.log"
        source.write_bytes(b"x" * 2000)
        target = self.dir / "logs" / "s" / "big.log"
        returns._copy_log(source, target, limit=1000)
        text = target.read_text()
        self.assertIn("[EXCERPT: original log 2000 bytes", text)
        self.assertLess(target.stat().st_size, 1000)


class ReturnSeriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.contract = fixture_contract(row_count=10)
        self.ws = state.Workspace(self.root / "r3r5_work")
        self.ws.create()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, cls, status="STOPPED"):
        archive, effective = returns.package_return(bundle_root=self.root, workspace=self.ws, contract=self.contract,
                                                    status=status, stop_class=cls, message="m", attempt=None, host=None)
        return archive

    def test_ordered_linked_series_and_current_state(self):
        a = self.make(StopClass.SIGNAL)
        time.sleep(1.1)
        b = self.make(StopClass.SUCCESS, "SUCCESS")
        series = returns.verify_return_series(self.root / "returns")
        self.assertEqual([r["index"] for r in series["returns"]], [1, 2])
        self.assertEqual(series["current_state"], "SUCCESS")
        manifest = json.loads(returns.read_return_member(b, "RETURN_MANIFEST.json"))
        self.assertEqual(manifest["predecessor"]["name"], a.name)

    def test_tampered_missing_or_post_terminal_returns_are_rejected(self):
        self.make(StopClass.SCHEDULER_TIME)
        time.sleep(1.1)
        second = self.make(StopClass.SCIENTIFIC)
        time.sleep(1.1)
        third = self.make(StopClass.SIGNAL)  # written after a terminal return
        with self.assertRaises(returns.ReturnSeriesError):
            returns.verify_return_series(self.root / "returns")
        third.unlink()
        Path(str(third) + ".sha256").unlink()
        returns.verify_return_series(self.root / "returns")
        sidecar = Path(str(second) + ".sha256")
        saved = sidecar.read_text()
        sidecar.unlink()
        with self.assertRaises(returns.ReturnSeriesError):
            returns.verify_return_series(self.root / "returns")
        sidecar.write_text(saved)
        with zipfile.ZipFile(second, "a") as z:
            z.writestr(second.name[:-4] + "/extra.json", "{}")
        Path(str(second) + ".sha256").write_text(f"{returns.sha256_file(second)}  {second.name}\n")
        with self.assertRaises(returns.ReturnSeriesError):
            returns.verify_return_series(self.root / "returns")

    def test_sanitation_failure_yields_minimal_integrity_stop_naming_the_artifact(self):
        gen = self.ws.new_generation("g", "s")
        (gen / "leak.json").write_text(json.dumps({"x": "ACGT" * 30}))
        self.ws.promote("s", group="g", generation=gen, fingerprint="f", upstream={}, retained=[gen / "leak.json"])
        archive, effective = returns.package_return(bundle_root=self.root, workspace=self.ws, contract=self.contract,
                                                    status="SUCCESS", stop_class=StopClass.SUCCESS, message="ok",
                                                    attempt=None, host=None)
        self.assertEqual(effective, StopClass.INTEGRITY)
        status = json.loads(returns.read_return_member(archive, "STATUS.json"))
        self.assertEqual(status["status"], "STOPPED")
        self.assertIn("leak.json", status["sanitation_failure"]["path"])
        self.assertEqual(len(status["sanitation_failure"]["sha256"]), 64)
        with zipfile.ZipFile(archive) as z:
            self.assertFalse([n for n in z.namelist() if "leak" in n])


class LauncherRuleTests(unittest.TestCase):
    def test_resume_decision_table_is_closed(self):
        for cls in StopClass:
            allowed, _ = resume_allowed(cls)
            self.assertEqual(allowed, cls in {StopClass.SIGNAL, StopClass.SCHEDULER_TIME, StopClass.RESOURCE_EXTERNAL,
                                              StopClass.UNRECORDED_INTERRUPTION})
            self.assertIn(cls.value, RESUME_DECISION_TABLE)
        self.assertEqual(resume_allowed(None)[0], False)

    def host(self, **env):
        base = {"SLURM_JOB_ID": "1", "SLURM_CPUS_PER_TASK": "4", "SLURM_MEM_PER_NODE": "96G"}
        return darwin.Host(env={**base, **env}, monitors=S.fake_monitors(), wall_clock=lambda: 1_000_000.0,
                           system=lambda: ("Linux", "x86_64"), running_mmseqs=lambda: "", running_rbp_jobs=lambda own: [])

    def test_unmeasurable_scheduler_state_fails_closed(self):
        host = self.host()
        host.running_rbp_jobs = lambda own: ["unmeasurable"]
        with self.assertRaises(ExternalResourceStop):
            darwin.host_preflight(PRODUCTION, host, Path("."))

    def test_allocation_branches(self):
        h = 3600
        ok = darwin.allocation_deadline(PRODUCTION, self.host(RBP_JOB_TIME_LIMIT_SECONDS=str(48 * h)), "execute")[1]
        self.assertEqual(ok["mode"], "single_job")
        with self.assertRaises(ExternalResourceStop):
            darwin.allocation_deadline(PRODUCTION, self.host(RBP_JOB_TIME_LIMIT_SECONDS=str(30 * h)), "execute")
        chain = darwin.allocation_deadline(PRODUCTION, self.host(RBP_JOB_TIME_LIMIT_SECONDS=str(24 * h),
                                                                 RBP_CHAIN_TOTAL_SECONDS=str(48 * h)), "execute")[1]
        self.assertEqual(chain["mode"], "dependency_chain")
        for bad in ({"RBP_JOB_TIME_LIMIT_SECONDS": str(19 * h), "RBP_CHAIN_TOTAL_SECONDS": str(57 * h)},
                    {"RBP_JOB_TIME_LIMIT_SECONDS": str(24 * h), "RBP_CHAIN_TOTAL_SECONDS": str(47 * h)},
                    {}):
            with self.subTest(bad=bad), self.assertRaises(ExternalResourceStop):
                darwin.allocation_deadline(PRODUCTION, self.host(**bad), "execute")
        self.assertEqual(darwin.allocation_deadline(PRODUCTION, self.host(RBP_JOB_TIME_LIMIT_SECONDS=str(20 * h)),
                                                    "resume")[1]["mode"], "resume_job")
        with self.assertRaises(ExternalResourceStop):
            darwin.allocation_deadline(PRODUCTION, self.host(RBP_JOB_TIME_LIMIT_SECONDS=str(19 * h)), "resume")
        end = darwin.allocation_deadline(PRODUCTION, self.host(RBP_JOB_TIME_LIMIT_SECONDS=str(48 * h),
                                                               SLURM_JOB_END_TIME=str(1_000_000 + 10 * h)), "execute")[1]
        self.assertEqual(end["remaining_seconds"], 10 * h)

    def test_host_preflight(self):
        good = self.host()
        self.assertEqual(darwin.host_preflight(PRODUCTION, good, Path("."))["cpus"], 4)
        for env, exc in (({"SLURM_JOB_ID": ""}, IntegrityStop), ({"SLURM_CPUS_PER_TASK": "8"}, IntegrityStop),
                         ({"SLURM_MEM_PER_NODE": "32G"}, ExternalResourceStop)):
            with self.subTest(env=env), self.assertRaises(exc):
                darwin.host_preflight(PRODUCTION, self.host(**env), Path("."))
        busy = self.host()
        busy.running_mmseqs = lambda: "4242"
        with self.assertRaises(ExternalResourceStop):
            darwin.host_preflight(PRODUCTION, busy, Path("."))
        other = self.host()
        other.running_rbp_jobs = lambda own: ["99"]
        with self.assertRaises(ExternalResourceStop):
            darwin.host_preflight(PRODUCTION, other, Path("."))
        mac = self.host()
        mac.system = lambda: ("Darwin", "arm64")
        with self.assertRaises(IntegrityStop):
            darwin.host_preflight(PRODUCTION, mac, Path("."))

    def test_quota_parsing_and_attestation_branches(self):
        quota = ("Disk quotas for user u (uid 1):\n     Filesystem  blocks   quota   limit   grace   files   quota   limit   grace\n"
                 "      /dev/sda1  1048576  0  104857600   10  0  0\n")
        self.assertAlmostEqual(darwin.parse_quota_output(quota)["headroom_gib"], 99.0)
        self.assertEqual(darwin.parse_quota_output("Disk quotas for user u (uid 1): none\n")["kind"], "none")
        self.assertEqual(darwin.parse_quota_output("garbage")["kind"], "unparseable")
        self.assertEqual(darwin.parse_lfs_quota_output("/lustre 10 0 0 - 1 0 0 -\n")["kind"], "none")
        self.assertAlmostEqual(darwin.parse_lfs_quota_output("/lustre 0 0 83886080 - 1 0 0 -\n")["headroom_gib"], 80.0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def check(probe, attestation=None):
                host = self.host()
                host.quota_probe = lambda p: probe
                return darwin.make_quota_check(PRODUCTION, root, host, attestation)(root, 500)
            self.assertEqual(check({"machine_readable": True, "result": {"kind": "none"}})["mode"], "machine_readable")
            with self.assertRaises(ExternalResourceStop):
                check({"machine_readable": True, "result": {"kind": "limited", "headroom_gib": 79.9}})
            with self.assertRaises(ExternalResourceStop):
                check({"machine_readable": False})
            att = root / "att.json"
            darwin.write_attestation(root, att, "op")
            self.assertEqual(check({"machine_readable": False}, att)["mode"], "operator_attestation")
            other = root / "other.json"
            darwin.write_attestation(root / "elsewhere", other, "op")
            with self.assertRaises(ExternalResourceStop):
                check({"machine_readable": False}, other)

    def test_width_launch_gates_are_floor_plus_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = state.Workspace(Path(tmp) / "w")
            ws.create()
            for width, needed in ((500, 140.0), (251, 105.0), (101, 95.0)):
                for free, ok in ((needed, True), (needed - 0.01, False)):
                    rt = engine.Runtime(contract=PRODUCTION, bundle_root=Path(tmp), workspace=ws, mmseqs_bin="x", binary={},
                                        monitors=S.fake_monitors(free_disk_gib=lambda p, f=free: f),
                                        allocation_deadline=time.monotonic() + 1e6, quota_check=lambda p, w: {"q": w})
                    wf = engine.Workflow.__new__(engine.Workflow)
                    wf.rt, wf.c, wf.ws = rt, PRODUCTION, ws
                    with self.subTest(width=width, free=free):
                        if ok:
                            self.assertEqual(wf.width_launch_gate(width, Path(tmp), "x")["required_free_gib"], needed)
                        else:
                            with self.assertRaises(ExternalResourceStop):
                                wf.width_launch_gate(width, Path(tmp), "x")

    def test_runtime_verification_binds_every_frozen_environment_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = S.write_fake_mmseqs(root)
            lock, pkgs = root / "lock.txt", root / "pkgs.json"
            lock.write_text("lock\n")
            pkgs.write_text("[]\n")
            receipt = {"platform": "linux-64", "mmseqs_conda_build": "hd6d6fdc_0", "python_executable": "/nonexistent",
                       "mmseqs_executable": str(fake), "mmseqs_sha256": returns.sha256_file(fake),
                       "explicit_lock": str(lock), "explicit_lock_sha256": returns.sha256_file(lock),
                       "package_list": str(pkgs), "package_list_sha256": returns.sha256_file(pkgs)}
            path = root / "newton_runtime_receipt.json"
            path.write_text(json.dumps(receipt))
            Path(str(path) + ".sha256").write_text(returns.sha256_file(path) + "  x\n")
            env = dict(mmseqs_sha256=receipt["mmseqs_sha256"], explicit_lock_sha256=receipt["explicit_lock_sha256"],
                       package_list_sha256=receipt["package_list_sha256"], runtime_receipt_sha256=returns.sha256_file(path))
            contract = fixture_contract(environment=env)
            self.assertEqual(darwin.verify_runtime(contract, path, require_python=False)["binary"]["version"], "18.8cc5c")
            with self.assertRaises(IntegrityStop):
                darwin.verify_runtime(contract, path, require_python=True)  # wrong interpreter
            with self.assertRaises(IntegrityStop):
                darwin.verify_runtime(PRODUCTION, path, require_python=False)  # not the accepted Darwin receipt
            lock.write_text("drift\n")
            with self.assertRaises(IntegrityStop):
                darwin.verify_runtime(contract, path, require_python=False)


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fx = S.write_fixture(self.root / "src")
        self.contract = self.fx["contract"]
        self.sources = {s.role: self.root / "src" / s.path for s in self.contract.inputs}

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, sources=None, name="b"):
        return bundle.build_bundle(S.REPO, self.root / name, sources or self.sources, contract=self.contract, require_clean=False)

    def test_refuses_missing_extra_drifted_or_unreviewed_inputs(self):
        missing = dict(self.sources)
        missing.pop("fasta_251")
        extra = {**self.sources, "unreviewed_extra": self.sources["dataset_csv"]}
        drifted_path = self.root / "drift.csv"
        drifted_path.write_bytes(self.sources["dataset_csv"].read_bytes() + b"x")
        drifted = {**self.sources, "dataset_csv": drifted_path}
        for name, sources in (("missing", missing), ("extra", extra), ("drifted", drifted)):
            with self.subTest(name), self.assertRaises(bundle.BundleError):
                self.build(sources, name)
            self.assertFalse((self.root / name).exists())

    def test_production_builder_refuses_the_tracked_r2_manifest_until_reconciled(self):
        with self.assertRaises(bundle.BundleError) as ctx:
            bundle.build_bundle(S.REPO, self.root / "prod", {s.role: S.REPO / s.path for s in PRODUCTION.inputs},
                                contract=PRODUCTION, require_clean=False)
        self.assertFalse((self.root / "prod").exists())
        self.assertRegex(str(ctx.exception), "requires|missing|not a file")

    def test_bundle_archive_extracts_and_verifies(self):
        result = self.build()
        self.assertIn("rbpbench/splits/r3r5/darwin.py", json.loads((self.root / "b" / "BUNDLE_SUMMARY.json").read_text())["source_closure"])
        archive = bundle.archive_bundle(self.root / "b")
        out = self.root / "extract"
        out.mkdir()
        with tarfile.open(archive["archive"]) as t:
            t.extractall(out)
        verified = bundle.verify_bundle(out / "b", contract=self.contract)
        self.assertEqual(verified["entry_count"], result["entry_count"])
        (out / "b" / "inputs" / "decode" / "sequence_partitions_width_101.fasta").write_text(">row_0\nA\n")
        with self.assertRaises(bundle.BundleError):
            bundle.verify_bundle(out / "b", contract=self.contract)

    def test_runtime_owned_directories_are_not_drift_but_other_additions_are(self):
        self.build()
        b = self.root / "b"
        (b / "r3r5_work").mkdir()
        (b / "returns").mkdir()
        (b / "r3r5_work" / "x").write_text("x")
        bundle.verify_bundle(b, contract=self.contract)
        (b / "inputs" / "new.txt").write_text("x")
        with self.assertRaises(bundle.BundleError):
            bundle.verify_bundle(b, contract=self.contract)
        shutil.rmtree(b / "r3r5_work")


if __name__ == "__main__":
    unittest.main()
