"""Regression coverage for Task 001B checkpoint B3A, item A2 (accepted
contig-length evidence) and the CRLF-safety half of item A4.

Test names map to the executor handoff's "Minimum regression set"
(docs/handoffs/001b_b3a_claude_executor_handoff.md):
  - item 5 (contig_lengths key/length/total validation and tied-largest tie-break)
  - item 6 (LF/CRLF equivalence)

Fixtures are tiny and synthetic throughout; nothing here touches the real
CSV, a real B2 FASTA, a real human reference, or a network URL.
"""

from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.derive_reference import (
    DerivationError,
    derive_reference_fasta,
    largest_contig,
    parse_assembly_report,
    validate_contig_lengths,
)
from rbpbench.coordinates.execution_sources import DerivedReferencePolicy

_POLICY_REFSEQ_ONLY = DerivedReferencePolicy(
    include_sequence_roles_primary_assembly=("assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold"),
    include_non_nuclear_assembled_molecule=True,
    accession_preference=("refseq",),
)

_ASSEMBLY_REPORT_HEADER = (
    "# Sequence-Name\tSequence-Role\tAssigned-Molecule\tAssigned-Molecule-Location/Type\t"
    "GenBank-Accn\tRelationship\tRefSeq-Accn\tAssembly-Unit\tSequence-Length\tUCSC-style-name\n"
)


def _report_rows(*, chr1_length: int, chr2_length: int) -> str:
    return _ASSEMBLY_REPORT_HEADER + "\n".join(
        [
            f"1\tassembled-molecule\t1\tChromosome\tCM_TEST1.1\t=\tNC_TEST1.1\tPrimary Assembly\t{chr1_length}\tchr1",
            f"2\tassembled-molecule\t2\tChromosome\tCM_TEST2.1\t=\tNC_TEST2.1\tPrimary Assembly\t{chr2_length}\tchr2",
        ]
    ) + "\n"


class DeriveReferenceContigLengthsTests(unittest.TestCase):
    """Item 5: contig_lengths key/length/total validation from a real
    derive_reference_fasta() call (not just the pure validator in isolation).
    """

    def test_contig_lengths_present_and_key_matches_contigs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_report_rows(chr1_length=40, chr2_length=20))
            fasta_path = tmp_path / "source.fna"
            fasta_path.write_text(">NC_TEST1.1\n" + "A" * 40 + "\n>NC_TEST2.1\n" + "C" * 20 + "\n")

            derivation = derive_reference_fasta(
                source_fasta=fasta_path,
                assembly_report=report_path,
                output_fasta=tmp_path / "derived.fna",
                policy=_POLICY_REFSEQ_ONLY,
            )
            self.assertEqual(derivation.contig_lengths, {"NC_TEST1.1": 40, "NC_TEST2.1": 20})
            self.assertEqual(set(derivation.contig_lengths), set(derivation.contigs))

    def test_largest_contig_selects_the_greatest_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_report_rows(chr1_length=40, chr2_length=100))
            fasta_path = tmp_path / "source.fna"
            fasta_path.write_text(">NC_TEST1.1\n" + "A" * 40 + "\n>NC_TEST2.1\n" + "C" * 100 + "\n")

            derivation = derive_reference_fasta(
                source_fasta=fasta_path,
                assembly_report=report_path,
                output_fasta=tmp_path / "derived.fna",
                policy=_POLICY_REFSEQ_ONLY,
            )
            self.assertEqual(largest_contig(derivation.contig_lengths), "NC_TEST2.1")

    def test_tied_largest_breaks_by_accession_lexicographic_order(self):
        # NC_TEST1.1 and NC_TEST2.1 tie at length 40; the deterministic
        # tie-break is accession lexicographic order ONLY.
        lengths = {"NC_TEST2.1": 40, "NC_TEST1.1": 40, "NC_TEST3.1": 10}
        self.assertEqual(largest_contig(lengths), "NC_TEST1.1")

    def test_validate_contig_lengths_rejects_key_mismatch(self):
        violations = validate_contig_lengths(
            {"A": 10}, contigs=("A", "B"), assembly_report_lengths={"A": 10, "B": 5}, total_emitted_bases=10
        )
        self.assertTrue(violations)

    def test_validate_contig_lengths_rejects_total_disagreement(self):
        violations = validate_contig_lengths(
            {"A": 10, "B": 5}, contigs=("A", "B"), assembly_report_lengths={"A": 10, "B": 5}, total_emitted_bases=999
        )
        self.assertTrue(any("total emitted" in v for v in violations))

    def test_validate_contig_lengths_rejects_non_positive_length(self):
        violations = validate_contig_lengths(
            {"A": 0}, contigs=("A",), assembly_report_lengths={"A": 0}, total_emitted_bases=0
        )
        self.assertTrue(any("positive integer" in v for v in violations))

    def test_validate_contig_lengths_rejects_assembly_report_disagreement(self):
        violations = validate_contig_lengths(
            {"A": 10}, contigs=("A",), assembly_report_lengths={"A": 11}, total_emitted_bases=10
        )
        self.assertTrue(any("does not agree with assembly-report length" in v for v in violations))

    def test_largest_contig_raises_on_empty_input(self):
        with self.assertRaises(DerivationError):
            largest_contig({})


