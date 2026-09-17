import gzip
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.runner import STAGES, main

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CONFIG = REPO_ROOT / "tests" / "fixtures" / "coordinates" / "tiny_coordinate_feasibility.toml"
FIXTURE_CSV = REPO_ROOT / "tests" / "fixtures" / "coordinates" / "tiny_coordinates_dataset.csv"


# Tiny fake mapper/matcher executables (bash + awk, no human data): a
# fixture-only stand-in for review R3's "genuinely capable of Task 001B
# execution when explicitly authorized" requirement. Each emits synthetic
# SAM/BED output derived only from whatever tiny reads FASTA this test
# supplies, never touching the real dataset or a real reference.
_FAKE_BWA = """#!/bin/bash
if [ "$#" -le 0 ]; then
  echo "Version: 0.7.19"
  exit 0
fi
reads="${@: -1}"
awk '
  /^>/ { if (name != "") print name "\\t0\\tchr1\\t1\\t60\\t" length(seq) "M\\t*\\t0\\t0\\t" seq "\\t*\\tNM:i:0\\tAS:i:" length(seq); name=substr($0,2); seq=""; next }
  { seq = seq $0 }
  END { if (name != "") print name "\\t0\\tchr1\\t1\\t60\\t" length(seq) "M\\t*\\t0\\t0\\t" seq "\\t*\\tNM:i:0\\tAS:i:" length(seq) }
' "$reads"
"""

_FAKE_MINIMAP2 = """#!/bin/bash
if [ "$#" -le 0 ]; then
  echo "2.31"
  exit 0
fi
for arg in "$@"; do
  if [ "$arg" == "--version" ]; then
    echo "2.31"
    exit 0
  fi
done
reads="${@: -1}"
awk '
  /^>/ { if (name != "") print name "\\t0\\tchr1\\t1\\t60\\t" length(seq) "=\\t*\\t0\\t0\\t" seq "\\t*\\tAS:i:" length(seq); name=substr($0,2); seq=""; next }
  { seq = seq $0 }
  END { if (name != "") print name "\\t0\\tchr1\\t1\\t60\\t" length(seq) "=\\t*\\t0\\t0\\t" seq "\\t*\\tAS:i:" length(seq) }
' "$reads"
"""

_FAKE_SEQKIT = """#!/bin/bash
if [ "$#" -le 0 ]; then
  echo "seqkit v2.13.0"
  exit 0
fi
if [ "$1" == "version" ] && [ "$#" -eq 1 ]; then
  echo "seqkit v2.13.0"
  exit 0
fi
reads="${@: -2:1}"
awk '
  /^>/ { if (name != "") print "chr1\\t0\\t" length(seq) "\\t" name "\\t.\\t+"; name=substr($0,2); seq=""; next }
  { seq = seq $0 }
  END { if (name != "") print "chr1\\t0\\t" length(seq) "\\t" name "\\t.\\t+" }
' "$reads"
"""


def _write_fake_executable(bin_dir: Path, name: str, source: str) -> None:
    path = bin_dir / name
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    # macOS does a one-time, slow (tens of seconds, occasionally longer under
    # load) first-launch security check for a freshly created executable. Pay
    # that cost here, retrying with a generous timeout until the executable
    # actually responds, so this cannot race the pipeline's own much tighter
    # subprocess timeouts and make an otherwise-deterministic test flaky.
    for attempt in range(3):
        try:
            subprocess.run([str(path)], capture_output=True, timeout=150)
            return
        except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            if attempt == 2:
                raise


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


