import contextlib
import gzip
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.alignment import build_candidate_loci, parse_sam_line
from rbpbench.coordinates.config import load_config
from rbpbench.coordinates.runner import _locus_detail, build_mapping_rows, main, stage_combined_report
from rbpbench.coordinates.sampling import SamplingResult
from rbpbench.data.audit import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CONFIG = REPO_ROOT / "tests" / "fixtures" / "coordinates" / "tiny_coordinate_feasibility.toml"
FIXTURE_CSV = REPO_ROOT / "tests" / "fixtures" / "coordinates" / "tiny_coordinates_dataset.csv"
# B1-R6: --execution-sources is now mandatory for any invocation that reads
# the CSV, so every fixture-based test must supply its own fixture spec
# rather than relying on a silent production bypass.
FIXTURE_EXECUTION_SOURCES = REPO_ROOT / "tests" / "fixtures" / "coordinates" / "tiny_execution_sources.toml"


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

# A tool reporting an unpinned version: used to prove that even an
# otherwise-authorized real-mapping attempt is refused when the fresh,
# binding preflight check (review item 1) rejects it.
_FAKE_BWA_WRONG_VERSION = _FAKE_BWA.replace("Version: 0.7.19", "Version: 0.7.17")


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


def _write_matching_execution_sources(
    path: Path, *, dataset_csv: Path, dataset_audit: Path, proteins_config: Path, study_config: Path
) -> Path:
    """B1-R6: build a fixture execution-source spec whose four local-input
    hashes match whatever fixture files a specific test is actually using
    (which may differ from the shared FIXTURE_EXECUTION_SOURCES when a test
    overrides --dataset-audit/--proteins-config/--csv/--config with its own
    tiny files, or deliberately mutates one at the same path across calls).
    """
    path.write_text(
        f"""
git_base_commit = "fixture"
[local_inputs.dataset_csv]
path = "{dataset_csv}"
sha256 = "{sha256_file(dataset_csv)}"
[local_inputs.dataset_audit]
path = "{dataset_audit}"
sha256 = "{sha256_file(dataset_audit)}"
[local_inputs.proteins_config]
path = "{proteins_config}"
sha256 = "{sha256_file(proteins_config)}"
[local_inputs.study_config]
path = "{study_config}"
sha256 = "{sha256_file(study_config)}"
[reference_sources.hg38]
assembly = "T38"
refseq_assembly_accession = "GCF_T38"
fasta_url = "https://example.invalid/hg38.fna.gz"
fasta_compressed_byte_size = 1
fasta_upstream_md5 = "{'a' * 32}"
assembly_report_url = "https://example.invalid/hg38_report.txt"
assembly_report_md5 = "{'b' * 32}"
md5checksums_url = "https://example.invalid/hg38_md5.txt"
[reference_sources.hg19]
assembly = "T37"
refseq_assembly_accession = "GCF_T37"
fasta_url = "https://example.invalid/hg19.fna.gz"
fasta_compressed_byte_size = 1
fasta_upstream_md5 = "{'c' * 32}"
assembly_report_url = "https://example.invalid/hg19_report.txt"
assembly_report_md5 = "{'d' * 32}"
md5checksums_url = "https://example.invalid/hg19_md5.txt"
[derived_reference_policy]
include_sequence_roles_primary_assembly = ["assembled-molecule"]
include_non_nuclear_assembled_molecule = true
accession_preference = ["refseq", "genbank"]
"""
    )
    return path


def _write_reference_manifest(manifest_path: Path, *, build: str, reference: Path) -> Path:
    """Write a valid reference manifest matching ``reference``'s real hash
    and size — required (review item 4b) for any real align/exact_match
    attempt.
    """
    manifest_path.write_text(
        json.dumps(
            {
                "build_id": build,
                "assembly_accession": f"TEST-{build}",
                "source_url": "https://example.invalid/reference.fa.gz",
                "contig_categories_included": ["chromosome"],
                "byte_size": reference.stat().st_size,
                "sha256": sha256_file(reference),
            }
        )
    )
    return manifest_path


@contextlib.contextmanager
def _approved_host_context(*, ram_gib: float = 32.0, free_disk_gib: float = 200.0):
    """Make ``run_preflight`` see a passing approved-mac host regardless of
    the machine actually running this test suite (a real Mac or Claude's
    constrained Linux dev VM per the executor handoff) — the same approach
    ``test_coordinates_preflight.py`` uses, applied around real-mapping
    integration tests so they stay host-independent.
    """
    with mock.patch("rbpbench.coordinates.preflight.platform.system", return_value="Darwin"), mock.patch(
        "rbpbench.coordinates.preflight.platform.machine", return_value="x86_64"
    ), mock.patch(
        "rbpbench.coordinates.preflight.detect_physical_ram_gib", return_value=ram_gib
    ), mock.patch(
        "rbpbench.coordinates.preflight.detect_free_disk_gib", return_value=free_disk_gib
    ):
        yield


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
                    "--execution-sources",
                    str(FIXTURE_EXECUTION_SOURCES),
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
            self.assertTrue((output_dir / "provenance.json").exists())

            sample_lines = (output_dir / "sample_ids.tsv").read_text().splitlines()
            self.assertEqual(len(sample_lines), 21)  # header + 20 rows

            for build in ("hg38", "hg19"):
                align_record = json.loads((output_dir / build / "align.json").read_text())
                self.assertFalse(align_record["executed"])
                self.assertIsNotNone(align_record["skip_reason"])

                exact_match_record = json.loads((output_dir / build / "exact_match.json").read_text())
                self.assertFalse(exact_match_record["executed"])

            combined_report = json.loads((output_dir / "report.json").read_text())
            self.assertEqual(sorted(combined_report["builds"]), ["hg19", "hg38"])
            self.assertIsNone(combined_report["phase2_recommendation"])

            state = json.loads((output_dir / "state.json").read_text())
            expected_keys = {"preflight", "sample", "decode", "controls", "combined_report"} | {
                f"{stage}:{build}"
                for stage in ("download", "derive", "index", "align", "exact_match", "report")
                for build in ("hg38", "hg19")
            }
            self.assertEqual(set(state["completed_stages"]), expected_keys)

    def test_rerun_without_force_skips_completed_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            argv = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--stage", "all",
            ]
            main(argv)
            report_path = output_dir / "report.json"
            first_mtime = report_path.stat().st_mtime_ns

            main(argv)  # re-run without --force
            self.assertEqual(report_path.stat().st_mtime_ns, first_mtime)

    def test_mapping_is_never_executed_without_explicit_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(output_dir),
                    "--stage", "align",
                    "--stage", "exact_match",
                ]
            )
            for build in ("hg38", "hg19"):
                align_record = json.loads((output_dir / build / "align.json").read_text())
                self.assertFalse(align_record["executed"])
                self.assertIn("--allow-mapping", align_record["skip_reason"])


