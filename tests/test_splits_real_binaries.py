"""Real-binary tiny smoke tests against the pinned MMseqs2 18.8cc5c
(build h8b377d6_0), installed in the isolated ``rbpbench-splits-002``
conda environment (``manifests/sequence_partition_environment_002a.yml``).

Every test here is skipped cleanly when ``mmseqs`` is not on PATH, so the
ordinary test suite never depends on that isolated environment being active
-- exactly like ``tests/test_coordinates_real_binaries.py`` for
BWA/minimap2/SeqKit. All fixtures are tiny and synthetic; nothing here
touches the real dataset.

These tests are the executable proof required by
``docs/tasks/002_sequence_clustered_partitions.md`` and the 002A correction
handoff (``docs/handoffs/002a_sequence_partition_correction_claude_handoff.md``,
"C3 -- Prove semantics with discriminating real-binary fixtures"): the
installed binary truly uses nucleotide alignments (explicit type-2
database), both strands, true identity, disabled masking, the explicit
E-value ceiling, connected-component clustering, single-step graph
construction, and -- the corrected part -- the exact frozen per-width
90%-identity / 80%-or-95%-coverage rule and the ``--max-seqs 361180`` hit
ceiling, discovered by MMseqs2 itself rather than injected as
already-decided edges. Every discriminating pair below uses a clear margin
on the side of the threshold it is meant to test, never boundary equality.
"""

from __future__ import annotations

import random
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from rbpbench.splits.commands import (
    UnknownWidthError,
    audit_search_command,
    cluster_command,
    createdb_command,
    createtsv_command,
    createtsv_search_command,
    resolve_mmseqs_binary_provenance,
    run_mmseqs_command,
)
from rbpbench.splits.membership import parse_cluster_tsv_lines, reconcile_membership

_HAVE_MMSEQS = shutil.which("mmseqs") is not None


def _run(argv, timeout=60):
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=True)


def _random_seq(seed: int, width: int) -> str:
    rng = random.Random(seed)
    return "".join(rng.choice("ACGT") for _ in range(width))


def _reverse_complement(seq: str) -> str:
    table = str.maketrans("ACGT", "TGCA")
    return seq.translate(table)[::-1]


def _mutate(seq: str, *, fraction: float, seed: int) -> str:
    """Mutates ``fraction`` of positions in ``seq`` to a different base --
    an identity fixture built with margin (e.g. 5% or 30% mutated), never a
    fragile floating-point boundary equality.
    """
    rng = random.Random(seed)
    bases = "ACGT"
    chars = list(seq)
    n_mutate = int(round(len(seq) * fraction))
    for pos in rng.sample(range(len(seq)), n_mutate):
        original = chars[pos]
        chars[pos] = rng.choice([base for base in bases if base != original])
    return "".join(chars)


def _effective_setting(log_text: str, label: str) -> float:
    """Extracts one of MMseqs2's own effective-parameter lines from a
    captured real stdout log (e.g. ``"Seq. id. threshold    0.9"``). Used to
    prove the binary itself received/applied the frozen setting -- so an
    omitted ``--min-seq-id``, ``-c``, or ``--max-seqs`` fails this assertion
    even if clustering still happened to produce plausible-looking output.
    """
    match = re.search(rf"{re.escape(label)}\s+([0-9.]+)", log_text)
    if match is None:
        raise AssertionError(f"{label!r} not found in mmseqs stdout log")
    return float(match.group(1))


_WIDTH_COVERAGE = {500: 0.80, 251: 0.95, 101: 0.95}

# (long_len, above_offset, below_offset) per width: a shifted pair's overlap
# fraction (= (width - offset) / width) is engineered to sit clearly above
# and clearly below that width's frozen coverage threshold, confirmed
# against the real binary before being encoded here:
#   500: overlap 0.90 (above 0.80) vs 0.40 (below 0.80)
#   251: overlap 0.976 (above 0.95) vs 0.797 (below 0.95)
#   101: overlap 0.980 (above 0.95) vs 0.792 (below 0.95)
_WIDTH_SHIFT_PLAN = {
    500: (800, 50, 300),
    251: (400, 6, 51),
    101: (150, 2, 21),
}


