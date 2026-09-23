"""Regression coverage for the Task 001B checkpoint B1 correction round.

Every test here targets exactly one item from
``docs/reviews/001b_b1_planning_review.md`` (B1-R1 through B1-R9, plus the
additional index-provenance-version and cumulative-provenance corrections)
and demonstrably fails against commit ``dda805f`` (the reviewed, pre-
correction implementation). Fixtures are tiny and synthetic throughout; the
real CSV is never opened and no NCBI URL is ever requested (B1's
authorization boundary), consistent with the rest of the coordinate-runner
test suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.cleanup import CleanupRefused, execute_index_cleanup
from rbpbench.coordinates.config import load_config
from rbpbench.coordinates.derive_reference import derive_reference_fasta
from rbpbench.coordinates.diskbudget import (
    DiskBudgetExceeded,
    check_pinned_volumes,
    load_ledger,
    start_ledger,
)
from rbpbench.coordinates.indexing import (
    build_index_manifest,
    check_minimap2_mapping_stderr,
    verify_index_binding,
    verify_index_files_against_manifest,
)
from rbpbench.coordinates.manifest import manifest_content_sha256
from rbpbench.coordinates.runner import (
    _run_tool_to_file,
    main,
    stage_align,
    stage_download,
    stage_exact_match,
    stage_report,
)
from rbpbench.coordinates.sampling import SamplingResult
from rbpbench.data.audit import sha256_file

from test_coordinates_runner import (
    FIXTURE_CONFIG,
    FIXTURE_CSV,
    FIXTURE_EXECUTION_SOURCES,
    _FAKE_BWA,
    _FAKE_MINIMAP2,
    _FAKE_SEQKIT,
    _approved_host_context,
    _write_fake_executable,
    _write_reference_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return load_config(FIXTURE_CONFIG)


def _empty_sample() -> SamplingResult:
    return SamplingResult(
        assignments=(), representative_ids=frozenset(), quota_ids=frozenset(), filler_ids=frozenset(), unsatisfied_quotas=()
    )


def _reference_and_manifest(tmp_path: Path, *, build: str, content: str) -> tuple[Path, dict]:
    reference = tmp_path / f"{build}_reference.fasta"
    reference.write_text(content)
    manifest_path = _write_reference_manifest(tmp_path / f"{build}_manifest.json", build=build, reference=reference)
    return reference, json.loads(manifest_path.read_text())


class R1ReferenceBindingTests(unittest.TestCase):
    """B1-R1: exact_match/report must fail closed when their active
    reference/manifest does not equal the reference recorded upstream.
    """

    def test_exact_match_non_forced_mismatch_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference, manifest = _reference_and_manifest(tmp_path, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            reads = tmp_path / "reads.fasta"
            reads.write_text(">s1\nAAAA\n")
            align_record = {
                "executed": True,
                "reference_sha256": "0" * 64,
                "reference_manifest_content_sha256": "0" * 64,
            }
            record = stage_exact_match(
                _cfg(),
                build="hg38",
                build_output_dir=tmp_path / "out",
                allow_mapping=True,
                host_role="approved_mac",
                threads=1,
                reference=reference,
                reference_manifest=manifest,
                reads_fasta=reads,
                align_record=align_record,
                dry_run=False,
            )
            self.assertFalse(record["executed"])
            self.assertIn("stale/foreign reference", record["skip_reason"])

    def test_exact_match_forced_mismatch_via_cli_never_combines_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference_a, manifest_a = _reference_and_manifest(output_dir, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            reference_b = output_dir / "reference_hg38_alt.fasta"
            reference_b.write_text(">chr1\n" + "C" * 20 + "\n")
            _write_reference_manifest(output_dir / "hg38_alt_manifest.json", build="hg38", reference=reference_b)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--reference", f"hg38={reference_a}", "--reference-manifest", f"hg38={output_dir / 'hg38_manifest.json'}", "--stage", "sample"])
                main([*common, "--reference", f"hg38={reference_a}", "--reference-manifest", f"hg38={output_dir / 'hg38_manifest.json'}", "--stage", "decode"])
                main([*common, "--reference", f"hg38={reference_a}", "--reference-manifest", f"hg38={output_dir / 'hg38_manifest.json'}", "--stage", "controls"])
                main([*common, "--reference", f"hg38={reference_a}", "--reference-manifest", f"hg38={output_dir / 'hg38_manifest.json'}", "--stage", "align"])
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertTrue(align_record["executed"])

                # A forced exact_match attempt with a *different* reference
                # (its own valid manifest, but not the one align recorded)
                # must never combine BWA mapping (reference A) with SeqKit
                # exact matches (reference B) — the original second-review
                # R3 failure.
                main(
                    [
                        *common,
                        "--reference", f"hg38={reference_b}",
                        "--reference-manifest", f"hg38={output_dir / 'hg38_alt_manifest.json'}",
                        "--force",
                        "--stage", "exact_match",
                    ]
                )
            exact_match_record = json.loads((output_dir / "hg38" / "exact_match.json").read_text())
            self.assertFalse(exact_match_record["executed"])
            self.assertIn("stale/foreign reference", exact_match_record["skip_reason"])

    def test_report_refuses_when_current_reference_differs_from_exact_match_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference, manifest = _reference_and_manifest(tmp_path, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            align_record = {
                "executed": True,
                "reference_sha256": manifest["sha256"],
                "reference_manifest_content_sha256": manifest_content_sha256(manifest),
            }
            exact_match_record = {
                "executed": True,
                "reference_sha256": "0" * 64,
                "reference_manifest_content_sha256": "0" * 64,
            }
            with self.assertRaises(SystemExit) as ctx:
                stage_report(
                    _empty_sample(),
                    cfg=_cfg(),
                    build_output_dir=tmp_path / "out",
                    expected_total=0,
                    expected_representative=0,
                    expected_controls=0,
                    build="hg38",
                    align_record=align_record,
                    exact_match_record=exact_match_record,
                    reference=reference,
                    reference_manifest=manifest,
                )
            self.assertIn("exact_match", str(ctx.exception))

    def test_report_refuses_when_current_reference_differs_from_align_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference, manifest = _reference_and_manifest(tmp_path, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            align_record = {
                "executed": True,
                "reference_sha256": "0" * 64,
                "reference_manifest_content_sha256": "0" * 64,
            }
            exact_match_record = {
                "executed": True,
                "reference_sha256": manifest["sha256"],
                "reference_manifest_content_sha256": manifest_content_sha256(manifest),
            }
            with self.assertRaises(SystemExit) as ctx:
                stage_report(
                    _empty_sample(),
                    cfg=_cfg(),
                    build_output_dir=tmp_path / "out",
                    expected_total=0,
                    expected_representative=0,
                    expected_controls=0,
                    build="hg38",
                    align_record=align_record,
                    exact_match_record=exact_match_record,
                    reference=reference,
                    reference_manifest=manifest,
                )
            self.assertIn("align", str(ctx.exception))

    def test_report_requires_a_reference_manifest_when_mapping_was_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference, _manifest = _reference_and_manifest(tmp_path, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            align_record = {"executed": True, "reference_sha256": "x", "reference_manifest_content_sha256": "y"}
            exact_match_record = {"executed": True, "reference_sha256": "x", "reference_manifest_content_sha256": "y"}
            with self.assertRaises(SystemExit) as ctx:
                stage_report(
                    _empty_sample(),
                    cfg=_cfg(),
                    build_output_dir=tmp_path / "out",
                    expected_total=0,
                    expected_representative=0,
                    expected_controls=0,
                    build="hg38",
                    align_record=align_record,
                    exact_match_record=exact_match_record,
                    reference=reference,
                    reference_manifest=None,
                )
            self.assertIn("reference manifest required", str(ctx.exception))


class R2IndexBindingTests(unittest.TestCase):
    """B1-R2: index manifests must cryptographically bind the reference,
    and every actual index path must equal what the manifest itself
    recorded — checked before any subprocess runs.
    """

    def _bwa_files(self, index_dir: Path, prefix: str, *, content: bytes) -> list[dict]:
        entries = []
        for suffix in (".amb", ".ann", ".bwt", ".pac", ".sa"):
            path = index_dir / f"{prefix}{suffix}"
            path.write_bytes(content)
            entries.append({"path": str(path), "byte_size": path.stat().st_size, "sha256": sha256_file(path)})
        return entries

    def test_foreign_index_built_from_a_different_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference, manifest = _reference_and_manifest(tmp_path, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            index_dir = tmp_path / "indices" / "hg38"
            index_dir.mkdir(parents=True)
            bwa_files = self._bwa_files(index_dir, "hg38", content=b"real bwt bytes")
            index_manifest = build_index_manifest(
                build="hg38",
                bwa={"files": bwa_files},
                minimap2=None,
                # Self-consistent with its own files, but built from a
                # *different* reference than the one this run is using.
                reference_sha256="deadbeef" * 8,
                reference_manifest_content_sha256="deadbeef" * 8,
            )
            (index_dir / "index_manifest.json").write_text(json.dumps(index_manifest))

            reads = tmp_path / "reads.fasta"
            reads.write_text(">s1\nAAAA\n")
            record = stage_align(
                _cfg(),
                build="hg38",
                build_output_dir=tmp_path / "out",
                allow_mapping=True,
                host_role="approved_mac",
                threads=1,
                reference=reference,
                reference_manifest=manifest,
                reads_fasta=reads,
                dry_run=False,
                bwa_index_prefix=index_dir / "hg38",
            )
            self.assertFalse(record["executed"])
            self.assertIn("stale/foreign index", record["skip_reason"])
            self.assertTrue(any("reference_sha256" in v for v in record["index_manifest_validation"]["violations"]))

    def test_same_size_tampered_index_file_is_rejected(self):
        """A same-sized-but-different-content replacement must be caught by
        the full SHA-256 check, never merely accepted because size matches.
        """
        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp)
            original = index_dir / "hg38.bwt"
            original.write_bytes(b"original 16 byte")
            manifest = {"bwa_index": {"files": [{"path": str(original), "byte_size": original.stat().st_size, "sha256": sha256_file(original)}]}}
            # Replace with a same-length but different-content file.
            replacement = b"tamperedX16 byte"
            self.assertEqual(len(replacement), original.stat().st_size)
            original.write_bytes(replacement)
            violations = verify_index_files_against_manifest(manifest, key="bwa_index")
            self.assertTrue(violations)
            self.assertTrue(any("sha256" in v for v in violations))

    def test_split_directory_override_each_checked_against_its_own_manifest(self):
        """Each override (BWA prefix, minimap2 .mmi) must be verified
        against the index manifest in *its own* directory — a single
        inferred shared directory previously let one override's
        verification be skipped entirely.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference, manifest = _reference_and_manifest(tmp_path, build="hg38", content=">chr1\n" + "A" * 20 + "\n")

            bwa_dir = tmp_path / "bwa_indices" / "hg38"
            bwa_dir.mkdir(parents=True)
            bwa_files = self._bwa_files(bwa_dir, "hg38", content=b"real bwt bytes")
            bwa_manifest = build_index_manifest(
                build="hg38",
                bwa={"files": bwa_files},
                minimap2=None,
                reference_sha256=manifest["sha256"],
                reference_manifest_content_sha256=manifest_content_sha256(manifest),
            )
            (bwa_dir / "index_manifest.json").write_text(json.dumps(bwa_manifest))

            # A *different* directory for the minimap2 override, with no
            # index manifest of its own at all.
            mm2_dir = tmp_path / "mm2_indices" / "hg38"
            mm2_dir.mkdir(parents=True)
            (mm2_dir / "hg38.mmi").write_bytes(b"fake mmi")

            reads = tmp_path / "reads.fasta"
            reads.write_text(">s1\nAAAA\n")
            record = stage_align(
                _cfg(),
                build="hg38",
                build_output_dir=tmp_path / "out",
                allow_mapping=True,
                host_role="approved_mac",
                threads=1,
                reference=reference,
                reference_manifest=manifest,
                reads_fasta=reads,
                dry_run=False,
                bwa_index_prefix=bwa_dir / "hg38",
                minimap2_index=mm2_dir / "hg38.mmi",
            )
            self.assertFalse(record["executed"])
            self.assertTrue(any("minimap2_index" in v and "no index manifest found" in v for v in record["index_manifest_validation"]["violations"]))

    def test_verify_index_binding_checks_actual_path_matches_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp)
            mmi = index_dir / "hg38.mmi"
            mmi.write_bytes(b"real mmi bytes")
            manifest = build_index_manifest(
                build="hg38",
                bwa=None,
                minimap2={"files": [{"path": str(mmi), "byte_size": mmi.stat().st_size, "sha256": sha256_file(mmi)}]},
                reference_sha256="abc",
                reference_manifest_content_sha256="def",
            )
            # A different actual_path than what the manifest recorded.
            other_path = index_dir / "elsewhere.mmi"
            violations = verify_index_binding(
                manifest,
                key="minimap2_index",
                actual_path=other_path,
                expected_build="hg38",
                expected_reference_sha256="abc",
                expected_reference_manifest_content_sha256="def",
            )
            self.assertTrue(any("do not match index-manifest-recorded" in v for v in violations))