class CrlfEquivalenceTests(unittest.TestCase):
    """Item 6: LF/CRLF equivalence -- CRLF input must never change emitted
    reference bytes relative to the same content as ordinary LF input.
    """

    def test_crlf_assembly_report_parses_identically_to_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            lf_text = _report_rows(chr1_length=40, chr2_length=20)
            crlf_text = lf_text.replace("\n", "\r\n")

            lf_path = tmp_path / "lf.txt"
            lf_path.write_text(lf_text)
            crlf_path = tmp_path / "crlf.txt"
            crlf_path.write_bytes(crlf_text.encode())

            lf_records = parse_assembly_report(lf_path)
            crlf_records = parse_assembly_report(crlf_path)
            self.assertEqual(lf_records, crlf_records)
            # In particular, no trailing "\r" leaked into a parsed field.
            self.assertEqual(crlf_records[0].sequence_name, "1")
            self.assertNotIn("\r", crlf_records[-1].sequence_name)

    def test_crlf_source_fasta_derives_byte_identical_output_to_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_report_rows(chr1_length=40, chr2_length=20))

            lf_fasta_text = ">NC_TEST1.1\n" + "A" * 40 + "\n>NC_TEST2.1\n" + "C" * 20 + "\n"
            crlf_fasta_text = lf_fasta_text.replace("\n", "\r\n")

            lf_fasta = tmp_path / "lf.fna"
            lf_fasta.write_text(lf_fasta_text)
            crlf_fasta = tmp_path / "crlf.fna"
            crlf_fasta.write_bytes(crlf_fasta_text.encode())

            lf_derivation = derive_reference_fasta(
                source_fasta=lf_fasta,
                assembly_report=report_path,
                output_fasta=tmp_path / "lf_out.fna",
                policy=_POLICY_REFSEQ_ONLY,
            )
            crlf_derivation = derive_reference_fasta(
                source_fasta=crlf_fasta,
                assembly_report=report_path,
                output_fasta=tmp_path / "crlf_out.fna",
                policy=_POLICY_REFSEQ_ONLY,
            )
            self.assertEqual(lf_derivation.output_fasta_sha256, crlf_derivation.output_fasta_sha256)
            self.assertEqual(lf_derivation.contig_lengths, crlf_derivation.contig_lengths)
            self.assertNotIn("\r", crlf_derivation.output_fasta.read_text())

    def test_gzipped_crlf_source_also_derives_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_report_rows(chr1_length=8, chr2_length=4))
            crlf_text = (">NC_TEST1.1\r\n" + "A" * 8 + "\r\n>NC_TEST2.1\r\n" + "C" * 4 + "\r\n")
            gz_path = tmp_path / "source.fna.gz"
            with gzip.open(gz_path, "wt") as handle:
                handle.write(crlf_text)

            derivation = derive_reference_fasta(
                source_fasta=gz_path,
                assembly_report=report_path,
                output_fasta=tmp_path / "out.fna",
                policy=_POLICY_REFSEQ_ONLY,
            )
            self.assertEqual(derivation.contig_lengths, {"NC_TEST1.1": 8, "NC_TEST2.1": 4})
            self.assertNotIn("\r", derivation.output_fasta.read_text())


if __name__ == "__main__":
    unittest.main()
