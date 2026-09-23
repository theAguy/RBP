"""B1 readiness-layer regression coverage for the runner: single-build
enforcement, executed-record protection, fail-closed disk budgeting,
execution-source verification before the CSV is opened, the new build-scoped
``index`` stage, and cleanup wiring. All fixtures are tiny and synthetic;
real-binary sections skip cleanly when bwa/minimap2 are not on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.runner import main
from rbpbench.data.audit import sha256_file
from test_coordinates_runner import (
    FIXTURE_CONFIG,
    FIXTURE_CSV,
    _FAKE_BWA,
    _FAKE_MINIMAP2,
    _FAKE_SEQKIT,
    _approved_host_context,
    _write_fake_executable,
    _write_reference_manifest,
)

_HAVE_REAL_TOOLS = shutil.which("bwa") and shutil.which("minimap2") and shutil.which("seqkit")


def _write_execution_sources_spec(path: Path, *, hashes: dict[str, str]) -> Path:
    md5_a, md5_b, md5_c, md5_d = "a" * 32, "b" * 32, "c" * 32, "d" * 32
    path.write_text(
        f"""
git_base_commit = "deadbeef"

[local_inputs.dataset_csv]
path = "dataset.csv"
sha256 = "{hashes['dataset_csv']}"

[local_inputs.dataset_audit]
path = "audit.json"
sha256 = "{hashes['dataset_audit']}"

[local_inputs.proteins_config]
path = "proteins.tsv"
sha256 = "{hashes['proteins_config']}"

[local_inputs.study_config]
path = "study.toml"
sha256 = "{hashes['study_config']}"

[reference_sources.hg38]
assembly = "TestAssembly38"
refseq_assembly_accession = "GCF_TEST38"
fasta_url = "https://example.invalid/hg38.fna.gz"
fasta_compressed_byte_size = 1
fasta_upstream_md5 = "{md5_a}"
assembly_report_url = "https://example.invalid/hg38_report.txt"
assembly_report_md5 = "{md5_b}"
md5checksums_url = "https://example.invalid/hg38_md5.txt"

[reference_sources.hg19]
assembly = "TestAssembly37"
refseq_assembly_accession = "GCF_TEST37"
fasta_url = "https://example.invalid/hg19.fna.gz"
fasta_compressed_byte_size = 1
fasta_upstream_md5 = "{md5_c}"
assembly_report_url = "https://example.invalid/hg19_report.txt"
assembly_report_md5 = "{md5_d}"
md5checksums_url = "https://example.invalid/hg19_md5.txt"

