import hashlib
import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.execution_sources import (
    LOCAL_INPUT_KEYS,
    load_execution_sources,
    verify_local_inputs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_SPEC_PATH = REPO_ROOT / "configs" / "coordinate_execution_sources.toml"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_fixture_spec(tmp: Path, *, hashes: dict[str, str]) -> Path:
    spec_path = tmp / "tiny_execution_sources.toml"
    spec_path.write_text(
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
fasta_compressed_byte_size = 123
fasta_upstream_md5 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
assembly_report_url = "https://example.invalid/hg38_report.txt"
assembly_report_md5 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
md5checksums_url = "https://example.invalid/hg38_md5.txt"

[reference_sources.hg19]
assembly = "TestAssembly37"
refseq_assembly_accession = "GCF_TEST37"
fasta_url = "https://example.invalid/hg19.fna.gz"
fasta_compressed_byte_size = 456
fasta_upstream_md5 = "cccccccccccccccccccccccccccccccc"
assembly_report_url = "https://example.invalid/hg19_report.txt"
assembly_report_md5 = "dddddddddddddddddddddddddddddddd"
md5checksums_url = "https://example.invalid/hg19_md5.txt"

[derived_reference_policy]
include_sequence_roles_primary_assembly = ["assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold"]
include_non_nuclear_assembled_molecule = true
accession_preference = ["refseq", "genbank"]
"""
    )
    return spec_path


class ExecutionSourcesLoadTests(unittest.TestCase):
    def test_real_config_loads_and_names_all_four_local_inputs(self):
        spec = load_execution_sources(REAL_SPEC_PATH)
        self.assertEqual(set(spec.local_inputs), set(LOCAL_INPUT_KEYS))
        self.assertEqual(set(spec.reference_sources), {"hg38", "hg19"})
        self.assertIn("assembled-molecule", spec.derived_reference_policy.include_sequence_roles_primary_assembly)

    def test_real_config_hashes_match_frozen_task_document(self):
        spec = load_execution_sources(REAL_SPEC_PATH)
        self.assertEqual(
            spec.local_inputs["dataset_csv"].sha256,
            "982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945",
        )
        self.assertEqual(spec.reference_sources["hg38"].fasta_upstream_md5, "c30471567037b2b2389d43c908c653e1")
        self.assertEqual(spec.reference_sources["hg19"].refseq_assembly_accession, "GCF_000001405.25")


class VerifyLocalInputsTests(unittest.TestCase):
    """Fixture-only coverage (never the real 724-MB CSV) of the fail-closed
    expected-vs-observed comparison that must run before the real CSV is
    opened for row-by-row reading (B1 required item 1).
    """

    def test_matching_fixture_hashes_pass_with_no_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "dataset.csv"
            audit_path = tmp_path / "audit.json"
            proteins_path = tmp_path / "proteins.tsv"
            study_path = tmp_path / "study.toml"
            csv_path.write_text("sample_id,sequence\nrow_0,ACGT\n")
            audit_path.write_text('{"ok": true}\n')
            proteins_path.write_text("1\tPROT1\n")
            study_path.write_text("seed = 1\n")

            hashes = {
                "dataset_csv": _sha256(csv_path.read_bytes()),
                "dataset_audit": _sha256(audit_path.read_bytes()),
                "proteins_config": _sha256(proteins_path.read_bytes()),
                "study_config": _sha256(study_path.read_bytes()),
            }
            spec = load_execution_sources(_write_fixture_spec(tmp_path, hashes=hashes))

            violations = verify_local_inputs(
                spec,
                paths={
                    "dataset_csv": csv_path,
                    "dataset_audit": audit_path,
                    "proteins_config": proteins_path,
                    "study_config": study_path,
                },
            )
            self.assertEqual(violations, ())

    def test_single_byte_change_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "dataset.csv"
            audit_path = tmp_path / "audit.json"
            proteins_path = tmp_path / "proteins.tsv"
            study_path = tmp_path / "study.toml"
            csv_path.write_text("sample_id,sequence\nrow_0,ACGT\n")
            audit_path.write_text('{"ok": true}\n')
            proteins_path.write_text("1\tPROT1\n")
            study_path.write_text("seed = 1\n")

            hashes = {
                "dataset_csv": _sha256(csv_path.read_bytes()),
                "dataset_audit": _sha256(audit_path.read_bytes()),
                "proteins_config": _sha256(proteins_path.read_bytes()),
                "study_config": _sha256(study_path.read_bytes()),
            }
            spec = load_execution_sources(_write_fixture_spec(tmp_path, hashes=hashes))

            # Flip one byte after freezing the expected hash.
            csv_path.write_text("sample_id,sequence\nrow_0,ACGA\n")

            violations = verify_local_inputs(
                spec,
                paths={
                    "dataset_csv": csv_path,
                    "dataset_audit": audit_path,
                    "proteins_config": proteins_path,
                    "study_config": study_path,
                },
            )
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].key, "dataset_csv")

    def test_missing_file_is_a_violation_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hashes = {k: "0" * 64 for k in LOCAL_INPUT_KEYS}
            spec = load_execution_sources(_write_fixture_spec(tmp_path, hashes=hashes))
            violations = verify_local_inputs(
                spec,
                paths={
                    "dataset_csv": tmp_path / "does_not_exist.csv",
                    "dataset_audit": tmp_path / "does_not_exist.json",
                    "proteins_config": tmp_path / "does_not_exist.tsv",
                    "study_config": tmp_path / "does_not_exist.toml",
                },
            )
            self.assertEqual(len(violations), 4)

    def test_missing_path_argument_is_a_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hashes = {k: "0" * 64 for k in LOCAL_INPUT_KEYS}
            spec = load_execution_sources(_write_fixture_spec(tmp_path, hashes=hashes))
            violations = verify_local_inputs(spec, paths={})
            self.assertEqual({v.key for v in violations}, set(LOCAL_INPUT_KEYS))


if __name__ == "__main__":
    unittest.main()
