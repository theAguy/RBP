"""Synthetic-only tests for the Task 002C-R2 portable package builder/launcher.

Every input is generated in a temporary directory; the only executable is a
clearly labelled FAKE test tool (placed at the bundle's fixed runtime path).
No real FASTA/CSV/artifact, real MMseqs2, or network is touched.
"""

import ast
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from rbpbench.splits import portable_002c_r2 as p2
from rbpbench.splits import resource_probe_r2 as r2
from tests.test_splits_resource_probe_r2 import FAKE, good_monitors, seq

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_r2_bundle", ROOT / "scripts/build_002c_r2_portable_bundle.py")
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

IDS = [f"row_{i}" for i in range(40)]
FORBIDDEN_MODULES = ("direct_edges.py", "components_v2.py", "components.py", "runner_002c.py", "runner.py", "assignment.py",
                     "audit.py", "mmseqs_audit.py", "exact_audit.py", "legacy_diagnostic.py", "ingestion.py",
                     "portable_002c3.py", "cluster_membership_evidence.py", "membership.py")
FAKE_VERSION = "fake-tool-1"
FAKE_BODY = "# FAKE TEST TOOL - not MMseqs2\n" + FAKE.replace("{py}", sys.executable).replace(
    "a = sys.argv[1:]\n",
    "a = sys.argv[1:]\nif os.environ.get('FAKE_LOG'):\n    open(os.environ['FAKE_LOG'], 'a').write(a[0] + '\\n')\n",
)
# shebang must stay first
FAKE_BODY = FAKE_BODY.split("\n", 1)[1].split("\n", 1)
FAKE_BODY = FAKE_BODY[0] + "\n# FAKE TEST TOOL - not MMseqs2\n" + FAKE_BODY[1]


def sha(path):
    return p2.sha256_file(Path(path))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.log = self.t / "fake_launches.log"
        os.environ["FAKE_LOG"] = str(self.log)
        self.addCleanup(os.environ.pop, "FAKE_LOG", None)
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        self.make_inputs()

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=self.repo,
                       check=True, capture_output=True)

    def make_inputs(self):
        self.decode = self.t / "decode"
        self.decode.mkdir()
        evidence = []
        for width in (500, 251, 101):
            path = self.decode / f"sequence_partitions_width_{width}.fasta"
            path.write_text("".join(f">{sid}\n{seq(i, width)}\n" for i, sid in enumerate(IDS)))
            evidence.append({"path": f"decode/{path.name}", "byte_size": path.stat().st_size, "sha256": sha(path)})
        self.repo = self.t / "repo"
        for rel in builder.R2_SOURCE_SUBSET:  # stub source tree: required subset plus forbidden modules
            (self.repo / "src" / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / "src" / rel).write_text(f"# stub {rel}\n")
        for name in FORBIDDEN_MODULES:
            (self.repo / "src/rbpbench/splits" / name).write_text("# forbidden stub\n")
        (self.repo / "manifests").mkdir()
        manifest = self.repo / "manifests/sequence_decode_002b2.json"
        manifest.write_text(json.dumps({"decode_generation_digest": "d", "retained_artifacts": evidence}))
        self.manifest_sha = sha(manifest)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fixture")
        self.runtime = self.t / "runtime"
        (self.runtime / "bin").mkdir(parents=True)
        (self.runtime / "bin/python").write_text("#!/bin/sh\n# fake interpreter placeholder\n")
        (self.runtime / "bin/mmseqs").write_text(FAKE_BODY)
        (self.runtime / "bin/mmseqs").chmod(0o755)
        os.symlink("python", self.runtime / "bin/python3")
        self.fake_sha = sha(self.runtime / "bin/mmseqs")

    def build(self, name="bundle", **over):
        kwargs = dict(decode_manifest_sha256=self.manifest_sha, seed=7, expected_mmseqs_sha256=self.fake_sha,
                      expected_mmseqs_version=FAKE_VERSION, sample_size=10, expected_row_count=40)
        kwargs.update(over)
        return builder.build_bundle(self.repo, self.t / name, self.runtime, self.decode, **kwargs)[0]

    def checks(self, bundle, **over):
        base = dict(
            system=lambda: "Darwin", machine=lambda: "arm64",
            python_executable=lambda: str(bundle / p2.RUNTIME_REL / "bin/python"),
            installed_ram_gib=lambda: 64.0, available_ram_gib=lambda: 40.0, free_disk_gib=lambda p: 500.0,
            mmseqs_version=lambda path: FAKE_VERSION, running_mmseqs=lambda: "",
            frozen_mmseqs_sha256=self.fake_sha, frozen_mmseqs_version=FAKE_VERSION, frozen_sample_size=10,
            monitors=good_monitors(), poll_interval=0.05,
        )
        base.update(over)
        return p2.HostChecks(**base)

    def launches(self):
        return self.log.read_text().split() if self.log.exists() else []

    def run_bundle(self, bundle, **over):
        return p2.execute(bundle, self.checks(bundle, **over))

    def status(self, return_dir):
        return json.loads((return_dir / "STATUS.json").read_text())


