"""Legacy-fold reproduction tests.

These tests exercise the ACTUAL pinned dependency stack (numpy==2.0.2,
scipy==1.16.1, scikit-learn==1.6.1, iterative-stratification==0.1.9 under
Python 3.12) and must run inside the isolated
``.venv-002c-legacy`` environment created for this handoff -- never inside
the accepted ``rbpbench-splits-002`` conda environment, which this task
must not modify and which does not carry these packages.
"""

import unittest

from rbpbench.splits.legacy_diagnostic import (
    LegacyDependencyError,
    build_leakage_diagnostic_report,
    build_positive_only_matrix,
    index_set_digest,
    require_pinned_versions,
    resolve_dependency_versions,
    run_legacy_fold,
)

# Golden fold-0 result, computed once against the exact pinned stack for the
# fixed 20-row synthetic fixture below (never re-derived at test time from
# the same code under test -- an independent frozen expectation).
_EXPECTED_TRAIN_INDICES = (0, 1, 2, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19)
_EXPECTED_HOLDOUT_INDICES = (3, 4, 5, 16)
_EXPECTED_TRAIN_DIGEST = "e5c78436493dfe8f20613ed5662a10bf7b1e91b54a1766b75495de1d3e80009d"
_EXPECTED_HOLDOUT_DIGEST = "259cdc6a32340f841037b88f8ae0e1af6cd6b24fd80dbcbbe56350db4f443cbf"


def _tiny_fixture_rows():
    rows = []
    for i in range(20):
        labels = {}
        if i % 2 == 0:
            labels[1] = 1
        else:
            labels[1] = -1
        if i % 3 == 0:
            labels[2] = 1
        rows.append(labels)
    return rows


class DependencyResolutionTests(unittest.TestCase):
    def test_pinned_stack_is_importable_in_this_environment(self):
        versions = resolve_dependency_versions()
        self.assertEqual(versions.numpy_version, "2.0.2")
        self.assertEqual(versions.scipy_version, "1.16.1")
        self.assertEqual(versions.scikit_learn_version, "1.6.1")
        self.assertEqual(versions.iterative_stratification_version, "0.1.9")
        self.assertTrue(versions.python_version.startswith("3.12"))

    def test_require_pinned_versions_accepts_a_matching_stack(self):
        versions = resolve_dependency_versions()
        require_pinned_versions(
            versions,
            expected={
                "python_version": "3.12",
                "numpy_version": "2.0.2",
                "scipy_version": "1.16.1",
                "scikit_learn_version": "1.6.1",
                "iterative_stratification_version": "0.1.9",
            },
        )  # must not raise

    def test_require_pinned_versions_rejects_a_version_mismatch(self):
        versions = resolve_dependency_versions()
        with self.assertRaises(LegacyDependencyError):
            require_pinned_versions(versions, expected={
                "python_version": "3.12",
                "numpy_version": "1.99.99",
                "scipy_version": "1.16.1",
                "scikit_learn_version": "1.6.1",
                "iterative_stratification_version": "0.1.9",
            })


class PositiveOnlyMatrixTests(unittest.TestCase):
    def test_known_negative_is_indistinguishable_from_unknown(self):
        # Reproduces the documented legacy defect exactly: targets * masks
        # only encodes +k; both -k and an absent protein become 0.
        rows = [{1: 1}, {1: -1}, {}]
        matrix = build_positive_only_matrix(rows, protein_ids=[1])
        self.assertEqual(matrix[0, 0], 1)
        self.assertEqual(matrix[1, 0], 0)
        self.assertEqual(matrix[2, 0], 0)


class IndexSetDigestTests(unittest.TestCase):
    def test_digest_is_order_independent(self):
        self.assertEqual(index_set_digest([3, 1, 2]), index_set_digest([1, 2, 3]))

    def test_digest_differs_for_different_sets(self):
        self.assertNotEqual(index_set_digest([1, 2, 3]), index_set_digest([1, 2, 4]))


class RunLegacyFoldExactReproductionTests(unittest.TestCase):
    """The core required evidence (docs/tasks/002c_partition_assignment_and_audit.md,
    "Former-split diagnostic"; handoff item 4): exact expected indices and
    digests from the pinned library, not merely counts.
    """

    def test_exact_train_and_holdout_indices_match_the_pinned_golden_result(self):
        result = run_legacy_fold(_tiny_fixture_rows(), protein_ids=[1, 2])
        self.assertEqual(result.train_indices, _EXPECTED_TRAIN_INDICES)
        self.assertEqual(result.holdout_indices, _EXPECTED_HOLDOUT_INDICES)

    def test_exact_digests_match_the_pinned_golden_result(self):
        result = run_legacy_fold(_tiny_fixture_rows(), protein_ids=[1, 2])
        self.assertEqual(result.train_digest, _EXPECTED_TRAIN_DIGEST)
        self.assertEqual(result.holdout_digest, _EXPECTED_HOLDOUT_DIGEST)

    def test_train_and_holdout_partition_every_row_exactly_once(self):
        result = run_legacy_fold(_tiny_fixture_rows(), protein_ids=[1, 2])
        combined = set(result.train_indices) | set(result.holdout_indices)
        self.assertEqual(combined, set(range(20)))
        self.assertEqual(len(result.train_indices) + len(result.holdout_indices), 20)
        self.assertEqual(set(result.train_indices) & set(result.holdout_indices), set())

    def test_result_records_the_exact_resolved_dependency_versions(self):
        result = run_legacy_fold(_tiny_fixture_rows(), protein_ids=[1, 2])
        self.assertEqual(result.dependency_versions.numpy_version, "2.0.2")
        self.assertEqual(result.dependency_versions.iterative_stratification_version, "0.1.9")

    def test_rerun_is_deterministic(self):
        first = run_legacy_fold(_tiny_fixture_rows(), protein_ids=[1, 2])
        second = run_legacy_fold(_tiny_fixture_rows(), protein_ids=[1, 2])
        self.assertEqual(first.train_indices, second.train_indices)
        self.assertEqual(first.holdout_indices, second.holdout_indices)


