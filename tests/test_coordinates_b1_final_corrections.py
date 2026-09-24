"""Regression coverage for the Task 001B checkpoint B1 FINAL convergence
round.

Every test here targets exactly one item from
``docs/reviews/001b_b1_second_correction_review.md`` (B1-F1 through B1-F6,
plus the "Transaction completion requirement") and demonstrably fails against
commit ``01d98b5`` (the reviewed, pre-final-correction implementation).
Fixtures are tiny and synthetic throughout; the real CSV is never opened and
no NCBI URL is ever requested (B1's authorization boundary), consistent with
the rest of the coordinate-runner test suite.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.diskbudget import BuildOutputBudget, DiskBudgetExceeded, start_build_output_budget
from rbpbench.coordinates.indexing import build_index_manifest, verify_index_binding
from rbpbench.coordinates.manifest import manifest_content_sha256
from rbpbench.coordinates.cleanup import resolve_git_repo_root
from rbpbench.coordinates.runner import (
    _current_output_bytes,
    _guarded_write_record,
    _load_report_state,
    _new_generation_dir,
    _run_tool_to_file,
    _verify_derive_evidence_hashes,
    main,
    stage_align,
    stage_derive,
    stage_download,
    stage_exact_match,
    stage_index,
    stage_report,
)
from rbpbench.coordinates.sampling import SampleAssignment, SamplingResult
from rbpbench.data.audit import sha256_file

from test_coordinates_runner import (
    FIXTURE_CONFIG,
    FIXTURE_CSV,
    FIXTURE_EXECUTION_SOURCES,
    _FAKE_SEQKIT,
    _approved_host_context,
    _write_fake_executable,
    _write_reference_manifest,
)
from test_coordinates_b1_second_corrections import _FAKE_BWA_FULL, _FAKE_MINIMAP2_FULL
from test_coordinates_runner_b1 import _git_init, _write_realistic_cleanup_evidence


def _cfg():
    from rbpbench.coordinates.config import load_config

    return load_config(FIXTURE_CONFIG)


def _tiny_sample() -> SamplingResult:
    assignment = SampleAssignment(sample_id="row_0", row_index=0, stratum="representative", labels=(1, 0))
    return SamplingResult(
        assignments=(assignment,),
        representative_ids=frozenset({"row_0"}),
        quota_ids=frozenset(),
        filler_ids=frozenset(),
        unsatisfied_quotas=(),
    )


def _write_reads(path: Path, *, sample_id: str = "row_0") -> Path:
    path.write_text(f">{sample_id}\n" + "A" * 20 + "\n")
    return path


class F1CombinedDiskBudgetTests(unittest.TestCase):
    """B1-F1: one live aggregate per-build output counter must cover stdout
    AND stderr for every writer, plus report/mappings/reference-index
    artifacts, never merely stdout alone or each writer independently
    capped.
    """

    def test_stderr_only_growth_breaches_the_cap(self):
        """Reproduces the exact B1-F1 defect: a subprocess writing large
        bytes to stderr and near-zero to stdout was previously accepted
        under a cap, because only stdout was polled.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_path = tmp_path / "out.txt"
            stderr_path = tmp_path / "err.txt"
            argv = ["python3", "-c", "import sys; sys.stderr.write('x' * 1000)"]
            with self.assertRaises(DiskBudgetExceeded):
                _run_tool_to_file(argv, output_path=output_path, stderr_path=stderr_path, max_output_bytes=100)

    def test_combined_stdout_and_stderr_within_cap_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_path = tmp_path / "out.txt"
            stderr_path = tmp_path / "err.txt"
            argv = ["python3", "-c", "import sys; print('a' * 10); sys.stderr.write('b' * 10)"]
            _run_tool_to_file(argv, output_path=output_path, stderr_path=stderr_path, max_output_bytes=1000)
            self.assertTrue(output_path.is_file())

    def test_build_output_budget_shares_remainder_across_writers(self):
        budget = start_build_output_budget(total_allowance_gib=0, already_accepted_bytes=0)
        # Override the byte total directly for a deterministic tiny test.
        budget = BuildOutputBudget(total_allowance_bytes=300, accepted_bytes=0)
        self.assertEqual(budget.remaining_bytes, 300)
        budget.accept(150)
        self.assertEqual(budget.remaining_bytes, 150)
        budget.accept(200)
        # Never goes negative even when total accepted exceeds the allowance.
        self.assertEqual(budget.remaining_bytes, 0)

    def test_align_bwa_and_minimap2_share_one_combined_allowance(self):
        """Individually sub-limit writers (each alone under the cap) must
        still be rejected when their COMBINED bytes exceed it — the B1-C3/F1
        acceptance case, exercised end-to-end through stage_align.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(
                bin_dir, "bwa",
                "#!/bin/bash\nif [ \"$#\" -le 0 ]; then echo 'Version: 0.7.19'; exit 0; fi\n"
                "python3 -c \"print('x' * 150)\"\n",
            )
            _write_fake_executable(
                bin_dir, "minimap2",
                "#!/bin/bash\n"
                "if [ \"$#\" -le 0 ]; then echo '2.31'; exit 0; fi\n"
                "for arg in \"$@\"; do if [ \"$arg\" == \"--version\" ]; then echo '2.31'; exit 0; fi; done\n"
                "python3 -c \"print('y' * 150)\"\n",
            )
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            reads = _write_reads(tmp_path / "reads.fasta")
            manifest = json.loads(_write_reference_manifest(tmp_path / "manifest.json", build="hg38", reference=reference).read_text())

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context(), mock.patch(
                "rbpbench.coordinates.runner.BUILD_OUTPUT_ALLOWANCE_GIB", 200 / (1024**3)
            ):
                with self.assertRaises(DiskBudgetExceeded):
                    stage_align(
                        _cfg(),
                        build="hg38",
                        build_output_dir=tmp_path / "out" / "hg38",
                        allow_mapping=True,
                        host_role="approved_mac",
                        threads=1,
                        reference=reference,
                        reference_manifest=manifest,
                        reads_fasta=reads,
                        dry_run=False,
                    )
            # No accepted generation was left behind by the rejected attempt.
            align_json = tmp_path / "out" / "hg38" / "align.json"
            self.assertFalse(align_json.exists())

    def test_report_artifacts_pushing_the_aggregate_over_the_limit_is_rejected(self):
        """Report's own mappings/report/reference-index artifacts must be
        charged to and checked against the SAME combined allowance as
        align/exact_match — not exempt from it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            build_dir = tmp_path / "hg38"
            build_dir.mkdir(parents=True)
            align_record = {"executed": False}
            exact_match_record = {"executed": False}
            # A near-zero remaining budget: even the smallest report set
            # (report.json + report.md, no mapping evaluated) still fits, so
            # use an explicitly zero-allowance budget to force rejection
            # regardless of mapping_evaluated status.
            budget = BuildOutputBudget(total_allowance_bytes=0, accepted_bytes=0)
            with self.assertRaises(DiskBudgetExceeded):
                stage_report(
                    _tiny_sample(),
                    cfg=_cfg(),
                    build_output_dir=build_dir,
                    expected_total=1,
                    expected_representative=1,
                    expected_controls=0,
                    build="hg38",
                    align_record=align_record,
                    exact_match_record=exact_match_record,
                    reference=None,
                    reference_manifest=None,
                    build_budget=budget,
                )
            # No report was promoted at the fixed convenience path.
            self.assertFalse((build_dir / "report.json").exists())
            self.assertFalse((build_dir / "report_state.json").exists())


