import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

from rbpbench.coordinates.provenance import BinaryProvenance
from rbpbench.data.audit import sha256_file
from rbpbench.splits.commands import (
    MmseqsExecutionError,
    NUCLEOTIDE_DBTYPE,
    UnknownWidthError,
    audit_search_command,
    cluster_command,
    createdb_command,
    createtsv_command,
    hash_db_files,
    new_generation_dir,
    run_mmseqs_command,
)


def _write_fake_binary(directory: Path, name: str, script_body: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n" + script_body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class CommandBuilderTests(unittest.TestCase):
    def test_createdb_pins_nucleotide_dbtype(self):
        cmd = createdb_command(Path("input.fasta"), Path("db"))
        self.assertEqual(list(cmd.argv), ["mmseqs", "createdb", "input.fasta", "db", "--dbtype", "2"])
        self.assertEqual(NUCLEOTIDE_DBTYPE, 2)

    def test_cluster_command_matches_frozen_flags_exactly_at_500nt(self):
        cmd = cluster_command(Path("db"), Path("clu"), Path("tmp"), width=500)
        argv = list(cmd.argv)
        self.assertEqual(argv[:5], ["mmseqs", "cluster", "db", "clu", "tmp"])
        flag_values = dict(zip(argv[5::2], argv[6::2]))
        self.assertEqual(len(argv[5:]), 2 * len(flag_values))  # no duplicated/stray flags
        self.assertEqual(
            flag_values,
            {
                "--min-seq-id": "0.90",
                "-c": "0.80",
                "--cov-mode": "0",
                "--max-seqs": "361180",
                "--alignment-mode": "3",
                "-e": "1000",
                "--mask": "0",
                "-s": "7.5",
                "--cluster-mode": "1",
                "--single-step-clustering": "1",
            },
        )

    def test_cluster_command_selects_coverage_by_width(self):
        for width, expected_coverage in ((500, "0.80"), (251, "0.95"), (101, "0.95")):
            with self.subTest(width=width):
                argv = list(cluster_command(Path("db"), Path("clu"), Path("tmp"), width=width).argv)
                self.assertEqual(argv[argv.index("-c") + 1], expected_coverage)
                self.assertEqual(argv[argv.index("--min-seq-id") + 1], "0.90")
                self.assertEqual(argv[argv.index("--cov-mode") + 1], "0")
                self.assertEqual(argv[argv.index("--max-seqs") + 1], "361180")

    def test_cluster_command_rejects_an_unknown_width_before_any_execution(self):
        with self.assertRaises(UnknownWidthError):
            cluster_command(Path("db"), Path("clu"), Path("tmp"), width=250)

    def test_cluster_command_has_no_identity_or_coverage_override_parameters(self):
        import inspect

        params = inspect.signature(cluster_command).parameters
        self.assertNotIn("min_seq_id", params)
        self.assertNotIn("coverage", params)
        self.assertNotIn("cov", params)

    def test_cluster_command_never_includes_search_type_or_strand(self):
        cmd = cluster_command(Path("db"), Path("clu"), Path("tmp"), width=500)
        argv = list(cmd.argv)
        self.assertNotIn("--search-type", argv)
        self.assertNotIn("--strand", argv)

    def test_audit_search_command_pins_search_type_and_strand(self):
        cmd = audit_search_command(Path("q"), Path("t"), Path("res"), Path("tmp"), width=500)
        argv = list(cmd.argv)
        self.assertIn("--search-type", argv)
        self.assertEqual(argv[argv.index("--search-type") + 1], "3")
        self.assertIn("--strand", argv)
        self.assertEqual(argv[argv.index("--strand") + 1], "2")
        # Same shared identity/coverage/alignment/e-value/mask/sensitivity
        # flags as cluster, at the same 500nt width.
        for flag, value in (
            ("--min-seq-id", "0.90"),
            ("-c", "0.80"),
            ("--cov-mode", "0"),
            ("--max-seqs", "361180"),
            ("--alignment-mode", "3"),
            ("-e", "1000"),
            ("--mask", "0"),
            ("-s", "7.5"),
        ):
            self.assertEqual(argv[argv.index(flag) + 1], value)

    def test_audit_search_command_selects_coverage_by_width(self):
        for width, expected_coverage in ((500, "0.80"), (251, "0.95"), (101, "0.95")):
            with self.subTest(width=width):
                argv = list(audit_search_command(Path("q"), Path("t"), Path("res"), Path("tmp"), width=width).argv)
                self.assertEqual(argv[argv.index("-c") + 1], expected_coverage)

    def test_audit_search_command_rejects_an_unknown_width_before_any_execution(self):
        with self.assertRaises(UnknownWidthError):
            audit_search_command(Path("q"), Path("t"), Path("res"), Path("tmp"), width=999)

    def test_audit_search_command_and_cluster_command_are_distinct_workflows(self):
        cluster_argv = list(cluster_command(Path("db"), Path("clu"), Path("tmp"), width=500).argv)
        search_argv = list(audit_search_command(Path("q"), Path("t"), Path("res"), Path("tmp"), width=500).argv)
        self.assertEqual(cluster_argv[1], "cluster")
        self.assertEqual(search_argv[1], "search")
        self.assertNotIn("--search-type", cluster_argv)
        self.assertIn("--search-type", search_argv)

    def test_argv_is_a_tuple_of_strings_never_a_shell_string(self):
        cmd = createtsv_command(Path("q"), Path("t"), Path("clu"), Path("out.tsv"))
        self.assertIsInstance(cmd.argv, tuple)
        self.assertTrue(all(isinstance(part, str) for part in cmd.argv))


class RunMmseqsCommandTests(unittest.TestCase):
    def test_successful_run_captures_separate_stdout_and_stderr_with_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _write_fake_binary(
                tmp_path, "fake_mmseqs_ok",
                textwrap.dedent(
                    """
                    echo "stdout line"
                    echo "stderr diagnostic line" 1>&2
                    exit 0
                    """
                ),
            )
            from rbpbench.coordinates.commands import ToolCommand

            command = ToolCommand(tool="mmseqs_createdb", argv=(str(fake), "arg1"), pinned_version="18.8cc5c")
            binary = BinaryProvenance(exe_name=str(fake), resolved_path=str(fake), sha256="deadbeef", version="18.8cc5c")
            result = run_mmseqs_command(command, log_dir=tmp_path / "logs", binary=binary)

            self.assertEqual(result.tool, "mmseqs_createdb")
            self.assertTrue(result.stdout_path.is_file())
            self.assertTrue(result.stderr_path.is_file())
            self.assertIn("stdout line", result.stdout_path.read_text())
            self.assertIn("stderr diagnostic line", result.stderr_path.read_text())
            self.assertNotEqual(result.stdout_sha256, result.stderr_sha256)
            self.assertEqual(result.binary.sha256, "deadbeef")

    def test_non_zero_exit_raises_and_preserves_stderr_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _write_fake_binary(
                tmp_path, "fake_mmseqs_fail",
                textwrap.dedent(
                    """
                    echo "fatal: bad flag" 1>&2
                    exit 1
                    """
                ),
            )
            from rbpbench.coordinates.commands import ToolCommand

            command = ToolCommand(tool="mmseqs_cluster", argv=(str(fake),), pinned_version="18.8cc5c")
            log_dir = tmp_path / "logs"
            with self.assertRaises(MmseqsExecutionError):
                run_mmseqs_command(command, log_dir=log_dir)
            stderr_logs = list(log_dir.glob("mmseqs_cluster.*.stderr.log"))
            self.assertEqual(len(stderr_logs), 1)
            self.assertIn("fatal: bad flag", stderr_logs[0].read_text())

    def test_timeout_kills_the_process_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _write_fake_binary(tmp_path, "fake_mmseqs_hang", "sleep 30\n")
            from rbpbench.coordinates.commands import ToolCommand

            command = ToolCommand(tool="mmseqs_search", argv=(str(fake),), pinned_version="18.8cc5c")
            binary = BinaryProvenance(exe_name=str(fake), resolved_path=str(fake), sha256="deadbeef", version=None)
            with self.assertRaises(MmseqsExecutionError) as ctx:
                run_mmseqs_command(command, log_dir=tmp_path / "logs", timeout_seconds=1, binary=binary)
            self.assertIn("timed out", str(ctx.exception))

    def test_missing_binary_is_a_hard_failure_not_a_silent_skip(self):
        from rbpbench.coordinates.commands import ToolCommand

        command = ToolCommand(tool="mmseqs_createdb", argv=("definitely-not-a-real-mmseqs-binary-xyz",), pinned_version="18.8cc5c")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises((MmseqsExecutionError, FileNotFoundError, OSError)):
                run_mmseqs_command(command, log_dir=Path(tmp) / "logs")


class LogPathUniquenessTests(unittest.TestCase):
    """C4: two same-tool invocations sharing one log directory (e.g. the two
    ``createdb`` calls that build a query and a target database for an
    audit search) must never collide -- neither invocation's returned,
    already-hashed stdout/stderr path may be silently overwritten by the
    other.
    """

    def test_two_createdb_style_invocations_in_one_log_dir_never_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _write_fake_binary(
                tmp_path, "fake_mmseqs_createdb",
                textwrap.dedent(
                    """
                    echo "created $1"
                    echo "createdb diagnostic for $1" 1>&2
                    exit 0
                    """
                ),
            )
            from rbpbench.coordinates.commands import ToolCommand

            log_dir = tmp_path / "logs"
            first_command = ToolCommand(tool="mmseqs_createdb", argv=(str(fake), "query_db"), pinned_version="18.8cc5c")
            second_command = ToolCommand(tool="mmseqs_createdb", argv=(str(fake), "target_db"), pinned_version="18.8cc5c")

            first = run_mmseqs_command(first_command, log_dir=log_dir)
            second = run_mmseqs_command(second_command, log_dir=log_dir)

            self.assertNotEqual(first.stdout_path, second.stdout_path)
            self.assertNotEqual(first.stderr_path, second.stderr_path)

            # Both EARLIER RETURNED paths re-hash successfully to their own
            # recorded hash: neither record was left pointing at content the
            # other, later, same-tool invocation overwrote.
            self.assertEqual(sha256_file(first.stdout_path), first.stdout_sha256)
            self.assertEqual(sha256_file(second.stdout_path), second.stdout_sha256)
            self.assertNotEqual(first.stdout_sha256, second.stdout_sha256)

            self.assertIn("created query_db", first.stdout_path.read_text())
            self.assertNotIn("created target_db", first.stdout_path.read_text())
            self.assertIn("created target_db", second.stdout_path.read_text())
            self.assertNotIn("created query_db", second.stdout_path.read_text())


class NewGenerationDirTests(unittest.TestCase):
    def test_each_call_returns_a_fresh_unique_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = new_generation_dir(base, prefix="cluster500")
            second = new_generation_dir(base, prefix="cluster500")
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())

    def test_a_failed_generation_never_corrupts_a_prior_accepted_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            accepted = new_generation_dir(base, prefix="cluster500")
            (accepted / "cluster_db").write_text("accepted output")

            # A second attempt gets its own directory; even if it "fails"
            # (simulated here by just not writing anything and being
            # abandoned), the accepted generation's file is untouched.
            failed = new_generation_dir(base, prefix="cluster500")
            self.assertNotEqual(accepted, failed)
            self.assertEqual((accepted / "cluster_db").read_text(), "accepted output")


class HashDbFilesTests(unittest.TestCase):
    def test_hashes_every_sibling_file_sharing_the_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db = tmp_path / "db"
            db.write_bytes(b"db-content")
            (tmp_path / "db.dbtype").write_bytes(b"\x02\x00\x00\x00")
            (tmp_path / "db.index").write_bytes(b"index-content")
            (tmp_path / "unrelated").write_bytes(b"should not be included")

            hashes = hash_db_files(db)
            self.assertIn("db", hashes)
            self.assertIn("db.dbtype", hashes)
            self.assertIn("db.index", hashes)
            self.assertNotIn("unrelated", hashes)


if __name__ == "__main__":
    unittest.main()
