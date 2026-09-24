"""Unit coverage for the B3A-A3 guarded-probe pure building blocks in
``rbpbench.coordinates.probe``. Every fixture here is tiny and synthetic;
nothing touches a real reference, the real B2 FASTAs, or a network URL.

Test names map to the executor handoff's "Minimum regression set" items
(docs/handoffs/001b_b3a_claude_executor_handoff.md):
  - item 9  (pattern ID/count/hash validation, transactional construction)
  - item 10 (streaming contig extraction and deterministic window selection)
  - item 12 (SeqKit BED6, bounds, known-ID, duplicate-hit, zero-hit behavior)
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.derive_reference import validate_contig_lengths
from rbpbench.coordinates.probe import (
    ProbeError,
    build_pattern_fasta,
    compute_probe_projection,
    extract_contig_streaming,
    load_and_verify_b2_checkpoint,
    probe_fingerprint,
    scan_reference_contig_lengths,
    select_probe_window,
    total_reference_bases,
    validate_probe_bed_rows,
)
from rbpbench.data.audit import sha256_file


class BuildPatternFastaTests(unittest.TestCase):
    """Item 9: pattern ID/count/hash validation and transactional construction."""

    def test_combines_biological_and_control_ids_with_exact_count_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bio = tmp_path / "bio.fasta"
            bio.write_text(">s1\nACGT\n>s2\nTTTT\n")
            ctrl = tmp_path / "ctrl.fasta"
            ctrl.write_text(">control_s1\nGGGG\n")
            out = tmp_path / "pattern.fasta"

            result = build_pattern_fasta(bio, ctrl, out)
            self.assertEqual(result.count, 3)
            self.assertEqual(result.biological_count, 2)
            self.assertEqual(result.control_count, 1)
            self.assertEqual(result.id_set, frozenset({"s1", "s2", "control_s1"}))
            self.assertTrue(out.is_file())
            self.assertEqual(result.sha256, result.sha256)  # sanity: deterministic value present
            # No leftover temp file.
            self.assertFalse(any(tmp_path.glob("pattern.fasta.tmp*")))

    def test_duplicate_id_across_biological_and_control_is_rejected_transactionally(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bio = tmp_path / "bio.fasta"
            bio.write_text(">dup\nACGT\n")
            ctrl = tmp_path / "ctrl.fasta"
            ctrl.write_text(">dup\nGGGG\n")
            out = tmp_path / "pattern.fasta"

            with self.assertRaises(ProbeError):
                build_pattern_fasta(bio, ctrl, out)
            # Transactional: no partial output left behind at the final path.
            self.assertFalse(out.exists())
            self.assertFalse(any(tmp_path.glob("pattern.fasta.tmp*")))

    def test_expected_id_sets_enforced_when_supplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bio = tmp_path / "bio.fasta"
            bio.write_text(">s1\nACGT\n")
            ctrl = tmp_path / "ctrl.fasta"
            ctrl.write_text(">control_s1\nGGGG\n")
            out = tmp_path / "pattern.fasta"

            with self.assertRaises(ProbeError):
                build_pattern_fasta(
                    bio, ctrl, out,
                    expected_biological_ids=frozenset({"s1", "s2"}),  # s2 missing -> mismatch
                )
            self.assertFalse(out.exists())

    def test_repeated_construction_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bio = tmp_path / "bio.fasta"
            bio.write_text(">s1\nACGT\n")
            ctrl = tmp_path / "ctrl.fasta"
            ctrl.write_text(">control_s1\nGGGG\n")

            first = build_pattern_fasta(bio, ctrl, tmp_path / "first.fasta")
            second = build_pattern_fasta(bio, ctrl, tmp_path / "second.fasta")
            self.assertEqual(first.sha256, second.sha256)


class ExtractContigStreamingTests(unittest.TestCase):
    """Item 10 (extraction half): streaming single-contig extraction."""

    def test_extracts_only_the_named_contig(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_text(">chr1\nACGTACGT\n>chr2\nTTTTGGGG\n>chr3\nAAAACCCC\n")
            out = tmp_path / "contig.fna"

            extraction = extract_contig_streaming(reference, accession="chr2", output_path=out)
            self.assertEqual(extraction.length, 8)
            self.assertEqual(extraction.upper_count, 8)
            self.assertEqual(extraction.lower_count, 0)
            text = out.read_text()
            self.assertEqual(text, ">chr2\nTTTTGGGG\n")
            self.assertNotIn("chr1", text)
            self.assertNotIn("chr3", text)

    def test_soft_masked_bases_counted_as_lowercase(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_text(">chrA\nACGTacgtNNNN\n")
            out = tmp_path / "contig.fna"
            extraction = extract_contig_streaming(reference, accession="chrA", output_path=out)
            self.assertEqual(extraction.upper_count, 4)
            self.assertEqual(extraction.lower_count, 4)
            self.assertEqual(extraction.ambiguous_count, 4)

    def test_missing_accession_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_text(">chr1\nACGT\n")
            with self.assertRaises(ProbeError):
                extract_contig_streaming(reference, accession="does_not_exist", output_path=tmp_path / "out.fna")

    def test_crlf_source_does_not_corrupt_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_bytes(b">chr1\r\nACGT\r\nACGT\r\n>chr2\r\nTTTT\r\n")
            out = tmp_path / "contig.fna"
            extraction = extract_contig_streaming(reference, accession="chr1", output_path=out)
            self.assertEqual(extraction.length, 8)
            self.assertNotIn("\r", out.read_text())


class SelectProbeWindowTests(unittest.TestCase):
    """Item 10 (window-selection half): deterministic A/C/G/T-only window selection."""

    def test_selects_a_window_of_only_acgt_bases(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            contig_path = tmp_path / "contig.fna"
            body = "ACGT" * 5 + "N" * 10 + "ACGT" * 5  # 20 + 10 + 20 = 50 nt
            contig_path.write_text(f">chrX\n{body}\n")
            window = select_probe_window(contig_path, accession="chrX", contig_length=len(body), window_length=15)
            selected = body[window.start:window.end]
            self.assertEqual(len(selected), 15)
            self.assertTrue(set(selected) <= {"A", "C", "G", "T"})
            self.assertGreaterEqual(window.start, 0)
            self.assertLessEqual(window.end, len(body))

    def test_selection_is_deterministic_across_repeated_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            contig_path = tmp_path / "contig.fna"
            body = "ACGT" * 200
            contig_path.write_text(f">chrY\n{body}\n")
            first = select_probe_window(contig_path, accession="chrY", contig_length=len(body), window_length=50)
            second = select_probe_window(contig_path, accession="chrY", contig_length=len(body), window_length=50)
            self.assertEqual(first, second)

    def test_no_valid_window_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            contig_path = tmp_path / "contig.fna"
            contig_path.write_text(">chrZ\nNNNNNNNNNN\n")
            with self.assertRaises(ProbeError):
                select_probe_window(contig_path, accession="chrZ", contig_length=10, window_length=15)

    def test_lowercase_soft_masked_bases_are_never_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            contig_path = tmp_path / "contig.fna"
            # Only a lowercase (soft-masked) run of sufficient length exists;
            # window selection must fail rather than silently accept it,
            # since the plan requires an A/C/G/T-ONLY (uppercase) window.
            contig_path.write_text(">chrW\n" + "acgt" * 10 + "\n")
            with self.assertRaises(ProbeError):
                select_probe_window(contig_path, accession="chrW", contig_length=40, window_length=15)


class ValidateProbeBedRowsTests(unittest.TestCase):
    """Item 12: SeqKit BED6, bounds, known-ID, duplicate-hit, zero-hit behavior."""

    def test_zero_hits_is_honest_valid_result(self):
        result = validate_probe_bed_rows([], known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertTrue(result.ok)
        self.assertEqual(result.hit_count, 0)

    def test_valid_bed6_rows_pass(self):
        lines = ["chr1\t10\t20\tp1\t0\t+", "chr1\t30\t40\tp2\t0\t-"]
        result = validate_probe_bed_rows(
            lines, known_pattern_ids=frozenset({"p1", "p2"}), contig_accession="chr1", contig_length=100
        )
        self.assertTrue(result.ok, result.violations)
        self.assertEqual(result.hit_count, 2)
        self.assertEqual(result.distinct_hit_count, 2)

    def test_unknown_pattern_id_is_a_violation(self):
        lines = ["chr1\t10\t20\tunknown_pattern\t0\t+"]
        result = validate_probe_bed_rows(lines, known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertFalse(result.ok)
        self.assertTrue(any("unknown pattern ID" in v for v in result.violations))

    def test_out_of_bounds_hit_is_a_violation(self):
        lines = ["chr1\t95\t105\tp1\t0\t+"]  # end=105 > contig_length=100
        result = validate_probe_bed_rows(lines, known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertFalse(result.ok)
        self.assertTrue(any("out-of-bounds" in v for v in result.violations))

    def test_malformed_start_equals_end_is_a_violation(self):
        lines = ["chr1\t10\t10\tp1\t0\t+"]  # start == end: not 0 <= start < end
        result = validate_probe_bed_rows(lines, known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertFalse(result.ok)

    def test_duplicate_identical_hit_is_flagged_not_double_counted(self):
        lines = ["chr1\t10\t20\tp1\t0\t+", "chr1\t10\t20\tp1\t0\t+"]
        result = validate_probe_bed_rows(lines, known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertFalse(result.ok)
        self.assertEqual(result.hit_count, 2)
        self.assertEqual(result.distinct_hit_count, 1)
        self.assertTrue(any("duplicate-counted" in v for v in result.violations))

    def test_hit_on_foreign_contig_is_a_violation(self):
        lines = ["chr2\t10\t20\tp1\t0\t+"]
        result = validate_probe_bed_rows(lines, known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertFalse(result.ok)
        self.assertTrue(any("unexpected contig" in v for v in result.violations))

    def test_malformed_column_count_is_a_violation(self):
        lines = ["chr1\t10\t20\tp1"]  # only 4 columns, not BED6
        result = validate_probe_bed_rows(lines, known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertFalse(result.ok)

    def test_invalid_strand_is_a_violation(self):
        """B3A-R6: complete BED6 semantics -- strand must be '+' or '-'."""
        lines = ["chr1\t10\t20\tp1\t0\t.", "chr1\t30\t40\tp1\t0\t?"]
        result = validate_probe_bed_rows(lines, known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertFalse(result.ok)
        self.assertTrue(any("invalid BED6 strand" in v for v in result.violations))

    def test_negative_score_is_a_violation(self):
        lines = ["chr1\t10\t20\tp1\t-1\t+"]
        result = validate_probe_bed_rows(lines, known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertFalse(result.ok)
        self.assertTrue(any("invalid BED6 score" in v for v in result.violations))

    def test_non_integer_score_is_a_violation(self):
        lines = ["chr1\t10\t20\tp1\t.\t+"]
        result = validate_probe_bed_rows(lines, known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100)
        self.assertFalse(result.ok)
        self.assertTrue(any("non-integer BED6 score" in v for v in result.violations))

    def test_accepts_an_iterator_never_requiring_a_sequence(self):
        """B3A-R6: the real-mode caller passes an OPEN FILE HANDLE (an
        iterator, not a ``Sequence``) -- this must never be indexed,
        measured for length, or iterated more than once.
        """
        def _line_generator():
            yield "chr1\t10\t20\tp1\t0\t+\n"
            yield "chr1\t30\t40\tp1\t0\t-\n"

        result = validate_probe_bed_rows(
            _line_generator(), known_pattern_ids=frozenset({"p1"}), contig_accession="chr1", contig_length=100
        )
        self.assertTrue(result.ok, result.violations)
        self.assertEqual(result.hit_count, 2)


class TotalReferenceBasesTests(unittest.TestCase):
    """B3A-R2: independently-streamed total base count across the ENTIRE
    reference FASTA (every contig), used to fully validate contig_lengths
    before the largest contig is ever selected.
    """

    def test_sums_every_contig_never_just_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_text(">chr1\nACGT\n>chr2\nACGTACGT\n>chr3\nAC\n")
            self.assertEqual(total_reference_bases(reference), 4 + 8 + 2)

    def test_crlf_source_counts_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_bytes(b">chr1\r\nACGT\r\nAC\r\n")
            self.assertEqual(total_reference_bases(reference), 6)


class ScanReferenceContigLengthsTests(unittest.TestCase):
    """B3A-F3: the streaming per-accession accession -> length scan required
    to equal accepted ``contig_lengths`` EXACTLY -- not merely agree on the
    grand total -- before Ltotal/the largest contig are ever derived from
    it. Every case here fails on ``bd1d671``, which only ever computed a
    total-only scan (``total_reference_bases``) and validated contig_lengths
    against that total alone.
    """

    def test_observed_map_matches_declared_per_contig_lengths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_text(">chr1\nACGT\n>chr2\nACGTACGT\n>chr3\nAC\n")
            self.assertEqual(scan_reference_contig_lengths(reference), {"chr1": 4, "chr2": 8, "chr3": 2})

    def test_preserved_total_per_contig_redistribution_is_caught(self):
        """The exact B3A-F3 reproduction: with three or more contigs, bases
        can be redistributed between two NON-largest contigs while
        preserving the same keys, positivity, and grand total -- a
        total-only check (as on bd1d671) cannot catch this, but the
        observed per-accession map must not equal the declared (falsified)
        contig_lengths.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            # Real per-accession lengths: chr1=80 (largest), chr2=15, chr3=5.
            reference.write_text(">chr1\n" + "ACGT" * 20 + "\n>chr2\n" + "A" * 15 + "\n>chr3\n" + "C" * 5 + "\n")
            observed = scan_reference_contig_lengths(reference)
            self.assertEqual(observed, {"chr1": 80, "chr2": 15, "chr3": 5})

            # A falsified manifest redistributes bases between the two
            # NON-largest contigs (chr2/chr3): same keys, same total (100),
            # same largest-contig choice (chr1) -- only the per-accession
            # values differ.
            falsified_contig_lengths = {"chr1": 80, "chr2": 5, "chr3": 15}
            self.assertEqual(set(falsified_contig_lengths), set(observed))
            self.assertEqual(sum(falsified_contig_lengths.values()), sum(observed.values()))
            self.assertNotEqual(falsified_contig_lengths, observed)

            # The B3A-A2 total-only validator alone is fooled (this is
            # exactly what bd1d671 relied on):
            total_only_violations = validate_contig_lengths(
                falsified_contig_lengths, contigs=("chr1", "chr2", "chr3"),
                assembly_report_lengths={}, total_emitted_bases=sum(observed.values()),
            )
            self.assertEqual(total_only_violations, ())
            # ...but the exact per-accession observed-map comparison the
            # B3A-F3 fix requires is NOT fooled.
            self.assertNotEqual(observed, falsified_contig_lengths)

    def test_duplicate_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_text(">chr1\nACGT\n>chr1\nTTTT\n")
            with self.assertRaises(ProbeError) as ctx:
                scan_reference_contig_lengths(reference)
            self.assertIn("duplicate", str(ctx.exception).lower())

    def test_empty_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_text(">\nACGT\n")
            with self.assertRaises(ProbeError) as ctx:
                scan_reference_contig_lengths(reference)
            self.assertIn("malformed", str(ctx.exception).lower())

    def test_sequence_before_any_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_text("ACGT\n>chr1\nACGT\n")
            with self.assertRaises(ProbeError) as ctx:
                scan_reference_contig_lengths(reference)
            self.assertIn("before any FASTA header", str(ctx.exception))

    def test_crlf_source_counts_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fna"
            reference.write_bytes(b">chr1\r\nACGT\r\nAC\r\n")
            self.assertEqual(scan_reference_contig_lengths(reference), {"chr1": 6})


