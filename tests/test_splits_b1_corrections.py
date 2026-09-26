"""Task 002B-1 bounded orchestration corrections
(docs/handoffs/002b1_orchestration_corrections_claude_handoff.md,
docs/reviews/002b1_orchestration_review.md).

Every regression here must FAIL against commit ``52fd295`` (the
pre-correction implementation) and PASS against the corrected
``rbpbench.splits.runner``. All fixtures are tiny and synthetic; nothing
here touches the real dataset, the real Task 002 artifact directory, or the
real MMseqs2 binary's scientific behavior.
"""

from __future__ import annotations

import csv
import json
import os
import random
import stat
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.decode import encode_sequence
from rbpbench.data.audit import sha256_file
from rbpbench.splits import runner
from rbpbench.splits.commands import PINNED_VERSION
from rbpbench.splits.config import load_config


def _marker_sequence(seed: int, width: int = 500) -> str:
    rng = random.Random(seed)
    return "".join(rng.choice("ACGT") for _ in range(width))


def _write_fake_mmseqs(directory: Path, *, version: str = PINNED_VERSION, name: str = "fake_mmseqs") -> Path:
    path = directory / name
    path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import sys, pathlib

            def read_ids(fasta_path):
                ids = []
                for line in open(fasta_path):
                    if line.startswith(">"):
                        ids.append(line[1:].strip())
                return ids

            args = sys.argv[1:]
            cmd = args[0]
            if cmd == "version":
                print({version!r})
            elif cmd == "createdb":
                input_fasta, db = args[1], args[2]
                ids = read_ids(input_fasta)
                pathlib.Path(db).write_text("fakedb")
                pathlib.Path(db + ".dbtype").write_bytes(bytes([2, 0, 0, 0]))
                pathlib.Path(db + ".fake_ids").write_text("\\n".join(ids))
            elif cmd == "cluster":
                pathlib.Path(args[2]).write_text("fakecluster")
            elif cmd == "createtsv":
                query_db, output = args[1], args[4]
                ids = pathlib.Path(query_db + ".fake_ids").read_text().splitlines()
                with open(output, "w") as fh:
                    for sample_id in ids:
                        fh.write(f"{{sample_id}}\\t{{sample_id}}\\n")
            else:
                sys.exit(1)
            sys.exit(0)
            """
        )
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _build_fixture(
    tmp_path: Path,
    sequences: list[str],
    *,
    mmseqs_bin_path: Path,
    csv_filename: str | None = None,
    audit_filename: str | None = None,
    proteins_filename: str | None = None,
    sample_size: int = 4,
    max_new_disk_gib: float = 1000.0,
    min_free_disk_gib: float = 0.0000001,
    timeout_seconds: float = 60,
    max_peak_memory_gib: float = 1000.0,
    min_available_memory_gib: float = 0.0000001,
    min_available_memory_gib_before_launch: float = 0.0000001,
    min_installed_ram_gib: float = 0.0,
    resource_poll_interval_seconds: float = 0.02,
    expected_row_count: int | None = None,
) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    csv_path = tmp_path / (csv_filename or "dataset.csv")
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sequence", "labels"])
        for seq in sequences:
            writer.writerow([encode_sequence(seq), ""])

    audit_path = tmp_path / (audit_filename or "audit.json")
    audit_path.write_text("{}")
    proteins_path = tmp_path / (proteins_filename or "proteins.tsv")
    proteins_path.write_text("dummy\n")

    csv_ref = csv_path.name if csv_filename is not None else str(csv_path)
    audit_ref = audit_path.name if audit_filename is not None else str(audit_path)
    proteins_ref = proteins_path.name if proteins_filename is not None else str(proteins_path)

    config_text = textwrap.dedent(
        f"""
        seed = 20260925
        protected_widths = [500, 251, 101]

        [dataset]
        csv_filename = "{csv_ref}"
        csv_sha256 = "{sha256_file(csv_path)}"
        csv_byte_size = {csv_path.stat().st_size}
        expected_row_count = {expected_row_count if expected_row_count is not None else len(sequences)}
        audit_json_path = "{audit_ref}"
        audit_json_sha256 = "{sha256_file(audit_path)}"
        proteins_tsv_path = "{proteins_ref}"
        proteins_tsv_sha256 = "{sha256_file(proteins_path)}"

        [binary]
        mmseqs_sha256 = "{sha256_file(mmseqs_bin_path)}"

        [resources]
        max_threads = 4
        timeout_seconds = {timeout_seconds}
        max_new_disk_gib = {max_new_disk_gib}
        min_free_disk_gib = {min_free_disk_gib}
        min_installed_ram_gib = {min_installed_ram_gib}
        min_available_memory_gib_before_launch = {min_available_memory_gib_before_launch}
        resource_poll_interval_seconds = {resource_poll_interval_seconds}

        [probe]
        sample_size = {sample_size}
        max_peak_memory_gib = {max_peak_memory_gib}
        min_available_memory_gib_before_next_stage = {min_available_memory_gib}

        [gate]
        giant_single_component_fraction = 0.05
        giant_top20_fraction = 0.20
        """
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_text)
    return csv_path, config_path


def _preflight(config, dataset_csv, output_dir, *, mmseqs_bin, audit_json=None, proteins_tsv=None, dry_run=False):
    return runner.stage_preflight(
        config=config,
        dataset_csv=dataset_csv,
        audit_json=audit_json if audit_json is not None else Path(config.dataset.audit_json_path),
        proteins_tsv=proteins_tsv if proteins_tsv is not None else Path(config.dataset.proteins_tsv_path),
        output_dir=output_dir,
        mmseqs_bin=mmseqs_bin,
        dry_run=dry_run,
    )


def _preflight_and_decode(tmp_path: Path, sequences: list[str], *, mmseqs_bin_path: Path | None = None, **fixture_kwargs):
    """``mmseqs_bin_path`` lets a caller supply its own binary (accepted at
    preflight time, so ``config.binary.mmseqs_sha256`` matches it) instead of
    the default fast fake -- needed by any test that later calls a stage
    function with a binary other than the default, since probe/cluster now
    independently reject a binary that does not match the accepted config
    (FC1).
    """
    fake_bin = mmseqs_bin_path if mmseqs_bin_path is not None else _write_fake_mmseqs(tmp_path)
    csv_path, config_path = _build_fixture(tmp_path, sequences, mmseqs_bin_path=fake_bin, **fixture_kwargs)
    config = load_config(config_path)
    output_dir = tmp_path / "out"
    preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))
    decode_record = runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
    return config, output_dir, decode_record, fake_bin


def _accept_all_probes(config, output_dir, decode_record, mmseqs_bin):
    for width in config.protected_widths:
        runner.stage_probe(width=width, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(mmseqs_bin))


def _generation_dirs(output_dir: Path, *parts: str) -> set:
    root = output_dir.joinpath(*parts, "generations")
    return set(root.iterdir()) if root.is_dir() else set()


class _RamMockedTestCase(unittest.TestCase):
    """FC3: mocks a sufficient numeric installed-RAM value for the whole
    test body. None of these fixtures test installed-RAM DETECTION itself,
    so a restricted host where ``sysctl``/``/proc/meminfo`` is unavailable
    (installed RAM detects as ``None``) must not fail them at an incidental
    preflight/current-preflight RAM gate -- only the dedicated
    ``FC3InstalledRamFailClosedTests`` below exercises that detection path,
    and does not inherit this mock.
    """

    def setUp(self):
        patcher = mock.patch("rbpbench.splits.runner.detect_physical_ram_gib", return_value=64.0)
        patcher.start()
        self.addCleanup(patcher.stop)


class R1SameRowCountCsvMutationTests(_RamMockedTestCase):
    """Regression 1: same-row-count CSV mutation after accepted preflight
    makes decode refuse before creating a generation.
    """

    def test_decode_refuses_a_silently_mutated_csv_before_any_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            seqs = [_marker_sequence(1), _marker_sequence(2)]
            csv_path, config_path = _build_fixture(tmp_path, seqs, mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))

            # Same row count, different byte content (e.g. a corrupted or
            # silently re-generated CSV) -- not re-validated by preflight.
            with csv_path.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["sequence", "labels"])
                writer.writerow([encode_sequence(_marker_sequence(3)), ""])
                writer.writerow([encode_sequence(_marker_sequence(4)), ""])

            before = _generation_dirs(output_dir, "decode")
            with self.assertRaises(runner.StaleAcceptanceError):
                runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            after = _generation_dirs(output_dir, "decode")
            self.assertEqual(before, after, "decode must not create a generation before the stale-CSV check")


class R2ForceRebuildInvalidatesClusterTests(_RamMockedTestCase):
    """Regression 2: force-replacing decode invalidates an old cluster even
    when source bytes are unchanged.
    """

    def test_force_rebuilt_decode_invalidates_the_old_cluster_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))

            preflight_record = runner._require_accepted(output_dir, "preflight")
            new_decode_record = runner.stage_decode(config=config, dataset_csv=Path(config.dataset.csv_filename), output_dir=output_dir, preflight_record=preflight_record)
            self.assertNotEqual(new_decode_record["generation_digest"], decode_record["generation_digest"])

            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner._require_current_width_stage(output_dir=output_dir, stage_name="cluster", width=500, config=config, decode_record=new_decode_record)


class R3ClusterRequiresCurrentProbesTests(_RamMockedTestCase):
    """Regression 3: cluster refuses before all three current probes and
    launches no subprocess.
    """

    def test_cluster_launches_no_subprocess_without_current_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            # Only accept ONE of the three required probe widths.
            runner.stage_probe(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))

            with mock.patch("rbpbench.splits.runner.run_guarded_mmseqs") as mocked:
                with self.assertRaises(runner.PriorStageNotAcceptedError):
                    runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
                mocked.assert_not_called()
            self.assertFalse((output_dir / "cluster").exists())


class R4StaleTamperedUpstreamBlocksDownstreamTests(_RamMockedTestCase):
    """Regression 4: stale/tampered probe or cluster upstream evidence
    blocks downstream work.
    """

    def test_tampered_decode_generation_blocks_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            # Tamper with one byte of a retained decode artifact.
            fasta_path = Path(decode_record["fasta_paths"]["500"])
            fasta_path.write_text(fasta_path.read_text() + "X")

            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner._require_accepted(output_dir, "decode")
            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner.stage_probe(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))

    def test_tampered_probe_generation_blocks_cluster(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            probe_record = json.loads((output_dir / "selected" / "probe_500.json").read_text())
            # Add a stray extra file into the accepted probe generation.
            (Path(probe_record["generation_dir"]) / "unexpected_extra_file.bin").write_bytes(b"tampered")

            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))


class R5WrongBinarySha256Tests(_RamMockedTestCase):
    """Regression 5: binary with correct version but wrong SHA fails
    preflight.
    """

    def test_correct_version_wrong_sha_fails_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pinned_bin = _write_fake_mmseqs(tmp_path, name="pinned_mmseqs")
            other_bin = _write_fake_mmseqs(tmp_path, name="other_mmseqs")
            other_bin.write_text(other_bin.read_text() + "\n# a different, unpinned build\n")
            self.assertEqual(runner.splits_commands.resolve_mmseqs_binary_provenance(str(other_bin)).version, PINNED_VERSION)
            self.assertNotEqual(sha256_file(pinned_bin), sha256_file(other_bin))

            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=pinned_bin)
            config = load_config(config_path)
            with self.assertRaises(runner.PreflightError) as ctx:
                _preflight(config, csv_path, tmp_path / "out", mmseqs_bin=str(other_bin))
            self.assertIn("SHA-256", str(ctx.exception))


class R6AvailableMemoryLaunchGateTests(_RamMockedTestCase):
    """Regression 6: missing/unknown/low available-memory evidence prevents
    MMseqs2 launch.
    """

    def test_none_available_memory_is_a_hard_failure_before_any_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            with mock.patch("rbpbench.splits.runner.detect_available_memory_gib", return_value=None):
                with mock.patch("rbpbench.splits.runner.run_guarded_mmseqs") as mocked:
                    with self.assertRaises(runner.ResourceGateExceededError):
                        runner.stage_probe(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
                    mocked.assert_not_called()

    def test_low_available_memory_is_a_hard_failure_before_any_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(
                tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin, min_available_memory_gib_before_launch=1e9
            )
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))
            decode_record = runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            with mock.patch("rbpbench.splits.runner.run_guarded_mmseqs") as mocked:
                with self.assertRaises(runner.ResourceGateExceededError):
                    runner.stage_probe(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
                mocked.assert_not_called()


def _write_growing_file_mmseqs(
    directory: Path,
    *,
    chunk_bytes: int = 300_000,
    iterations: int = 400,
    sleep_seconds: float = 0.05,
    activate_env_var: str = "RBPBENCH_TEST_GROW",
) -> Path:
    """Only grows disk on ``cluster`` when ``activate_env_var`` is set in the
    environment, and otherwise behaves like a normal fast fake mmseqs (full
    createdb/cluster/createtsv support) -- so this SAME binary can be the one
    accepted at preflight time (satisfying the FC1 binary-identity check for
    every stage, including probe acceptance) and only grows disk for the
    specific cluster invocation under test.
    """
    path = directory / "growing_mmseqs"
    path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import os, sys, pathlib, time
            args = sys.argv[1:]
            cmd = args[0]
            if cmd == "version":
                print({PINNED_VERSION!r})
            elif cmd == "createdb":
                input_fasta, db = args[1], args[2]
                ids = [line[1:].strip() for line in open(input_fasta) if line.startswith(">")]
                pathlib.Path(db).write_text("fakedb")
                pathlib.Path(db + ".dbtype").write_bytes(bytes([2, 0, 0, 0]))
                pathlib.Path(db + ".fake_ids").write_text("\\n".join(ids))
            elif cmd == "cluster":
                if os.environ.get({activate_env_var!r}):
                    growth_file = pathlib.Path(args[2]).parent / "growing.bin"
                    for _ in range({iterations}):
                        with open(growth_file, "ab") as f:
                            f.write(b"x" * {chunk_bytes})
                        time.sleep({sleep_seconds})
                pathlib.Path(args[2]).write_text("done")
            elif cmd == "createtsv":
                query_db, output = args[1], args[4]
                ids = pathlib.Path(query_db + ".fake_ids").read_text().splitlines()
                with open(output, "w") as fh:
                    for sample_id in ids:
                        fh.write(f"{{sample_id}}\\t{{sample_id}}\\n")
            sys.exit(0)
            """
        )
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _write_grandchild_spawning_mmseqs(directory: Path, *, activate_env_var: str = "RBPBENCH_TEST_GRANDCHILD") -> Path:
    """Only spawns the grandchild writer on ``cluster`` when
    ``activate_env_var`` is set, and otherwise behaves like a normal fast
    fake mmseqs (full createdb/cluster/createtsv support) -- see
    :func:`_write_growing_file_mmseqs` for why this same-binary pattern is
    needed under the FC1 binary-identity check.
    """
    path = directory / "grandchild_mmseqs"
    path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import os, sys, pathlib, subprocess, time
            args = sys.argv[1:]
            cmd = args[0]
            if cmd == "version":
                print({PINNED_VERSION!r})
            elif cmd == "createdb":
                input_fasta, db = args[1], args[2]
                ids = [line[1:].strip() for line in open(input_fasta) if line.startswith(">")]
                pathlib.Path(db).write_text("fakedb")
                pathlib.Path(db + ".dbtype").write_bytes(bytes([2, 0, 0, 0]))
                pathlib.Path(db + ".fake_ids").write_text("\\n".join(ids))
            elif cmd == "cluster":
                if os.environ.get({activate_env_var!r}):
                    marker = pathlib.Path(args[2]).parent / "grandchild_heartbeat.txt"
                    subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), "grandchild", str(marker)])
                    time.sleep(30)
                else:
                    pathlib.Path(args[2]).write_text("fakecluster")
            elif cmd == "grandchild":
                marker = pathlib.Path(args[1])
                for i in range(600):
                    with open(marker, "a") as f:
                        f.write(str(i) + "\\n")
                    time.sleep(0.05)
            elif cmd == "createtsv":
                query_db, output = args[1], args[4]
                ids = pathlib.Path(query_db + ".fake_ids").read_text().splitlines()
                with open(output, "w") as fh:
                    for sample_id in ids:
                        fh.write(f"{{sample_id}}\\t{{sample_id}}\\n")
            sys.exit(0)
            """
        )
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class R7LiveResourceGuardTests(_RamMockedTestCase):
    """Regression 7: live disk growth and a grandchild writer are stopped,
    with prior evidence untouched.
    """

    def test_live_disk_growth_is_terminated_before_natural_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            growing_bin = _write_growing_file_mmseqs(tmp_path, activate_env_var="RBPBENCH_TEST_GROW_R7A")
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(
                tmp_path, [_marker_sequence(1)],
                mmseqs_bin_path=growing_bin,
                max_new_disk_gib=0.00005,  # ~53 KB: well above tiny decode/probe overhead, well below one growth chunk
                resource_poll_interval_seconds=0.02,
                timeout_seconds=100,
            )
            # Env var unset here -- probe acceptance uses the same binary but
            # completes fast, with no disk growth.
            _accept_all_probes(config, output_dir, decode_record, fake_bin)

            start = time.monotonic()
            with mock.patch.dict(os.environ, {"RBPBENCH_TEST_GROW_R7A": "1"}):
                with self.assertRaises(runner.ResourceTerminatedError):
                    runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(growing_bin))
            elapsed = time.monotonic() - start
            # Natural completion would take 400 * 0.05s = 20s; a live guard
            # must catch it in well under a second.
            self.assertLess(elapsed, 5.0)
            self.assertFalse((output_dir / "cluster" / "500" / "generations").exists() and any((output_dir / "cluster" / "500" / "generations").iterdir()))
            # Prior probe/decode evidence is untouched.
            runner._require_accepted(output_dir, "decode")
            for width in config.protected_widths:
                runner._require_accepted(output_dir, f"probe_{width}")

    def test_grandchild_writer_is_terminated_with_the_whole_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            grandchild_bin = _write_grandchild_spawning_mmseqs(tmp_path, activate_env_var="RBPBENCH_TEST_GRANDCHILD_R7B")
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(
                tmp_path, [_marker_sequence(1)],
                mmseqs_bin_path=grandchild_bin,
                timeout_seconds=1.2,
                resource_poll_interval_seconds=0.02,
            )
            # Env var unset here -- probe acceptance uses the same binary but
            # completes fast, with no grandchild spawned.
            _accept_all_probes(config, output_dir, decode_record, fake_bin)

            # The candidate generation (including the heartbeat marker
            # inside it) is normally discarded on failure -- proven
            # separately by the R9 write-failure/discard regressions. Here
            # we only want to inspect whether the grandchild kept writing
            # AFTER termination, so keep the candidate directory around for
            # this one assertion instead of letting it be swept away first.
            with mock.patch("rbpbench.splits.runner.shutil.rmtree"):
                with mock.patch.dict(os.environ, {"RBPBENCH_TEST_GRANDCHILD_R7B": "1"}):
                    with self.assertRaises(runner.ResourceTerminatedError):
                        runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(grandchild_bin))

            marker_candidates = list(tmp_path.rglob("grandchild_heartbeat.txt"))
            self.assertEqual(len(marker_candidates), 1)
            marker = marker_candidates[0]
            count_at_kill = len(marker.read_text().splitlines())
            time.sleep(0.4)
            count_after_wait = len(marker.read_text().splitlines())
            self.assertEqual(count_at_kill, count_after_wait, "grandchild kept writing after the process group should have been killed")


class R8ThreadCapTests(_RamMockedTestCase):
    """Regression 8: all three MMseqs2 commands use no more than four
    threads.
    """

    def test_createdb_cluster_and_createtsv_all_receive_the_thread_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log_path = tmp_path / "argv_log.txt"
            logging_bin = tmp_path / "logging_mmseqs"
            logging_bin.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env python3
                    import sys, pathlib
                    LOG = pathlib.Path({str(log_path)!r})
                    args = sys.argv[1:]
                    cmd = args[0]
                    with open(LOG, "a") as f:
                        f.write(" ".join(args) + "\\n")
                    if cmd == "version":
                        print({PINNED_VERSION!r})
                    elif cmd == "createdb":
                        ids = []
                        for line in open(args[1]):
                            if line.startswith(">"):
                                ids.append(line[1:].strip())
                        db = args[2]
                        pathlib.Path(db).write_text("fakedb")
                        pathlib.Path(db + ".dbtype").write_bytes(bytes([2, 0, 0, 0]))
                        pathlib.Path(db + ".fake_ids").write_text("\\n".join(ids))
                    elif cmd == "cluster":
                        pathlib.Path(args[2]).write_text("fakecluster")
                    elif cmd == "createtsv":
                        query_db, output = args[1], args[4]
                        ids = pathlib.Path(query_db + ".fake_ids").read_text().splitlines()
                        with open(output, "w") as fh:
                            for sample_id in ids:
                                fh.write(f"{{sample_id}}\\t{{sample_id}}\\n")
                    sys.exit(0)
                    """
                )
            )
            logging_bin.chmod(logging_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=logging_bin)
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(logging_bin))
            decode_record = runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            _accept_all_probes(config, output_dir, decode_record, logging_bin)
            runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(logging_bin))

            lines = log_path.read_text().splitlines()
            seen = {"createdb": None, "cluster": None, "createtsv": None}
            for line in lines:
                parts = line.split()
                if parts and parts[0] in seen:
                    seen[parts[0]] = parts
            for tool, argv in seen.items():
                self.assertIsNotNone(argv, f"{tool} was never invoked")
                self.assertIn("--threads", argv, f"{tool} argv missing --threads: {argv}")
                self.assertEqual(argv[argv.index("--threads") + 1], "4", f"{tool} did not receive the configured thread cap: {argv}")