class AuthorizedDryRunGuaranteeTests(unittest.TestCase):
    """Regression coverage for review item 2: --dry-run must guarantee that
    no external mapping/exact-match subprocess can ever execute, even when
    every authorization flag is also given, and a dry-run/skip must never be
    recorded in a way that blocks a later real run of the same stage.
    """

    def test_authorized_dry_run_never_executes_and_does_not_block_a_later_real_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                # Fully authorized (--allow-mapping, approved host, a real
                # reference and fake-but-real executables on PATH) AND
                # --dry-run: --dry-run must still win.
                main([*common, "--stage", "align", "--stage", "exact_match", "--dry-run"])

                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertFalse(align_record["executed"])
                self.assertIn("--dry-run", align_record["skip_reason"])
                exact_match_record = json.loads((output_dir / "hg38" / "exact_match.json").read_text())
                self.assertFalse(exact_match_record["executed"])
                self.assertIn("--dry-run", exact_match_record["skip_reason"])
                # No SAM/BED output was ever produced.
                self.assertFalse((output_dir / "hg38" / "align_bwa_mem.sam").exists())
                self.assertFalse((output_dir / "hg38" / "exact_match_hits.bed").exists())

                state = json.loads((output_dir / "state.json").read_text())
                self.assertNotIn("align:hg38", state["completed_stages"])
                self.assertNotIn("exact_match:hg38", state["completed_stages"])

                # A later real (non-dry-run) invocation for the same
                # output-dir/build must still execute, i.e. it was never
                # poisoned into "already completed" by the dry run above.
                main([*common, "--stage", "align", "--stage", "exact_match"])

            align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            self.assertTrue(align_record["executed"])
            exact_match_record = json.loads((output_dir / "hg38" / "exact_match.json").read_text())
            self.assertTrue(exact_match_record["executed"])
            state = json.loads((output_dir / "state.json").read_text())
            self.assertIn("align:hg38", state["completed_stages"])
            self.assertIn("exact_match:hg38", state["completed_stages"])


class RestartStateValidityTests(unittest.TestCase):
    """Regression coverage for review item 1 (round two): a planning-only
    run must never block a later, differently-authorized real run in the
    same output directory, and any change to the declared CSV/config/
    reference must invalidate (never silently skip) the stages that depend
    on it.
    """

    def test_ordinary_documented_dry_run_then_real_full_run_in_same_directory(self):
        # Exactly the documented COORDINATES.md workflow (no --allow-mapping
        # at all) followed by a separate, fully authorized real run in the
        # same --output-dir: this reproduced the reported failure where
        # every build-scoped stage was skipped and the combined report
        # stayed mapping_evaluated=false.
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            # Step 1: the plain documented dry run, no authorization flags.
            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(output_dir),
                    "--stage", "all",
                    "--dry-run",
                ]
            )
            combined_after_dry_run = json.loads((output_dir / "report.json").read_text())
            self.assertFalse(combined_after_dry_run["per_build"]["hg38"].get("mapping_evaluated", True))

            # Step 2: a separate, fully authorized real run in that same
            # directory, for a single build and without --dry-run.
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(output_dir),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--reference", f"hg38={reference}",
                        "--reference-manifest", f"hg38={manifest}",
                        "--build", "hg38",
                        "--stage", "align", "--stage", "exact_match", "--stage", "report", "--stage", "combined_report",
                    ]
                )

            align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            self.assertTrue(align_record["executed"])
            exact_match_record = json.loads((output_dir / "hg38" / "exact_match.json").read_text())
            self.assertTrue(exact_match_record["executed"])
            combined_after_real_run = json.loads((output_dir / "report.json").read_text())
            self.assertTrue(combined_after_real_run["per_build"]["hg38"].get("mapping_evaluated", True) is not False)
            self.assertIn("representative_stratum_gate", combined_after_real_run["per_build"]["hg38"])

    def test_changed_csv_invalidates_sample_decode_controls(self):
        # B1-R6: --execution-sources is now mandatory, so this test's own
        # spec must be regenerated to match csv_copy's *current* content
        # before each call — this test exercises restart-fingerprint
        # invalidation, not the execution-source hash gate itself (which is
        # exercised separately in ExecutionSourceVerificationWiringTests).
        def _spec_for(csv_path: Path) -> Path:
            return _write_matching_execution_sources(
                csv_path.with_name("execution_sources.toml"),
                dataset_csv=csv_path,
                dataset_audit=REPO_ROOT / "manifests" / "dataset_audit.json",
                proteins_config=REPO_ROOT / "configs" / "proteins.tsv",
                study_config=FIXTURE_CONFIG,
            )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            csv_copy = Path(tmp) / "dataset.csv"
            csv_copy.write_text(FIXTURE_CSV.read_text())
            common = ["--config", str(FIXTURE_CONFIG), "--csv", str(csv_copy), "--output-dir", str(output_dir)]

            main([*common, "--execution-sources", str(_spec_for(csv_copy)), "--stage", "sample", "--stage", "decode"])
            fasta_path = output_dir / "sample_sequences.fasta"
            first_mtime = fasta_path.stat().st_mtime_ns
            first_ids_hash = sha256_file(output_dir / "sample_ids.tsv")

            # Re-running unchanged is a no-op (skip).
            main([*common, "--execution-sources", str(_spec_for(csv_copy)), "--stage", "sample", "--stage", "decode"])
            self.assertEqual(fasta_path.stat().st_mtime_ns, first_mtime)

            # Change the CSV content at the same path: sample/decode must
            # re-run, not be silently skipped as "already completed".
            lines = FIXTURE_CSV.read_text().splitlines(keepends=True)
            # Flip one label field so the CSV's bytes (and hash) actually change.
            lines[1] = lines[1].replace(",1;2", ",2;1")
            csv_copy.write_text("".join(lines))

            main([*common, "--execution-sources", str(_spec_for(csv_copy)), "--stage", "sample", "--stage", "decode"])
            self.assertNotEqual(sha256_file(output_dir / "sample_ids.tsv"), first_ids_hash)

    def test_changed_reference_invalidates_align_even_with_identical_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                first_reference_hash = align_record["provenance"]["input_hashes"]["reference"]

                # Same path, different content, same manifest (now stale —
                # stage_align validates the manifest against the *new*
                # content and must reject it). B1-R3: a rejected attempt must
                # never overwrite the prior executed:true record — it raises
                # rather than silently downgrading align.json to executed:false.
                reference.write_text(">chr1\n" + "C" * 20 + "\n")
                with self.assertRaises(SystemExit) as ctx:
                    main([*common, "--stage", "align"])
                self.assertIn("refusing to overwrite", str(ctx.exception))
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertTrue(align_record["executed"])
                self.assertEqual(align_record["provenance"]["input_hashes"]["reference"], first_reference_hash)

                # With a manifest that matches the new content, align must
                # actually re-run rather than being skipped as already
                # complete (the reference-hash component of its fingerprint
                # changed).
                fresh_manifest = _write_reference_manifest(
                    Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference
                )
                main([*common, "--reference-manifest", f"hg38={fresh_manifest}", "--stage", "align"])
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertTrue(align_record["executed"])
                self.assertNotEqual(align_record["provenance"]["input_hashes"]["reference"], first_reference_hash)
                self.assertEqual(align_record["provenance"]["input_hashes"]["reference"], sha256_file(reference))