class F2TransactionalReportTests(unittest.TestCase):
    """B1-F2: the complete per-build report artifact set is one generation
    selected by an atomic report-stage record; a failed reconciliation or a
    disk-budget breach must never overwrite a previously accepted report.
    """

    def _mapping_evaluated_kwargs(self, tmp_path: Path, build_dir: Path, *, expected_total: int = 1) -> dict:
        """A fixture where align/exact_match both recorded executed=True
        against empty-but-real SAM/BED files, so reconciliation is actually
        EVALUATED (never merely "not_evaluated") and can be made to FAIL by
        passing a mismatched ``expected_total``.
        """
        reference = tmp_path / "reference.fasta"
        reference.write_text(">chr1\n" + "A" * 20 + "\n")
        manifest = json.loads(
            _write_reference_manifest(tmp_path / "manifest.json", build="hg38", reference=reference).read_text()
        )
        bwa_sam = tmp_path / "align_bwa_mem.sam"
        mm2_sam = tmp_path / "align_minimap2_splice.sam"
        bed = tmp_path / "exact_match_hits.bed"
        bwa_sam.write_text("")
        mm2_sam.write_text("")
        bed.write_text("")
        align_record = {
            "executed": True,
            "reference_sha256": manifest["sha256"],
            "reference_manifest_content_sha256": manifest_content_sha256(manifest),
            "sam_paths": {"bwa_mem": str(bwa_sam), "minimap2_splice": str(mm2_sam)},
        }
        exact_match_record = {
            "executed": True,
            "reference_sha256": manifest["sha256"],
            "reference_manifest_content_sha256": manifest_content_sha256(manifest),
            "bed_path": str(bed),
        }
        return dict(
            cfg=_cfg(),
            build_output_dir=build_dir,
            expected_total=expected_total,
            expected_representative=1,
            expected_controls=0,
            build="hg38",
            align_record=align_record,
            exact_match_record=exact_match_record,
            reference=reference,
            reference_manifest=manifest,
        )

    def test_forced_failed_retry_never_overwrites_a_previously_passed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            build_dir = tmp_path / "hg38"
            sample = _tiny_sample()

            first = stage_report(sample, **self._mapping_evaluated_kwargs(tmp_path, build_dir, expected_total=1))
            self.assertEqual(first["reconciliation"]["status"], "passed")
            original_report_bytes = (build_dir / "report.json").read_bytes()
            original_state = json.loads((build_dir / "report_state.json").read_text())

            # A forced retry with a MISMATCHED expected_total makes
            # reconciliation fail this time.
            second = stage_report(sample, **self._mapping_evaluated_kwargs(tmp_path, build_dir, expected_total=999))
            self.assertEqual(second["reconciliation"]["status"], "failed")

            # The fixed-path report.json and report_state.json are BYTE-FOR-
            # BYTE untouched by the failed retry.
            self.assertEqual((build_dir / "report.json").read_bytes(), original_report_bytes)
            self.assertEqual(json.loads((build_dir / "report_state.json").read_text()), original_state)
            # The failed attempt's own generation was discarded, not left as
            # an accepted (or even lingering-but-referenced) generation.
            self.assertNotIn("999", (build_dir / "report.json").read_text())

    def test_later_non_forced_retry_still_sees_the_original_passed_report(self):
        """After a passed report followed by a forced failed retry, a LATER
        non-forced invocation must be able to validly skip (its restart-skip
        revalidation must find no drift) and therefore still observe the
        ORIGINAL accepted generation — never the failed retry's.
        """
        from rbpbench.coordinates.runner import _verify_report_state_evidence_hashes

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            build_dir = tmp_path / "hg38"
            sample = _tiny_sample()
            stage_report(sample, **self._mapping_evaluated_kwargs(tmp_path, build_dir, expected_total=1))
            original_state = json.loads((build_dir / "report_state.json").read_text())

            # A forced retry that fails...
            stage_report(sample, **self._mapping_evaluated_kwargs(tmp_path, build_dir, expected_total=999))

            # ...must leave report_state.json in a state that STILL
            # revalidates cleanly (a later non-forced invocation can validly
            # skip and therefore still see the ORIGINAL accepted report).
            current_state = json.loads((build_dir / "report_state.json").read_text())
            self.assertEqual(current_state, original_state)
            self.assertEqual(_verify_report_state_evidence_hashes(current_state), ())

    def _not_evaluated_kwargs(self, build_dir: Path) -> dict:
        return dict(
            cfg=_cfg(),
            build_output_dir=build_dir,
            expected_total=1,
            expected_representative=1,
            expected_controls=0,
            build="hg38",
            align_record={"executed": False},
            exact_match_record={"executed": False},
            reference=None,
            reference_manifest=None,
        )

    def test_disk_budget_breach_during_report_never_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp) / "hg38"
            sample = _tiny_sample()
            stage_report(sample, **self._not_evaluated_kwargs(build_dir))
            original_bytes = (build_dir / "report.json").read_bytes()

            with self.assertRaises(DiskBudgetExceeded):
                stage_report(
                    sample,
                    build_budget=BuildOutputBudget(total_allowance_bytes=0, accepted_bytes=0),
                    **self._not_evaluated_kwargs(build_dir),
                )
            self.assertEqual((build_dir / "report.json").read_bytes(), original_bytes)

    def test_report_state_evidence_survives_process_interruption_mid_generation(self):
        """A crash/exception partway through building the candidate
        generation (after some but not all files are written) must discard
        the whole partial generation and leave any prior accepted report
        untouched.
        """
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp) / "hg38"
            sample = _tiny_sample()
            stage_report(sample, **self._not_evaluated_kwargs(build_dir))
            original_bytes = (build_dir / "report.json").read_bytes()
            generations_before = set((build_dir / "generations").glob("*"))

            with mock.patch(
                "rbpbench.coordinates.runner.render_markdown", side_effect=RuntimeError("simulated interruption")
            ):
                with self.assertRaises(RuntimeError):
                    stage_report(sample, **self._not_evaluated_kwargs(build_dir))

            self.assertEqual((build_dir / "report.json").read_bytes(), original_bytes)
            # The interrupted attempt's own (partial) generation directory
            # was discarded, not left behind as orphaned disk debris.
            generations_after = set((build_dir / "generations").glob("*"))
            self.assertEqual(generations_before, generations_after)


