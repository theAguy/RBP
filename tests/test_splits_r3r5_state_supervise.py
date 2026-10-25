"""Transactions, cleanup receipts, supervision, and signals (tests 4, 6, 14, 22)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from rbpbench.coordinates.commands import ToolCommand
from rbpbench.splits.r3r5 import state, supervise
from rbpbench.splits.r3r5.contract import fixture_contract
from rbpbench.splits.r3r5.darwin import SignalLatch
from rbpbench.splits.r3r5.stops import (
    ExternalResourceStop,
    IntegrityStop,
    ResourceLimitStop,
    SchedulerTimeStop,
    SignalStop,
    StopClass,
    ToolFailureStop,
)
from tests import r3r5_support as S


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = state.Workspace(Path(self.tmp.name) / "work")
        self.ws.create()

    def tearDown(self):
        state.PROMOTION_HOOK = None
        self.tmp.cleanup()

    def candidate(self, key="stage_a", text="evidence\n"):
        gen = self.ws.new_generation("grp", key)
        (gen / "out.json").write_text(text)
        (gen / "big_db").write_text("reconstructable\n")
        return gen

    def test_failure_at_every_promotion_boundary_selects_nothing_and_keeps_prior_records(self):
        self.ws.promote("prior", group="grp", generation=self.candidate("prior"), fingerprint="fp0", upstream={},
                                retained=[self.ws.group_dir("grp").glob("prior__*/out.json").__next__()])
        prior_bytes = self.ws.record_path("prior").read_bytes()
        for phase in ("before_inventory", "before_atomic_write"):
            with self.subTest(phase=phase):
                def hook(key, current, phase=phase):
                    if current == phase:
                        raise OSError("injected transaction failure")
                state.PROMOTION_HOOK = hook
                gen = self.candidate("stage_a")
                with self.assertRaises(OSError):
                    self.ws.promote("stage_a", group="grp", generation=gen, fingerprint="fp", upstream={},
                                    retained=[gen / "out.json"])
                self.assertIsNone(self.ws.load_record("stage_a"))
                self.assertEqual(self.ws.record_path("prior").read_bytes(), prior_bytes)
                self.assertFalse(list(self.ws.selected_dir.glob(".*.tmp")))
        state.PROMOTION_HOOK = None
        self.assertIsNotNone(self.ws.current("prior", fingerprint="fp0"))

    def test_atomic_write_interrupted_before_replace_leaves_no_record(self):
        gen = self.candidate()
        real_replace = os.replace

        def failing_replace(src, dst):
            raise OSError("disk vanished during replace")
        try:
            os.replace = failing_replace
            with self.assertRaises(OSError):
                self.ws.promote("stage_a", group="grp", generation=gen, fingerprint="fp", upstream={}, retained=[gen / "out.json"])
        finally:
            os.replace = real_replace
        self.assertIsNone(self.ws.load_record("stage_a"))

    def test_accepted_records_are_never_overwritten(self):
        gen = self.candidate()
        self.ws.promote("stage_a", group="grp", generation=gen, fingerprint="fp", upstream={}, retained=[gen / "out.json"])
        with self.assertRaises(IntegrityStop):
            self.ws.promote("stage_a", group="grp", generation=self.candidate(), fingerprint="fp", upstream={},
                            retained=[gen / "out.json"])

    def test_stale_or_damaged_records_are_integrity_stops(self):
        gen = self.candidate()
        self.ws.promote("stage_a", group="grp", generation=gen, fingerprint="fp", upstream={}, retained=[gen / "out.json"])
        with self.assertRaises(IntegrityStop):
            self.ws.current("stage_a", fingerprint="different-upstream")
        (gen / "out.json").write_text("tampered\n")
        with self.assertRaises(IntegrityStop):
            self.ws.current("stage_a", fingerprint="fp")

    def test_cleanup_receipts_delete_only_reconstructable_files(self):
        gen = self.candidate()
        record = self.ws.promote("stage_a", group="grp", generation=gen, fingerprint="fp", upstream={},
                                 retained=[gen / "out.json"], reconstructable=[gen / "big_db"])
        receipt = self.ws.cleanup_reconstructable(record, reason="test")
        self.assertEqual(receipt["status"], "deletion_complete")
        self.assertEqual([d["path"].split("/")[-1] for d in receipt["deleted"]], ["big_db"])
        self.assertFalse((gen / "big_db").exists())
        self.assertTrue((gen / "out.json").exists())
        self.assertIsNone(self.ws.cleanup_reconstructable(record, reason="again"))  # idempotent

    def test_cleanup_refuses_to_delete_accepted_evidence(self):
        gen = self.candidate()
        sub = gen / "sub"
        sub.mkdir()
        (sub / "kept.json").write_text("{}\n")
        record = self.ws.promote("stage_a", group="grp", generation=gen, fingerprint="fp", upstream={},
                                 retained=[gen / "out.json", sub / "kept.json"], reconstructable=[gen / "out.json"])
        with self.assertRaises(IntegrityStop):
            self.ws.cleanup_reconstructable(record, reason="bad")
        record2 = self.ws.load_record("stage_a")
        record2["reconstructable"] = [self.ws.rel(sub)]
        with self.assertRaises(IntegrityStop):
            self.ws.cleanup_reconstructable(record2, reason="directory holding evidence")
        self.assertTrue((gen / "out.json").exists() and (sub / "kept.json").exists())

    def test_abandoned_candidates_are_removed_with_a_receipt(self):
        gen = self.candidate()
        self.ws.promote("stage_a", group="grp", generation=gen, fingerprint="fp", upstream={}, retained=[gen / "out.json"])
        orphan = self.candidate("stage_b")
        orphan_rel = self.ws.rel(orphan)
        receipt = self.ws.cleanup_abandoned_candidates()
        self.assertEqual(receipt["generations"], [orphan_rel])
        self.assertEqual(receipt["status"], "deletion_complete")
        self.assertEqual({Path(d["path"]).name for d in receipt["deleted"]}, {"out.json", "big_db"})
        self.assertFalse(orphan.exists())
        self.assertTrue(gen.exists())

    def test_attempt_ledger_terminal_state_and_lock(self):
        attempt = self.ws.start_attempt(mode="execute", owner={"slurm_job_id": "1"})
        self.assertIsNotNone(self.ws.lock())
        self.ws.finish_attempt(attempt, stop_class=StopClass.SIGNAL, message="sig", signals=["USR1"])
        self.assertIsNone(self.ws.lock())
        self.assertIsNone(self.ws.terminal())
        attempt = self.ws.start_attempt(mode="resume", owner={"slurm_job_id": "2"})
        self.ws.finish_attempt(attempt, stop_class=StopClass.SCIENTIFIC, message="giant", signals=[])
        self.assertEqual(self.ws.terminal()["class"], "SCIENTIFIC_STOP")
        self.assertEqual([a["stop"]["class"] for a in self.ws.attempts()], ["SIGNAL_STOP", "SCIENTIFIC_STOP"])


SLEEPER = ToolCommand(tool="fake_child", argv=(sys.executable, "-c", "import time,os,sys; "
                                               "open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(60)", "PIDFILE"),
                      pinned_version="x")


def sleeper(pidfile: Path) -> ToolCommand:
    return ToolCommand(tool="fake_child", argv=SLEEPER.argv[:-1] + (str(pidfile),), pinned_version="x")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    return not (stat.exists() and stat.read_text().split()[2] == "Z")


class SupervisorTests(unittest.TestCase):
    contract = fixture_contract(row_count=10)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_child(self, command, *, monitors=None, deadline=None, width=101):
        deadline = deadline or supervise.Deadline(time.monotonic() + 30, supervise.DEADLINE_STAGE)
        return supervise.run_child(command, contract=self.contract, monitors=monitors or S.fake_monitors(),
                                   log_dir=self.root / "logs", owned_dir=self.root / "owned", width=width,
                                   deadline=deadline, binary={}, poll_interval=0.05)

    def wait_for_pid(self, pidfile, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            if pidfile.exists() and pidfile.read_text():
                return int(pidfile.read_text())
            time.sleep(0.02)
        raise AssertionError("child did not start")

    def assert_stops_and_kills(self, exc_type, *, monitors=None, deadline=None):
        pidfile = self.root / "pid"
        if pidfile.exists():
            pidfile.unlink()
        with self.assertRaises(exc_type):
            self.run_child(sleeper(pidfile), monitors=monitors, deadline=deadline)
        self.assertFalse(pid_alive(self.wait_for_pid(pidfile)))

    def test_success_records_evidence(self):
        ok = ToolCommand(tool="ok", argv=(sys.executable, "-c", "print('done')"), pinned_version="x")
        evidence = self.run_child(ok)
        self.assertEqual(evidence["returncode"], 0)
        self.assertEqual(evidence["deadline_kind"], supervise.DEADLINE_STAGE)

    def test_stage_timeout_is_terminal_and_reserve_deadline_is_resumable(self):
        self.assert_stops_and_kills(ResourceLimitStop, deadline=supervise.Deadline(time.monotonic() + 0.3, supervise.DEADLINE_STAGE))
        self.assert_stops_and_kills(ResourceLimitStop, deadline=supervise.Deadline(time.monotonic() + 0.3, supervise.DEADLINE_BUDGET))
        self.assert_stops_and_kills(SchedulerTimeStop, deadline=supervise.Deadline(time.monotonic() + 0.3, supervise.DEADLINE_RESERVE))

    def test_live_resource_violations(self):
        cases = [
            (ResourceLimitStop, dict(dir_size_bytes=lambda p: int(16 * 1024**3))),  # > 15-GiB width-101 ceiling
            (ExternalResourceStop, dict(free_disk_gib=lambda p: 79.0)),
            (ExternalResourceStop, dict(available_ram_gib=lambda: 23.5)),
            (ExternalResourceStop, dict(process_tree_rss_kib=lambda pid: None)),
            (ExternalResourceStop, dict(memory_pressure=lambda: ("x", "warn"))),
        ]
        for exc, overrides in cases:
            calls = {"n": 0}
            # let pre-launch checks pass, then fail live
            def delayed(name, value, calls=calls, overrides=overrides):
                base = S.fake_monitors()
                original = getattr(base, name)
                def fn(*args):
                    calls["n"] += 1
                    return overrides[name](*args) if calls["n"] > 1 else original(*args)
                return fn
            name = next(iter(overrides))
            with self.subTest(name=name):
                self.assert_stops_and_kills(exc, monitors=S.fake_monitors(**{name: delayed(name, None)}))

    def test_swap_growth_is_an_external_stop(self):
        state_ = {"n": 0}
        def swap():
            state_["n"] += 1
            return ("raw", 0 if state_["n"] == 1 else int(3 * 1024**3))
        self.assert_stops_and_kills(ExternalResourceStop, monitors=S.fake_monitors(swap_used_bytes=swap))

    def test_prelaunch_gates(self):
        for overrides in (dict(installed_ram_gib=lambda: 32.0), dict(available_ram_gib=lambda: None),
                          dict(free_disk_gib=lambda p: 50.0), dict(swap_used_bytes=lambda: ("x", None))):
            with self.subTest(overrides=list(overrides)), self.assertRaises(ExternalResourceStop):
                self.run_child(ToolCommand("ok", (sys.executable, "-c", "pass"), "x"), monitors=S.fake_monitors(**overrides))

    def test_tool_failure_and_fatal_diagnostics(self):
        with self.assertRaises(ToolFailureStop):
            self.run_child(ToolCommand("bad", (sys.executable, "-c", "import sys; sys.exit(3)"), "x"))
        with self.assertRaises(ToolFailureStop):
            self.run_child(ToolCommand("diag", (sys.executable, "-c",
                                                "import sys; sys.stderr.write('Process prefiltering step 1 of 3\\n')"), "x"))
        evidence = self.run_child(ToolCommand("warn", (sys.executable, "-c",
                                                       "import sys; sys.stderr.write('Warning: harmless\\n')"), "x"))
        self.assertTrue(evidence["advisory_diagnostics"])


class SignalLatchTests(unittest.TestCase):
    def test_first_signal_stops_and_kills_the_group_once_later_signals_are_only_recorded(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        latch = SignalLatch()
        latch.install()
        self.addCleanup(latch.restore)
        pidfile = root / "pid"
        timer = threading.Timer(0.6, lambda: os.kill(os.getpid(), signal.SIGUSR1))
        timer.start()
        with self.assertRaises(SignalStop):
            supervise.run_child(sleeper(pidfile), contract=fixture_contract(row_count=1), monitors=S.fake_monitors(),
                                log_dir=root / "logs", owned_dir=root / "owned", width=101,
                                deadline=supervise.Deadline(time.monotonic() + 30, supervise.DEADLINE_STAGE),
                                binary={}, poll_interval=0.05)
        child = int(pidfile.read_text())
        self.assertFalse(pid_alive(child))
        # later catchable signals are recorded but never raise into the packaging path
        os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGUSR1)
        time.sleep(0.1)
        self.assertEqual(len(latch.received), 3)
        self.assertTrue(latch.latched)

    def test_real_sigterm_to_a_subprocess_launcher_records_signal(self):
        code = ("import os, signal, time\n"
                "from rbpbench.splits.r3r5.darwin import SignalLatch\n"
                "from rbpbench.splits.r3r5.stops import SignalStop\n"
                "l = SignalLatch(); l.install()\n"
                "try:\n    time.sleep(10)\nexcept SignalStop:\n    print('stopped', len(l.received))\n")
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        time.sleep(1.0)
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=10)
        self.assertEqual(out.strip(), "stopped 1")


if __name__ == "__main__":
    unittest.main()