class ReferenceManifestFingerprintTests(unittest.TestCase):
    """Regression coverage for the follow-on correction: each required
    reference manifest's own content hash must be part of restart
    fingerprints, so a manifest-only change (the FASTA itself untouched)
    invalidates/revalidates align as appropriate, reruns the combined report
    when contig-category metadata changes, and provenance never attaches a
    newer manifest to reports actually produced under an older one.
    """

    def _authorized_common(self, tmp: Path, reference: Path, manifest: Path) -> list:
        return [
            "--config", str(FIXTURE_CONFIG),
            "--csv", str(FIXTURE_CSV),
            "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
            "--output-dir", str(tmp),
            "--allow-mapping",
            "--host-role", "approved_mac",
            "--reference", f"hg38={reference}",
            "--reference-manifest", f"hg38={manifest}",
            "--build", "hg38",
        ]

    def test_manifest_becoming_invalid_while_fasta_unchanged_blocks_align(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest_path = tmp_path / "hg38_manifest.json"
            _write_reference_manifest(manifest_path, build="hg38", reference=reference)

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                common = self._authorized_common(output_dir, reference, manifest_path)
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertTrue(align_record["executed"])

                # The FASTA is byte-for-byte unchanged; only the manifest is
                # edited to declare a wrong SHA-256 (as if it now describes
                # a different reference than the one on disk).
                manifest_payload = json.loads(manifest_path.read_text())
                manifest_payload["sha256"] = "0" * 64
                manifest_path.write_text(json.dumps(manifest_payload))

                # B1-R3: a manifest-invalid attempt must never overwrite the
                # prior executed:true record — it raises rather than
                # silently downgrading align.json to executed:false. The
                # rejected attempt is instead durably recorded separately
                # (see the .rejected_attempts.jsonl sidecar).
                with self.assertRaises(SystemExit) as ctx:
                    main([*common, "--stage", "align"])
                self.assertIn("refusing to overwrite", str(ctx.exception))

            align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            self.assertTrue(align_record["executed"])
            rejected_path = output_dir / "hg38" / "align.json.rejected_attempts.jsonl"
            self.assertTrue(rejected_path.is_file())
            rejected_entries = [json.loads(line) for line in rejected_path.read_text().splitlines()]
            self.assertIn("manifest", rejected_entries[-1]["skip_reason"])
            self.assertIn("sha256", " ".join(rejected_entries[-1]["reference_manifest_validation"]["violations"]))
            # The rejected attempt's own manifest is what's recorded in the
            # sidecar, not silently discarded.
            self.assertEqual(rejected_entries[-1]["reference_manifest"]["sha256"], "0" * 64)

    def test_contig_category_metadata_change_with_unchanged_fasta_reruns_combined_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest_path = tmp_path / "hg38_manifest.json"
            _write_reference_manifest(manifest_path, build="hg38", reference=reference)

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                common = self._authorized_common(output_dir, reference, manifest_path)
                for stage in ("sample", "decode", "controls", "align", "exact_match", "report"):
                    main([*common, "--stage", stage])
                main([*common, "--stage", "combined_report"])

                combined_before = json.loads((output_dir / "report.json").read_text())
                self.assertIsNone(combined_before["per_build"]["hg38"]["retention"]["combined"]["by_contig_category"])
                # Compare decompressed content, not the raw .gz bytes: gzip
                # embeds a write-time mtime in its header, so byte-identical
                # TSV content re-written a second later still hashes
                # differently at the file level.
                with gzip.open(output_dir / "hg38" / "mappings.tsv.gz", "rt") as handle:
                    first_mapping_rows = handle.read()

                # FASTA is untouched; only contig_categories metadata is
                # added to the manifest (still describing the same,
                # unchanged reference correctly).
                manifest_payload = json.loads(manifest_path.read_text())
                manifest_payload["contig_categories"] = {"chr1": "chromosome"}
                manifest_path.write_text(json.dumps(manifest_payload))

                for stage in ("align", "exact_match", "report"):
                    main([*common, "--stage", stage])
                main([*common, "--stage", "combined_report"])

            align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            self.assertTrue(align_record["executed"])
            self.assertEqual(align_record["reference_manifest"]["contig_categories"], {"chr1": "chromosome"})
            # Mapping content is unaffected (same reference/reads); the
            # manifest-only change still legitimately re-ran align per the
            # fingerprint design, but the actual mapping result is identical.
            with gzip.open(output_dir / "hg38" / "mappings.tsv.gz", "rt") as handle:
                second_mapping_rows = handle.read()
            self.assertEqual(second_mapping_rows, first_mapping_rows)

            combined_after = json.loads((output_dir / "report.json").read_text())
            by_contig = combined_after["per_build"]["hg38"]["retention"]["combined"]["by_contig_category"]
            self.assertIsNotNone(by_contig)
            self.assertIn("chromosome", by_contig)

            provenance = json.loads((output_dir / "provenance.json").read_text())
            self.assertEqual(
                provenance["builds"]["hg38"]["reference_manifest"]["contig_categories"], {"chr1": "chromosome"}
            )

    def test_provenance_never_attaches_a_newer_manifest_to_an_unrerun_report(self):
        # A --reference-manifest passed on an invocation that does not
        # actually re-run align/exact_match for that build must not make
        # provenance (or the combined report's contig-category retention)
        # look as though the existing report was produced under it.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest_path = tmp_path / "hg38_manifest.json"
            _write_reference_manifest(manifest_path, build="hg38", reference=reference)

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                common = self._authorized_common(output_dir, reference, manifest_path)
                for stage in ("sample", "decode", "controls", "align", "exact_match", "report"):
                    main([*common, "--stage", stage])

                original_manifest = json.loads(manifest_path.read_text())

                # A *different* manifest file (new contig_categories) is
                # passed, but only "combined_report" is requested this
                # invocation — align/exact_match/report for hg38 are not
                # re-attempted.
                other_manifest_path = tmp_path / "hg38_manifest_new.json"
                other_payload = dict(original_manifest)
                other_payload["contig_categories"] = {"chr1": "unlocalized_scaffold"}
                other_manifest_path.write_text(json.dumps(other_payload))
                argv = [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(output_dir),
                    "--allow-mapping",
                    "--host-role", "approved_mac",
                    "--reference", f"hg38={reference}",
                    "--reference-manifest", f"hg38={other_manifest_path}",
                    "--build", "hg38",
                    "--stage", "combined_report",
                ]
                main(argv)

            # provenance.json must still attribute hg38's report to the
            # manifest align actually ran under (no contig_categories),
            # never the newer one passed on this later, non-reruning call.
            provenance = json.loads((output_dir / "provenance.json").read_text())
            self.assertNotIn("contig_categories", provenance["builds"]["hg38"]["reference_manifest"] or {})
            combined = json.loads((output_dir / "report.json").read_text())
            self.assertIsNone(combined["per_build"]["hg38"]["retention"]["combined"]["by_contig_category"])


class PreflightHardPrerequisiteTests(unittest.TestCase):
    """Regression coverage for review item 1: successful preflight must be a
    hard prerequisite for real alignment/exact-match, bound to detected
    OS/architecture, resource limits, pinned tool versions, and hashes of the
    current inputs — never merely a declared --host-role=approved_mac.
    """

    def test_direct_align_execution_without_valid_preflight_is_refused(self):
        # Every basic capability flag is satisfied (--allow-mapping,
        # --host-role=approved_mac, a real reference, fake executables on
        # PATH) and the host facts are mocked to "pass" the OS/arch/RAM/disk
        # checks, but the resolved 'bwa' binary reports an unpinned version.
        # Real execution must still be refused: preflight, not the declared
        # role, is the gate.
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA_WRONG_VERSION)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                # No explicit "preflight" stage was ever run; align is
                # invoked directly. It must still refuse to execute, because
                # it runs its own fresh, binding preflight check internally.
                main([*common, "--stage", "align"])

            align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            self.assertFalse(align_record["executed"])
            self.assertIn("preflight failed closed", align_record["skip_reason"])
            self.assertIn("0.7.19", align_record["skip_reason"])
            self.assertFalse((output_dir / "hg38" / "align_bwa_mem.sam").exists())

            # A stage that was authorized but never actually executed must
            # not be recorded as completed (review item 2's bookkeeping
            # rule applies here too): a later, correctly-versioned run must
            # still be able to retry it.
            state = json.loads((output_dir / "state.json").read_text())
            self.assertNotIn("align:hg38", state["completed_stages"])

    def test_exact_match_also_requires_its_own_passing_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = Path(tmp) / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                # Thread count above the fixture config's max_threads=4:
                # exact_match's own fresh preflight must reject it even
                # though align already succeeded.
                main([*common, "--stage", "exact_match", "--threads", "8"])

            exact_match_record = json.loads((output_dir / "hg38" / "exact_match.json").read_text())
            self.assertFalse(exact_match_record["executed"])
            self.assertIn("preflight failed closed", exact_match_record["skip_reason"])


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
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
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
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(Path(tmp) / "hg38_manifest.json", build="hg38", reference=reference)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample"])
                main([*common, "--stage", "decode"])
                main([*common, "--stage", "controls"])
                main([*common, "--stage", "align"])
                main([*common, "--stage", "exact_match"])
                # A brand-new "process" for report: align/exact_match results
                # must be reloaded from align.json/exact_match.json, not lost.
                main([*common, "--stage", "report"])

            report = json.loads((output_dir / "hg38" / "report.json").read_text())
            self.assertEqual(report["reconciliation"]["status"], "passed")
            mappings_path = output_dir / "hg38" / "mappings.tsv.gz"
            self.assertTrue(mappings_path.exists())
            with gzip.open(mappings_path, "rt") as handle:
                lines = handle.read().splitlines()
            self.assertGreater(len(lines), 1)


