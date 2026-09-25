"""Real-binary tiny smoke tests against the pinned MMseqs2 18.8cc5c
(build h8b377d6_0), installed in the isolated ``rbpbench-splits-002``
conda environment (``manifests/sequence_partition_environment_002a.yml``).

Every test here is skipped cleanly when ``mmseqs`` is not on PATH, so the
ordinary test suite never depends on that isolated environment being active
-- exactly like ``tests/test_coordinates_real_binaries.py`` for
BWA/minimap2/SeqKit. All fixtures are tiny and synthetic; nothing here
touches the real dataset.

These tests are the executable proof required by
``docs/tasks/002_sequence_clustered_partitions.md`` and
``docs/handoffs/002a_sequence_partition_pipeline_claude_handoff.md``: the
installed binary truly uses nucleotide alignments (explicit type-2
database), both strands, true identity, disabled masking, the explicit
E-value ceiling, connected-component clustering, and single-step graph
construction -- and that ``cluster`` truly does not expose
``--search-type``/``--strand`` while ``search`` (the separate audit-search
workflow) truly does.
"""

from __future__ import annotations

import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from rbpbench.splits.commands import (
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
class RealClusteringReverseComplementFixtureTests(unittest.TestCase):
    """The scientific gate required before any real-data execution: on a
    tiny, non-palindromic fixture, real ``createdb --dbtype 2`` +
    ``cluster`` with every frozen flag groups an exact duplicate AND a
    reverse-complement duplicate into the SAME cluster as their source, at
    every protected width, while an unrelated sequence stays separate --
    proving both-orientation nucleotide clustering without a --strand flag
    that ``cluster`` does not expose.
    """

    def _cluster_tiny_fixture(self, tmp_path: Path, width: int) -> dict[str, str]:
        seq = _random_seq(seed=width, width=width)
        rc = _reverse_complement(seq)
        unrelated = _random_seq(seed=width + 1000, width=width)
        self.assertNotEqual(seq, rc)  # non-palindromic fixture, a real test of RC-awareness

        fasta = tmp_path / f"tiny_{width}.fasta"
        fasta.write_text(
            f">row_0\n{seq}\n"
            f">row_1_rc_of_row0\n{rc}\n"
            f">row_2_unrelated\n{unrelated}\n"
            f">row_3_identical_to_row0\n{seq}\n"
        )

        db_path = tmp_path / f"db_{width}"
        cluster_prefix = tmp_path / f"clu_{width}"
        tool_tmp = tmp_path / f"tmp_{width}"
        tool_tmp.mkdir()
        log_dir = tmp_path / f"logs_{width}"

        run_mmseqs_command(createdb_command(fasta, db_path), log_dir=log_dir)
        run_mmseqs_command(cluster_command(db_path, cluster_prefix, tool_tmp), log_dir=log_dir)

        tsv_path = tmp_path / f"clu_{width}.tsv"
        run_mmseqs_command(createtsv_command(db_path, db_path, cluster_prefix, tsv_path), log_dir=log_dir)

        membership = parse_cluster_tsv_lines(tsv_path.read_text().splitlines())
        reconcile_membership(
            membership, {"row_0", "row_1_rc_of_row0", "row_2_unrelated", "row_3_identical_to_row0"}
        )
        return membership

    def test_exact_and_reverse_complement_duplicates_cluster_together_at_500nt(self):
        membership = self._cluster_tiny_fixture(Path(tempfile.mkdtemp()), 500)
        self._assert_expected_grouping(membership)

    def test_exact_and_reverse_complement_duplicates_cluster_together_at_251nt(self):
        membership = self._cluster_tiny_fixture(Path(tempfile.mkdtemp()), 251)
        self._assert_expected_grouping(membership)

    def test_exact_and_reverse_complement_duplicates_cluster_together_at_101nt(self):
        membership = self._cluster_tiny_fixture(Path(tempfile.mkdtemp()), 101)
        self._assert_expected_grouping(membership)

    def _assert_expected_grouping(self, membership: dict[str, str]) -> None:
        self.assertEqual(membership["row_0"], membership["row_1_rc_of_row0"])
        self.assertEqual(membership["row_0"], membership["row_3_identical_to_row0"])
        self.assertNotEqual(membership["row_0"], membership["row_2_unrelated"])


@unittest.skipUnless(_HAVE_MMSEQS, "requires the real mmseqs2 18.8cc5c binary on PATH")
class RealAuditSearchStrandTests(unittest.TestCase):
    """Proves the audit-search workflow's --strand semantics against the
    real binary: --strand 2 (both) finds a reverse-complement hit that
    --strand 1 (forward-only) misses, using the frozen --search-type 3
    nucleotide mode and every other frozen audit-search flag.
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
        command = audit_search_command(query_db, target_db, result_prefix, tool_tmp)
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
