"""Regression coverage for the Task 001B checkpoint B3A FINAL correction.

Every test here targets exactly one of the three findings in
``docs/reviews/001b_b3a_correction_review.md`` (B3A-F1, B3A-F2, B3A-F3) and
demonstrably fails against commit ``bd1d671`` (the reviewed, pre-final-
correction implementation). Fixtures are tiny and synthetic throughout: the
real CSV/B2 FASTAs are never opened, no NCBI URL is ever requested, and no
human reference/index is built (B3A's authorization boundary), consistent
with the rest of the coordinate-runner test suite.

Pure fingerprint-input sensitivity (every one of B3A-F1's load-bearing
inputs, including command semantics, changes ``probe_fingerprint``'s output)
is already covered by
``test_coordinates_probe.ProbeFingerprintTests.test_deterministic_and_sensitive_to_every_input``
and is not duplicated here; this file adds the behavioral proof that was
actually missing -- that the accepted and restart-recomputed fingerprints
use the SAME representation, and that the real ``main()`` restart/skip
machinery honors that (skips only when truly unchanged, reruns otherwise).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.commands import canonical_probe_commands
from rbpbench.coordinates.diskbudget import BuildOutputBudget, DiskBudgetExceeded, start_build_output_budget
from rbpbench.coordinates.probe import probe_fingerprint
from rbpbench.coordinates.runner import main
from rbpbench.data.audit import sha256_file

from test_coordinates_runner import (
    FIXTURE_CONFIG,
    FIXTURE_CSV,
    FIXTURE_EXECUTION_SOURCES,
    _approved_host_context,
)
from test_coordinates_runner_probe import (
    ProbeStageFixture,
    _bin_dir_with_fake_tools,
    _write_b2_checkpoint,
)


class F1AcceptedVersusRestartFingerprintTests(unittest.TestCase, ProbeStageFixture):
    """B3A-F1: an accepted probe's own ``probe_fingerprint`` must equal a
    restart recomputation built from the SAME canonical (fixed-placeholder-
    path) command representation. Fails on ``bd1d671``, where the accepted
    fingerprint was built from the REAL executed argv (random generation/
    candidate-directory paths) and could never equal a restart's
    placeholder-based recomputation, even with nothing else changed.
    """

    def test_recomputed_canonical_fingerprint_matches_the_accepted_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            record = self._run_probe(ctx, tmp_path / "out")
            self.assertTrue(record["executed"], record.get("skip_reason"))

            canonical_bwa, canonical_mm2, canonical_seqkit = canonical_probe_commands(threads=1)
            evidence = record["b2_checkpoint_evidence"]
            resource = record["resource_evidence"]
            recomputed = probe_fingerprint(
                b2_manifest_sha256=evidence["manifest_sha256"],
                b2_sample_sha256=evidence["sample_fasta_sha256"],
                b2_control_sha256=evidence["control_fasta_sha256"],
                reference_sha256=record["reference_sha256"],
                reference_manifest_content_sha256=record["reference_manifest_content_sha256"],
                reference_manifest_raw_sha256=record["reference_manifest_raw_sha256"],
                index_generation_digest=record["upstream_index_generation_digest"],
                bwa_binary_sha256=resource["bwa_mem"]["binary"]["sha256"],
                minimap2_binary_sha256=resource["minimap2_splice"]["binary"]["sha256"],
                seqkit_binary_sha256=resource["seqkit_locate"]["binary"]["sha256"],
                bwa_binary_version=resource["bwa_mem"]["binary"]["version"],
                minimap2_binary_version=resource["minimap2_splice"]["binary"]["version"],
                seqkit_binary_version=resource["seqkit_locate"]["binary"]["version"],
                bwa_command=canonical_bwa,
                minimap2_command=canonical_mm2,
                seqkit_command=canonical_seqkit,
                git_commit=record["git_commit"],
                git_clean=record["git_clean"],
            )
            self.assertEqual(recomputed, record["probe_fingerprint"])

            # The REAL executed commands (random generation/candidate paths)
            # are still preserved separately in tool provenance -- never
            # lost, only no longer used as the fingerprint's own input.
            self.assertNotEqual(resource["bwa_mem"]["command"], canonical_bwa)
            self.assertIn(str(tmp_path), resource["bwa_mem"]["command"])


def _write_probe_capable_reference_and_manifest(tmp_path: Path) -> tuple[Path, Path]:
    """A reference big enough to clear the REAL 500-nt probe window (never
    overridden through ``main()``'s CLI wiring, unlike the direct
    ``stage_probe`` fixture seam's tiny ``window_length=8``).
    """
    chr1_body = "ACGT" * 150  # 600 nt
    chr2_body = "ACGT" * 5  # 20 nt
    reference = tmp_path / "reference.fasta"
    reference.write_text(f">chr1\n{chr1_body}\n>chr2\n{chr2_body}\n")
    manifest = {
        "build_id": "hg38",
        "assembly_accession": "TEST-hg38",
        "source_url": "https://example.invalid/reference.fa.gz",
        "contig_categories_included": ["chromosome"],
        "byte_size": reference.stat().st_size,
        "sha256": sha256_file(reference),
        "contigs": ["chr1", "chr2"],
        "contig_lengths": {"chr1": 600, "chr2": 20},
    }
    manifest_path = tmp_path / "hg38_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return reference, manifest_path


class F1RestartSkipViaMainTests(unittest.TestCase):
    """B3A-F1 mandatory regression: "a complete guarded success followed by
    an unchanged restart skip, proving no subprocess and no new generation
    occurs" plus "invalidation of that skip when a load-bearing fingerprint
    input changes" -- exercised through the REAL ``main()`` CLI restart-
    fingerprint/skip machinery (stage_probe itself has no skip logic of its
    own; the decision lives entirely in ``main()``'s stage loop). The core
    skip proof fails on ``bd1d671``: because the accepted/restart
    fingerprints could never agree there, a "restart" always re-executes
    real subprocesses instead of skipping.
    """

    def _common_args(self, *, output_dir: Path, indices_dir: Path, reference: Path, manifest_path: Path, b2_manifest_path: Path) -> list[str]:
        return [
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
            "--b2-manifest", str(b2_manifest_path),
        ]

    def _b2_constant_patches(self, b2_manifest_sha256: str):
        # B3A-R1: the frozen real-CLI trust-anchor constants are module-level
        # (never CLI-overridable); binding them to our tiny fixture B2
        # checkpoint here is what lets `main()` exercise its REAL probe
        # restart/skip code path without ever touching the real accepted
        # B2 checkpoint.
        return mock.patch.multiple(
            "rbpbench.coordinates.runner",
            B2_ACCEPTED_MANIFEST_SHA256=b2_manifest_sha256,
            B2_ACCEPTED_CHECKPOINT="001B-B2",
            B2_ACCEPTED_STATUS="passed",
            B2_REAL_BIOLOGICAL_COUNT=2,
            B2_REAL_CONTROL_COUNT=1,
        )

    def _setup(self, tmp_path: Path):
        output_dir = tmp_path / "out"
        indices_dir = tmp_path / "indices"
        reference, manifest_path = _write_probe_capable_reference_and_manifest(tmp_path)
        b2 = _write_b2_checkpoint(tmp_path)
        bin_dir = _bin_dir_with_fake_tools(tmp_path)
        common = self._common_args(
            output_dir=output_dir, indices_dir=indices_dir, reference=reference,
            manifest_path=manifest_path, b2_manifest_path=b2["manifest_path"],
        )
        return dict(output_dir=output_dir, indices_dir=indices_dir, b2=b2, bin_dir=bin_dir, common=common)

    def test_unchanged_restart_is_skipped_without_subprocess_or_new_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._setup(tmp_path)
            env = dict(os.environ, PATH=f"{ctx['bin_dir']}{os.pathsep}{os.environ.get('PATH', '')}")
            build_dir = ctx["output_dir"] / "hg38"
            with mock.patch.dict(os.environ, env), _approved_host_context(), self._b2_constant_patches(
                ctx["b2"]["manifest_sha256"]
            ), mock.patch("rbpbench.coordinates.runner.git_is_clean", return_value=True), mock.patch(
                "rbpbench.coordinates.runner.current_git_commit", return_value="0" * 40
            ):
                main([*ctx["common"], "--stage", "index"])
                main([*ctx["common"], "--stage", "probe"])

                probe_record = json.loads((build_dir / "probe.json").read_text())
                self.assertTrue(probe_record["executed"], probe_record.get("skip_reason"))
                generations_before = set((build_dir / "generations").glob("*"))
                probe_json_before = (build_dir / "probe.json").read_text()

                with mock.patch(
                    "rbpbench.coordinates.runner.run_tool_with_provenance",
                    side_effect=AssertionError("no subprocess must run on an unchanged probe restart skip"),
                ):
                    main([*ctx["common"], "--stage", "probe"])

                generations_after = set((build_dir / "generations").glob("*"))
                self.assertEqual(generations_before, generations_after)
                self.assertEqual((build_dir / "probe.json").read_text(), probe_json_before)

    def test_git_commit_change_forces_a_real_rerun_not_a_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._setup(tmp_path)
            env = dict(os.environ, PATH=f"{ctx['bin_dir']}{os.pathsep}{os.environ.get('PATH', '')}")
            build_dir = ctx["output_dir"] / "hg38"
            with mock.patch.dict(os.environ, env), _approved_host_context(), self._b2_constant_patches(
                ctx["b2"]["manifest_sha256"]
            ):
                with mock.patch("rbpbench.coordinates.runner.git_is_clean", return_value=True), mock.patch(
                    "rbpbench.coordinates.runner.current_git_commit", return_value="0" * 40
                ):
                    main([*ctx["common"], "--stage", "index"])
                    main([*ctx["common"], "--stage", "probe"])
                first = json.loads((build_dir / "probe.json").read_text())
                self.assertTrue(first["executed"])

                with mock.patch("rbpbench.coordinates.runner.git_is_clean", return_value=True), mock.patch(
                    "rbpbench.coordinates.runner.current_git_commit", return_value="1" * 40
                ):
                    main([*ctx["common"], "--stage", "probe"])
                second = json.loads((build_dir / "probe.json").read_text())
                self.assertTrue(second["executed"])
                self.assertNotEqual(second["generation_digest"], first["generation_digest"])
                self.assertEqual(second["git_commit"], "1" * 40)

    def test_bwa_binary_identity_change_forces_a_real_rerun_not_a_skip(self):
        """A binary whose SHA-256 changed (its resolved executable file's
        bytes differ) while its self-reported ``--version`` string stays
        pinned/unchanged must still force a rerun -- binary IDENTITY, not
        merely the declared version string, is a load-bearing fingerprint
        input.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._setup(tmp_path)
            env = dict(os.environ, PATH=f"{ctx['bin_dir']}{os.pathsep}{os.environ.get('PATH', '')}")
            build_dir = ctx["output_dir"] / "hg38"
            with mock.patch.dict(os.environ, env), _approved_host_context(), self._b2_constant_patches(
                ctx["b2"]["manifest_sha256"]
            ), mock.patch("rbpbench.coordinates.runner.git_is_clean", return_value=True), mock.patch(
                "rbpbench.coordinates.runner.current_git_commit", return_value="0" * 40
            ):
                main([*ctx["common"], "--stage", "index"])
                main([*ctx["common"], "--stage", "probe"])
                first = json.loads((build_dir / "probe.json").read_text())
                self.assertTrue(first["executed"])

                # Same declared version ("Version: 0.7.19"), different file
                # bytes (harmless trailing comment) -- a different resolved
                # binary sha256, never touching the declared/pinned version.
                bwa_path = ctx["bin_dir"] / "bwa"
                bwa_path.write_text(bwa_path.read_text() + "\n# harmless byte-identity-changing comment\n")

                main([*ctx["common"], "--stage", "probe"])
                second = json.loads((build_dir / "probe.json").read_text())
                self.assertTrue(second["executed"], second.get("skip_reason"))
                self.assertNotEqual(second["generation_digest"], first["generation_digest"])


class F2SharedBudgetLiveChargingTests(unittest.TestCase, ProbeStageFixture):
    """B3A-F2: the shared build_budget must be decremented IMMEDIATELY after
    each probe writer (bwa/minimap2/seqkit), with every prior RETAINED
    probe byte seeded into it before the first new writer -- never charged
    only once, cumulatively, at completion. Every case here fails on
    ``bd1d671``.
    """

    def test_three_individually_sublimit_writers_cannot_together_exceed_the_shared_budget(self):
        """B3A-F2's exact reproduction shape: three writers each
        individually under a cap, whose SUM exceeds the shared remaining
        allowance, must be impossible to all accept.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            measured = self._run_probe(ctx, tmp_path / "measure")
            self.assertTrue(measured["executed"], measured.get("skip_reason"))
            bwa_bytes = (
                Path(measured["sam_paths"]["bwa_mem"]).stat().st_size
                + Path(measured["stderr_paths"]["bwa_mem"]).stat().st_size
            )
            mm2_bytes = (
                Path(measured["sam_paths"]["minimap2_splice"]).stat().st_size
                + Path(measured["stderr_paths"]["minimap2_splice"]).stat().st_size
            )
            seqkit_bytes = (
                Path(measured["bed_path"]).stat().st_size
                + Path(measured["stderr_paths"]["seqkit_locate"]).stat().st_size
            )
            total = bwa_bytes + mm2_bytes + seqkit_bytes
            max_single = max(bwa_bytes, mm2_bytes, seqkit_bytes)
            allowance = total - 1
            self.assertGreater(
                allowance, max_single, "fixture writers are not individually sub-limit for this allowance"
            )

            budget = BuildOutputBudget(total_allowance_bytes=allowance, accepted_bytes=0)
            with self.assertRaises(DiskBudgetExceeded):
                self._run_probe(ctx, tmp_path / "out", build_budget=budget)
            # The rejected attempt left no accepted generation behind.
            self.assertEqual(list((tmp_path / "out" / "generations").glob("*")), [])

    def test_retry_where_prior_retained_plus_other_accepted_leave_insufficient_room(self):
        """A retry's own new generation must be capped by what remains
        after BOTH this probe's own prior retained bytes (never deleted --
        B3A-R4) AND every other stage's already-accepted bytes for this
        build are already counted against the shared allowance.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            first = self._run_probe(ctx, out_dir)
            self.assertTrue(first["executed"])
            prior_retained_bytes = first["accepted_bytes"]
            new_generation_bytes_estimate = first["new_generation_bytes"]

            other_accepted_build_outputs = 7  # e.g. align/exact_match/report already accepted this many bytes
            budget_total = other_accepted_build_outputs + prior_retained_bytes + new_generation_bytes_estimate - 1
            budget = BuildOutputBudget(total_allowance_bytes=budget_total, accepted_bytes=other_accepted_build_outputs)

            with self.assertRaises(DiskBudgetExceeded):
                self._run_probe(ctx, out_dir, build_budget=budget)
            # The retry's failed generation was discarded; only the original
            # accepted generation's record remains on disk.
            still_on_disk = json.loads((out_dir / "probe.json").read_text())
            self.assertEqual(still_on_disk["generation_digest"], first["generation_digest"])

    def test_successful_retry_charges_shared_budget_exactly_once_per_writer_and_seed(self):
        """A successful retry must charge the shared budget exactly 4 times:
        the prior-retained-bytes seed, then bwa, then minimap2, then seqkit
        -- never a 5th cumulative "charge everything again at the end" call
        (the exact ``bd1d671`` defect), and never fewer than the three live
        per-writer charges either.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            first = self._run_probe(ctx, out_dir)
            self.assertTrue(first["executed"])

            budget = start_build_output_budget(total_allowance_gib=4.0)
            calls: list[int] = []
            original_accept = budget.accept

            def _tracking_accept(num_bytes: int) -> None:
                calls.append(num_bytes)
                original_accept(num_bytes)

            budget.accept = _tracking_accept

            second = self._run_probe(ctx, out_dir, build_budget=budget)
            self.assertTrue(second["executed"], second.get("skip_reason"))

            self.assertEqual(len(calls), 4)
            self.assertEqual(calls[0], first["accepted_bytes"])  # the prior-retained-bytes seed, charged first
            self.assertEqual(sum(calls), second["accepted_bytes"])
            self.assertEqual(budget.accepted_bytes, second["accepted_bytes"])


class F3RunnerLevelContigLengthValidationTests(unittest.TestCase, ProbeStageFixture):
    """B3A-F3, exercised through the real ``stage_probe`` wiring (never just
    the pure :func:`rbpbench.coordinates.probe.scan_reference_contig_lengths`
    function) -- complements the pure-function coverage in
    ``test_coordinates_probe.ScanReferenceContigLengthsTests``.
    """

    def _build_with_manifest(self, tmp_path: Path, manifest: dict, reference: Path):
        from rbpbench.coordinates.runner import stage_index

        from test_coordinates_runner_probe import _cfg

        b2 = _write_b2_checkpoint(tmp_path)
        bin_dir = _bin_dir_with_fake_tools(tmp_path)
        index_dir = tmp_path / "indices" / "hg38"
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
        with mock.patch.dict(os.environ, env), _approved_host_context():
            index_record = stage_index(
                _cfg(), build="hg38", index_dir=index_dir, allow_mapping=True, host_role="approved_mac",
                threads=1, reference=reference, reference_manifest=manifest, dry_run=False,
            )
        assert index_record["executed"], index_record
        return dict(
            reference=reference, manifest=manifest, bin_dir=bin_dir, index_record=index_record,
            b2_manifest_path=b2["manifest_path"], b2_manifest_sha256=b2["manifest_sha256"],
            sample_fasta=b2["sample_fasta"], control_fasta=b2["control_fasta"],
        )

    def test_three_contig_redistribution_between_non_largest_contigs_is_refused(self):
        """The exact B3A-F3 reproduction: with three contigs, bases
        redistributed between the two NON-largest contigs preserve the same
        keys, positivity, grand total, AND largest-contig choice -- only a
        genuine per-accession scan (never a total-only one) catches it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fasta"
            chr1_body = "ACGT" * 20  # 80 (largest, real+declared agree)
            chr2_body = "A" * 15  # real 15
            chr3_body = "C" * 5  # real 5
            reference.write_text(f">chr1\n{chr1_body}\n>chr2\n{chr2_body}\n>chr3\n{chr3_body}\n")
            manifest = {
                "build_id": "hg38",
                "assembly_accession": "TEST-hg38",
                "source_url": "https://example.invalid/reference.fa.gz",
                "contig_categories_included": ["chromosome"],
                "byte_size": reference.stat().st_size,
                "sha256": sha256_file(reference),
                "contigs": ["chr1", "chr2", "chr3"],
                # Falsified: chr2/chr3 swapped (5/15 instead of the real
                # 15/5) -- same keys, same total (100), same largest
                # contig (chr1) as the real per-accession lengths.
                "contig_lengths": {"chr1": 80, "chr2": 5, "chr3": 15},
            }
            ctx = self._build_with_manifest(tmp_path, manifest, reference)
            record = self._run_probe(ctx, tmp_path / "out")
            self.assertFalse(record["executed"])
            self.assertIn("contig_lengths validation failed", record["skip_reason"])
            self.assertIn("do not exactly equal accepted", record["skip_reason"])

    def test_duplicate_fasta_header_in_the_reference_is_refused(self):
        """A trailing, EMPTY duplicate ``>chr1`` header contributes zero
        bases, so the grand total, the keys, AND the extracted-contig
        length (``extract_contig_streaming`` already stops at the next
        header, regardless of whether its accession matches) all still
        agree with a declared ``contig_lengths`` of 80 -- a total-only
        check (as on ``bd1d671``) is fully satisfied end-to-end and the
        duplicate header is silently accepted; only a genuine per-accession
        scan that rejects a repeated accession catches it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "ACGT" * 20 + "\n>chr1\n")
            manifest = {
                "build_id": "hg38",
                "assembly_accession": "TEST-hg38",
                "source_url": "https://example.invalid/reference.fa.gz",
                "contig_categories_included": ["chromosome"],
                "byte_size": reference.stat().st_size,
                "sha256": sha256_file(reference),
                "contigs": ["chr1"],
                "contig_lengths": {"chr1": 80},
            }
            ctx = self._build_with_manifest(tmp_path, manifest, reference)
            record = self._run_probe(ctx, tmp_path / "out")
            self.assertFalse(record["executed"])
            self.assertIn("reference FASTA scan failed", record["skip_reason"])
            self.assertIn("duplicate", record["skip_reason"].lower())


if __name__ == "__main__":
    unittest.main()