[derived_reference_policy]
include_sequence_roles_primary_assembly = ["assembled-molecule"]
include_non_nuclear_assembled_molecule = true
accession_preference = ["refseq", "genbank"]
"""
    )
    return path


class SingleBuildEnforcementTests(unittest.TestCase):
    def test_allow_mapping_with_zero_explicit_builds_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--output-dir", str(Path(tmp)),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--stage", "sample",
                    ]
                )
            self.assertIn("exactly one explicit --build", str(ctx.exception))

    def test_allow_mapping_with_two_explicit_builds_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--output-dir", str(Path(tmp)),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                        "--build", "hg19",
                        "--stage", "sample",
                    ]
                )
            self.assertIn("exactly one explicit --build", str(ctx.exception))

    def test_plain_dry_run_with_default_two_builds_is_unaffected(self):
        # The single-build rule only binds --allow-mapping; the ordinary
        # documented dry-run workflow over both default builds must be
        # unaffected.
        with tempfile.TemporaryDirectory() as tmp:
            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--output-dir", str(Path(tmp)),
                    "--stage", "all",
                    "--dry-run",
                ]
            )  # must not raise


class ExecutedRecordProtectionTests(unittest.TestCase):
    """A plainly unauthorized retry (missing --allow-mapping, or --dry-run)
    must never overwrite a prior executed:true align/exact_match record —
    B1 required item 7 / second-review R4.
    """

    def test_forgetting_allow_mapping_does_not_erase_prior_executed_align(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--allow-mapping", "--stage", "sample"])
                main([*common, "--allow-mapping", "--stage", "decode"])
                main([*common, "--allow-mapping", "--stage", "controls"])
                main([*common, "--allow-mapping", "--stage", "align"])
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertTrue(align_record["executed"])

                # Forgot --allow-mapping this time: must refuse to overwrite,
                # never silently record "not executed" over real evidence.
                with self.assertRaises(SystemExit) as ctx:
                    main([*common, "--force", "--stage", "align"])
                self.assertIn("refusing to overwrite", str(ctx.exception))

            # The original executed:true record survives untouched.
            align_record_after = json.loads((output_dir / "hg38" / "align.json").read_text())
            self.assertTrue(align_record_after["executed"])

    def test_dry_run_retry_does_not_erase_prior_executed_align(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                self.assertTrue(json.loads((output_dir / "hg38" / "align.json").read_text())["executed"])

                with self.assertRaises(SystemExit) as ctx:
                    main([*common, "--force", "--dry-run", "--stage", "align"])
                self.assertIn("refusing to overwrite", str(ctx.exception))
            self.assertTrue(json.loads((output_dir / "hg38" / "align.json").read_text())["executed"])


class ReportStageFailedReconciliationExitTests(unittest.TestCase):
    """A failed per-build reconciliation must make the ``report`` stage exit
    nonzero directly, not merely be discoverable later in combined_report
    (B1 required item 9 / second-review R10).
    """

    def test_report_stage_exits_nonzero_on_reconciliation_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                main([*common, "--stage", "exact_match"])

                # Corrupt the persisted sample state so `report`'s count
                # reconciliation fails deterministically.
                sample_state_path = output_dir / "sample_state.json"
                sample_state = json.loads(sample_state_path.read_text())
                sample_state["assignments"] = sample_state["assignments"][:-1]  # drop one row
                sample_state_path.write_text(json.dumps(sample_state))

                with self.assertRaises(SystemExit) as ctx:
                    main([*common, "--force", "--stage", "report"])
                self.assertIn("reconciliation failed", str(ctx.exception))


class ExecutionSourceVerificationWiringTests(unittest.TestCase):
    """Opt-in --execution-sources wiring (B1 required item 1): compared
    before the CSV is opened for row-by-row reading, using fixture hashes
    only — never the real dataset.
    """

    def test_matching_execution_sources_spec_allows_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            audit_path = tmp_path / "audit.json"
            proteins_path = tmp_path / "proteins.tsv"
            audit_path.write_text('{"ok": true}\n')
            proteins_path.write_text("1\tPROT1\n")

            hashes = {
                "dataset_csv": sha256_file(FIXTURE_CSV),
                "dataset_audit": sha256_file(audit_path),
                "proteins_config": sha256_file(proteins_path),
                "study_config": sha256_file(FIXTURE_CONFIG),
            }
            spec_path = _write_execution_sources_spec(tmp_path / "sources.toml", hashes=hashes)

            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--output-dir", str(output_dir),
                    "--dataset-audit", str(audit_path),
                    "--proteins-config", str(proteins_path),
                    "--execution-sources", str(spec_path),
                    "--stage", "sample",
                ]
            )  # must not raise
            self.assertTrue((output_dir / "sample_ids.tsv").exists())

    def test_mismatched_hash_stops_before_any_stage_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            audit_path = tmp_path / "audit.json"
            proteins_path = tmp_path / "proteins.tsv"
            audit_path.write_text('{"ok": true}\n')
            proteins_path.write_text("1\tPROT1\n")

            hashes = {
                "dataset_csv": "0" * 64,  # deliberately wrong
                "dataset_audit": sha256_file(audit_path),
                "proteins_config": sha256_file(proteins_path),
                "study_config": sha256_file(FIXTURE_CONFIG),
            }
            spec_path = _write_execution_sources_spec(tmp_path / "sources.toml", hashes=hashes)

            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--output-dir", str(output_dir),
                        "--dataset-audit", str(audit_path),
                        "--proteins-config", str(proteins_path),
                        "--execution-sources", str(spec_path),
                        "--stage", "sample",
                    ]
                )
            self.assertIn("execution-source verification failed", str(ctx.exception))
            self.assertFalse(output_dir.exists())


class DiskBudgetWiringTests(unittest.TestCase):
    """Fail-closed projected-peak check wired before real index/mapping
    subprocesses (B1 required item 8).
    """

    def test_disk_budget_violation_stops_align_before_any_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

            def starved_disk_usage(_path):
                class _Usage:
                    total = 200 * 1024**3
                    used = 199 * 1024**3
                    free = 1 * 1024**3  # far below the 80 GiB minimum

                return _Usage()

            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", side_effect=starved_disk_usage):
                    with self.assertRaises(SystemExit) as ctx:
                        main([*common, "--stage", "align"])
                self.assertIn("disk-budget check failed", str(ctx.exception))
            # No mapping evidence was produced.
            self.assertFalse((output_dir / "hg38" / "align_bwa_mem.sam").exists())


class CleanupCliWiringTests(unittest.TestCase):
    def test_cleanup_index_removes_directory_when_evidence_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            indices_dir = Path(tmp) / "indices"
            build_dir = output_dir / "hg38"
            index_dir = indices_dir / "hg38"
            index_dir.mkdir(parents=True)
            build_dir.mkdir(parents=True)
            (index_dir / "hg38.bwt").write_bytes(b"x")
            (index_dir / "index_manifest.json").write_text("{}")
            (build_dir / "align.json").write_text(json.dumps({"executed": True}))
            (build_dir / "exact_match.json").write_text(json.dumps({"executed": True}))
            (build_dir / "report.json").write_text(json.dumps({"reconciliation": {"status": "passed"}}))

            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--output-dir", str(output_dir),
                    "--indices-dir", str(indices_dir),
                    "--cleanup-index", "hg38",
                ]
            )
            self.assertFalse(index_dir.exists())

    def test_cleanup_index_refuses_without_passed_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            indices_dir = Path(tmp) / "indices"
            build_dir = output_dir / "hg38"
            index_dir = indices_dir / "hg38"
            index_dir.mkdir(parents=True)
            build_dir.mkdir(parents=True)
            (index_dir / "hg38.bwt").write_bytes(b"x")
            (index_dir / "index_manifest.json").write_text("{}")
            (build_dir / "align.json").write_text(json.dumps({"executed": True}))
            (build_dir / "exact_match.json").write_text(json.dumps({"executed": True}))
            (build_dir / "report.json").write_text(json.dumps({"reconciliation": {"status": "failed"}}))

            with self.assertRaises(SystemExit):
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--output-dir", str(output_dir),
                        "--indices-dir", str(indices_dir),
                        "--cleanup-index", "hg38",
                    ]
                )
            self.assertTrue(index_dir.exists())


@unittest.skipUnless(_HAVE_REAL_TOOLS, "requires real bwa/minimap2/seqkit on PATH")
class IndexStageRealBinaryEndToEndTests(unittest.TestCase):
    """The `index` stage builds real BWA/minimap2 indices on a tiny
    synthetic reference; `align` then uses the prepared BWA index prefix and
    minimap2 `.mmi` instead of the raw FASTA (B1 required item 4).
    """

    def test_index_then_align_uses_prepared_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            import random

            rng = random.Random(42)
            body = "".join(rng.choice("ACGT") for _ in range(2000))
            reference = tmp_path / "reference.fasta"
            with reference.open("w") as handle:
                handle.write(">chrTest\n")
                for i in range(0, len(body), 70):
                    handle.write(body[i : i + 70] + "\n")
            manifest = _write_reference_manifest(tmp_path / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
                "--indices-dir", str(indices_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            with _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "index"])

                index_record = json.loads((indices_dir / "hg38" / "index.json").read_text())
                self.assertTrue(index_record["executed"])
                self.assertTrue(Path(index_record["bwa_index_prefix"] + ".bwt").is_file())
                self.assertTrue(Path(index_record["minimap2_index"]).is_file())
                self.assertTrue((indices_dir / "hg38" / "index_manifest.json").is_file())

                main([*common, "--stage", "align"])
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertTrue(align_record["executed"])
                self.assertEqual(align_record["index_paths"]["bwa_index_prefix"], index_record["bwa_index_prefix"])
                self.assertEqual(align_record["index_paths"]["minimap2_index"], index_record["minimap2_index"])

    def test_corrupted_index_file_is_rejected_as_stale_foreign(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            import random

            rng = random.Random(99)
            body = "".join(rng.choice("ACGT") for _ in range(2000))
            reference = tmp_path / "reference.fasta"
            with reference.open("w") as handle:
                handle.write(">chrTest\n")
                for i in range(0, len(body), 70):
                    handle.write(body[i : i + 70] + "\n")
            manifest = _write_reference_manifest(tmp_path / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
                "--indices-dir", str(indices_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            with _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "index"])

                index_record = json.loads((indices_dir / "hg38" / "index.json").read_text())
                bwt_path = Path(index_record["bwa_index_prefix"] + ".bwt")
                original = bwt_path.read_bytes()
                bwt_path.write_bytes(original + b"\x00corruption")

                main([*common, "--stage", "align"])
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertFalse(align_record["executed"])
                self.assertIn("stale/foreign index", align_record["skip_reason"])


class StderrCaptureTests(unittest.TestCase):
    """Real mapping/exact-match invocations capture stderr separately from
    stdout and hash it — never DEVNULL (B1 required item 5 / second-review R1).
    """

    def test_align_and_exact_match_provenance_include_hashed_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                main([*common, "--stage", "exact_match"])

            align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            for tool in ("bwa_mem", "minimap2_splice"):
                tool_prov = align_record["provenance"][tool]
                self.assertIn("stderr_path", tool_prov)
                self.assertIn("stderr_sha256", tool_prov)
                self.assertTrue(Path(tool_prov["stderr_path"]).is_file())
                self.assertNotEqual(Path(tool_prov["stderr_path"]).resolve(), Path(tool_prov["output_path"]).resolve())

            exact_match_record = json.loads((output_dir / "hg38" / "exact_match.json").read_text())
            seqkit_prov = exact_match_record["provenance"]["seqkit_locate"]
            self.assertIn("stderr_path", seqkit_prov)
            self.assertIn("stderr_sha256", seqkit_prov)
            self.assertTrue(Path(seqkit_prov["stderr_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