class R9SelectionRecordWriteFailureTests(_RamMockedTestCase):
    """Regression 9: selection-record write failures for decode,
    probe/cluster, and report remove the new candidate and preserve a prior
    acceptance.
    """

    def test_decode_write_failure_removes_the_new_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))
            accepted = runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            accepted_record_bytes = (output_dir / "selected" / "decode.json").read_bytes()

            before = _generation_dirs(output_dir, "decode")
            with mock.patch("rbpbench.splits.runner.os.replace", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(OSError):
                    runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            after = _generation_dirs(output_dir, "decode")

            self.assertEqual((output_dir / "selected" / "decode.json").read_bytes(), accepted_record_bytes)
            self.assertEqual(before, after, "the failed candidate generation must be removed")
            self.assertTrue(Path(accepted["generation_dir"]).is_dir())

    def test_cluster_write_failure_removes_the_new_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            accepted = runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
            accepted_bytes = (output_dir / "selected" / "cluster_500.json").read_bytes()

            before = _generation_dirs(output_dir, "cluster", "500")
            with mock.patch("rbpbench.splits.runner.os.replace", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(OSError):
                    runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
            after = _generation_dirs(output_dir, "cluster", "500")

            self.assertEqual((output_dir / "selected" / "cluster_500.json").read_bytes(), accepted_bytes)
            self.assertEqual(before, after)
            self.assertTrue(Path(accepted["generation_dir"]).is_dir())


class R10ComponentReportInterruptionTests(_RamMockedTestCase):
    """Regression 10: component-report interruption cannot overwrite
    accepted report artifacts.
    """

    def test_interrupted_second_attempt_cannot_overwrite_the_accepted_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1), _marker_sequence(2)])
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            cluster_records = {
                width: runner.stage_cluster(width=width, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
                for width in config.protected_widths
            }
            accepted = runner.stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)
            accepted_record_bytes = (output_dir / "selected" / "component_report.json").read_bytes()
            accepted_membership_bytes = Path(accepted["membership_path"]).read_bytes()

            with mock.patch("rbpbench.splits.runner.os.replace", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(OSError):
                    runner.stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)

            self.assertEqual((output_dir / "selected" / "component_report.json").read_bytes(), accepted_record_bytes)
            self.assertEqual(Path(accepted["membership_path"]).read_bytes(), accepted_membership_bytes)


