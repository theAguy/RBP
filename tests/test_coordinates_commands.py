import unittest
from pathlib import Path

from rbpbench.coordinates.commands import (
    bwa_mem_command,
    canonical_probe_commands,
    format_command,
    minimap2_splice_command,
    resolve_version,
    seqkit_locate_command,
)


class CommandsTests(unittest.TestCase):
    def test_bwa_mem_command_matches_pinned_invocation(self):
        cmd = bwa_mem_command(Path("ref.fa"), Path("reads.fa"), threads=4)
        self.assertEqual(
            list(cmd.argv),
            ["bwa", "mem", "-a", "-Y", "-t", "4", "ref.fa", "reads.fa"],
        )
        self.assertEqual(cmd.pinned_version, "0.7.19")

    def test_minimap2_command_matches_pinned_invocation(self):
        cmd = minimap2_splice_command(Path("ref.fa"), Path("reads.fa"), threads=2)
        self.assertEqual(
            list(cmd.argv),
            [
                "minimap2", "-ax", "splice:sr", "--secondary=yes", "-N", "20",
                "--MD", "--eqx", "-t", "2", "ref.fa", "reads.fa",
            ],
        )
        self.assertEqual(cmd.pinned_version, "2.31")

    def test_seqkit_command_is_argv_list_not_a_shell_string(self):
        cmd = seqkit_locate_command(Path("queries.fa"), Path("ref.fa"))
        self.assertIsInstance(cmd.argv, tuple)
        self.assertTrue(all(isinstance(part, str) for part in cmd.argv))

    def test_rejects_non_positive_thread_count(self):
        with self.assertRaises(ValueError):
            bwa_mem_command(Path("ref.fa"), Path("reads.fa"), threads=0)
        with self.assertRaises(ValueError):
            minimap2_splice_command(Path("ref.fa"), Path("reads.fa"), threads=-1)

    def test_format_command_is_shell_quoted_for_display_only(self):
        rendered = format_command(["bwa", "mem", "a path with space"])
        self.assertIn("'a path with space'", rendered)

    def test_resolve_version_returns_none_for_missing_binary(self):
        self.assertIsNone(resolve_version(["definitely-not-a-real-binary-xyz"]))


class CanonicalProbeCommandsTests(unittest.TestCase):
    """B3A-F1: the probe stage's ONE stable command-semantics
    representation -- independent of any specific generation's random
    candidate/index/query paths, used for both an accepted probe's own
    fingerprint and every restart recomputation.
    """

    def test_is_independent_of_real_generation_paths(self):
        """The whole point of B3A-F1: two calls that only ever differ by
        REAL, per-generation candidate/index paths must still be compared
        against the SAME canonical representation -- canonical_probe_commands
        never even accepts those paths as input, so it cannot vary with them.
        """
        first = canonical_probe_commands(threads=1)
        second = canonical_probe_commands(threads=1)
        self.assertEqual(first, second)
        bwa_command, minimap2_command, seqkit_command = first
        # Never a real, random generation-directory path -- always the
        # fixed placeholder tokens.
        for real_path in (
            "/tmp/pytest-of-x/generations/probe-000123-abcdef/candidate/patterns.fasta",
            "/private/var/folders/xy/generations/probe-987654-fedcba/candidate/contig.fna",
        ):
            self.assertNotIn(real_path, bwa_command)
            self.assertNotIn(real_path, minimap2_command)
            self.assertNotIn(real_path, seqkit_command)
        self.assertIn("REFERENCE", bwa_command)
        self.assertIn("READS", bwa_command)
        self.assertIn("REFERENCE", minimap2_command)
        self.assertIn("READS", minimap2_command)
        self.assertIn("QUERY", seqkit_command)
        self.assertIn("REFERENCE", seqkit_command)

    def test_matches_the_real_command_builders_flags_exactly(self):
        """The canonical representation must still carry every real command
        FLAG (thread count, mode, pinned options) -- it substitutes only the
        path arguments, never silently drops or alters a flag.
        """
        bwa_command, minimap2_command, seqkit_command = canonical_probe_commands(threads=1)
        self.assertEqual(
            bwa_command, format_command(bwa_mem_command(Path("REFERENCE"), Path("READS"), threads=1).argv)
        )
        self.assertEqual(
            minimap2_command,
            format_command(minimap2_splice_command(Path("REFERENCE"), Path("READS"), threads=1).argv),
        )
        self.assertEqual(seqkit_command, format_command(seqkit_locate_command(Path("QUERY"), Path("REFERENCE")).argv))

    def test_thread_count_still_changes_the_canonical_representation(self):
        """Only PATHS are canonicalized -- a genuine flag/semantics change
        (thread count) must still change the rendered command.
        """
        one_thread, _, _ = canonical_probe_commands(threads=1)
        two_threads, _, _ = canonical_probe_commands(threads=2)
        self.assertNotEqual(one_thread, two_threads)


if __name__ == "__main__":
    unittest.main()
