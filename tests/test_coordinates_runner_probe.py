"""Integration coverage for the B3A-A3 guarded ``probe`` stage
(``rbpbench.coordinates.runner.stage_probe``), through the actual runner
functions with fake (never real) bwa/minimap2/seqkit executables on PATH.

Every fixture here is tiny and synthetic. No test in this file opens the
real CSV, any real B2 FASTA, a real human reference/index, or any network
URL. Test names/docstrings map to the executor handoff's "Minimum
regression set" (docs/handoffs/001b_b3a_claude_executor_handoff.md), items
7, 8, 11, 12 (integration level), 14, 15, and 16.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.config import load_config
from rbpbench.coordinates.diskbudget import start_build_output_budget, start_ledger
from rbpbench.coordinates.runner import PROBE_OUTPUT_ALLOWANCE_GIB, stage_align, stage_index, stage_probe
from rbpbench.data.audit import sha256_file

from test_coordinates_runner import (
    FIXTURE_CONFIG,
    _FAKE_SEQKIT,
    _approved_host_context,
    _write_fake_executable,
)
from test_coordinates_b1_second_corrections import _FAKE_BWA_FULL, _FAKE_MINIMAP2_FULL

REPO_ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return load_config(FIXTURE_CONFIG)


# A reference with a clearly largest contig ("chr1", 80 nt, pure ACGT so a
# small window is trivially selectable) plus a shorter second contig
# ("chr2") so largest-contig selection is actually exercised, not merely
# assumed. Both fake mappers hardcode "chr1" as the mapped chrom regardless
# of reads content (see test_coordinates_runner.py/_FAKE_BWA/_FAKE_MINIMAP2's
# own docstring-equivalent comments), so the reference text itself does not
# need to be biologically meaningful.
_REFERENCE_TEXT = ">chr1\n" + ("ACGT" * 20) + "\n>chr2\n" + ("ACGT" * 5) + "\n"


def _write_reference_and_manifest(tmp_path: Path) -> tuple[Path, dict]:
    reference = tmp_path / "reference.fasta"
    reference.write_text(_REFERENCE_TEXT)
    manifest = {
        "build_id": "hg38",
        "assembly_accession": "TEST-hg38",
        "source_url": "https://example.invalid/reference.fa.gz",
        "contig_categories_included": ["chromosome"],
        "byte_size": reference.stat().st_size,
        "sha256": sha256_file(reference),
        "contigs": ["chr1", "chr2"],
        "contig_lengths": {"chr1": 80, "chr2": 20},
    }
    return reference, manifest


def _write_b2_fixtures(tmp_path: Path) -> tuple[Path, Path, str, str]:
    sample_fasta = tmp_path / "sample_sequences.fasta"
    sample_fasta.write_text(">s1\nACGTACGTAC\n>s2\nTTTTGGGGCC\n")
    control_fasta = tmp_path / "control_sequences.fasta"
    control_fasta.write_text(">control_s1\nGGGGCCCCAA\n")
    return sample_fasta, control_fasta, sha256_file(sample_fasta), sha256_file(control_fasta)


def _bin_dir_with_fake_tools(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_executable(bin_dir, "bwa", _FAKE_BWA_FULL)
    _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2_FULL)
    _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
    return bin_dir


class ProbeStageFixture:
    """Shared setup: a fully accepted (fake-tool) index generation for one
    tiny reference, reused across most tests in this file.
    """

    def _build(self, tmp_path: Path):
        reference, manifest = _write_reference_and_manifest(tmp_path)
        sample_fasta, control_fasta, sample_sha256, control_sha256 = _write_b2_fixtures(tmp_path)
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
            reference=reference, manifest=manifest, sample_fasta=sample_fasta, control_fasta=control_fasta,
            sample_sha256=sample_sha256, control_sha256=control_sha256, bin_dir=bin_dir, index_record=index_record,
        )

    def _run_probe(self, ctx: dict, build_output_dir: Path, **overrides):
        kwargs = dict(
            build="hg38",
            build_output_dir=build_output_dir,
            allow_mapping=True,
            host_role="approved_mac",
            reference=ctx["reference"],
            reference_manifest=ctx["manifest"],
            reference_manifest_raw_sha256=None,
            index_record=ctx["index_record"],
            sample_fasta=ctx["sample_fasta"],
            control_fasta=ctx["control_fasta"],
            sample_fasta_expected_sha256=ctx["sample_sha256"],
            control_fasta_expected_sha256=ctx["control_sha256"],
            dry_run=False,
            window_length=8,  # tiny fixture window, never the real 500 nt
        )
        kwargs.update(overrides)
        env = dict(os.environ, PATH=f"{ctx['bin_dir']}{os.pathsep}{os.environ.get('PATH', '')}")
        with mock.patch.dict(os.environ, env), _approved_host_context():
            return stage_probe(_cfg(), **kwargs)


class ProbeAuthorizationAndCheckpointTests(unittest.TestCase, ProbeStageFixture):
    """Item 7: probe dry run, authorization/checkpoint combinations."""

    def test_dry_run_is_an_absolute_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            record = self._run_probe(ctx, tmp_path / "out", dry_run=True)
            self.assertFalse(record["executed"])
            self.assertIn("--dry-run", record["skip_reason"])

    def test_missing_allow_mapping_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            record = self._run_probe(ctx, tmp_path / "out", allow_mapping=False)
            self.assertFalse(record["executed"])
            self.assertIn("--allow-mapping", record["skip_reason"])

    def test_wrong_host_role_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            record = self._run_probe(ctx, tmp_path / "out", host_role="dev_vm")
            self.assertFalse(record["executed"])
            self.assertIn("--host-role", record["skip_reason"])

    def test_successful_probe_produces_an_executed_immutable_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            record = self._run_probe(ctx, out_dir)
            self.assertTrue(record["executed"], record.get("skip_reason"))
            self.assertEqual(record["selected_contig"]["accession"], "chr1")  # the longer contig
            self.assertTrue(Path(record["sam_paths"]["bwa_mem"]).is_file())
            self.assertTrue(Path(record["sam_paths"]["minimap2_splice"]).is_file())
            self.assertTrue(Path(record["bed_path"]).is_file())
            self.assertTrue((out_dir / "probe.json").is_file())
            # Never writes align.json/exact_match.json/report_state.json.
            self.assertFalse((out_dir / "align.json").exists())
            self.assertFalse((out_dir / "exact_match.json").exists())
            self.assertFalse((out_dir / "report_state.json").exists())

    def test_protected_prior_executed_record_is_never_overwritten_by_an_unauthorized_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            first = self._run_probe(ctx, out_dir)
            self.assertTrue(first["executed"])

            with self.assertRaises(SystemExit):
                self._run_probe(ctx, out_dir, allow_mapping=False)  # plainly unauthorized retry

            still_on_disk = json.loads((out_dir / "probe.json").read_text())
            self.assertTrue(still_on_disk["executed"])
            self.assertEqual(still_on_disk["generation_digest"], first["generation_digest"])

    def test_candidate_interruption_discards_the_generation_and_preserves_prior_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            first = self._run_probe(ctx, out_dir)
            self.assertTrue(first["executed"])
            generations_before = set((out_dir / "generations").glob("*"))

            with mock.patch(
                "rbpbench.coordinates.runner.build_pattern_fasta", side_effect=RuntimeError("simulated interruption")
            ):
                with self.assertRaises(RuntimeError):
                    self._run_probe(ctx, out_dir)

            self.assertEqual(json.loads((out_dir / "probe.json").read_text())["generation_digest"], first["generation_digest"])
            generations_after = set((out_dir / "generations").glob("*"))
            self.assertEqual(generations_before, generations_after)

    def test_selection_record_write_failure_discards_the_new_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            first = self._run_probe(ctx, out_dir)
            self.assertTrue(first["executed"])
            generations_before = set((out_dir / "generations").glob("*"))

            def _boom(*_args, **_kwargs):
                raise RuntimeError("simulated selection-record write failure")

            with mock.patch("rbpbench.coordinates.runner._guarded_write_record", side_effect=_boom):
                with self.assertRaises(RuntimeError):
                    self._run_probe(ctx, out_dir)

            generations_after = set((out_dir / "generations").glob("*"))
            self.assertEqual(generations_before, generations_after)


class ProbeInputBindingTests(unittest.TestCase, ProbeStageFixture):
    """Item 8: missing/changed B2 inputs, invalid reference manifest,
    missing/foreign/stale/changed index generation.
    """

    def test_missing_sample_fasta_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            record = self._run_probe(ctx, tmp_path / "out", sample_fasta=None)
            self.assertFalse(record["executed"])
            self.assertIn("biological", record["skip_reason"])

    def test_changed_sample_fasta_hash_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            ctx["sample_fasta"].write_text(">tampered\nAAAA\n")  # bytes changed since sha256 was computed
            record = self._run_probe(ctx, tmp_path / "out")
            self.assertFalse(record["executed"])
            self.assertIn("B2 evidence", record["skip_reason"])

    def test_no_expected_b2_hash_supplied_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            record = self._run_probe(ctx, tmp_path / "out", sample_fasta_expected_sha256=None)
            self.assertFalse(record["executed"])

    def test_invalid_reference_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            bad_manifest = dict(ctx["manifest"])
            bad_manifest["sha256"] = "0" * 64  # no longer matches the real reference file
            record = self._run_probe(ctx, tmp_path / "out", reference_manifest=bad_manifest)
            self.assertFalse(record["executed"])
            self.assertIn("reference manifest invalid", record["skip_reason"])

    def test_missing_contig_lengths_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            manifest_without_lengths = {k: v for k, v in ctx["manifest"].items() if k != "contig_lengths"}
            record = self._run_probe(ctx, tmp_path / "out", reference_manifest=manifest_without_lengths)
            self.assertFalse(record["executed"])
            self.assertIn("contig_lengths", record["skip_reason"])

    def test_missing_index_record_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            record = self._run_probe(ctx, tmp_path / "out", index_record={"executed": False})
            self.assertFalse(record["executed"])
            self.assertIn("index generation", record["skip_reason"])

    def test_stale_index_bound_to_a_different_reference_is_refused(self):
        """Foreign/stale index: the accepted index.json claims a different
        reference_sha256 than the one this probe attempt is about to use.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            foreign_index_record = dict(ctx["index_record"])
            foreign_index_record["reference_sha256"] = "f" * 64
            record = self._run_probe(ctx, tmp_path / "out", index_record=foreign_index_record)
            self.assertFalse(record["executed"])
            self.assertIn("index generation", record["skip_reason"])

    def test_index_files_altered_since_acceptance_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            bwa_prefix = Path(ctx["index_record"]["bwa_index_prefix"])
            Path(str(bwa_prefix) + ".amb").write_bytes(b"tampered bytes, wrong hash now")
            record = self._run_probe(ctx, tmp_path / "out")
            self.assertFalse(record["executed"])
            self.assertIn("index generation", record["skip_reason"])


