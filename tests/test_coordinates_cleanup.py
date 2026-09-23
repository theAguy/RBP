import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.cleanup import (
    CleanupRefused,
    execute_index_cleanup,
    plan_index_cleanup,
)


class PlanIndexCleanupTests(unittest.TestCase):
    """All cleanup tests operate only inside a newly created tiny temporary
    directory (B1 required item 8's cleanup-safety mandate).
    """

    def test_plans_deletion_of_a_real_index_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            index_dir = tmp_path / "indices" / "hg38"
            index_dir.mkdir(parents=True)
            (index_dir / "hg38.bwt").write_bytes(b"fake bwt bytes")
            (index_dir / "hg38.mmi").write_bytes(b"fake mmi bytes")

            plan = plan_index_cleanup(index_dir)
            self.assertEqual(plan.resolved_target, index_dir.resolve())
            self.assertEqual(len(plan.files), 2)

    def test_refuses_missing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CleanupRefused):
                plan_index_cleanup(Path(tmp) / "indices" / "does_not_exist")

    def test_refuses_a_file_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            not_a_dir = tmp_path / "not_a_dir"
            not_a_dir.write_text("x")
            with self.assertRaises(CleanupRefused):
                plan_index_cleanup(not_a_dir)

    def test_refuses_a_symlinked_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            real_dir = tmp_path / "real_indices"
            real_dir.mkdir()
            (real_dir / "important.txt").write_text("do not delete me")
            symlink_target = tmp_path / "indices_symlink"
            symlink_target.symlink_to(real_dir, target_is_directory=True)

            with self.assertRaises(CleanupRefused):
                plan_index_cleanup(symlink_target)
            # Nothing was deleted.
            self.assertTrue((real_dir / "important.txt").is_file())

    def test_refuses_target_equal_to_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "artifacts"
            output_dir.mkdir()
            with self.assertRaises(CleanupRefused):
                plan_index_cleanup(output_dir, output_dir=output_dir)

    def test_refuses_target_that_contains_the_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            parent = tmp_path / "shared_parent"
            output_dir = parent / "artifacts"
            output_dir.mkdir(parents=True)
            with self.assertRaises(CleanupRefused):
                plan_index_cleanup(parent, output_dir=output_dir)

    def test_refuses_target_that_is_inside_the_reference_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference_dir = tmp_path / "references" / "derived" / "hg38"
            reference_dir.mkdir(parents=True)
            reference_fasta = reference_dir / "reference.fna"
            reference_fasta.write_text(">chr1\nACGT\n")
            index_dir = reference_dir / "indices_accidentally_nested"
            index_dir.mkdir()
            with self.assertRaises(CleanupRefused):
                plan_index_cleanup(index_dir, reference=reference_fasta)

    def test_accepts_a_narrow_sibling_index_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference_fasta = tmp_path / "references" / "derived" / "hg38" / "reference.fna"
            reference_fasta.parent.mkdir(parents=True)
            reference_fasta.write_text(">chr1\nACGT\n")
            output_dir = tmp_path / "artifacts"
            output_dir.mkdir()
            index_dir = tmp_path / "indices" / "hg38"
            index_dir.mkdir(parents=True)
            (index_dir / "hg38.bwt").write_bytes(b"x")

            plan = plan_index_cleanup(index_dir, reference=reference_fasta, output_dir=output_dir)
            self.assertEqual(len(plan.files), 1)


class ExecuteIndexCleanupTests(unittest.TestCase):
    def test_refuses_without_index_manifest_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "indices" / "hg38"
            index_dir.mkdir(parents=True)
            (index_dir / "hg38.bwt").write_bytes(b"x")
            with self.assertRaises(CleanupRefused):
                execute_index_cleanup(
                    index_dir,
                    index_manifest_present=False,
                    mapping_outputs_present=True,
                    reconciliation_passed=True,
                )
            self.assertTrue(index_dir.exists())

    def test_refuses_without_successful_mapping_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "indices" / "hg38"
            index_dir.mkdir(parents=True)
            with self.assertRaises(CleanupRefused):
                execute_index_cleanup(
                    index_dir,
                    index_manifest_present=True,
                    mapping_outputs_present=False,
                    reconciliation_passed=True,
                )
            self.assertTrue(index_dir.exists())

    def test_refuses_without_passed_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "indices" / "hg38"
            index_dir.mkdir(parents=True)
            with self.assertRaises(CleanupRefused):
                execute_index_cleanup(
                    index_dir,
                    index_manifest_present=True,
                    mapping_outputs_present=True,
                    reconciliation_passed=False,
                )
            self.assertTrue(index_dir.exists())

    def test_deletes_exactly_the_index_directory_when_all_evidence_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            index_dir = tmp_path / "indices" / "hg38"
            index_dir.mkdir(parents=True)
            (index_dir / "hg38.bwt").write_bytes(b"x")
            sibling = tmp_path / "indices" / "hg19"
            sibling.mkdir()
            (sibling / "hg19.bwt").write_bytes(b"y")

            execute_index_cleanup(
                index_dir,
                index_manifest_present=True,
                mapping_outputs_present=True,
                reconciliation_passed=True,
            )
            self.assertFalse(index_dir.exists())
            # The sibling build's index directory is untouched.
            self.assertTrue((sibling / "hg19.bwt").is_file())


if __name__ == "__main__":
    unittest.main()
