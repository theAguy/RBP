from __future__ import annotations

from dataclasses import replace
from pathlib import Path
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
from rbpbench.rescnn.data_004a2 import CacheRecord, CompactSampleCache, canonical_content_sha256
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
    ResCNN004A2RunnerError,
    build_parser,
    execute,
    resolve_fasta_500,
)
from rbpbench.rescnn.smoke_004a2 import run_paired_smoke, scientific_signature


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/models/task004a_v1.toml"


class TinyDropoutModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.dropout = torch.nn.Dropout(0.2)
        self.linear = torch.nn.Linear(500 * 4, 122)

    def forward(self, values):
        return self.linear(self.dropout(values.flatten(1)))


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


class RunnerBoundaryTests(unittest.TestCase):
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

    def test_cli_requires_every_bound_manifest(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])


if __name__ == "__main__":
    unittest.main()
