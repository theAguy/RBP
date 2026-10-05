"""Synthetic-only tests for Task 002C-R2 (fake tool, tiny fixtures)."""

import ast
import json
import os
import random
import stat
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from rbpbench.splits import resource_probe_r2 as r2
from rbpbench.splits.resource_probe_r2 import (
    PROBE_STAGES,
    ProbeGateFailure,
    ProbeInputError,
    ProbeLimits,
    ProbeResourceError,
    ProbeResultError,
    ResourceMonitors,
)

GIB = 1024**3
W = {500: 12, 251: 8, 101: 6}  # tiny synthetic "widths" are length-checked per stage below


def make_universe(n=40):
    return [f"row_{i}" for i in range(n)]


def seq(i, width):
    rng = random.Random(i * 1000 + width)
    return "".join(rng.choice("ACGT") for _ in range(width))


def write_fastas(root, ids):
    paths = {}
    for width in (500, 251, 101):
        p = Path(root) / f"w{width}.fasta"
        p.write_text("".join(f">{sid}\n{seq(i, width)}\n" for i, sid in enumerate(ids)))
        paths[width] = p
    return paths


FAKE = """#!{py}
import os, sys
a = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "ok")
def ids(path):
    return [l[1:].strip() for l in open(path) if l.startswith(">")]
if a[0] == "createdb":
    open(a[2], "w").write("".join(l for l in open(a[1])))
elif a[0] == "search":
    q = ids(a[1]); t = ids(a[2])
    out = []
    for qi in q:
        if mode == "noself" and qi == q[0]:
            continue
        out.append((qi, qi))
        if mode == "cap":
            out.extend((qi, x) for x in t if x != qi)
    open(a[3], "w").write("".join(f"{x}\\t{y}\\n" for x, y in out))
    if mode == "warn":
        sys.stderr.write("Warning: multi-part split\\n")
    if mode == "fail":
        sys.exit(3)
elif a[0] == "createtsv":
    body = open(a[3]).read()
    if mode == "foreign":
        body += "row_0\\tnot_in_universe\\n"
    if mode == "malformed":
        body += "row_0\\n"
    open(a[4], "w").write(body)
"""


class Binary:
    def to_dict(self):
        return {"exe_name": "fake_probe_tool", "resolved_path": "x", "sha256": "0" * 64, "version": "fake"}


def good_monitors(**over):
    base = dict(
        installed_ram_gib=lambda: 64.0,
        available_ram_gib=lambda: 40.0,
        process_tree_rss_kib=lambda pid: 1024 * 1024,
        free_disk_gib=lambda p: 500.0,
        dir_size_bytes=lambda p: 1000,
        swap_used_bytes=lambda: ("vm.swapusage: used = 0.00M", 0),
        memory_pressure=lambda: ("1", "normal"),
    )
    base.update(over)
    return ResourceMonitors(**base)


class ProbeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ids = make_universe(40)
        self.fastas = write_fastas(self.root, self.ids)
        self.fake = self.root / "fake_probe_tool"
        self.fake.write_text(FAKE.replace("{py}", sys.executable))
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)

    def run_probe(self, name="out", monitors=None, limits=None, **kw):
        return r2.run_probe(
            self.root / name, fasta_paths=self.fastas, universe=self.ids, seed=7, mmseqs_bin=str(self.fake),
            binary=Binary(), monitors=monitors or good_monitors(), limits=limits or ProbeLimits(), sample_size=10,
            poll_interval=0.05, **kw,
        )


