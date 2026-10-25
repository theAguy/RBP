"""Tiny end-to-end pipeline through the real launcher with a fake MMseqs2
(tests 5, 11–13, 21, 22, 25 and the handoff's end-to-end scenarios).

Every run uses a generated 90-row fixture bundle built by the real bundle
builder; no real data and no real MMseqs2 binary is used.
"""

from __future__ import annotations

import json
import os
import signal
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from rbpbench.splits.r3r5 import darwin, engine, returns
from rbpbench.splits.r3r5.stops import IntegrityStop
from tests import r3r5_support as S


class E2EBase(unittest.TestCase):
    def setUp(self):
        S.clear_fake_env()
        self.tmp = tempfile.TemporaryDirectory()
        self.h = S.Harness(Path(self.tmp.name))

    def tearDown(self):
        S.clear_fake_env()
        self.tmp.cleanup()

    def assert_stop(self, archive, stop_class):
        status = self.h.status(archive)
        self.assertEqual(status["stop_class"], stop_class, status["message"])
        return status

    def zip_names(self, archive):
        with zipfile.ZipFile(archive) as z:
            return sorted(n.split("/", 1)[1] for n in z.namelist())


class SuccessTests(E2EBase):
    def test_zero_hit_success_produces_one_sanitized_terminal_return(self):
        code, archive, state = self.h.launch("execute")
        self.assertEqual((code, state), (0, "SUCCESS"), self.h.last_log[-2000:])
        selected = self.h.selected()
        self.assertEqual(len([s for s in selected if "_to_" in s]), 18)
        self.assertIn("final", selected)
        self.assertNotIn("cycle2_components", selected)
        series = returns.verify_return_series(self.h.bundle / "returns")
        self.assertEqual((series["count"], series["current_state"], series["terminal"]), (1, "SUCCESS", True))
        names = self.zip_names(archive)
        self.assertIn("final/membership.tsv.gz", names)
        for w in (500, 251, 101):
            self.assertIn(f"edges/normalized_edges_{w}.tsv.gz", names)
        self.assertFalse([n for n in names if n.endswith((".fasta", ".csv")) or "raw_full_search" in n])
        rows = returns.gunzip_bytes(returns.read_return_member(archive, "final/membership.tsv.gz")).splitlines()
        self.assertEqual(rows[0], "sample_id\tcomponent_id\tpartition")
        self.assertEqual(len(rows) - 1, S.ROWS)
        part = {r.split("\t")[0]: r.split("\t")[2] for r in rows[1:]}
        for a, b in ((80, 81), (30, 31), (49, 50), (52, 53), (1, 3)):  # v1-only, 101-only, exact, RC, transitive
            self.assertEqual(part[f"row_{a}"], part[f"row_{b}"])
        receipts = list((self.h.work / "receipts").glob("*.cleanup.json"))
        self.assertTrue(receipts)
        # every accepted width's reconstructable databases are gone, evidence remains
        self.assertFalse(list((self.h.work / "generations").rglob("full_db*")))
        self.assertTrue(list((self.h.work / "generations").rglob("raw_full_search_500.tsv")))
        manifest = json.loads(returns.read_return_member(archive, "final/final_manifest.json"))
        self.assertEqual(manifest["accepted_cycle"], 1)
        self.assertTrue(manifest["bfs_verification"]["matches_production"])

    def test_execute_is_single_use_and_successors_become_noops(self):
        self.assertEqual(self.h.launch("resume")[0], 2)  # no prior attempt: refused
        self.h.launch("execute")
        self.assertEqual(self.h.launch("execute")[0], 2)
        code, archive, state = self.h.launch("resume")
        self.assertEqual((code, archive), (0, None))
        self.assertIn("noop", state)
        self.assertEqual(returns.verify_return_series(self.h.bundle / "returns")["count"], 1)

    def test_unlisted_bundle_file_is_an_integrity_stop(self):
        (self.h.bundle / "src" / "rbpbench" / "extra.py").write_text("print('x')\n")
        code, archive, _ = self.h.launch("execute")
        self.assertEqual(code, 1)
        self.assert_stop(archive, "INTEGRITY_STOP")


