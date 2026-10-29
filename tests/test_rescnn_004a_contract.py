from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

try:
    import numpy as np
    import torch
except ModuleNotFoundError as exc:  # clean base environments do not carry the optional neural stack
    raise unittest.SkipTest("Task 004A tests require the dedicated PyTorch environment") from exc

from rbpbench.rescnn.checkpoint import (
    ResCNNCheckpointError,
    atomic_save_checkpoint,
    load_final_model_checkpoint,
)
from rbpbench.rescnn.data import (
    CompactSequenceDataset,
    DeferredRawRow,
    Membership,
    ResCNNDataError,
    assert_no_test_records,
    build_allowed_records,
    encode_sequence,
    targets_and_masks,
)
from rbpbench.rescnn.fidelity import canonical_state_hash
from rbpbench.rescnn.metrics import ResCNNMetricError, evaluate_known_outputs, summarize_protein
from rbpbench.rescnn.output import (
    PREDICTION_FIELDS,
    ResCNNOutputError,
    WholeRunGeneration,
    validate_prediction_rows,
    verify_selected,
)
from rbpbench.rescnn.reproducibility import (
    DeterminismError,
    FixedEpochBatchSampler,
    configure_strict_float32,
    derive_seed,
    epoch_order,
    require_paired_orders,
    reset_random_state,
    seed_streams,
)


class ReproducibilityTests(unittest.TestCase):
    def test_labelled_seed_streams_are_stable_and_distinct(self):
        first = seed_streams(20261029)
        second = seed_streams(20261029)
        self.assertEqual(first, second)
        self.assertEqual(len({first.initialization, first.loader, first.model_stochasticity}), 3)
        self.assertNotEqual(derive_seed(20261029, "epoch:0"), derive_seed(20261029, "epoch:1"))

    def test_remainder_one_training_drops_one_and_validation_keeps_it(self):
        training = epoch_order(257, batch_size=256, loader_seed=91, epoch=0, drop_last=True)
        validation = epoch_order(257, batch_size=256, loader_seed=91, epoch=0, drop_last=False)
        self.assertEqual([len(batch) for batch in training.batches], [256])
        self.assertEqual(len(training.dropped_indices), 1)
        self.assertEqual([len(batch) for batch in validation.batches], [256, 1])
        self.assertEqual(validation.dropped_indices, ())
        self.assertEqual(len(list(FixedEpochBatchSampler(training))), 1)

    def test_paired_configs_have_identical_orders_and_dropped_row(self):
        streams = seed_streams(20261029)
        orders = [epoch_order(257, batch_size=256, loader_seed=streams.loader, epoch=4, drop_last=True) for _ in range(3)]
        require_paired_orders(orders)
        different = epoch_order(257, batch_size=256, loader_seed=streams.loader, epoch=5, drop_last=True)
        with self.assertRaises(DeterminismError):
            require_paired_orders([orders[0], different])

    def test_reset_random_state_pairs_initialization_and_model_stochasticity(self):
        streams = seed_streams(20261029)
        reset_random_state(streams.initialization)
        first = torch.nn.Linear(5, 3).state_dict()
        reset_random_state(streams.initialization)
        second = torch.nn.Linear(5, 3).state_dict()
        self.assertEqual(canonical_state_hash(first), canonical_state_hash(second))
        reset_random_state(streams.model_stochasticity)
        first_dropout = torch.nn.functional.dropout(torch.ones(20), p=0.5, training=True)
        reset_random_state(streams.model_stochasticity)
        second_dropout = torch.nn.functional.dropout(torch.ones(20), p=0.5, training=True)
        torch.testing.assert_close(first_dropout, second_dropout, rtol=0.0, atol=0.0)

    def test_cpu_strict_float32_settings_take_effect(self):
        evidence = configure_strict_float32(require_cuda=False)
        self.assertFalse(evidence["cudnn_allow_tf32"])
        self.assertFalse(evidence["cuda_matmul_allow_tf32"])
        self.assertEqual(evidence["float32_matmul_precision"], "highest")
        self.assertTrue(evidence["deterministic_algorithms"])
        self.assertTrue(evidence["cudnn_deterministic"])
        self.assertFalse(evidence["cudnn_benchmark"])