class R3EvidencePreservationTests(unittest.TestCase):
    """B1-R3: no non-executed outcome may overwrite prior executed
    evidence, and a partial multi-tool attempt must never touch final
    output paths.
    """

    def _authorized_common(self, output_dir: Path, reference: Path, manifest: Path) -> list:
        return [
            "--config", str(FIXTURE_CONFIG),
            "--csv", str(FIXTURE_CSV),
            "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
            "--output-dir", str(output_dir),
            "--allow-mapping",
            "--host-role", "approved_mac",
            "--reference", f"hg38={reference}",
            "--reference-manifest", f"hg38={manifest}",
            "--build", "hg38",
        ]

    def test_failed_preflight_does_not_overwrite_executed_align(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference, _ = _reference_and_manifest(output_dir, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            manifest = output_dir / "hg38_manifest.json"
            common = self._authorized_common(output_dir, reference, manifest)
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                self.assertTrue(json.loads((output_dir / "hg38" / "align.json").read_text())["executed"])

                # Force a fresh preflight failure (RAM below the configured
                # minimum) on a re-attempt of the same, otherwise-identical
                # stage.
                with _approved_host_context(ram_gib=0.5):
                    with self.assertRaises(SystemExit) as ctx:
                        main([*common, "--force", "--stage", "align"])
                    self.assertIn("refusing to overwrite", str(ctx.exception))
            self.assertTrue(json.loads((output_dir / "hg38" / "align.json").read_text())["executed"])

    def test_partial_two_tool_failure_preserves_prior_accepted_sam_files(self):
        """A failure after bwa succeeds but before minimap2 completes must
        never truncate/replace the previously-accepted final SAM files.
        """
        _fake_minimap2_that_fails = (
            "#!/bin/bash\n"
            "if [ \"$#\" -le 0 ]; then\n"
            "  echo \"2.31\"\n"
            "  exit 0\n"
            "fi\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" == \"--version\" ]; then\n"
            "    echo \"2.31\"\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "exit 7\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference, _ = _reference_and_manifest(output_dir, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            manifest = output_dir / "hg38_manifest.json"
            common = self._authorized_common(output_dir, reference, manifest)
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                original_bwa_sam = (output_dir / "hg38" / "align_bwa_mem.sam").read_bytes()
                original_mm2_sam = (output_dir / "hg38" / "align_minimap2_splice.sam").read_bytes()

                # Change the reference so align legitimately re-attempts,
                # but make minimap2 itself fail this time (bwa still
                # succeeds first).
                new_reference = output_dir / "reference_hg38_alt.fasta"
                new_reference.write_text(">chr1\n" + "C" * 20 + "\n")
                new_manifest_path = output_dir / "hg38_alt_manifest.json"
                _write_reference_manifest(new_manifest_path, build="hg38", reference=new_reference)
                _write_fake_executable(bin_dir, "minimap2", _fake_minimap2_that_fails)
                common2 = self._authorized_common(output_dir, new_reference, new_manifest_path)
                with self.assertRaises(subprocess.CalledProcessError):
                    main([*common2, "--stage", "align"])

            # The final SAM files are byte-for-byte unchanged from the prior
            # accepted attempt: no attempt-specific temp output was ever
            # promoted over them.
            self.assertEqual((output_dir / "hg38" / "align_bwa_mem.sam").read_bytes(), original_bwa_sam)
            self.assertEqual((output_dir / "hg38" / "align_minimap2_splice.sam").read_bytes(), original_mm2_sam)
            align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            self.assertTrue(align_record["executed"])  # the prior record, untouched

            # No attempt-specific temporary directory was left behind.
            leftovers = [p for p in (output_dir / "hg38").iterdir() if p.name.startswith(".attempt_")]
            self.assertEqual(leftovers, [])

    def test_rejected_attempt_is_recorded_separately_not_only_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference, _ = _reference_and_manifest(output_dir, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            manifest = output_dir / "hg38_manifest.json"
            common = self._authorized_common(output_dir, reference, manifest)
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                with self.assertRaises(SystemExit):
                    main([*common, "--force", "--dry-run", "--stage", "align"])
            rejected_path = output_dir / "hg38" / "align.json.rejected_attempts.jsonl"
            self.assertTrue(rejected_path.is_file())
            entries = [json.loads(line) for line in rejected_path.read_text().splitlines()]
            self.assertFalse(entries[-1]["executed"])
            self.assertIn("rejected_at", entries[-1])


class R4DiskBudgetTests(unittest.TestCase):
    """B1-R4: the ledger's observed_new_gib is a conservative maximum (never
    a double-counting sum), persists across separate process invocations,
    checks cross-volume placement, and mapper writers stop on live breach.
    """

    def _fake_disk_usage(self, free_gib: float, total_gib: float = 500.0):
        gib = 1024**3

        class _Usage:
            free = int(free_gib * gib)
            total = int(total_gib * gib)
            used = int((total_gib - free_gib) * gib)

        return _Usage()

    def test_sequential_snapshots_use_max_not_sum(self):
        """Reproduces the planning review's exact reported defect: after
        cumulative snapshots of 5 GiB and 6 GiB since baseline,
        observed_new_gib must report 6 GiB (the actual current increase),
        never 11 GiB.
        """
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=self._fake_disk_usage(200.0)):
                ledger = start_ledger(Path(tmp))
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=self._fake_disk_usage(195.0)):
                ledger.record_step("step_one", path=Path(tmp))
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=self._fake_disk_usage(194.0)):
                ledger.record_step("step_two", path=Path(tmp))
            self.assertAlmostEqual(ledger.observed_new_gib, 6.0, places=6)

    def test_ledger_persists_across_separate_process_invocations(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_path = tmp_path / "ledger.json"
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=self._fake_disk_usage(200.0)):
                first = start_ledger(tmp_path, state_path=state_path)
                first.record_step("checkpoint_a", path=tmp_path)
            self.assertTrue(state_path.is_file())

            # A brand-new ledger object in a "new process" (no shared Python
            # state) must resume the *same* baseline/entries, not re-baseline
            # from whatever free disk happens to be measured now.
            with mock.patch("rbpbench.coordinates.diskbudget.shutil.disk_usage", return_value=self._fake_disk_usage(150.0)):
                second = start_ledger(tmp_path, state_path=state_path)
                self.assertEqual(second.baseline.free_gib, first.baseline.free_gib)
                self.assertEqual(len(second.entries), 1)
                reloaded = load_ledger(state_path)
                self.assertEqual(reloaded.entries, first.entries)

    def test_cross_volume_placement_is_a_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            real_dir = tmp_path / "real"
            real_dir.mkdir()
            fake_dev_map = {str(real_dir): 1, str(tmp_path): 2}

            def fake_volume_id(path):
                path = Path(path)
                return fake_dev_map.get(str(path), 2)

            with mock.patch("rbpbench.coordinates.diskbudget.volume_id", side_effect=fake_volume_id):
                violations = check_pinned_volumes({"some_dir": real_dir}, primary=tmp_path)
            self.assertTrue(violations)
            self.assertIn("different filesystem volume", violations[0])

    def test_nonexistent_path_is_skipped_not_a_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            missing = tmp_path / "not_created_yet" / "deep" / "path"
            self.assertFalse(missing.exists())
            # volume_id walks up to the nearest existing ancestor (tmp_path
            # itself), so it resolves rather than returning None here — the
            # real "nothing to check" case is exercised in
            # check_pinned_volumes, which must not flag a same-volume path.
            violations = check_pinned_volumes({"missing": missing}, primary=tmp_path)
            self.assertEqual(violations, ())

    def test_growing_output_past_allowance_stops_the_subprocess(self):
        """B1-R4: the mapper output writer must enforce its allowance while
        writing, never merely check it before starting.
        """
        big_output_script = "#!/bin/bash\npython3 -c \"print('x' * 10000)\"\n"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = tmp_path / "big_tool.sh"
            script.write_text(big_output_script)
            script.chmod(0o755)
            out_path = tmp_path / "out.txt"
            err_path = tmp_path / "err.txt"
            with self.assertRaises(DiskBudgetExceeded):
                _run_tool_to_file([str(script)], output_path=out_path, stderr_path=err_path, max_output_bytes=100)

    def test_output_under_allowance_succeeds(self):
        small_output_script = "#!/bin/bash\necho hi\n"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = tmp_path / "small_tool.sh"
            script.write_text(small_output_script)
            script.chmod(0o755)
            out_path = tmp_path / "out.txt"
            err_path = tmp_path / "err.txt"
            _run_tool_to_file([str(script)], output_path=out_path, stderr_path=err_path, max_output_bytes=1_000_000)
            self.assertEqual(out_path.read_text(), "hi\n")


class R5CleanupSafetyTests(unittest.TestCase):
    """B1-R5: preview happens before deletion, the target must have exactly
    the pinned indices/<build>/ shape, and index provenance is durably
    receipted outside the disposable directory.
    """

    def test_cleanup_refuses_a_symlinked_component_even_with_all_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            real_dir = tmp_path / "indices" / "hg38_real"
            real_dir.mkdir(parents=True)
            (real_dir / "hg38.bwt").write_bytes(b"x")
            symlinked_index = tmp_path / "indices" / "hg38"
            symlinked_index.symlink_to(real_dir, target_is_directory=True)

            with self.assertRaises(CleanupRefused):
                execute_index_cleanup(
                    symlinked_index,
                    index_manifest_present=True,
                    mapping_outputs_present=True,
                    reconciliation_passed=True,
                    build="hg38",
                )
            self.assertTrue((real_dir / "hg38.bwt").is_file())

    def test_receipt_embeds_complete_index_manifest_outside_the_deleted_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            index_dir = tmp_path / "indices" / "hg38"
            index_dir.mkdir(parents=True)
            (index_dir / "hg38.bwt").write_bytes(b"x")
            receipt_path = tmp_path / "receipts" / "hg38_receipt.json"
            index_manifest = {"schema_version": 2, "build": "hg38", "bwa_index": {"files": []}}

            execute_index_cleanup(
                index_dir,
                index_manifest_present=True,
                mapping_outputs_present=True,
                reconciliation_passed=True,
                build="hg38",
                index_manifest=index_manifest,
                receipt_path=receipt_path,
            )
            self.assertFalse(index_dir.exists())
            self.assertTrue(receipt_path.is_file())
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["index_manifest"], index_manifest)
            self.assertTrue(receipt["completed"])


class R6MandatoryGatesTests(unittest.TestCase):
    """B1-R6: --execution-sources is mandatory for any invocation that reads
    the CSV, and --allow-mapping refuses an omitted or "all" --stage.
    """

    def test_omitted_execution_sources_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--output-dir", str(Path(tmp)),
                        "--stage", "sample",
                    ]
                )
            self.assertIn("--execution-sources is required", str(ctx.exception))

    def test_cleanup_only_invocation_does_not_require_execution_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            index_dir = indices_dir / "hg38"
            index_dir.mkdir(parents=True)
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--output-dir", str(output_dir),
                        "--indices-dir", str(indices_dir),
                        "--cleanup-index", "hg38",
                    ]
                )
            # Refused for cleanup-evidence reasons, never for a missing
            # --execution-sources.
            self.assertNotIn("--execution-sources is required", str(ctx.exception))

    def test_allow_mapping_with_stage_all_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(Path(tmp)),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                        "--stage", "all",
                    ]
                )
            self.assertIn("--stage allowlist", str(ctx.exception))

    def test_allow_mapping_with_omitted_stage_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(Path(tmp)),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                    ]
                )
            self.assertIn("--stage allowlist", str(ctx.exception))