class AuditInputRejectionTests(E2EBase):
    def run_fault(self, **env):
        os.environ.update(env)
        code, archive, state = self.h.launch("execute")
        self.assertEqual(code, 1)
        self.assertNotIn("final", self.h.selected())
        return self.assert_stop(archive, "INTEGRITY_STOP")

    def test_empty_audit_database_is_rejected_before_any_directed_search(self):
        status = self.run_fault(FAKE_EMPTY_DB_MATCH="db_validation")
        self.assertIn(".lookup", status["message"])
        self.assertFalse([s for s in self.h.selected() if "_to_" in s])

    def test_wrong_audit_database_is_rejected(self):
        self.run_fault(FAKE_WRONG_DB_MATCH="db_test")

    def test_corrupt_convert2fasta_roundtrip_is_rejected(self):
        self.run_fault(FAKE_CORRUPT_CONVERT_MATCH="db_train")

    def test_positive_control_missing_self_hit_is_rejected(self):
        status = self.run_fault(FAKE_DROP_CONTROL_SELF=",".join(f"row_{i}" for i in range(S.ROWS)))
        self.assertIn("positive control", status["message"])

    def test_missing_full_search_self_hit_is_rejected_and_not_resumable(self):
        status = self.run_fault(FAKE_DROP_SELF="row_5")
        self.assertFalse(status["resumable"])
        self.assertEqual(self.h.launch("resume")[2], "noop: workflow already terminal (INTEGRITY_STOP); nothing to resume")

    def test_foreign_or_ungrouped_full_search_output_is_rejected(self):
        self.run_fault(FAKE_FOREIGN="1")


class RemediationTests(E2EBase):
    def test_first_cycle_violations_trigger_exactly_one_rebuild_that_succeeds(self):
        os.environ["FAKE_EXTRA_HIT_MATCH"] = "cycle1_audit_500"
        code, archive, state = self.h.launch("execute")
        self.assertEqual((code, state), (0, "SUCCESS"), self.h.last_log[-2000:])
        summary1 = json.loads((self.h.work / "selected" / "cycle1_audit_summary.json").read_text())
        self.assertGreater(summary1["payload"]["audit_discovered"], 0)
        self.assertEqual(summary1["payload"]["protected_but_split"], 0)
        self.assertEqual(len([s for s in self.h.selected() if s.startswith("cycle1_") and "_to_" in s]), 18)  # complete first audit
        self.assertEqual(len([s for s in self.h.selected() if s.startswith("cycle2_") and "_to_" in s]), 18)
        names = self.zip_names(archive)
        self.assertIn("audit/violations_cycle1.tsv.gz", names)
        self.assertIn("audit/cycle1_audit_discovered_edges.tsv", names)
        discovered = returns.read_return_member(archive, "audit/cycle1_audit_discovered_edges.tsv").decode().splitlines()
        final = returns.gunzip_bytes(returns.read_return_member(archive, "final/membership.tsv.gz")).splitlines()[1:]
        part = {r.split("\t")[0]: r.split("\t")[2] for r in final}
        for line in discovered:
            a, b = line.split("\t")
            self.assertEqual(part[a], part[b])
        manifest = json.loads(returns.read_return_member(archive, "final/final_manifest.json"))
        self.assertEqual((manifest["accepted_cycle"], manifest["remediation_cycle_used"]), (2, True))
        comps = json.loads((next((self.h.work / "generations" / "cycle2_components").glob("*/components_report.json"))).read_text())
        self.assertEqual(comps["metadata"]["relations"]["audit_discovered_direct"]["pair_count"], len(discovered))

    def test_second_cycle_violation_is_a_terminal_scientific_stop_with_complete_pairs(self):
        os.environ["FAKE_EXTRA_HIT_MATCH"] = "_audit_251"  # matches cycle 1 and cycle 2 audit databases
        code, archive, state = self.h.launch("execute")
        self.assertEqual(code, 1)
        status = self.assert_stop(archive, "SCIENTIFIC_STOP")
        self.assertTrue(status["terminal"])
        self.assertNotIn("final", self.h.selected())
        self.assertNotIn("cycle3_components", self.h.selected())
        rows = returns.gunzip_bytes(returns.read_return_member(archive, "audit/violations_cycle2.tsv.gz")).splitlines()
        self.assertEqual(rows[0], "width\tdirection\tsample_a\tsample_b")
        self.assertEqual(len(rows) - 1, 6)  # one injected pair per direction at width 251, none truncated
        self.assertEqual(self.h.launch("resume")[0], 0)  # successor no-op
        self.assertEqual(returns.verify_return_series(self.h.bundle / "returns")["count"], 1)

    def test_already_protected_pair_split_is_an_integrity_stop(self):
        os.environ["FAKE_EXTRA_HIT_MATCH"] = "cycle1_audit_101"
        real = engine.r3audit.classify_cycle_violations

        def everything_protected(pairs, **kwargs):
            out = real(pairs, **kwargs)
            return {"protected_but_split": out["protected_but_split"] + out["audit_discovered"], "audit_discovered": []}
        with mock.patch.object(engine.r3audit, "classify_cycle_violations", everything_protected):
            code, archive, _ = self.h.launch("execute")
        self.assertEqual(code, 1)
        self.assert_stop(archive, "INTEGRITY_STOP")
        self.assertNotIn("cycle2_components", self.h.selected())


