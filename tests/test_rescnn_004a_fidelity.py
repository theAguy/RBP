from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest

try:
    import torch
except ModuleNotFoundError as exc:  # clean base environments do not carry the optional neural stack
    raise unittest.SkipTest("Task 004A tests require the dedicated PyTorch environment") from exc

from rbpbench.rescnn.config import ResCNNConfigError, load_config
from rbpbench.rescnn.fidelity import (
    CELL_HASHES,
    canonical_state_hash,
    load_notebook_oracles,
    require_identical_state,
)
from rbpbench.rescnn.loss import ResCNNLossError, decomposed_masked_bce, masked_bce_with_soft_neg
from rbpbench.rescnn.model import (
    CNNMultiLabelResidual,
    EXPECTED_LEARNABLE_PARAMETERS,
    count_learnable_parameters,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/models/task004a_v1.toml"
NOTEBOOK = ROOT / "intRBP ResCNN - for students.ipynb"


class ConfigTests(unittest.TestCase):
    def test_frozen_configuration_loads(self):
        config = load_config(CONFIG)
        self.assertEqual(config.window, 500)
        self.assertEqual(config.batch_size, 256)
        self.assertTrue(config.train_drop_last)
        self.assertFalse(config.validation_drop_last)
        self.assertEqual([row.config_id for row in config.loss_configs], [
            "submitted", "submitted_no_unknown", "joint_standard",
        ])
        self.assertEqual(config.architecture["learnable_parameter_count"], 9_029_562)
        self.assertEqual(config.architecture["batch_norm_epsilon"], 1e-5)
        self.assertEqual(config.label_contract["unsigned_token"], "known_positive")
        self.assertEqual(config.input_encoding["channel_order"], ["A", "C", "G", "T"])

    def test_scientific_drift_is_rejected(self):
        source = CONFIG.read_text()
        replacements = (
            ("window = 500", "window = 251"),
            ("train_drop_last = true", "train_drop_last = false"),
            ("positive_multiplier = 15.0", "positive_multiplier = 2.0"),
            ("cudnn_allow_tf32 = false", "cudnn_allow_tf32 = true"),
            ("batch_norm_epsilon = 1e-5", "batch_norm_epsilon = 1e-4"),
        )
        for old, new in replacements:
            with self.subTest(new=new), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.toml"
                path.write_text(source.replace(old, new, 1))
                with self.assertRaises(ResCNNConfigError):
                    load_config(path)

    def test_unknown_loss_config_key_is_rejected(self):
        source = CONFIG.read_text().replace(
            'config_id = "submitted"',
            'config_id = "submitted"\nunreviewed_override = true',
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(source)
            with self.assertRaisesRegex(ResCNNConfigError, "loss_configs"):
                load_config(path)


class NotebookFidelityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.oracles = load_notebook_oracles(NOTEBOOK)

    def test_notebook_cells_and_hyperparameters_are_directly_bound(self):
        self.assertEqual(self.oracles.cell_hashes, CELL_HASHES)
        self.assertEqual(self.oracles.hyperparameters, {
            "num_epochs": 30, "batch_size": 256, "lr": 1e-3,
            "kfolds": 5, "lambda_unknown": 1, "lambda_pos": 15,
        })

    def test_exact_parameter_count_and_output_shape(self):
        model = CNNMultiLabelResidual(122)
        self.assertEqual(count_learnable_parameters(model), EXPECTED_LEARNABLE_PARAMETERS)
        model.eval()
        output = model(torch.zeros(2, 500, 4))
        self.assertEqual(tuple(output.shape), (2, 122))
        with self.assertRaisesRegex(ValueError, "expected input"):
            model(torch.zeros(2, 251, 4))

    def test_version_sensitive_layer_defaults_are_explicit_and_frozen(self):
        model = CNNMultiLabelResidual(122)
        first = model.encoder[0]
        self.assertEqual(first.conv1.stride, (1,))
        self.assertEqual(first.conv1.dilation, (1,))
        self.assertEqual(first.conv1.groups, 1)
        self.assertIsNotNone(first.conv1.bias)
        self.assertEqual(first.bn1.eps, 1e-5)
        self.assertEqual(first.bn1.momentum, 0.1)
        self.assertTrue(first.bn1.affine)
        self.assertTrue(first.bn1.track_running_stats)
        self.assertFalse(first.relu.inplace)
        self.assertEqual(first.pool_layer.stride, 2)
        self.assertFalse(first.pool_layer.ceil_mode)

    def test_same_seed_default_initialization_is_identical_to_extracted_oracle(self):
        torch.manual_seed(701)
        clean = CNNMultiLabelResidual(122)
        torch.manual_seed(701)
        oracle = self.oracles.model_class(122)
        require_identical_state(clean.state_dict(), oracle.state_dict())
        self.assertEqual(canonical_state_hash(clean.state_dict()), canonical_state_hash(oracle.state_dict()))

    def test_oracle_and_clean_logits_and_gradients_match_in_train_and_eval(self):
        for training in (False, True):
            with self.subTest(training=training):
                torch.manual_seed(702)
                clean = CNNMultiLabelResidual(122)
                torch.manual_seed(999)
                oracle = self.oracles.model_class(122)
                oracle.load_state_dict(clean.state_dict())
                clean.train(training)
                oracle.train(training)
                generator = torch.Generator().manual_seed(703)
                inputs = torch.rand((2, 500, 4), generator=generator)

                torch.manual_seed(704)
                clean_output = clean(inputs.clone())
                clean_output.sum().backward()
                torch.manual_seed(704)
                oracle_output = oracle(inputs.clone())
                oracle_output.sum().backward()
                torch.testing.assert_close(clean_output, oracle_output, rtol=0.0, atol=0.0)
                for (clean_name, clean_parameter), (oracle_name, oracle_parameter) in zip(
                    clean.named_parameters(), oracle.named_parameters()
                ):
                    self.assertEqual(clean_name, oracle_name)
                    torch.testing.assert_close(clean_parameter.grad, oracle_parameter.grad, rtol=0.0, atol=0.0)
                require_identical_state(clean.state_dict(), oracle.state_dict())

    def test_training_singleton_reaches_dense_batchnorm_failure(self):
        model = CNNMultiLabelResidual(122)
        model.train()
        with self.assertRaisesRegex(ValueError, "more than 1 value per channel"):
            model(torch.zeros(1, 500, 4))


class LossFidelityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle_loss = staticmethod(load_notebook_oracles(NOTEBOOK).loss_function)

    def test_hand_calculated_zero_logit_components(self):
        outputs = torch.zeros(2, 2, requires_grad=True)
        targets = torch.tensor([[1.0, 0.0], [0.0, 0.0]])
        masks = torch.tensor([[1.0, 1.0], [0.0, 0.0]])
        result = decomposed_masked_bce(
            outputs, targets, masks, positive_multiplier=15, unknown_negative_coefficient=1,
        )
        self.assertAlmostEqual(result.known_weighted.item(), 8 * math.log(2), places=6)
        self.assertAlmostEqual(result.unknown_negative.item(), math.log(2), places=6)
        self.assertAlmostEqual(result.total.item(), 9 * math.log(2), places=6)
        self.assertEqual((result.known_count, result.unknown_count), (2, 2))
        result.total.backward()
        self.assertTrue(torch.isfinite(outputs.grad).all())

    def test_all_three_configs_match_direct_notebook_loss(self):
        generator = torch.Generator().manual_seed(801)
        outputs = torch.randn(4, 7, generator=generator, requires_grad=True)
        targets = torch.randint(0, 2, (4, 7), generator=generator).float()
        masks = torch.randint(0, 2, (4, 7), generator=generator).float()
        masks[0, 0] = 1
        masks[0, 1] = 0
        for positive, unknown in ((15, 1), (15, 0), (1, 0)):
            with self.subTest(positive=positive, unknown=unknown):
                clean = masked_bce_with_soft_neg(outputs, targets, masks, unknown, positive)
                oracle = self.oracle_loss(outputs, targets, masks, unknown, positive)
                torch.testing.assert_close(clean, oracle, rtol=0.0, atol=0.0)

    def test_unknown_coefficient_zero_changes_only_total_contribution(self):
        outputs = torch.tensor([[0.2, -0.3]], requires_grad=True)
        targets = torch.tensor([[1.0, 0.0]])
        masks = torch.tensor([[1.0, 0.0]])
        with_unknown = decomposed_masked_bce(
            outputs, targets, masks, positive_multiplier=15, unknown_negative_coefficient=1,
        )
        without_unknown = decomposed_masked_bce(
            outputs, targets, masks, positive_multiplier=15, unknown_negative_coefficient=0,
        )
        torch.testing.assert_close(with_unknown.known_weighted, without_unknown.known_weighted)
        torch.testing.assert_close(with_unknown.unknown_negative, without_unknown.unknown_negative)
        torch.testing.assert_close(
            with_unknown.total - without_unknown.total, with_unknown.unknown_negative,
        )

    def test_invalid_shapes_binary_values_and_zero_denominators_stop(self):
        cases = (
            (torch.zeros(1, 2), torch.zeros(1, 3), torch.zeros(1, 2)),
            (torch.zeros(1, 2), torch.tensor([[2.0, 0.0]]), torch.tensor([[1.0, 0.0]])),
            (torch.zeros(1, 2), torch.zeros(1, 2), torch.zeros(1, 2)),
            (torch.zeros(1, 2), torch.zeros(1, 2), torch.ones(1, 2)),
        )
        for outputs, targets, masks in cases:
            with self.subTest(targets=targets, masks=masks), self.assertRaises(ResCNNLossError):
                decomposed_masked_bce(
                    outputs, targets, masks, positive_multiplier=15, unknown_negative_coefficient=1,
                )

    def test_batch_size_variation_matches_oracle(self):
        for batch_size in (1, 3, 9):
            with self.subTest(batch_size=batch_size):
                generator = torch.Generator().manual_seed(802 + batch_size)
                outputs = torch.randn(batch_size, 5, generator=generator)
                targets = torch.randint(0, 2, (batch_size, 5), generator=generator).float()
                masks = torch.randint(0, 2, (batch_size, 5), generator=generator).float()
                masks[0, 0] = 1
                masks[0, 1] = 0
                clean = masked_bce_with_soft_neg(outputs, targets, masks, 1, 15)
                oracle = self.oracle_loss(outputs, targets, masks, 1, 15)
                torch.testing.assert_close(clean, oracle, rtol=0.0, atol=0.0)

    def test_nonbinary_masks_and_negative_coefficients_stop(self):
        outputs = torch.zeros(1, 3)
        targets = torch.tensor([[1.0, 0.0, 0.0]])
        with self.assertRaisesRegex(ResCNNLossError, "masks must be binary"):
            decomposed_masked_bce(
                outputs,
                targets,
                torch.tensor([[1.0, 0.5, 0.0]]),
                positive_multiplier=15,
                unknown_negative_coefficient=1,
            )
        for positive, unknown in ((0, 1), (-1, 1), (15, -1)):
            with self.subTest(positive=positive, unknown=unknown), self.assertRaises(ResCNNLossError):
                decomposed_masked_bce(
                    outputs,
                    targets,
                    torch.tensor([[1.0, 1.0, 0.0]]),
                    positive_multiplier=positive,
                    unknown_negative_coefficient=unknown,
                )


if __name__ == "__main__":
    unittest.main()