class R7AcquisitionDerivationTests(unittest.TestCase):
    """B1-R7: guarded, restart-safe, fixture-tested download/derive stages,
    reachable through the actual runner CLI — never ad hoc Python.
    """

    def _source_spec(self):
        from rbpbench.coordinates.execution_sources import load_execution_sources

        spec = load_execution_sources(FIXTURE_EXECUTION_SOURCES)
        return spec.reference_sources["hg38"]

    def test_download_checksum_mismatch_is_refused_and_leaves_no_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_dir = Path(tmp) / "sources"

            def bad_transport(url, dest_path):
                dest_path.write_bytes(b"not the expected bytes")

            with self.assertRaises(Exception):
                stage_download(
                    build="hg38",
                    source_spec=self._source_spec(),
                    sources_dir=sources_dir,
                    allow_mapping=True,
                    host_role="approved_mac",
                    dry_run=False,
                    transport=bad_transport,
                )
            # No partial/promoted file left at the final destination.
            self.assertFalse(any(sources_dir.glob("*.fna.gz")) if sources_dir.exists() else False)

    def test_download_authoritative_size_mismatch_is_a_hard_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_dir = Path(tmp) / "sources"
            spec = self._source_spec()

            import hashlib

            payload = b"x" * 50

            def transport(url, dest_path):
                # Correct MD5 for this payload, but the wrong byte size
                # relative to the spec's authoritative plan size.
                dest_path.write_bytes(payload)

            import dataclasses

            adjusted_spec = dataclasses.replace(
                spec,
                fasta_upstream_md5=hashlib.md5(payload).hexdigest(),
                assembly_report_md5=hashlib.md5(payload).hexdigest(),
            )
            record = stage_download(
                build="hg38",
                source_spec=adjusted_spec,
                sources_dir=sources_dir,
                allow_mapping=True,
                host_role="approved_mac",
                dry_run=False,
                transport=transport,
            )
            self.assertFalse(record["executed"])
            self.assertIn("authoritative plan size", record["skip_reason"])

    def test_download_then_derive_through_the_actual_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            sources_dir = tmp_path / "sources"
            derived_dir = tmp_path / "derived"

            fasta_body = ">NC_TEST1.1\n" + "ACGT" * 5 + "\n"
            report_body = (
                "# Sequence-Name\tSequence-Role\tAssigned-Molecule\tAssigned-Molecule-Location/Type\t"
                "GenBank-Accn\tRelationship\tRefSeq-Accn\tAssembly-Unit\tSequence-Length\tUCSC-style-name\n"
                "1\tassembled-molecule\t1\tChromosome\tCM_TEST1.1\t=\tNC_TEST1.1\tPrimary Assembly\t20\tchr1\n"
            )
            import gzip
            import hashlib

            fasta_body_gz = gzip.compress(fasta_body.encode())
            fasta_md5 = hashlib.md5(fasta_body_gz).hexdigest()
            report_md5 = hashlib.md5(report_body.encode()).hexdigest()

            def fake_transport(url, dest_path):
                if "fna.gz" in url:
                    dest_path.write_bytes(fasta_body_gz)
                else:
                    dest_path.write_text(report_body)

            from rbpbench.coordinates.execution_sources import load_execution_sources

            spec = load_execution_sources(FIXTURE_EXECUTION_SOURCES)
            import dataclasses

            adjusted = dataclasses.replace(
                spec.reference_sources["hg38"],
                fasta_upstream_md5=fasta_md5,
                fasta_compressed_byte_size=len(fasta_body_gz),
                assembly_report_md5=report_md5,
            )

            with mock.patch("rbpbench.coordinates.runner.urllib_transport", fake_transport):
                with mock.patch(
                    "rbpbench.coordinates.runner.load_execution_sources",
                    return_value=dataclasses.replace(
                        spec, reference_sources={**spec.reference_sources, "hg38": adjusted}
                    ),
                ):
                    common = [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(output_dir),
                        "--sources-dir", str(sources_dir),
                        "--derived-dir", str(derived_dir),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                    ]
                    with _approved_host_context():
                        main([*common, "--stage", "download"])
                        main([*common, "--stage", "derive"])

            derive_record_path = derived_dir / "hg38" / "derive.json"
            self.assertTrue(derive_record_path.is_file())
            derive_record = json.loads(derive_record_path.read_text())
            self.assertTrue(derive_record["executed"])
            self.assertTrue(Path(derive_record["output_fasta"]).is_file())

    def test_failed_derivation_does_not_destroy_a_prior_valid_fasta(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(
                "# Sequence-Name\tSequence-Role\tAssigned-Molecule\tAssigned-Molecule-Location/Type\t"
                "GenBank-Accn\tRelationship\tRefSeq-Accn\tAssembly-Unit\tSequence-Length\tUCSC-style-name\n"
                "1\tassembled-molecule\t1\tChromosome\tCM_TEST1.1\t=\tNC_TEST1.1\tPrimary Assembly\t8\tchr1\n"
            )
            good_source = tmp_path / "source_good.fna"
            good_source.write_text(">NC_TEST1.1\nACGTACGT\n")
            output_fasta = tmp_path / "reference.fna"

            derive_reference_fasta(source_fasta=good_source, assembly_report=report_path, output_fasta=output_fasta)
            original_bytes = output_fasta.read_bytes()

            bad_source = tmp_path / "source_bad.fna"
            bad_source.write_text(">NC_TEST1.1\nACGT\n")  # wrong length vs. report
            with self.assertRaises(Exception):
                derive_reference_fasta(source_fasta=bad_source, assembly_report=report_path, output_fasta=output_fasta)

            self.assertEqual(output_fasta.read_bytes(), original_bytes)
            leftovers = list(tmp_path.glob("reference.fna.tmp*"))
            self.assertEqual(leftovers, [])


class R8MappingWarningsAndReconciliationTests(unittest.TestCase):
    """B1-R8: minimap2 mapping-time stderr warnings must stop the run, and
    a failed reconciliation must remain retryable (never marked complete).
    """

    def test_check_minimap2_mapping_stderr_flags_override_warning(self):
        violations = check_minimap2_mapping_stderr(
            "[E::main] Indexing parameters (-k, -w or -H) overridden by parameters used in the prebuilt index.\n"
        )
        self.assertTrue(any("overridden" in v for v in violations))

    def test_check_minimap2_mapping_stderr_flags_multipart(self):
        stderr = (
            "[M::mm_idx_stat] kmer size: 15; skip: 5; is_hpc: 0; #seq: 1\n"
            "[M::mm_idx_stat] kmer size: 15; skip: 5; is_hpc: 0; #seq: 1\n"
        )
        violations = check_minimap2_mapping_stderr(stderr)
        self.assertTrue(any("part" in v for v in violations))

    def test_check_minimap2_mapping_stderr_empty_is_clean(self):
        self.assertEqual(check_minimap2_mapping_stderr(""), ())
        self.assertEqual(check_minimap2_mapping_stderr("ordinary log line\n"), ())

    def test_align_refuses_to_promote_when_minimap2_mapping_stderr_is_disqualifying(self):
        fake_minimap2_overridden = (
            "#!/bin/bash\n"
            "if [ \"$#\" -le 0 ]; then\n"
            "  echo \"2.31\"\n"
            "  exit 0\n"
            "fi\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" == \"--version\" ]; then\n"
            "    echo \"2.31\"\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "reads=\"${@: -1}\"\n"
            "echo 'Indexing parameters (-k, -w or -H) overridden by parameters used in the prebuilt index.' >&2\n"
            "awk '\n"
            "  /^>/ { if (name != \"\") print name \"\\t0\\tchr1\\t1\\t60\\t\" length(seq) \"=\\t*\\t0\\t0\\t\" seq \"\\t*\\tAS:i:\" length(seq); "
            "name=substr($0,2); seq=\"\"; next }\n"
            "  { seq = seq $0 }\n"
            "  END { if (name != \"\") print name \"\\t0\\tchr1\\t1\\t60\\t\" length(seq) \"=\\t*\\t0\\t0\\t\" seq \"\\t*\\tAS:i:\" length(seq) }\n"
            "' \"$reads\"\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", fake_minimap2_overridden)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference, _ = _reference_and_manifest(output_dir, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            manifest = output_dir / "hg38_manifest.json"

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
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

            align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            self.assertFalse(align_record["executed"])
            self.assertIn("disqualifying", align_record["skip_reason"])
            self.assertFalse((output_dir / "hg38" / "align_minimap2_splice.sam").exists())

    def test_failed_reconciliation_remains_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference, _ = _reference_and_manifest(output_dir, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            manifest = output_dir / "hg38_manifest.json"
            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
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

                sample_state_path = output_dir / "sample_state.json"
                sample_state = json.loads(sample_state_path.read_text())
                sample_state["assignments"] = sample_state["assignments"][:-1]
                sample_state_path.write_text(json.dumps(sample_state))

                with self.assertRaises(SystemExit):
                    main([*common, "--force", "--stage", "report"])

                state = json.loads((output_dir / "state.json").read_text())
                self.assertNotIn("report:hg38", state["completed_stages"])

                # Fix the sample state back and re-run *without* --force:
                # a failed report must not have been silently marked
                # complete, so a later non-forced invocation must still
                # attempt it (not skip it as "already completed").
                sample_state["assignments"].append(
                    {"sample_id": "extra", "row_index": 999, "stratum": "filler", "labels": []}
                )
                # Restore original count instead by re-reading original file
                # is simpler: just re-run report with --force again and
                # confirm it is attempted (raises) rather than skipped.
                with self.assertRaises(SystemExit):
                    main([*common, "--stage", "report"])


class R9MaskingClassificationTests(unittest.TestCase):
    """B1-R9: masking status must never infer `hard` from an ambiguous-
    symbol (N) fraction alone.
    """

    _REPORT_TEMPLATE = (
        "# Sequence-Name\tSequence-Role\tAssigned-Molecule\tAssigned-Molecule-Location/Type\t"
        "GenBank-Accn\tRelationship\tRefSeq-Accn\tAssembly-Unit\tSequence-Length\tUCSC-style-name\n"
        "1\tassembled-molecule\t1\tChromosome\tCM_TEST1.1\t=\tNC_TEST1.1\tPrimary Assembly\t{length}\tchr1\n"
    )

    def _derive(self, tmp_path: Path, *, sequence: str):
        report_path = tmp_path / "report.txt"
        report_path.write_text(self._REPORT_TEMPLATE.format(length=len(sequence)))
        source = tmp_path / "source.fna"
        source.write_text(f">NC_TEST1.1\n{sequence}\n")
        output = tmp_path / "out.fna"
        return derive_reference_fasta(source_fasta=source, assembly_report=report_path, output_fasta=output)

    def test_lowercase_bases_report_soft(self):
        with tempfile.TemporaryDirectory() as tmp:
            derivation = self._derive(Path(tmp), sequence="acgtACGT")
            self.assertEqual(derivation.masking["status"], "soft")

    def test_uppercase_only_reports_none_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            derivation = self._derive(Path(tmp), sequence="ACGTACGT")
            self.assertEqual(derivation.masking["status"], "none_detected")

    def test_uppercase_with_high_ambiguous_fraction_still_reports_none_detected(self):
        """An uppercase assembly with ordinary assembly gaps (many `N`s)
        must never be labeled `hard` from base counts alone.
        """
        with tempfile.TemporaryDirectory() as tmp:
            derivation = self._derive(Path(tmp), sequence="NNNNNNNNNNNNNNNNNNAC")
            self.assertEqual(derivation.masking["status"], "none_detected")
            self.assertGreater(derivation.masking["ambiguous"], 0)


class AdditionalProvenanceCorrectionTests(unittest.TestCase):
    """Index-building provenance must record the actually-detected pinned
    binary version, never a hardcoded None; provenance.json must persist
    build/disk evidence cumulatively across separate invocations.
    """

    @unittest.skipUnless(
        __import__("shutil").which("bwa") and __import__("shutil").which("minimap2"),
        "requires real bwa/minimap2 on PATH",
    )
    def test_index_provenance_records_a_real_resolved_version(self):
        from rbpbench.coordinates.indexing import prepare_bwa_index, prepare_minimap2_index

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            import random

            rng = random.Random(7)
            body = "".join(rng.choice("ACGT") for _ in range(500))
            reference = tmp_path / "reference.fasta"
            reference.write_text(f">chrTest\n{body}\n")

            bwa_prov = prepare_bwa_index(reference, tmp_path / "hg38")
            mm2_prov = prepare_minimap2_index(reference, tmp_path / "hg38.mmi")
            self.assertIsNotNone(bwa_prov.binary.version)
            self.assertIsNotNone(mm2_prov.binary.version)

    def test_provenance_json_is_cumulative_across_invocations_with_different_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            ref_hg38, _ = _reference_and_manifest(output_dir, build="hg38", content=">chr1\n" + "A" * 20 + "\n")
            ref_hg19, _ = _reference_and_manifest(output_dir, build="hg19", content=">chr1\n" + "G" * 20 + "\n")

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                common_hg38 = [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(output_dir),
                    "--allow-mapping",
                    "--host-role", "approved_mac",
                    "--reference", f"hg38={ref_hg38}",
                    "--reference-manifest", f"hg38={output_dir / 'hg38_manifest.json'}",
                    "--build", "hg38",
                ]
                main([*common_hg38, "--stage", "sample"])
                main([*common_hg38, "--stage", "decode"])
                main([*common_hg38, "--stage", "controls"])
                main([*common_hg38, "--stage", "align"])
                provenance_after_hg38 = json.loads((output_dir / "provenance.json").read_text())
                self.assertIn("hg38", provenance_after_hg38["builds"])
                self.assertTrue(provenance_after_hg38["builds"]["hg38"]["align"].get("executed"))

                # A separate invocation naming only hg19 must not drop hg38's
                # already-recorded evidence from provenance.json.
                common_hg19 = [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(output_dir),
                    "--allow-mapping",
                    "--host-role", "approved_mac",
                    "--reference", f"hg19={ref_hg19}",
                    "--reference-manifest", f"hg19={output_dir / 'hg19_manifest.json'}",
                    "--build", "hg19",
                ]
                main([*common_hg19, "--stage", "sample"])
                main([*common_hg19, "--stage", "decode"])
                main([*common_hg19, "--stage", "controls"])
                main([*common_hg19, "--stage", "align"])

            provenance_after_hg19 = json.loads((output_dir / "provenance.json").read_text())
            self.assertIn("hg38", provenance_after_hg19["builds"])
            self.assertTrue(provenance_after_hg19["builds"]["hg38"]["align"].get("executed"))
            self.assertIn("hg19", provenance_after_hg19["builds"])
            self.assertTrue(provenance_after_hg19["builds"]["hg19"]["align"].get("executed"))


if __name__ == "__main__":
    unittest.main()