class ResumeTests(E2EBase):
    def interrupt_before(self, method: str, *, advance=47 * 3600):
        original = getattr(engine.Workflow, method)
        clock = S.FakeClock()
        self.h.monitors = S.fake_monitors(clock=clock)

        def wrapped(wf, *args, **kwargs):
            clock.advance(advance)
            return original(wf, *args, **kwargs)
        with mock.patch.object(engine.Workflow, method, wrapped):
            code, archive, state = self.h.launch("execute")
        self.h.monitors = S.fake_monitors()
        return code, archive, state

    def test_scheduler_time_stop_resumes_and_reuses_accepted_records(self):
        code, archive, state = self.interrupt_before("stage_components")
        self.assertEqual((code, state), (1, "SCHEDULER_TIME_STOP"))
        self.assertTrue(self.h.status(archive)["resumable"])
        edge_generations = sorted((self.h.work / "generations" / "edges_500").iterdir())
        code, archive2, state = self.h.launch("resume")
        self.assertEqual((code, state), (0, "SUCCESS"), self.h.last_log[-2000:])
        self.assertEqual(sorted((self.h.work / "generations" / "edges_500").iterdir()), edge_generations)  # reused
        series = returns.verify_return_series(self.h.bundle / "returns")
        self.assertEqual([r["stop_class"] for r in series["returns"]], ["SCHEDULER_TIME_STOP", "SUCCESS"])
        second = json.loads(returns.read_return_member(archive2, "RETURN_MANIFEST.json"))
        self.assertEqual(second["predecessor"]["name"], archive.name)

    def test_stale_upstream_after_each_stage_is_refused_on_resume(self):
        cases = [
            ("stage_components", "edges_101", "normalized_edges_101.tsv"),
            ("stage_assignment", "cycle1_components", "components_report.json"),
            ("stage_exact_audit", "cycle1_assignment", "assignment_summary.json"),
            ("stage_audit_prep", "cycle1_exact_audit", "exact_rc_audit.json"),
            ("stage_audit_summary", "cycle1_audit_500_train_to_validation", "audit_500_train_to_validation.json"),
            ("stage_final", "cycle1_audit_summary", "audit_summary_cycle1.json"),
        ]
        for method, victim, name in cases:
            with self.subTest(method=method):
                S.clear_fake_env()
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()
                self.h = S.Harness(Path(self.tmp.name))
                code, _archive, state = self.interrupt_before(method)
                self.assertEqual(state, "SCHEDULER_TIME_STOP", self.h.last_log[-1500:])
                record = json.loads((self.h.work / "selected" / f"{victim}.json").read_text())
                path = next(self.h.work / e["path"] for e in record["retained"] if e["path"].endswith(name))
                path.write_bytes(path.read_bytes() + b" ")
                code, archive, state = self.h.launch("resume")
                self.assertEqual((code, state), (1, "INTEGRITY_STOP"))
                self.assertNotIn("final", self.h.selected()) if method != "stage_final" else None
                self.assertIn("noop", self.h.launch("resume")[2])

    def test_external_resource_stop_resumes_after_correction(self):
        self.h.monitors = S.fake_monitors(free_disk_gib=lambda path: 120.0)  # >= 80 floor, < 140 for 500 nt
        code, archive, state = self.h.launch("execute")
        self.assertEqual(state, "RESOURCE_EXTERNAL_STOP")
        self.assertIn("140", self.h.status(archive)["message"])
        self.h.monitors = S.fake_monitors()
        self.assertEqual(self.h.launch("resume")[2], "SUCCESS")

    def test_quota_below_80_gib_is_external_and_attestation_branches(self):
        self.h.quota = {"machine_readable": True, "result": {"kind": "limited", "headroom_gib": 50.0}}
        self.assertEqual(self.h.launch("execute")[2], "RESOURCE_EXTERNAL_STOP")
        self.h.quota = {"machine_readable": False, "evidence": []}
        self.assertEqual(self.h.launch("resume")[2], "RESOURCE_EXTERNAL_STOP")  # no attestation recorded
        attestation = Path(self.tmp.name) / "attest.json"
        darwin.write_attestation(self.h.bundle, attestation, "operator")
        self.assertEqual(self.h.launch("resume", attestation_path=attestation)[2], "SUCCESS")

    def test_frozen_ceiling_breach_is_terminal(self):
        from rbpbench.splits.guarded_exec import directory_size_bytes
        self.h.monitors = S.fake_monitors(
            dir_size_bytes=lambda p: 16 * 1024**3 if "edges_101" in str(p) else directory_size_bytes(p))
        code, archive, state = self.h.launch("execute")
        self.assertEqual(state, "RESOURCE_LIMIT_STOP")
        self.assertFalse(self.h.status(archive)["resumable"])
        self.assertIn("noop", self.h.launch("resume")[2])

    def test_tool_failure_is_terminal(self):
        os.environ["FAKE_SEARCH_FAIL_MATCH"] = "full_result"
        self.assertEqual(self.h.launch("execute")[2], "TOOL_FAILURE_STOP")
        self.assertIn("noop", self.h.launch("resume")[2])

    def test_signal_stops_active_search_packages_once_and_resumes(self):
        marker = Path(self.tmp.name) / "hang.pid"
        os.environ.update(FAKE_HANG_MATCH="cycle1_audit_251", FAKE_HANG_MARKER=str(marker))

        def send_when_hung():
            for _ in range(600):
                if marker.exists():
                    time.sleep(0.2)
                    os.kill(os.getpid(), signal.SIGUSR1)
                    return
                time.sleep(0.05)
        thread = threading.Thread(target=send_when_hung)
        thread.start()
        real_collect = returns.collect_workspace

        def collect_with_second_signal(*args, **kwargs):
            os.kill(os.getpid(), signal.SIGTERM)  # must be recorded, never interrupt packaging
            return real_collect(*args, **kwargs)
        with mock.patch.object(returns, "collect_workspace", collect_with_second_signal):
            code, archive, state = self.h.launch("execute")
        thread.join()
        self.assertEqual((code, state), (1, "SIGNAL_STOP"))
        hung = int(marker.read_text())
        self.assertFalse(Path(f"/proc/{hung}").exists() and Path(f"/proc/{hung}/stat").read_text().split()[2] != "Z")
        attempt = json.loads(next((self.h.work / "attempts").glob("attempt_0001.json")).read_text())
        self.assertEqual([s.split()[1] for s in attempt["signals_recorded"]], ["SIGUSR1", "SIGTERM"])
        os.environ.pop("FAKE_HANG_MATCH")
        self.assertEqual(self.h.launch("resume")[2], "SUCCESS")
        self.assertEqual(returns.verify_return_series(self.h.bundle / "returns")["count"], 2)

    def test_unrecorded_interruption_resume_table(self):
        self.interrupt_before("stage_assignment")
        # simulate an uncatchable kill: an attempt with no stop record still holding the lock
        from rbpbench.splits.r3r5.state import Workspace
        ws = Workspace(self.h.work)
        ws.start_attempt(mode="resume", owner={"slurm_job_id": "999"})
        self.h.alive = True
        self.assertEqual(self.h.launch("resume")[0], 2)  # owner job still running: refused
        self.h.alive = False
        code, _archive, state = self.h.launch("resume")
        self.assertEqual(state, "SUCCESS")
        classes = [a["stop"]["class"] for a in ws.attempts()]
        self.assertEqual(classes, ["SCHEDULER_TIME_STOP", "UNRECORDED_INTERRUPTION", "SUCCESS"])

    def test_abandoned_candidate_generation_is_cleaned_on_resume(self):
        self.interrupt_before("stage_assignment")
        orphan = self.h.work / "generations" / "edges_500" / "edges_500__deadbeef0000"
        orphan.mkdir()
        (orphan / "partial.tsv").write_text("row_0\trow_1\n")
        self.assertEqual(self.h.launch("resume")[2], "SUCCESS")
        self.assertFalse(orphan.exists())
        receipts = [json.loads(p.read_text()) for p in (self.h.work / "receipts").glob("abandoned_candidates__*.json")]
        self.assertTrue(any("edges_500__deadbeef0000" in g for r in receipts for g in r["generations"]))


