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
from rbpbench.baselines.gc_matching import assign_bins, gc_bin_edges, matched_indices
from rbpbench.baselines.metrics import MetricError, auroc, average_precision, summarize
from rbpbench.baselines.models import BaselineFitError, fit_logistic, prevalence_score, select_c
from rbpbench.baselines.output import Generation, OutputError, atomic_write, verify_selected
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


if __name__ == "__main__":
    unittest.main()
