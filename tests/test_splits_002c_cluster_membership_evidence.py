"""Task 002C-2A: synthetic-fixture tests for the accepted per-width
connected-component cluster-membership evidence contract
(:mod:`rbpbench.splits.cluster_membership_evidence`,
:mod:`rbpbench.splits.legacy_cluster_evidence_manifest`), the pinned config
binding (:mod:`rbpbench.splits.config_002c`), and the runner's portable-root
confinement and current-evidence revalidation
(:mod:`rbpbench.splits.runner_002c`).

Every fixture here is tiny and synthetic; nothing opens the real dataset
CSV, the real 361,180-row accepted Task 002B return, or launches MMseqs2.
docs/tasks/002c2a_legacy_cluster_evidence.md, "Required focused tests".
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rbpbench.splits import cluster_membership_evidence as cme
from rbpbench.splits import legacy_cluster_evidence_manifest as manifest_builder
from rbpbench.splits import runner_002c as r002c
from rbpbench.splits.config_002c import (
    ClusterMembershipFileExpectation,
    LegacyClusterEvidenceConfig,
    ReturnBundleFileExpectation,
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode())


_CANONICAL_IDS = frozenset(f"row_{i}" for i in range(5))


def _write_membership(path: Path, rows: list[tuple[str, str]]) -> None:
    path.write_text("".join(f"{rep}\t{mem}\n" for rep, mem in rows))


class ClusterBoundaryReportTests(unittest.TestCase):
    """Item 1/2/9: a transitive A-B-C cluster is reported as cluster
    co-membership -- never labeled a direct A-C match -- with exact
    per-width counts and all required denominators.
    """

    def test_transitive_cluster_is_never_described_as_a_direct_match(self):
        # row_a is the representative; row_b and row_c are both members of
        # the SAME cluster, but row_a and row_c were never directly
        # compared by MMseqs2 -- only transitively, via row_b.
        membership = {"row_a": "row_a", "row_b": "row_a", "row_c": "row_a"}
        report = cme.cluster_boundary_report(
            width=500, membership=membership, holdout_ids={"row_c"}, train_ids={"row_a", "row_b"},
        )
        self.assertEqual(report["total_cluster_count"], 1)
        self.assertEqual(report["clusters_represented_in_holdout"], 1)
        self.assertEqual(report["crossing_cluster_count"], 1)
        self.assertEqual(report["train_rows_in_crossing_clusters_count"], 2)
        self.assertEqual(report["holdout_rows_in_crossing_clusters_count"], 1)
        # The report never asserts row_a/row_c were directly compared --
        # only that they co-occur in one cluster (direct or transitive).
        self.assertIn("direct or transitive", report["relationship_note"])
        self.assertNotIn("directly_edge_matched", json.dumps(report))

    def test_exact_counts_and_all_required_denominators(self):
        # Two clusters: cluster A (rep row_0) has 2 train + 1 holdout
        # (crossing); cluster B (rep row_3) is holdout-only (not crossing).
        membership = {
            "row_0": "row_0", "row_1": "row_0", "row_2": "row_0",
            "row_3": "row_3", "row_4": "row_3",
        }
        holdout_ids = {"row_2", "row_3", "row_4"}
        train_ids = {"row_0", "row_1"}
        report = cme.cluster_boundary_report(width=101, membership=membership, holdout_ids=holdout_ids, train_ids=train_ids)

        self.assertEqual(report["total_cluster_count"], 2)
        self.assertEqual(report["clusters_represented_in_holdout"], 2)  # both clusters have >=1 holdout row
        self.assertEqual(report["crossing_cluster_count"], 1)  # only cluster A crosses
        self.assertAlmostEqual(report["crossing_cluster_rate_over_holdout_clusters"], 1 / 2)
        self.assertEqual(report["train_rows_in_crossing_clusters_count"], 2)
        self.assertAlmostEqual(report["train_rows_in_crossing_clusters_rate_over_train_rows"], 2 / 2)
        self.assertEqual(report["holdout_rows_in_crossing_clusters_count"], 1)
        self.assertAlmostEqual(report["holdout_rows_in_crossing_clusters_rate_over_holdout_rows"], 1 / 3)

    def test_zero_holdout_or_train_never_divides_by_zero(self):
        report = cme.cluster_boundary_report(width=500, membership={"row_0": "row_0"}, holdout_ids=set(), train_ids={"row_0"})
        self.assertEqual(report["crossing_cluster_rate_over_holdout_clusters"], 0.0)
        self.assertEqual(report["holdout_rows_in_crossing_clusters_rate_over_holdout_rows"], 0.0)


class LoadAndVerifyClusterMembershipTests(unittest.TestCase):
    """Items 3/4: hash/size mismatch, malformed rows, duplicate/missing/
    foreign members, and foreign representatives are all hard failures.
    """

    def _write(self, tmp: Path, lines: str) -> Path:
        path = tmp / "membership.tsv"
        path.write_text(lines)
        return path

    def test_accepts_a_well_formed_membership_and_reproduces_its_summary(self):
        with TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "row_0\trow_0\nrow_0\trow_1\nrow_2\trow_2\nrow_2\trow_3\nrow_2\trow_4\n")
            sha256 = _sha256_bytes(path.read_bytes())
            size = path.stat().st_size
            membership = cme.load_and_verify_cluster_membership(
                path, expected_sha256=sha256, expected_byte_size=size, canonical_ids=_CANONICAL_IDS,
                expected_member_count=5, expected_cluster_count=2, expected_largest_cluster_size=3, label="tiny",
            )
            self.assertEqual(membership["row_3"], "row_2")

    def test_wrong_byte_size_is_rejected_before_parsing(self):
        with TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "row_0\trow_0\n")
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.load_and_verify_cluster_membership(
                    path, expected_sha256=_sha256_bytes(path.read_bytes()), expected_byte_size=999999,
                    canonical_ids=_CANONICAL_IDS, expected_member_count=1, expected_cluster_count=1,
                    expected_largest_cluster_size=1, label="tiny",
                )

    def test_wrong_sha256_is_rejected_before_parsing(self):
        with TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "row_0\trow_0\n")
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.load_and_verify_cluster_membership(
                    path, expected_sha256="0" * 64, expected_byte_size=path.stat().st_size,
                    canonical_ids=_CANONICAL_IDS, expected_member_count=1, expected_cluster_count=1,
                    expected_largest_cluster_size=1, label="tiny",
                )

    def test_malformed_row_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "row_0\trow_0\trow_extra\n")
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.load_and_verify_cluster_membership(
                    path, expected_sha256=_sha256_bytes(path.read_bytes()), expected_byte_size=path.stat().st_size,
                    canonical_ids=_CANONICAL_IDS, expected_member_count=1, expected_cluster_count=1,
                    expected_largest_cluster_size=1, label="tiny",
                )

    def test_duplicate_member_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "row_0\trow_0\nrow_0\trow_1\nrow_0\trow_1\n")
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.load_and_verify_cluster_membership(
                    path, expected_sha256=_sha256_bytes(path.read_bytes()), expected_byte_size=path.stat().st_size,
                    canonical_ids=_CANONICAL_IDS, expected_member_count=2, expected_cluster_count=1,
                    expected_largest_cluster_size=2, label="tiny",
                )

    def test_missing_canonical_member_is_rejected(self):
        with TemporaryDirectory() as tmp:
            # Only 4 of the 5 canonical row_0..row_4 IDs appear.
            path = self._write(Path(tmp), "row_0\trow_0\nrow_0\trow_1\nrow_0\trow_2\nrow_0\trow_3\n")
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.load_and_verify_cluster_membership(
                    path, expected_sha256=_sha256_bytes(path.read_bytes()), expected_byte_size=path.stat().st_size,
                    canonical_ids=_CANONICAL_IDS, expected_member_count=4, expected_cluster_count=1,
                    expected_largest_cluster_size=4, label="tiny",
                )

    def test_foreign_member_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write(
                Path(tmp), "row_0\trow_0\nrow_0\trow_1\nrow_0\trow_2\nrow_0\trow_3\nrow_0\trow_99999\n"
            )
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.load_and_verify_cluster_membership(
                    path, expected_sha256=_sha256_bytes(path.read_bytes()), expected_byte_size=path.stat().st_size,
                    canonical_ids=_CANONICAL_IDS, expected_member_count=5, expected_cluster_count=1,
                    expected_largest_cluster_size=5, label="tiny",
                )

    def test_foreign_representative_is_rejected(self):
        with TemporaryDirectory() as tmp:
            # Every MEMBER is canonical, but the representative is foreign
            # -- MMseqs2 always chooses a representative from within the
            # same input database, so this can only mean a corrupted or
            # cross-generation TSV.
            path = self._write(
                Path(tmp),
                "row_99999\trow_0\nrow_99999\trow_1\nrow_99999\trow_2\nrow_99999\trow_3\nrow_99999\trow_4\n",
            )
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.load_and_verify_cluster_membership(
                    path, expected_sha256=_sha256_bytes(path.read_bytes()), expected_byte_size=path.stat().st_size,
                    canonical_ids=_CANONICAL_IDS, expected_member_count=5, expected_cluster_count=1,
                    expected_largest_cluster_size=5, label="tiny",
                )

    def test_wrong_accepted_cluster_count_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "row_0\trow_0\nrow_1\trow_1\nrow_2\trow_2\nrow_3\trow_3\nrow_4\trow_4\n")
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.load_and_verify_cluster_membership(
                    path, expected_sha256=_sha256_bytes(path.read_bytes()), expected_byte_size=path.stat().st_size,
                    canonical_ids=_CANONICAL_IDS, expected_member_count=5, expected_cluster_count=1,  # wrong: actually 5
                    expected_largest_cluster_size=1, label="tiny",
                )


class VerifySelectedRecordTests(unittest.TestCase):
    """Item 5: a selected record must declare the expected width,
    ``stage`` == ``"cluster"``, ``executed`` is ``True``, the expected
    sample count and generation digest, and the SAME pinned membership
    hash/size in its own artifacts inventory.
    """

    def _write_record(self, tmp: Path, **overrides) -> Path:
        record = {
            "stage": "cluster", "executed": True, "width": 500, "sample_count": 5,
            "generation_digest": "gen-500",
            "artifacts": [{"path": "membership.tsv", "sha256": "m" * 64, "size": 123}],
        }
        record.update(overrides)
        path = tmp / "record.json"
        path.write_text(json.dumps(record))
        return path

    def _verify(self, path: Path, **kw):
        defaults = dict(
            expected_sha256=_sha256_bytes(path.read_bytes()), expected_byte_size=path.stat().st_size,
            expected_width=500, expected_generation_digest="gen-500", expected_member_count=5,
            membership_sha256="m" * 64, membership_byte_size=123, label="tiny record",
        )
        defaults.update(kw)
        return cme.verify_selected_record(path, **defaults)

    def test_accepts_a_well_formed_record(self):
        with TemporaryDirectory() as tmp:
            path = self._write_record(Path(tmp))
            record = self._verify(path)
            self.assertEqual(record["width"], 500)

    def test_wrong_stage_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_record(Path(tmp), stage="probe")
            with self.assertRaises(cme.ClusterEvidenceError):
                self._verify(path)

    def test_not_executed_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_record(Path(tmp), executed=False)
            with self.assertRaises(cme.ClusterEvidenceError):
                self._verify(path)

    def test_wrong_width_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_record(Path(tmp), width=251)
            with self.assertRaises(cme.ClusterEvidenceError):
                self._verify(path)

    def test_wrong_sample_count_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_record(Path(tmp), sample_count=999)
            with self.assertRaises(cme.ClusterEvidenceError):
                self._verify(path)

    def test_wrong_generation_digest_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_record(Path(tmp), generation_digest="other-gen")
            with self.assertRaises(cme.ClusterEvidenceError):
                self._verify(path)

    def test_mismatched_membership_inventory_hash_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_record(
                Path(tmp), artifacts=[{"path": "membership.tsv", "sha256": "x" * 64, "size": 123}]
            )
            with self.assertRaises(cme.ClusterEvidenceError):
                self._verify(path)

    def test_mismatched_membership_inventory_size_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_record(
                Path(tmp), artifacts=[{"path": "membership.tsv", "sha256": "m" * 64, "size": 999}]
            )
            with self.assertRaises(cme.ClusterEvidenceError):
                self._verify(path)

    def test_missing_membership_artifact_entry_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = self._write_record(Path(tmp), artifacts=[{"path": "other.txt", "sha256": "m" * 64, "size": 1}])
            with self.assertRaises(cme.ClusterEvidenceError):
                self._verify(path)


class PortableRootConfinementTests(unittest.TestCase):
    """Item 7: the evidence root must accept only pinned children beneath
    it -- a ``..`` traversal or a symlink escaping the root is refused,
    never silently followed.
    """

    def test_pinned_child_resolves_inside_the_root(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "RETURN_MANIFEST.json").write_text("{}")
            resolved = r002c._resolve_pinned_child(root, "RETURN_MANIFEST.json", label="manifest")
            self.assertEqual(resolved, (root / "RETURN_MANIFEST.json").resolve())

    def test_traversal_outside_the_root_is_refused(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence_root"
            root.mkdir()
            (Path(tmp) / "secret.json").write_text("{}")
            with self.assertRaises(r002c.InputValidationError):
                r002c._resolve_pinned_child(root, "../secret.json", label="manifest")

    def test_symlink_escape_is_refused(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence_root"
            root.mkdir()
            outside = Path(tmp) / "outside.json"
            outside.write_text("{}")
            symlink_path = root / "escape.json"
            try:
                symlink_path.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported on this filesystem")
            with self.assertRaises(r002c.InputValidationError):
                r002c._resolve_pinned_child(root, "escape.json", label="manifest")

    def test_the_manifest_builder_applies_the_same_confinement(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence_root"
            root.mkdir()
            with self.assertRaises(cme.ClusterEvidenceError):
                manifest_builder._resolve_pinned_child(root, "../outside.json", label="manifest")


class SanitizedManifestTests(unittest.TestCase):
    """Item 8: the sanitized manifest is deterministic and contains no
    row-level IDs, cluster memberships, sequences, labels, or absolute
    collaborator path.
    """

    def _build_tiny_config_and_root(self, tmp: Path):
        root = tmp / "cluster_evidence_root"
        (root / "memberships").mkdir(parents=True)
        (root / "selected_records").mkdir(parents=True)

        return_manifest_path = root / "RETURN_MANIFEST.json"
        return_manifest_path.write_text(json.dumps({"tiny": "manifest"}))
        return_inventory_path = root / "RETURN_INVENTORY.json"
        return_inventory_path.write_text(json.dumps({"tiny": "inventory"}))

        cluster_membership = {}
        for width in (500, 251, 101):
            membership_path = root / "memberships" / f"cluster_{width}.membership.tsv"
            _write_membership(membership_path, [(f"row_{i}", f"row_{i}") for i in range(5)])
            membership_sha = _sha256_bytes(membership_path.read_bytes())
            membership_size = membership_path.stat().st_size

            record_path = root / "selected_records" / f"cluster_{width}.json"
            record_path.write_text(json.dumps({
                "stage": "cluster", "executed": True, "width": width, "sample_count": 5,
                "generation_digest": f"gen-{width}",
                "artifacts": [{"path": "membership.tsv", "sha256": membership_sha, "size": membership_size}],
                "tool_provenance": [
                    {
                        "tool": "mmseqs_cluster",
                        "command_text": (
                            f"/Users/collaborator/abs/mmseqs cluster /abs/db /abs/clu /abs/tmp "
                            f"--min-seq-id 0.90 -c 0.80 --threads 4"
                        ),
                    },
                ],
            }))

            cluster_membership[width] = ClusterMembershipFileExpectation(
                membership_relative_path=f"memberships/cluster_{width}.membership.tsv",
                membership_byte_size=membership_size, membership_sha256=membership_sha,
                selected_record_relative_path=f"selected_records/cluster_{width}.json",
                selected_record_byte_size=record_path.stat().st_size,
                selected_record_sha256=_sha256_bytes(record_path.read_bytes()),
                expected_generation_digest=f"gen-{width}", expected_member_count=5, expected_cluster_count=5,
                expected_largest_cluster_size=1, evidence_kind="connected_component_membership",
            )

        legacy_edges = LegacyClusterEvidenceConfig(
            return_manifest=ReturnBundleFileExpectation(
                relative_path="RETURN_MANIFEST.json", byte_size=return_manifest_path.stat().st_size,
                sha256=_sha256_bytes(return_manifest_path.read_bytes()),
            ),
            return_inventory=ReturnBundleFileExpectation(
                relative_path="RETURN_INVENTORY.json", byte_size=return_inventory_path.stat().st_size,
                sha256=_sha256_bytes(return_inventory_path.read_bytes()),
            ),
            cluster_membership=cluster_membership,
        )

        from rbpbench.splits.config_002c import load_config_002c

        full_config_path = Path(__file__).resolve().parent.parent / "configs" / "splits" / "sequence_partitions_002c_v1.toml"
        base_config = load_config_002c(full_config_path)
        tiny_config = dataclasses.replace(
            base_config, protected_widths=(500, 251, 101),
            dataset=dataclasses.replace(base_config.dataset, expected_row_count=5),
            legacy_edges=legacy_edges,
        )
        return tiny_config, root

    def test_manifest_has_no_row_level_or_absolute_path_content(self):
        with TemporaryDirectory() as tmp:
            config, root = self._build_tiny_config_and_root(Path(tmp))
            manifest = manifest_builder.validate_and_build_manifest(config=config, cluster_evidence_root=root)
            blob = json.dumps(manifest)
            self.assertNotIn("row_0", blob)
            self.assertNotIn("/Users/collaborator", blob)
            self.assertIn("mmseqs cluster --min-seq-id 0.90 -c 0.80 --threads 4", blob)
            for width_key in ("500", "251", "101"):
                self.assertTrue(manifest["cluster_membership_by_width"][width_key]["reconciled"])
            self.assertIn("direct or transitive", manifest["direct_edge_limitation_statement"])

    def test_manifest_is_byte_for_byte_reproducible(self):
        with TemporaryDirectory() as tmp:
            config, root = self._build_tiny_config_and_root(Path(tmp))
            first = manifest_builder.validate_and_build_manifest(config=config, cluster_evidence_root=root)
            second = manifest_builder.validate_and_build_manifest(config=config, cluster_evidence_root=root)
            self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class CurrentLegacyClusterEvidenceRevalidationTests(unittest.TestCase):
    """Item 6: a changed pinned membership/selected-record hash, size, or
    generation digest invalidates both the stage fingerprint and
    finalization's current-evidence revalidation.
    """

    def _config_with_one_width(self, *, membership_sha256: str, selected_record_sha256: str, generation_digest: str):
        entry = ClusterMembershipFileExpectation(
            membership_relative_path="memberships/cluster_500.membership.tsv", membership_byte_size=10,
            membership_sha256=membership_sha256, selected_record_relative_path="selected_records/cluster_500.json",
            selected_record_byte_size=20, selected_record_sha256=selected_record_sha256,
            expected_generation_digest=generation_digest, expected_member_count=5, expected_cluster_count=5,
            expected_largest_cluster_size=1, evidence_kind="connected_component_membership",
        )
        from rbpbench.splits.config_002c import load_config_002c

        full_config_path = Path(__file__).resolve().parent.parent / "configs" / "splits" / "sequence_partitions_002c_v1.toml"
        base_config = load_config_002c(full_config_path)
        legacy_edges = LegacyClusterEvidenceConfig(
            return_manifest=base_config.legacy_edges.return_manifest,
            return_inventory=base_config.legacy_edges.return_inventory,
            cluster_membership={500: entry},
        )
        return dataclasses.replace(base_config, protected_widths=(500,), legacy_edges=legacy_edges)

    def test_fingerprint_changes_when_a_cluster_membership_hash_changes(self):
        common = dict(
            config=self._config_with_one_width(membership_sha256="a" * 64, selected_record_sha256="b" * 64, generation_digest="gen"),
            csv_sha256="csv", assign_stage_fingerprint="asg", assign_generation_digest="asg-gen",
            decode_generation_digest="dec-gen", exact_rc_evidence={},
        )
        cluster_evidence_a = {
            "500": {
                "membership_sha256": "a" * 64, "membership_byte_size": 10, "selected_record_sha256": "b" * 64,
                "selected_record_byte_size": 20, "generation_digest": "gen",
            }
        }
        cluster_evidence_b = {
            "500": {**cluster_evidence_a["500"], "membership_sha256": "c" * 64},
        }
        fp_a = r002c.legacy_diagnostic_fingerprint(cluster_evidence=cluster_evidence_a, **common)
        fp_b = r002c.legacy_diagnostic_fingerprint(cluster_evidence=cluster_evidence_b, **common)
        self.assertNotEqual(fp_a, fp_b)

    def test_finalize_revalidation_rejects_a_stale_membership_hash(self):
        config = self._config_with_one_width(membership_sha256="a" * 64, selected_record_sha256="b" * 64, generation_digest="gen")
        legacy_record = {
            "cluster_evidence": {
                "500": {
                    "membership_sha256": "STALE", "membership_byte_size": 10, "selected_record_sha256": "b" * 64,
                    "selected_record_byte_size": 20, "generation_digest": "gen",
                }
            }
        }
        with self.assertRaises(r002c.StaleLegacyEvidenceError):
            r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record=legacy_record)

    def test_finalize_revalidation_accepts_a_current_binding(self):
        config = self._config_with_one_width(membership_sha256="a" * 64, selected_record_sha256="b" * 64, generation_digest="gen")
        legacy_record = {
            "cluster_evidence": {
                "500": {
                    "membership_sha256": "a" * 64, "membership_byte_size": 10, "selected_record_sha256": "b" * 64,
                    "selected_record_byte_size": 20, "generation_digest": "gen",
                }
            }
        }
        r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record=legacy_record)  # must not raise

    def test_finalize_revalidation_rejects_a_missing_binding(self):
        config = self._config_with_one_width(membership_sha256="a" * 64, selected_record_sha256="b" * 64, generation_digest="gen")
        with self.assertRaises(r002c.StaleLegacyEvidenceError):
            r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record={"cluster_evidence": {}})


class LegacyDiagnosticDryRunTests(unittest.TestCase):
    """Item 10: ``--dry-run`` opens no declared real input and launches no
    subprocess, even when every path argument is nonexistent/garbage.
    """

    def test_dry_run_never_touches_declared_paths(self):
        result = r002c.stage_legacy_diagnostic(
            config=None, csv_path=Path("/does/not/exist.csv"), output_dir=Path("/does/not/exist"),
            assign_record={}, exact_rc_edges_dir=Path("/does/not/exist/edges"),
            cluster_evidence_root=Path("/does/not/exist/cluster_root"),
            decode_manifest_path=Path("/does/not/exist/manifest.json"), dry_run=True,
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["stage"], "legacy_diagnostic")


if __name__ == "__main__":
    unittest.main()
