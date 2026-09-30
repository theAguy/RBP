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


def _build_tiny_cluster_evidence_root_and_config(
    tmp: Path, *, widths: tuple[int, ...] = (500, 251, 101), sample_count: int = 5,
):
    """Builds a tiny, schema-correct synthetic Task 002B return bundle and a
    matching config binding: ``RETURN_MANIFEST.json``'s ``selected_stages``/
    ``membership_summary`` shape and ``RETURN_INVENTORY.json``'s flat
    list-of-``{path,byte_size,sha256}``-entries shape mirror the real
    accepted return exactly (correction review C2 -- an outer-hash-only
    placeholder like ``{"tiny": "manifest"}`` can no longer satisfy the
    shared verifier's semantic cross-check). Returns ``(config,
    cluster_evidence_root, evidence_by_width)``, where ``evidence_by_width``
    exposes each width's real file paths/hashes/sizes/generation digest for
    mutation-based regressions.
    """
    root = tmp / "cluster_evidence_root"
    (root / "memberships").mkdir(parents=True)
    (root / "selected_records").mkdir(parents=True)

    cluster_membership: dict[int, ClusterMembershipFileExpectation] = {}
    selected_stages: dict[str, dict] = {}
    inventory_entries: list[dict] = []
    evidence_by_width: dict[int, dict] = {}

    for width in widths:
        membership_relative_path = f"memberships/cluster_{width}.membership.tsv"
        membership_path = root / membership_relative_path
        _write_membership(membership_path, [(f"row_{i}", f"row_{i}") for i in range(sample_count)])
        membership_sha = _sha256_bytes(membership_path.read_bytes())
        membership_size = membership_path.stat().st_size

        generation_digest = f"gen-{width}"
        selected_record_relative_path = f"selected_records/cluster_{width}.json"
        record_path = root / selected_record_relative_path
        record_path.write_text(json.dumps({
            "stage": "cluster", "executed": True, "width": width, "sample_count": sample_count,
            "generation_digest": generation_digest,
            "artifacts": [{"path": "membership.tsv", "sha256": membership_sha, "size": membership_size}],
            "tool_provenance": [
                {
                    "tool": "mmseqs_cluster",
                    "command_text": (
                        "/Users/collaborator/abs/mmseqs cluster /abs/db /abs/clu /abs/tmp "
                        "--min-seq-id 0.90 -c 0.80 --threads 4"
                    ),
                },
            ],
        }))
        selected_record_sha = _sha256_bytes(record_path.read_bytes())
        selected_record_size = record_path.stat().st_size

        cluster_membership[width] = ClusterMembershipFileExpectation(
            membership_relative_path=membership_relative_path, membership_byte_size=membership_size,
            membership_sha256=membership_sha, selected_record_relative_path=selected_record_relative_path,
            selected_record_byte_size=selected_record_size, selected_record_sha256=selected_record_sha,
            expected_generation_digest=generation_digest, expected_member_count=sample_count,
            expected_cluster_count=sample_count, expected_largest_cluster_size=1,
            evidence_kind="connected_component_membership",
        )
        selected_stages[f"cluster_{width}"] = {
            "stage": "cluster", "executed": True, "width": width, "generation_digest": generation_digest,
            "returned_membership_path": membership_relative_path,
            "membership_summary": {
                "member_count": sample_count, "cluster_count": sample_count, "largest_cluster_size": 1,
            },
        }
        inventory_entries.append(
            {"path": membership_relative_path, "byte_size": membership_size, "sha256": membership_sha}
        )
        inventory_entries.append(
            {"path": selected_record_relative_path, "byte_size": selected_record_size, "sha256": selected_record_sha}
        )
        evidence_by_width[width] = {
            "membership_path": membership_path, "selected_record_path": record_path,
            "membership_sha256": membership_sha, "membership_byte_size": membership_size,
            "selected_record_sha256": selected_record_sha, "selected_record_byte_size": selected_record_size,
            "generation_digest": generation_digest,
        }

    return_manifest_path = root / "RETURN_MANIFEST.json"
    return_manifest_path.write_text(json.dumps({"selected_stages": selected_stages}))
    return_inventory_path = root / "RETURN_INVENTORY.json"
    return_inventory_path.write_text(json.dumps(inventory_entries))

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
    config = dataclasses.replace(
        base_config, protected_widths=tuple(widths),
        dataset=dataclasses.replace(base_config.dataset, expected_row_count=sample_count),
        legacy_edges=legacy_edges,
    )
    return config, root, evidence_by_width


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
        config, root, _evidence_by_width = _build_tiny_cluster_evidence_root_and_config(tmp)
        return config, root

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
    """Item 6 / correction review C1: finalization's current-evidence
    revalidation re-hashes the LIVE cluster-evidence files at the exact
    portable return root the accepted ``legacy_diagnostic`` record itself
    recorded (:func:`rbpbench.splits.cluster_membership_evidence.verify_live_cluster_evidence`)
    -- neither a live file mutated after acceptance (config unchanged) nor a
    config edit made after acceptance (live files unchanged) can leave
    ``finalize`` apparently current. Configured expected strings alone are
    never proof of live currency.
    """

    def _accept(self, config, root, evidence_by_width) -> dict:
        """Builds a ``legacy_diagnostic``-shaped accepted record exactly as
        :func:`rbpbench.splits.runner_002c.stage_legacy_diagnostic` would,
        by running the SAME shared verifier the real stage uses.
        """
        live = cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)
        return {
            "cluster_evidence_root": str(root.resolve()),
            "cluster_evidence": live["cluster_evidence"],
            "return_metadata_evidence": {
                "return_manifest_sha256": live["return_manifest_sha256"],
                "return_manifest_byte_size": live["return_manifest_byte_size"],
                "return_inventory_sha256": live["return_inventory_sha256"],
                "return_inventory_byte_size": live["return_inventory_byte_size"],
            },
        }

    def test_fingerprint_changes_when_a_cluster_membership_hash_changes(self):
        from rbpbench.splits.config_002c import load_config_002c

        full_config_path = Path(__file__).resolve().parent.parent / "configs" / "splits" / "sequence_partitions_002c_v1.toml"
        common = dict(
            config=load_config_002c(full_config_path), csv_sha256="csv", assign_stage_fingerprint="asg",
            assign_generation_digest="asg-gen", decode_generation_digest="dec-gen", exact_rc_evidence={},
            return_metadata_evidence={
                "return_manifest_sha256": "rm", "return_manifest_byte_size": 1,
                "return_inventory_sha256": "ri", "return_inventory_byte_size": 2,
            },
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

    def test_fingerprint_changes_when_return_metadata_changes(self):
        """Correction review C1: the two small return-metadata files were
        previously absent from the fingerprint entirely.
        """
        from rbpbench.splits.config_002c import load_config_002c

        full_config_path = Path(__file__).resolve().parent.parent / "configs" / "splits" / "sequence_partitions_002c_v1.toml"
        common = dict(
            config=load_config_002c(full_config_path), csv_sha256="csv", assign_stage_fingerprint="asg",
            assign_generation_digest="asg-gen", decode_generation_digest="dec-gen", exact_rc_evidence={},
            cluster_evidence={},
        )
        fp_a = r002c.legacy_diagnostic_fingerprint(
            return_metadata_evidence={
                "return_manifest_sha256": "rm-a", "return_manifest_byte_size": 1,
                "return_inventory_sha256": "ri", "return_inventory_byte_size": 2,
            },
            **common,
        )
        fp_b = r002c.legacy_diagnostic_fingerprint(
            return_metadata_evidence={
                "return_manifest_sha256": "rm-b", "return_manifest_byte_size": 1,
                "return_inventory_sha256": "ri", "return_inventory_byte_size": 2,
            },
            **common,
        )
        self.assertNotEqual(fp_a, fp_b)

    def test_finalize_revalidation_accepts_a_current_binding(self):
        with TemporaryDirectory() as tmp:
            config, root, evidence_by_width = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            legacy_record = self._accept(config, root, evidence_by_width)
            r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record=legacy_record)  # must not raise

    def test_finalize_revalidation_rejects_a_missing_cluster_evidence_root(self):
        with TemporaryDirectory() as tmp:
            config, root, evidence_by_width = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            legacy_record = self._accept(config, root, evidence_by_width)
            del legacy_record["cluster_evidence_root"]
            with self.assertRaises(r002c.StaleLegacyEvidenceError):
                r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record=legacy_record)

    def test_finalize_revalidation_rejects_a_missing_binding(self):
        with TemporaryDirectory() as tmp:
            config, root, evidence_by_width = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            legacy_record = self._accept(config, root, evidence_by_width)
            legacy_record["cluster_evidence"] = {}
            with self.assertRaises(r002c.StaleLegacyEvidenceError):
                r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record=legacy_record)

    def test_finalize_revalidation_rejects_a_live_membership_mutation(self):
        """C1 regression: first accept, then mutate the LIVE membership TSV
        without re-pinning config -- finalize must refuse, never trust the
        unchanged configured expectation.
        """
        with TemporaryDirectory() as tmp:
            config, root, evidence_by_width = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            legacy_record = self._accept(config, root, evidence_by_width)

            membership_path = evidence_by_width[500]["membership_path"]
            membership_path.write_text(membership_path.read_text() + "row_extra\trow_extra\n")

            with self.assertRaises(r002c.StaleLegacyEvidenceError):
                r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record=legacy_record)

    def test_finalize_revalidation_rejects_a_live_selected_record_mutation(self):
        with TemporaryDirectory() as tmp:
            config, root, evidence_by_width = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            legacy_record = self._accept(config, root, evidence_by_width)

            selected_record_path = evidence_by_width[251]["selected_record_path"]
            selected_record_path.write_text(selected_record_path.read_text() + " ")

            with self.assertRaises(r002c.StaleLegacyEvidenceError):
                r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record=legacy_record)

    def test_finalize_revalidation_rejects_a_live_return_manifest_mutation(self):
        with TemporaryDirectory() as tmp:
            config, root, evidence_by_width = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            legacy_record = self._accept(config, root, evidence_by_width)

            return_manifest_path = root / "RETURN_MANIFEST.json"
            return_manifest_path.write_text(return_manifest_path.read_text() + " ")

            with self.assertRaises(r002c.StaleLegacyEvidenceError):
                r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record=legacy_record)

    def test_finalize_revalidation_rejects_a_live_return_inventory_mutation(self):
        with TemporaryDirectory() as tmp:
            config, root, evidence_by_width = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            legacy_record = self._accept(config, root, evidence_by_width)

            return_inventory_path = root / "RETURN_INVENTORY.json"
            return_inventory_path.write_text(return_inventory_path.read_text() + " ")

            with self.assertRaises(r002c.StaleLegacyEvidenceError):
                r002c._verify_current_legacy_cluster_evidence(config=config, legacy_record=legacy_record)

    def test_finalize_revalidation_rejects_a_stale_recorded_binding_after_config_re_pin(self):
        """The other direction: config is edited (and correctly re-pinned)
        to a NEW live membership after acceptance, but the accepted record
        still holds the OLD binding -- configured expected strings alone
        (which now agree with the NEW live file) are never proof that the
        ACCEPTED record itself is still current.
        """
        with TemporaryDirectory() as tmp:
            config, root, evidence_by_width = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            legacy_record = self._accept(config, root, evidence_by_width)

            # Re-cluster width 101 within the SAME canonical universe: merge
            # row_1 into row_0's cluster (member count unchanged at 5;
            # cluster count drops 5 -> 4; largest cluster grows 1 -> 2).
            membership_path = evidence_by_width[101]["membership_path"]
            _write_membership(
                membership_path,
                [("row_0", "row_0"), ("row_0", "row_1"), ("row_2", "row_2"), ("row_3", "row_3"), ("row_4", "row_4")],
            )
            new_sha = _sha256_bytes(membership_path.read_bytes())
            new_size = membership_path.stat().st_size

            selected_record_path = evidence_by_width[101]["selected_record_path"]
            selected_record_path.write_text(json.dumps({
                "stage": "cluster", "executed": True, "width": 101, "sample_count": 5,
                "generation_digest": evidence_by_width[101]["generation_digest"],
                "artifacts": [{"path": "membership.tsv", "sha256": new_sha, "size": new_size}],
            }))
            new_record_sha = _sha256_bytes(selected_record_path.read_bytes())
            new_record_size = selected_record_path.stat().st_size

            new_entry = dataclasses.replace(
                config.legacy_edges.cluster_membership[101],
                membership_byte_size=new_size, membership_sha256=new_sha,
                selected_record_byte_size=new_record_size, selected_record_sha256=new_record_sha,
                expected_cluster_count=4, expected_largest_cluster_size=2,
            )
            cluster_membership = dict(config.legacy_edges.cluster_membership)
            cluster_membership[101] = new_entry

            # RETURN_MANIFEST/RETURN_INVENTORY must also agree with the new
            # membership for the shared verifier to succeed against the
            # re-pinned config -- rebuild them the same way the fixture
            # builder does.
            manifest_raw = json.loads((root / "RETURN_MANIFEST.json").read_text())
            manifest_raw["selected_stages"]["cluster_101"]["generation_digest"] = evidence_by_width[101]["generation_digest"]
            manifest_raw["selected_stages"]["cluster_101"]["membership_summary"] = {
                "member_count": 5, "cluster_count": 4, "largest_cluster_size": 2,
            }
            (root / "RETURN_MANIFEST.json").write_text(json.dumps(manifest_raw))
            inventory_raw = json.loads((root / "RETURN_INVENTORY.json").read_text())
            for entry in inventory_raw:
                if entry["path"] == "memberships/cluster_101.membership.tsv":
                    entry["byte_size"], entry["sha256"] = new_size, new_sha
                if entry["path"] == "selected_records/cluster_101.json":
                    entry["byte_size"], entry["sha256"] = new_record_size, new_record_sha
            (root / "RETURN_INVENTORY.json").write_text(json.dumps(inventory_raw))
            new_return_manifest_sha = _sha256_bytes((root / "RETURN_MANIFEST.json").read_bytes())
            new_return_manifest_size = (root / "RETURN_MANIFEST.json").stat().st_size
            new_return_inventory_sha = _sha256_bytes((root / "RETURN_INVENTORY.json").read_bytes())
            new_return_inventory_size = (root / "RETURN_INVENTORY.json").stat().st_size

            new_config = dataclasses.replace(
                config,
                legacy_edges=LegacyClusterEvidenceConfig(
                    return_manifest=ReturnBundleFileExpectation(
                        relative_path="RETURN_MANIFEST.json", byte_size=new_return_manifest_size,
                        sha256=new_return_manifest_sha,
                    ),
                    return_inventory=ReturnBundleFileExpectation(
                        relative_path="RETURN_INVENTORY.json", byte_size=new_return_inventory_size,
                        sha256=new_return_inventory_sha,
                    ),
                    cluster_membership=cluster_membership,
                ),
            )

            # The NEW config's live re-verification succeeds on its own --
            # only the comparison against the STALE accepted record catches
            # the drift.
            cme.verify_live_cluster_evidence(config=new_config, cluster_evidence_root=root)
            with self.assertRaises(r002c.StaleLegacyEvidenceError):
                r002c._verify_current_legacy_cluster_evidence(config=new_config, legacy_record=legacy_record)