class F3ChainedGenerationDigestTests(unittest.TestCase):
    """B1-F3: downstream restart validity must be chained from the accepted
    UPSTREAM GENERATION digest, not merely a declared-input fingerprint or
    an ``executed`` boolean — so a forced upstream rerun that changes actual
    content is detected even when no CLI flag changed.
    """

    def _index_manifest(self, *, reference_sha256: str, salt: str) -> dict:
        return build_index_manifest(
            build="hg38",
            bwa={"tool": "bwa_index", "files": [{"path": f"/tmp/{salt}.bwt", "byte_size": 1, "sha256": "a" * 64}]},
            minimap2={"tool": "minimap2_index", "files": [{"path": f"/tmp/{salt}.mmi", "byte_size": 1, "sha256": "b" * 64}]},
            reference_sha256=reference_sha256,
            reference_manifest_content_sha256="c" * 64,
        )

    def test_byte_identical_rebuild_keeps_the_same_generation_digest(self):
        manifest_a = self._index_manifest(reference_sha256="r" * 64, salt="same")
        manifest_b = self._index_manifest(reference_sha256="r" * 64, salt="same")
        self.assertEqual(manifest_content_sha256(manifest_a), manifest_content_sha256(manifest_b))

    def test_genuinely_different_rebuild_changes_the_generation_digest(self):
        manifest_a = self._index_manifest(reference_sha256="r" * 64, salt="a")
        manifest_b = self._index_manifest(reference_sha256="s" * 64, salt="a")
        self.assertNotEqual(manifest_content_sha256(manifest_a), manifest_content_sha256(manifest_b))

    def test_forced_index_rerun_with_nondeterministic_content_invalidates_align_restart_skip(self):
        """End-to-end through the CLI: a forced index rerun against the SAME
        reference that happens to produce DIFFERENT index bytes (simulating
        real-world index-build non-determinism, e.g. an updated tool build)
        must force align to re-verify on its next invocation, never stay
        silently "skippable" merely because align's OWN declared-input
        fingerprint never changed (it did not: the reference is unchanged).
        The ordinary reference_sha256 binding check alone would NOT catch
        this — the index still correctly binds to the same reference — only
        the generation-digest chain does.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            # A fake bwa/minimap2 index builder whose output bytes include a
            # random component: successive builds from the IDENTICAL
            # reference are still bound to the same reference_sha256, but
            # are byte-different generations.
            _write_fake_executable(
                bin_dir, "bwa",
                "#!/bin/bash\n"
                "if [ \"$#\" -le 0 ]; then echo 'Version: 0.7.19'; exit 0; fi\n"
                "if [ \"$1\" == \"index\" ]; then\n"
                "  prefix=\"$3\"\n"
                "  for suffix in .amb .ann .bwt .pac .sa; do\n"
                "    printf 'fake bwa index bytes %s' \"$RANDOM$RANDOM\" > \"${prefix}${suffix}\"\n"
                "  done\n"
                "  exit 0\n"
                "fi\n"
                "reads=\"${@: -1}\"\n"
                "awk '/^>/ { if (name != \"\") print name \"\\t0\\tchr1\\t1\\t60\\t\" length(seq) \"M\\t*\\t0\\t0\\t\" seq \"\\t*\\tNM:i:0\\tAS:i:\" length(seq); name=substr($0,2); seq=\"\"; next } { seq = seq $0 } END { if (name != \"\") print name \"\\t0\\tchr1\\t1\\t60\\t\" length(seq) \"M\\t*\\t0\\t0\\t\" seq \"\\t*\\tNM:i:0\\tAS:i:\" length(seq) }' \"$reads\"\n",
            )
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2_FULL)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 40 + "\n")
            manifest_path = tmp_path / "manifest.json"
            _write_reference_manifest(manifest_path, build="hg38", reference=reference)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--indices-dir", str(indices_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest_path}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample", "--stage", "decode", "--stage", "controls"])
                main([*common, "--stage", "index"])
                main([*common, "--stage", "align"])
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertTrue(align_record["executed"])
                first_bwa_prefix = align_record["index_paths"]["bwa_index_prefix"]

                # Force-rebuild the index against the UNCHANGED reference —
                # declared inputs (--reference/--reference-manifest) are
                # identical to align's own last-used values.
                main([*common, "--force", "--stage", "index"])
                new_index_record = json.loads((indices_dir / "hg38" / "index.json").read_text())
                self.assertNotEqual(new_index_record["bwa_index_prefix"], first_bwa_prefix)

                # A non-forced align re-invocation: its OWN declared-input
                # fingerprint is unchanged (same reference/manifest/flags),
                # so only the upstream-generation-digest chain can force
                # re-verification here.
                main([*common, "--stage", "align"])

            second_align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            # align actually re-ran (rebound to the new index generation)
            # rather than being silently skipped with stale index paths.
            self.assertEqual(
                second_align_record["index_paths"]["bwa_index_prefix"],
                new_index_record["bwa_index_prefix"],
            )

    def test_forced_align_rerun_invalidates_exact_match_restart_skip(self):
        exact_match_record = {
            "executed": True,
            "bed_path": "/does/not/matter",
            "upstream_align_generation_digest": "old-digest",
        }
        from rbpbench.coordinates.runner import _upstream_generation_digest_violation

        violations = _upstream_generation_digest_violation(
            exact_match_record, upstream_key="upstream_align_generation_digest", current_digest="new-digest"
        )
        self.assertTrue(violations)
        self.assertIn("new-digest", violations[0])

        # No violation when the upstream digest still matches (byte-
        # equivalent case correctly stays skippable).
        no_violation = _upstream_generation_digest_violation(
            exact_match_record, upstream_key="upstream_align_generation_digest", current_digest="old-digest"
        )
        self.assertEqual(no_violation, ())

    def test_index_generation_still_referenced_by_align_is_not_pruned(self):
        """B1-F3: a forced index rerun must not prune the OLD generation
        while an already-accepted align.json record still depends on it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA_FULL)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2_FULL)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 40 + "\n")
            manifest = json.loads(_write_reference_manifest(tmp_path / "manifest.json", build="hg38", reference=reference).read_text())
            index_dir = tmp_path / "indices" / "hg38"

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                first_index = stage_index(
                    _cfg(), build="hg38", index_dir=index_dir, allow_mapping=True, host_role="approved_mac",
                    threads=1, reference=reference, reference_manifest=manifest, dry_run=False,
                )
                self.assertTrue(first_index["executed"])
                first_bwa_prefix = Path(first_index["bwa_index_prefix"])
                self.assertTrue(first_bwa_prefix.with_suffix(".bwt").exists() or (index_dir / "generations").exists())

                # An accepted align record that still names the FIRST
                # index's generation digest as its upstream dependency.
                downstream_align_record = {
                    "executed": True,
                    "upstream_index_generation_digest": {
                        "bwa_index": first_index["generation_digest"],
                        "minimap2_index": first_index["generation_digest"],
                    },
                }

                second_index = stage_index(
                    _cfg(), build="hg38", index_dir=index_dir, allow_mapping=True, host_role="approved_mac",
                    threads=1, reference=reference, reference_manifest=manifest, dry_run=False,
                    downstream_align_record=downstream_align_record,
                )
                self.assertTrue(second_index["executed"])
                self.assertNotEqual(second_index["bwa_index_prefix"], first_index["bwa_index_prefix"])

            # The FIRST generation's files were NOT pruned: align.json still
            # depends on them.
            first_generation_dir = Path(first_index["bwa_index_prefix"]).parent
            self.assertTrue(first_generation_dir.exists())