class StageAndSelectionTests(unittest.TestCase):
    def test_fixed_stage_enum(self):
        self.assertEqual(PROBE_STAGES, ("probe_500", "probe_251", "probe_101"))
        self.assertEqual([r2.validate_stage(s) for s in PROBE_STAGES], [500, 251, 101])
        for bad in ("all", "full", "probe_all", "direct_edges", "components", "components_v2", "assignment", "audit",
                    "r3", "R3", "full_search", "probe_1000", ""):
            with self.assertRaises(ProbeInputError, msg=bad):
                r2.validate_stage(bad)

    def test_selection_deterministic_label_blind(self):
        ids = [f"row_{i}" for i in range(500)]
        a = r2.select_probe_ids(ids, seed=3, sample_size=50)
        b = r2.select_probe_ids(random.Random(1).sample(ids, len(ids)), seed=3, sample_size=50)
        self.assertEqual(a, b)
        self.assertEqual(a["ids"], sorted(a["ids"]))
        self.assertEqual(a["digest"], r2.selection_digest(a["ids"]))
        self.assertNotEqual(a["digest"], r2.select_probe_ids(ids, seed=4, sample_size=50)["digest"])
        with self.assertRaises(ProbeInputError):
            r2.select_probe_ids(ids[:10], seed=3, sample_size=50)
        with self.assertRaises(ProbeInputError):
            r2.select_probe_ids(ids + ["row_1"], seed=3, sample_size=5)
        self.assertEqual(r2.PROBE_QUERY_COUNT, 10_000)
        self.assertAlmostEqual(r2.LINEAR_SCALE, 36.118)


class InputTests(ProbeBase):
    def test_target_must_be_complete_and_valid(self):
        uni = frozenset(self.ids)
        self.assertEqual(len(r2.read_fasta_strict(self.fastas[101], width=101, universe=uni)), 40)
        with self.assertRaises(ProbeInputError):  # wrong width
            r2.read_fasta_strict(self.fastas[101], width=251, universe=uni)
        with self.assertRaises(ProbeInputError):  # smaller target than universe
            r2.read_fasta_strict(self.fastas[101], width=101, universe=uni | {"row_999"})
        with self.assertRaises(ProbeInputError):  # foreign
            r2.read_fasta_strict(self.fastas[101], width=101, universe=uni - {"row_0"})
        bad = self.root / "bad.fasta"
        bad.write_text(">row_0\n" + "N" * 101 + "\n")
        with self.assertRaises(ProbeInputError):
            r2.read_fasta_strict(bad, width=101, universe=frozenset(["row_0"]))
        dup = self.root / "dup.fasta"
        dup.write_text(f">row_0\n{'A'*101}\n>row_0\n{'A'*101}\n")
        with self.assertRaises(ProbeInputError):
            r2.read_fasta_strict(dup, width=101, universe=frozenset(["row_0"]))

    def test_subset_query_reconciles(self):
        records = r2.read_fasta_strict(self.fastas[101], width=101, universe=frozenset(self.ids))
        sel = r2.select_probe_ids(self.ids, seed=1, sample_size=5)["ids"]
        info = r2.write_subset_query_fasta(records, sel, self.root / "q.fasta", width=101)
        self.assertEqual(info["records"], 5)
        with self.assertRaises(ProbeInputError):
            r2.write_subset_query_fasta(records, list(reversed(sel)), self.root / "q2.fasta", width=101)
        with self.assertRaises(ProbeInputError):
            r2.write_subset_query_fasta(records, sel + ["zzz"], self.root / "q3.fasta", width=101)

    def test_argv_frozen_and_thread_cap(self):
        argv = r2.probe_search_command(Path("q"), Path("t"), Path("r"), Path("x"), width=251, threads=4).argv
        self.assertEqual(
            " ".join(argv[6:]),
            "--min-seq-id 0.90 -c 0.95 --cov-mode 0 --max-seqs 361180 --search-type 3 --strand 2 "
            "--alignment-mode 3 -e 1000 --mask 0 -s 7.5 --threads 4",
        )
        for bad in (0, 5, 64):
            with self.assertRaises(ProbeInputError):
                r2.probe_search_command(Path("q"), Path("t"), Path("r"), Path("x"), width=251, threads=bad)
        import inspect

        for fn in (r2.probe_search_command, r2.run_probe, r2.run_probe_stage):
            for name in inspect.signature(fn).parameters:
                for forbidden in ("identity", "min_seq_id", "coverage", "cov", "max_seqs", "sensitivity", "strand"):
                    self.assertNotIn(forbidden, name.lower())


