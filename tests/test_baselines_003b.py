from __future__ import annotations

import io
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from scipy.sparse import issparse

from rbpbench.baselines.access import AccessAudit, TestAccessError
from rbpbench.baselines.config import BaselineConfigError, load_config
from rbpbench.baselines.data import BaselineDataError, build_label_index, parse_labels, read_membership
from rbpbench.baselines.features import FeatureError, gc_matrix, kmer_code, kmer_matrix, read_fasta_subset, sequence_kmer_counts
from rbpbench.baselines.gc_matching import assign_bins, gc_bin_edges, matched_indices, matched_indices_with_edges
from rbpbench.baselines.metrics import MetricError, auroc, average_precision, summarize
from rbpbench.baselines.models import BaselineFitError, fit_logistic, prevalence_score, select_c
from rbpbench.baselines.output import Generation, OutputError, atomic_write, verify_selected
from rbpbench.baselines.phase_a import PhaseAError, run_phase_a
from rbpbench.baselines.phase_b import PhaseBError, run_phase_b
from rbpbench.baselines.pilot import run_pilot
from rbpbench.baselines.reproducibility import ReproducibilityError, compare_pilot_generations
from rbpbench.baselines.runner import RunnerError, main as runner_main, verify_production_inputs


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_frozen_config_loads(self):
        config = load_config(ROOT / "configs/baselines/task003b_v1.toml")
        self.assertEqual(config.windows, (500, 251, 101))
        self.assertEqual(config.development_protein_ids, (33, 53, 82, 84, 85, 86, 107, 112))
        self.assertEqual(config.c_grid, (0.01, 0.1, 1.0, 10.0))

    def test_scientific_drift_is_rejected(self):
        source = (ROOT / "configs/baselines/task003b_v1.toml").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.toml"
            path.write_text(source.replace("windows = [500, 251, 101]", "windows = [500, 150]"))
            with self.assertRaisesRegex(BaselineConfigError, "windows drift"):
                load_config(path)


class DataContractTests(unittest.TestCase):
    def test_unsigned_and_plus_positive_negative_and_unknown(self):
        self.assertEqual(parse_labels("7;+18;-3"), {7: 1, 18: 1, 3: 0})
        self.assertEqual(parse_labels(""), {})

    def test_malformed_duplicate_and_contradictory_rejected(self):
        for raw in ("0", "123", "x", "7;7", "7;-7", "1;;2"):
            with self.subTest(raw=raw), self.assertRaises(BaselineDataError):
                parse_labels(raw)

    def test_membership_requires_whole_components_and_canonical_ids(self):
        lines = io.StringIO("sample_id\tcomponent_id\tpartition\nrow_0\ta\ttrain\nrow_1\ta\tvalidation\n")
        with self.assertRaisesRegex(BaselineDataError, "split"):
            read_membership(lines, expected_rows=2)
        lines = io.StringIO("sample_id\tcomponent_id\tpartition\nrow_1\ta\ttrain\n")
        with self.assertRaisesRegex(BaselineDataError, "foreign"):
            read_membership(lines, expected_rows=1)

    def test_lexicographic_membership_is_reconciled_to_numeric_order(self):
        lines = io.StringIO(
            "sample_id\tcomponent_id\tpartition\n"
            "row_0\ta\ttrain\nrow_1\tb\tvalidation\nrow_10\tc\ttest\n"
            "row_2\td\ttrain\nrow_3\te\ttrain\nrow_4\tf\ttrain\n"
            "row_5\tg\ttrain\nrow_6\th\ttrain\nrow_7\ti\ttrain\n"
            "row_8\tj\ttrain\nrow_9\tk\ttrain\n"
        )
        rows = read_membership(lines, expected_rows=11)
        self.assertEqual([row.sample_id for row in rows], [f"row_{i}" for i in range(11)])

    def test_membership_rejects_duplicate_missing_and_foreign_ids(self):
        cases = (
            ("row_0\ta\ttrain\nrow_0\tb\ttrain\n", "duplicate"),
            ("row_0\ta\ttrain\nrow_2\tb\ttrain\n", "foreign"),
            ("row_1\ta\ttrain\n", "missing"),
        )
        for body, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(BaselineDataError, message):
                read_membership(io.StringIO("sample_id\tcomponent_id\tpartition\n" + body), expected_rows=2)

    def test_pilot_skips_test_label_before_parsing(self):
        membership = read_membership(io.StringIO(
            "sample_id\tcomponent_id\tpartition\n"
            "row_0\ta\ttrain\nrow_1\tb\tvalidation\nrow_2\tc\ttest\n"
        ), expected_rows=3)
        csv_text = "labels,sequence\n33,AAAA\n-33,CCCC\nTHIS_IS_FORBIDDEN,GGGG\n"
        index = build_label_index(io.StringIO(csv_text), membership, protein_ids=[33], allowed_partitions={"train", "validation"})
        self.assertEqual(index.labels[(33, "train")], [1])
        self.assertEqual(index.labels[(33, "validation")], [0])
        self.assertEqual(index.skipped_partition_rows["test"], 1)

    def test_unknown_is_not_negative(self):
        membership = read_membership(io.StringIO(
            "sample_id\tcomponent_id\tpartition\nrow_0\ta\ttrain\nrow_1\tb\ttrain\n"
        ), expected_rows=2)
        index = build_label_index(io.StringIO('labels\n33\n""\n'), membership, protein_ids=[33], allowed_partitions={"train"})
        self.assertEqual(index.sample_ids[(33, "train")], ["row_0"])
        self.assertEqual(index.labels[(33, "train")], [1])