class RunnerRealMappingCapabilityTests(unittest.TestCase):
    """Review R3: the runner must be genuinely capable of executing real
    mapping/exact-match when explicitly authorized, guarded by subprocess.run
    with shell=False, using tiny fake executables rather than any human data.
    Every real-mapping attempt now also passes through its own fresh,
    binding preflight check (review item 1), so these tests mock the host
    facts to a passing approved-mac state rather than omitting preflight.
    """

    def _run_full_authorized_pipeline(self, output_dir: Path, bin_dir: Path, *, build: str = "hg38") -> None:
        _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
        _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
        _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
        reference = output_dir / f"reference_{build}.fasta"
        reference.write_text(">chr1\n" + "A" * 20 + "\n")
        manifest = _write_reference_manifest(output_dir / f"{build}_manifest.json", build=build, reference=reference)

        argv = [
            "--config", str(FIXTURE_CONFIG),
            "--csv", str(FIXTURE_CSV),
            "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
            "--output-dir", str(output_dir),
            "--allow-mapping",
            "--host-role", "approved_mac",
            "--reference", f"{build}={reference}",
            "--reference-manifest", f"{build}={manifest}",
            "--build", build,
        ]
        for stage in ("sample", "decode", "controls", "align", "exact_match", "report"):
            argv.extend(["--stage", stage])
        main(argv)

    def test_real_mapping_executes_and_produces_classified_mappings(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                self._run_full_authorized_pipeline(output_dir, bin_dir)

            align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
            self.assertTrue(align_record["executed"])
            exact_match_record = json.loads((output_dir / "hg38" / "exact_match.json").read_text())
            self.assertTrue(exact_match_record["executed"])

            state = json.loads((output_dir / "state.json").read_text())
            self.assertTrue(state["mapping_executed"]["hg38"]["align"])
            self.assertTrue(state["mapping_executed"]["hg38"]["exact_match"])

            mappings_path = output_dir / "hg38" / "mappings.tsv.gz"
            with gzip.open(mappings_path, "rt") as handle:
                rows = handle.read().splitlines()
            header = rows[0].split("\t")
            body = [dict(zip(header, line.split("\t"))) for line in rows[1:]]
            # Every fake read is a perfect full-length match: primary mode
            # must classify it exact_unique (BWA perfect + SeqKit single hit).
            primary_categories = {r["category"] for r in body if r["mode"] == "primary" and r["is_control"] == "False"}
            self.assertEqual(primary_categories, {"exact_unique"})

    def test_provenance_is_connected_to_the_runner(self):
        # Review item 7: input hashes, resolved binary hashes/versions,
        # commands, output hashes, elapsed time, and peak memory must all be
        # recorded for a real mapping/exact-match run.
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                self._run_full_authorized_pipeline(output_dir, bin_dir)

            provenance = json.loads((output_dir / "provenance.json").read_text())
            self.assertIsNotNone(provenance["declared_inputs"]["dataset_csv"]["sha256"])
            self.assertIsNotNone(provenance["declared_inputs"]["config"]["sha256"])

            align_provenance = provenance["builds"]["hg38"]["align"]["provenance"]
            self.assertIn("reference", align_provenance["input_hashes"])
            self.assertEqual(len(align_provenance["input_hashes"]["reference"]), 64)
            for tool_key in ("bwa_mem", "minimap2_splice"):
                tool_prov = align_provenance[tool_key]
                self.assertTrue(tool_prov["command"])
                self.assertGreaterEqual(tool_prov["elapsed_seconds"], 0)
                self.assertIsInstance(tool_prov["peak_rss_kib_of_children"], int)
                self.assertEqual(len(tool_prov["output_sha256"]), 64)
                self.assertIsNotNone(tool_prov["binary"]["resolved_path"])
                self.assertEqual(len(tool_prov["binary"]["sha256"]), 64)
                self.assertIsNotNone(tool_prov["binary"]["version"])

            exact_match_provenance = provenance["builds"]["hg38"]["exact_match"]["provenance"]
            seqkit_prov = exact_match_provenance["seqkit_locate"]
            self.assertTrue(seqkit_prov["command"])
            self.assertEqual(len(seqkit_prov["output_sha256"]), 64)

    def test_reference_manifest_metadata_is_connected_to_provenance(self):
        # Review item 7: "index/reference metadata required by the parent
        # task" must reach provenance.json when supplied.
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            manifest_path = output_dir / "hg38_manifest.json"
            manifest_payload = {
                "build_id": "hg38",
                "assembly_accession": "GCF_000001405.40",
                "source_url": "https://example.invalid/hg38.fa.gz",
                "contig_categories_included": ["chromosome", "mitochondrion"],
                "byte_size": 123,
                "sha256": "0" * 64,
            }
            manifest_path.write_text(json.dumps(manifest_payload))

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
                _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
                _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
                reference = output_dir / "reference_hg38.fasta"
                reference.write_text(">chr1\n" + "A" * 20 + "\n")
                argv = [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(output_dir),
                    "--allow-mapping",
                    "--host-role", "approved_mac",
                    "--reference", f"hg38={reference}",
                    "--reference-manifest", f"hg38={manifest_path}",
                    "--build", "hg38",
                ]
                for stage in ("sample", "decode", "controls", "align", "exact_match", "report"):
                    argv.extend(["--stage", stage])
                main(argv)

            provenance = json.loads((output_dir / "provenance.json").read_text())
            self.assertEqual(provenance["builds"]["hg38"]["reference_manifest"], manifest_payload)

    def test_planned_but_skipped_mapping_is_not_recorded_as_executed(self):
        # Review R4 regression: a planning-only / dry-run stage must not be
        # confused with a completed real mapping run.
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(output_dir),
                    "--stage", "all",
                    "--dry-run",
                ]
            )
            state = json.loads((output_dir / "state.json").read_text())
            self.assertIn("align:hg38", state["completed_stages"])  # the stage ran (planned)
            self.assertFalse(state["mapping_executed"]["hg38"]["align"])  # but never executed real mapping
            self.assertFalse(state["mapping_executed"]["hg38"]["exact_match"])
            self.assertFalse(state["mapping_executed"]["hg19"]["align"])

            for build in ("hg38", "hg19"):
                report = json.loads((output_dir / build / "report.json").read_text())
                self.assertEqual(report["reconciliation"]["status"], "not_evaluated")
                self.assertFalse(report["reconciliation"]["passed"])