class R11GenerationTamperingInvalidatesRevalidationTests(_RamMockedTestCase):
    """Regression 11: added, deleted, or changed generation files invalidate
    revalidation.
    """

    def test_added_file_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            (Path(decode_record["generation_dir"]) / "extra_stray_file.txt").write_text("not part of the accepted inventory")
            self.assertIsNone(runner._load_accepted(output_dir, "decode"))

    def test_deleted_file_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            Path(decode_record["fasta_paths"]["101"]).unlink()
            self.assertIsNone(runner._load_accepted(output_dir, "decode"))

    def test_modified_file_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            fasta_path = Path(decode_record["fasta_paths"]["500"])
            fasta_path.write_text(fasta_path.read_text() + "\n>row_injected\nACGT\n")
            self.assertIsNone(runner._load_accepted(output_dir, "decode"))


class R12RepoRootIndependentOfCwdTests(_RamMockedTestCase):
    """Regression 12: running from outside the repository resolves the
    declared frozen inputs deterministically.
    """

    def test_relative_config_paths_resolve_against_repo_root_not_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project_dir = tmp_path / "project"
            project_dir.mkdir()
            fake_bin = _write_fake_mmseqs(project_dir)
            # Relative filenames only -- these must resolve against
            # --repo-root, never the process's current working directory.
            csv_path, config_path = _build_fixture(
                project_dir, [_marker_sequence(1)], mmseqs_bin_path=fake_bin,
                csv_filename="dataset.csv", audit_filename="audit.json", proteins_filename="proteins.tsv",
            )
            output_dir = tmp_path / "out"
            elsewhere = tmp_path / "elsewhere"
            elsewhere.mkdir()

            original_cwd = Path.cwd()
            os.chdir(elsewhere)
            try:
                runner.main(
                    [
                        "--stage", "preflight",
                        "--config", str(config_path),
                        "--repo-root", str(project_dir),
                        "--output-dir", str(output_dir),
                        "--mmseqs-bin", str(fake_bin),
                    ]
                )
            finally:
                os.chdir(original_cwd)

            record = json.loads((output_dir / "selected" / "preflight.json").read_text())
            self.assertTrue(record["executed"])