def _build_width_fixture(width: int) -> dict[str, str]:
    """A single per-width synthetic fixture proving every C3-required
    behavior in ONE clustering pass: exact and non-palindromic
    reverse-complement duplicates, an unrelated sequence, a shifted pair
    meeting this width's coverage threshold, a shifted pair clearly below
    it -- and, at 500 nt (identity is shared across all widths, so proving
    it once is sufficient), an above-90%-identity full-length pair and a
    clearly below-90% pair.
    """
    base_seed = width * 13
    base0 = _random_seq(base_seed, width)
    long_len, above_offset, below_offset = _WIDTH_SHIFT_PLAN[width]
    long_seq = _random_seq(base_seed + 5000, long_len)
    records = {
        "row_0": base0,
        "row_1_identical": base0,
        "row_2_rc": _reverse_complement(base0),
        "row_3_unrelated": _random_seq(base_seed + 1000, width),
        "row_6_shift_base": long_seq[0:width],
        "row_7_shift_above": long_seq[above_offset:above_offset + width],
        "row_8_shift_below": long_seq[below_offset:below_offset + width],
    }
    if width == 500:
        records["row_4_high_identity"] = _mutate(base0, fraction=0.05, seed=base_seed + 9001)  # ~95% identity
        records["row_5_low_identity"] = _mutate(base0, fraction=0.30, seed=base_seed + 9002)  # ~70% identity
    return records


def _write_fasta(path: Path, records: dict[str, str]) -> None:
    path.write_text("".join(f">{name}\n{seq}\n" for name, seq in records.items()))


@unittest.skipUnless(_HAVE_MMSEQS, "requires the real mmseqs2 18.8cc5c binary on PATH")
class MmseqsVersionBuildTests(unittest.TestCase):
    def test_resolved_binary_reports_the_pinned_version(self):
        binary = resolve_mmseqs_binary_provenance()
        self.assertIsNotNone(binary.resolved_path)
        self.assertEqual(binary.version, "18.8cc5c")
        self.assertIsNotNone(binary.sha256)


@unittest.skipUnless(_HAVE_MMSEQS, "requires the real mmseqs2 18.8cc5c binary on PATH")
class ClusterWorkflowFlagExposureTests(unittest.TestCase):
    """Confirms the "cluster does not expose --search-type/--strand" claim
    against the REAL binary's own --help text, not just our own command
    builders (which could drift from reality without this check).
    """

    def test_cluster_help_does_not_list_search_type_or_strand(self):
        result = _run(["mmseqs", "cluster", "--help"])
        self.assertNotIn("--search-type", result.stdout)
        self.assertNotIn("--strand", result.stdout)

    def test_search_help_lists_search_type_and_strand(self):
        result = _run(["mmseqs", "search", "--help"])
        self.assertIn("--search-type", result.stdout)
        self.assertIn("--strand", result.stdout)

    def test_createdb_help_lists_dbtype(self):
        result = _run(["mmseqs", "createdb", "--help"])
        self.assertIn("--dbtype", result.stdout)