class SequentialTwoBuildProcessingTests(unittest.TestCase):
    """Regression coverage for review item 6: hg38 and hg19 must process
    sequentially into collision-safe per-build artifacts, with neither
    overwriting the other and neither's stages stale-skipped because a
    same-named stage already ran for the other build.
    """

    def test_sequential_hg38_and_hg19_do_not_overwrite_or_stale_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            ref_hg38 = output_dir / "hg38.fasta"
            ref_hg38.write_text(">chr1\n" + "A" * 20 + "\n")
            ref_hg19 = output_dir / "hg19.fasta"
            ref_hg19.write_text(">chr2\n" + "C" * 20 + "\n")
            manifest_hg38 = _write_reference_manifest(output_dir / "hg38_manifest.json", build="hg38", reference=ref_hg38)
            manifest_hg19 = _write_reference_manifest(output_dir / "hg19_manifest.json", build="hg19", reference=ref_hg19)

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--host-role", "approved_mac",
                "--reference", f"hg38={ref_hg38}",
                "--reference", f"hg19={ref_hg19}",
                "--reference-manifest", f"hg38={manifest_hg38}",
                "--reference-manifest", f"hg19={manifest_hg19}",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                # Single-build enforcement (B1 required item 7): each
                # authorized real-mapping invocation names exactly one build,
                # processed sequentially into its own subdirectory. `sample`/
                # `decode`/`controls` are build-independent and restart-skip
                # (matching fingerprint) on the second invocation.
                for build in ("hg38", "hg19"):
                    main(
                        [
                            *common,
                            "--allow-mapping",
                            "--build", build,
                            "--stage", "sample", "--stage", "decode", "--stage", "controls",
                            "--stage", "align", "--stage", "exact_match", "--stage", "report",
                        ]
                    )
                # combined_report reads both already-produced per-build
                # reports back from disk; it does not itself map anything, so
                # it is exempt from the single-build rule.
                main([*common, "--build", "hg38", "--build", "hg19", "--stage", "combined_report"])

            # Collision-safe: each build kept its own SAM/BED/mappings/report.
            hg38_sam = (output_dir / "hg38" / "align_bwa_mem.sam").read_text()
            hg19_sam = (output_dir / "hg19" / "align_bwa_mem.sam").read_text()
            self.assertIn("chr1", hg38_sam)
            self.assertIn("chr1", hg19_sam)  # both fake mappers always emit chr1
            self.assertTrue((output_dir / "hg38" / "mappings.tsv.gz").exists())
            self.assertTrue((output_dir / "hg19" / "mappings.tsv.gz").exists())

            state = json.loads((output_dir / "state.json").read_text())
            # Neither build's align/exact_match/report was stale-skipped
            # because the other build's same-named stage already ran.
            for build in ("hg38", "hg19"):
                for stage in ("align", "exact_match", "report"):
                    self.assertIn(f"{stage}:{build}", state["completed_stages"])
                self.assertTrue(state["mapping_executed"][build]["align"])
                self.assertTrue(state["mapping_executed"][build]["exact_match"])

            combined = json.loads((output_dir / "report.json").read_text())
            self.assertEqual(sorted(combined["builds"]), ["hg19", "hg38"])
            self.assertIn("hg38", combined["per_build"])
            self.assertIn("hg19", combined["per_build"])
            self.assertIn("usable_unique_rate_by_build", combined["build_comparison"])


