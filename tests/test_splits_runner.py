"""Checkpoint 002B-1 orchestration tests
(docs/handoffs/002b1_orchestration_claude_handoff.md,
docs/handoffs/002b1_orchestration_corrections_claude_handoff.md).

Every test here uses only tiny synthetic CSV/FASTA data built in-process; the
real dataset, real Task 002 artifacts, and the real MMseqs2 binary's
scientific behavior (already proven in tests/test_splits_real_binaries.py and
tests/test_splits_split_memory_gate.py) are never touched. Most tests use a
small fake ``mmseqs`` script (below) so the ordinary suite never depends on
the isolated ``rbpbench-splits-002`` environment for orchestration coverage;
scientific clustering correctness is a 002A concern, not this checkpoint's.

C1-C5 regressions specifically required by the correction handoff live in
``tests/test_splits_b1_corrections.py``.
"""

from __future__ import annotations

import csv
import json
import random
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.decode import encode_sequence
from rbpbench.coordinates.hashing import label_blind_rank
from rbpbench.data.audit import sha256_file
from rbpbench.splits import runner
from rbpbench.splits.commands import MmseqsExecutionError, PINNED_VERSION
from rbpbench.splits.config import load_config
from rbpbench.splits.membership import MembershipReconciliationError
from rbpbench.splits.output import read_component_membership_gzip


def _marker_sequence(seed: int, width: int = 500) -> str:
    rng = random.Random(seed)
    return "".join(rng.choice("ACGT") for _ in range(width))


