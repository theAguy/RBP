from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

try:
    import numpy as np
    import torch
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("Task 004A-3 tests require NumPy and PyTorch") from exc

from rbpbench.rescnn.adam_004a3 import ADAM_FLAGS, build_gpu_adam, run_three_step_oracle
from rbpbench.rescnn import cache_004a3, projection_004a3, runtime_004a3
from rbpbench.rescnn.cache_004a3 import (
    CacheRow, open_cache, select_development_rows, write_cache,
)
from rbpbench.rescnn.data_004a2 import SampleCandidate
from rbpbench.rescnn.checkpoint import (
    atomic_save_resource_smoke_checkpoint, load_resource_smoke_model_checkpoint,
    ResCNNCheckpointError,
)
from rbpbench.rescnn.config import load_config
from rbpbench.rescnn.environment_004a3 import sha256_file, verify_runtime, ResCNN004A3EnvironmentError
from rbpbench.rescnn.portable_004a3 import (
    ResCNN004A3PortableError, build_inventory, compare_process_records,
    package_sanitized_return, verify_bundle,
)
from rbpbench.rescnn.projection_004a3 import (
    PROJECT_004A4_SLURM_LIMIT_SECONDS,
    StorageInputs, TimeInputs, project_storage_bytes, project_wall_seconds,
    require_projection_limits, ResCNN004A3ProjectionError,
)
from rbpbench.rescnn import runner_004a3
from rbpbench.rescnn.runner_004a3 import THREAD_ENV, require_pre_python_environment
from rbpbench.rescnn.runtime_004a3 import (
    LiveResourceMonitor,
    ResourceUse, RuntimeIdentity, require_discovery_install_policy,
    require_identity_match, require_memory_headroom, ResCNN004A3RuntimeError,
)
from rbpbench.rescnn.timing_004a3 import measure_batches, worst_case_metric_arrays


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/models/task004a_v1.toml"


def _command_evidence(*, available=True, returncode=0, stdout="ok\n", stderr=""):
    return {
        "available": available, "returncode": returncode,
        "stdout": stdout, "stderr": stderr,
    }


def _complete_discovery_payload():
    payload = {
        "schema_version": "task004a3_discovery_v2",
        "host": "synthetic", "system": "Linux", "machine": "x86_64",
        "allocated_cpus": 4, "slurm_job_id": "1", "slurm_partition": "gpu",
        "requested_slurm_partition": "gpu", "slurm_account": "synthetic",
        "requested_slurm_account": None,
        "installed_ram_bytes": 128 * 2**30,
        "available_ram_bytes": 120 * 2**30,
        "free_disk_bytes": 10**12, "quota_available_bytes": 10**12,
        "operator_quota_available_bytes": 10**12,
        "slurm_limit_seconds": 172800,
        "slurm_limit_error": None,
        "compute_node_required_channels_reachable": False,
        "site_approved_install_location": "login_node",
        "gpu_csv": "NVIDIA A100, GPU-1, 81920 MiB, 8.0, 550",
        "nvidia_smi": "synthetic nvidia-smi evidence",
        "requires_owner_review_before_lock": True,
    }
    payload.update({
        key: _command_evidence() for key in runtime_004a3.DISCOVERY_COMMAND_FIELDS
    })
    payload["slurm_partition_detail"] = _command_evidence(
        stdout="PartitionName=gpu MaxTime=2-00:00:00 PreemptMode=OFF\n",
    )
    return payload


def _cache_rows(size=3):
    for partition_index, partition in enumerate(("train", "validation")):
        for index in range(size):
            targets = tuple((index + protein) % 2 for protein in range(4))
            masks = (1, 1, 1, 1)
            yield CacheRow(
                sample_id=f"row_{partition_index * size + index}",
                component_id=f"component-{partition_index}-{index}", partition=partition,
                base_codes=tuple((index + base) % 4 for base in range(5)),
                targets=targets, masks=masks,
            )