class ResultTests(unittest.TestCase):
    sel = [f"row_{i}" for i in range(5)]
    uni = [f"row_{i}" for i in range(10)]

    def rows(self, extra=()):
        """Grouped by query: each query's self hit then its extras."""
        extra_by_q = {}
        for e in extra:
            extra_by_q.setdefault(e.split("\t")[0], []).append(e)
        out = []
        for s in self.sel:
            out.append(f"{s}\t{s}\n")
            out.extend(extra_by_q.get(s, []))
        return out

    def analyze(self, rows, **kw):
        return r2.analyze_probe_result(rows, selected_ids=kw.get("sel", self.sel), universe=self.uni)

    def test_metrics(self):
        m = self.analyze(self.rows(["row_0\trow_7\n", "row_0\trow_8\n", "row_1\trow_7\n"]))
        self.assertEqual((m["rows"], m["distinct_queries"], m["distinct_targets"]), (8, 5, 7))
        self.assertEqual(m["self_hit_rate"], 1.0)
        self.assertEqual(m["hit_count_quantiles"], {"min": 1, "median": 1, "p95": 3, "p99": 3, "max": 3})
        self.assertNotIn("edges", m)
        self.assertEqual(m["bytes"], sum(len(r.encode()) for r in self.rows(["row_0\trow_7\n", "row_0\trow_8\n", "row_1\trow_7\n"])))

    def test_duplicate_within_group(self):
        with self.assertRaises(ProbeResultError):
            self.analyze(["row_0\trow_0\n", "row_0\trow_7\n", "row_0\trow_7\n"] + self.rows()[1:])

    def test_query_reappearing_later(self):
        rows = self.rows()
        with self.assertRaises(ProbeResultError) as ctx:
            self.analyze(rows + ["row_0\trow_7\n"])
        self.assertIn("reappears", str(ctx.exception))
        with self.assertRaises(ProbeResultError):  # interleaved
            self.analyze(["row_0\trow_0\n", "row_1\trow_1\n", "row_0\trow_7\n"] + self.rows()[2:])

    def test_large_stream_retains_no_all_pair_set(self):
        sel = [f"q{i:05d}" for i in range(3000)]
        uni = sel + [f"t{i}" for i in range(50)]
        stream_rows = []

        def gen():
            for q in sel:
                yield f"{q}\t{q}\n"
                for j in range(40):
                    yield f"{q}\tt{j}\n"

        import tracemalloc

        tracemalloc.start()
        m = r2.analyze_probe_result(gen(), selected_ids=sel, universe=uni)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(m["rows"], 3000 * 41)
        # an all-pair set of 123k tuples would exceed ~15 MB; bounded state stays far below
        self.assertLess(peak, 6_000_000)
        self.assertNotIn("edges", m)

    def test_bad_rows(self):
        for bad, why in [("row_0\n", "malformed"), ("row_0\tx\ty\n", "extra"), ("\trow_1\n", "empty"),
                         ("row_9\trow_1\n", "query not selected"), ("row_0\tfar\n", "foreign target"),
                         ("row_0\trow_0\n", "duplicate pair")]:
            with self.assertRaises(ProbeResultError, msg=why):
                base = self.rows()
                self.analyze(base[:1] + [bad] + base[1:])

    def test_self_hit_loss(self):
        with self.assertRaises(ProbeResultError):
            self.analyze(self.rows()[1:])

    def test_cap_saturation(self):
        sel = ["q"]
        uni = ["q"] + [f"t{i}" for i in range(r2.RESULT_CAP)]
        rows = ["q\tq\n"] + [f"q\tt{i}\n" for i in range(r2.RESULT_CAP - 1)]
        with self.assertRaises(ProbeResultError):
            r2.analyze_probe_result(rows, selected_ids=sel, universe=uni)
        rows.pop()
        self.assertEqual(r2.analyze_probe_result(rows, selected_ids=sel, universe=uni)["rows"], r2.RESULT_CAP - 1)

    def test_block_heterogeneity(self):
        sel = [f"q{i:05d}" for i in range(2000)]

        def stream(dense_n, selection):
            for k, q in enumerate(selection):
                yield f"{q}\t{q}\n"
                if k < dense_n:
                    yield f"{q}\tt\n"

        m = r2.analyze_probe_result(stream(1000, sel), selected_ids=sel, universe=sel + ["t"])
        self.assertEqual([b["rows_per_query"] for b in m["blocks"]], [2.0, 1.0])
        self.assertEqual([b["queries"] for b in m["blocks"]], [1000, 1000])
        self.assertEqual([b["rows"] for b in m["blocks"]], [2000, 1000])
        self.assertEqual(sum(b["bytes"] for b in m["blocks"]), m["bytes"])
        self.assertAlmostEqual(m["block_density_ratio_max"], 2.0 / 1.5)
        r2.check_block_heterogeneity(m, ProbeLimits())  # 1.333 <= 1.5
        sel2 = [f"q{i:05d}" for i in range(4000)]
        m2 = r2.analyze_probe_result(stream(1000, sel2), selected_ids=sel2, universe=sel2 + ["t"])
        self.assertGreater(m2["block_density_ratio_max"], 1.5)
        with self.assertRaises(ProbeGateFailure):
            r2.check_block_heterogeneity(m2, ProbeLimits())

    def test_byte_density_alone_trips_gate(self):
        sel = [f"q{i:05d}" for i in range(4000)]
        uni = sel + ["t" * 400, "t"]

        def stream():
            for k, q in enumerate(sel):
                yield f"{q}\t{q}\n"
                if k < 1000:  # same row count everywhere, but block 0 has long target IDs
                    yield f"{q}\t{'t' * 400}\n"
                else:
                    yield f"{q}\tt\n"

        m = r2.analyze_probe_result(stream(), selected_ids=sel, universe=uni)
        self.assertAlmostEqual(m["block_density_ratio_max"], 1.0)
        self.assertGreater(m["block_bytes_density_ratio_max"], 1.5)
        with self.assertRaises(ProbeGateFailure) as ctx:
            r2.check_block_heterogeneity(m, ProbeLimits())
        self.assertIn("bytes/query", str(ctx.exception))