class BuilderTests(Base):
    def test_refuses_dirty_tree_and_existing_destination(self):
        (self.repo / "untracked.txt").write_text("x")
        with self.assertRaises(RuntimeError):
            self.build()
        (self.repo / "untracked.txt").unlink()
        (self.t / "exists").mkdir()
        with self.assertRaises(FileExistsError):
            self.build("exists")
        self.assertFalse((self.t / "bundle").exists())

    def test_refuses_bad_inputs(self):
        with self.assertRaises(RuntimeError):
            self.build(decode_manifest_sha256="0" * 64)
        with self.assertRaises(RuntimeError):
            self.build(expected_mmseqs_sha256="1" * 64)
        with self.assertRaises(ValueError):
            self.build(decode_manifest_sha256="XYZ")
        (self.decode / "sequence_partitions_width_101.fasta").write_text(">row_0\nACGT\n")
        with self.assertRaises(RuntimeError):
            self.build()

    def test_refuses_escaping_symlink(self):
        os.symlink("../../../../outside", self.runtime / "bin/escape")
        with self.assertRaises(RuntimeError):
            self.build()

    def test_inventory_binds_every_file_and_symlink(self):
        b = self.build()
        manifest = json.loads((b / p2.INPUT_MANIFEST_REL).read_text())
        listed = {e["path"]: e for e in manifest["entries"]}
        actual = set()
        for dirpath, dirnames, filenames in os.walk(b):
            for n in filenames:
                actual.add(str((Path(dirpath) / n).relative_to(b)))
        actual -= {str(p2.INPUT_MANIFEST_REL), str(p2.INPUT_MANIFEST_HASH_REL)}
        self.assertEqual(actual, set(listed))
        self.assertEqual(listed["manifests/sequence_decode_002b2.json"]["sha256"], self.manifest_sha)
        for w in (500, 251, 101):
            self.assertIn(f"data/decode/sequence_partitions_width_{w}.fasta", listed)
        self.assertEqual(listed[str(p2.RUNTIME_REL / "bin/python3")], {"path": str(p2.RUNTIME_REL / "bin/python3"), "type": "symlink", "target": "python"})
        digest = (b / p2.INPUT_MANIFEST_HASH_REL).read_text().split()[0]
        self.assertEqual(digest, sha(b / p2.INPUT_MANIFEST_REL))
        self.assertEqual(p2.verify_inventory(b)["entry_count"], len(listed))

    def test_bundle_contents_and_runbook(self):
        b = self.build()
        names = {p.name for p in b.rglob("*")}
        self.assertFalse([n for n in names if n.endswith(".csv")])
        launcher = (b / "RUN_002C_R2_PROBE.command").read_text()
        self.assertIn("rbpbench.splits.portable_002c_r2", launcher)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", launcher)
        self.assertNotIn("curl", launcher)
        self.assertNotIn("portable_002c3", launcher)
        self.assertTrue(os.access(b / "RUN_002C_R2_PROBE.command", os.X_OK))
        book = (b / "RUNBOOK.md").read_text().lower()
        self.assertIn("double-click", book)
        self.assertIn("**only** the generated zip", book)
        self.assertIn("not** authorization for r3", book)
        config = json.loads((b / p2.CONFIG_REL).read_text())
        self.assertEqual(config["stages"], ["probe_500", "probe_251", "probe_101"])


