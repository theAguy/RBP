"""Real-binary tiny smoke tests against the pinned BWA 0.7.19, minimap2
2.31, and SeqKit 2.13.0 (B1 required items 8 and 11).

Every test here is skipped cleanly when the relevant binary is not on PATH
(e.g. Claude's constrained Linux dev VM), so the ordinary test suite never
depends on the isolated project environment being active. All fixtures are
tiny and synthetic; nothing here touches the real dataset or a human
reference.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.alignment import build_candidate_loci, classify_primary, ClassificationThresholds, parse_sam_line
from rbpbench.coordinates.commands import (
    bwa_index_command,
    bwa_mem_command,
    minimap2_index_command,
    minimap2_splice_command,
    seqkit_locate_command,
)
from rbpbench.coordinates.exact_match import exact_occurrence_count, exact_unique_confirmed, parse_seqkit_bed
from rbpbench.coordinates.probe import build_pattern_fasta, extract_contig_streaming, select_probe_window, validate_probe_bed_rows
from rbpbench.coordinates.runner import stage_index, stage_probe
from rbpbench.data.audit import sha256_file

from test_coordinates_runner import _approved_host_context
from test_coordinates_runner_probe import _write_b2_checkpoint

_HAVE_BWA = shutil.which("bwa") is not None
_HAVE_MINIMAP2 = shutil.which("minimap2") is not None
_HAVE_SEQKIT = shutil.which("seqkit") is not None


def _run(argv, timeout=60):
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=True)


@unittest.skipUnless(_HAVE_SEQKIT, "requires the real seqkit 2.13.0 binary on PATH")
class SeqKitRealBinaryContractTests(unittest.TestCase):
    """Confirms the SeqKit 2.13.0 CLI contract assumed by
    ``rbpbench.coordinates.commands.seqkit_locate_command`` and
    ``rbpbench.coordinates.exact_match.parse_seqkit_bed`` — the "Known
    assumption to confirm in Task 001B" flagged in docs/COORDINATES.md.
    """

    def test_version_reports_2_13_0(self):
        result = _run(["seqkit", "version"])
        self.assertIn("2.13.0", result.stdout)

    def test_locate_help_still_exposes_the_assumed_flags(self):
        result = subprocess.run(["seqkit", "locate", "--help"], capture_output=True, text=True, timeout=30)
        help_text = result.stdout
        for flag in ("--bed", "--use-fmi", "--pattern-file", "--ignore-case"):
            self.assertIn(flag, help_text)

    def test_bed6_both_strands_once_and_case_insensitive_boundary_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fasta"
            # chrA: a non-palindromic 8-mer placed once on the forward
            # strand and once (as its reverse complement) on the reverse
            # strand, separated by unrelated filler so a single seqkit
            # invocation must report exactly two distinct occurrences with
            # correct, non-duplicated strand labels.
            # chrB: the same query pattern's uppercase form spans a
            # lowercase (soft-masked) run in the reference, matchable only
            # with --ignore-case.
            reference.write_text(
                ">chrA\n"
                "AAAACCCC" + "TCTCTCTCTCTCTCTC" + "GGGGTTTT" + "\n"
                ">chrB\n"
                "CCCC" + "aaaa" + "GGGG" + "\n"
            )
            queries = tmp_path / "queries.fasta"
            queries.write_text(">pat_strand\nAAAACCCC\n>pat_case_boundary\nCCCCAAAAGGGG\n")

            cmd = seqkit_locate_command(queries, reference)
            result = _run(cmd.argv)
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            hits = parse_seqkit_bed(lines)

            # Both-strands-once, no double counting: exactly 2 occurrences
            # for pat_strand (forward at chrA:0-8, reverse at chrA:24-32),
            # never 4 from an accidental double count.
            self.assertEqual(exact_occurrence_count(hits, "pat_strand"), 2)
            self.assertEqual(
                hits["pat_strand"],
                {("chrA", 0, 8, "+"), ("chrA", 24, 32, "-")},
            )

            # Case-insensitive match spanning a lowercase/uppercase boundary
            # in a soft-masked fixture: exactly one occurrence, full span.
            self.assertEqual(exact_occurrence_count(hits, "pat_case_boundary"), 1)
            self.assertEqual(hits["pat_case_boundary"], {("chrB", 0, 12, "+")})

            # BED6: six tab-separated columns per output line.
            for line in lines:
                self.assertEqual(len(line.split("\t")), 6)


@unittest.skipUnless(_HAVE_BWA and _HAVE_MINIMAP2 and _HAVE_SEQKIT, "requires real bwa/minimap2/seqkit on PATH")
class EndToEndRealBinarySmokeTests(unittest.TestCase):
    """A tiny end-to-end smoke test exercising the pipeline's own command
    builders and parsers against the genuinely installed, pinned binaries —
    not fake executables — confirming exact_unique classification works
    with real tool output.
    """

    def test_exact_unique_read_classified_consistently_by_bwa_and_seqkit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fasta"
            import random

            rng = random.Random(1)
            body = "".join(rng.choice("ACGT") for _ in range(300))
            reference.write_text(">chrTest\n" + body + "\n")

            read_seq = body[50:100]  # a unique 50-nt substring of the reference
            reads = tmp_path / "reads.fasta"
            reads.write_text(f">read_unique\n{read_seq}\n")

            _run(["bwa", "index", str(reference)])
            bwa_cmd = bwa_mem_command(reference, reads, threads=1)
            sam_text = _run(bwa_cmd.argv).stdout
            records = [parse_sam_line(line) for line in sam_text.splitlines()]
            records = [r for r in records if r is not None]
            self.assertTrue(records)

            loci = build_candidate_loci(records, total_query_bases=len(read_seq))
            thresholds = ClassificationThresholds(
                high_conf_min_coverage=0.98, high_conf_min_identity=0.99,
                secondary_min_coverage=0.90, secondary_min_identity=0.95,
            )
            best = loci[0]
            self.assertEqual(best.coverage, 1.0)
            self.assertEqual(best.identity, 1.0)

            seqkit_cmd = seqkit_locate_command(reads, reference)
            bed_lines = [line for line in _run(seqkit_cmd.argv).stdout.splitlines() if line.strip()]
            occurrences = parse_seqkit_bed(bed_lines)
            occurrence_count = exact_occurrence_count(occurrences, "read_unique")
            self.assertEqual(occurrence_count, 1)
            self.assertTrue(exact_unique_confirmed(primary_is_perfect_unique=True, occurrence_count=occurrence_count))

    def test_minimap2_splice_smoke_mapping_produces_parseable_sam(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "reference.fasta"
            import random

            rng = random.Random(2)
            body = "".join(rng.choice("ACGT") for _ in range(300))
            reference.write_text(">chrTest\n" + body + "\n")
            reads = tmp_path / "reads.fasta"
            reads.write_text(f">read_a\n{body[10:60]}\n")

            cmd = minimap2_splice_command(reference, reads, threads=1)
            sam_text = _run(cmd.argv).stdout
            records = [parse_sam_line(line) for line in sam_text.splitlines() if line and not line.startswith("@")]
            records = [r for r in records if r is not None]
            self.assertTrue(records)


@unittest.skipUnless(_HAVE_BWA and _HAVE_MINIMAP2 and _HAVE_SEQKIT, "requires real bwa/minimap2/seqkit on PATH")
class ProbeMechanicsRealBinarySmokeTests(unittest.TestCase):
    """Task 001B checkpoint B3A, "Minimum regression set" item 16: a guarded
    real-binary tiny probe integration test, against the genuinely installed,
    pinned bwa/minimap2/seqkit binaries -- never fake executables.

    Exercises the SAME building blocks ``rbpbench.coordinates.runner.stage_probe``
    orchestrates (streaming contig extraction, deterministic window
    selection, transactional pattern-FASTA construction, real one-thread
    BWA/minimap2 smoke mapping, real SeqKit locate, and BED6 validation)
    directly against real binaries, bypassing ``stage_probe``'s own
    preflight/authorization gating -- consistent with every other real-binary
    test in this file, which call the pinned tools directly rather than
    through the runner's CLI-level orchestration (whose RAM/disk thresholds
    are not something a real-binary unit test should depend on). Nothing
    here touches the real dataset, a real B2 FASTA, or a real human
    reference/index; the reference is a tiny synthetic fixture.
    """

    def test_probe_pipeline_end_to_end_against_real_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            import random

            rng = random.Random(3)
            # A largest ("chr1", 400 nt) and a smaller ("chr2", 100 nt)
            # contig, so largest-contig selection is exercised for real.
            chr1_body = "".join(rng.choice("ACGT") for _ in range(400))
            chr2_body = "".join(rng.choice("ACGT") for _ in range(100))
            reference = tmp_path / "reference.fasta"
            reference.write_text(f">chr1\n{chr1_body}\n>chr2\n{chr2_body}\n")

            # Real BWA/minimap2 indices, built once (not through stage_index,
            # to avoid its own RAM/disk preflight gate -- same rationale as
            # the module docstring above).
            bwa_prefix = tmp_path / "idx" / "hg38"
            bwa_prefix.parent.mkdir(parents=True, exist_ok=True)
            _run(bwa_index_command(reference, bwa_prefix).argv, timeout=120)
            mm2_index = tmp_path / "idx" / "hg38.mmi"
            _run(minimap2_index_command(reference, mm2_index).argv, timeout=120)

            # Accepted B2-shaped biological/control FASTAs (tiny fixture).
            bio_fasta = tmp_path / "sample_sequences.fasta"
            bio_fasta.write_text(f">bio1\n{chr1_body[0:20]}\n>bio2\n{chr2_body[0:20]}\n")
            ctrl_fasta = tmp_path / "control_sequences.fasta"
            ctrl_fasta.write_text(f">control_bio1\n{chr1_body[20:40]}\n")

            pattern_result = build_pattern_fasta(bio_fasta, ctrl_fasta, tmp_path / "patterns.fasta")
            self.assertEqual(pattern_result.count, 3)

            contig_extraction = extract_contig_streaming(reference, accession="chr1", output_path=tmp_path / "contig.fna")
            self.assertEqual(contig_extraction.length, 400)

            window = select_probe_window(
                contig_extraction.output_path, accession="chr1", contig_length=400, window_length=60
            )
            smoke_seq = chr1_body[window.start:window.end]
            self.assertEqual(len(smoke_seq), 60)
            smoke_query_id = f"probe_smoke_chr1_{window.start}_{window.end}"
            smoke_query = tmp_path / "smoke_query.fasta"
            smoke_query.write_text(f">{smoke_query_id}\n{smoke_seq}\n")

            bwa_sam_text = _run(bwa_mem_command(bwa_prefix, smoke_query, threads=1).argv, timeout=60).stdout
            bwa_records = [r for r in (parse_sam_line(line) for line in bwa_sam_text.splitlines()) if r is not None]
            primary_bwa = [r for r in bwa_records if r.is_primary and r.query_name == smoke_query_id]
            self.assertEqual(len(primary_bwa), 1)
            self.assertEqual(primary_bwa[0].chrom, "chr1")

            mm2_sam_text = _run(minimap2_splice_command(mm2_index, smoke_query, threads=1).argv, timeout=60).stdout
            mm2_records = [
                r for r in (parse_sam_line(line) for line in mm2_sam_text.splitlines() if not line.startswith("@")) if r is not None
            ]
            primary_mm2 = [r for r in mm2_records if r.is_primary and r.query_name == smoke_query_id]
            self.assertEqual(len(primary_mm2), 1)
            self.assertEqual(primary_mm2[0].chrom, "chr1")

            seqkit_cmd = seqkit_locate_command(pattern_result.output_path, contig_extraction.output_path)
            bed_lines = _run(seqkit_cmd.argv, timeout=60).stdout.splitlines()
            validation = validate_probe_bed_rows(
                bed_lines, known_pattern_ids=pattern_result.id_set, contig_accession="chr1", contig_length=400
            )
            self.assertTrue(validation.ok, validation.violations)
            # bio1's own 20-nt substring must be found exactly on chr1.
            self.assertGreaterEqual(validation.hit_count, 1)


@unittest.skipUnless(_HAVE_BWA and _HAVE_MINIMAP2 and _HAVE_SEQKIT, "requires real bwa/minimap2/seqkit on PATH")
class GuardedProbeStageRealBinarySmokeTests(unittest.TestCase):
    """B3A-R7: a guarded real-binary tiny probe integration test through the
    ACTUAL ``stage_probe`` orchestration -- authorization, fresh preflight,
    B2-checkpoint/reference/index binding, disk budgets, transactional
    generation selection, and ``probe.json`` writing -- against genuinely
    installed, pinned bwa/minimap2/seqkit binaries. Unlike
    ``ProbeMechanicsRealBinarySmokeTests`` above (which deliberately bypasses
    the guarded path to stay host-independent), this test mocks only the
    HOST-detection facts ``run_preflight`` reads (OS/arch/RAM/free-disk, via
    the same ``_approved_host_context`` helper every other guarded-stage
    integration test in this suite uses) so it stays portable, while every
    subprocess actually invoked is the real pinned binary. Nothing here
    touches the real dataset, a real B2 FASTA, or a real human
    reference/index; the reference and B2 checkpoint are tiny synthetic
    fixtures.
    """

    def test_stage_probe_end_to_end_through_the_guarded_path_with_real_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # A largest ("chr1", 400 nt) and a smaller ("chr2", 100 nt)
            # RANDOM (non-repetitive) contig -- real aligners cannot map a
            # short read reliably against a highly-repetitive tiny fixture,
            # unlike the fake-tool fixtures elsewhere in this suite.
            import random

            rng = random.Random(42)
            chr1_body = "".join(rng.choice("ACGT") for _ in range(400))
            chr2_body = "".join(rng.choice("ACGT") for _ in range(100))
            reference = tmp_path / "reference.fasta"
            reference.write_text(f">chr1\n{chr1_body}\n>chr2\n{chr2_body}\n")
            manifest = {
                "build_id": "hg38",
                "assembly_accession": "TEST-hg38",
                "source_url": "https://example.invalid/reference.fa.gz",
                "contig_categories_included": ["chromosome"],
                "byte_size": reference.stat().st_size,
                "sha256": sha256_file(reference),
                "contigs": ["chr1", "chr2"],
                "contig_lengths": {"chr1": 400, "chr2": 100},
            }
            b2 = _write_b2_checkpoint(tmp_path)

            from rbpbench.coordinates.config import load_config

            fixture_config = Path(__file__).resolve().parent / "fixtures" / "coordinates" / "tiny_coordinate_feasibility.toml"
            cfg = load_config(fixture_config)

            index_dir = tmp_path / "indices" / "hg38"
            with _approved_host_context():
                index_record = stage_index(
                    cfg, build="hg38", index_dir=index_dir, allow_mapping=True, host_role="approved_mac",
                    threads=1, reference=reference, reference_manifest=manifest, dry_run=False,
                )
            self.assertTrue(index_record["executed"], index_record.get("skip_reason"))

            out_dir = tmp_path / "out"
            with _approved_host_context(), mock.patch(
                "rbpbench.coordinates.runner.git_is_clean", return_value=True
            ), mock.patch("rbpbench.coordinates.runner.current_git_commit", return_value="0" * 40):
                probe_record = stage_probe(
                    cfg,
                    build="hg38",
                    build_output_dir=out_dir,
                    allow_mapping=True,
                    host_role="approved_mac",
                    reference=reference,
                    reference_manifest=manifest,
                    reference_manifest_raw_sha256=None,
                    index_record=index_record,
                    b2_manifest_path=b2["manifest_path"],
                    repo_root=tmp_path,
                    b2_manifest_expected_sha256=b2["manifest_sha256"],
                    b2_manifest_expected_checkpoint="001B-B2",
                    b2_manifest_expected_status="passed",
                    b2_expected_biological_count=None,
                    b2_expected_control_count=None,
                    dry_run=False,
                    window_length=60,  # tiny fixture window, never the real 500 nt
                )
            self.assertTrue(probe_record["executed"], probe_record.get("skip_reason"))
            self.assertEqual(probe_record["selected_contig"]["accession"], "chr1")
            self.assertTrue(Path(probe_record["sam_paths"]["bwa_mem"]).is_file())
            self.assertTrue(Path(probe_record["sam_paths"]["minimap2_splice"]).is_file())
            self.assertTrue(Path(probe_record["bed_path"]).is_file())
            self.assertTrue(probe_record["projection"]["wall_time_gate_ok"])
            self.assertTrue(probe_record["projection"]["output_gate_ok"])
            self.assertTrue((out_dir / "probe.json").is_file())
            self.assertFalse((out_dir / "align.json").exists())
            self.assertFalse((out_dir / "exact_match.json").exists())


if __name__ == "__main__":
    unittest.main()
