"""Regression coverage for the Task 001B checkpoint B3B-1 accession-policy
correction (``docs/handoffs/001b_b3b1_derivation_correction_claude_handoff.md``,
``docs/reviews/001b_b3b1_derivation_stop_review.md``).

Every test here targets one item from that handoff's "Mandatory regressions"
list (numbered in each test's docstring) and is designed to fail against the
handoff's parent commit ``d9bfcad`` (where ``derive_reference_fasta``/
``selected_accession``/``stage_derive`` hard-code "RefSeq when present, else
GenBank" and never accept a ``DerivedReferencePolicy`` at all -- so every
call below that passes ``policy=`` raises ``TypeError`` there, and
``EXCLUSION_REASON_SOURCE_NAMESPACE_UNREPRESENTED``/
``validate_derived_reference_policy`` do not exist to import).

Fixtures are tiny and synthetic throughout: nothing here touches the network,
the real dataset CSV, a real B2 FASTA, a real human reference, or any ignored
B3 execution evidence.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.derive_reference import (
    CATEGORY_CHROMOSOME,
    CATEGORY_UNLOCALIZED,
    CATEGORY_UNPLACED,
    EXCLUSION_REASON_SOURCE_NAMESPACE_UNREPRESENTED,
    DerivationError,
    build_reference_manifest,
    derive_reference_fasta,
    parse_assembly_report,
    selected_accession,
)
from rbpbench.coordinates.execution_sources import (
    DerivedReferencePolicy,
    load_execution_sources,
    validate_derived_reference_policy,
)
from rbpbench.coordinates.manifest import manifest_content_sha256
from rbpbench.coordinates.runner import main, stage_derive
from rbpbench.data.audit import sha256_file

from test_coordinates_runner import FIXTURE_CONFIG, FIXTURE_CSV, FIXTURE_EXECUTION_SOURCES, _approved_host_context
from test_coordinates_b1_second_corrections import _fixture_report, _hg38_source_spec

REPO_ROOT = Path(__file__).resolve().parents[1]

_ROLES = ("assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold")

POLICY_REFSEQ_ONLY = DerivedReferencePolicy(
    include_sequence_roles_primary_assembly=_ROLES,
    include_non_nuclear_assembled_molecule=True,
    accession_preference=("refseq",),
)
POLICY_REFSEQ_THEN_GENBANK = DerivedReferencePolicy(
    include_sequence_roles_primary_assembly=_ROLES,
    include_non_nuclear_assembled_molecule=True,
    accession_preference=("refseq", "genbank"),
)
POLICY_GENBANK_ONLY = DerivedReferencePolicy(
    include_sequence_roles_primary_assembly=_ROLES,
    include_non_nuclear_assembled_molecule=True,
    accession_preference=("genbank",),
)
POLICY_GENBANK_THEN_REFSEQ = DerivedReferencePolicy(
    include_sequence_roles_primary_assembly=_ROLES,
    include_non_nuclear_assembled_molecule=True,
    accession_preference=("genbank", "refseq"),
)

_REPORT_HEADER = (
    "# Sequence-Name\tSequence-Role\tAssigned-Molecule\tAssigned-Molecule-Location/Type\t"
    "GenBank-Accn\tRelationship\tRefSeq-Accn\tAssembly-Unit\tSequence-Length\tUCSC-style-name\n"
)

# One GCF-shaped assembly report: a RefSeq-selectable chromosome plus a
# category-eligible unplaced scaffold that has ONLY a GenBank accession
# (RefSeq-Accn == "na") -- mirrors the real GRCh38.p14 KI270721.1/
# KI270734.1/KI270752.1 shape (docs/DECISIONS.md, 2026-09-24 "B3B-1 RefSeq
# derivation universe").
_GCF_SHAPED_REPORT = _REPORT_HEADER + "\n".join(
    [
        "1\tassembled-molecule\t1\tChromosome\tCM_TEST1.1\t=\tNC_TEST1.1\tPrimary Assembly\t40\tchr1",
        "HSCHRUN_RANDOM\tunplaced-scaffold\tna\tna\tKI_TESTGB.1\t=\tna\tPrimary Assembly\t16\tchrUn_test",
    ]
) + "\n"


def _gcf_shaped_source_fasta_text() -> str:
    # The GenBank-only accession's sequence is deliberately absent from the
    # source FASTA -- it must never be treated as a "selected but missing"
    # hard failure under a RefSeq-only policy.
    return ">NC_TEST1.1\n" + "A" * 40 + "\n"


class Item1And2And3ExclusionEvidenceTests(unittest.TestCase):
    """Items 1-3: a GCF-shaped report with one RefSeq-selected row plus one
    category-eligible GenBank-only row omitted from the FASTA derives
    successfully with only the RefSeq row selected, the GenBank-only row
    explicitly reported (reason/count/bases/category/record evidence), and
    category counts for selected contigs excluding the reported row.
    """

    def test_refseq_only_policy_selects_only_the_refseq_row_and_reports_the_genbank_only_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_GCF_SHAPED_REPORT)
            fasta_path = tmp_path / "source.fna"
            fasta_path.write_text(_gcf_shaped_source_fasta_text())

            derivation = derive_reference_fasta(
                source_fasta=fasta_path,
                assembly_report=report_path,
                output_fasta=tmp_path / "derived.fna",
                policy=POLICY_REFSEQ_ONLY,
            )

            # Item 1: derivation succeeds with only the RefSeq row selected.
            self.assertEqual(derivation.contigs, ("NC_TEST1.1",))
            self.assertNotIn("KI_TESTGB.1", derivation.contigs)

            # Item 3: category counts for SELECTED contigs exclude the
            # reported row -- only the chromosome, never the unplaced
            # scaffold that was excluded.
            self.assertEqual(derivation.category_counts, {CATEGORY_CHROMOSOME: 1})

            # Item 2: exact exclusion reason/count/bases/category/record
            # evidence.
            self.assertEqual(derivation.exclusion_summary["count"], 1)
            self.assertEqual(derivation.exclusion_summary["total_bases"], 16)
            self.assertEqual(
                derivation.exclusion_summary["reason_counts"],
                {EXCLUSION_REASON_SOURCE_NAMESPACE_UNREPRESENTED: 1},
            )
            self.assertEqual(derivation.exclusion_summary["category_counts"], {CATEGORY_UNPLACED: 1})
            self.assertEqual(len(derivation.excluded_records), 1)
            record = derivation.excluded_records[0]
            self.assertEqual(record["accession"], "KI_TESTGB.1")
            self.assertEqual(record["category"], CATEGORY_UNPLACED)
            self.assertEqual(record["sequence_name"], "HSCHRUN_RANDOM")
            self.assertEqual(record["length"], 16)
            self.assertEqual(record["reason"], EXCLUSION_REASON_SOURCE_NAMESPACE_UNREPRESENTED)

            # Also present in the manifest (not merely the in-memory result).
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
            self.assertEqual(manifest["exclusion_summary"], derivation.exclusion_summary)
            self.assertEqual(manifest["excluded_records"], list(derivation.excluded_records))
            self.assertEqual(manifest["effective_policy"]["accession_preference"], ["refseq"])


class Item4MissingSelectedAccessionTests(unittest.TestCase):
    """Item 4: a selected RefSeq accession absent from the FASTA is a hard
    failure, never an inferred exclusion.
    """

    def test_selected_accession_missing_from_fasta_is_a_hard_derivation_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_GCF_SHAPED_REPORT)
            fasta_path = tmp_path / "source.fna"
            # NC_TEST1.1 is a category-eligible RefSeq-selected row, but the
            # source FASTA contains no record for it at all.
            fasta_path.write_text(">SOME_OTHER_ACCESSION.1\nACGT\n")

            with self.assertRaises(DerivationError) as ctx:
                derive_reference_fasta(
                    source_fasta=fasta_path,
                    assembly_report=report_path,
                    output_fasta=tmp_path / "derived.fna",
                    policy=POLICY_REFSEQ_ONLY,
                )
            # Never silently reported as an exclusion.
            self.assertNotIn("source_namespace_unrepresented", str(ctx.exception))


class Item5DuplicateSelectedAccessionTests(unittest.TestCase):
    """Item 5: a selected accession duplicated in the FASTA is an explicit
    hard failure (proves the B3B-1 fix to the previously-unraised
    occurrence-violations list -- see req 7 / the derive_reference_fasta
    docstring).
    """

    def test_duplicated_selected_accession_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_fixture_report(accession="NC_TEST1.1", length=8))
            fasta_path = tmp_path / "source.fna"
            fasta_path.write_text(">NC_TEST1.1\nACGTACGT\n>NC_TEST1.1\nACGTACGT\n")

            with self.assertRaises(DerivationError) as ctx:
                derive_reference_fasta(
                    source_fasta=fasta_path,
                    assembly_report=report_path,
                    output_fasta=tmp_path / "derived.fna",
                    policy=POLICY_REFSEQ_ONLY,
                )
            self.assertIn("occurs 2 time(s)", str(ctx.exception))


class Item6LengthMismatchTests(unittest.TestCase):
    """Item 6: a selected accession with a length mismatch is an explicit
    hard failure.
    """

    def test_length_mismatched_selected_accession_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_fixture_report(accession="NC_TEST1.1", length=8))
            fasta_path = tmp_path / "source.fna"
            fasta_path.write_text(">NC_TEST1.1\nACGT\n")  # 4 bases, declared 8

            with self.assertRaises(DerivationError) as ctx:
                derive_reference_fasta(
                    source_fasta=fasta_path,
                    assembly_report=report_path,
                    output_fasta=tmp_path / "derived.fna",
                    policy=POLICY_REFSEQ_ONLY,
                )
            self.assertIn("derived length", str(ctx.exception))


class Item7FailurePreservesPriorGenerationTests(unittest.TestCase):
    """Item 7: each of the item 4/5/6 failure modes preserves a prior
    accepted output/selection generation (exercised through stage_derive so
    the accepted derive.json/generation directory is what is checked, not
    merely the pure function).
    """

    def _accepted_download_record(self, tmp_path: Path, *, fasta_text: str, report_text: str) -> dict:
        source_fasta = tmp_path / "source.fna"
        source_fasta.write_text(fasta_text)
        report_path = tmp_path / "report.txt"
        report_path.write_text(report_text)
        return {
            "executed": True,
            "fasta": {"dest_path": str(source_fasta), "sha256": sha256_file(source_fasta)},
            "assembly_report": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
            "checksum_listing": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
        }

    def _first_accepted_generation(self, tmp_path: Path) -> tuple[dict, dict, Path]:
        derived_dir = tmp_path / "derived"
        download_record = self._accepted_download_record(
            tmp_path,
            fasta_text=">NC_TEST1.1\nACGTACGT\n",
            report_text=_fixture_report(accession="NC_TEST1.1", length=8),
        )
        first = stage_derive(
            build="hg38",
            source_spec=_hg38_source_spec(),
            derived_dir=derived_dir,
            allow_mapping=True,
            host_role="approved_mac",
            download_record=download_record,
            dry_run=False,
            policy=POLICY_REFSEQ_ONLY,
        )
        self.assertTrue(first["executed"])
        accepted_record = json.loads((derived_dir / "derive.json").read_text())
        return download_record, accepted_record, derived_dir

    def test_missing_selected_accession_preserves_prior_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, accepted_record, derived_dir = self._first_accepted_generation(tmp_path)

            (tmp_path / "attempt2").mkdir(exist_ok=True)
            bad_download_record = self._accepted_download_record(
                tmp_path / "attempt2",
                fasta_text=">SOME_OTHER.1\nACGT\n",
                report_text=_fixture_report(accession="NC_TEST1.1", length=8),
            )
            with self.assertRaises(DerivationError):
                stage_derive(
                    build="hg38",
                    source_spec=_hg38_source_spec(),
                    derived_dir=derived_dir,
                    allow_mapping=True,
                    host_role="approved_mac",
                    download_record=bad_download_record,
                    dry_run=False,
                    policy=POLICY_REFSEQ_ONLY,
                )
            self.assertEqual(json.loads((derived_dir / "derive.json").read_text()), accepted_record)

    def test_duplicated_selected_accession_preserves_prior_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, accepted_record, derived_dir = self._first_accepted_generation(tmp_path)

            (tmp_path / "attempt2").mkdir(exist_ok=True)
            bad_download_record = self._accepted_download_record(
                tmp_path / "attempt2",
                fasta_text=">NC_TEST1.1\nACGTACGT\n>NC_TEST1.1\nACGTACGT\n",
                report_text=_fixture_report(accession="NC_TEST1.1", length=8),
            )
            with self.assertRaises(DerivationError):
                stage_derive(
                    build="hg38",
                    source_spec=_hg38_source_spec(),
                    derived_dir=derived_dir,
                    allow_mapping=True,
                    host_role="approved_mac",
                    download_record=bad_download_record,
                    dry_run=False,
                    policy=POLICY_REFSEQ_ONLY,
                )
            self.assertEqual(json.loads((derived_dir / "derive.json").read_text()), accepted_record)

    def test_length_mismatched_selected_accession_preserves_prior_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, accepted_record, derived_dir = self._first_accepted_generation(tmp_path)

            (tmp_path / "attempt2").mkdir(exist_ok=True)
            bad_download_record = self._accepted_download_record(
                tmp_path / "attempt2",
                fasta_text=">NC_TEST1.1\nACGT\n",
                report_text=_fixture_report(accession="NC_TEST1.1", length=8),
            )
            with self.assertRaises(DerivationError):
                stage_derive(
                    build="hg38",
                    source_spec=_hg38_source_spec(),
                    derived_dir=derived_dir,
                    allow_mapping=True,
                    host_role="approved_mac",
                    download_record=bad_download_record,
                    dry_run=False,
                    policy=POLICY_REFSEQ_ONLY,
                )
            self.assertEqual(json.loads((derived_dir / "derive.json").read_text()), accepted_record)


class Item8And9And10NamespacePreferenceTests(unittest.TestCase):
    """Items 8-10: explicit GenBank-only selection, RefSeq-only never
    falling back to a present GenBank alias, and preference-order behavior
    when a fixture has both accessions.
    """

    def test_explicit_genbank_only_policy_selects_the_genbank_only_record(self):
        # Item 8.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_GCF_SHAPED_REPORT)
            records = {r.sequence_name: r for r in parse_assembly_report(report_path)}
            self.assertEqual(selected_accession(records["HSCHRUN_RANDOM"], POLICY_GENBANK_ONLY), "KI_TESTGB.1")

    def test_refseq_only_policy_never_falls_back_to_present_genbank_alias(self):
        # Item 9.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_GCF_SHAPED_REPORT)
            records = {r.sequence_name: r for r in parse_assembly_report(report_path)}
            self.assertIsNone(selected_accession(records["HSCHRUN_RANDOM"], POLICY_REFSEQ_ONLY))

    def test_preference_order_when_both_accessions_present(self):
        # Item 10: a row with BOTH a RefSeq and a GenBank accession selects
        # whichever namespace is FIRST in accession_preference.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_fixture_report(accession="NC_TEST1.1", length=8))
            records = {r.sequence_name: r for r in parse_assembly_report(report_path)}
            record = records["1"]
            self.assertEqual(selected_accession(record, POLICY_REFSEQ_THEN_GENBANK), "NC_TEST1.1")
            self.assertEqual(selected_accession(record, POLICY_GENBANK_THEN_REFSEQ), "NC_TEST1.1")

    def test_preference_order_selects_genbank_when_listed_first_and_distinct(self):
        # A row where the RefSeq and GenBank accessions genuinely differ:
        # preference order alone decides which one is used.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(
                _REPORT_HEADER
                + "1\tassembled-molecule\t1\tChromosome\tCM_TEST1.1\t=\tNC_TEST1.1\tPrimary Assembly\t8\tchr1\n"
            )
            records = {r.sequence_name: r for r in parse_assembly_report(report_path)}
            record = records["1"]
            self.assertEqual(selected_accession(record, POLICY_REFSEQ_THEN_GENBANK), "NC_TEST1.1")
            self.assertEqual(selected_accession(record, POLICY_GENBANK_THEN_REFSEQ), "CM_TEST1.1")


class Item11And12PolicyValidationTests(unittest.TestCase):
    """Items 11-12: unknown/empty/duplicate accession policy and
    malformed/empty role policy are rejected before any source data access.
    """

    def test_empty_accession_preference_rejected(self):
        policy = dataclasses.replace(POLICY_REFSEQ_ONLY, accession_preference=())
        violations = validate_derived_reference_policy(policy)
        self.assertTrue(any("accession_preference is empty" in v for v in violations))

    def test_unknown_accession_namespace_rejected(self):
        policy = dataclasses.replace(POLICY_REFSEQ_ONLY, accession_preference=("ucsc",))
        violations = validate_derived_reference_policy(policy)
        self.assertTrue(any("unsupported namespace" in v for v in violations))

    def test_duplicate_accession_namespace_rejected(self):
        policy = dataclasses.replace(POLICY_REFSEQ_ONLY, accession_preference=("refseq", "refseq"))
        violations = validate_derived_reference_policy(policy)
        self.assertTrue(any("duplicate namespace" in v for v in violations))

    def test_empty_role_policy_rejected(self):
        policy = dataclasses.replace(POLICY_REFSEQ_ONLY, include_sequence_roles_primary_assembly=())
        violations = validate_derived_reference_policy(policy)
        self.assertTrue(any("include_sequence_roles_primary_assembly is empty" in v for v in violations))

    def test_malformed_role_rejected(self):
        policy = dataclasses.replace(POLICY_REFSEQ_ONLY, include_sequence_roles_primary_assembly=("", "assembled-molecule"))
        violations = validate_derived_reference_policy(policy)
        self.assertTrue(any("malformed role" in v for v in violations))

    def test_unknown_role_rejected(self):
        policy = dataclasses.replace(
            POLICY_REFSEQ_ONLY, include_sequence_roles_primary_assembly=("assembled-molecule", "not-a-real-role")
        )
        violations = validate_derived_reference_policy(policy)
        self.assertTrue(any("unknown role" in v for v in violations))

    def test_duplicate_role_rejected(self):
        policy = dataclasses.replace(
            POLICY_REFSEQ_ONLY,
            include_sequence_roles_primary_assembly=("assembled-molecule", "assembled-molecule"),
        )
        violations = validate_derived_reference_policy(policy)
        self.assertTrue(any("duplicate role" in v for v in violations))

    def test_valid_policy_has_no_violations(self):
        self.assertEqual(validate_derived_reference_policy(POLICY_REFSEQ_ONLY), ())
        self.assertEqual(validate_derived_reference_policy(POLICY_REFSEQ_THEN_GENBANK), ())

    def test_malformed_policy_rejected_before_any_source_data_access_via_runner(self):
        # Integration-level proof: main() must fail closed on a malformed
        # policy BEFORE opening the CSV -- point --csv at a path that does
        # not exist, and confirm the failure is the policy violation
        # SystemExit, never a "file not found" error from actually trying to
        # open/hash the CSV.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_spec = dataclasses.replace(
                load_execution_sources(FIXTURE_EXECUTION_SOURCES),
                derived_reference_policy=dataclasses.replace(
                    load_execution_sources(FIXTURE_EXECUTION_SOURCES).derived_reference_policy,
                    accession_preference=("refseq", "refseq"),
                ),
            )
            nonexistent_csv = tmp_path / "does_not_exist.csv"
            with mock.patch("rbpbench.coordinates.runner.load_execution_sources", return_value=bad_spec):
                with self.assertRaises(SystemExit) as ctx:
                    main(
                        [
                            "--config", str(FIXTURE_CONFIG),
                            "--csv", str(nonexistent_csv),
                            "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                            "--output-dir", str(tmp_path / "out"),
                            "--sources-dir", str(tmp_path / "sources"),
                            "--derived-dir", str(tmp_path / "derived"),
                            "--allow-mapping",
                            "--host-role", "approved_mac",
                            "--build", "hg38",
                            "--stage", "download",
                        ]
                    )
            self.assertIn("derived-reference policy validation failed", str(ctx.exception))


class Item13And14And15RunnerBindingAndFingerprintTests(unittest.TestCase):
    """Items 13-15: stage_derive uses the supplied policy and records/binds
    it; a policy-only change invalidates derive restart state but does not
    invalidate or trigger download; and manifest content changes when
    policy/exclusion evidence changes.
    """

    def test_stage_derive_uses_the_supplied_policy_and_records_it(self):
        # Item 13.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_fasta = tmp_path / "source.fna"
            source_fasta.write_text(_gcf_shaped_source_fasta_text())
            report_path = tmp_path / "report.txt"
            report_path.write_text(_GCF_SHAPED_REPORT)
            download_record = {
                "executed": True,
                "fasta": {"dest_path": str(source_fasta), "sha256": sha256_file(source_fasta)},
                "assembly_report": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
                "checksum_listing": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
            }
            record = stage_derive(
                build="hg38",
                source_spec=_hg38_source_spec(),
                derived_dir=tmp_path / "derived",
                allow_mapping=True,
                host_role="approved_mac",
                download_record=download_record,
                dry_run=False,
                policy=POLICY_REFSEQ_ONLY,
            )
            self.assertTrue(record["executed"])
            self.assertEqual(record["derived_reference_policy"]["accession_preference"], ["refseq"])
            manifest = json.loads(Path(record["reference_manifest_path"]).read_text())
            self.assertNotIn("KI_TESTGB.1", manifest["contigs"])
            self.assertEqual(manifest["exclusion_summary"]["count"], 1)

    def test_policy_only_change_invalidates_derive_but_not_download(self):
        # Item 14.
        fasta_body_gz = gzip.compress(b">NC_TEST1.1\n" + b"ACGT" * 5 + b"\n")  # 20 nt
        report_body = _fixture_report(accession="NC_TEST1.1", length=20)
        fasta_md5 = hashlib.md5(fasta_body_gz).hexdigest()
        report_md5 = hashlib.md5(report_body.encode()).hexdigest()
        spec = _hg38_source_spec()
        adjusted = dataclasses.replace(
            spec,
            fasta_upstream_md5=fasta_md5,
            fasta_compressed_byte_size=len(fasta_body_gz),
            assembly_report_md5=report_md5,
        )

        def transport(url, dest_path):
            if "fna.gz" in url:
                dest_path.write_bytes(fasta_body_gz)
            elif "md5" in url:
                dest_path.write_text(
                    f"{fasta_md5}  ./{adjusted.fasta_remote_basename}\n"
                    f"{report_md5}  ./{adjusted.assembly_report_remote_basename}\n"
                )
            else:
                dest_path.write_text(report_body)

        base_spec = load_execution_sources(FIXTURE_EXECUTION_SOURCES)
        spec_policy_a = dataclasses.replace(
            base_spec,
            reference_sources={"hg38": adjusted, "hg19": adjusted},
            derived_reference_policy=POLICY_REFSEQ_THEN_GENBANK,
        )
        spec_policy_b = dataclasses.replace(spec_policy_a, derived_reference_policy=POLICY_REFSEQ_ONLY)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            sources_dir = tmp_path / "sources"
            derived_dir = tmp_path / "derived"
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

            with mock.patch("rbpbench.coordinates.runner.urllib_transport", transport):
                with mock.patch("rbpbench.coordinates.runner.load_execution_sources", return_value=spec_policy_a):
                    with _approved_host_context():
                        main([*common, "--stage", "download"])
                        main([*common, "--stage", "derive"])

                download_record_1 = json.loads((sources_dir / adjusted.assembly / "download.json").read_text())
                derive_record_1 = json.loads((derived_dir / "hg38" / "derive.json").read_text())
                self.assertTrue(download_record_1["executed"])
                self.assertTrue(derive_record_1["executed"])

                # Re-run BOTH stages again, this time with a policy-only
                # change (same reference source, same local-input hashes).
                with mock.patch("rbpbench.coordinates.runner.load_execution_sources", return_value=spec_policy_b):
                    with _approved_host_context():
                        main([*common, "--stage", "download"])
                        main([*common, "--stage", "derive"])

            download_record_2 = json.loads((sources_dir / adjusted.assembly / "download.json").read_text())
            derive_record_2 = json.loads((derived_dir / "hg38" / "derive.json").read_text())

            # Download must NOT be invalidated/repeated: same accepted
            # generation path as before.
            self.assertEqual(download_record_1["fasta"]["dest_path"], download_record_2["fasta"]["dest_path"])
            # Derive MUST be invalidated and re-run: a fresh generation with
            # a different selected-contig set (policy_b excludes nothing
            # extra here since this fixture has no GenBank-only row, but the
            # generation path itself must differ, proving a real re-run
            # rather than a silent skip).
            self.assertNotEqual(derive_record_1["output_fasta"], derive_record_2["output_fasta"])
            self.assertEqual(derive_record_2["derived_reference_policy"]["accession_preference"], ["refseq"])

    def test_manifest_content_changes_when_policy_and_exclusion_evidence_changes(self):
        # Item 15.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.txt"
            report_path.write_text(_GCF_SHAPED_REPORT)
            fasta_path = tmp_path / "source.fna"
            fasta_path.write_text(_gcf_shaped_source_fasta_text())

            def _manifest_for(policy: DerivedReferencePolicy, output_name: str) -> dict:
                derivation = derive_reference_fasta(
                    source_fasta=fasta_path,
                    assembly_report=report_path,
                    output_fasta=tmp_path / output_name,
                    policy=policy,
                )
                return build_reference_manifest(
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

            manifest_a = _manifest_for(POLICY_REFSEQ_ONLY, "policy_a.fna")
            # Same selection outcome (this tiny fixture has no non-nuclear
            # row either way), but a genuinely different policy value --
            # isolates that ``effective_policy``/manifest content reflects
            # the POLICY itself, not merely whatever it happened to select.
            policy_b = dataclasses.replace(POLICY_REFSEQ_ONLY, include_non_nuclear_assembled_molecule=False)
            manifest_b = _manifest_for(policy_b, "policy_b.fna")
            self.assertEqual(manifest_a["contigs"], manifest_b["contigs"])
            self.assertNotEqual(manifest_a["effective_policy"], manifest_b["effective_policy"])
            self.assertNotEqual(manifest_content_sha256(manifest_a), manifest_content_sha256(manifest_b))

            # And, independently, a policy change that actually changes the
            # EXCLUSION evidence also changes manifest content (item 1-3's
            # fixture: the GenBank-only row is namespace-unrepresented under
            # REFSEQ_ONLY but selected under GENBANK_ONLY, for a row whose
            # GenBank accession happens to be present in the FASTA).
            gcf_report = tmp_path / "gcf_report.txt"
            gcf_report.write_text(_GCF_SHAPED_REPORT)
            gcf_fasta = tmp_path / "gcf_source.fna"
            gcf_fasta.write_text(">NC_TEST1.1\n" + "A" * 40 + "\n>KI_TESTGB.1\n" + "C" * 16 + "\n")

            def _gcf_manifest_for(policy: DerivedReferencePolicy, output_name: str) -> dict:
                derivation = derive_reference_fasta(
                    source_fasta=gcf_fasta,
                    assembly_report=gcf_report,
                    output_fasta=tmp_path / output_name,
                    policy=policy,
                )
                return build_reference_manifest(
                    derivation,
                    build_id="hg38",
                    assembly_accession="GCF_TEST38",
                    source_url="https://example.invalid/hg38.fna.gz",
                    source_fasta_compressed=gcf_fasta,
                    source_fasta_compressed_upstream_md5="a" * 32,
                    assembly_report=gcf_report,
                    assembly_report_upstream_md5="b" * 32,
                    derivation_command="derive_reference_fasta(...)",
                    git_commit="deadbeef",
                )

            manifest_refseq_only = _gcf_manifest_for(POLICY_REFSEQ_ONLY, "gcf_refseq_only.fna")
            manifest_refseq_then_genbank = _gcf_manifest_for(POLICY_REFSEQ_THEN_GENBANK, "gcf_refseq_then_genbank.fna")
            self.assertEqual(manifest_refseq_only["exclusion_summary"]["count"], 1)
            self.assertEqual(manifest_refseq_then_genbank["exclusion_summary"]["count"], 0)
            self.assertNotEqual(
                manifest_content_sha256(manifest_refseq_only),
                manifest_content_sha256(manifest_refseq_then_genbank),
            )


class Item16WriteFailureRetentionTests(unittest.TestCase):
    """Item 16: candidate and selection-record write failures retain the
    prior accepted generation under the new (policy/exclusion) fields.
    """

    def test_derive_selection_write_failure_retains_prior_generation_with_policy_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_fasta = tmp_path / "source.fna"
            source_fasta.write_text(_gcf_shaped_source_fasta_text())
            report_path = tmp_path / "report.txt"
            report_path.write_text(_GCF_SHAPED_REPORT)
            download_record = {
                "executed": True,
                "fasta": {"dest_path": str(source_fasta), "sha256": sha256_file(source_fasta)},
                "assembly_report": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
                "checksum_listing": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
            }
            derived_dir = tmp_path / "derived"

            first = stage_derive(
                build="hg38",
                source_spec=_hg38_source_spec(),
                derived_dir=derived_dir,
                allow_mapping=True,
                host_role="approved_mac",
                download_record=download_record,
                dry_run=False,
                policy=POLICY_REFSEQ_ONLY,
            )
            self.assertTrue(first["executed"])
            self.assertIn("derived_reference_policy", first)
            original_record = json.loads((derived_dir / "derive.json").read_text())
            generations_before = set((derived_dir / "generations").glob("*"))

            with mock.patch("rbpbench.coordinates.runner._guarded_write_record", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    stage_derive(
                        build="hg38",
                        source_spec=_hg38_source_spec(),
                        derived_dir=derived_dir,
                        allow_mapping=True,
                        host_role="approved_mac",
                        download_record=download_record,
                        dry_run=False,
                        policy=POLICY_REFSEQ_ONLY,
                    )

            self.assertEqual(json.loads((derived_dir / "derive.json").read_text()), original_record)
            self.assertEqual(
                json.loads((derived_dir / "derive.json").read_text())["derived_reference_policy"]["accession_preference"],
                ["refseq"],
            )
            generations_after = set((derived_dir / "generations").glob("*"))
            self.assertEqual(generations_before, generations_after)


if __name__ == "__main__":
    unittest.main()
