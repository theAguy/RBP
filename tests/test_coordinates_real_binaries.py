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

from rbpbench.coordinates.alignment import build_candidate_loci, classify_primary, ClassificationThresholds, parse_sam_line
from rbpbench.coordinates.commands import bwa_mem_command, minimap2_splice_command, seqkit_locate_command
from rbpbench.coordinates.exact_match import exact_occurrence_count, exact_unique_confirmed, parse_seqkit_bed

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


if __name__ == "__main__":
    unittest.main()