class F4ManifestEvidenceTests(unittest.TestCase):
    """B1-F4: both the derived manifest's own hash/size AND the raw
    reference-manifest file hash (distinct from the canonical parsed-content
    hash) must be recorded and revalidated.
    """

    def test_semantic_derived_manifest_tampering_is_detected_on_restart(self):
        derive_record = {
            "executed": True,
            "output_fasta": "",
            "output_fasta_sha256": "",
            "reference_manifest_path": "",
            "reference_manifest_sha256": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fasta = tmp_path / "reference.fna"
            fasta.write_text(">chr1\nACGT\n")
            manifest_path = tmp_path / "reference_manifest.json"
            manifest_path.write_text(json.dumps({"contigs": ["chr1"]}))
            derive_record["output_fasta"] = str(fasta)
            derive_record["output_fasta_sha256"] = sha256_file(fasta)
            derive_record["reference_manifest_path"] = str(manifest_path)
            derive_record["reference_manifest_sha256"] = sha256_file(manifest_path)

            self.assertEqual(_verify_derive_evidence_hashes(derive_record), ())

            # A semantic edit to the manifest's CONTENT (path unchanged).
            manifest_path.write_text(json.dumps({"contigs": ["chr1", "chr2"]}))
            violations = _verify_derive_evidence_hashes(derive_record)
            self.assertTrue(violations)
            self.assertIn("reference_manifest_path", violations[0])

    def test_whitespace_only_raw_manifest_drift_is_distinguished_from_canonical_content(self):
        """Two manifest FILES that parse to identical content (same
        canonical hash) but differ byte-for-byte (different raw hash) must
        be distinguished by verify_index_binding's raw-hash check.
        """
        payload = {"a": 1, "b": 2}
        compact_bytes = json.dumps(payload, sort_keys=True).encode()
        pretty_bytes = json.dumps(payload, indent=4, sort_keys=True).encode()
        import hashlib

        compact_raw_sha256 = hashlib.sha256(compact_bytes).hexdigest()
        pretty_raw_sha256 = hashlib.sha256(pretty_bytes).hexdigest()
        self.assertNotEqual(compact_raw_sha256, pretty_raw_sha256)
        # Canonical content hash (independent of raw formatting) is the same
        # for both, by construction of manifest_content_sha256.
        self.assertEqual(manifest_content_sha256(payload), manifest_content_sha256(payload))

        manifest = build_index_manifest(
            build="hg38",
            bwa=None,
            minimap2=None,
            reference_sha256="r" * 64,
            reference_manifest_content_sha256=manifest_content_sha256(payload),
            reference_manifest_raw_sha256=compact_raw_sha256,
        )
        # The CURRENT raw hash (pretty-printed) disagrees with what the
        # index manifest recorded (compact) even though canonical content
        # is identical — must be flagged.
        violations = verify_index_binding(
            manifest,
            key="bwa_index",
            actual_path=Path("/tmp/does-not-matter"),
            expected_build="hg38",
            expected_reference_sha256="r" * 64,
            expected_reference_manifest_content_sha256=manifest_content_sha256(payload),
            expected_reference_manifest_raw_sha256=pretty_raw_sha256,
        )
        self.assertTrue(any("raw" in v for v in violations))

        # Matching raw hash: no raw-hash violation.
        violations_matching = verify_index_binding(
            manifest,
            key="bwa_index",
            actual_path=Path("/tmp/does-not-matter"),
            expected_build="hg38",
            expected_reference_sha256="r" * 64,
            expected_reference_manifest_content_sha256=manifest_content_sha256(payload),
            expected_reference_manifest_raw_sha256=compact_raw_sha256,
        )
        self.assertFalse(any("raw" in v for v in violations_matching))


class F5CheckpointBoundaryTests(unittest.TestCase):
    """B1-F5: under real --allow-mapping, exactly one build-scoped stage may
    run, accompanied by nothing but "preflight"; combined_report must never
    accompany --allow-mapping at all.
    """

    def test_b2_stage_combined_with_align_is_rejected_before_data_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(Path(tmp) / "does_not_exist.csv"),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(Path(tmp) / "out"),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                        "--stage", "sample", "--stage", "align",
                    ]
                )
            self.assertIn("exactly one build-scoped stage", str(ctx.exception))

    def test_report_combined_with_combined_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(Path(tmp) / "does_not_exist.csv"),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(Path(tmp) / "out"),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                        "--stage", "report", "--stage", "combined_report",
                    ]
                )
            self.assertIn("combined_report", str(ctx.exception))

    def test_combined_report_alone_with_allow_mapping_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(Path(tmp) / "does_not_exist.csv"),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(Path(tmp) / "out"),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                        "--stage", "combined_report",
                    ]
                )
            self.assertIn("combined_report", str(ctx.exception))

    def test_build_scoped_stage_with_only_preflight_is_still_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(Path(tmp) / "out"),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                        "--stage", "preflight", "--stage", "align",
                    ]
                )
            except SystemExit as exc:
                self.assertNotIn("exactly one build-scoped stage", str(exc))
                self.assertNotIn("combined_report", str(exc))

    def test_solo_b2_stage_with_allow_mapping_present_remains_allowed(self):
        """allow_mapping is simply unused by sample/decode/controls alone;
        this must remain permitted (many existing invocations reuse one
        authorized flag set across every stage of a study).
        """
        with tempfile.TemporaryDirectory() as tmp:
            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(Path(tmp) / "out"),
                    "--allow-mapping",
                    "--host-role", "approved_mac",
                    "--build", "hg38",
                    "--stage", "sample",
                ]
            )  # must not raise