class CacheTests(unittest.TestCase):
    def test_mmap_cache_round_trip_and_test_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cache"
            metadata = write_cache(
                root, _cache_rows(), expected_partition_size=3, width=5, output_count=4,
            )
            cache = open_cache(root)
            self.assertIsInstance(cache.base_codes, np.memmap)
            self.assertEqual(cache.base_codes.shape, (6, 5))
            self.assertEqual(cache.targets.dtype, np.uint8)
            self.assertEqual(len(cache.indices("train")), 3)
            self.assertEqual(metadata["validation_known_counts"], [3, 3, 3, 3])
            self.assertFalse(cache.metadata["test_accessed"])

    def test_cache_failure_is_transactional(self):
        bad = list(_cache_rows())
        bad[-1] = CacheRow("row_0", "dup", "validation", (0,) * 5, (0,) * 4, (1,) * 4)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cache"
            with self.assertRaisesRegex(ValueError, "unique"):
                write_cache(root, bad, expected_partition_size=3, width=5, output_count=4)
            self.assertFalse(root.exists())

    def test_cache_inventory_detects_identity_file_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cache"
            write_cache(root, _cache_rows(), expected_partition_size=3, width=5, output_count=4)
            with (root / "identities.tsv").open("a") as handle:
                handle.write("tamper\n")
            with self.assertRaisesRegex(ValueError, "inventory drift"):
                open_cache(root)

    def test_accepted_sampler_is_deterministic_with_label_blind_filler(self):
        rows = []
        for partition_index, partition in enumerate(("train", "validation")):
            for index in range(20):
                sample_id = f"row_{partition_index * 100 + index}"
                rows.append((SampleCandidate(sample_id, f"c-{sample_id}", partition, "a" * 64), {
                    1: index % 2, 2: (index // 2) % 2,
                }))
        forward = select_development_rows(rows, seed=5, sample_size=7, output_count=2)
        reverse = select_development_rows(reversed(rows), seed=5, sample_size=7, output_count=2)
        self.assertEqual(forward, reverse)
        self.assertEqual({k: len(v) for k, v in forward.items()}, {"train": 7, "validation": 7})

    def test_reviewed_streaming_builder_reconciles_and_never_interprets_test_fields(self):
        membership = ["sample_id\tcomponent_id\tpartition\n"]
        csv_rows = ["sequence,labels\n"]
        fasta = []
        row_index = 0
        for partition in ("train", "validation"):
            for protein_id in range(1, 123):
                for label in (1, 0):
                    sample_id = f"row_{row_index}"
                    membership.append(f"{sample_id}\tc-{row_index}\t{partition}\n")
                    token = str(protein_id) if label == 1 else f"-{protein_id}"
                    csv_rows.append(f"10001000,{token}\n")
                    fasta.extend((f">{sample_id}\n", "AA\n"))
                    row_index += 1
        test_id = f"row_{row_index}"
        membership.append(f"{test_id}\tc-{row_index}\ttest\n")
        csv_rows.append("BROKEN,BAD-LABEL\n")
        fasta.extend((f">{test_id}\n", "NOT-ACGT\n"))
        with tempfile.TemporaryDirectory() as tmp:
            evidence = cache_004a3._build_development_cache_from_streams(
                Path(tmp) / "cache",
                membership_factory=lambda: iter(membership),
                csv_factory=lambda: iter(csv_rows),
                fasta_factory=lambda: iter(fasta), seed=17,
                sample_size=244, width=2, output_count=122,
                expected_partition_rows={"train": 244, "validation": 244, "test": 1},
                expected_component_count=489,
            )
            self.assertEqual(evidence.cache_metadata["partition_counts"], {
                "train": 244, "validation": 244,
            })
            self.assertEqual(evidence.cache_metadata["validation_known_counts"], [2] * 122)
            self.assertFalse(evidence.gate_a_access["test_accessed"])
            self.assertFalse(evidence.gate_b_access["test_accessed"])
            self.assertEqual(evidence.gate_a_access["test_rows_seen"], 1)
            self.assertEqual(evidence.gate_b_access["test_rows_seen"], 1)
            self.assertEqual(
                evidence.development_count_matrix["validation"]["positive"],
                (1,) * 122,
            )


class AdamTests(unittest.TestCase):
    def test_frozen_flags_and_three_step_state_oracle(self):
        config = load_config(CONFIG)
        model = torch.nn.Linear(3, 2)
        optimizer = build_gpu_adam(model, config)
        for key, value in ADAM_FLAGS.items():
            self.assertIs(optimizer.param_groups[0][key], value)
        evidence = run_three_step_oracle(config)
        self.assertEqual(evidence.steps, 3)
        self.assertTrue(evidence.step_counters_equal)
        self.assertEqual(evidence.compared_state_tensors, 8)

    def test_resource_checkpoint_has_distinct_authenticated_role(self):
        config = load_config(CONFIG)
        model = torch.nn.Linear(3, 2)
        optimizer = build_gpu_adam(model, config)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer)
        identity = {
            "source_sha256": "a" * 64, "config_sha256": "b" * 64,
            "environment_sha256": "c" * 64, "seed": 20261029,
            "config_id": "submitted",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource.pt"
            evidence = atomic_save_resource_smoke_checkpoint(
                path, model=model, optimizer=optimizer, scheduler=scheduler,
                identity=identity, training_steps=32,
            )
            loaded = load_resource_smoke_model_checkpoint(
                path, model=torch.nn.Linear(3, 2), expected_sha256=evidence["sha256"],
                expected_identity=identity,
            )
            self.assertEqual(loaded["training_step"], 32)
            with self.assertRaises(ResCNNCheckpointError):
                atomic_save_resource_smoke_checkpoint(
                    Path(tmp) / "bad.pt", model=model, optimizer=optimizer,
                    scheduler=scheduler, identity=identity, training_steps=1,
                )

    def test_role_directories_keep_checkpoint_basenames_and_bytes_identical(self):
        config = load_config(CONFIG)
        model = torch.nn.Linear(3, 2)
        optimizer = build_gpu_adam(model, config)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer)
        identity = {
            "source_sha256": "a" * 64, "config_sha256": "b" * 64,
            "environment_sha256": "c" * 64, "seed": 20261029,
            "config_id": "submitted",
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "candidate" / "primary.json"
            primary = runner_004a3.resource_checkpoint_path(output, "primary", "submitted")
            repeat = runner_004a3.resource_checkpoint_path(output, "repeat", "submitted")
            primary.parent.mkdir(parents=True); repeat.parent.mkdir(parents=True)
            atomic_save_resource_smoke_checkpoint(
                primary, model=model, optimizer=optimizer, scheduler=scheduler,
                identity=identity, training_steps=32,
            )
            atomic_save_resource_smoke_checkpoint(
                repeat, model=model, optimizer=optimizer, scheduler=scheduler,
                identity=identity, training_steps=32,
            )
            self.assertEqual(primary.name, repeat.name)
            self.assertEqual(primary.read_bytes(), repeat.read_bytes())


class TimingTests(unittest.TestCase):
    def test_sync_brackets_step_and_hashing_is_outside(self):
        events = []
        values = iter(float(i) for i in range(20))
        def sync(): events.append("sync")
        def clock(): events.append("clock"); return next(values)
        def step(batch): events.append(f"step:{batch}"); return batch
        def evidence(batch, result): events.append(f"hash:{batch}")
        summary = measure_batches(
            range(6), step=step, synchronize=sync, clock=clock,
            outside_timed_region=evidence,
        )
        self.assertEqual(summary.excluded_warmup, 4)
        self.assertEqual(summary.retained, 2)
        for batch in range(6):
            fragment = ["sync", "clock", f"step:{batch}", "sync", "clock", f"hash:{batch}"]
            start = batch * len(fragment)
            self.assertEqual(events[start:start + len(fragment)], fragment)

    def test_worst_case_metric_arrays_have_unique_known_scores_and_both_classes(self):
        targets, scores, masks = worst_case_metric_arrays([2] * 122)
        self.assertEqual(targets.shape, (57565, 122))
        known = masks.astype(bool)
        self.assertEqual(len(np.unique(scores[known])), 244)
        for protein in range(122):
            self.assertEqual(set(targets[:, protein][known[:, protein]]), {0, 1})


class ProjectionAndResourceTests(unittest.TestCase):
    def test_frozen_wall_and_storage_equations(self):
        wall = project_wall_seconds(TimeInputs(1, 2, 3, 4, 5, 6, 0.5, 10))
        expected_epoch = 961 + 225 * 2 + 3 + 4 + 5
        expected_raw = 6 + 3 * 30 * expected_epoch + 5
        self.assertEqual(wall["raw_seconds"], expected_raw)
        self.assertEqual(wall["projected_seconds"], expected_raw * 1.5)
        storage = project_storage_bytes(StorageInputs(100, 10, 20, 30, 40, 50))
        raw = 90 * 100 + 90 * 10 + 20 + 30 + 40 + 50
        self.assertEqual(storage["raw_bytes"], raw)
        self.assertEqual(storage["projected_bytes"], int(raw * 1.5))

    def test_resource_and_projection_limits_fail_closed(self):
        good = ResourceUse(1000, 800, 2000, 1600)
        require_memory_headroom(good)
        for bad in (ResourceUse(1000, 801, 2000, 1600), ResourceUse(1000, 800, 2000, 1601)):
            with self.assertRaises(ResCNN004A3RuntimeError):
                require_memory_headroom(bad)
        require_projection_limits(
            projected_wall_seconds=100, slurm_limit_seconds=100,
            projected_storage_bytes=100, free_bytes=100, quota_available_bytes=100,
        )
        for kwargs in (
            dict(projected_wall_seconds=101, slurm_limit_seconds=100, projected_storage_bytes=1, free_bytes=2, quota_available_bytes=2),
            dict(projected_wall_seconds=1, slurm_limit_seconds=2, projected_storage_bytes=2, free_bytes=1, quota_available_bytes=2),
            dict(projected_wall_seconds=1, slurm_limit_seconds=2, projected_storage_bytes=2, free_bytes=2, quota_available_bytes=None),
        ):
            with self.assertRaises(ResCNN004A3ProjectionError):
                require_projection_limits(**kwargs)

    def test_live_monitor_checks_deadline_disk_gpu_and_rss(self):
        values = {"gpu": 10, "rss": 20, "disk": 30, "clock": 1}
        monitor = LiveResourceMonitor(
            physical_gpu_bytes=100, requested_ram_bytes=100,
            output_path=Path("."), minimum_free_disk_bytes=25,
            deadline_monotonic=2, gpu_reserved_reader=lambda: values["gpu"],
            rss_reader=lambda: values["rss"], disk_free_reader=lambda _p: values["disk"],
            clock=lambda: values["clock"],
        )
        self.assertEqual(monitor.observe()["free_disk_bytes"], 30)
        for key, value in (("gpu", 81), ("rss", 81), ("disk", 24), ("clock", 3)):
            changed = dict(values); changed[key] = value
            bad = LiveResourceMonitor(
                physical_gpu_bytes=100, requested_ram_bytes=100,
                output_path=Path("."), minimum_free_disk_bytes=25,
                deadline_monotonic=2, gpu_reserved_reader=lambda c=changed: c["gpu"],
                rss_reader=lambda c=changed: c["rss"], disk_free_reader=lambda _p, c=changed: c["disk"],
                clock=lambda c=changed: c["clock"],
            )
            with self.assertRaises(ResCNN004A3RuntimeError):
                bad.observe()

    def test_identity_and_discovery_policy(self):
        identity = RuntimeIdentity("A100", "GPU-1", "a" * 64)
        require_identity_match(identity, identity)
        with self.assertRaises(ResCNN004A3RuntimeError):
            require_identity_match(identity, RuntimeIdentity("A100", "GPU-2", "a" * 64))
        self.assertEqual(require_discovery_install_policy({
            "compute_node_required_channels_reachable": False,
            "site_approved_install_location": "login_node",
        }), "login_node")
        with self.assertRaises(ResCNN004A3RuntimeError):
            require_discovery_install_policy({})

    def test_discovery_validator_rejects_each_missing_evidence_field(self):
        valid = _complete_discovery_payload()
        self.assertEqual(runtime_004a3.require_discovery_payload(valid), valid)
        required = set(valid) | set(runtime_004a3.DISCOVERY_COMMAND_FIELDS)
        for key in sorted(required):
            broken = dict(valid); broken.pop(key)
            with self.subTest(key=key), self.assertRaises(ResCNN004A3RuntimeError):
                runtime_004a3.require_discovery_payload(broken)

    def test_discovery_script_captures_every_frozen_command(self):
        script = (ROOT / "hpc/newton/004a3/01_DISCOVERY.sbatch").read_text()
        for fragment in (
            '"scontrol", "show", "partition"',
            '"sinfo", "-h", "-o", "%P|%l|%G|%f"',
            '"cat", "/etc/os-release"', '"uname", "-r"',
            '"ldd", "--version"', 'shutil.which("conda")',
            '"conda", "--version"', '"conda", "info", "--json"',
            'command_evidence("module avail", shell=True)',
            '"python3", "--version"', '"quota", "-s"',
            '"lfs", "quota", "-u"', '"df", "-B1"',
        ):
            self.assertIn(fragment, script)

    def test_discovery_validator_import_and_execution_do_not_require_torch(self):
        payload = _complete_discovery_payload()
        with tempfile.TemporaryDirectory() as tmp:
            discovery = Path(tmp) / "DISCOVERY.json"
            discovery.write_text(json.dumps(payload))
            code = (
                "import json, pathlib, sys; "
                "sys.modules['torch'] = None; "
                "from rbpbench.discovery_004a3 import require_discovery_payload; "
                "require_discovery_payload(json.loads(pathlib.Path(sys.argv[1]).read_text()))"
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT / "src")
            result = subprocess.run(
                [sys.executable, "-c", code, str(discovery)], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_discovery_return_precedes_stdlib_validation_and_is_python36_compatible(self):
        script = (ROOT / "hpc/newton/004a3/01_DISCOVERY.sbatch").read_text()
        checksum_write = script.index("Path(str(destination)+'.sha256')")
        validator = script.index("python3 -m rbpbench.discovery_004a3")
        self.assertLess(checksum_write, validator)
        self.assertNotIn("capture_output=", script)
        self.assertNotIn("text=", script)
        self.assertNotIn("rbpbench.rescnn", script)

    def test_discovery_submit_refuses_bad_quota_and_missing_user_before_sbatch(self):
        submit = ROOT / "hpc/newton/004a3/00_SUBMIT_DISCOVERY.sh"
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            marker = temporary / "sbatch-called"
            stub = temporary / "sbatch"
            stub.write_text(
                "#!/usr/bin/env bash\n"
                f"printf called > {marker!s}\n"
            )
            stub.chmod(0o755)
            base = dict(os.environ)
            base.update({
                "PATH": str(temporary) + os.pathsep + base.get("PATH", ""),
                "RBP_004A3_INSTALL_LOCATION": "login_node",
                "RBP_SLURM_MAIL_USER": "synthetic@example.invalid",
                "RBP_SLURM_PARTITION": "gpu-a100",
                "HOME": str(temporary), "USER": "synthetic-user",
            })
            cases = (
                ("non_numeric_quota", {**base, "RBP_004A3_QUOTA_AVAILABLE_BYTES": "10G"}),
                ("missing_user", {**base, "RBP_004A3_QUOTA_AVAILABLE_BYTES": "1000"}),
            )
            cases[1][1].pop("USER")
            for name, environment in cases:
                marker.unlink(missing_ok=True)
                result = subprocess.run(
                    ["/bin/bash", str(submit)], env=environment,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, check=False,
                )
                with self.subTest(case=name):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(marker.exists())

    def test_discovery_submit_requires_and_passes_reviewed_partition_and_account(self):
        submit = ROOT / "hpc/newton/004a3/00_SUBMIT_DISCOVERY.sh"
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            marker = temporary / "sbatch-arguments"
            stub = temporary / "sbatch"
            stub.write_text(
                "#!/usr/bin/env bash\n"
                f"printf '%s\\n' \"$@\" > {marker!s}\n"
                "printf 'Submitted batch job 1\\n'\n"
            )
            stub.chmod(0o755)
            environment = dict(os.environ)
            environment.update({
                "PATH": str(temporary) + os.pathsep + environment.get("PATH", ""),
                "RBP_004A3_INSTALL_LOCATION": "login_node",
                "RBP_004A3_QUOTA_AVAILABLE_BYTES": "1000",
                "RBP_SLURM_MAIL_USER": "synthetic@example.invalid",
                "HOME": str(temporary), "USER": "synthetic-user",
            })
            environment.pop("RBP_SLURM_PARTITION", None)
            environment.pop("RBP_SLURM_ACCOUNT", None)
            missing = subprocess.run(
                ["/bin/bash", str(submit)], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, check=False,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertFalse(marker.exists())

            environment["RBP_SLURM_PARTITION"] = "gpu-a100"
            accepted = subprocess.run(
                ["/bin/bash", str(submit)], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, check=False,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            arguments = marker.read_text().splitlines()
            self.assertIn("--partition=gpu-a100", arguments)
            self.assertFalse(any(value.startswith("--account=") for value in arguments))

            environment["RBP_SLURM_ACCOUNT"] = "research-account"
            accepted = subprocess.run(
                ["/bin/bash", str(submit)], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, check=False,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            arguments = marker.read_text().splitlines()
            self.assertIn("--partition=gpu-a100", arguments)
            self.assertIn("--account=research-account", arguments)

    def test_discovery_validator_binds_requested_scheduler_routing(self):
        valid = _complete_discovery_payload()
        self.assertEqual(runtime_004a3.require_discovery_payload(valid), valid)
        for key, value in (
            ("requested_slurm_partition", "other-gpu"),
            ("requested_slurm_account", "other-account"),
        ):
            broken = dict(valid); broken[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                ResCNN004A3RuntimeError, "disagree",
            ):
                runtime_004a3.require_discovery_payload(broken)

    def test_discovery_heredoc_uses_safe_user_and_home_fallbacks(self):
        script = (ROOT / "hpc/newton/004a3/01_DISCOVERY.sbatch").read_text()
        self.assertNotIn('os.environ["USER"]', script)
        self.assertNotIn('os.environ["HOME"]', script)
        self.assertIn('os.environ.get("USER") or getpass.getuser()', script)
        self.assertIn('os.environ.get("HOME") or str(Path.home())', script)

    def test_discovery_accepts_bound_unlimited_partition_as_raw_evidence(self):
        from rbpbench.discovery_004a3 import (
            parse_slurm_max_time, require_partition_time_evidence,
        )

        seconds, reason = parse_slurm_max_time("UNLIMITED")
        self.assertIsNone(seconds)
        self.assertIn("not a finite", reason)
        payload = _complete_discovery_payload()
        payload["slurm_limit_seconds"] = None
        payload["slurm_limit_error"] = reason
        payload["slurm_partition_detail"] = _command_evidence(
            stdout="PartitionName=public MaxTime=UNLIMITED PreemptMode=REQUEUE\n",
        )
        self.assertEqual(runtime_004a3.require_discovery_payload(payload), payload)
        self.assertEqual(require_partition_time_evidence(payload), {
            "kind": "unbounded", "seconds": None, "raw_value": "UNLIMITED",
        })

    def test_discovery_refuses_unbound_or_malformed_partition_limits(self):
        unlimited_error = "partition MaxTime is not a finite reviewed limit: UNLIMITED"
        cases = []
        for value in (0, -1):
            payload = _complete_discovery_payload()
            payload["slurm_limit_seconds"] = value
            cases.append(payload)
        payload = _complete_discovery_payload()
        payload["slurm_limit_seconds"] = None
        payload["slurm_limit_error"] = unlimited_error
        cases.append(payload)  # raw evidence still says a finite limit
        payload = _complete_discovery_payload()
        payload["slurm_limit_seconds"] = None
        payload["slurm_limit_error"] = "invented"
        payload["slurm_partition_detail"] = _command_evidence(
            stdout="PartitionName=public MaxTime=UNLIMITED PreemptMode=REQUEUE\n",
        )
        cases.append(payload)
        payload = _complete_discovery_payload()
        payload["slurm_limit_seconds"] = 86400  # raw evidence still says two days
        cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ResCNN004A3RuntimeError):
                runtime_004a3.require_discovery_payload(payload)

    def test_partition_preemption_evidence_is_required_and_unambiguous(self):
        from rbpbench.discovery_004a3 import require_partition_preempt_mode

        payload = _complete_discovery_payload()
        self.assertEqual(require_partition_preempt_mode(payload), "OFF")
        for stdout in (
            "PartitionName=gpu MaxTime=2-00:00:00\n",
            "MaxTime=2-00:00:00 PreemptMode=OFF PreemptMode=REQUEUE\n",
        ):
            broken = _complete_discovery_payload()
            broken["slurm_partition_detail"] = _command_evidence(stdout=stdout)
            with self.subTest(stdout=stdout), self.assertRaises(ResCNN004A3RuntimeError):
                runtime_004a3.require_discovery_payload(broken)

    def test_gpu_uuid_normalization_accepts_prefix_case_only_and_rejects_drift(self):
        bare = "58a8c3e2-1234-4abc-8def-1234567890ab"
        actual_name, normalized = runtime_004a3.require_allocated_gpu(
            required_gpu_name="NVIDIA A100", actual_gpu_name="NVIDIA A100",
            allocated_gpu_uuid=" GPU-58A8C3E2-1234-4ABC-8DEF-1234567890AB ",
            torch_gpu_uuid=bare,
        )
        self.assertEqual(actual_name, "NVIDIA A100")
        self.assertEqual(normalized, bare)
        with self.assertRaisesRegex(ResCNN004A3RuntimeError, "does not match"):
            runtime_004a3.require_allocated_gpu(
                required_gpu_name="NVIDIA A100", actual_gpu_name="NVIDIA A100",
                allocated_gpu_uuid="GPU-58A8C3E2-1234-4ABC-8DEF-1234567890AB",
                torch_gpu_uuid="68a8c3e2-1234-4abc-8def-1234567890ab",
            )
        for malformed in ("", "GPU-", "GPU-1", "not-a-uuid"):
            with self.subTest(malformed=malformed), self.assertRaisesRegex(
                ResCNN004A3RuntimeError, "malformed",
            ):
                runtime_004a3.require_allocated_gpu(
                    required_gpu_name="NVIDIA A100", actual_gpu_name="NVIDIA A100",
                    allocated_gpu_uuid=malformed, torch_gpu_uuid=bare,
                )

    def test_gpu_policy_mismatch_precedes_cache_open(self):
        allocated_uuid = "GPU-58A8C3E2-1234-4ABC-8DEF-1234567890AB"
        properties = type("Properties", (), {
            "uuid": "58a8c3e2-1234-4abc-8def-1234567890ab",
        })()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, THREAD_ENV, clear=False), \
             mock.patch.object(runner_004a3, "configure_strict_float32"), \
             mock.patch.object(torch.cuda, "is_available", return_value=True), \
             mock.patch.object(torch.cuda, "current_device", return_value=0), \
             mock.patch.object(torch.cuda, "get_device_properties", return_value=properties), \
             mock.patch.object(torch.cuda, "get_device_name", return_value="Wrong GPU"), \
             mock.patch.object(runner_004a3, "open_cache") as cache_open:
            with self.assertRaisesRegex(runner_004a3.ResCNN004A3RunnerError, "model"):
                runner_004a3.run_process(
                    role="primary", config_path=CONFIG,
                    cache_path=Path(tmp) / "never-opened",
                    output_path=Path(tmp) / "primary.json",
                    runtime_manifest_sha256="a" * 64, source_sha256="b" * 64,
                    requested_ram_bytes=100, physical_gpu_bytes=100,
                    minimum_free_disk_bytes=1, deadline_monotonic=1,
                    required_gpu_name="NVIDIA A100", allocated_gpu_uuid=allocated_uuid,
                )
            cache_open.assert_not_called()

    def test_project_requires_positive_bundle_slurm_limit_before_other_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "bundle.json"
            common = [
                "project", "--bundle-root", str(root), "--bundle-config", str(config),
                "--primary", str(root / "missing-primary"),
                "--repeat", str(root / "missing-repeat"),
                "--metric-benchmark", str(root / "missing-metric"),
                "--comparison", str(root / "missing-comparison"),
                "--output", str(root / "out"),
            ]
            for payload in ({}, {"slurm_limit_seconds": 0}, {"slurm_limit_seconds": -1}):
                config.write_text(json.dumps(payload))
                with self.subTest(payload=payload), self.assertRaises(ResCNN004A3ProjectionError):
                    runner_004a3.main(common)
        self.assertEqual(
            projection_004a3.reviewed_slurm_limit_seconds({"slurm_limit_seconds": 99}), 99,
        )


class EnvironmentPortableAndScriptTests(unittest.TestCase):
    def test_builder_declares_all_focused_suite_root_dependencies(self):
        spec = importlib.util.spec_from_file_location(
            "build_004a3_bundle_dependencies",
            ROOT / "scripts/build_004a3_portable_bundle.py",
        )
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        required = {
            "intRBP ResCNN - for students.ipynb",
            "manifests/task003b_phase_a_003b3.json",
            "manifests/task004a2b_local_smoke.json",
            "scripts/run_004a2b_local_smoke_recovery.sh",
            "scripts/build_004a3_portable_bundle.py",
            "hpc/newton/004a3/00_SUBMIT_DISCOVERY.sh",
        }
        self.assertTrue(required.issubset(set(builder.OTHER_FILES)))

    def test_complete_runtime_manifest_and_lock_are_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = root / "env"
            (prefix / "bin").mkdir(parents=True)
            (prefix / "bin/python").write_bytes(b"python")
            lock = root / "lock.txt"; lock.write_text("@EXPLICIT\n")
            manifest = root / "runtime.json"
            payload = {"entries": [{
                "path": "bin/python", "type": "file", "byte_size": 6,
                "sha256": hashlib.sha256(b"python").hexdigest(),
            }]}
            manifest.write_text(json.dumps(payload))
            result = verify_runtime(
                prefix, manifest_path=manifest, manifest_sha256=sha256_file(manifest),
                lock_path=lock, lock_sha256=sha256_file(lock),
            )
            self.assertEqual(result["entry_count"], 1)
            (prefix / "extra").write_text("x")
            with self.assertRaises(ResCNN004A3EnvironmentError):
                verify_runtime(
                    prefix, manifest_path=manifest, manifest_sha256=sha256_file(manifest),
                    lock_path=lock, lock_sha256=sha256_file(lock),
                )

    def test_launcher_exports_before_separate_python_processes(self):
        script = (ROOT / "hpc/newton/004a3/RUN_004A3_SMOKE.sbatch").read_text()
        first_python = script.index('"$RBP_004A3_ENV_PREFIX/bin/python"')
        for key, value in THREAD_ENV.items():
            self.assertIn(f"{key}={value}", script[:first_python])
        primary = script.index("--role primary")
        repeat = script.index("--role repeat")
        self.assertLess(primary, repeat)
        self.assertIn("set -Eeuo pipefail", script)
        self.assertIn("--requested-ram-bytes", script)
        self.assertIn("--physical-gpu-bytes", script)
        self.assertIn("--deadline-monotonic", script)
        self.assertNotIn("RBP_004A3_SOURCE_SHA256", script)
        self.assertNotIn("RBP_004A3_RUNTIME_SHA256", script)
        self.assertIn('c["runtime_manifest_sha256"]', script)
        self.assertIn('c["source_sha256"]', script)
        self.assertNotIn("--slurm-limit-seconds 14400", script)
        self.assertIn("RBP_ALLOCATED_GPU_UUID", script)
        self.assertIn('--required-gpu-name "$REQUIRED_GPU_NAME"', script)
        ordered = [
            "bundle_verification", "environment_verification", "focused_tests",
            "predata_probe", "full_metric_benchmark", 'STAGE="primary"',
        ]
        positions = [script.index(value) for value in ordered]
        self.assertEqual(positions, sorted(positions))
        for path in (ROOT / "hpc/newton/004a3").iterdir():
            if path.suffix in (".sh", ".sbatch"):
                import subprocess
                subprocess.run(["/bin/bash", "-n", str(path)], check=True)

    def test_pre_python_environment_gate(self):
        with mock.patch.dict(os.environ, THREAD_ENV, clear=False):
            require_pre_python_environment()
        with mock.patch.dict(os.environ, {**THREAD_ENV, "OMP_NUM_THREADS": "3"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "pre-Python"):
                require_pre_python_environment()

    def test_process_comparison_binds_gpu_runtime_and_all_digests(self):
        record = {
            "gpu_name": "A100", "gpu_uuid": "GPU-1", "runtime_manifest_sha256": "a" * 64,
            "initial_state_sha256": "b" * 64, "order_sha256": "c" * 64,
            "dropped_sha256": "d" * 64,
            "config_records": {"submitted": {
                "checkpoint_sha256": "e" * 64, "prediction_sha256": "f" * 64,
                "loss_steps_sha256": "1" * 64, "gradient_steps_sha256": "2" * 64,
                "checkpoint_model_state_sha256": "3" * 64,
                "reloaded_model_state_sha256": "3" * 64,
                "validation_batch_sizes": [256, 1], "checkpoint_seconds": 1.0,
            }},
        }
        repeat = json.loads(json.dumps(record))
        repeat["config_records"]["submitted"]["checkpoint_seconds"] = 2.0
        self.assertTrue(compare_process_records(record, repeat)["all_required_digests_equal"])
        changed = json.loads(json.dumps(record)); changed["gpu_uuid"] = "GPU-2"
        with self.assertRaises(ResCNN004A3PortableError):
            compare_process_records(record, changed)
        changed = json.loads(json.dumps(record))
        changed["config_records"]["submitted"]["gradient_steps_sha256"] = "9" * 64
        with self.assertRaises(ResCNN004A3PortableError):
            compare_process_records(record, changed)

    def test_return_sanitation_refuses_rows_sequences_and_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            for payload in (
                {"sample_id": "x"}, {"message": "row_12"},
                {"message": "A" * 60}, {"path": "model.pt"},
            ):
                with self.assertRaises(ResCNN004A3PortableError):
                    package_sanitized_return(Path(tmp), payload, Path(tmp) / "return.zip")

    def test_bundle_inventory_and_positive_sanitized_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bundle"; root.mkdir()
            (root / "file.txt").write_text("aggregate evidence\n")
            inventory = build_inventory(root)
            (root / "BUNDLE_INVENTORY.json").write_text(json.dumps(inventory))
            self.assertEqual(verify_bundle(root), inventory)
            returned = package_sanitized_return(
                Path(tmp), {"status": "COMPLETED", "counts": {"configs": 3}},
                Path(tmp) / "return.zip",
            )
            self.assertEqual(len(returned["sha256"]), 64)
            self.assertTrue((Path(tmp) / "return.zip.sha256").is_file())

    def test_portable_builder_and_archive_with_synthetic_cache(self):
        spec = importlib.util.spec_from_file_location(
            "build_004a3_bundle", ROOT / "scripts/build_004a3_portable_bundle.py",
        )
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        bases = (0,) * 500; targets = (0,) * 122; masks = (1,) * 122
        def rows():
            for partition_index, partition in enumerate(("train", "validation")):
                for index in range(8193):
                    number = partition_index * 8193 + index
                    yield CacheRow(f"row_{number}", f"c-{number}", partition, bases, targets, masks)
        with tempfile.TemporaryDirectory() as tmp:
            temporary = Path(tmp)
            cache = temporary / "cache"; write_cache(cache, rows())
            discovery = temporary / "discovery.json"
            discovery.write_text(json.dumps(_complete_discovery_payload()))
            lock = temporary / "lock"; lock.write_text("@EXPLICIT\n")
            runtime = temporary / "runtime.json"; runtime.write_text(json.dumps({
                "entries": [{"path": "bin/python", "type": "file", "byte_size": 10}],
            }))
            summary = temporary / "summary.json"; summary.write_text("{}")
            with mock.patch.object(
                builder, "_full_validation_known_counts", return_value=[8193] * 122,
            ), self.assertRaisesRegex(RuntimeError, "subset-derived"):
                builder.build_bundle(
                    repo=ROOT, destination=temporary / "rejected-bundle", cache=cache,
                    discovery=discovery, environment_lock=lock, runtime_manifest=runtime,
                    task004a2_summary=summary,
                    expected_lock_sha256=sha256_file(lock),
                    expected_runtime_sha256=sha256_file(runtime),
                    required_gpu_name="NVIDIA A100", gpu_gres="gpu:a100:1",
                    gpu_constraint="a100",
                )
            with mock.patch.object(
                builder, "_full_validation_known_counts", return_value=[10000] * 122,
            ):
                bundle = builder.build_bundle(
                    repo=ROOT, destination=temporary / "bundle", cache=cache,
                    discovery=discovery, environment_lock=lock, runtime_manifest=runtime,
                    task004a2_summary=summary,
                    expected_lock_sha256=sha256_file(lock),
                    expected_runtime_sha256=sha256_file(runtime),
                    required_gpu_name="NVIDIA A100", gpu_gres="gpu:a100:1",
                    gpu_constraint="a100",
                )
            verify_bundle(bundle)
            bundled_config = json.loads((bundle / "BUNDLE_CONFIG.json").read_text())
            self.assertEqual(len(bundled_config["source_sha256"]), 64)
            self.assertEqual(
                bundled_config["source_sha256"], builder._source_digest(ROOT),
            )
            self.assertEqual(bundled_config["validation_known_counts"], [10000] * 122)
            self.assertEqual(
                bundled_config["slurm_limit_seconds"],
                PROJECT_004A4_SLURM_LIMIT_SECONDS,
            )
            self.assertEqual(bundled_config["slurm_limit_source"], "project_owned_reviewed_ceiling")
            self.assertEqual(bundled_config["partition_slurm_limit_kind"], "finite")
            self.assertEqual(bundled_config["partition_slurm_limit_seconds"], 172800)
            self.assertEqual(bundled_config["partition_preempt_mode"], "OFF")
            self.assertEqual(bundled_config["smoke_requeue_policy"], "disabled_fail_closed")
            self.assertEqual(bundled_config["required_gpu_name"], "NVIDIA A100")
            for relative in (
                "intRBP ResCNN - for students.ipynb",
                "manifests/task003b_phase_a_003b3.json",
                "manifests/task004a2b_local_smoke.json",
                "scripts/run_004a2b_local_smoke_recovery.sh",
                "scripts/build_004a3_portable_bundle.py",
                "hpc/newton/004a3/00_SUBMIT_DISCOVERY.sh",
            ):
                self.assertTrue((bundle / relative).is_file(), relative)
            archive = builder.archive_bundle(bundle)
            self.assertEqual(len(archive["sha256"]), 64)
            self.assertTrue(Path(str(archive["path"]) + ".sha256").is_file())

    def test_bundle_binds_unlimited_partition_to_finite_project_limit(self):
        spec = importlib.util.spec_from_file_location(
            "build_004a3_bundle_scheduler", ROOT / "scripts/build_004a3_portable_bundle.py",
        )
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        payload = _complete_discovery_payload()
        payload["slurm_limit_seconds"] = None
        payload["slurm_limit_error"] = (
            "partition MaxTime is not a finite reviewed limit: UNLIMITED"
        )
        payload["slurm_partition_detail"] = _command_evidence(
            stdout="PartitionName=public MaxTime=UNLIMITED PreemptMode=REQUEUE\n",
        )
        runtime_004a3.require_discovery_payload(payload)
        policy = builder._reviewed_scheduler_policy(payload)
        self.assertEqual(policy["partition_slurm_limit_kind"], "unbounded")
        self.assertIsNone(policy["partition_slurm_limit_seconds"])
        self.assertEqual(policy["partition_slurm_limit_raw_value"], "UNLIMITED")
        self.assertEqual(policy["slurm_limit_seconds"], 12 * 60 * 60)
        self.assertEqual(policy["partition_preempt_mode"], "REQUEUE")
        self.assertEqual(policy["full_run_preemption_requirement"], "restart_safe_before_004a4")

    def test_project_limit_must_fit_a_finite_partition_limit(self):
        spec = importlib.util.spec_from_file_location(
            "build_004a3_bundle_limit", ROOT / "scripts/build_004a3_portable_bundle.py",
        )
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        payload = _complete_discovery_payload()
        payload["slurm_limit_seconds"] = PROJECT_004A4_SLURM_LIMIT_SECONDS - 1
        payload["slurm_partition_detail"] = _command_evidence(
            stdout="PartitionName=gpu MaxTime=11:59:59 PreemptMode=OFF\n",
        )
        with self.assertRaisesRegex(RuntimeError, "exceeds"):
            builder._reviewed_scheduler_policy(payload)

    def test_smoke_is_fail_closed_on_public_partition_preemption(self):
        script = (ROOT / "hpc/newton/004a3/RUN_004A3_SMOKE.sbatch").read_text()
        self.assertIn("#SBATCH --no-requeue", script)
        self.assertIn("trap on_failure ERR INT TERM", script)

    def test_full_validation_counts_refuse_subset_derived_or_unbound_evidence(self):
        spec = importlib.util.spec_from_file_location(
            "build_004a3_bundle_counts", ROOT / "scripts/build_004a3_portable_bundle.py",
        )
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        def payload(positive, negative):
            return {"audit": {"development_counts": {"validation": {
                "positive": positive, "negative": negative,
            }}}}
        with self.assertRaisesRegex(RuntimeError, "strictly larger"):
            builder._extract_full_validation_known_counts(
                payload=payload([4] * 122, [6] * 122), subset_counts=[10] * 122,
            )
        with self.assertRaisesRegex(RuntimeError, "length 122"):
            builder._extract_full_validation_known_counts(
                payload=payload([5] * 121, [6] * 121), subset_counts=[1] * 122,
            )
        with tempfile.TemporaryDirectory() as tmp:
            wrong = Path(tmp) / "summary.json"; wrong.write_text(json.dumps(
                payload([5000] * 122, [5000] * 122),
            ))
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                builder._full_validation_known_counts(
                    repo=ROOT, summary=wrong, subset_counts=[10] * 122,
                )


if __name__ == "__main__":
    unittest.main()