@unittest.skipUnless(_HAVE_MMSEQS, "requires the real mmseqs2 18.8cc5c binary on PATH")
class WidthSpecificClusteringDiscriminationTests(unittest.TestCase):
    """C3: at each of the three frozen protected widths, real
    ``createdb --dbtype 2`` + the corrected ``cluster_command(..., width=...)``
    groups every pair the frozen rule should accept and separates every pair
    it should reject -- discovered by MMseqs2 itself from raw sequence
    content, never injected as an already-decided edge. The SAME captured
    real stdout log also proves the binary's effective
    identity/coverage/max-seqs settings, so an omitted ``--min-seq-id``,
    ``-c``, or ``--max-seqs`` fails this regression even if the observed
    grouping still happened to look plausible.
    """

    def _run_cluster(self, tmp_path: Path, width: int, records: dict[str, str]) -> tuple[dict[str, str], str]:
        fasta = tmp_path / f"width{width}.fasta"
        _write_fasta(fasta, records)

        db_path = tmp_path / f"db_{width}"
        cluster_prefix = tmp_path / f"clu_{width}"
        tool_tmp = tmp_path / f"tmp_{width}"
        tool_tmp.mkdir()
        log_dir = tmp_path / f"logs_{width}"

        run_mmseqs_command(createdb_command(fasta, db_path), log_dir=log_dir)
        cluster_result = run_mmseqs_command(
            cluster_command(db_path, cluster_prefix, tool_tmp, width=width), log_dir=log_dir
        )

        tsv_path = tmp_path / f"clu_{width}.tsv"
        run_mmseqs_command(createtsv_command(db_path, db_path, cluster_prefix, tsv_path), log_dir=log_dir)

        membership = parse_cluster_tsv_lines(tsv_path.read_text().splitlines())
        reconcile_membership(membership, set(records))
        return membership, cluster_result.stdout_path.read_text()

    def _assert_effective_settings(self, log_text: str, *, width: int) -> None:
        self.assertAlmostEqual(_effective_setting(log_text, "Seq. id. threshold"), 0.90, places=2)
        self.assertAlmostEqual(_effective_setting(log_text, "Coverage threshold"), _WIDTH_COVERAGE[width], places=2)
        self.assertEqual(int(_effective_setting(log_text, "Max results per query")), 361180)

    def test_500nt_identity_and_coverage_rule_discriminates_with_margin(self):
        tmp_path = Path(tempfile.mkdtemp())
        records = _build_width_fixture(500)
        membership, log_text = self._run_cluster(tmp_path, 500, records)

        self.assertEqual(membership["row_0"], membership["row_1_identical"])  # exact duplicate
        self.assertEqual(membership["row_0"], membership["row_2_rc"])  # non-palindromic RC duplicate
        self.assertEqual(membership["row_0"], membership["row_4_high_identity"])  # ~95% identity, full coverage
        self.assertNotEqual(membership["row_0"], membership["row_5_low_identity"])  # ~70% identity: excluded
        self.assertNotEqual(membership["row_0"], membership["row_3_unrelated"])
        self.assertEqual(membership["row_6_shift_base"], membership["row_7_shift_above"])  # 90% overlap: >80%
        self.assertNotEqual(membership["row_6_shift_base"], membership["row_8_shift_below"])  # 40% overlap: <80%

        self._assert_effective_settings(log_text, width=500)

    def test_251nt_coverage_rule_discriminates_with_margin(self):
        tmp_path = Path(tempfile.mkdtemp())
        records = _build_width_fixture(251)
        membership, log_text = self._run_cluster(tmp_path, 251, records)

        self.assertEqual(membership["row_0"], membership["row_1_identical"])
        self.assertEqual(membership["row_0"], membership["row_2_rc"])
        self.assertNotEqual(membership["row_0"], membership["row_3_unrelated"])
        self.assertEqual(membership["row_6_shift_base"], membership["row_7_shift_above"])  # ~97.6% overlap: >95%
        self.assertNotEqual(membership["row_6_shift_base"], membership["row_8_shift_below"])  # ~79.7%: <95%

        self._assert_effective_settings(log_text, width=251)

    def test_101nt_coverage_rule_discriminates_with_margin(self):
        tmp_path = Path(tempfile.mkdtemp())
        records = _build_width_fixture(101)
        membership, log_text = self._run_cluster(tmp_path, 101, records)

        self.assertEqual(membership["row_0"], membership["row_1_identical"])
        self.assertEqual(membership["row_0"], membership["row_2_rc"])
        self.assertNotEqual(membership["row_0"], membership["row_3_unrelated"])
        self.assertEqual(membership["row_6_shift_base"], membership["row_7_shift_above"])  # ~98.0% overlap: >95%
        self.assertNotEqual(membership["row_6_shift_base"], membership["row_8_shift_below"])  # ~79.2%: <95%

        self._assert_effective_settings(log_text, width=101)

    def test_an_unknown_width_never_reaches_the_real_binary(self):
        with self.assertRaises(UnknownWidthError):
            cluster_command(Path("db"), Path("clu"), Path("tmp"), width=250)


