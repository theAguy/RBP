from __future__ import annotations

from dataclasses import replace
import gzip
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

try:
    import torch
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("Task 004A-2 tests require PyTorch") from exc

from rbpbench.rescnn.checkpoint import (
    ResCNNCheckpointError,
    atomic_save_final_checkpoint,
    atomic_save_smoke_checkpoint,
    load_final_model_checkpoint,
    load_smoke_model_checkpoint,
)
from rbpbench.rescnn.config import ResCNNConfigError, load_config
from rbpbench.rescnn.data_004a2 import (
    CacheRecord,
    CompactSampleCache,
    ResCNN004A2DataError,
    canonical_content_sha256,
)
from rbpbench.rescnn.environment_004a2 import require_safe_torch_load
from rbpbench.rescnn.factories_004a2 import build_adam, build_scheduler
from rbpbench.rescnn.output import ResCNNOutputError, validate_prediction_rows
from rbpbench.rescnn.resources_004a2 import (
    GIB,
    ResCNNResourceError,
    ResourceSnapshot,
    configure_exact_threads,
    normalize_ru_maxrss_bytes,
    parse_macos_available_memory_bytes,
    require_local_resources,
)
from rbpbench.rescnn.runner_004a2 import (
    EXPECTED_BOUNDS,
    ResCNN004A2RunnerError,
    _bound_source_evidence,
    _phase_a_bounds_from_payload,
    _verify_phase_a_bounds,
    build_parser,
    execute,
    resolve_fasta_500,
)
from rbpbench.rescnn.smoke_004a2 import run_paired_smoke, scientific_signature
from rbpbench.rescnn.model import (
    CNNMultiLabelResidual,
    EXPECTED_LEARNABLE_PARAMETERS,
    count_learnable_parameters,
)
from rbpbench.rescnn.reproducibility import configure_strict_float32


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/models/task004a_v1.toml"


class TinyDropoutModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.dropout = torch.nn.Dropout(0.2)
        self.linear = torch.nn.Linear(500 * 4, 122)

    def forward(self, values):
        return self.linear(self.dropout(values.flatten(1)))


class DriftingBatchNormModel(torch.nn.Module):
    calls = 0

    def __init__(self):
        super().__init__()
        self.linear = torch.nn.Linear(500 * 4, 122)
        self.batch_norm = torch.nn.BatchNorm1d(122)
        type(self).calls += 1
        self.batch_norm.running_var.fill_(float(type(self).calls))

    def forward(self, values):
        return self.batch_norm(self.linear(values.flatten(1)))


def _cache() -> CompactSampleCache:
    records = []
    for index in range(1026):
        partition = "train" if index < 513 else "validation"
        state = index % 3
        targets = tuple(1 if state == 0 else 0 for _ in range(122))
        masks = tuple(0 if state == 2 else 1 for _ in range(122))
        codes = tuple((index + position) % 4 for position in range(500))
        content = canonical_content_sha256(
            sample_id=f"row_{index}", component_id=f"component-{index}", partition=partition,
            base_codes=codes, targets=targets, masks=masks,
        )
        records.append(CacheRecord(
            f"row_{index}", f"component-{index}", partition,
            codes, targets, masks, content,
        ))
    return CompactSampleCache(records)


class FactoryAndResourceTests(unittest.TestCase):
    def test_factories_reject_hand_built_config_drift(self):
        config = load_config(CONFIG)
        model = torch.nn.Linear(2, 2)
        drift = replace(config, optimizer={**config.optimizer, "learning_rate": 0.2})
        with self.assertRaises(ResCNNConfigError):
            build_adam(model, drift)
        optimizer = build_adam(model, config)
        scheduler = build_scheduler(optimizer, config)
        self.assertEqual(optimizer.param_groups[0]["lr"], 0.001)
        self.assertEqual(scheduler.mode, "max")

    def test_resource_units_vm_stat_and_four_threads(self):
        self.assertEqual(normalize_ru_maxrss_bytes(123, "Darwin"), 123)
        self.assertEqual(normalize_ru_maxrss_bytes(123, "Linux"), 123 * 1024)
        vm = "Mach Virtual Memory Statistics: (page size of 4096 bytes)\n" \
             "Pages free: 10.\nPages inactive: 20.\nPages speculative: 30.\n"
        self.assertEqual(parse_macos_available_memory_bytes(vm), 60 * 4096)
        with self.assertRaises(ResCNNResourceError):
            parse_macos_available_memory_bytes("Pages free: 10.\n")
        evidence = configure_exact_threads(torch)
        self.assertEqual(evidence["numerical_threads"], 4)
        self.assertEqual(torch.get_num_threads(), 4)
        with self.assertRaises(ResCNNResourceError):
            configure_exact_threads(torch, count=3)

    def test_resource_boundaries_fail_closed(self):
        good = ResourceSnapshot("Darwin", 16 * GIB, 4 * GIB, 20 * GIB, 4 * GIB)
        require_local_resources(good)
        for value in (
            replace(good, installed_ram_bytes=16 * GIB - 1),
            replace(good, available_ram_bytes=4 * GIB - 1),
            replace(good, free_disk_bytes=20 * GIB - 1),
            replace(good, peak_rss_bytes=4 * GIB + 1),
        ):
            with self.assertRaises(ResCNNResourceError):
                require_local_resources(value)