class F6CleanupPinningTests(unittest.TestCase):
    """B1-F6: the repository root must be resolved independently (never
    merely trusted from --repo-root, even when it agrees with
    --indices-dir's parent), and a valid, hash-verified derive record is
    mandatory before cleanup proceeds at all.
    """

    def test_arbitrary_matched_root_not_the_real_git_root_is_refused(self):
        """--repo-root and --indices-dir's parent agree with EACH OTHER
        (the pre-F6 check would have accepted this) but neither is the
        REAL checked-out Git repository root.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)  # deliberately NOT a git repository
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            index_dir = indices_dir / "hg38"
            derived_dir = tmp_path / "derived"
            _write_realistic_cleanup_evidence(
                output_dir=output_dir, index_dir=index_dir, build="hg38", reconciliation_status="passed",
                derived_dir=derived_dir,
            )

            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(output_dir),
                        "--indices-dir", str(indices_dir),
                        "--derived-dir", str(derived_dir),
                        "--repo-root", str(tmp_path),
                        "--cleanup-index", "hg38",
                    ]
                )
            self.assertIn("Git", str(ctx.exception))
            self.assertTrue(index_dir.exists())

    def test_missing_derive_record_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _git_init(tmp_path)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            index_dir = indices_dir / "hg38"
            # Note: derived_dir intentionally omitted -- no derive.json exists.
            _write_realistic_cleanup_evidence(
                output_dir=output_dir, index_dir=index_dir, build="hg38", reconciliation_status="passed",
            )

            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(output_dir),
                        "--indices-dir", str(indices_dir),
                        "--repo-root", str(tmp_path),
                        "--cleanup-index", "hg38",
                    ]
                )
            self.assertIn("derive.json", str(ctx.exception))
            self.assertTrue(index_dir.exists())

    def test_altered_derived_reference_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _git_init(tmp_path)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            index_dir = indices_dir / "hg38"
            derived_dir = tmp_path / "derived"
            _write_realistic_cleanup_evidence(
                output_dir=output_dir, index_dir=index_dir, build="hg38", reconciliation_status="passed",
                derived_dir=derived_dir,
            )
            # Tamper with the derived reference AFTER derive.json recorded
            # its hash.
            (derived_dir / "hg38" / "reference.fna").write_text(">chr1\nTAMPERED\n")

            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(output_dir),
                        "--indices-dir", str(indices_dir),
                        "--derived-dir", str(derived_dir),
                        "--repo-root", str(tmp_path),
                        "--cleanup-index", "hg38",
                    ]
                )
            self.assertIn("derive evidence", str(ctx.exception))
            self.assertTrue(index_dir.exists())

    def test_altered_report_markdown_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _git_init(tmp_path)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            index_dir = indices_dir / "hg38"
            derived_dir = tmp_path / "derived"
            _write_realistic_cleanup_evidence(
                output_dir=output_dir, index_dir=index_dir, build="hg38", reconciliation_status="passed",
                derived_dir=derived_dir,
            )
            # The report Markdown was altered after provenance.json recorded
            # its hash (report.json/mappings.tsv.gz are untouched).
            (output_dir / "hg38" / "report.md").write_text("# tampered\n")

            from rbpbench.coordinates.runner import _verify_report_evidence_hashes

            violations = _verify_report_evidence_hashes(output_dir / "hg38", cfg=_cfg(), output_dir=output_dir)
            self.assertTrue(any("report_md" in v for v in violations))

            with self.assertRaises(SystemExit):
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(output_dir),
                        "--indices-dir", str(indices_dir),
                        "--derived-dir", str(derived_dir),
                        "--repo-root", str(tmp_path),
                        "--cleanup-index", "hg38",
                    ]
                )
            self.assertTrue(index_dir.exists())

    def test_resolve_git_repo_root_finds_the_real_repository(self):
        # This test file itself lives inside the real repository checkout.
        repo_root = resolve_git_repo_root(Path(__file__).resolve().parent)
        self.assertIsNotNone(repo_root)
        self.assertTrue((repo_root / ".git").exists())


class SelectionRecordWriteFailureTests(unittest.TestCase):
    """Transaction completion requirement: a failure while writing the
    atomic selection record itself (after every file in the candidate
    generation has already been produced) must discard that generation and
    leave the previous accepted selection completely untouched, for EVERY
    stage — download, derive, index, align, exact_match, report.
    """

    def _boom(self, *_args, **_kwargs):
        raise RuntimeError("simulated selection-record write failure")

    def test_index_selection_write_failure_discards_the_new_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA_FULL)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2_FULL)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 40 + "\n")
            manifest = json.loads(_write_reference_manifest(tmp_path / "manifest.json", build="hg38", reference=reference).read_text())
            index_dir = tmp_path / "indices" / "hg38"

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                first = stage_index(
                    _cfg(), build="hg38", index_dir=index_dir, allow_mapping=True, host_role="approved_mac",
                    threads=1, reference=reference, reference_manifest=manifest, dry_run=False,
                )
                self.assertTrue(first["executed"])
                original_record = json.loads((index_dir / "index.json").read_text())
                generations_before = set((index_dir / "generations").glob("*"))

                with mock.patch("rbpbench.coordinates.runner._guarded_write_record", side_effect=self._boom):
                    with self.assertRaises(RuntimeError):
                        stage_index(
                            _cfg(), build="hg38", index_dir=index_dir, allow_mapping=True, host_role="approved_mac",
                            threads=1, reference=reference, reference_manifest=manifest, dry_run=False,
                        )

            # Previous selection completely untouched.
            self.assertEqual(json.loads((index_dir / "index.json").read_text()), original_record)
            # The new (unselected) generation was discarded, not left behind.
            generations_after = set((index_dir / "generations").glob("*"))
            self.assertEqual(generations_before, generations_after)

    def test_align_selection_write_failure_discards_the_new_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA_FULL)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2_FULL)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 40 + "\n")
            manifest = json.loads(_write_reference_manifest(tmp_path / "manifest.json", build="hg38", reference=reference).read_text())
            reads = _write_reads(tmp_path / "reads.fasta")
            build_dir = tmp_path / "out" / "hg38"

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                with mock.patch("rbpbench.coordinates.runner._guarded_write_record", side_effect=self._boom):
                    with self.assertRaises(RuntimeError):
                        stage_align(
                            _cfg(), build="hg38", build_output_dir=build_dir, allow_mapping=True,
                            host_role="approved_mac", threads=1, reference=reference, reference_manifest=manifest,
                            reads_fasta=reads, dry_run=False,
                        )
            self.assertFalse((build_dir / "align.json").exists())
            self.assertFalse((build_dir / "generations").exists() and any((build_dir / "generations").glob("*")))

    def test_exact_match_selection_write_failure_discards_the_new_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 40 + "\n")
            manifest = json.loads(_write_reference_manifest(tmp_path / "manifest.json", build="hg38", reference=reference).read_text())
            reads = _write_reads(tmp_path / "reads.fasta")
            build_dir = tmp_path / "out" / "hg38"
            align_record = {
                "executed": True,
                "reference_sha256": manifest["sha256"],
                "reference_manifest_content_sha256": manifest_content_sha256(manifest),
                "sam_paths": {},
                "stderr_paths": {},
                "generation_digest": "align-digest",
            }

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                with mock.patch("rbpbench.coordinates.runner._guarded_write_record", side_effect=self._boom):
                    with self.assertRaises(RuntimeError):
                        stage_exact_match(
                            _cfg(), build="hg38", build_output_dir=build_dir, allow_mapping=True,
                            host_role="approved_mac", threads=1, reference=reference, reference_manifest=manifest,
                            reads_fasta=reads, align_record=align_record, dry_run=False,
                        )
            self.assertFalse((build_dir / "exact_match.json").exists())

    def test_report_selection_write_failure_discards_the_new_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp) / "hg38"
            sample = _tiny_sample()
            with mock.patch("rbpbench.coordinates.runner._guarded_write_record", side_effect=self._boom):
                with self.assertRaises(RuntimeError):
                    stage_report(
                        sample, cfg=_cfg(), build_output_dir=build_dir, expected_total=1,
                        expected_representative=1, expected_controls=0, build="hg38",
                        align_record={"executed": False}, exact_match_record={"executed": False},
                        reference=None, reference_manifest=None,
                    )
            self.assertFalse((build_dir / "report_state.json").exists())
            self.assertFalse((build_dir / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
