import json
import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.runner import STAGES, main

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CONFIG = REPO_ROOT / "tests" / "fixtures" / "coordinates" / "tiny_coordinate_feasibility.toml"
FIXTURE_CSV = REPO_ROOT / "tests" / "fixtures" / "coordinates" / "tiny_coordinates_dataset.csv"


class RunnerIntegrationTests(unittest.TestCase):
    def test_full_pipeline_on_fixtures_never_touches_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            main(
                [
                    "--config",
                    str(FIXTURE_CONFIG),
                    "--csv",
                    str(FIXTURE_CSV),
                    "--output-dir",
                    str(output_dir),
                    "--stage",
                    "all",
                    "--dry-run",
                ]
            )

            self.assertTrue((output_dir / "sample_ids.tsv").exists())
            self.assertTrue((output_dir / "sample_sequences.fasta").exists())
            self.assertTrue((output_dir / "control_sequences.fasta").exists())
            self.assertTrue((output_dir / "report.json").exists())
            self.assertTrue((output_dir / "report.md").exists())
            self.assertTrue((output_dir / "dry_run.json").exists())

            sample_lines = (output_dir / "sample_ids.tsv").read_text().splitlines()
            self.assertEqual(len(sample_lines), 21)  # header + 20 rows

            align_record = json.loads((output_dir / "align.json").read_text())
            self.assertFalse(align_record["executed"])
            self.assertIsNotNone(align_record["skip_reason"])

            exact_match_record = json.loads((output_dir / "exact_match.json").read_text())
            self.assertFalse(exact_match_record["executed"])

            report = json.loads((output_dir / "report.json").read_text())
            self.assertEqual(report["sample"]["total"], 20)
            self.assertIsNone(report["phase2_recommendation"])

            state = json.loads((output_dir / "state.json").read_text())
            self.assertEqual(state["completed_stages"], list(STAGES))

    def test_rerun_without_force_skips_completed_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            argv = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
                "--stage", "all",
            ]
            main(argv)
            report_path = output_dir / "report.json"
            first_mtime = report_path.stat().st_mtime_ns

            main(argv)  # re-run without --force
            self.assertEqual(report_path.stat().st_mtime_ns, first_mtime)

            state = json.loads((output_dir / "state.json").read_text())
            self.assertEqual(state["completed_stages"], list(STAGES))  # not duplicated

    def test_mapping_is_never_executed_without_explicit_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--output-dir", str(output_dir),
                    "--stage", "align",
                    "--stage", "exact_match",
                ]
            )
            align_record = json.loads((output_dir / "align.json").read_text())
            self.assertFalse(align_record["executed"])
            self.assertIn("--allow-mapping", align_record["skip_reason"])


if __name__ == "__main__":
    unittest.main()