def _write_fake_mmseqs(directory: Path, *, version: str = PINNED_VERSION, name: str = "fake_mmseqs") -> Path:
    """A tiny Python stand-in for ``mmseqs`` sufficient for orchestration
    tests: ``version`` prints a fixed string, ``createdb`` records the input
    FASTA's IDs in a sidecar file, ``cluster`` is a no-op, and ``createtsv``
    reports every ID as its own singleton cluster (real cluster/coverage
    semantics are a 002A concern, already proven against the real binary).
    """
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
                pathlib.Path(db + ".index").write_text("index")
                pathlib.Path(db + ".fake_ids").write_text("\\n".join(ids))
            elif cmd == "cluster":
                cluster_prefix = args[2]
                pathlib.Path(cluster_prefix).write_text("fakecluster")
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
    sample_size: int = 4,
    max_new_disk_gib: float = 1000.0,
    min_free_disk_gib: float = 0.0000001,
    timeout_seconds: int = 60,
    max_peak_memory_gib: float = 1000.0,
    min_available_memory_gib: float = 0.0000001,
    min_available_memory_gib_before_launch: float = 0.0000001,
    min_installed_ram_gib: float = 0.0,
    resource_poll_interval_seconds: float = 0.02,
) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    csv_path = tmp_path / "dataset.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sequence", "labels"])
        for seq in sequences:
            writer.writerow([encode_sequence(seq), ""])

    audit_path = tmp_path / "audit.json"
    audit_path.write_text("{}")
    proteins_path = tmp_path / "proteins.tsv"
    proteins_path.write_text("dummy\n")

    config_text = textwrap.dedent(
        f"""
        seed = 20260925
        protected_widths = [500, 251, 101]

        [dataset]
        csv_filename = "{csv_path}"
        csv_sha256 = "{sha256_file(csv_path)}"
        csv_byte_size = {csv_path.stat().st_size}
        expected_row_count = {len(sequences)}
        audit_json_path = "{audit_path}"
        audit_json_sha256 = "{sha256_file(audit_path)}"
        proteins_tsv_path = "{proteins_path}"
        proteins_tsv_sha256 = "{sha256_file(proteins_path)}"

        [binary]
        mmseqs_sha256 = "{sha256_file(mmseqs_bin_path)}"

        [resources]
        max_threads = 2
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


def _preflight(config, dataset_csv, output_dir, *, mmseqs_bin="mmseqs", dry_run=False,
               audit_json: Path | None = None, proteins_tsv: Path | None = None):
    return runner.stage_preflight(
        config=config,
        dataset_csv=dataset_csv,
        audit_json=audit_json if audit_json is not None else Path(config.dataset.audit_json_path),
        proteins_tsv=proteins_tsv if proteins_tsv is not None else Path(config.dataset.proteins_tsv_path),
        output_dir=output_dir,
        mmseqs_bin=mmseqs_bin,
        dry_run=dry_run,
    )


def _preflight_and_decode(tmp_path: Path, sequences: list[str], **fixture_kwargs):
    """Common setup: a fake mmseqs binary, a matching config, a real accepted
    preflight, and a real accepted decode. Returns
    (config, output_dir, decode_record, fake_bin_path).
    """
    fake_bin = _write_fake_mmseqs(tmp_path)
    csv_path, config_path = _build_fixture(tmp_path, sequences, mmseqs_bin_path=fake_bin, **fixture_kwargs)
    config = load_config(config_path)
    output_dir = tmp_path / "out"
    preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))
    decode_record = runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
    return config, output_dir, decode_record, fake_bin


def _accept_all_probes(config, output_dir, decode_record, mmseqs_bin):
    for width in config.protected_widths:
        runner.stage_probe(width=width, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(mmseqs_bin))


class CliValidationTests(unittest.TestCase):
    def test_unknown_width_rejected(self):
        with self.assertRaises(SystemExit):
            runner.main(["--stage", "cluster", "--width", "999", "--authorize-mmseqs"])

    def test_missing_stage_rejected(self):
        with self.assertRaises(SystemExit):
            runner.main([])

    def test_all_stage_rejected(self):
        with self.assertRaises(SystemExit):
            runner.main(["--stage", "all"])

    def test_repeated_stage_flag_rejected(self):
        with self.assertRaises(SystemExit):
            runner.main(["--stage", "decode", "--stage", "probe"])

    def test_repeated_width_flag_rejected(self):
        with self.assertRaises(SystemExit):
            runner.main(["--stage", "cluster", "--width", "500", "--width", "251", "--authorize-mmseqs"])

    def test_width_rejected_for_non_width_scoped_stage(self):
        with self.assertRaises(runner.StageValidationError):
            runner.main(["--stage", "decode", "--width", "500"])

    def test_width_required_for_width_scoped_stage(self):
        with self.assertRaises(runner.StageValidationError):
            runner.main(["--stage", "probe", "--authorize-mmseqs"])

    def test_authorization_missing_for_probe_rejected_before_any_file_access(self):
        with self.assertRaises(runner.AuthorizationError):
            runner.main(["--stage", "probe", "--width", "500", "--config", "/definitely/not/a/real/config.toml"])

    def test_authorization_missing_for_cluster_rejected(self):
        with self.assertRaises(runner.AuthorizationError):
            runner.main(["--stage", "cluster", "--width", "500"])

    def test_authorization_not_required_for_preflight(self):
        # Should get past the authorization gate (fails later for an
        # unrelated reason: a nonexistent config file).
        with self.assertRaises(FileNotFoundError):
            runner.main(["--stage", "preflight", "--config", "/definitely/not/a/real/config.toml"])

    def test_no_scientific_override_flags_are_exposed(self):
        parser = runner.build_parser()
        option_strings = set(parser._option_string_actions.keys())
        for forbidden in ("--min-seq-id", "--coverage", "-c", "--cov-mode", "--max-seqs", "--split-memory-limit"):
            self.assertNotIn(forbidden, option_strings)


class DryRunTests(unittest.TestCase):
    def test_dry_run_preflight_never_reads_declared_real_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            _, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            result = runner.stage_preflight(
                config=config,
                dataset_csv=tmp_path / "does-not-exist.csv",
                audit_json=tmp_path / "does-not-exist-audit.json",
                proteins_tsv=tmp_path / "does-not-exist-proteins.tsv",
                output_dir=tmp_path / "out",
                dry_run=True,
            )
            self.assertTrue(result["dry_run"])

    def test_dry_run_cluster_never_invokes_a_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            _, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            with mock.patch("rbpbench.splits.runner.run_guarded_mmseqs") as mocked:
                mocked.side_effect = AssertionError("must not be called in dry-run")
                runner.main(
                    [
                        "--stage", "cluster", "--width", "500", "--dry-run",
                        "--output-dir", str(tmp_path / "out"), "--config", str(config_path),
                        "--dataset-csv", str(tmp_path / "does-not-exist.csv"),
                    ]
                )
                mocked.assert_not_called()

    def test_dry_run_probe_does_not_require_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            _, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            with mock.patch("rbpbench.splits.runner.run_guarded_mmseqs") as mocked:
                runner.main(
                    [
                        "--stage", "probe", "--width", "500", "--dry-run",
                        "--output-dir", str(tmp_path / "out"), "--config", str(config_path),
                        "--dataset-csv", str(tmp_path / "does-not-exist.csv"),
                    ]
                )
                mocked.assert_not_called()


class StageOrderingTests(unittest.TestCase):
    """No stage can advance automatically into a later checkpoint."""

    def test_decode_requires_accepted_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner._require_accepted(output_dir, "preflight")

    def test_probe_requires_accepted_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner._require_accepted(output_dir, "decode")

    def test_component_report_requires_all_widths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            _, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner.main(
                    ["--stage", "component_report", "--output-dir", str(tmp_path / "out"), "--config", str(config_path)]
                )


class PreflightStageTests(unittest.TestCase):
    def test_accepts_matching_hashes_and_writes_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1), _marker_sequence(2)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))
            self.assertTrue(record["executed"])
            self.assertIn("stage_fingerprint", record)
            self.assertTrue((output_dir / "selected" / "preflight.json").is_file())

    def test_rejects_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            csv_path.write_text(csv_path.read_text() + "\n")  # corrupt after hash was recorded
            with self.assertRaises(runner.PreflightError):
                _preflight(config, csv_path, tmp_path / "out", mmseqs_bin=str(fake_bin))

    def test_rejects_missing_dataset_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            _, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            with self.assertRaises(runner.PreflightError):
                _preflight(config, tmp_path / "missing.csv", tmp_path / "out", mmseqs_bin=str(fake_bin))

    def test_rejects_missing_mmseqs_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            with self.assertRaises(runner.PreflightError):
                _preflight(config, csv_path, tmp_path / "out", mmseqs_bin="definitely-not-a-real-binary-xyz")

    def test_rejects_wrong_pinned_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            wrong_version_bin = _write_fake_mmseqs(tmp_path, version="99.0.0", name="wrong_version_mmseqs")
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            with self.assertRaises(runner.PreflightError):
                _preflight(config, csv_path, tmp_path / "out", mmseqs_bin=str(wrong_version_bin))

    def test_rejects_low_free_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin, min_free_disk_gib=1e9)
            config = load_config(config_path)
            with self.assertRaises(runner.ResourceGateExceededError):
                _preflight(config, csv_path, tmp_path / "out", mmseqs_bin=str(fake_bin))


class DecodeStageTests(unittest.TestCase):
    def test_produces_three_fastas_and_duplicate_edges_in_an_immutable_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seqs = [_marker_sequence(1), _marker_sequence(1), _marker_sequence(2)]  # rows 0,1 exact duplicates
            config, output_dir, decode_record, _fake_bin = _preflight_and_decode(tmp_path, seqs)

            self.assertEqual(decode_record["total_rows"], 3)
            self.assertEqual(set(decode_record["sample_ids"]), {"row_0", "row_1", "row_2"})
            for width in (500, 251, 101):
                self.assertTrue(Path(decode_record["fasta_paths"][str(width)]).is_file())
                summary = decode_record["duplicate_edge_summary"][str(width)]
                self.assertEqual(summary["duplicate_group_count"], 1)
                self.assertEqual(summary["max_duplicate_group_size"], 2)
            self.assertIn("generations", decode_record["generation_dir"])
            self.assertIsInstance(decode_record["artifacts"], list)
            self.assertGreater(len(decode_record["artifacts"]), 0)

    def test_row_count_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))
            # Add an extra row -- same accepted CSV hash check still passes
            # here because we mutate AFTER preflight accepted the original
            # bytes, so decode's own row-count reconciliation is what fires.
            accepted_bytes = csv_path.read_bytes()
            with csv_path.open("a", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([encode_sequence(_marker_sequence(2)), ""])
            # Since the CSV changed, decode's stale-acceptance guard fires
            # first; assert on that explicitly, then restore accepted bytes
            # and prove the underlying row-count guard separately.
            with self.assertRaises(runner.StaleAcceptanceError):
                runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            csv_path.write_bytes(accepted_bytes)

            # Now simulate a config that expects a row count the CSV doesn't
            # have, without touching the CSV after preflight accepted it.
            csv_path2, config_path2 = _build_fixture(tmp_path / "v2", [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config2_text = config_path2.read_text().replace("expected_row_count = 1", "expected_row_count = 5")
            config_path2.write_text(config2_text)
            config2 = load_config(config_path2)
            preflight_record2 = _preflight(config2, csv_path2, output_dir, mmseqs_bin=str(fake_bin))
            with self.assertRaises(runner.PreflightError):
                runner.stage_decode(config=config2, dataset_csv=csv_path2, output_dir=output_dir, preflight_record=preflight_record2)

    def test_a_second_decode_gets_its_own_generation_never_overwriting_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            preflight_record = _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))
            first = runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            second = runner.stage_decode(config=config, dataset_csv=csv_path, output_dir=output_dir, preflight_record=preflight_record)
            self.assertNotEqual(first["generation_dir"], second["generation_dir"])
            self.assertTrue(Path(first["fasta_paths"]["500"]).is_file())
            self.assertTrue(Path(second["fasta_paths"]["500"]).is_file())


class ClusterStageTests(unittest.TestCase):
    def test_cluster_requires_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            with self.assertRaises(runner.AuthorizationError):
                runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=False)

    def test_cluster_refuses_before_all_three_probes_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            with self.assertRaises(runner.PriorStageNotAcceptedError):
                runner.stage_cluster(width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin))
            self.assertFalse((output_dir / "cluster").exists())

    def test_cluster_writes_accepted_record_and_reconciles_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1), _marker_sequence(2)])
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            record = runner.stage_cluster(
                width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin)
            )
            self.assertTrue(record["executed"])
            self.assertEqual(record["sample_count"], 2)
            self.assertTrue((output_dir / "selected" / "cluster_500.json").is_file())
            stdout_paths = {entry["stdout_path"] for entry in record["tool_provenance"]}
            self.assertEqual(len(stdout_paths), 3)
            self.assertIsNone(record["split_memory_limit"])
            self.assertIsInstance(record["artifacts"], list)

    def test_cluster_rejects_a_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            broken_bin = tmp_path / "broken_mmseqs"
            broken_bin.write_text("#!/bin/sh\necho boom 1>&2\nexit 1\n")
            broken_bin.chmod(broken_bin.stat().st_mode | stat.S_IEXEC)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            with self.assertRaises(Exception):
                runner.stage_cluster(
                    width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(broken_bin)
                )
            self.assertFalse((output_dir / "selected" / "cluster_500.json").is_file())

    def test_cluster_rejects_a_timeout_and_kills_the_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hang_bin = tmp_path / "hang_mmseqs"
            hang_bin.write_text("#!/bin/sh\nif [ \"$1\" = \"createdb\" ]; then sleep 30; fi\nexit 0\n")
            hang_bin.chmod(hang_bin.stat().st_mode | stat.S_IEXEC)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)], timeout_seconds=1)
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            with self.assertRaises((MmseqsExecutionError, runner.ResourceTerminatedError)):
                runner.stage_cluster(
                    width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(hang_bin)
                )

    def test_membership_reconciliation_rejects_a_foreign_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_bin = tmp_path / "bad_mmseqs"
            bad_bin.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import sys, pathlib
                    args = sys.argv[1:]
                    cmd = args[0]
                    if cmd == "version":
                        print("18.8cc5c")
                    elif cmd == "createdb":
                        db = args[2]
                        pathlib.Path(db).write_text("fakedb")
                        pathlib.Path(db + ".dbtype").write_bytes(bytes([2, 0, 0, 0]))
                    elif cmd == "cluster":
                        pathlib.Path(args[2]).write_text("fakecluster")
                    elif cmd == "createtsv":
                        output = args[4]
                        with open(output, "w") as fh:
                            fh.write("row_0\\tforeign_id_not_in_input\\n")
                    sys.exit(0)
                    """
                )
            )
            bad_bin.chmod(bad_bin.stat().st_mode | stat.S_IEXEC)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)])
            _accept_all_probes(config, output_dir, decode_record, fake_bin)
            with self.assertRaises(MembershipReconciliationError):
                runner.stage_cluster(
                    width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(bad_bin)
                )


