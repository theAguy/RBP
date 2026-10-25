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


def rewrite_return(archive: Path, edits: dict, *, regen_inventory=True, regen_checksums=True, sidecar_name=None):
    """Mutates members of one return, optionally re-deriving its inventory and
    CHECKSUMS so only the targeted semantic check can catch the change, then
    rebuilds the outer digest sidecar."""
    import hashlib
    top = returns.archive_top(archive)
    with zipfile.ZipFile(archive) as z:
        members = {n[len(top) + 1:]: z.read(n) for n in z.namelist()}
    for rel, value in edits.items():
        if value is None:
            members.pop(rel, None)
        else:
            members[rel] = value(members.get(rel)) if callable(value) else value
    if regen_inventory:
        entries = [{"path": r, "byte_size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                   for r, b in sorted(members.items()) if r not in {"RETURN_INVENTORY.json", "CHECKSUMS.sha256"}]
        members["RETURN_INVENTORY.json"] = (json.dumps({"entries": entries}, indent=2, sort_keys=True) + "\n").encode()
    if regen_checksums:
        members["CHECKSUMS.sha256"] = "".join(f"{hashlib.sha256(b).hexdigest()}  {r}\n" for r, b in sorted(members.items())
                                              if r != "CHECKSUMS.sha256").encode()
    archive.unlink()
    with zipfile.ZipFile(archive, "x") as z:
        for rel, data in sorted(members.items()):
            z.writestr(f"{top}/{rel}", data)
    Path(f"{archive}.sha256").write_text(f"{returns.sha256_file(archive)}  {sidecar_name or archive.name}\n")


def json_edit(**changes):
    def apply(data):
        doc = json.loads(data)
        doc.update(changes)
        return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()
    return apply


class DottedHostnameAndInternalConsistencyTests(unittest.TestCase):
    """H2 and H4 regressions."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.contract = fixture_contract(row_count=10)
        self.ws = state.Workspace(self.root / "r3r5_work")
        self.ws.create()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, cls=StopClass.SIGNAL, status="STOPPED", host="GuyA.local"):
        return returns.package_return(bundle_root=self.root, workspace=self.ws, contract=self.contract, status=status,
                                      stop_class=cls, message="m", attempt=None, host=None, host_name=host)[0]

    def test_dotted_hostname_is_preserved_and_verifiable(self):
        archive = self.make()
        self.assertTrue(archive.name.endswith("_GuyA.local.zip"), archive.name)            # 1: hostname intact
        with zipfile.ZipFile(archive) as z:
            tops = {n.split("/", 1)[0] for n in z.namelist()}
        self.assertEqual(tops, {archive.name[:-len(".zip")]})                            # 2: top dir == basename
        self.assertEqual(returns.verify_return_series(self.root / "returns")["count"], 1)  # 3: series verifies
        status = json.loads(returns.read_return_member(archive, "STATUS.json"))          # 4: member readable
        self.assertEqual(status["return_index"], 1)
        self.assertEqual(Path(f"{archive}.sha256").read_text().split()[1], archive.name)
        for host in ("node.cluster.example.org", "a.b", "trailing."):
            time.sleep(1.05)
            other = self.make(cls=StopClass.SCHEDULER_TIME, host=host)
            self.assertTrue(other.name.endswith(f"_{host}.zip"), other.name)
        self.assertEqual(returns.verify_return_series(self.root / "returns")["count"], 4)

    def test_existing_archive_or_sidecar_is_never_overwritten(self):
        from unittest import mock
        fixed = "2026-10-25T12:00:00Z"
        with mock.patch.object(returns, "utc_now", lambda: fixed):
            first = self.make()
            first_bytes = first.read_bytes()
            sidecar_bytes = Path(f"{first}.sha256").read_bytes()
            # force the next package to target the same name (same index, status, stamp, host)
            with mock.patch.object(returns, "existing_returns", lambda d: []):
                with self.assertRaises(returns.ReturnSeriesError):
                    self.make()
            first.rename(first.with_name(first.name + ".moved"))
            with mock.patch.object(returns, "existing_returns", lambda d: []):
                with self.assertRaises(returns.ReturnSeriesError):  # sidecar alone still blocks
                    self.make()
            first.with_name(first.name + ".moved").rename(first)
        self.assertEqual(first.read_bytes(), first_bytes)
        self.assertEqual(Path(f"{first}.sha256").read_bytes(), sidecar_bytes)

    def assert_rejected(self, edits, **kwargs):
        archive = self.make()
        returns.verify_return_series(self.root / "returns")
        rewrite_return(archive, edits, **kwargs)
        with self.assertRaises(returns.ReturnSeriesError):
            returns.verify_return_series(self.root / "returns")

    def fresh(self):
        self.tmp.cleanup()
        self.setUp()

    def test_internal_mutations_are_rejected_after_outer_digest_rebuild(self):
        def checksum_edit(transform):
            def apply(data):
                return transform(data.decode()).encode()
            return apply
        cases = {
            "checksum digest wrong": ({"CHECKSUMS.sha256": checksum_edit(lambda t: ("0" * 64) + t[64:])}, {"regen_checksums": False}),
            "checksum duplicate line": ({"CHECKSUMS.sha256": checksum_edit(lambda t: t + t.splitlines(True)[0])}, {"regen_checksums": False}),
            "checksum foreign path": ({"CHECKSUMS.sha256": checksum_edit(lambda t: t + ("1" * 64) + "  foreign.json\n")}, {"regen_checksums": False}),
            "checksum missing line": ({"CHECKSUMS.sha256": checksum_edit(lambda t: "".join(t.splitlines(True)[1:]))}, {"regen_checksums": False}),
            "checksum non-canonical": ({"CHECKSUMS.sha256": checksum_edit(lambda t: t.replace("  ", " *", 1))}, {"regen_checksums": False}),
            "status rewritten": ({"STATUS.json": json_edit(message="rewritten")}, {}),
            "manifest index": ({"RETURN_MANIFEST.json": json_edit(return_index=1, status="SUCCESS")}, {}),
            "manifest stop class": ({"RETURN_MANIFEST.json": json_edit(stop_class="SUCCESS")}, {}),
            "manifest predecessor": ({"RETURN_MANIFEST.json": json_edit(predecessor={"name": "x", "sha256": "0" * 64})}, {}),
        }
        for name, (edits, kwargs) in cases.items():
            with self.subTest(name):
                self.fresh()
                self.assert_rejected(edits, **kwargs)

    def test_status_flags_must_agree_with_stop_class_even_with_a_consistent_manifest(self):
        import hashlib
        for change in ({"terminal": True}, {"resumable": False}, {"status": "SUCCESS"}):
            with self.subTest(change=change):
                self.fresh()
                archive = self.make()
                top = returns.archive_top(archive)
                with zipfile.ZipFile(archive) as z:
                    status = json.loads(z.read(f"{top}/STATUS.json"))
                status.update(change)
                new_status = (json.dumps(status, indent=2, sort_keys=True) + "\n").encode()
                manifest_fix = json_edit(status_sha256=hashlib.sha256(new_status).hexdigest(), status=status["status"])
                rewrite_return(archive, {"STATUS.json": new_status, "RETURN_MANIFEST.json": manifest_fix})
                with self.assertRaises(returns.ReturnSeriesError):
                    returns.verify_return_series(self.root / "returns")

    def test_sidecar_filename_must_match(self):
        archive = self.make()
        rewrite_return(archive, {}, sidecar_name="other_name.zip")
        with self.assertRaises(returns.ReturnSeriesError):
            returns.verify_return_series(self.root / "returns")

    def test_unmutated_rewrite_still_verifies(self):
        archive = self.make()
        rewrite_return(archive, {})
        self.assertEqual(returns.verify_return_series(self.root / "returns")["count"], 1)


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

    def test_production_builder_accepts_tracked_manifests_and_refuses_absent_real_inputs(self):
        """H1: the tracked R2 manifest no longer blocks; the absent (ignored) real inputs still do."""
        tracked = {"dataset_audit", "proteins_tsv", "decode_manifest", "r2_return_manifest"}
        for spec in PRODUCTION.inputs:
            if spec.role in tracked:
                bundle.check_source_input(spec, S.REPO / spec.path)
        with self.assertRaises(bundle.BundleError) as ctx:
            bundle.build_bundle(S.REPO, self.root / "prod", {s.role: self.root / "absent" / s.path for s in PRODUCTION.inputs}
                                | {r: S.REPO / PRODUCTION.input(r).path for r in tracked},
                                contract=PRODUCTION, require_clean=False)
        self.assertFalse((self.root / "prod").exists())
        self.assertIn("dataset_csv", str(ctx.exception))

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