class RoleAndSmokeTests(unittest.TestCase):
    def test_prediction_roles_are_schema_separated(self):
        fields = (
            "sample_id", "component_id", "protein_id", "fold", "partition", "seed",
            "window", "config_id", "config_hash", "label", "score",
        )
        smoke = dict(zip(fields, (
            "row_1", "component-1", 1, "components_v2_coverage_smoke", "validation",
            20261029, 500, "submitted", "a" * 64, 1, 0.5,
        )))
        self.assertEqual(validate_prediction_rows(
            [smoke], artifact_role="coverage_smoke",
            schema_version="task004a_smoke_prediction_v1",
        ), 1)
        with self.assertRaises(ResCNNOutputError):
            validate_prediction_rows([smoke], artifact_role="coverage_smoke")

    def test_final_and_smoke_checkpoint_roles_cannot_cross(self):
        require_safe_torch_load()
        config = load_config(CONFIG)
        identity = {
            "source_sha256": "a" * 64, "config_sha256": "b" * 64,
            "environment_sha256": "c" * 64, "seed": 20261029,
            "config_id": "submitted",
        }
        with tempfile.TemporaryDirectory() as tmp:
            model = torch.nn.Linear(4, 2)
            optimizer = torch.optim.Adam(model.parameters())
            scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer)
            final = atomic_save_final_checkpoint(
                Path(tmp) / "final.pt", model=model, optimizer=optimizer,
                scheduler=scheduler, config=config, identity=identity,
            )
            smoke = atomic_save_smoke_checkpoint(
                Path(tmp) / "smoke.pt", model=model, optimizer=optimizer,
                scheduler=scheduler, identity=identity,
            )
            with self.assertRaisesRegex(ResCNNCheckpointError, "not a final"):
                load_final_model_checkpoint(
                    Path(tmp) / "smoke.pt", model=torch.nn.Linear(4, 2), config=config,
                    expected_sha256=smoke["sha256"], expected_identity=identity,
                )
            with self.assertRaisesRegex(ResCNNCheckpointError, "not a local smoke"):
                load_smoke_model_checkpoint(
                    Path(tmp) / "final.pt", model=torch.nn.Linear(4, 2),
                    expected_sha256=final["sha256"], expected_identity=identity,
                )

    def test_hash_and_identity_are_checked_before_deserialization(self):
        config = load_config(CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.pt"
            path.write_bytes(b"not a checkpoint")
            with mock.patch("rbpbench.rescnn.checkpoint.torch.load") as loader:
                with self.assertRaisesRegex(ResCNNCheckpointError, "SHA-256 mismatch"):
                    load_final_model_checkpoint(
                        path, model=torch.nn.Linear(2, 1), config=config,
                        expected_sha256="0" * 64,
                        expected_identity={
                            "source_sha256": "a" * 64, "config_sha256": "b" * 64,
                            "environment_sha256": "c" * 64, "seed": 20261029,
                            "config_id": "submitted",
                        },
                    )
                loader.assert_not_called()

    def test_complete_paired_smoke_repeats_exactly(self):
        require_safe_torch_load()
        config = load_config(CONFIG)
        cache = _cache()
        with tempfile.TemporaryDirectory() as tmp:
            primary = run_paired_smoke(
                cache, config=config, output_dir=Path(tmp) / "primary",
                source_sha256="a" * 64, config_sha256="b" * 64,
                environment_sha256="c" * 64, model_factory=TinyDropoutModel,
            )
            repeat = run_paired_smoke(
                cache, config=config, output_dir=Path(tmp) / "repeat",
                source_sha256="a" * 64, config_sha256="b" * 64,
                environment_sha256="c" * 64, model_factory=TinyDropoutModel,
            )
        self.assertEqual(scientific_signature(primary), scientific_signature(repeat))
        self.assertTrue(primary.evidence["all_pair_losses_distinct"])
        self.assertTrue(primary.evidence["all_pair_gradients_distinct"])
        for result in primary.by_config.values():
            self.assertEqual(result.evidence["validation_batch_sizes"], [256, 256, 1])
            self.assertEqual(result.evidence["metrics"]["eligible_output_count"], 122)
            self.assertTrue(result.evidence["weights_only_used"])

    def test_paired_smoke_refuses_different_initial_state_with_equal_training_logits(self):
        require_safe_torch_load()
        config = load_config(CONFIG)
        DriftingBatchNormModel.calls = 0
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "initial model state"):
                run_paired_smoke(
                    _cache(), config=config, output_dir=Path(tmp) / "drift",
                    source_sha256="a" * 64, config_sha256="b" * 64,
                    environment_sha256="c" * 64, model_factory=DriftingBatchNormModel,
                )

    def test_real_cnn_completes_paired_primary_repeat_at_four_threads(self):
        require_safe_torch_load()
        configure_exact_threads(torch)
        configure_strict_float32(require_cuda=False)
        config = load_config(CONFIG)
        cache = _cache()
        factory = lambda: CNNMultiLabelResidual(config.output_count)
        self.assertEqual(
            count_learnable_parameters(factory()), EXPECTED_LEARNABLE_PARAMETERS,
        )
        with tempfile.TemporaryDirectory() as tmp:
            primary = run_paired_smoke(
                cache, config=config, output_dir=Path(tmp) / "cnn-primary",
                source_sha256="a" * 64, config_sha256="b" * 64,
                environment_sha256="c" * 64, model_factory=factory,
            )
            repeat = run_paired_smoke(
                cache, config=config, output_dir=Path(tmp) / "cnn-repeat",
                source_sha256="a" * 64, config_sha256="b" * 64,
                environment_sha256="c" * 64, model_factory=factory,
            )
            checkpoint_bytes = sum(
                int(result.evidence["checkpoint"]["byte_size"])
                for run in (primary, repeat)
                for result in run.by_config.values()
            )
        self.assertEqual(scientific_signature(primary), scientific_signature(repeat))
        self.assertTrue(primary.evidence["all_initial_model_state_hashes_equal"])
        self.assertEqual(
            len({
                result.evidence["initial_model_state_sha256"]
                for result in primary.by_config.values()
            }),
            1,
        )
        self.assertLess(checkpoint_bytes, GIB)
        for result in primary.by_config.values():
            self.assertEqual(result.evidence["validation_batch_sizes"], [256, 256, 1])
            self.assertEqual(result.evidence["metrics"]["eligible_output_count"], 122)
            self.assertTrue(result.evidence["weights_only_used"])