class LeakageDiagnosticReportTests(unittest.TestCase):
    def test_report_includes_every_required_count_and_denominator(self):
        result = run_legacy_fold(_tiny_fixture_rows(), protein_ids=[1, 2])
        sample_ids_by_index = [f"row_{i}" for i in range(20)]
        # Two components, each spanning both legacy train and holdout rows,
        # so a real crossing count/rate is exercised.
        sample_to_component = {}
        for i in range(20):
            sample_to_component[f"row_{i}"] = "compA" if i < 10 else "compB"
        sample_to_partition = {f"row_{i}": ("train" if i < 14 else "validation") for i in range(20)}

        # A transitive A-B-C cluster at width 500: row_0 (representative) --
        # row_1 -- row_3, all in the same connected-component cluster, but
        # row_0/row_3 were never directly aligned -- the diagnostic must
        # report cluster CO-MEMBERSHIP, never label row_0/row_3 a direct
        # match (docs/tasks/002c2a_legacy_cluster_evidence.md).
        cluster_membership_500 = {"row_0": "row_0", "row_1": "row_0", "row_3": "row_0"}
        report = build_leakage_diagnostic_report(
            legacy_result=result,
            sample_ids_by_index=sample_ids_by_index,
            sample_to_component=sample_to_component,
            sample_to_partition=sample_to_partition,
            cluster_membership_by_width={500: cluster_membership_500},
            exact_rc_edges_by_width={500: [("row_1", "row_4")]},
        )

        crossing = report["component_crossing"]
        for key in (
            "crossing_component_count", "components_represented_in_holdout",
            "crossing_component_rate_over_holdout_components", "crossing_holdout_row_count",
            "crossing_holdout_row_rate_over_holdout_rows", "crossing_train_row_count",
            "crossing_train_row_rate_over_train_rows",
        ):
            self.assertIn(key, crossing)

        self.assertNotIn("directly_edge_matched_by_width", report)
        self.assertIn("500", report["cluster_boundary_by_width"])
        boundary = report["cluster_boundary_by_width"]["500"]
        for key in (
            "total_cluster_count", "clusters_represented_in_holdout", "crossing_cluster_count",
            "crossing_cluster_rate_over_holdout_clusters", "train_rows_in_crossing_clusters_count",
            "train_rows_in_crossing_clusters_rate_over_train_rows", "holdout_rows_in_crossing_clusters_count",
            "holdout_rows_in_crossing_clusters_rate_over_holdout_rows", "relationship_note",
        ):
            self.assertIn(key, boundary)
        # row_0/row_1 are legacy-train (indices 0, 1 < 14 fold-0 train
        # membership is not guaranteed, so assert via the actual fold
        # result rather than a hard-coded split); the cluster is a crossing
        # cluster iff it has at least one member on each side.
        holdout_ids = {sample_ids_by_index[i] for i in result.holdout_indices}
        train_ids = {sample_ids_by_index[i] for i in result.train_indices}
        cluster_ids = {"row_0", "row_1", "row_3"}
        expected_crossing = bool(cluster_ids & holdout_ids) and bool(cluster_ids & train_ids)
        self.assertEqual(boundary["crossing_cluster_count"] == 1, expected_crossing)
        self.assertIn("direct or transitive", boundary["relationship_note"])

        self.assertIn("500", report["exact_rc_by_width"])
        exact_rc = report["exact_rc_by_width"]["500"]
        self.assertIn("affected_holdout_row_count", exact_rc)
        self.assertIn("affected_holdout_row_rate_over_holdout_rows", exact_rc)
        self.assertIn("raw_violating_pair_count", exact_rc)

    def test_zero_holdout_rows_never_divides_by_zero(self):
        # Degenerate but must never raise: an empty holdout produces 0.0
        # rates, not a ZeroDivisionError.
        class _FakeResult:
            train_indices = (0, 1)
            holdout_indices = ()
            train_digest = "x"
            holdout_digest = "y"

            def to_dict(self):
                return {}

        report = build_leakage_diagnostic_report(
            legacy_result=_FakeResult(),
            sample_ids_by_index=["row_0", "row_1"],
            sample_to_component={"row_0": "c1", "row_1": "c1"},
        )
        self.assertEqual(report["component_crossing"]["crossing_holdout_row_rate_over_holdout_rows"], 0.0)


if __name__ == "__main__":
    unittest.main()
