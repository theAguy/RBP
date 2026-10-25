"""R3–R5 contract, frozen commands, and no-override proofs (tests 1, 16)."""

from __future__ import annotations

import inspect
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rbpbench.splits import commands as cmd
from rbpbench.splits.r3r5 import contract as c
from rbpbench.splits.r3r5 import engine

REPO = Path(__file__).resolve().parents[1]

EXPECTED_FLAGS = {
    500: ["--min-seq-id", "0.90", "-c", "0.80", "--cov-mode", "0", "--max-seqs", "361180", "--search-type", "3",
          "--strand", "2", "--alignment-mode", "3", "-e", "1000", "--mask", "0", "-s", "7.5", "--threads", "4"],
}
EXPECTED_FLAGS[251] = [x if x != "0.80" else "0.95" for x in EXPECTED_FLAGS[500]]
EXPECTED_FLAGS[101] = EXPECTED_FLAGS[251]


class ContractTests(unittest.TestCase):
    def test_production_toml_equals_reviewed_constants(self):
        loaded = c.load_production_contract(REPO / c.CONFIG_REL)
        self.assertEqual(loaded, c.PRODUCTION)
        self.assertEqual(loaded.mode, "production")
        self.assertEqual([loaded.resources.launch_free_gib(w) for w in c.WIDTHS], [140.0, 105.0, 95.0])
        self.assertEqual(loaded.resources.min_quota_headroom_gib, 80.0)
        self.assertEqual(loaded.row_count, 361_180)
        self.assertEqual(loaded.seed, 20260925)
        self.assertEqual(loaded.max_audit_cycles, 2)

    def test_any_toml_drift_is_refused(self):
        text = (REPO / c.CONFIG_REL).read_text()
        for old, new in (("evaluation_floor = 30", "evaluation_floor = 29"),
                         ('"500" = 60.0', '"500" = 61.0'),
                         ("min_quota_headroom_gib = 80.0", "min_quota_headroom_gib = 50.0"),
                         ('mode = "production"', 'mode = "fixture"'),
                         ("seed = 20260925", "seed = 1"),
                         ("single_component_fraction = 0.05", "single_component_fraction = 0.5")):
            with self.subTest(old=old), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.toml"
                path.write_text(text.replace(old, new, 1))
                with self.assertRaises(c.ContractError):
                    c.load_production_contract(path)

    def test_fixture_contract_is_marked_and_distinct(self):
        fixture = c.fixture_contract(row_count=10)
        self.assertEqual(fixture.mode, "fixture")
        self.assertNotEqual(fixture.content_hash, c.PRODUCTION.content_hash)

    def test_plan_frozen_inputs_are_bound(self):
        specs = {s.role: s for s in c.PRODUCTION.inputs}
        self.assertEqual(set(specs), c.REQUIRED_INPUT_ROLES)
        self.assertEqual(specs["dataset_csv"].byte_size, 724_425_277)
        self.assertEqual(specs["fasta_500"].sha256, "0849d4f8aceaed37c3dc7fec69056f38ae344338aa4adf321a3e11c4a72df0b0")
        self.assertEqual(specs["v1_component_membership"].byte_size, 14_578_797)
        self.assertEqual(c.PRODUCTION.environment.mmseqs_sha256,
                         "d6d1bf1b50c095eb0cb66f685a7fb1d9b8b69497e1e88416fd48f28e313cc773")
        # tracked manifests that the plan pins by hash
        from rbpbench.data.audit import sha256_file
        for role in ("dataset_audit", "proteins_tsv", "decode_manifest"):
            self.assertEqual(sha256_file(REPO / specs[role].path), specs[role].sha256)

    def test_tracked_r2_return_manifest_matches_the_production_contract_exactly(self):
        """H1: the accepted tracked 5,001-byte artifact is bound byte for byte."""
        import hashlib
        spec = c.PRODUCTION.input("r2_return_manifest")
        data = (REPO / spec.path).read_bytes()
        self.assertEqual(spec.path, "manifests/sequence_r2_darwin_convergence_return.json")
        self.assertEqual((len(data), spec.byte_size), (5_001, 5_001))
        self.assertEqual(hashlib.sha256(data).hexdigest(), spec.sha256)
        self.assertEqual(spec.sha256, "3a275d538f2167ed6a1a01b80bfb34295890ac1f5d30611fb5e34bf2e5d02123")
        self.assertTrue(data.endswith(b"}\n") and not data.endswith(b"\n\n"))
        self.assertEqual(c.load_production_contract(REPO / c.CONFIG_REL).input("r2_return_manifest"), spec)

    def test_tracked_manifests_bind_and_later_byte_drift_fails_closed(self):
        from rbpbench.splits.r3r5 import bundle
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = {}
            for role in ("dataset_audit", "proteins_tsv", "decode_manifest", "r2_return_manifest"):
                sources[role] = REPO / c.PRODUCTION.input(role).path
                bundle.check_source_input(c.PRODUCTION.input(role), sources[role])  # accepted as tracked
            drift = root / "r2.json"
            drift.write_bytes(sources["r2_return_manifest"].read_bytes() + b"\n")
            with self.assertRaises(bundle.BundleError):
                bundle.check_source_input(c.PRODUCTION.input("r2_return_manifest"), drift)
            drift.write_bytes(sources["r2_return_manifest"].read_bytes().replace(b"accepted", b"Accepted", 1))
            with self.assertRaises(bundle.BundleError):
                bundle.check_source_input(c.PRODUCTION.input("r2_return_manifest"), drift)