class FinalizationRefusalTests(E2EBase):
    def test_final_refuses_failing_or_stale_evidence(self):
        self.assertEqual(self.h.launch("execute")[2], "SUCCESS")
        from rbpbench.splits.r3r5.state import Workspace
        ws = Workspace(self.h.work)
        chain = [json.loads(p.read_text()) for p in sorted(ws.selected_dir.glob("*.json")) if p.stem != "final"]
        bad = [dict(r) for r in chain]
        for r in bad:
            if r["stage"] == "cycle1_audit_500_train_to_test":
                r["payload"] = {**r["payload"], "violation_count": 1}
        rt = engine.Runtime(contract=self.h.contract, bundle_root=self.h.bundle, workspace=ws, mmseqs_bin=str(self.h.fake),
                            binary={"sha256": "fake-sha"}, monitors=S.fake_monitors(),
                            allocation_deadline=time.monotonic() + 48 * 3600, quota_check=lambda p, w: {})
        wf = engine.Workflow(rt)
        (ws.selected_dir / "final.json").unlink()
        edges = {w: ws.load_record(f"edges_{w}") for w in (500, 251, 101)}
        comps, assign = ws.load_record("cycle1_components"), ws.load_record("cycle1_assignment")
        with self.assertRaises(IntegrityStop):
            wf.stage_final(1, bad, comps, assign, edges, [])
        tampered = ws.retained_path(comps, "components_v2.tsv.gz")
        tampered.write_bytes(tampered.read_bytes()[:-4] + b"\x00\x00\x00\x00")
        with self.assertRaises(IntegrityStop):
            wf.stage_final(1, chain, comps, assign, edges, [])


if __name__ == "__main__":
    unittest.main()