def _sam(qname, flag, rname, pos1, mapq, cigar, nm=None):
    tags = [] if nm is None else [f"NM:i:{nm}"]
    return "\t".join([qname, str(flag), rname, str(pos1), str(mapq), cigar, "*", "0", "0", "*", "*", *tags])


class ReverseStrandLocusSerializationTests(unittest.TestCase):
    """Regression coverage for review item 5: _locus_detail must serialize a
    reverse-strand split mapping with start < end and BED-style blocks in
    ascending genomic order, even though CandidateLocus.blocks itself is
    template(query)-ordered (genomically descending for '-' strand).
    """

    def test_reverse_strand_spliced_locus_has_start_less_than_end(self):
        record = parse_sam_line(_sam("read1", 16, "chr5", 1001, 60, "50=300N50="))
        loci = build_candidate_loci([record], total_query_bases=100)
        detail = _locus_detail(loci[0])
        self.assertLess(detail["start"], detail["end"])
        starts = [int(v) for v in detail["block_starts"].split(";")]
        self.assertEqual(starts, sorted(starts))

    def test_reverse_strand_two_record_split_locus_has_start_less_than_end(self):
        five_prime = parse_sam_line(_sam("read2", 16, "chr5", 201, 60, "50H50=", nm=0))
        three_prime = parse_sam_line(_sam("read2", 2064, "chr5", 1, 60, "50=50S", nm=0))
        loci = build_candidate_loci([five_prime, three_prime], total_query_bases=100)
        detail = _locus_detail(loci[0])
        self.assertLess(detail["start"], detail["end"])
        starts = [int(v) for v in detail["block_starts"].split(";")]
        self.assertEqual(starts, sorted(starts))
        # Genomic order, not the template order that produced locus.blocks:
        # the smallest ref_start (three_prime's block, ref_start=0) must be
        # first.
        self.assertEqual(starts[0], 0)