class FeatureTests(unittest.TestCase):
    def test_gc_and_ordered_overlapping_kmers(self):
        self.assertEqual(gc_matrix(["ACGT", "AAAA"]).ravel().tolist(), [0.5, 0.0])
        indices, values = sequence_kmer_counts("AAAA", 3)
        self.assertEqual(indices, [kmer_code("AAA")])
        self.assertEqual(values, [1.0])
        indices, values = sequence_kmer_counts("AAAC", 3)
        self.assertEqual(sum(values), 1.0)
        self.assertEqual(set(indices), {kmer_code("AAA"), kmer_code("AAC")})

    def test_reverse_complements_are_not_collapsed(self):
        self.assertNotEqual(kmer_code("AAC"), kmer_code("GTT"))

    def test_6mer_matrix_is_sparse_and_normalized(self):
        matrix = kmer_matrix(["AAAAAA", "ACGTAC"], 6)
        self.assertTrue(issparse(matrix))
        self.assertEqual(matrix.shape, (2, 4096))
        np.testing.assert_allclose(np.asarray(matrix.sum(axis=1)).ravel(), [1.0, 1.0])

    def test_fasta_subset_reconciles_ids_and_width(self):
        result = read_fasta_subset(io.StringIO(">row_0\nAC\nGT\n>row_1\nAAAA\n"), wanted_ids={"row_0"}, width=4)
        self.assertEqual(result, {"row_0": "ACGT"})
        with self.assertRaises(FeatureError):
            read_fasta_subset(io.StringIO(">row_0\nACG\n"), wanted_ids={"row_0"}, width=4)


class MetricTests(unittest.TestCase):
    def test_exact_ties(self):
        self.assertEqual(auroc([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5]), 0.5)
        self.assertEqual(average_precision([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5]), 0.5)

    def test_perfect_and_reversed_rankings(self):
        self.assertEqual(auroc([0, 1], [0.0, 1.0]), 1.0)
        self.assertEqual(auroc([0, 1], [1.0, 0.0]), 0.0)
        self.assertEqual(average_precision([0, 1], [0.0, 1.0]), 1.0)

    def test_counts_and_undefined_metrics(self):
        result = summarize([0, 1, 1], [0.1, 0.8, 0.7])
        self.assertEqual((result["positive_count"], result["negative_count"]), (2, 1))
        with self.assertRaises(MetricError):
            summarize([1, 1], [0.1, 0.2])