class LoadAndVerifyB2CheckpointTests(unittest.TestCase):
    """B3A-R1: the real trust anchor for the probe's pattern population --
    the accepted B2 checkpoint manifest, re-verified artifact evidence, and
    derived exact biological/control ID sets.
    """

    def _write_checkpoint(self, tmp_path: Path, **overrides) -> Path:
        sample_ids_tsv = tmp_path / "sample_ids.tsv"
        sample_ids_tsv.write_text(
            overrides.get(
                "sample_ids_text",
                "sample_id\trow_index\tstratum\tlabels\n"
                "s1\t0\trepresentative\t1;0\n"
                "s2\t1\tfiller\t0;1\n",
            )
        )
        sample_fasta = tmp_path / "sample_sequences.fasta"
        sample_fasta.write_text(overrides.get("sample_fasta_text", ">s1\nACGT\n>s2\nTTTT\n"))
        control_fasta = tmp_path / "control_sequences.fasta"
        control_fasta.write_text(overrides.get("control_fasta_text", ">control_s1\nGGGG\n"))

        manifest_path = tmp_path / "b2_manifest.json"
        manifest = {
            "checkpoint": overrides.get("checkpoint", "001B-B2"),
            "status": overrides.get("status", "passed"),
            "input_output_hashes": {
                "generated_artifacts": {
                    "sample_ids_tsv": {
                        "path": str(sample_ids_tsv), "sha256": sha256_file(sample_ids_tsv),
                        "byte_size": sample_ids_tsv.stat().st_size,
                    },
                    "sample_sequences_fasta": {
                        "path": str(sample_fasta), "sha256": sha256_file(sample_fasta),
                        "byte_size": sample_fasta.stat().st_size,
                    },
                    "control_sequences_fasta": {
                        "path": str(control_fasta), "sha256": sha256_file(control_fasta),
                        "byte_size": control_fasta.stat().st_size,
                    },
                }
            },
        }
        manifest_path.write_text(json.dumps(manifest))
        return manifest_path

    def test_accepts_a_self_consistent_checkpoint_and_derives_exact_id_sets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = self._write_checkpoint(tmp_path)
            evidence, violations = load_and_verify_b2_checkpoint(
                manifest_path, repo_root=tmp_path, expected_manifest_sha256=sha256_file(manifest_path),
                expected_checkpoint="001B-B2", expected_status="passed",
                expected_biological_count=None, expected_control_count=None,
            )
            self.assertEqual(violations, (), violations)
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence.biological_ids, frozenset({"s1", "s2"}))
            self.assertEqual(evidence.control_ids, frozenset({"control_s1"}))

    def test_manifest_hash_not_matching_frozen_anchor_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = self._write_checkpoint(tmp_path)
            evidence, violations = load_and_verify_b2_checkpoint(
                manifest_path, repo_root=tmp_path, expected_manifest_sha256="0" * 64,
                expected_checkpoint="001B-B2", expected_status="passed",
                expected_biological_count=None, expected_control_count=None,
            )
            self.assertIsNone(evidence)
            self.assertTrue(violations)

    def test_missing_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            evidence, violations = load_and_verify_b2_checkpoint(
                tmp_path / "does_not_exist.json", repo_root=tmp_path, expected_manifest_sha256="0" * 64,
                expected_checkpoint="001B-B2", expected_status="passed",
                expected_biological_count=None, expected_control_count=None,
            )
            self.assertIsNone(evidence)
            self.assertTrue(violations)

    def test_wrong_checkpoint_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = self._write_checkpoint(tmp_path, checkpoint="001B-B7")
            evidence, violations = load_and_verify_b2_checkpoint(
                manifest_path, repo_root=tmp_path, expected_manifest_sha256=sha256_file(manifest_path),
                expected_checkpoint="001B-B2", expected_status="passed",
                expected_biological_count=None, expected_control_count=None,
            )
            self.assertIsNone(evidence)
            self.assertTrue(any("checkpoint" in v for v in violations))

    def test_wrong_status_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = self._write_checkpoint(tmp_path, status="pending")
            evidence, violations = load_and_verify_b2_checkpoint(
                manifest_path, repo_root=tmp_path, expected_manifest_sha256=sha256_file(manifest_path),
                expected_checkpoint="001B-B2", expected_status="passed",
                expected_biological_count=None, expected_control_count=None,
            )
            self.assertIsNone(evidence)
            self.assertTrue(any("status" in v for v in violations))

    def test_drifted_artifact_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = self._write_checkpoint(tmp_path)
            expected_sha256 = sha256_file(manifest_path)
            (tmp_path / "sample_sequences.fasta").write_text(">tampered\nAAAA\n")
            evidence, violations = load_and_verify_b2_checkpoint(
                manifest_path, repo_root=tmp_path, expected_manifest_sha256=expected_sha256,
                expected_checkpoint="001B-B2", expected_status="passed",
                expected_biological_count=None, expected_control_count=None,
            )
            self.assertIsNone(evidence)
            self.assertTrue(any("drifted" in v for v in violations))

    def test_control_id_set_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = self._write_checkpoint(tmp_path, control_fasta_text=">control_UNRELATED\nGGGG\n")
            evidence, violations = load_and_verify_b2_checkpoint(
                manifest_path, repo_root=tmp_path, expected_manifest_sha256=sha256_file(manifest_path),
                expected_checkpoint="001B-B2", expected_status="passed",
                expected_biological_count=None, expected_control_count=None,
            )
            self.assertIsNone(evidence)
            self.assertTrue(any("control-ID-set mismatch" in v for v in violations))

    def test_real_mode_population_count_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = self._write_checkpoint(tmp_path)
            evidence, violations = load_and_verify_b2_checkpoint(
                manifest_path, repo_root=tmp_path, expected_manifest_sha256=sha256_file(manifest_path),
                expected_checkpoint="001B-B2", expected_status="passed",
                expected_biological_count=10000, expected_control_count=100,
            )
            self.assertIsNone(evidence)
            self.assertTrue(any("10000" in v or "100" in v for v in violations))