class CombinedReportBlocksOnFailedReconciliationTests(unittest.TestCase):
    """Regression coverage for review item 4: combined_report must stop
    (never silently finalize) when any evaluated per-build reconciliation
    failed, rather than laundering an internally-inconsistent per-build
    report into a combined report that looks trustworthy.
    """

    def _empty_sample(self) -> SamplingResult:
        return SamplingResult(
            assignments=(),
            representative_ids=frozenset(),
            quota_ids=frozenset(),
            filler_ids=frozenset(),
            unsatisfied_quotas=(),
        )

    def test_failed_build_reconciliation_stops_combined_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "hg38").mkdir()
            (output_dir / "hg38" / "report.json").write_text(
                json.dumps(
                    {
                        "reconciliation": {
                            "status": "failed",
                            "passed": False,
                            "issues": [{"check": "sample_total", "detail": "mismatch"}],
                        }
                    }
                )
            )

            cfg = load_config(FIXTURE_CONFIG)
            with self.assertRaises(SystemExit) as ctx:
                stage_combined_report(self._empty_sample(), cfg=cfg, output_dir=output_dir, builds=("hg38",))
            self.assertIn("reconciliation failed", str(ctx.exception))
            # No top-level combined report was written as a side effect of
            # the failed attempt (only the per-build report.json exists).
            self.assertFalse((output_dir / "report.json").exists())

    def test_not_evaluated_build_does_not_block_combined_report(self):
        # A dry-run/unauthorized build (honestly "not_evaluated") is not the
        # same as a "failed" one and must not block finalization.
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "hg38").mkdir()
            (output_dir / "hg38" / "report.json").write_text(
                json.dumps({"reconciliation": {"status": "not_evaluated", "passed": False, "issues": []}})
            )

            cfg = load_config(FIXTURE_CONFIG)
            combined = stage_combined_report(self._empty_sample(), cfg=cfg, output_dir=output_dir, builds=("hg38",))
            self.assertFalse(combined["per_build"]["hg38"]["mapping_evaluated"])


class BuildMappingRowsUniverseTests(unittest.TestCase):
    """Regression coverage for review item 3: mapping rows must be built
    from the complete expected biological-and-control ID universe, not from
    whichever IDs happen to appear in mapped SAM records. A query unmapped by
    both tools never appears in a SAM dict at all (parse_sam_line returns
    None for an unmapped record), so it must still receive an explicit
    'unmapped' row in both modes rather than being silently dropped.
    """

    def test_query_unmapped_by_both_tools_is_still_emitted_as_unmapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Neither SAM contains any record for "row_0": both tools failed
            # to map it (an unmapped SAM record parses to None and is simply
            # absent, per rbpbench.coordinates.alignment.parse_sam_line).
            bwa_sam = tmp_path / "bwa.sam"
            bwa_sam.write_text("@HD\tVN:1.6\n")
            mm2_sam = tmp_path / "mm2.sam"
            mm2_sam.write_text("@HD\tVN:1.6\n")

            cfg = load_config(FIXTURE_CONFIG)
            results, rows = build_mapping_rows(
                cfg,
                {"row_0": "representative"},
                build="hg38",
                bwa_sam=bwa_sam,
                minimap2_sam=mm2_sam,
                exact_hits_bed=None,
            )

            categories = {(r.sample_id, r.mode): r.category for r in results}
            self.assertEqual(categories[("row_0", "primary")], "unmapped")
            self.assertEqual(categories[("row_0", "splice")], "unmapped")
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row["sample_id"], "row_0")
                self.assertEqual(row["category"], "unmapped")
                self.assertEqual(row["chrom"], "")