class ProbeMapperEvidenceTests(unittest.TestCase, ProbeStageFixture):
    """Item 11: mapper SAM parsing/unmapped/foreign-contig rejection."""

    def test_unmapped_smoke_query_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            unmapped_bwa = tmp_path / "bin2"
            unmapped_bwa.mkdir()
            shutil.copytree(ctx["bin_dir"], unmapped_bwa, dirs_exist_ok=True)
            # An "unmapped" fake bwa: emits FLAG=4 (unmapped) for every read
            # instead of a mapped record, for the `bwa mem` code path only
            # (index-building still works, reusing the accepted index above).
            (unmapped_bwa / "bwa").write_text(
                "#!/bin/bash\n"
                "if [ \"$#\" -le 0 ]; then echo 'Version: 0.7.19'; exit 0; fi\n"
                "if [ \"$1\" == \"index\" ]; then prefix=\"$3\"; for s in .amb .ann .bwt .pac .sa; do "
                "printf x > \"${prefix}${s}\"; done; exit 0; fi\n"
                "reads=\"${@: -1}\"\n"
                "awk '/^>/ { if (name!=\"\") print name \"\\t4\\t*\\t0\\t0\\t*\\t*\\t0\\t0\\t\" seq \"\\t*\"; "
                "name=substr($0,2); seq=\"\"; next } { seq = seq $0 } "
                "END { if (name!=\"\") print name \"\\t4\\t*\\t0\\t0\\t*\\t*\\t0\\t0\\t\" seq \"\\t*\" }' \"$reads\"\n"
            )
            (unmapped_bwa / "bwa").chmod(0o755)
            ctx["bin_dir"] = unmapped_bwa
            record = self._run_probe(ctx, tmp_path / "out")
            self.assertFalse(record["executed"])
            self.assertIn("smoke query", record["skip_reason"])

    def test_foreign_contig_mapping_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            foreign_bin = tmp_path / "bin_foreign"
            foreign_bin.mkdir()
            shutil.copytree(ctx["bin_dir"], foreign_bin, dirs_exist_ok=True)
            (foreign_bin / "bwa").write_text(
                "#!/bin/bash\n"
                "if [ \"$#\" -le 0 ]; then echo 'Version: 0.7.19'; exit 0; fi\n"
                "if [ \"$1\" == \"index\" ]; then prefix=\"$3\"; for s in .amb .ann .bwt .pac .sa; do "
                "printf x > \"${prefix}${s}\"; done; exit 0; fi\n"
                "reads=\"${@: -1}\"\n"
                "awk '/^>/ { if (name!=\"\") print name \"\\t0\\tchrFOREIGN\\t1\\t60\\t\" length(seq) \"M\\t*\\t0\\t0\\t\" "
                "seq \"\\t*\\tNM:i:0\\tAS:i:\" length(seq); name=substr($0,2); seq=\"\"; next } { seq = seq $0 } "
                "END { if (name!=\"\") print name \"\\t0\\tchrFOREIGN\\t1\\t60\\t\" length(seq) \"M\\t*\\t0\\t0\\t\" "
                "seq \"\\t*\\tNM:i:0\\tAS:i:\" length(seq) }' \"$reads\"\n"
            )
            (foreign_bin / "bwa").chmod(0o755)
            ctx["bin_dir"] = foreign_bin
            record = self._run_probe(ctx, tmp_path / "out")
            self.assertFalse(record["executed"])
            self.assertIn("foreign", record["skip_reason"].lower())