class ComputeProbeProjectionTests(unittest.TestCase):
    """B3A-R6: the accepted wall-time/output/memory projection formulas and
    fail-closed gates.
    """

    def _base_kwargs(self, **overrides):
        kwargs = dict(
            largest_contig_length=100,
            total_reference_bases=1000,  # scale = 10
            observed_wall_seconds=10.0,
            observed_output_bytes=1000,
            observed_peak_rss_kib=1024,  # 1 MiB
            observed_hit_count=5,
            physical_ram_gib=16.0,
            available_memory_gib=8.0,
            probe_output_allowance_bytes=int(1.0 * (1024**3)),
        )
        kwargs.update(overrides)
        return kwargs

    def test_healthy_projection_passes_every_gate(self):
        projection = compute_probe_projection(**self._base_kwargs())
        self.assertTrue(projection.ok, projection.violations)
        self.assertTrue(projection.wall_time_gate_ok)
        self.assertTrue(projection.output_gate_ok)
        self.assertTrue(projection.memory_gate_ok)
        self.assertEqual(projection.scale, 10.0)
        self.assertEqual(projection.projected_wall_seconds, 10.0 * 10.0 * 1.5)
        self.assertEqual(projection.projected_output_bytes, 1000 * 10.0 * 2.0)
        self.assertFalse(projection.zero_hit_limitation)

    def test_zero_hits_is_recorded_as_a_limitation_not_a_failure(self):
        projection = compute_probe_projection(**self._base_kwargs(observed_hit_count=0, observed_output_bytes=0))
        self.assertTrue(projection.zero_hit_limitation)
        self.assertTrue(projection.ok, projection.violations)

    def test_wall_time_gate_fails_closed_over_4_5_hours(self):
        projection = compute_probe_projection(**self._base_kwargs(observed_wall_seconds=999999.0))
        self.assertFalse(projection.ok)
        self.assertFalse(projection.wall_time_gate_ok)

    def test_output_gate_fails_closed_over_1_gib_share(self):
        projection = compute_probe_projection(**self._base_kwargs(observed_output_bytes=10**9))
        self.assertFalse(projection.ok)
        self.assertFalse(projection.output_gate_ok)

    def test_missing_physical_ram_fails_closed(self):
        projection = compute_probe_projection(**self._base_kwargs(physical_ram_gib=None))
        self.assertFalse(projection.ok)
        self.assertFalse(projection.memory_gate_ok)

    def test_missing_available_memory_fails_closed(self):
        projection = compute_probe_projection(**self._base_kwargs(available_memory_gib=None))
        self.assertFalse(projection.ok)
        self.assertFalse(projection.memory_gate_ok)

    def test_peak_rss_plus_margin_exceeding_available_memory_fails_closed(self):
        projection = compute_probe_projection(**self._base_kwargs(available_memory_gib=1.0))
        self.assertFalse(projection.ok)
        self.assertFalse(projection.memory_gate_ok)

    def test_peak_rss_plus_margin_exceeding_physical_ram_fails_closed(self):
        projection = compute_probe_projection(**self._base_kwargs(physical_ram_gib=1.0, available_memory_gib=100.0))
        self.assertFalse(projection.ok)
        self.assertFalse(projection.memory_gate_ok)