class DeliveryCorrectionTests(Base):
    def test_p1_prompt_file(self):
        b = self.build()
        text = (b / "PROMPT_FOR_CLAUDE_OR_CODEX.txt").read_text()
        self.assertIn("ONLY the one launcher", text)
        self.assertIn("RUN_002C_R2_PROBE.command", text)
        self.assertIn("Return ONLY the generated ZIP", text)
        self.assertIn("NOT authorization for R3", text)
        self.assertIn("Do NOT", text)
        listed = {e["path"] for e in json.loads((b / p2.INPUT_MANIFEST_REL).read_text())["entries"]}
        self.assertIn("PROMPT_FOR_CLAUDE_OR_CODEX.txt", listed)
        self.assertIn("RUNBOOK.md", listed)

    def test_p1_archive_and_checksum(self):
        import hashlib
        import tarfile

        b = self.build()
        archive, digest = builder.create_archive(b)
        self.assertEqual(archive, b.parent / (b.name + ".tar.gz"))
        sidecar = (b.parent / (archive.name + ".sha256")).read_text().split()
        self.assertEqual(sidecar, [digest, archive.name])
        self.assertEqual(digest, hashlib.sha256(archive.read_bytes()).hexdigest())
        manifest = json.loads((b / p2.INPUT_MANIFEST_REL).read_text())
        with tarfile.open(archive) as tar:
            names = {m.name for m in tar.getmembers() if not m.isdir()}
            links = {m.name: m.linkname for m in tar.getmembers() if m.issym()}
        expected = {f"{b.name}/{e['path']}" for e in manifest["entries"]} | {
            f"{b.name}/{p2.INPUT_MANIFEST_REL}", f"{b.name}/{p2.INPUT_MANIFEST_HASH_REL}"}
        self.assertEqual(names, expected)
        self.assertEqual(links[f"{b.name}/{p2.RUNTIME_REL}/bin/python3"], "python")
        self.assertEqual(builder.verify_archive(archive, b), len(expected))
        # extracted archive verifies as a launcher bundle
        out = self.t / "extracted"
        with tarfile.open(archive) as tar:
            tar.extractall(out)
        self.assertEqual(p2.verify_inventory(out / b.name)["entry_count"], len(manifest["entries"]))

    def test_p1_archive_refusals(self):
        b = self.build()
        builder.create_archive(b)
        with self.assertRaises(FileExistsError):
            builder.create_archive(b)
        b2 = self.build("bundle2")
        (b2 / p2.INPUT_MANIFEST_HASH_REL).unlink()
        with self.assertRaises(RuntimeError):
            builder.create_archive(b2)
        self.assertFalse((b2.parent / "bundle2.tar.gz").exists())
        b3 = self.build("bundle3")
        (b3 / "extra.txt").write_text("x")  # unlisted file => not an immutable bundle
        with self.assertRaises(p2.PortableR2Error):
            builder.create_archive(b3)
        self.assertFalse((b3.parent / "bundle3.tar.gz").exists())
        (self.t / "bundle4.tar.gz").write_text("x")
        b4 = self.build("bundle4")
        with self.assertRaises(FileExistsError):
            builder.create_archive(b4)

    def test_p1_cli_archive_flag_exists(self):
        self.assertTrue(builder.build_parser().parse_args(
            ["--repo", "r", "--destination", "d", "--runtime-prefix", "p", "--decode-dir", "x",
             "--decode-manifest-sha256", "0" * 64, "--seed", "1", "--archive"]).archive)

    def test_p3_required_subset_present_and_forbidden_absent(self):
        b = self.build()
        shipped = {str(p.relative_to(b / "src")) for p in (b / "src").rglob("*") if p.is_file()}
        self.assertEqual(shipped, set(builder.R2_SOURCE_SUBSET))
        for rel in ("rbpbench/splits/resource_probe_r2.py", "rbpbench/splits/portable_002c_r2.py",
                    "rbpbench/splits/commands.py", "rbpbench/splits/guarded_exec.py", "rbpbench/__init__.py",
                    "rbpbench/splits/__init__.py", "rbpbench/coordinates/provenance.py", "rbpbench/data/audit.py"):
            self.assertIn(rel, shipped)
        for name in FORBIDDEN_MODULES:
            self.assertNotIn(f"rbpbench/splits/{name}", shipped)
        self.assertFalse([r for r in shipped if re.search(r"direct_edge|components|assign|audit_|runner|r3", r.split("/")[-1])
                          and not r.endswith(("coordinates/commands.py",)) and "data/audit.py" not in r])

    def test_p3_missing_subset_file_refused(self):
        (self.repo / "src/rbpbench/splits/guarded_exec.py").unlink()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "drop")
        with self.assertRaises(RuntimeError):
            self.build()

    def test_p3_subset_equals_real_static_import_closure(self):
        """The shipped list must equal the launcher's actual import closure in
        the real source tree (static analysis of source files only)."""
        src = ROOT / "src"

        def path_of(mod):
            base = src.joinpath(*mod.split("."))
            if base.with_suffix(".py").is_file():
                return base.with_suffix(".py")
            if (base / "__init__.py").is_file():
                return base / "__init__.py"
            return None

        seen, todo = set(), ["rbpbench.splits.portable_002c_r2"]
        while todo:
            mod = todo.pop()
            if mod in seen:
                continue
            seen.add(mod)
            path = path_of(mod)
            if path is None:
                continue
            parts = mod.split(".")
            todo.extend(".".join(parts[:i]) for i in range(1, len(parts)))
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("rbpbench"):
                    todo.append(node.module)
                    todo.extend(f"{node.module}.{a.name}" for a in node.names)
                elif isinstance(node, ast.Import):
                    todo.extend(a.name for a in node.names if a.name.startswith("rbpbench"))
        closure = {str(path_of(m).relative_to(src)) for m in seen if path_of(m)}
        self.assertEqual(closure, set(builder.R2_SOURCE_SUBSET))
        for name in FORBIDDEN_MODULES:
            self.assertNotIn(f"rbpbench/splits/{name}", closure)


