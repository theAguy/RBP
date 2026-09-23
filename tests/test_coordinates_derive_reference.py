import gzip
import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.derive_reference import (
    CATEGORY_CHROMOSOME,
    CATEGORY_MITOCHONDRION,
    CATEGORY_UNLOCALIZED,
    CATEGORY_UNPLACED,
    DerivationError,
    build_reference_manifest,
    contig_category,
    derive_reference_fasta,
    parse_assembly_report,
    selected_accession,
)
from rbpbench.coordinates.manifest import REQUIRED_REFERENCE_MANIFEST_FIELDS

_ASSEMBLY_REPORT_HEADER = (
    "# Sequence-Name\tSequence-Role\tAssigned-Molecule\tAssigned-Molecule-Location/Type\t"
    "GenBank-Accn\tRelationship\tRefSeq-Accn\tAssembly-Unit\tSequence-Length\tUCSC-style-name\n"
)

# Six accessions mirroring the real NCBI assembly-report shape: an assembled
# chromosome, an unlocalized and an unplaced scaffold (all Primary Assembly,
# all included), the mitochondrial assembled-molecule (non-nuclear, included),
# and two excluded records (an ALT_REF_LOCI alt-scaffold and a separately
# packaged HLA/decoy-style contig) so exclusion is exercised, not merely
# assumed.
_TINY_ASSEMBLY_REPORT = _ASSEMBLY_REPORT_HEADER + "\n".join(
    [
        "1\tassembled-molecule\t1\tChromosome\tCM_TEST1.1\t=\tNC_TEST1.1\tPrimary Assembly\t40\tchr1",
        "1_RANDOM\tunlocalized-scaffold\t1\tChromosome\tKI_TEST1.1\t=\tNT_TEST1.1\tPrimary Assembly\t20\tchr1_random",
        "HSCHRUN_RANDOM\tunplaced-scaffold\tna\tna\tKI_TEST2.1\t=\tna\tPrimary Assembly\t16\tchrUn_test",
        "MT\tassembled-molecule\tMT\tMitochondrion\tJ_TEST.2\t=\tNC_TESTMT.1\tnon-nuclear\t24\tchrM",
        "1_ALT\talt-scaffold\t1\tChromosome\tGL_TESTALT.1\t=\tNW_TESTALT.1\tALT_REF_LOCI_1\t20\tchr1_alt",
        "HSCHR6_MHC\talt-scaffold\t6\tChromosome\tGL_TESTHLA.1\t=\tna\tALT_REF_LOCI_2\t18\tchr6_mhc",
    ]
) + "\n"


def _tiny_source_fasta_text() -> str:
    # Uppercase-only chromosome, a soft-masked (lowercase) unlocalized
    # scaffold, an unplaced scaffold, mitochondrion, and the two excluded
    # records' sequences too (present in the *source*, but must never be
    # written to the derived FASTA).
    return "".join(
        [
            ">NC_TEST1.1\n", "A" * 40 + "\n",
            ">NT_TEST1.1\n", "acgt" * 5 + "\n",  # 20 nt, soft-masked
            ">KI_TEST2.1\n", "C" * 16 + "\n",  # unplaced scaffold has no RefSeq-Accn -> GenBank fallback
            ">NC_TESTMT.1\n", "G" * 24 + "\n",
            ">NW_TESTALT.1\n", "T" * 20 + "\n",  # excluded (ALT_REF_LOCI)
            ">GL_TESTHLA.1\n", "A" * 18 + "\n",  # excluded (separately packaged HLA-style)
        ]
    )


class ParseAssemblyReportTests(unittest.TestCase):
    def test_parses_all_rows_and_reads_header_column_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "assembly_report.txt"
            path.write_text(_TINY_ASSEMBLY_REPORT)
            records = parse_assembly_report(path)
            self.assertEqual(len(records), 6)
            self.assertEqual(records[0].sequence_name, "1")
            self.assertEqual(records[0].sequence_role, "assembled-molecule")
            self.assertEqual(records[0].sequence_length, 40)

    def test_falls_back_to_default_column_order_without_a_header_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "assembly_report.txt"
            path.write_text(_TINY_ASSEMBLY_REPORT.split("\n", 1)[1])  # strip the header comment
            records = parse_assembly_report(path)
            self.assertEqual(len(records), 6)
            self.assertEqual(records[0].sequence_name, "1")