class ModelTests(unittest.TestCase):
    def test_prevalence_and_converged_logistic(self):
        self.assertEqual(prevalence_score([0, 1, 1, 0]), 0.5)
        matrix = gc_matrix(["AAAA", "AAAT", "GGGC", "GGGG"])
        fit = fit_logistic(matrix, [0, 0, 1, 1], c_value=1.0, seed=20261028)
        self.assertTrue(fit.converged)
        scores = fit.scores(matrix)
        self.assertGreater(scores[-1], scores[0])

    def test_candidate_selection_excludes_any_nonconverged_fit(self):
        metrics = {
            0.01: [{"converged": True, "auroc": 0.7}, {"converged": True, "auroc": 0.7}],
            0.1: [{"converged": True, "auroc": 0.9}, {"converged": False, "auroc": 0.9}],
            1.0: [{"converged": True, "auroc": 0.7}, {"converged": True, "auroc": 0.7}],
        }
        selected, evidence = select_c(metrics)
        self.assertEqual(selected, 0.01)
        self.assertFalse(next(row for row in evidence if row["c"] == 0.1)["eligible"])

    def test_all_nonconverged_stops(self):
        with self.assertRaisesRegex(BaselineFitError, "no candidate"):
            select_c({0.1: [{"converged": False, "auroc": 0.5}]})