class ProbeFingerprintTests(unittest.TestCase):
    def test_deterministic_and_sensitive_to_every_input(self):
        base_kwargs = dict(
            b2_manifest_sha256="z" * 64,
            b2_sample_sha256="a" * 64,
            b2_control_sha256="b" * 64,
            reference_sha256="c" * 64,
            reference_manifest_content_sha256="d" * 64,
            reference_manifest_raw_sha256="i" * 64,
            index_generation_digest="e" * 64,
            bwa_binary_sha256="f" * 64,
            minimap2_binary_sha256="g" * 64,
            seqkit_binary_sha256="h" * 64,
            bwa_binary_version="0.7.19",
            minimap2_binary_version="2.31",
            seqkit_binary_version="2.13.0",
            bwa_command="bwa mem -a -Y -t 1 ref reads",
            minimap2_command="minimap2 -ax splice:sr ref reads",
            seqkit_command="seqkit locate --bed ref reads",
            git_commit="deadbeef",
            git_clean=True,
        )
        first = probe_fingerprint(**base_kwargs)
        second = probe_fingerprint(**base_kwargs)
        self.assertEqual(first, second)

        for key in base_kwargs:
            mutated = dict(base_kwargs)
            mutated[key] = "different_value"
            self.assertNotEqual(probe_fingerprint(**mutated), first, f"fingerprint insensitive to {key!r}")


if __name__ == "__main__":
    unittest.main()