class RunnerRestartTests(unittest.TestCase):
    """Regression coverage for review R4/R10: an interrupted run must be able
    to resume a later stage from a brand-new process, not merely later calls
    within the same one.
    """

    def test_sample_then_separate_decode_invocation_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
            ]
            # First "process": only the sample stage runs, then exits.
            main([*common, "--stage", "sample"])
            self.assertTrue((output_dir / "sample_state.json").exists())

            # A brand-new call to main() has no leftover Python state from
            # the call above; it can only see what was persisted to disk.
            main([*common, "--stage", "decode"])
            self.assertTrue((output_dir / "sample_sequences.fasta").exists())
            fasta_text = (output_dir / "sample_sequences.fasta").read_text()
            self.assertEqual(fasta_text.count(">"), 20)

    def test_align_then_separate_report_invocation_sees_real_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\nACGT\n")

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", str(reference),
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env):
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                main([*common, "--stage", "exact_match"])
                # A brand-new "process" for report: align/exact_match results
                # must be reloaded from align.json/exact_match.json, not lost.
                main([*common, "--stage", "report"])

            report = json.loads((output_dir / "report.json").read_text())
            self.assertEqual(report["reconciliation"]["status"], "passed")
            # Outputs are flattened directly under output_dir (matching every
            # other stage's output_dir / Path(cfg.outputs.X).name convention).
            mappings_path = output_dir / "mappings.tsv.gz"
            self.assertTrue(mappings_path.exists())
            with gzip.open(mappings_path, "rt") as handle:
                lines = handle.read().splitlines()
            self.assertGreater(len(lines), 1)


class RunnerRealMappingCapabilityTests(unittest.TestCase):
    """Review R3: the runner must be genuinely capable of executing real
    mapping/exact-match when explicitly authorized, guarded by subprocess.run
    with shell=False, using tiny fake executables rather than any human data.
    """

    def _run_full_authorized_pipeline(self, output_dir: Path, bin_dir: Path) -> None:
        _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
        _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
        _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
        reference = output_dir / "reference.fasta"
        reference.write_text(">chr1\nACGT\n")

        argv = [
            "--config", str(FIXTURE_CONFIG),
            "--csv", str(FIXTURE_CSV),
            "--output-dir", str(output_dir),
            "--allow-mapping",
            "--host-role", "approved_mac",
            "--reference", str(reference),
            "--build", "hg38",
        ]
        # "preflight" is intentionally excluded: it independently enforces
        # the approved-host hardware/tool contract (review R5) and is
        # exercised on its own in test_coordinates_preflight.py.
        for stage in ("sample", "decode", "controls", "align", "exact_match", "report"):
            argv.extend(["--stage", stage])
        main(argv)

    def test_real_mapping_executes_and_produces_classified_mappings(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env):
                self._run_full_authorized_pipeline(output_dir, bin_dir)

            align_record = json.loads((output_dir / "align.json").read_text())
            self.assertTrue(align_record["executed"])
            exact_match_record = json.loads((output_dir / "exact_match.json").read_text())
            self.assertTrue(exact_match_record["executed"])

            state = json.loads((output_dir / "state.json").read_text())
            self.assertTrue(state["mapping_executed"]["align"])
            self.assertTrue(state["mapping_executed"]["exact_match"])

            mappings_path = output_dir / "mappings.tsv.gz"
            with gzip.open(mappings_path, "rt") as handle:
                rows = handle.read().splitlines()
            header = rows[0].split("\t")
            body = [dict(zip(header, line.split("\t"))) for line in rows[1:]]
            # Every fake read is a perfect full-length match: primary mode
            # must classify it exact_unique (BWA perfect + SeqKit single hit).
            primary_categories = {r["category"] for r in body if r["mode"] == "primary" and r["is_control"] == "False"}
            self.assertEqual(primary_categories, {"exact_unique"})

    def test_planned_but_skipped_mapping_is_not_recorded_as_executed(self):
        # Review R4 regression: a planning-only / dry-run stage must not be
        # confused with a completed real mapping run.
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--output-dir", str(output_dir),
                    "--stage", "all",
                    "--dry-run",
                ]
            )
            state = json.loads((output_dir / "state.json").read_text())
            self.assertIn("align", state["completed_stages"])  # the stage ran (planned)
            self.assertFalse(state["mapping_executed"]["align"])  # but never executed real mapping
            self.assertFalse(state["mapping_executed"]["exact_match"])

            report = json.loads((output_dir / "report.json").read_text())
            self.assertEqual(report["reconciliation"]["status"], "not_evaluated")
            self.assertFalse(report["reconciliation"]["passed"])


if __name__ == "__main__":
    unittest.main()