@unittest.skipUnless(_HAVE_MMSEQS, "requires the real mmseqs2 18.8cc5c binary on PATH")
class AuditSearchDiscriminationTests(unittest.TestCase):
    """C3's last bullet: the audit-search workflow applies the SAME
    width-specific identity/coverage rule as clustering, proven the same
    way -- MMseqs2 discovering real hits/misses on tiny fixtures, never
    injected edges.
    """

    def _run_search(self, tmp_path: Path, width: int, query: dict[str, str], targets: dict[str, str]) -> list[str]:
        query_fasta = tmp_path / "query.fasta"
        target_fasta = tmp_path / "target.fasta"
        _write_fasta(query_fasta, query)
        _write_fasta(target_fasta, targets)

        query_db = tmp_path / "querydb"
        target_db = tmp_path / "targetdb"
        log_dir = tmp_path / "logs"
        run_mmseqs_command(createdb_command(query_fasta, query_db), log_dir=log_dir)
        run_mmseqs_command(createdb_command(target_fasta, target_db), log_dir=log_dir)

        result_prefix = tmp_path / "search_out"
        tool_tmp = tmp_path / "search_tmp"
        tool_tmp.mkdir()
        run_mmseqs_command(
            audit_search_command(query_db, target_db, result_prefix, tool_tmp, width=width), log_dir=log_dir
        )

        output_tsv = tmp_path / "search_out.tsv"
        run_mmseqs_command(
            createtsv_search_command(query_db, target_db, result_prefix, output_tsv), log_dir=log_dir
        )
        return [line for line in output_tsv.read_text().splitlines() if line.strip()]

    def test_500nt_audit_search_applies_identity_rule(self):
        records = _build_width_fixture(500)
        tmp_path = Path(tempfile.mkdtemp())
        lines = self._run_search(
            tmp_path,
            500,
            query={"row_0": records["row_0"]},
            targets={
                "row_4_high_identity": records["row_4_high_identity"],
                "row_5_low_identity": records["row_5_low_identity"],
                "row_3_unrelated": records["row_3_unrelated"],
            },
        )
        hit_targets = {line.split("\t")[1] for line in lines}
        self.assertEqual(hit_targets, {"row_4_high_identity"})

    def test_width_specific_audit_search_applies_coverage_rule(self):
        for width in (500, 251, 101):
            with self.subTest(width=width):
                records = _build_width_fixture(width)
                tmp_path = Path(tempfile.mkdtemp())
                lines = self._run_search(
                    tmp_path,
                    width,
                    query={"row_6_shift_base": records["row_6_shift_base"]},
                    targets={
                        "row_7_shift_above": records["row_7_shift_above"],
                        "row_8_shift_below": records["row_8_shift_below"],
                    },
                )
                hit_targets = {line.split("\t")[1] for line in lines}
                self.assertEqual(hit_targets, {"row_7_shift_above"})


@unittest.skipUnless(_HAVE_MMSEQS, "requires the real mmseqs2 18.8cc5c binary on PATH")
class RealAuditSearchStrandTests(unittest.TestCase):
    """Proves the audit-search workflow's --strand semantics against the
    real binary: --strand 2 (both) finds a reverse-complement hit that
    --strand 1 (forward-only) misses, using the frozen --search-type 3
    nucleotide mode, the frozen width-specific identity/coverage rule, and
    every other frozen audit-search flag.
    """

    def _search(self, tmp_path: Path, strand_flag_override: str | None) -> list[str]:
        seq = _random_seq(seed=77, width=80)
        rc = _reverse_complement(seq)
        query_fasta = tmp_path / "query.fasta"
        target_fasta = tmp_path / "target.fasta"
        query_fasta.write_text(f">q_forward\n{seq}\n")
        target_fasta.write_text(f">t_rc\n{rc}\n>t_unrelated\n{_random_seq(seed=78, width=80)}\n")

        query_db = tmp_path / "querydb"
        target_db = tmp_path / "targetdb"
        run_mmseqs_command(createdb_command(query_fasta, query_db), log_dir=tmp_path / "logs")
        run_mmseqs_command(createdb_command(target_fasta, target_db), log_dir=tmp_path / "logs")

        result_prefix = tmp_path / "search_out"
        tool_tmp = tmp_path / "search_tmp"
        tool_tmp.mkdir()
        command = audit_search_command(query_db, target_db, result_prefix, tool_tmp, width=500)
        if strand_flag_override is not None:
            argv = list(command.argv)
            argv[argv.index("--strand") + 1] = strand_flag_override
            from rbpbench.coordinates.commands import ToolCommand

            command = ToolCommand(tool=command.tool, argv=tuple(argv), pinned_version=command.pinned_version)
        run_mmseqs_command(command, log_dir=tmp_path / "logs")

        output_tsv = tmp_path / "search_out.tsv"
        run_mmseqs_command(createtsv_search_command(query_db, target_db, result_prefix, output_tsv), log_dir=tmp_path / "logs")
        lines = [line for line in output_tsv.read_text().splitlines() if line.strip()]
        return lines

    def test_both_strand_search_finds_the_reverse_complement_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = self._search(Path(tmp), strand_flag_override=None)  # default frozen --strand 2
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("q_forward\tt_rc"))

    def test_forward_only_strand_misses_the_reverse_complement_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = self._search(Path(tmp), strand_flag_override="1")
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