class LiveClusterEvidenceSemanticCrossCheckTests(unittest.TestCase):
    """Correction review C2: ``RETURN_MANIFEST.json``/``RETURN_INVENTORY.json``
    must be semantically cross-checked against the selected records and
    membership files -- a syntactically valid, CORRECTLY re-pinned (the
    outer hash/size check alone would pass) but internally inconsistent
    return manifest/inventory must still be rejected.
    """

    def _repin_return_manifest(self, config, root):
        path = root / "RETURN_MANIFEST.json"
        sha = _sha256_bytes(path.read_bytes())
        size = path.stat().st_size
        return dataclasses.replace(
            config,
            legacy_edges=LegacyClusterEvidenceConfig(
                return_manifest=ReturnBundleFileExpectation(relative_path="RETURN_MANIFEST.json", byte_size=size, sha256=sha),
                return_inventory=config.legacy_edges.return_inventory,
                cluster_membership=config.legacy_edges.cluster_membership,
            ),
        )

    def _repin_return_inventory(self, config, root):
        path = root / "RETURN_INVENTORY.json"
        sha = _sha256_bytes(path.read_bytes())
        size = path.stat().st_size
        return dataclasses.replace(
            config,
            legacy_edges=LegacyClusterEvidenceConfig(
                return_manifest=config.legacy_edges.return_manifest,
                return_inventory=ReturnBundleFileExpectation(relative_path="RETURN_INVENTORY.json", byte_size=size, sha256=sha),
                cluster_membership=config.legacy_edges.cluster_membership,
            ),
        )

    def test_wrong_generation_digest_in_return_manifest_is_rejected_despite_correct_outer_hash(self):
        with TemporaryDirectory() as tmp:
            config, root, _evidence = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            manifest_path = root / "RETURN_MANIFEST.json"
            manifest_raw = json.loads(manifest_path.read_text())
            manifest_raw["selected_stages"]["cluster_500"]["generation_digest"] = "wrong-digest"
            manifest_path.write_text(json.dumps(manifest_raw))
            config = self._repin_return_manifest(config, root)  # outer hash now correctly matches the corrupted file
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)

    def test_wrong_member_count_in_return_manifest_is_rejected_despite_correct_outer_hash(self):
        with TemporaryDirectory() as tmp:
            config, root, _evidence = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            manifest_path = root / "RETURN_MANIFEST.json"
            manifest_raw = json.loads(manifest_path.read_text())
            manifest_raw["selected_stages"]["cluster_500"]["membership_summary"]["member_count"] = 999
            manifest_path.write_text(json.dumps(manifest_raw))
            config = self._repin_return_manifest(config, root)
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)

    def test_wrong_returned_membership_path_in_return_manifest_is_rejected(self):
        with TemporaryDirectory() as tmp:
            config, root, _evidence = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            manifest_path = root / "RETURN_MANIFEST.json"
            manifest_raw = json.loads(manifest_path.read_text())
            manifest_raw["selected_stages"]["cluster_500"]["returned_membership_path"] = (
                "memberships/cluster_251.membership.tsv"
            )
            manifest_path.write_text(json.dumps(manifest_raw))
            config = self._repin_return_manifest(config, root)
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)

    def test_not_executed_in_return_manifest_is_rejected(self):
        with TemporaryDirectory() as tmp:
            config, root, _evidence = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            manifest_path = root / "RETURN_MANIFEST.json"
            manifest_raw = json.loads(manifest_path.read_text())
            manifest_raw["selected_stages"]["cluster_500"]["executed"] = False
            manifest_path.write_text(json.dumps(manifest_raw))
            config = self._repin_return_manifest(config, root)
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)

    def test_missing_cluster_stage_in_return_manifest_is_rejected(self):
        with TemporaryDirectory() as tmp:
            config, root, _evidence = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            manifest_path = root / "RETURN_MANIFEST.json"
            manifest_raw = json.loads(manifest_path.read_text())
            del manifest_raw["selected_stages"]["cluster_500"]
            manifest_path.write_text(json.dumps(manifest_raw))
            config = self._repin_return_manifest(config, root)
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)

    def test_missing_membership_entry_in_return_inventory_is_rejected_despite_correct_outer_hash(self):
        with TemporaryDirectory() as tmp:
            config, root, _evidence = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            inventory_path = root / "RETURN_INVENTORY.json"
            inventory_raw = json.loads(inventory_path.read_text())
            inventory_raw = [e for e in inventory_raw if e["path"] != "memberships/cluster_500.membership.tsv"]
            inventory_path.write_text(json.dumps(inventory_raw))
            config = self._repin_return_inventory(config, root)
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)

    def test_duplicate_entry_in_return_inventory_is_rejected(self):
        with TemporaryDirectory() as tmp:
            config, root, _evidence = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            inventory_path = root / "RETURN_INVENTORY.json"
            inventory_raw = json.loads(inventory_path.read_text())
            duplicate = next(e for e in inventory_raw if e["path"] == "memberships/cluster_500.membership.tsv")
            inventory_raw.append(dict(duplicate))
            inventory_path.write_text(json.dumps(inventory_raw))
            config = self._repin_return_inventory(config, root)
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)

    def test_contradictory_hash_in_return_inventory_is_rejected(self):
        with TemporaryDirectory() as tmp:
            config, root, _evidence = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            inventory_path = root / "RETURN_INVENTORY.json"
            inventory_raw = json.loads(inventory_path.read_text())
            for entry in inventory_raw:
                if entry["path"] == "memberships/cluster_500.membership.tsv":
                    entry["sha256"] = "f" * 64
            inventory_path.write_text(json.dumps(inventory_raw))
            config = self._repin_return_inventory(config, root)
            with self.assertRaises(cme.ClusterEvidenceError):
                cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)

    def test_well_formed_evidence_is_accepted(self):
        with TemporaryDirectory() as tmp:
            config, root, _evidence = _build_tiny_cluster_evidence_root_and_config(Path(tmp))
            live = cme.verify_live_cluster_evidence(config=config, cluster_evidence_root=root)
            self.assertEqual(set(live["cluster_evidence"]), {"500", "251", "101"})
            for width in (500, 251, 101):
                self.assertEqual(live["cluster_membership_by_width"][width]["row_0"], "row_0")


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