class GCMatchingTests(unittest.TestCase):
    def test_linear_quantiles_collapse_duplicates_and_right_closed_bins(self):
        edges = gc_bin_edges([0.0] * 5 + [0.5] * 5 + [1.0] * 5)
        np.testing.assert_allclose(edges, [0.0, 0.1, 0.5, 0.9, 1.0])
        bins = assign_bins([0.0, 0.1, 0.11, 0.5, 1.0], edges)
        np.testing.assert_array_equal(bins, [0, 0, 1, 1, 3])

    def test_matching_is_deterministic_balanced_and_subset(self):
        kwargs = dict(
            fitting_gc=[0.1, 0.2, 0.3, 0.8, 0.9],
            evaluation_gc=[0.1, 0.1, 0.2, 0.2, 0.9, 0.9, 0.9],
            labels=[0, 1, 0, 1, 0, 0, 1],
            sample_ids=[f"row_{i}" for i in range(7)],
            seed=20261028, protein_id=33, width=500,
        )
        first, edges = matched_indices(**kwargs)
        second, _ = matched_indices(**kwargs)
        np.testing.assert_array_equal(first, second)
        selected_labels = np.asarray(kwargs["labels"])[first]
        self.assertEqual(int(selected_labels.sum()), len(first) // 2)
        self.assertTrue(set(first) <= set(range(7)))

    def test_matching_can_use_phase_a_frozen_edges(self):
        selected = matched_indices_with_edges(
            edges=[0.0, 0.5, 1.0], evaluation_gc=[0.1, 0.1, 0.8, 0.8],
            labels=[0, 1, 0, 1], sample_ids=[f"row_{i}" for i in range(4)],
            seed=20261028, protein_id=1, width=500,
        )
        np.testing.assert_array_equal(selected, [0, 1, 2, 3])


class AccessAndOutputTests(unittest.TestCase):
    def test_test_access_fails_closed(self):
        audit = AccessAudit(authorize_test=False)
        audit.require(partition="validation", action="score", sample_id="row_1")
        with self.assertRaisesRegex(TestAccessError, "not authorized"):
            audit.require(partition="test", action="score", sample_id="row_2")
        self.assertFalse(audit.test_accessed)

    def test_test_access_requires_explicit_authorization(self):
        audit = AccessAudit(authorize_test=True)
        audit.require(partition="test", action="score", sample_id="row_2")
        self.assertTrue(audit.test_accessed)

    def test_generation_commit_restart_and_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with Generation(root, "pilot") as generation:
                (generation.candidate / "metrics.json").write_text("{}\n")
                final = generation.commit(fingerprint="abc", payload={"test_accessed": False})
            self.assertTrue(final.is_dir())
            self.assertIsNotNone(verify_selected(root, "pilot", fingerprint="abc"))
            self.assertIsNone(verify_selected(root, "pilot", fingerprint="other"))
            (final / "metrics.json").write_text("changed\n")
            with self.assertRaisesRegex(OutputError, "drift"):
                verify_selected(root, "pilot", fingerprint="abc")

    def test_selection_write_failure_discards_candidate_and_preserves_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected = root / "selected/pilot.json"
            selected.parent.mkdir(parents=True)
            selected.write_text("prior\n")
            with self.assertRaises(OSError):
                with Generation(root, "pilot") as generation:
                    (generation.candidate / "metrics.json").write_text("{}\n")
                    with mock.patch("rbpbench.baselines.output.os.replace", side_effect=[None, OSError("injected")]):
                        generation.commit(fingerprint="abc", payload={})
            self.assertEqual(selected.read_text(), "prior\n")

    def test_atomic_write_failure_preserves_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selected.json"
            path.write_text("prior")
            with mock.patch("rbpbench.baselines.output.os.replace", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    atomic_write(path, b"new")
            self.assertEqual(path.read_text(), "prior")


class PilotPipelineTests(unittest.TestCase):
    def _fixture(self, root: Path):
        config = load_config(ROOT / "configs/baselines/task003b_v1.toml")
        memberships = [
            (f"row_{index}", f"component_{index}", "train" if index < 4 else "validation" if index < 8 else "test")
            for index in range(9)
        ]
        membership = root / "membership.tsv.gz"
        membership.write_bytes(gzip.compress((
            "sample_id\tcomponent_id\tpartition\n" +
            "".join(f"{sample}\t{component}\t{partition}\n" for sample, component, partition in memberships)
        ).encode(), mtime=0))
        positives = ";".join(map(str, config.development_protein_ids))
        negatives = ";".join(f"-{value}" for value in config.development_protein_ids)
        labels = [positives, positives, negatives, negatives, positives, positives, negatives, negatives, "FORBIDDEN_TEST_LABEL"]
        csv_path = root / "tiny.csv"
        csv_path.write_text("labels\n" + "".join(f'"{value}"\n' for value in labels))
        fastas = {}
        patterns = ("AC", "CA", "GT", "TG", "AC", "CA", "GT", "TG", "NN")
        for width in config.windows:
            path = root / f"width_{width}.fasta"
            chunks = []
            for index, pattern in enumerate(patterns):
                sequence = (pattern * ((width + 1) // 2))[:width]
                chunks.append(f">row_{index}\n{sequence}\n")
            path.write_text("".join(chunks))
            fastas[width] = path
        return config, csv_path, membership, fastas

    def test_pilot_is_test_blind_complete_and_repeat_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, csv_path, membership, fastas = self._fixture(root)
            output = root / "output"
            first = run_pilot(config=config, csv_path=csv_path, membership_path=membership, fasta_by_width=fastas, output_root=output, expected_rows=9)
            first_files = {name: (first / name).read_bytes() for name in ("summary.json", "metrics.json", "predictions.tsv.gz")}
            second = run_pilot(config=config, csv_path=csv_path, membership_path=membership, fasta_by_width=fastas, output_root=output, expected_rows=9, force=True)
            for name, content in first_files.items():
                self.assertEqual((second / name).read_bytes(), content)
            summary = json.loads((second / "summary.json").read_text())
            self.assertFalse(summary["test_accessed"])
            self.assertEqual(summary["test_labels_parsed"], 0)
            self.assertEqual(len(summary["selected_c"]), 9)
            self.assertEqual(summary["development_sequence_count"], 8)
            self.assertGreater(summary["peak_width_feature_storage_bytes"], 0)
            self.assertEqual(set(summary["feature_storage_bytes"]), {"500", "251", "101"})
            metrics = json.loads((second / "metrics.json").read_text())
            self.assertEqual(len(metrics), 8 * 4 * 3)
            prevalence = [row for row in metrics if row["baseline"] == "prevalence"]
            self.assertTrue(all(row["auroc"] == 0.5 for row in prevalence))
            predictions = gzip.decompress((second / "predictions.tsv.gz").read_bytes()).decode()
            self.assertNotIn("row_8", predictions)
            self.assertNotIn("FORBIDDEN", predictions)

    def test_runner_final_gate_precedes_input_requirements(self):
        config = str(ROOT / "configs/baselines/task003b_v1.toml")
        with self.assertRaisesRegex(RunnerError, "requires --authorize-test"):
            runner_main(["--stage", "final", "--config", config])
        with self.assertRaisesRegex(RunnerError, "unavailable until an accepted pilot"):
            runner_main(["--stage", "final", "--config", config, "--authorize-test"])
        with self.assertRaisesRegex(RunnerError, "requires --authorize-test"):
            runner_main(["--stage", "final-phase-b", "--config", config])
        with self.assertRaisesRegex(RunnerError, "requires"):
            runner_main(["--stage", "final-phase-b", "--config", config, "--authorize-test"])
        with self.assertRaisesRegex(RunnerError, "must not receive"):
            runner_main(["--stage", "final-phase-a", "--config", config, "--authorize-test"])

    def test_dry_run_never_requires_or_opens_inputs(self):
        config = str(ROOT / "configs/baselines/task003b_v1.toml")
        self.assertEqual(runner_main(["--stage", "final", "--config", config, "--dry-run"]), 0)

    def test_production_runner_rejects_fixture_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, csv_path, membership, fastas = self._fixture(root)
            args = type("Args", (), {
                "repo_root": root, "csv": csv_path, "membership": membership,
                "fasta_500": fastas[500], "fasta_251": fastas[251], "fasta_101": fastas[101],
            })()
            for path in (root / "manifests/dataset_audit.json", root / "manifests/sequence_decode_002b2.json", root / "manifests/sequence_partitions_002c_v2.json", root / "configs/proteins.tsv"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            with self.assertRaisesRegex(RunnerError, "hash mismatch"):
                verify_production_inputs(args, config)


class ReproducibilityTests(unittest.TestCase):
    def _generation(self, root: Path, *, score: float, selected_c: float = 0.1, sample_id: str = "row_1") -> Path:
        root.mkdir()
        evidence = [{"c": 0.1, "eligible": True, "fit_count": 8, "macro_validation_auroc": 0.8}]
        summary = {
            "schema_version": "task003b_pilot_v1", "status": "complete",
            "test_accessed": False, "test_labels_parsed": 0, "test_features_built": 0,
            "protein_ids": [33], "widths": [500], "selected_c": {"3mer_500": selected_c},
            "selection_evidence": {"3mer_500": {"selected_c": selected_c, "evidence": evidence}},
            "metric_row_count": 1, "prediction_row_count": 1,
            "development_sequence_count": 2,
            "feature_storage_bytes": {"500": {"gc": 16, "3mer": 32, "6mer": 64, "total": 112}},
            "peak_width_feature_storage_bytes": 112,
        }
        metric = [{
            "protein_id": 33, "width": 500, "baseline": "3mer", "c": selected_c,
            "converged": True, "n_iter": 9, "auroc": 0.8, "average_precision": 0.7,
            "matched_auroc": 0.75, "matched_average_precision": 0.65,
            "prevalence": 0.4, "positive_count": 10, "negative_count": 12,
            "matched_count": 14, "config_hash": "a" * 64,
        }]
        (root / "summary.json").write_text(json.dumps(summary, separators=(",", ":")))
        (root / "metrics.json").write_text(json.dumps(metric, separators=(",", ":")))
        body = (
            "sample_id\tcomponent_id\tprotein_id\tfold\tpartition\tseed\twindow\tconfig_id\tconfig_hash\tlabel\tscore\n"
            f"{sample_id}\tc1\t33\tpilot\tvalidation\t1\t500\t3mer\t{'a' * 64}\t1\t{score}\n"
        )
        (root / "predictions.tsv.gz").write_bytes(gzip.compress(body.encode(), mtime=0))
        return root

    def test_numerically_equivalent_runs_pass_without_hiding_iteration_variation(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = self._generation(Path(tmp) / "primary", score=0.500000)
            repeat = self._generation(Path(tmp) / "repeat", score=0.50009)
            metrics = json.loads((repeat / "metrics.json").read_text())
            metrics[0]["n_iter"] = 10
            (repeat / "metrics.json").write_text(json.dumps(metrics, separators=(",", ":")))
            result = compare_pilot_generations(primary, repeat)
            self.assertTrue(result["passed"])
            self.assertAlmostEqual(result["max_score_difference"], 9e-5)
            self.assertEqual(result["max_iteration_difference"], 1)

    def test_scientific_decision_identity_and_score_tolerance_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._generation(root / "primary", score=0.5)
            changed_c = self._generation(root / "changed_c", score=0.5, selected_c=1.0)
            with self.assertRaisesRegex(ReproducibilityError, "selected_c"):
                compare_pilot_generations(primary, changed_c)
            changed_id = self._generation(root / "changed_id", score=0.5, sample_id="row_2")
            with self.assertRaisesRegex(ReproducibilityError, "sample_id"):
                compare_pilot_generations(primary, changed_id)
            changed_score = self._generation(root / "changed_score", score=0.5002)
            with self.assertRaisesRegex(ReproducibilityError, "score difference"):
                compare_pilot_generations(primary, changed_score)


class FinalPhaseATests(unittest.TestCase):
    def _fixture(self, root: Path, *, all_positive: bool = False):
        config = load_config(ROOT / "configs/baselines/task003b_v1.toml")
        membership = root / "membership.tsv.gz"
        membership.write_bytes(gzip.compress((
            "sample_id\tcomponent_id\tpartition\n"
            "row_0\tc0\ttrain\nrow_1\tc1\ttrain\n"
            "row_2\tc2\tvalidation\nrow_3\tc3\tvalidation\nrow_4\tc4\ttest\n"
        ).encode(), mtime=0))
        positives = ";".join(str(value) for value in range(1, 123))
        negatives = positives if all_positive else ";".join(f"-{value}" for value in range(1, 123))
        csv_path = root / "tiny.csv"
        csv_path.write_text(
            "labels\n" + "".join(f'"{value}"\n' for value in (positives, negatives, positives, negatives, "FORBIDDEN"))
        )
        fastas = {}
        for width in config.windows:
            path = root / f"width_{width}.fasta"
            path.write_text(
                f">row_0\n{('AC' * width)[:width]}\n"
                f">row_1\n{('GT' * width)[:width]}\n"
                f">row_2\n{('CA' * width)[:width]}\n"
                f">row_3\n{('TG' * width)[:width]}\n"
                f">row_4\n{'N' * width}\n"
            )
            fastas[width] = path
        selected_c = {
            f"{baseline}_{width}": 0.01
            for baseline in ("gc", "3mer", "6mer") for width in config.windows
        }
        pilot_manifest = root / "pilot.json"
        pilot_manifest.write_text(json.dumps({
            "schema_version": "task003b_pilot_acceptance_v1", "status": "accepted",
            "test_boundary": {"test_accessed": False, "final_stage_authorized": False},
            "development": {"selected_c": selected_c},
        }))
        return config, csv_path, membership, fastas, pilot_manifest

    def test_phase_a_fits_all_models_and_never_builds_test_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, csv_path, membership, fastas, pilot_manifest = self._fixture(root)
            output = root / "output"
            generation = run_phase_a(
                config=config, csv_path=csv_path, membership_path=membership,
                fasta_by_width=fastas, pilot_manifest_path=pilot_manifest,
                output_root=output, expected_rows=5,
            )
            summary = json.loads((generation / "summary.json").read_text())
            self.assertTrue(summary["all_fits_converged"])
            self.assertEqual(summary["fit_record_count"], 122 * 3 * 3)
            self.assertEqual(summary["protein_count"], 122)
            self.assertEqual(summary["fitting_sequence_count"], 4)
            self.assertFalse(summary["test_accessed"])
            self.assertEqual(summary["test_labels_parsed"], 0)
            self.assertEqual(summary["test_features_built"], 0)
            self.assertEqual(summary["test_predictions_emitted"], 0)
            self.assertTrue((generation / "model_500_6mer_coef.npy").is_file())
            self.assertTrue((generation / "gc_bin_edges.json").is_file())
            selected = json.loads((output / "selected/final_phase_a.json").read_text())
            self.assertFalse(selected["payload"]["test_accessed"])

    def test_phase_a_missing_fitting_class_fails_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, csv_path, membership, fastas, pilot_manifest = self._fixture(root, all_positive=True)
            output = root / "output"
            with self.assertRaisesRegex(PhaseAError, "lacks both fitting classes"):
                run_phase_a(
                    config=config, csv_path=csv_path, membership_path=membership,
                    fasta_by_width=fastas, pilot_manifest_path=pilot_manifest,
                    output_root=output, expected_rows=5,
                )
            self.assertFalse(output.exists())


class FinalPhaseBTests(unittest.TestCase):
    def _fixture(self, root: Path):
        config = load_config(ROOT / "configs/baselines/task003b_v1.toml")
        membership = root / "membership.tsv.gz"
        membership.write_bytes(gzip.compress((
            "sample_id\tcomponent_id\tpartition\n"
            "row_0\tc0\ttrain\nrow_1\tc1\ttrain\n"
            "row_2\tc2\tvalidation\nrow_3\tc3\tvalidation\n"
            "row_4\tc4\ttest\nrow_5\tc5\ttest\n"
        ).encode(), mtime=0))
        positives = ";".join(str(value) for value in range(1, 123))
        negatives = ";".join(f"-{value}" for value in range(1, 123))
        csv_path = root / "tiny.csv"
        csv_path.write_text(
            "labels\n" + "".join(f'"{value}"\n' for value in (
                positives, negatives, positives, negatives, positives, negatives,
            ))
        )
        # Test positives/negatives deliberately share a GC bin so the tiny
        # fixture exercises matching without relying on production-scale bin
        # occupancy.
        patterns = ("AC", "GT", "CA", "TG", "AG", "AG")
        fastas = {}
        for width in config.windows:
            path = root / f"width_{width}.fasta"
            path.write_text("".join(
                f">row_{index}\n{(pattern * ((width + 1) // 2))[:width]}\n"
                for index, pattern in enumerate(patterns)
            ))
            fastas[width] = path
        selected_c = {
            f"{baseline}_{width}": 0.01
            for baseline in ("gc", "3mer", "6mer") for width in config.windows
        }
        pilot_manifest = root / "pilot.json"
        pilot_manifest.write_text(json.dumps({
            "schema_version": "task003b_pilot_acceptance_v1", "status": "accepted",
            "test_boundary": {"test_accessed": False, "final_stage_authorized": False},
            "development": {"selected_c": selected_c},
        }))
        output = root / "output"
        phase_a_generation = run_phase_a(
            config=config, csv_path=csv_path, membership_path=membership,
            fasta_by_width=fastas, pilot_manifest_path=pilot_manifest,
            output_root=output, expected_rows=6,
        )
        selection_path = output / "selected/final_phase_a.json"
        selection = json.loads(selection_path.read_text())
        import hashlib
        phase_a_manifest = root / "phase_a_manifest.json"
        phase_a_manifest.write_text(json.dumps({
            "schema_version": "task003b_final_phase_a_acceptance_v1", "status": "accepted",
            "inputs": {"pilot_manifest": {
                "path": str(pilot_manifest),
                "sha256": hashlib.sha256(pilot_manifest.read_bytes()).hexdigest(),
            }},
            "execution": {"generation": selection["generation"]},
            "accepted_evidence": {"selection_record": {
                "byte_size": selection_path.stat().st_size,
                "sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
            }},
            "test_boundary": {"test_accessed": False, "phase_b_record_exists": False},
        }))
        partition_manifest = root / "partition_manifest.json"
        partition_manifest.write_text(json.dumps({"balance_disclosure": {
            "proteins_flagged_any_partition": 122,
            "cells_flagged_any_partition": 732,
            "proteins_flagged_validation_or_test": 122,
            "cells_flagged_validation_or_test": 488,
        }}))
        return (
            config, csv_path, membership, fastas, output, phase_a_manifest,
            partition_manifest, phase_a_generation,
        )

    def test_phase_b_scores_only_test_reconciles_predictions_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = self._fixture(Path(tmp))
            config, csv_path, membership, fastas, output, phase_a_manifest, partition_manifest, _ = values
            generation = run_phase_b(
                config=config, csv_path=csv_path, membership_path=membership,
                fasta_by_width=fastas, phase_a_manifest_path=phase_a_manifest,
                partition_manifest_path=partition_manifest, output_root=output,
                expected_rows=6, authorize_test=True,
            )
            summary = json.loads((generation / "summary.json").read_text())
            self.assertTrue(summary["test_accessed"])
            self.assertEqual(summary["models_refit_in_phase_b"], 0)
            self.assertEqual(summary["metric_row_count"], 122 * 3 * 4)
            self.assertEqual(summary["prediction_row_count"], 2 * 122 * 3 * 4)
            self.assertTrue(summary["prediction_metric_reconciliation_passed"])
            metrics = json.loads((generation / "metrics.json").read_text())
            self.assertEqual(len(metrics), 122 * 3 * 4)
            prevalence = [row for row in metrics if row["baseline"] == "prevalence"]
            self.assertTrue(all(row["auroc"] == 0.5 for row in prevalence))
            self.assertTrue(all(row["matched_positive_count"] == row["matched_negative_count"] for row in metrics))
            predictions = gzip.decompress((generation / "predictions.tsv.gz").read_bytes()).decode()
            self.assertNotIn("row_0\t", predictions)
            self.assertNotIn("row_1\t", predictions)
            self.assertNotIn("row_2\t", predictions)
            self.assertNotIn("row_3\t", predictions)
            self.assertIn("row_4\t", predictions)
            first = {name: (generation / name).read_bytes() for name in (
                "metrics.json", "aggregate_metrics.json", "predictions.tsv.gz",
            )}
            repeat = run_phase_b(
                config=config, csv_path=csv_path, membership_path=membership,
                fasta_by_width=fastas, phase_a_manifest_path=phase_a_manifest,
                partition_manifest_path=partition_manifest, output_root=output,
                expected_rows=6, authorize_test=True, force=True,
            )
            for name, content in first.items():
                self.assertEqual((repeat / name).read_bytes(), content)

    def test_phase_b_requires_authorization_before_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = self._fixture(Path(tmp))
            config, csv_path, membership, fastas, output, phase_a_manifest, partition_manifest, _ = values
            with self.assertRaisesRegex(PhaseBError, "authorization"):
                run_phase_b(
                    config=config, csv_path=csv_path, membership_path=membership,
                    fasta_by_width=fastas, phase_a_manifest_path=phase_a_manifest,
                    partition_manifest_path=partition_manifest, output_root=output,
                    expected_rows=6, authorize_test=False,
                )
            self.assertFalse((output / "selected/final_phase_b.json").exists())

    def test_phase_a_artifact_drift_stops_before_phase_b_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = self._fixture(Path(tmp))
            config, csv_path, membership, fastas, output, phase_a_manifest, partition_manifest, phase_a_generation = values
            array = phase_a_generation / "prevalence.npy"
            array.write_bytes(array.read_bytes() + b"drift")
            with self.assertRaisesRegex(OutputError, "drift"):
                run_phase_b(
                    config=config, csv_path=csv_path, membership_path=membership,
                    fasta_by_width=fastas, phase_a_manifest_path=phase_a_manifest,
                    partition_manifest_path=partition_manifest, output_root=output,
                    expected_rows=6, authorize_test=True,
                )
            self.assertFalse((output / "selected/final_phase_b.json").exists())


if __name__ == "__main__":
    unittest.main()