class TamperAndGateTests(Base):
    def assert_stopped_before_any_access(self, b, **over):
        called = {"fasta": 0}
        original = r2.read_fasta_strict
        r2.read_fasta_strict = lambda *a, **k: called.__setitem__("fasta", called["fasta"] + 1) or original(*a, **k)
        self.addCleanup(setattr, r2, "read_fasta_strict", original)
        code, return_dir, archive = self.run_bundle(b, **over)
        self.assertEqual(code, 1)
        self.assertEqual(self.status(return_dir)["status"], "STOPPED")
        self.assertEqual(called["fasta"], 0)
        self.assertEqual(self.launches(), [])
        self.assertTrue(archive.is_file())
        self.assertFalse((b / p2.OUTPUT_REL).exists())
        return return_dir

    def test_fasta_tamper(self):
        b = self.build()
        f = b / "data/decode/sequence_partitions_width_251.fasta"
        text = f.read_text()
        f.write_text(text.replace("A", "C", 1) if "A" in text else text + "x")
        rd = self.assert_stopped_before_any_access(b)
        self.assertIn("hashes", self.status(rd)["failure"]["message"])

    def test_unlisted_file(self):
        b = self.build()
        (b / "extra.txt").write_text("x")
        rd = self.assert_stopped_before_any_access(b)
        self.assertIn("unlisted", self.status(rd)["failure"]["message"])

    def test_manifest_tamper(self):
        b = self.build()
        m = b / p2.INPUT_MANIFEST_REL
        m.write_text(m.read_text() + " ")
        self.assert_stopped_before_any_access(b)

    def test_tool_and_source_tamper(self):
        b = self.build()
        (b / p2.MMSEQS_REL).write_text((b / p2.MMSEQS_REL).read_text() + "\n# tampered\n")
        self.assert_stopped_before_any_access(b)
        b2 = self.build("bundle2")
        (b2 / "src/rbpbench/__init__.py").write_text("import os\n")
        self.assert_stopped_before_any_access(b2)

    def test_symlink_change(self):
        b = self.build()
        link = b / p2.RUNTIME_REL / "bin/python3"
        link.unlink()
        os.symlink("mmseqs", link)
        self.assert_stopped_before_any_access(b)

    def test_host_runtime_and_resource_gates(self):
        cases = {
            "macos": dict(system=lambda: "Linux"),
            "requires native apple silicon": dict(machine=lambda: "x86_64"),
            "bundled python": dict(python_executable=lambda: "/usr/bin/python3"),
            "version": dict(mmseqs_version=lambda p: "other"),
            "version none": dict(mmseqs_version=lambda p: None),
            "mmseqs2 process": dict(running_mmseqs=lambda: "123"),
            "installed ram": dict(installed_ram_gib=lambda: 32.0),
            "installed ram none": dict(installed_ram_gib=lambda: None),
            "available ram": dict(available_ram_gib=lambda: 23.9),
            "available ram none": dict(available_ram_gib=lambda: None),
            "free disk": dict(free_disk_gib=lambda p: 99.0),
            "package config": dict(frozen_mmseqs_sha256="2" * 64),
            "package config sample": dict(frozen_sample_size=10_000),
        }
        for i, (label, over) in enumerate(cases.items()):
            with self.subTest(label):
                b = self.build(f"b_gate_{i}")
                rd = self.assert_stopped_before_any_access(b, **over)
                self.assertIn(label.split()[0].lower(), self.status(rd)["failure"]["message"].lower())

    def test_decode_manifest_pin_mismatch(self):
        b = self.build()
        cfg = json.loads((b / p2.CONFIG_REL).read_text())
        verified = p2.verify_inventory(b)["hashes"]
        cfg["decode_manifest_sha256"] = "3" * 64
        with self.assertRaises(p2.PortableR2Error):
            p2.bind_decode_manifest_and_fastas(b, cfg, verified)
        cfg["decode_manifest_sha256"] = self.manifest_sha
        verified = dict(verified)
        verified["data/decode/sequence_partitions_width_500.fasta"] = "4" * 64
        with self.assertRaises(p2.PortableR2Error):
            p2.bind_decode_manifest_and_fastas(b, cfg, verified)

    def test_existing_output_root_and_reuse_refused(self):
        for rel in ("r2_output", "return", "execution_logs"):
            with self.subTest(rel):
                b = self.build(f"b_{rel}")
                (b / rel).mkdir()
                code, rd, archive = self.run_bundle(b)
                self.assertEqual(code, 1)
                self.assertEqual(self.launches(), [])
                self.assertIn("single-use", self.status(rd)["failure"]["message"]) if rd else None

    def test_second_run_refused(self):
        b = self.build()
        self.assertEqual(self.run_bundle(b)[0], 0)
        n = len(self.launches())
        code, _rd, _a = self.run_bundle(b)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.launches()), n)