class RunnerBoundaryTests(unittest.TestCase):
    def test_accepted_phase_a_manifest_schema_maps_to_frozen_bounds(self):
        path = ROOT / "manifests/task003b_phase_a_003b3.json"
        payload = json.loads(path.read_text())
        self.assertEqual(_phase_a_bounds_from_payload(payload), EXPECTED_BOUNDS)
        evidence = _verify_phase_a_bounds(path, repo_root=ROOT)
        self.assertEqual(evidence["path"], "manifests/task003b_phase_a_003b3.json")
        self.assertEqual(
            evidence["sha256"],
            "77922d6d906b7a4fd9ba8cae091e93072b0e1b09735a0397cdead2b2dfeed257",
        )

    def test_phase_a_schema_translation_refuses_scientific_drift(self):
        path = ROOT / "manifests/task003b_phase_a_003b3.json"
        payload = json.loads(path.read_text())
        payload["fitting"]["fitting_sequence_count"] += 1
        with self.assertRaisesRegex(ResCNN004A2RunnerError, "development bounds drift"):
            _phase_a_bounds_from_payload(payload)

        payload = json.loads(path.read_text())
        payload["fitting"]["partitions"] = ["validation", "train"]
        with self.assertRaisesRegex(ResCNN004A2RunnerError, "partitions drift"):
            _phase_a_bounds_from_payload(payload)

        payload = json.loads(path.read_text())
        payload["fitting"]["protein_count"] = 121
        with self.assertRaisesRegex(ResCNN004A2RunnerError, "protein count drift"):
            _phase_a_bounds_from_payload(payload)

    def test_recovery_wrapper_is_macos_bash_compatible(self):
        script = ROOT / "scripts/run_004a2b_local_smoke_recovery.sh"
        text = script.read_text()
        self.assertNotIn("declare -A", text)
        completed = subprocess.run(
            ["/bin/bash", "-n", str(script)], capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_source_evidence_includes_loaded_baseline_dependencies(self):
        evidence = _bound_source_evidence(ROOT)
        paths = {row["path"] for row in evidence["files"]}
        self.assertIn("rbpbench/baselines/data.py", paths)
        self.assertIn("rbpbench/baselines/metrics.py", paths)
        self.assertIn("rbpbench/rescnn/runner_004a2.py", paths)
        self.assertTrue(all(not Path(path).is_absolute() for path in paths))

    def test_loaded_rbpbench_module_outside_source_tree_stops_before_input_hashing(self):
        module = sys.modules["rbpbench.rescnn.data_004a2"]
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "stale.py"
            stale.write_text("# stale installed copy\n")
            args = SimpleNamespace(repo_root=ROOT)
            with mock.patch.object(module, "__file__", str(stale)), mock.patch(
                "rbpbench.rescnn.runner_004a2._require_clean_worktree"
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2._input_evidence"
            ) as input_evidence:
                with self.assertRaisesRegex(ResCNN004A2RunnerError, "outside repo_root/src"):
                    execute(args)
                input_evidence.assert_not_called()

    def test_decode_manifest_is_authoritative_for_fasta_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fasta = root / "decode/generations/d/sequence_partitions_width_500.fasta"
            fasta.parent.mkdir(parents=True)
            fasta.write_text(">row_0\nA\n")
            import hashlib
            digest = hashlib.sha256(fasta.read_bytes()).hexdigest()
            manifest = root / "decode.json"
            manifest.write_text(__import__("json").dumps({
                "retained_artifacts": [{
                    "path": fasta.relative_to(root).as_posix(),
                    "byte_size": fasta.stat().st_size,
                    "sha256": digest,
                }]
            }))
            self.assertEqual(resolve_fasta_500(root, manifest, digest), fasta.resolve())
            with self.assertRaises(ResCNN004A2RunnerError):
                resolve_fasta_500(root, manifest, "0" * 64)

    def test_environment_failure_occurs_before_real_input_evidence(self):
        args = SimpleNamespace(
            repo_root=ROOT, config=CONFIG, environment_manifest=ROOT / "missing-env.json",
            output_dir=ROOT / "artifacts/never-created",
        )
        with mock.patch(
            "rbpbench.rescnn.runner_004a2._verify_environment",
            side_effect=ResCNN004A2RunnerError("environment stopped"),
        ), mock.patch(
            "rbpbench.rescnn.runner_004a2._require_clean_worktree"
        ), mock.patch("rbpbench.rescnn.runner_004a2._input_evidence") as input_evidence:
            with self.assertRaisesRegex(ResCNN004A2RunnerError, "environment stopped"):
                execute(args)
            input_evidence.assert_not_called()

    def test_gate_a_failure_writes_sanitized_stop_record_and_no_selection(self):
        good = ResourceSnapshot("Darwin", 16 * GIB, 8 * GIB, 40 * GIB, 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "input.csv"
            csv_path.write_text("sequence,labels\n")
            fasta_path = root / "input.fasta"
            fasta_path.write_text(">row_0\nA\n")
            membership_path = root / "membership.tsv.gz"
            with gzip.open(membership_path, "wt") as handle:
                handle.write("sample_id\tcomponent_id\tpartition\n")
            output_dir = root / "output"
            args = SimpleNamespace(
                repo_root=ROOT,
                config=CONFIG,
                environment_manifest=root / "environment.json",
                output_dir=output_dir,
                csv=csv_path,
                dataset_audit=root / "dataset_audit.json",
                proteins=root / "proteins.tsv",
                decode_manifest=root / "decode.json",
                partition_manifest=root / "partition.json",
                membership=membership_path,
                phase_a_manifest=root / "phase_a.json",
            )
            fake_evidence = {"path": "synthetic", "byte_size": 1, "sha256": "a" * 64}
            with mock.patch(
                "rbpbench.rescnn.runner_004a2._require_clean_worktree"
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2._bound_source_evidence",
                return_value={"sha256": "b" * 64, "files": []},
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2._verify_environment",
                return_value=({}, "c" * 64),
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2.configure_exact_threads",
                return_value={"numerical_threads": 4},
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2.configure_strict_float32",
                return_value={"deterministic_algorithms": True},
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2.torch.cuda.is_available", return_value=False,
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2.local_resource_snapshot", return_value=good,
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2._input_evidence", return_value=fake_evidence,
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2._verify_phase_a_bounds",
                return_value=fake_evidence,
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2.resolve_fasta_500", return_value=fasta_path,
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2._source_commit", return_value="d" * 40,
            ), mock.patch(
                "rbpbench.rescnn.runner_004a2.audit_streams",
                side_effect=ResCNN004A2DataError("lockstep ID mismatch at row_0"),
            ):
                with self.assertRaisesRegex(ResCNN004A2DataError, "lockstep ID mismatch"):
                    execute(args)

            stopped = json.loads((output_dir / "STOPPED.json").read_text())
            self.assertEqual(stopped["status"], "STOPPED")
            self.assertEqual(stopped["stage"], "gate_a_audit")
            self.assertEqual(stopped["error"]["class"], "ResCNN004A2DataError")
            self.assertFalse(stopped["test_accessed"])
            self.assertFalse(stopped["selection_record_written"])
            self.assertFalse((output_dir / "selected" / "local_data_contract_smoke.json").exists())
            self.assertFalse(any((output_dir / "generations").glob("*")))

    def test_cli_requires_every_bound_manifest(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])


if __name__ == "__main__":
    unittest.main()