class FC1CurrentPrerequisiteChainTests(_RamMockedTestCase):
    """Task 002B-1 final bounded correction
    (docs/handoffs/002b1_orchestration_final_correction_claude_handoff.md,
    docs/reviews/002b1_orchestration_correction_review.md), FC1: a current
    preflight/decode chain is required before every downstream action, not
    merely an intact selected record.
    """

    def test_audit_json_mutation_after_accepted_preflight_blocks_decode_before_any_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))

            Path(config.dataset.audit_json_path).write_text('{"mutated": true}')

            before = _generation_dirs(output_dir, "decode")
            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            after = _generation_dirs(output_dir, "decode")
            self.assertEqual(before, after, "decode must not create a generation before the stale-preflight check")

    def test_proteins_tsv_mutation_after_accepted_preflight_blocks_decode_before_any_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))

            Path(config.dataset.proteins_tsv_path).write_text("mutated\n")

            before = _generation_dirs(output_dir, "decode")
            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            after = _generation_dirs(output_dir, "decode")
            self.assertEqual(before, after, "decode must not create a generation before the stale-preflight check")

    def test_tampered_binary_bytes_after_accepted_preflight_blocks_probe_before_any_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])

            # Same path, same reported version, different bytes -- exactly
            # the F1 second reproduction (docs/reviews/
            # 002b1_orchestration_correction_review.md).
            fake_bin.write_text(fake_bin.read_text() + "\n# tampered after acceptance\n")
            fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            self.assertEqual(runner.splits_commands.resolve_mmseqs_binary_provenance(str(fake_bin)).version, PINNED_VERSION)

            with mock.patch("rbpbench.splits.runner.run_guarded_mmseqs") as mocked:
                with self.assertRaises(runner.PreflightError) as ctx:
                    runner.stage_probe(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
                mocked.assert_not_called()
            self.assertIn("SHA-256", str(ctx.exception))

    def test_stale_preflight_cannot_be_used_to_skip_an_accepted_decode_via_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            output_dir = tmp_path / "out"
            common_args = [
                "--config", str(config_path), "--output-dir", str(output_dir),
                "--dataset-csv", str(csv_path), "--mmseqs-bin", str(fake_bin),
            ]
            runner.main(["--stage", "preflight", *common_args])
            runner.main(["--stage", "decode", *common_args])

            config = load_config(config_path)
            Path(config.dataset.proteins_tsv_path).write_text("mutated\n")

            before = _generation_dirs(output_dir, "decode")
            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner.main(["--stage", "decode", *common_args])
            after = _generation_dirs(output_dir, "decode")
            self.assertEqual(before, after, "a stale preflight must not be used to skip decode")


class FC2FinalResourceSnapshotTests(_RamMockedTestCase):
    """FC2: every MMseqs2 child gets one unconditional final ceiling/floor
    re-measurement right after it exits, even one that completes before the
    first polling interval.
    """

    def test_fast_process_with_a_low_final_free_disk_reading_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # A generous poll interval so this instant fake mmseqs reliably
            # exits before the first poll -- exactly the "completes before
            # the first polling interval" scenario this final check must
            # still catch.
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(
                tmp_path, [_marker_sequence(1)], resource_poll_interval_seconds=5.0
            )
            _accept_all_probes(config, output_dir, decode_record, fake_bin)

            real_snapshot = runner.snapshot
            calls = {"n": 0}

            def fake_snapshot(path):
                calls["n"] += 1
                if calls["n"] == 1:
                    # The pre-launch free-disk check sees the real, plentiful
                    # reading -- only the post-exit final check is faked low.
                    return real_snapshot(path)
                from rbpbench.coordinates.diskbudget import DiskSnapshot

                return DiskSnapshot(path=str(path), free_gib=0.0, total_gib=100.0, used_gib=100.0)

            before = _generation_dirs(output_dir, "cluster", "500")
            with mock.patch("rbpbench.splits.runner.snapshot", side_effect=fake_snapshot):
                with self.assertRaises(runner.ResourceGateExceededError):
                    runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
            after = _generation_dirs(output_dir, "cluster", "500")
            self.assertEqual(before, after, "the candidate generation must be discarded, not promoted")

            # Prior accepted evidence is untouched.
            runner._require_accepted(output_dir, "decode")
            for width in config.protected_widths:
                runner._require_accepted(output_dir, f"probe_{width}")


class FC3InstalledRamFailClosedTests(unittest.TestCase):
    """FC3: dedicated, host-DEPENDENT tests exercising the RAM detection
    fail-closed path itself (deliberately not inheriting
    ``_RamMockedTestCase``, unlike every synthetic fixture above).
    """

    def test_none_installed_ram_is_a_hard_failure_at_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            with mock.patch("rbpbench.splits.runner.detect_physical_ram_gib", return_value=None):
                with self.assertRaises(runner.PreflightError) as ctx:
                    _preflight(config, csv_path, tmp_path / "out", mmseqs_bin=str(fake_bin))
            self.assertIn("installed RAM", str(ctx.exception))

    def test_low_installed_ram_below_configured_minimum_is_a_hard_failure_at_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(
                tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin, min_installed_ram_gib=1000.0
            )
            config = load_config(config_path)
            with mock.patch("rbpbench.splits.runner.detect_physical_ram_gib", return_value=1.0):
                with self.assertRaises(runner.PreflightError) as ctx:
                    _preflight(config, csv_path, tmp_path / "out", mmseqs_bin=str(fake_bin))
            self.assertIn("installed RAM", str(ctx.exception))

    def test_preflight_cli_skip_path_still_rechecks_ram_now(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            output_dir = tmp_path / "out"
            common_args = [
                "--config", str(config_path), "--output-dir", str(output_dir),
                "--dataset-csv", str(csv_path), "--mmseqs-bin", str(fake_bin),
            ]
            with mock.patch("rbpbench.splits.runner.detect_physical_ram_gib", return_value=64.0):
                runner.main(["--stage", "preflight", *common_args])

            # Same fingerprint as before -- would normally SKIP straight to
            # the prior accepted record. RAM is now undetectable.
            with mock.patch("rbpbench.splits.runner.detect_physical_ram_gib", return_value=None):
                with self.assertRaises(runner.PreflightError):
                    runner.main(["--stage", "preflight", *common_args])

    def test_current_decode_helper_rechecks_ram_now(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch("rbpbench.splits.runner.detect_physical_ram_gib", return_value=64.0):
                config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            with mock.patch("rbpbench.splits.runner.detect_physical_ram_gib", return_value=None):
                with self.assertRaises(runner.PreflightError):
                    runner._require_current_decode(output_dir=output_dir, config=config)


class FC4ComponentReportArtifactManifestTests(_RamMockedTestCase):
    """FC4: the accepted component-report record binds immutable artifact
    inventories (not only fingerprints/digests) for decode and all three
    cluster generations.
    """

    def test_component_report_binds_decode_and_all_three_cluster_artifact_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(
                tmp_path, [_marker_sequence(1), _marker_sequence(2)]
            )
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            cluster_records = {
                width: runner.stage_cluster(width=width, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
                for width in config.protected_widths
            }
            record = runner.stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)

            manifests = record["upstream_artifact_manifests"]
            self.assertEqual(manifests["decode"], decode_record["artifacts"])
            self.assertGreater(len(manifests["decode"]), 0)
            for width in config.protected_widths:
                key = f"cluster_{width}"
                self.assertEqual(manifests[key], cluster_records[width]["artifacts"])
                self.assertGreater(len(manifests[key]), 0)
                for entry in manifests[key]:
                    self.assertIn("path", entry)
                    self.assertIn("size", entry)
                    self.assertIn("sha256", entry)

            on_disk = json.loads((output_dir / "selected" / "component_report.json").read_text())
            self.assertEqual(on_disk["upstream_artifact_manifests"], manifests)


if __name__ == "__main__":
    unittest.main()