class ProbeStageTests(unittest.TestCase):
    def test_probe_selects_only_the_configured_sample_size_label_blind(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seqs = [_marker_sequence(i) for i in range(10)]
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, seqs, sample_size=3)
            record = runner.stage_probe(
                width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin)
            )
            self.assertEqual(record["sample_count"], 3)

    def test_probe_is_deterministic_across_repeated_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seqs = [_marker_sequence(i) for i in range(10)]
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, seqs, sample_size=3)
            first = runner.stage_probe(
                width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin)
            )
            all_ids = decode_record["sample_ids"]
            ranked = sorted(all_ids, key=lambda sid: (label_blind_rank(config.seed, sid), sid))
            expected_subset = set(ranked[:3])
            with open(first["membership_tsv"]) as handle:
                actual_subset = {line.split("\t")[0] for line in handle if line.strip()}
            self.assertEqual(actual_subset, expected_subset)

    def test_probe_peak_memory_gate_rejects_and_discards_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, [_marker_sequence(1)], max_peak_memory_gib=0.0)
            with self.assertRaises(runner.ResourceGateExceededError):
                runner.stage_probe(
                    width=500, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin)
                )
            self.assertFalse((output_dir / "selected" / "probe_500.json").is_file())


class RestartFingerprintTests(unittest.TestCase):
    def test_repeated_preflight_invocation_skips_recomputation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            output_dir = tmp_path / "out"
            argv = ["--stage", "preflight", "--config", str(config_path), "--dataset-csv", str(csv_path), "--output-dir", str(output_dir), "--mmseqs-bin", str(fake_bin)]
            runner.main(argv)
            with mock.patch("rbpbench.splits.runner.stage_preflight", wraps=runner.stage_preflight) as wrapped:
                runner.main(argv)
                wrapped.assert_not_called()

    def test_record_write_failure_preserves_the_prior_accepted_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = _write_fake_mmseqs(tmp_path)
            csv_path, config_path = _build_fixture(tmp_path, [_marker_sequence(1)], mmseqs_bin_path=fake_bin)
            config = load_config(config_path)
            output_dir = tmp_path / "out"
            _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))
            record_path = output_dir / "selected" / "preflight.json"
            before_bytes = record_path.read_bytes()

            with mock.patch("rbpbench.splits.runner.os.replace", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(OSError):
                    _preflight(config, csv_path, output_dir, mmseqs_bin=str(fake_bin))

            self.assertEqual(record_path.read_bytes(), before_bytes)


class ComponentReportStageTests(unittest.TestCase):
    def _full_pipeline(self, tmp_path: Path, seqs: list[str], **fixture_kwargs):
        config, output_dir, decode_record, fake_bin = _preflight_and_decode(tmp_path, seqs, **fixture_kwargs)
        _accept_all_probes(config, output_dir, decode_record, fake_bin)
        cluster_records = {
            width: runner.stage_cluster(
                width=width, config=config, output_dir=output_dir, decode_record=decode_record, authorize=True, mmseqs_bin=str(fake_bin)
            )
            for width in config.protected_widths
        }
        return config, output_dir, decode_record, cluster_records

    def test_exact_duplicates_alone_form_a_component_even_with_singleton_fake_clustering(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seqs = [_marker_sequence(1), _marker_sequence(1), _marker_sequence(2), _marker_sequence(3)]
            config, output_dir, decode_record, cluster_records = self._full_pipeline(tmp_path, seqs)
            record = runner.stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)

            rows = dict(read_component_membership_gzip(Path(record["membership_path"])))
            self.assertEqual(rows["row_0"], rows["row_1"])
            self.assertNotEqual(rows["row_0"], rows["row_2"])
            self.assertEqual(record["component_count"], 3)
            self.assertIn("generations", record["generation_dir"])

    def test_giant_component_gate_trips_when_duplicates_dominate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dominant = _marker_sequence(1)
            seqs = [dominant] * 8 + [_marker_sequence(i) for i in range(2, 6)]
            config, output_dir, decode_record, cluster_records = self._full_pipeline(tmp_path, seqs)
            record = runner.stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)
            self.assertTrue(record["giant_component_gate"]["single_component_gate_tripped"])

    def test_membership_gzip_is_reproducible_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seqs = [_marker_sequence(i) for i in range(5)]
            config, output_dir, decode_record, cluster_records = self._full_pipeline(tmp_path, seqs)
            first = runner.stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)
            first_bytes = Path(first["membership_path"]).read_bytes()
            second = runner.stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)
            second_bytes = Path(second["membership_path"]).read_bytes()
            self.assertEqual(first_bytes, second_bytes)
            self.assertNotEqual(first["generation_dir"], second["generation_dir"])

    def test_report_never_contains_a_sequence_or_label_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seqs = [_marker_sequence(i) for i in range(4)]
            config, output_dir, decode_record, cluster_records = self._full_pipeline(tmp_path, seqs)
            record = runner.stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)
            manifest_text = Path(record["manifest_path"]).read_text()
            for seq in seqs:
                self.assertNotIn(seq, manifest_text)


if __name__ == "__main__":
    unittest.main()