class ExactMatchDiscordanceEvidenceTests(unittest.TestCase):
    """Regression coverage for review item 4 (auditability): exact-occurrence
    evidence must be persisted on the mapping row itself, not just implied
    by which terminal category a row landed in, so BWA-vs-SeqKit discordance
    can be audited downstream (rbpbench.coordinates.summaries.exact_match_discordance).
    """

    def test_discordant_row_persists_occurrence_count_and_perfect_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg = load_config(FIXTURE_CONFIG)
            length = cfg.sequence_length_nt
            bwa_sam = tmp_path / "bwa.sam"
            bwa_sam.write_text(
                "\t".join(["row_0", "0", "chr1", "1", "60", f"{length}M", "*", "0", "0", "*", "*", "NM:i:0"]) + "\n"
            )
            mm2_sam = tmp_path / "mm2.sam"
            mm2_sam.write_text("@HD\tVN:1.6\n")
            # SeqKit independently finds TWO occurrences: discordant with
            # BWA-MEM's perfect-unique call.
            bed = tmp_path / "hits.bed"
            bed.write_text("chr1\t0\t{0}\trow_0\t.\t+\nchr2\t0\t{0}\trow_0\t.\t+\n".format(length))

            _, rows = build_mapping_rows(
                cfg,
                {"row_0": "representative"},
                build="hg38",
                bwa_sam=bwa_sam,
                minimap2_sam=mm2_sam,
                exact_hits_bed=bed,
            )
            primary_row = next(r for r in rows if r["mode"] == "primary")
            self.assertEqual(str(primary_row["bwa_best_is_perfect"]), "True")
            self.assertEqual(str(primary_row["bwa_perfect_unique_candidate"]), "True")
            self.assertEqual(primary_row["exact_occurrence_count"], 2)
            # Discordant: BWA-perfect but not exactly one SeqKit occurrence,
            # so classification must not be exact_unique.
            self.assertNotEqual(primary_row["category"], "exact_unique")
            self.assertEqual(primary_row["category"], "high_conf_unique")

            splice_row = next(r for r in rows if r["mode"] == "splice")
            self.assertEqual(splice_row["bwa_best_is_perfect"], "")
            self.assertEqual(splice_row["exact_occurrence_count"], "")

    def test_two_perfect_bwa_loci_stays_ambiguous_and_is_not_a_discordance_candidate(self):
        # Regression: two equally perfect (100% coverage/identity) BWA loci
        # must classify ambiguous (a plausible distinct secondary exists)
        # and must NOT be reported as a BWA-vs-SeqKit uniqueness
        # discordance, even though SeqKit also finds two occurrences (i.e.
        # even where BWA and SeqKit occurrence counts happen to "agree").
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg = load_config(FIXTURE_CONFIG)
            length = cfg.sequence_length_nt
            bwa_sam = tmp_path / "bwa.sam"
            bwa_sam.write_text(
                "\n".join(
                    [
                        "\t".join(["row_0", "0", "chr1", "1", "60", f"{length}M", "*", "0", "0", "*", "*", "NM:i:0"]),
                        "\t".join(
                            ["row_0", "256", "chr2", "1", "0", f"{length}M", "*", "0", "0", "*", "*", "NM:i:0"]
                        ),
                    ]
                )
                + "\n"
            )
            mm2_sam = tmp_path / "mm2.sam"
            mm2_sam.write_text("@HD\tVN:1.6\n")
            bed = tmp_path / "hits.bed"
            bed.write_text("chr1\t0\t{0}\trow_0\t.\t+\nchr2\t0\t{0}\trow_0\t.\t+\n".format(length))

            _, rows = build_mapping_rows(
                cfg,
                {"row_0": "representative"},
                build="hg38",
                bwa_sam=bwa_sam,
                minimap2_sam=mm2_sam,
                exact_hits_bed=bed,
            )
            primary_row = next(r for r in rows if r["mode"] == "primary")
            self.assertEqual(primary_row["category"], "ambiguous")
            self.assertEqual(str(primary_row["bwa_best_is_perfect"]), "True")
            self.assertEqual(str(primary_row["bwa_perfect_unique_candidate"]), "False")

            from rbpbench.coordinates import summaries

            primary_by_id = summaries.exclude_controls(summaries.index_rows_by_sample(rows, mode="primary"))
            discordance = summaries.exact_match_discordance(primary_by_id)
            self.assertEqual(discordance["total_bwa_perfect_unique_candidates"], 0)
            self.assertNotIn("row_0", discordance["discordant_sample_ids"])


class ProvenanceCompletenessTests(unittest.TestCase):
    """Regression coverage for review item 4: provenance must hash declared
    inputs (dataset audit, protein config) and generated artifacts (sample
    IDs, mappings, reports), include index provenance, and bind everything
    to the current restart-state fingerprints.
    """

    def test_provenance_hashes_declared_inputs_and_generated_artifacts_and_binds_fingerprints(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = output_dir / "reference_hg38.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(output_dir / "hg38_manifest.json", build="hg38", reference=reference)

            dataset_audit = Path(tmp) / "dataset_audit.json"
            dataset_audit.write_text(json.dumps({"ok": True}))
            proteins_config = Path(tmp) / "proteins.tsv"
            proteins_config.write_text("protein_id\tname\n1\tTEST\n")
            # B1-R6: this test overrides --dataset-audit/--proteins-config
            # with its own tiny fixtures, so the mandatory --execution-sources
            # spec must match *those*, not the shared FIXTURE_EXECUTION_SOURCES
            # (which pins the real manifests/dataset_audit.json and
            # configs/proteins.tsv hashes).
            custom_sources = _write_matching_execution_sources(
                Path(tmp) / "execution_sources.toml",
                dataset_csv=FIXTURE_CSV,
                dataset_audit=dataset_audit,
                proteins_config=proteins_config,
                study_config=FIXTURE_CONFIG,
            )

            argv = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(custom_sources),
                "--output-dir", str(output_dir),
                "--dataset-audit", str(dataset_audit),
                "--proteins-config", str(proteins_config),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
                "--build", "hg38",
            ]
            for stage in ("sample", "decode", "controls", "align", "exact_match", "report", "combined_report"):
                argv.extend(["--stage", stage])
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main(argv)

            provenance = json.loads((output_dir / "provenance.json").read_text())
            self.assertEqual(provenance["declared_inputs"]["dataset_audit"]["sha256"], sha256_file(dataset_audit))
            self.assertEqual(provenance["declared_inputs"]["proteins_config"]["sha256"], sha256_file(proteins_config))

            generated = provenance["generated_artifacts"]
            self.assertEqual(generated["sample_ids_tsv"]["sha256"], sha256_file(output_dir / "sample_ids.tsv"))
            self.assertEqual(
                generated["sample_sequences_fasta"]["sha256"], sha256_file(output_dir / "sample_sequences.fasta")
            )
            self.assertIsNotNone(generated["combined_report_json"])

            build_artifacts = provenance["builds"]["hg38"]["generated_artifacts"]
            self.assertEqual(
                build_artifacts["mappings_tsv_gz"]["sha256"],
                sha256_file(output_dir / "hg38" / "mappings.tsv.gz"),
            )
            self.assertIsNotNone(build_artifacts["report_json"])

            self.assertIsNotNone(provenance["builds"]["hg38"]["reference_index"])
            self.assertIn("index_sha256", provenance["builds"]["hg38"]["reference_index"])

            # Bound to the state fingerprints that decided which stages ran.
            state = json.loads((output_dir / "state.json").read_text())
            self.assertEqual(provenance["state_fingerprints"], state["stage_fingerprints"])
            self.assertIn("align:hg38", provenance["state_fingerprints"])


if __name__ == "__main__":
    unittest.main()
