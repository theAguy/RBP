import unittest
from pathlib import Path

from rbpbench.coordinates.commands import (
    bwa_mem_command,
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


if __name__ == "__main__":
    unittest.main()