class ContigCategoryTests(unittest.TestCase):
    def test_category_assignment_matches_frozen_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "assembly_report.txt"
            path.write_text(_TINY_ASSEMBLY_REPORT)
            records = {r.sequence_name: r for r in parse_assembly_report(path)}
            self.assertEqual(contig_category(records["1"]), CATEGORY_CHROMOSOME)
            self.assertEqual(contig_category(records["1_RANDOM"]), CATEGORY_UNLOCALIZED)
            self.assertEqual(contig_category(records["HSCHRUN_RANDOM"]), CATEGORY_UNPLACED)
            self.assertEqual(contig_category(records["MT"]), CATEGORY_MITOCHONDRION)
            self.assertIsNone(contig_category(records["1_ALT"]))
            self.assertIsNone(contig_category(records["HSCHR6_MHC"]))

    def test_selected_accession_prefers_refseq_falls_back_to_genbank(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "assembly_report.txt"
            path.write_text(_TINY_ASSEMBLY_REPORT)
            records = {r.sequence_name: r for r in parse_assembly_report(path)}
            self.assertEqual(selected_accession(records["1"]), "NC_TEST1.1")
            # RefSeq-Accn is "na" -> GenBank fallback, never a renamed alias.
            self.assertEqual(selected_accession(records["HSCHRUN_RANDOM"]), "KI_TEST2.1")


class DeriveReferenceFastaTests(unittest.TestCase):
    def _write_fixtures(self, tmp: Path, *, gz: bool) -> tuple[Path, Path]:
        report_path = tmp / "assembly_report.txt"
        report_path.write_text(_TINY_ASSEMBLY_REPORT)
        fasta_text = _tiny_source_fasta_text()
        if gz:
            fasta_path = tmp / "source.fna.gz"
            with gzip.open(fasta_path, "wt") as handle:
                handle.write(fasta_text)
        else:
            fasta_path = tmp / "source.fna"
            fasta_path.write_text(fasta_text)
        return report_path, fasta_path

    def test_derivation_selects_exactly_the_policy_matched_contigs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path, fasta_path = self._write_fixtures(tmp_path, gz=True)
            output_fasta = tmp_path / "derived.fna"

            derivation = derive_reference_fasta(
                source_fasta=fasta_path, assembly_report=report_path, output_fasta=output_fasta
            )

            self.assertEqual(
                set(derivation.contigs), {"NC_TEST1.1", "NT_TEST1.1", "KI_TEST2.1", "NC_TESTMT.1"}
            )
            self.assertNotIn("NW_TESTALT.1", derivation.contigs)
            self.assertNotIn("GL_TESTHLA.1", derivation.contigs)
            self.assertEqual(
                derivation.category_counts,
                {
                    CATEGORY_CHROMOSOME: 1,
                    CATEGORY_UNLOCALIZED: 1,
                    CATEGORY_UNPLACED: 1,
                    CATEGORY_MITOCHONDRION: 1,
                },
            )
            derived_text = output_fasta.read_text()
            self.assertNotIn("NW_TESTALT.1", derived_text)
            self.assertNotIn("GL_TESTHLA.1", derived_text)

    def test_works_identically_on_plain_and_gzipped_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path, gz_fasta = self._write_fixtures(tmp_path, gz=True)
            _, plain_fasta = self._write_fixtures(tmp_path, gz=False)

            derivation_gz = derive_reference_fasta(
                source_fasta=gz_fasta, assembly_report=report_path, output_fasta=tmp_path / "from_gz.fna"
            )
            derivation_plain = derive_reference_fasta(
                source_fasta=plain_fasta, assembly_report=report_path, output_fasta=tmp_path / "from_plain.fna"
            )
            self.assertEqual(derivation_gz.output_fasta_sha256, derivation_plain.output_fasta_sha256)

    def test_repeated_derivation_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path, fasta_path = self._write_fixtures(tmp_path, gz=True)
            first = derive_reference_fasta(
                source_fasta=fasta_path, assembly_report=report_path, output_fasta=tmp_path / "first.fna"
            )
            second = derive_reference_fasta(
                source_fasta=fasta_path, assembly_report=report_path, output_fasta=tmp_path / "second.fna"
            )
            self.assertEqual(first.output_fasta_sha256, second.output_fasta_sha256)

    def test_masking_status_soft_when_lowercase_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path, fasta_path = self._write_fixtures(tmp_path, gz=True)
            derivation = derive_reference_fasta(
                source_fasta=fasta_path, assembly_report=report_path, output_fasta=tmp_path / "derived.fna"
            )
            self.assertEqual(derivation.masking["status"], "soft")
            self.assertGreater(derivation.masking["lower"], 0)
            self.assertGreater(derivation.masking["upper"], 0)

    def test_duplicate_accession_in_source_fails_the_exactly_once_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "assembly_report.txt"
            report_path.write_text(_TINY_ASSEMBLY_REPORT)
            fasta_path = tmp_path / "source.fna"
            # NC_TEST1.1 appears twice in the source.
            fasta_path.write_text(">NC_TEST1.1\n" + "A" * 40 + "\n>NC_TEST1.1\n" + "A" * 40 + "\n")
            with self.assertRaises(DerivationError):
                derive_reference_fasta(
                    source_fasta=fasta_path, assembly_report=report_path, output_fasta=tmp_path / "derived.fna"
                )

    def test_length_mismatch_against_assembly_report_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "assembly_report.txt"
            report_path.write_text(_TINY_ASSEMBLY_REPORT)
            fasta_path = tmp_path / "source.fna"
            # NC_TEST1.1 declared length 40 but only 39 bases supplied.
            fasta_path.write_text(">NC_TEST1.1\n" + "A" * 39 + "\n")
            with self.assertRaises(DerivationError):
                derive_reference_fasta(
                    source_fasta=fasta_path, assembly_report=report_path, output_fasta=tmp_path / "derived.fna"
                )


class BuildReferenceManifestTests(unittest.TestCase):
    def test_manifest_satisfies_required_fields_for_validate_reference_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "assembly_report.txt"
            report_path.write_text(_TINY_ASSEMBLY_REPORT)
            fasta_path = tmp_path / "source.fna.gz"
            with gzip.open(fasta_path, "wt") as handle:
                handle.write(_tiny_source_fasta_text())
            output_fasta = tmp_path / "derived.fna"

            derivation = derive_reference_fasta(
                source_fasta=fasta_path, assembly_report=report_path, output_fasta=output_fasta
            )
            manifest = build_reference_manifest(
                derivation,
                build_id="hg38",
                assembly_accession="GCF_TEST38",
                source_url="https://example.invalid/hg38.fna.gz",
                source_fasta_compressed=fasta_path,
                source_fasta_compressed_upstream_md5="a" * 32,
                assembly_report=report_path,
                assembly_report_upstream_md5="b" * 32,
                derivation_command="derive_reference_fasta(...)",
                git_commit="deadbeef",
            )
            for field_name in REQUIRED_REFERENCE_MANIFEST_FIELDS:
                self.assertIn(field_name, manifest)
                self.assertNotIn(manifest[field_name], (None, ""))
            self.assertEqual(manifest["build_id"], "hg38")
            self.assertEqual(manifest["sha256"], derivation.output_fasta_sha256)
            self.assertEqual(manifest["byte_size"], derivation.output_fasta_byte_size)
            self.assertEqual(set(manifest["contig_categories"]), set(derivation.contigs))
            self.assertIn("masking", manifest)
            self.assertIn("source", manifest)
            self.assertEqual(manifest["source"]["fasta_compressed_upstream_md5"], "a" * 32)


if __name__ == "__main__":
    unittest.main()
