from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    import numpy as np
    import torch
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("Task 004A-3 tests require NumPy and PyTorch") from exc

from rbpbench.rescnn.adam_004a3 import ADAM_FLAGS, build_gpu_adam, run_three_step_oracle
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
    StorageInputs, TimeInputs, project_storage_bytes, project_wall_seconds,
    require_projection_limits, ResCNN004A3ProjectionError,
)
from rbpbench.rescnn.runner_004a3 import THREAD_ENV, require_pre_python_environment
from rbpbench.rescnn.runtime_004a3 import (
    LiveResourceMonitor,
    ResourceUse, RuntimeIdentity, require_discovery_install_policy,
    require_identity_match, require_memory_headroom, ResCNN004A3RuntimeError,
)
from rbpbench.rescnn.timing_004a3 import measure_batches, worst_case_metric_arrays


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/models/task004a_v1.toml"


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


class EnvironmentPortableAndScriptTests(unittest.TestCase):
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
            discovery.write_text(json.dumps({
                "compute_node_required_channels_reachable": False,
                "site_approved_install_location": "login_node",
                "quota_available_bytes": 10**12,
            }))
            lock = temporary / "lock"; lock.write_text("@EXPLICIT\n")
            runtime = temporary / "runtime.json"; runtime.write_text(json.dumps({
                "entries": [{"path": "bin/python", "type": "file", "byte_size": 10}],
            }))
            bundle = builder.build_bundle(
                repo=ROOT, destination=temporary / "bundle", cache=cache,
                discovery=discovery, environment_lock=lock, runtime_manifest=runtime,
                expected_lock_sha256=sha256_file(lock),
                expected_runtime_sha256=sha256_file(runtime),
            )
            verify_bundle(bundle)
            bundled_config = json.loads((bundle / "BUNDLE_CONFIG.json").read_text())
            self.assertEqual(len(bundled_config["source_sha256"]), 64)
            self.assertEqual(
                bundled_config["source_sha256"], builder._source_digest(ROOT),
            )
            archive = builder.archive_bundle(bundle)
            self.assertEqual(len(archive["sha256"]), 64)
            self.assertTrue(Path(str(archive["path"]) + ".sha256").is_file())


if __name__ == "__main__":
    unittest.main()