class ProbeBudgetAndRetentionTests(unittest.TestCase, ProbeStageFixture):
    """Item 14: live 1-GiB probe cap, 2-GiB projected check, downstream
    shared 4-GiB budget seeding. Item 15: selected-vs-ephemeral retention
    and provenance separation from B4 align/exact/report/combined state.
    """

    def test_projected_peak_check_blocks_probe_before_any_candidate_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            ledger = start_ledger(tmp_path)
            with mock.patch(
                "rbpbench.coordinates.runner.check_projected_peak",
                return_value=type("_R", (), {"ok": False, "violations": ("simulated ceiling breach",), "to_dict": lambda self: {}})(),
            ):
                with self.assertRaises(SystemExit):
                    self._run_probe(ctx, out_dir, disk_ledger=ledger)
            # No generation was ever created for this refused attempt.
            self.assertFalse((out_dir / "generations").exists())

    def test_accepted_bytes_never_exceed_the_one_gib_probe_sub_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            record = self._run_probe(ctx, tmp_path / "out")
            self.assertTrue(record["executed"])
            self.assertLessEqual(record["accepted_bytes"], PROBE_OUTPUT_ALLOWANCE_GIB * (1024**3))
            self.assertEqual(record["probe_output_allowance_bytes"], int(PROBE_OUTPUT_ALLOWANCE_GIB * (1024**3)))

    def test_accepted_bytes_are_seeded_into_the_shared_build_output_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            record = self._run_probe(ctx, out_dir)
            self.assertTrue(record["executed"])

            shared_budget = start_build_output_budget(total_allowance_gib=4.0)
            remaining_before = shared_budget.remaining_bytes
            shared_budget.accept(record["accepted_bytes"])
            self.assertEqual(shared_budget.remaining_bytes, remaining_before - record["accepted_bytes"])
            self.assertGreater(shared_budget.remaining_bytes, 0)  # still >=3 GiB left for B4

    def test_candidate_workspace_is_removed_but_selected_evidence_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            record = self._run_probe(ctx, out_dir)
            self.assertTrue(record["executed"])
            generation_dir = Path(record["sam_paths"]["bwa_mem"]).parent
            self.assertFalse((generation_dir / "candidate").exists())
            self.assertTrue(Path(record["sam_paths"]["bwa_mem"]).is_file())
            self.assertTrue(Path(record["sam_paths"]["minimap2_splice"]).is_file())
            self.assertTrue(Path(record["bed_path"]).is_file())

    def test_probe_evidence_is_kept_distinct_from_align_state(self):
        """provenance/record separation: probe.json is never merged into or
        mistaken for align.json/exact_match.json state.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = self._build(tmp_path)
            out_dir = tmp_path / "out"
            probe_record = self._run_probe(ctx, out_dir)
            self.assertTrue(probe_record["executed"])
            self.assertFalse((out_dir / "align.json").exists())

            sample_fasta = ctx["sample_fasta"]
            # Reuse the accepted B2 biological FASTA as the "reads" input for
            # a real align attempt too, proving align proceeds independently
            # and writes its own separate align.json without disturbing
            # probe.json.
            env = dict(os.environ, PATH=f"{ctx['bin_dir']}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                align_record = stage_align(
                    _cfg(), build="hg38", build_output_dir=out_dir, allow_mapping=True, host_role="approved_mac",
                    threads=1, reference=ctx["reference"], reference_manifest=ctx["manifest"], reads_fasta=sample_fasta,
                    dry_run=False, bwa_index_prefix=Path(ctx["index_record"]["bwa_index_prefix"]),
                    minimap2_index=Path(ctx["index_record"]["minimap2_index"]),
                )
            self.assertTrue(align_record["executed"], align_record.get("skip_reason"))
            still_probe = json.loads((out_dir / "probe.json").read_text())
            self.assertEqual(still_probe["generation_digest"], probe_record["generation_digest"])
            self.assertTrue((out_dir / "align.json").is_file())


if __name__ == "__main__":
    unittest.main()