class DataBoundaryTests(unittest.TestCase):
    def _fixture(self):
        calls = {"test_labels": 0, "test_sequence": 0}

        def forbidden(name):
            def invoke():
                calls[name] += 1
                raise AssertionError(f"forbidden supplier called: {name}")
            return invoke

        rows = (
            DeferredRawRow("row_0", lambda: "1;-2", lambda: "ACGT"),
            DeferredRawRow("row_1", lambda: "2", lambda: "TGCA"),
            DeferredRawRow("row_2", forbidden("test_labels"), forbidden("test_sequence")),
        )
        membership = {
            "row_0": Membership("row_0", "component-a", "train"),
            "row_1": Membership("row_1", "component-b", "validation"),
            "row_2": Membership("row_2", "component-c", "test"),
        }
        return rows, membership, calls

    def test_partition_gate_prevents_test_label_and_sequence_interpretation(self):
        rows, membership, calls = self._fixture()
        records, skipped = build_allowed_records(rows, membership, width=4, output_count=3)
        self.assertEqual(calls, {"test_labels": 0, "test_sequence": 0})
        self.assertEqual(skipped, {"test": 1})
        self.assertEqual([record.partition for record in records], ["train", "validation"])
        assert_no_test_records(records)

    def test_target_mask_and_one_hot_contract(self):
        targets, masks = targets_and_masks("1;-2", output_count=3)
        self.assertEqual(targets, (1.0, 0.0, 0.0))
        self.assertEqual(masks, (1.0, 1.0, 0.0))
        rows, membership, _ = self._fixture()
        records, _ = build_allowed_records(rows, membership, width=4, output_count=3)
        dataset = CompactSequenceDataset(records)
        sequence, target, mask = dataset[0]
        self.assertEqual(tuple(sequence.shape), (4, 4))
        torch.testing.assert_close(sequence, torch.eye(4), rtol=0.0, atol=0.0)
        torch.testing.assert_close(target, torch.tensor(targets))
        torch.testing.assert_close(mask, torch.tensor(masks))

    def test_invalid_sequence_labels_or_universe_stop(self):
        with self.assertRaises(ResCNNDataError):
            encode_sequence("ACGN", width=4)
        with self.assertRaises(ResCNNDataError):
            targets_and_masks("1;-1", output_count=3)
        rows, membership, _ = self._fixture()
        with self.assertRaisesRegex(ResCNNDataError, "missing"):
            build_allowed_records(rows[:-1], membership, width=4, output_count=3)


class MetricTests(unittest.TestCase):
    def test_122_outputs_are_all_eligible_and_pooled_ap_is_named_honestly(self):
        labels = np.tile(np.array([[0], [1], [0], [1]], dtype=np.float32), (1, 122))
        scores = np.tile(np.array([[0.1], [0.9], [0.2], [0.8]], dtype=np.float32), (1, 122))
        masks = np.ones_like(labels)
        rows, aggregate = evaluate_known_outputs(labels, scores, masks)
        self.assertEqual(len(rows), 122)
        self.assertEqual(aggregate["eligible_output_count"], 122)
        self.assertEqual(aggregate["technical_collapse_count"], 0)
        self.assertEqual(aggregate["macro_auroc"], 1.0)
        self.assertEqual(aggregate["pooled_known_entry_AP"], 1.0)

    def test_scheduler_metric_refuses_any_output_count_other_than_122(self):
        labels = np.array([[0, 1], [1, 0]], dtype=np.float32)
        scores = np.array([[0.1, 0.9], [0.9, 0.1]], dtype=np.float32)
        with self.assertRaisesRegex(ResCNNMetricError, "exactly 122"):
            evaluate_known_outputs(labels, scores, np.ones_like(labels))

    def test_collapse_and_saturation_are_measurable(self):
        summary = summarize_protein([0, 1, 0, 1], [1.0, 1.0, 1.0, 1.0])
        self.assertTrue(summary["technical_collapse"])
        self.assertEqual(summary["unique_score_count"], 1)
        self.assertEqual(summary["modal_score_fraction"], 1.0)
        self.assertEqual(summary["saturated_score_fraction"], 1.0)
        with self.assertRaises(ResCNNMetricError):
            summarize_protein([1, 1], [0.2, 0.3])