class FrozenCommandTests(unittest.TestCase):
    def test_construction_and_audit_commands_carry_exactly_the_frozen_flags(self):
        for width in c.WIDTHS:
            construction = cmd.with_threads(cmd.components_v2_direct_search_command(
                Path("db"), Path("db"), Path("res"), Path("tmp"), width=width, mmseqs_bin="mmseqs"), 4)
            audit = cmd.with_threads(cmd.audit_search_command(
                Path("q"), Path("t"), Path("res"), Path("tmp"), width=width, mmseqs_bin="mmseqs"), 4)
            self.assertEqual(list(construction.argv[1:6]), ["search", "db", "db", "res", "tmp"])  # same database
            self.assertEqual(list(construction.argv[6:]), EXPECTED_FLAGS[width])
            self.assertEqual(list(audit.argv[6:]), EXPECTED_FLAGS[width])
            self.assertNotIn("--single-step-clustering", construction.argv)

    def test_no_scientific_override_is_reachable(self):
        for fn in (cmd.components_v2_direct_search_command, cmd.audit_search_command):
            params = set(inspect.signature(fn).parameters)
            self.assertFalse(params & {"identity", "coverage", "min_seq_id", "max_seqs", "sensitivity", "strand", "evalue"})
        contract_fields = set(c.PRODUCTION.to_dict())
        self.assertFalse(contract_fields & {"min_seq_id", "coverage", "max_seqs", "sensitivity", "strand", "evalue", "mask"})
        self.assertEqual(c.PRODUCTION.mmseqs_threads, 4)

    def test_engine_builds_only_frozen_command_builders(self):
        source = inspect.getsource(engine)
        for forbidden in ("--min-seq-id", "-c ", "--max-seqs", "--strand", "-s 7.5", "with_split_memory_limit", "cluster_command"):
            self.assertNotIn(forbidden, source)


class NoOutOfScopeStageTests(unittest.TestCase):
    def test_entrypoint_imports_no_network_model_or_coordinate_stage(self):
        code = ("import sys, rbpbench.splits.r3r5.darwin as d; "
                "print('\\n'.join(sorted(m for m in sys.modules)))")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                              env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"})
        modules = set(done.stdout.split())
        for forbidden in ("urllib.request", "http.client", "requests", "ftplib", "smtplib", "torch", "sklearn", "numpy",
                          "rbpbench.coordinates.download", "rbpbench.coordinates.runner", "rbpbench.coordinates.indexing",
                          "rbpbench.splits.runner", "rbpbench.splits.runner_002c", "rbpbench.splits.legacy_diagnostic"):
            self.assertNotIn(forbidden, modules)

    def test_bundle_closure_is_computed_and_guarded(self):
        from rbpbench.splits.r3r5 import bundle
        closure = bundle.source_closure(REPO / "src")
        self.assertIn("rbpbench/splits/r3r5/darwin.py", closure)
        self.assertIn("rbpbench/splits/r3r5/engine.py", closure)
        self.assertFalse([p for p in closure if "runner" in p or "download" in p or "legacy_diagnostic" in p])

    def test_launcher_imports_from_a_built_bundle_source_tree(self):
        from tests import r3r5_support as S
        with tempfile.TemporaryDirectory() as tmp:
            harness = S.Harness(Path(tmp))
            code = "import rbpbench.splits.r3r5.darwin as d, rbpbench.splits.r3r5.engine as e; print(d.__file__)"
            done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                  env={"PYTHONPATH": str(harness.bundle / "src"), "PATH": "/usr/bin:/bin",
                                       "PYTHONDONTWRITEBYTECODE": "1"}, cwd=tmp)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue(done.stdout.strip().startswith(str(harness.bundle / "src")))
            check = subprocess.run([sys.executable, "-m", "rbpbench.splits.r3r5.darwin", "resume-check",
                                    "--bundle-root", str(harness.bundle)], capture_output=True, text=True,
                                   env={"PYTHONPATH": str(harness.bundle / "src"), "PATH": "/usr/bin:/bin",
                                        "PYTHONDONTWRITEBYTECODE": "1"}, cwd=tmp)
            self.assertEqual(check.returncode, 3)
            self.assertIn("no prior attempt", check.stdout)

    def test_stage_names_are_closed(self):
        source = inspect.getsource(engine.run_workflow)
        for word in ("baseline", "model", "train_model", "coordinate", "network"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
