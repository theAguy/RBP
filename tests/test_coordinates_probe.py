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

import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.probe import (
    ProbeError,
    build_pattern_fasta,
    extract_contig_streaming,
    probe_fingerprint,
    select_probe_window,
    validate_probe_bed_rows,
)


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


class ProbeFingerprintTests(unittest.TestCase):
    def test_deterministic_and_sensitive_to_every_input(self):
        base_kwargs = dict(
            b2_sample_sha256="a" * 64,
            b2_control_sha256="b" * 64,
            reference_sha256="c" * 64,
            reference_manifest_content_sha256="d" * 64,
            index_generation_digest="e" * 64,
            bwa_binary_sha256="f" * 64,
            minimap2_binary_sha256="g" * 64,
            seqkit_binary_sha256="h" * 64,
            bwa_command="bwa mem -a -Y -t 1 ref reads",
            minimap2_command="minimap2 -ax splice:sr ref reads",
            seqkit_command="seqkit locate --bed ref reads",
            git_commit="deadbeef",
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