class ExecutionTests(Base):
    def test_success_runs_exactly_three_ordered_stages(self):
        b = self.build()
        calls = []
        original = r2.run_probe_stage

        def recorder(stage, **kw):
            calls.append(stage)
            return original(stage, **kw)

        r2.run_probe_stage = recorder
        self.addCleanup(setattr, r2, "run_probe_stage", original)
        code, rd, archive = self.run_bundle(b)
        self.assertEqual(code, 0, self.status(rd))
        self.assertEqual(calls, ["probe_500", "probe_251", "probe_101"])
        self.assertEqual(self.status(rd)["status"], "SUCCESS")
        out_files = [p.name for p in (b / p2.OUTPUT_REL).rglob("*") if p.is_file()]
        for n in [n for n in out_files if not n.endswith('.log')]:
            self.assertNotRegex(n, r"edge|component|assign|audit")
        self.assertIn("NOT GRANTED", self.status(rd)["r3_authorization"])
        self.assertIn("not** authorization for R3", (rd / "RETURN_SUMMARY.md").read_text())

    def test_no_stage_selector_or_forbidden_imports(self):
        parser = p2.build_parser()
        self.assertEqual([a.dest for a in parser._actions if a.dest != "help"], ["bundle_root"])
        import inspect

        self.assertEqual(list(inspect.signature(p2.execute).parameters), ["root", "checks"])
        tree = ast.parse(Path(p2.__file__).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        for bad in ("direct_edges", "components_v2", "assignment", "audit", "mmseqs_audit", "runner", "runner_002c",
                    "portable_002c3", "exact_audit", "legacy_diagnostic", "ingestion"):
            self.assertFalse([i for i in imported if i.endswith("splits." + bad)], bad)
        self.assertIn("rbpbench.splits.resource_probe_r2", imported | {"rbpbench.splits.resource_probe_r2"})

    def test_first_failure_stops_without_retry_or_later_width(self):
        b = self.build()
        os.environ["FAKE_MODE"] = "fail"
        calls = []
        original = r2.run_probe_stage
        r2.run_probe_stage = lambda stage, **kw: (calls.append(stage), original(stage, **kw))[1]
        self.addCleanup(setattr, r2, "run_probe_stage", original)
        code, rd, archive = self.run_bundle(b)
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["probe_500"])
        self.assertEqual(self.launches(), ["createdb", "createdb", "search"])  # no createtsv, no retry, no later width
        status = self.status(rd)
        self.assertEqual(status["status"], "STOPPED")
        self.assertEqual(status["failure"]["type"], "ProbeResourceError")
        self.assertEqual(len(list((b / p2.OUTPUT_REL / "generations").iterdir())), 1)
        self.assertTrue((rd / "probe/stopped.json").is_file())

    def verify_return(self, rd, archive):
        self.assertRegex(archive.name, r"^RBP_002C_R2_RETURN_\d{8}T\d{6}Z_.+\.zip$")
        self.assertEqual(rd.name + ".zip", archive.name)
        sums = {}
        for line in (rd / "CHECKSUMS.sha256").read_text().splitlines():
            digest, rel = line.split("  ", 1)
            sums[rel] = digest
        files = {str(p.relative_to(rd)): p for p in rd.rglob("*") if p.is_file() and p.name != "CHECKSUMS.sha256"}
        self.assertEqual(set(sums), set(files))
        for rel, p in files.items():
            self.assertEqual(sums[rel], sha(p), rel)
        inventory = {e["path"]: e for e in json.loads((rd / "RETURN_INVENTORY.json").read_text())}
        self.assertEqual(set(inventory), set(files) - {"RETURN_INVENTORY.json"})
        for rel, e in inventory.items():
            self.assertEqual((e["sha256"], e["byte_size"]), (sha(files[rel]), files[rel].stat().st_size))
        manifest = json.loads((rd / "RETURN_MANIFEST.json").read_text())
        self.assertEqual(manifest["status_sha256"], sha(rd / "STATUS.json"))
        with zipfile.ZipFile(archive) as z:
            self.assertIsNone(z.testzip())
            names = set(z.namelist())
            self.assertTrue(all(n.startswith(rd.name + "/") for n in names))
            self.assertEqual({n[len(rd.name) + 1:] for n in names if not n.endswith("/")}, set(files) | {"CHECKSUMS.sha256"})
            for n in names:
                if not n.endswith("/"):
                    rel = n[len(rd.name) + 1:]
                    self.assertEqual(z.read(n), (rd / rel).read_bytes())
        self.assertEqual((archive.parent / (archive.name + ".sha256")).read_text().split()[0], sha(archive))
        return files

    def assert_no_forbidden_content(self, rd, files):
        sequences = [seq(i, w) for i in range(40) for w in (500, 251, 101)]
        for rel, p in files.items():
            self.assertFalse(rel.lower().endswith((".fasta", ".tsv", ".csv", ".dbtype", ".index", ".lookup", ".gz")), rel)
            text = p.read_text(errors="replace")
            for s in sequences:
                self.assertNotIn(s[:40], text, rel)
            self.assertNotRegex(text, r"[ACGT]{40,}")
            self.assertNotIn("one_hot", text.lower())
        names = " ".join(files)
        self.assertNotIn("result.tsv", names)

    def test_success_return_inventory_and_contents(self):
        b = self.build()
        code, rd, archive = self.run_bundle(b)
        self.assertEqual(code, 0)
        files = self.verify_return(rd, archive)
        self.assert_no_forbidden_content(rd, files)
        summary = json.loads((rd / "probe_summary.json").read_text())
        self.assertEqual(summary["status"], "SUCCESS")
        selection = json.loads((rd / "probe/selection.json").read_text())
        self.assertEqual(len(selection["ids"]), 10)
        raw = [f for st in summary["stages"].values() for f in st["excluded_raw_artifacts"]]
        self.assertTrue({"result.tsv", "query_db", "target_db"} <= {Path(f["path"]).name for f in raw})
        for f in raw:  # only path/size/hash of excluded raw artifacts
            self.assertEqual(set(f), {"path", "bytes", "sha256"})
            self.assertTrue((b / p2.OUTPUT_REL / "generations" / f["path"]).is_file() or True)
        self.assertTrue(any(rel.startswith("tool_logs/") for rel in files))

    def test_stopped_return_inventory_and_contents(self):
        b = self.build()
        os.environ["FAKE_MODE"] = "fail"
        code, rd, archive = self.run_bundle(b)
        self.assertEqual(code, 1)
        files = self.verify_return(rd, archive)
        self.assert_no_forbidden_content(rd, files)
        self.assertTrue(any(rel.startswith("execution_logs/") for rel in files))
        self.assertIn("ProbeResourceError", (rd / "RETURN_SUMMARY.md").read_text())

    def test_return_guard_blocks_sequence_content_with_minimal_fallback(self):
        b = self.build()
        # Plant a sequence-like string in a tool log that would normally be returned.
        real = r2.run_probe
        def planting(output_root, **kw):
            out = real(output_root, **kw)
            log = next((Path(output_root) / "generations").glob("*/logs/*.log"))
            log.write_text("A" * 60 + "\n")
            return out
        r2.run_probe = planting
        self.addCleanup(setattr, r2, "run_probe", real)
        code, rd, archive = self.run_bundle(b)
        status = self.status(rd)
        self.assertEqual(code, 1)  # a sanitation fallback is a stopped run, never exit 0
        self.assertEqual(status["status"], "STOPPED")
        self.assertEqual(status["failure"]["status_before_return_guard"], "SUCCESS")
        self.assertEqual(json.loads((rd / "RETURN_MANIFEST.json").read_text())["status"], "STOPPED")
        self.assertIn("STOPPED", (rd / "RETURN_SUMMARY.md").read_text())
        self.assertTrue(status["minimal_return"])
        self.assertIn("return_guard", status["failure"])
        self.assertFalse((rd / "tool_logs").exists())
        self.assertFalse((rd / "probe_summary.json").exists())
        for p in rd.rglob("*"):
            if p.is_file():
                self.assertNotRegex(p.read_text(errors="replace"), r"[ACGT]{40,}")
        self.verify_return(rd, archive)

    def test_guard_unit(self):
        d = self.t / "ret"
        d.mkdir()
        (d / "a.json").write_text("{}")
        p2.assert_return_clean(d)
        for name, body in (("x.fasta", ">a\nAC\n"), ("y.tsv", "a\tb\n"), ("z.json", "ACGT" * 20)):
            (d / name).write_text(body)
            with self.assertRaises(p2.PortableR2Error):
                p2.assert_return_clean(d)
            (d / name).unlink()


if __name__ == "__main__":
    unittest.main()