class OutputAndCheckpointTests(unittest.TestCase):
    def test_prediction_schema_is_validation_only_and_unique(self):
        row = dict(zip(PREDICTION_FIELDS, (
            "row_1", "component-a", 33, "components_v2_pilot", "validation",
            20261029, 500, "submitted", "a" * 64, 1, 0.75,
        )))
        self.assertEqual(validate_prediction_rows([row]), 1)
        with self.assertRaisesRegex(ResCNNOutputError, "duplicate"):
            validate_prediction_rows([row, dict(row)])
        forbidden = dict(row, partition="test")
        with self.assertRaisesRegex(ResCNNOutputError, "validation-only"):
            validate_prediction_rows([forbidden])

    def test_whole_run_commit_revalidation_and_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with WholeRunGeneration(root, "seed_20261029") as generation:
                (generation.candidate / "summary.json").write_text("{}\n")
                final = generation.commit(fingerprint="abc", payload={"test_accessed": False})
            self.assertTrue(final.is_dir())
            record = verify_selected(root, "seed_20261029", fingerprint="abc")
            self.assertFalse(record["mid_run_resume_supported"])
            self.assertIsNone(verify_selected(root, "seed_20261029", fingerprint="other"))
            (final / "summary.json").write_text("changed\n")
            with self.assertRaisesRegex(ResCNNOutputError, "drift"):
                verify_selected(root, "seed_20261029", fingerprint="abc")

    def test_nested_artifacts_are_inventoried_and_unlisted_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with WholeRunGeneration(root, "seed_20261029") as generation:
                nested = generation.candidate / "checkpoints"
                nested.mkdir()
                (nested / "epoch30.pt").write_bytes(b"trusted-checkpoint-placeholder")
                final = generation.commit(fingerprint="abc", payload={"test_accessed": False})
            record = verify_selected(root, "seed_20261029", fingerprint="abc")
            self.assertEqual(record["inventory"][0]["path"], "checkpoints/epoch30.pt")
            (final / "unlisted.txt").write_text("unexpected\n")
            with self.assertRaisesRegex(ResCNNOutputError, "inventory drift"):
                verify_selected(root, "seed_20261029", fingerprint="abc")

    def test_interrupted_candidate_is_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                with WholeRunGeneration(root, "seed_1") as generation:
                    (generation.candidate / "partial.txt").write_text("partial\n")
                    raise RuntimeError("interrupted")
            self.assertEqual(list((root / "generations").iterdir()), [])
            self.assertFalse((root / "selected/seed_1.json").exists())

    def test_atomic_final_checkpoint_round_trip_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "epoch30.pt"
            reset_random_state(44)
            model = torch.nn.Linear(4, 2)
            optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
            scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
                optimizer, mode="max", factor=0.5, patience=2,
            )
            before = canonical_state_hash(model.state_dict())
            evidence = atomic_save_checkpoint(
                path, model=model, optimizer=optimizer, scheduler=scheduler,
                epoch=30, source_sha256="a" * 64, config_sha256="b" * 64,
                environment_sha256="c" * 64, seed=20261029, config_id="submitted",
            )
            self.assertEqual(evidence["model_state_sha256"], before)
            restored = torch.nn.Linear(4, 2)
            payload = load_final_model_checkpoint(
                path,
                model=restored,
                expected_epoch=30,
                expected_identity={
                    "source_sha256": "a" * 64,
                    "config_sha256": "b" * 64,
                    "environment_sha256": "c" * 64,
                    "seed": 20261029,
                    "config_id": "submitted",
                },
            )
            self.assertFalse(payload["mid_run_resume_supported"])
            self.assertEqual(canonical_state_hash(restored.state_dict()), before)
            with self.assertRaisesRegex(ResCNNCheckpointError, "final epoch"):
                load_final_model_checkpoint(
                    path, model=restored, expected_epoch=29,
                    expected_identity={"seed": 20261029},
                )


if __name__ == "__main__":
    unittest.main()