class ProjectionTests(unittest.TestCase):
    def measured(self, **over):
        base = dict(search_seconds=100.0, createtsv_seconds=10.0, db_creation_seconds=500.0, peak_rss_gib=10.0,
                    result_bytes=1_000_000, retained_upper_bound_bytes=GIB // 10, transient_free_disk_drop_gib=0.1)
        base.update(over)
        return base

    def test_arithmetic(self):
        p = r2.project_width(self.measured())
        self.assertAlmostEqual(p["search_seconds"]["linear"], 3611.8)
        self.assertAlmostEqual(p["search_seconds"]["conservative"], 3611.8 * 1.5)
        self.assertEqual(p["db_creation_seconds_unscaled"], 500.0)  # never multiplied
        self.assertEqual(p["peak_rss_gib"]["observed"], 10.0)
        self.assertEqual(p["peak_rss_gib"]["conservative"], 15.0)
        self.assertAlmostEqual(p["retained_gib"]["conservative"], 0.1 * 36.118 * 1.5)

    def test_real_time_gate_arithmetic(self):
        ok = r2.project_width(self.measured(search_seconds=13.2 * 60))
        bad = r2.project_width(self.measured(search_seconds=13.4 * 60))
        self.assertEqual(r2.evaluate_width_gates(ok), [])
        self.assertTrue(r2.evaluate_width_gates(bad))
        # total: three searches summing to 26.5 min pass, 26.7 min fail
        def total(minutes):
            ps = {s: r2.project_width(self.measured(search_seconds=minutes * 60 / 3)) for s in PROBE_STAGES}
            return r2.evaluate_total_gates(ps)
        self.assertEqual(total(26.5), [])
        self.assertTrue(total(26.7))

    def test_rss_transient_retained_gates(self):
        self.assertTrue(r2.evaluate_width_gates(r2.project_width(self.measured(peak_rss_gib=32.1))))
        self.assertEqual(r2.evaluate_width_gates(r2.project_width(self.measured(peak_rss_gib=31.9))), [])
        # transient: 20 GiB / (36.118 * 1.5) = 0.3692 GiB
        self.assertTrue(r2.evaluate_width_gates(r2.project_width(self.measured(transient_free_disk_drop_gib=0.38))))
        self.assertEqual(r2.evaluate_width_gates(r2.project_width(self.measured(transient_free_disk_drop_gib=0.36))), [])
        # retained: 25 GiB total across widths
        per = 25 / 3 / (36.118 * 1.5)
        mk = lambda f: {s: r2.project_width(self.measured(retained_upper_bound_bytes=int(per * GIB * f))) for s in PROBE_STAGES}
        self.assertEqual(r2.evaluate_total_gates(mk(0.99)), [])
        self.assertTrue(r2.evaluate_total_gates(mk(1.02)))


class LiveMonitorTests(ProbeBase):
    def attempt(self, expect="", **mon):
        with self.assertRaises(ProbeResourceError) as ctx:
            self.run_probe(monitors=good_monitors(**mon))
        self.assertIn(expect, str(ctx.exception))
        stopped = json.loads((self.root / "out" / "stopped.json").read_text())
        self.assertEqual(stopped["stage"], "failed")

    def test_undetectable_memory(self):
        self.attempt("available RAM", available_ram_gib=lambda: None)

    def test_low_ram(self):
        self.attempt("available RAM", available_ram_gib=lambda: 23.9)

    def test_installed_ram(self):
        self.attempt("installed RAM", installed_ram_gib=lambda: 32.0)

    def test_pressure_unavailable_or_nonnormal(self):
        self.attempt("memory pressure", memory_pressure=lambda: ("", None))
        os.rename(self.root / "out", self.root / "gone1")
        self.attempt("memory pressure", memory_pressure=lambda: ("2", "warn"))

    def test_swap(self):
        values = iter([0] + [3 * GIB] * 1000)
        self.attempt("swap increased", swap_used_bytes=lambda: ("raw", next(values)))

    def test_swap_unavailable(self):
        self.attempt("swap use is unavailable", swap_used_bytes=lambda: ("", None))

    def test_rss_unavailable(self):
        self.attempt("unavailable", process_tree_rss_kib=lambda pid: None)

    def test_disk_floor_and_prewidth(self):
        self.attempt("free disk", free_disk_gib=lambda p: 99.0)  # below the 100-GiB pre-width gate

    def test_live_disk_floor(self):
        calls = iter([500.0] * 3 + [79.0] * 1000)
        self.attempt("free disk", free_disk_gib=lambda p: next(calls))

    def test_output_ceiling(self):
        self.attempt("output/temp", dir_size_bytes=lambda p: 11 * GIB)

    def test_timeout(self):
        t = iter(range(0, 10_000_000, 4000))
        self.attempt("timeout", clock=lambda: float(next(t)))


class WorkflowTests(ProbeBase):
    def test_success_end_to_end_and_return_schema(self):
        summary = self.run_probe()
        self.assertEqual(summary["status"], "SUCCESS")
        root = self.root / "out"
        self.assertEqual(sorted(p.stem for p in (root / "selected").glob("*.json")), sorted(PROBE_STAGES))
        recs = [json.loads((root / "selected" / f"{s}.json").read_text()) for s in PROBE_STAGES]
        digests = {r["selection_digest"] for r in recs}
        self.assertEqual(len(digests), 1)  # identical IDs at every width
        selection = json.loads((root / "selection.json").read_text())
        self.assertEqual(digests, {selection["digest"]})
        for r in recs:
            self.assertFalse(r["scientific_edge_evidence"])
            self.assertEqual(r["metrics"]["self_hit_rate"], 1.0)
            self.assertIn("--threads 4", r["steps"]["search"]["command_text"])
        a = r2.build_return_summary(root)
        b = r2.build_return_summary(root)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        blob = json.dumps(a)
        for s in range(40):
            for width in (500, 251, 101):
                self.assertNotIn(seq(s, width), blob)  # no raw sequence
        names = {f["path"].split("/")[-1] for st in a["stages"].values() for f in st["excluded_raw_artifacts"]}
        self.assertTrue({"result.tsv", "query_db", "target_db"} <= {n for n in names})
        for st in a["stages"].values():
            for f in st["excluded_raw_artifacts"]:
                self.assertEqual(set(f), {"path", "bytes", "sha256"})
        self.assertEqual(a["selection"]["ids"], selection["ids"])
        self.assertNotIn("label", blob.lower())

    def test_existing_output_root_refused(self):
        (self.root / "out").mkdir()
        with self.assertRaises(ProbeInputError):
            self.run_probe()
        self.assertEqual(list((self.root / "out").iterdir()), [])
        (self.root / "out2").mkdir()
        (self.root / "out2" / "x").write_text("1")
        with self.assertRaises(ProbeInputError):
            self.run_probe("out2")
        self.assertEqual(sorted(p.name for p in (self.root / "out2").iterdir()), ["x"])

    def test_failure_stops_without_retry_or_progress(self):
        os.environ["FAKE_MODE"] = "fail"
        with self.assertRaises(ProbeResourceError):
            self.run_probe()
        root = self.root / "out"
        self.assertEqual(list((root / "selected").glob("*.json")), [])
        self.assertTrue((root / "stopped.json").exists())
        self.assertFalse((root / "summary.json").exists())
        self.assertEqual(len(list((root / "generations").iterdir())), 1)  # never reached 251/101, no retry

    def test_prior_accepted_record_untouched_by_later_failure(self):
        root = self.root / "out"
        state = {"n": 0}

        def pressure():
            return ("1", "normal")

        # run once successfully to a root, then simulate a failed later stage on a fresh root
        self.run_probe()
        before = (root / "selected" / "probe_500.json").read_bytes()
        os.environ["FAKE_MODE"] = "noself"
        with self.assertRaises(ProbeResultError):
            self.run_probe("out_b")
        self.assertEqual((root / "selected" / "probe_500.json").read_bytes(), before)
        self.assertEqual(list((self.root / "out_b" / "selected").glob("*.json")), [])

    def test_result_defects_stop(self):
        for mode, exc in [("foreign", ProbeResultError), ("malformed", ProbeResultError), ("cap", ProbeResultError),
                          ("warn", ProbeResourceError)]:
            os.environ["FAKE_MODE"] = mode
            name = f"out_{mode}"
            if mode == "cap":
                with self.subTest(mode):
                    # cap saturation is exercised with the analyzer; here every target hit stays below the cap
                    summary = self.run_probe(name)
                    self.assertEqual(summary["status"], "SUCCESS")
                continue
            with self.subTest(mode), self.assertRaises(exc):
                self.run_probe(name)

    def test_gate_failure_writes_stopped_with_evidence(self):
        limits = replace(ProbeLimits(), max_projected_rss_gib=0.001)
        with self.assertRaises(ProbeGateFailure):
            self.run_probe(limits=limits)
        stopped = json.loads((self.root / "out" / "stopped.json").read_text())
        self.assertTrue(stopped["gate_failures"])
        self.assertEqual(list((self.root / "out" / "selected").glob("*.json")), [])
        self.assertEqual(r2.build_return_summary(self.root / "out")["status"], "STOPPED")

    def test_wrong_fasta_widths_refused(self):
        with self.assertRaises(ProbeInputError):
            r2.run_probe(self.root / "o", fasta_paths={500: self.fastas[500]}, universe=self.ids, seed=1,
                         mmseqs_bin=str(self.fake), binary=Binary(), monitors=good_monitors(), sample_size=5)


class CorrectionTests(ProbeBase):
    def test_f2_warning_stops_before_next_command(self):
        # Fake tool logs every launch; a createdb(target) warning must prevent search.
        log = self.root / "launches.log"
        script = self.fake.read_text().replace(
            "a = sys.argv[1:]\n", f"a = sys.argv[1:]\nopen({str(log)!r}, 'a').write(a[0] + '\\n')\n"
        )
        script = script.replace(
            'if a[0] == "createdb":\n',
            'if a[0] == "createdb":\n    if mode == "dbwarn" and "query" not in a[1]:\n        sys.stderr.write("WARNING: database was split into 2 parts\\n")\n',
        )
        self.fake.write_text(script)
        os.environ["FAKE_MODE"] = "dbwarn"
        with self.assertRaises(ProbeResourceError) as ctx:
            self.run_probe()
        self.assertIn("createdb_target", str(ctx.exception))
        self.assertEqual(log.read_text().split(), ["createdb", "createdb"])  # no search launched
        os.environ["FAKE_MODE"] = "warn"
        log.unlink()
        with self.assertRaises(ProbeResourceError) as ctx:
            self.run_probe("out_s")
        self.assertIn("search", str(ctx.exception))
        self.assertEqual(log.read_text().split(), ["createdb", "createdb", "search"])  # no createtsv

    def test_f2_precise_patterns(self):
        rx = r2._WARNING_RE
        for bad in ("Warning: something", "WARNING database", "Error: x", "multi-part search", "target split into 3 parts",
                    "Out of memory", "result truncated", "--split-memory-limit override", "cannot fit in memory"):
            self.assertTrue(rx.search(bad), bad)
        for ok in ("/tmp/split_dir/query_db", "Time for processing: 0h 0m 1s", "createdb done", "splitted_file.txt"):
            self.assertIsNone(rx.search(ok), ok)

    def test_f3_stage_disk_minimum_includes_every_command(self):
        # free disk dips only during the createtsv command (fourth launch)
        launches = {"n": 0}

        def free(p):
            return 500.0 - (400.0 if launches["n"] >= 4 else 0.0)

        real_pre = r2.check_pre_launch

        def counting_pre(*a, **k):
            launches["n"] += 1
            return real_pre(*a, **k)

        r2.check_pre_launch = counting_pre
        self.addCleanup(setattr, r2, "check_pre_launch", real_pre)
        limits = replace(ProbeLimits(), min_free_disk_gib_live=0.0)
        with self.assertRaises(ProbeGateFailure) as ctx:  # 400 GiB drop => projected >> 20 GiB
            self.run_probe(monitors=good_monitors(free_disk_gib=free), limits=limits)
        self.assertIn("transient", str(ctx.exception))
        stopped = json.loads((self.root / "out" / "stopped.json").read_text())
        measured = stopped["record"]["measured"]
        self.assertEqual(measured["stage_start_free_disk_gib"], 500.0)
        self.assertEqual(measured["stage_min_free_disk_gib"], 100.0)
        self.assertEqual(measured["transient_free_disk_drop_gib"], 400.0)
        self.assertLess(stopped["record"]["steps"]["search"]["start_free_disk_gib"] - stopped["record"]["steps"]["search"]["min_free_disk_gib"], 1.0)

    def test_f3_retained_upper_bound_uses_larger_of_db_and_tsv(self):
        m = {"search_seconds": 1, "createtsv_seconds": 1, "db_creation_seconds": 1, "peak_rss_gib": 1,
             "result_bytes": 3 * GIB, "retained_upper_bound_bytes": 3 * GIB, "transient_free_disk_drop_gib": 0}
        p = r2.project_width(m)
        self.assertAlmostEqual(p["retained_gib"]["linear"], 3 * 36.118)
        self.assertIn("upper-bound", p["retained_note"])
        summary = self.run_probe()
        rec = json.loads((self.root / "out" / "selected" / "probe_500.json").read_text())["measured"]
        self.assertEqual(rec["retained_upper_bound_bytes"], max(rec["raw_result_db_bytes"], rec["rendered_tsv_bytes"]))
        self.assertGreater(rec["rendered_tsv_bytes"], 0)

    def test_f3_tsv_larger_than_db_drives_bound(self):
        script = self.fake.read_text()
        script = script.replace(
            '    open(a[3], "w").write("".join(f"{x}\\t{y}\\n" for x, y in out))',
            '    open(a[3], "w").write("".join((f"{x}\\n" if mode == "bigtsv" else f"{x}\\t{y}\\n") for x, y in out))',
        ).replace(
            '    body = open(a[3]).read()\n',
            '    body = open(a[3]).read()\n    if mode == "bigtsv":\n        body = "".join(f"{l.strip()}\\t{l.strip()}\\n" for l in body.splitlines())\n',
        )
        self.assertNotEqual(script, self.fake.read_text())
        self.fake.write_text(script)
        os.environ["FAKE_MODE"] = "bigtsv"
        self.run_probe()
        rec = json.loads((self.root / "out" / "selected" / "probe_500.json").read_text())["measured"]
        self.assertGreater(rec["rendered_tsv_bytes"], rec["raw_result_db_bytes"])
        self.assertEqual(rec["retained_upper_bound_bytes"], rec["rendered_tsv_bytes"])

    def test_f4_short_lived_child_peak(self):
        # poll interval far longer than the child's life: live sampler never runs
        calls = {"n": 0}

        def rss(pid):
            calls["n"] += 1
            return 1

        big = 40 * 1024 * 1024  # 40 GiB in KiB; x1.5 = 60 > 48
        with self.assertRaises(ProbeGateFailure) as ctx:
            r2.run_probe(self.root / "o4", fasta_paths=self.fastas, universe=self.ids, seed=7, mmseqs_bin=str(self.fake),
                         binary=Binary(), monitors=good_monitors(process_tree_rss_kib=rss, children_peak_rss_kib=lambda: big),
                         sample_size=10, poll_interval=30.0)
        self.assertIn("RSS", str(ctx.exception))
        stopped = json.loads((self.root / "o4" / "stopped.json").read_text())
        step = stopped["record"]["steps"]["search"]
        self.assertEqual(step["peak_rss_kib"], big)
        self.assertEqual(step["peak_rss_source"]["cumulative_children_kib"], big)
        self.assertIn("limitation", step["peak_rss_source"])

    def test_f4_unavailable_post_run_measurement_fails_closed(self):
        with self.assertRaises(ProbeResourceError) as ctx:
            self.run_probe(monitors=good_monitors(children_peak_rss_kib=lambda: None))
        self.assertIn("child peak RSS", str(ctx.exception))

    def test_f5_invalid_universe_ids(self):
        good = ["a", "b"]
        for bad in (["a", ""], ["a", "b\tc"], ["a", "b\nc"], ["a", "a"], [], ["a", "b\r"]):
            with self.assertRaises(ProbeInputError, msg=bad):
                r2.validate_canonical_ids(bad)
            with self.assertRaises(ProbeInputError, msg=bad):
                r2.select_probe_ids(bad, seed=1, sample_size=1)
            with self.assertRaises(ProbeInputError, msg=bad):
                r2.read_fasta_strict(self.fastas[101], width=101, universe=frozenset(bad))
            with self.assertRaises(ProbeInputError, msg=bad):
                r2.run_probe(self.root / "never", fasta_paths=self.fastas, universe=bad, seed=1, mmseqs_bin="x",
                             binary=Binary(), monitors=good_monitors(), sample_size=1)
        self.assertFalse((self.root / "never").exists())
        self.assertEqual(r2.validate_canonical_ids(good), frozenset(good))

    def test_f5_empty_fasta_header(self):
        p = self.root / "empty_header.fasta"
        p.write_text(">\n" + "A" * 101 + "\n>row_1\n" + "A" * 101 + "\n")
        with self.assertRaises(ProbeInputError):
            r2.read_fasta_strict(p, width=101, universe=frozenset(["row_1"]))
        with self.assertRaises(ProbeInputError):
            r2.read_fasta_strict(p, width=101, universe=frozenset(["", "row_1"]))


class BoundaryTests(unittest.TestCase):
    def test_no_edge_component_or_r3_writer_in_probe_path(self):
        path = Path(r2.__file__)
        tree = ast.parse(path.read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        for forbidden in ("rbpbench.splits.direct_edges", "rbpbench.splits.components_v2", "rbpbench.splits.assignment",
                          "rbpbench.splits.audit", "rbpbench.splits.mmseqs_audit", "rbpbench.splits.runner",
                          "rbpbench.splits.runner_002c", "rbpbench.splits.portable_002c3"):
            self.assertNotIn(forbidden, imported)
        public = [n for n in dir(r2) if not n.startswith("_")]
        for n in public:
            for word in ("normalize", "build_components", "write_normalized", "assign", "full_query"):
                self.assertNotIn(word, n.lower())
        self.assertEqual(r2.PROBE_STAGES, tuple(f"probe_{w}" for w in (500, 251, 101)))


if __name__ == "__main__":
    unittest.main()
