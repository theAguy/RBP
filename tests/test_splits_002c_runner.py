"""End-to-end and restart-safety tests for the Task 002C runner.

Designed to run under the isolated environment created for this handoff
(``.venv-002c-legacy``, Python 3.12 with the pinned numpy/scipy/scikit-learn/
iterative-stratification stack) so the full pipeline -- including
``legacy_diagnostic`` -- executes for real, never skipped. The accepted
local MMseqs2 binary (from the ``rbpbench-splits-002`` conda environment,
never modified by this task) is reached by its exact resolved absolute
path, which :func:`shutil.which` accepts directly.

Every input here is a tiny synthetic fixture: distinct-length synthetic
sequences per protected width (guaranteeing no accidental exact/
reverse-complement collision and satisfying the strict per-width FASTA
validation added by the C1-C7 correction pass), a tiny 20-row CSV, a tiny
20-singleton-component membership file, a matching tiny component-report
JSON, tiny dataset-audit/proteins-table stand-ins, tiny per-width exact-RC
edge files, and a tiny per-width 20-singleton-cluster membership TSV/
selected-record layout (Task 002C-2A,
:mod:`rbpbench.splits.cluster_membership_evidence`) mirroring the accepted
Task 002B return's shape. No real CSV, accepted Task 002B artifact, or real
MMseqs2 execution over real sequences is ever touched.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rbpbench.splits import commands as splits_commands
from rbpbench.splits import mmseqs_audit
from rbpbench.splits import output as splits_output
from rbpbench.splits import restart
from rbpbench.splits import runner_002c as r002c
from rbpbench.splits.config_002c import load_config_002c

_MMSEQS_CANDIDATES = (
    "mmseqs",
    "/opt/miniconda3/envs/rbpbench-splits-002/bin/mmseqs",
)


def _resolve_mmseqs_bin() -> str:
    for candidate in _MMSEQS_CANDIDATES:
        if shutil.which(candidate):
            return candidate
    raise RuntimeError(
        "no usable mmseqs binary found for real-binary Task 002C audit tests; expected it on PATH or at "
        f"one of {_MMSEQS_CANDIDATES}"
    )


# 20 singleton components (one row each): with the frozen seed, this
# splits deterministically into a non-empty train/validation/test (14/3/3),
# so every directed query/target partition pair has at least one sequence
# on each side -- an mmseqs createdb call on a genuinely empty FASTA is a
# tool-level failure unrelated to what this suite is testing.
_SAMPLE_COUNT = 20
_COMPONENT_IDS = [f"{i:064x}" for i in range(_SAMPLE_COUNT)]
_PROTECTED_WIDTHS = (500, 251, 101)


def _pseudo_random_sequence(seed: int, length: int) -> str:
    import random

    rng = random.Random(seed)
    return "".join(rng.choices("ACGT", k=length))


# Pseudo-random sequences at EACH protected width's exact nucleotide length
# (the strict per-width FASTA validation added by the C1-C7 correction pass
# rejects a length mismatch), one distinct RNG seed per (width, row): two
# independently drawn random sequences at these lengths are overwhelmingly
# unlikely to reach the frozen 90% identity / 80-95% coverage MMseqs2
# thresholds by chance, so a clean run is expected to find zero qualifying
# hits, while still being distinct enough to never accidentally collide
# under exact/reverse-complement hashing either.
_SEQUENCES_BY_WIDTH: dict[int, dict[str, str]] = {
    width: {f"row_{i}": _pseudo_random_sequence(seed=1000 * width + i, length=width) for i in range(_SAMPLE_COUNT)}
    for width in _PROTECTED_WIDTHS
}


def _write_config(path: Path, *, mmseqs_sha256: str) -> None:
    path.write_text(f"""
seed = 20260925
protected_widths = [500, 251, 101]

[dataset]
csv_filename = "tiny.csv"
csv_sha256 = "{'0' * 64}"
csv_byte_size = 0
expected_row_count = {_SAMPLE_COUNT}
audit_json_path = "tiny_dataset_audit.json"
audit_json_sha256 = "{'0' * 64}"
proteins_tsv_path = "tiny_proteins.tsv"
proteins_tsv_sha256 = "{'0' * 64}"
protein_id_min = 1
protein_id_max = 122

[components_002b]
membership_byte_size = 0
membership_sha256 = "{'0' * 64}"
report_byte_size = 0
report_sha256 = "{'0' * 64}"
expected_component_count = {_SAMPLE_COUNT}

[assignment]
target_fractions = {{ train = 0.70, validation = 0.15, test = 0.15 }}
evaluation_floor = 0
balance_deviation_flag_pct = 3.0
row_dimension_weight = 244
protein_class_dimension_weight = 1
max_repair_passes = 10
max_repair_proposals = 10000
row_fraction_repair_limit_pct = 100.0

[legacy_diagnostic]
python_version = "3.12"
numpy_version = "2.0.2"
scipy_version = "1.16.1"
scikit_learn_version = "1.6.1"
iterative_stratification_version = "0.1.9"
n_splits = 5
shuffle = true
random_state = 42
fold_index = 0

[audit]
max_threads = 1
timeout_seconds = 120
max_new_disk_gib = 5.0
min_free_disk_gib = 0.01
min_installed_ram_gib = 0.0
min_available_memory_gib_before_launch = 0.0
resource_poll_interval_seconds = 0.2
probe_sample_size = 100
probe_max_peak_memory_gib = 10.0
probe_min_available_memory_gib_before_next_stage = 0.0

[binary]
mmseqs_sha256 = "{mmseqs_sha256}"

[decode_002b2]
manifest_path = "tiny_decode_manifest.json"
manifest_sha256 = "{'0' * 64}"

[legacy_edges]
return_manifest_relative_path = "RETURN_MANIFEST.json"
return_manifest_byte_size = 0
return_manifest_sha256 = "{'0' * 64}"
return_inventory_relative_path = "RETURN_INVENTORY.json"
return_inventory_byte_size = 0
return_inventory_sha256 = "{'0' * 64}"

[legacy_edges.cluster_membership.500]
membership_relative_path = "memberships/cluster_500.membership.tsv"
membership_byte_size = 0
membership_sha256 = "{'0' * 64}"
selected_record_relative_path = "selected_records/cluster_500.json"
selected_record_byte_size = 0
selected_record_sha256 = "{'0' * 64}"
expected_generation_digest = "PENDING"
expected_member_count = {_SAMPLE_COUNT}
expected_cluster_count = {_SAMPLE_COUNT}
expected_largest_cluster_size = 1
evidence_kind = "connected_component_membership"

[legacy_edges.cluster_membership.251]
membership_relative_path = "memberships/cluster_251.membership.tsv"
membership_byte_size = 0
membership_sha256 = "{'0' * 64}"
selected_record_relative_path = "selected_records/cluster_251.json"
selected_record_byte_size = 0
selected_record_sha256 = "{'0' * 64}"
expected_generation_digest = "PENDING"
expected_member_count = {_SAMPLE_COUNT}
expected_cluster_count = {_SAMPLE_COUNT}
expected_largest_cluster_size = 1
evidence_kind = "connected_component_membership"

[legacy_edges.cluster_membership.101]
membership_relative_path = "memberships/cluster_101.membership.tsv"
membership_byte_size = 0
membership_sha256 = "{'0' * 64}"
selected_record_relative_path = "selected_records/cluster_101.json"
selected_record_byte_size = 0
selected_record_sha256 = "{'0' * 64}"
expected_generation_digest = "PENDING"
expected_member_count = {_SAMPLE_COUNT}
expected_cluster_count = {_SAMPLE_COUNT}
expected_largest_cluster_size = 1
evidence_kind = "connected_component_membership"
""")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Fixture:
    def __init__(self, root: Path, *, mmseqs_bin: str):
        self.root = root
        self.output_dir = root / "output"
        self.csv_path = root / "tiny.csv"
        self.membership_path = root / "membership.tsv.gz"
        self.component_report_path = root / "tiny_component_report.json"
        self.audit_json_path = root / "tiny_dataset_audit.json"
        self.proteins_tsv_path = root / "tiny_proteins.tsv"
        self.decode_fasta_dir = root / "decode"
        self.exact_rc_edges_dir = root / "exact_rc_edges"
        self.cluster_evidence_root = root / "cluster_evidence_root"
        self.decode_manifest_path = root / "tiny_decode_manifest.json"
        self.config_path = root / "sequence_partitions_002c_v1_fixture.toml"
        self.mmseqs_bin = mmseqs_bin

        # 20 singleton components (one row each; see _COMPONENT_IDS).
        rows = [(f"row_{i}", _COMPONENT_IDS[i]) for i in range(_SAMPLE_COUNT)]
        splits_output.write_deterministic_component_membership_gzip(rows, self.membership_path)
        membership_sha256 = _sha256_bytes(self.membership_path.read_bytes())
        membership_size = self.membership_path.stat().st_size

        component_report = {
            "total_rows": _SAMPLE_COUNT,
            "component_count": _SAMPLE_COUNT,
            "component_sizes": {cid: 1 for cid in _COMPONENT_IDS},
            "giant_component_gate": {"single_component_gate_tripped": False, "top20_gate_tripped": False},
        }
        self.component_report_path.write_text(json.dumps(component_report))
        report_sha256 = _sha256_bytes(self.component_report_path.read_bytes())
        report_size = self.component_report_path.stat().st_size

        self.audit_json_path.write_text(json.dumps({"tiny": "fixture-audit"}))
        audit_json_sha256 = _sha256_bytes(self.audit_json_path.read_bytes())
        self.proteins_tsv_path.write_text("protein_id\tprotein_name\n1\tTINY1\n2\tTINY2\n")
        proteins_tsv_sha256 = _sha256_bytes(self.proteins_tsv_path.read_bytes())

        label_by_row = {0: "+1", 2: "-1", 4: "+2", 6: "-2", 8: "+1", 10: "-1"}
        csv_lines = ["sequence,labels"]
        for i in range(_SAMPLE_COUNT):
            csv_lines.append(f"junk{i},{label_by_row.get(i, '')}")
        self.csv_path.write_text("\n".join(csv_lines) + "\n")
        csv_sha256 = _sha256_bytes(self.csv_path.read_bytes())
        csv_size = self.csv_path.stat().st_size

        binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
        assert binary.sha256, "mmseqs binary must be resolvable for real-binary fixture tests"

        _write_config(self.config_path, mmseqs_sha256=binary.sha256)
        # Patch in the real tiny file hashes/sizes (the static template
        # above uses placeholder zeros -- overwritten here so every fixture
        # invocation binds to THIS run's actual tiny files, never a stale
        # hard-coded value).
        text = self.config_path.read_text()
        text = text.replace('csv_sha256 = "' + "0" * 64 + '"', f'csv_sha256 = "{csv_sha256}"')
        text = text.replace("csv_byte_size = 0", f"csv_byte_size = {csv_size}")
        text = text.replace(
            'membership_sha256 = "' + "0" * 64 + '"', f'membership_sha256 = "{membership_sha256}"'
        )
        text = text.replace("membership_byte_size = 0", f"membership_byte_size = {membership_size}")
        text = text.replace('report_sha256 = "' + "0" * 64 + '"', f'report_sha256 = "{report_sha256}"')
        text = text.replace("report_byte_size = 0", f"report_byte_size = {report_size}")
        text = text.replace(
            'audit_json_sha256 = "' + "0" * 64 + '"', f'audit_json_sha256 = "{audit_json_sha256}"'
        )
        text = text.replace(
            'proteins_tsv_sha256 = "' + "0" * 64 + '"', f'proteins_tsv_sha256 = "{proteins_tsv_sha256}"'
        )

        self.decode_fasta_dir.mkdir(parents=True, exist_ok=True)
        fasta_evidence: dict[int, tuple[str, int, str]] = {}
        for width in _PROTECTED_WIDTHS:
            fasta_path = self.decode_fasta_dir / f"sequence_partitions_width_{width}.fasta"
            sequences = _SEQUENCES_BY_WIDTH[width]
            with fasta_path.open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            fasta_evidence[width] = (
                f"decode/generations/decode_tiny/sequence_partitions_width_{width}.fasta",
                fasta_path.stat().st_size,
                _sha256_bytes(fasta_path.read_bytes()),
            )

        self.exact_rc_edges_dir.mkdir(parents=True, exist_ok=True)
        duplicate_edges_evidence: dict[int, tuple[str, int, str]] = {}
        for width_index, width in enumerate(_PROTECTED_WIDTHS):
            # Distinct, non-empty, in-universe content per width (rather
            # than a uniform "[]" for all three) so a width-swapped file is
            # actually hash-distinguishable -- see
            # LegacyEdgeProvenanceTests.test_width_swapped_exact_rc_edges_is_rejected.
            a, b = f"row_{2 * width_index}", f"row_{2 * width_index + 1}"

            exact_rc_path = self.exact_rc_edges_dir / f"exact_rc_edges_{width}.json"
            exact_rc_path.write_text(json.dumps([[a, b]]))
            duplicate_edges_evidence[width] = (
                f"decode/generations/decode_tiny/duplicate_edges_{width}.json",
                exact_rc_path.stat().st_size,
                _sha256_bytes(exact_rc_path.read_bytes()),
            )

        # Task 002C-2A: the accepted Task 002B return's cluster-MEMBERSHIP
        # evidence -- RETURN_MANIFEST.json/RETURN_INVENTORY.json plus, per
        # width, a tiny 20-singleton-cluster membership TSV (every row is
        # its own cluster: representative == member) and its selected
        # record -- laid out exactly like the real accepted return, under a
        # portable root never a hard-coded collaborator absolute path.
        (self.cluster_evidence_root / "memberships").mkdir(parents=True, exist_ok=True)
        (self.cluster_evidence_root / "selected_records").mkdir(parents=True, exist_ok=True)

        return_manifest_path = self.cluster_evidence_root / "RETURN_MANIFEST.json"
        return_manifest_path.write_text(json.dumps({"tiny": "fixture-return-manifest"}))
        return_manifest_size = return_manifest_path.stat().st_size
        return_manifest_sha256 = _sha256_bytes(return_manifest_path.read_bytes())

        return_inventory_path = self.cluster_evidence_root / "RETURN_INVENTORY.json"
        return_inventory_path.write_text(json.dumps({"tiny": "fixture-return-inventory"}))
        return_inventory_size = return_inventory_path.stat().st_size
        return_inventory_sha256 = _sha256_bytes(return_inventory_path.read_bytes())

        cluster_membership_evidence: dict[int, dict] = {}
        for width in _PROTECTED_WIDTHS:
            membership_path = self.cluster_evidence_root / "memberships" / f"cluster_{width}.membership.tsv"
            with membership_path.open("w") as handle:
                for i in range(_SAMPLE_COUNT):
                    handle.write(f"row_{i}\trow_{i}\n")
            membership_size = membership_path.stat().st_size
            membership_sha256 = _sha256_bytes(membership_path.read_bytes())

            generation_digest = f"tiny-cluster-generation-digest-{width}"
            selected_record_path = self.cluster_evidence_root / "selected_records" / f"cluster_{width}.json"
            selected_record_path.write_text(json.dumps({
                "stage": "cluster",
                "executed": True,
                "width": width,
                "sample_count": _SAMPLE_COUNT,
                "generation_digest": generation_digest,
                "artifacts": [{"path": "membership.tsv", "sha256": membership_sha256, "size": membership_size}],
            }))
            selected_record_size = selected_record_path.stat().st_size
            selected_record_sha256 = _sha256_bytes(selected_record_path.read_bytes())

            cluster_membership_evidence[width] = {
                "membership_size": membership_size, "membership_sha256": membership_sha256,
                "selected_record_size": selected_record_size, "selected_record_sha256": selected_record_sha256,
                "generation_digest": generation_digest,
            }

        decode_manifest = {
            "checkpoint": "002B-2",
            "decode_generation_digest": "tiny-fixture-decode-generation-digest",
            "retained_artifacts": [
                {"path": path, "byte_size": size, "sha256": sha}
                for path, size, sha in fasta_evidence.values()
            ] + [
                {"path": path, "byte_size": size, "sha256": sha}
                for path, size, sha in duplicate_edges_evidence.values()
            ],
        }
        self.decode_manifest_path.write_text(json.dumps(decode_manifest))
        decode_manifest_sha256 = _sha256_bytes(self.decode_manifest_path.read_bytes())

        text = text.replace(
            'manifest_sha256 = "' + "0" * 64 + '"', f'manifest_sha256 = "{decode_manifest_sha256}"'
        )

        text = text.replace("return_manifest_byte_size = 0", f"return_manifest_byte_size = {return_manifest_size}")
        text = text.replace(
            'return_manifest_sha256 = "' + "0" * 64 + '"', f'return_manifest_sha256 = "{return_manifest_sha256}"'
        )
        text = text.replace("return_inventory_byte_size = 0", f"return_inventory_byte_size = {return_inventory_size}")
        text = text.replace(
            'return_inventory_sha256 = "' + "0" * 64 + '"', f'return_inventory_sha256 = "{return_inventory_sha256}"'
        )
        for width in _PROTECTED_WIDTHS:
            evidence = cluster_membership_evidence[width]
            text = text.replace(
                f'membership_relative_path = "memberships/cluster_{width}.membership.tsv"\n'
                f'membership_byte_size = 0\nmembership_sha256 = "{"0" * 64}"',
                f'membership_relative_path = "memberships/cluster_{width}.membership.tsv"\n'
                f'membership_byte_size = {evidence["membership_size"]}\n'
                f'membership_sha256 = "{evidence["membership_sha256"]}"',
            )
            text = text.replace(
                f'selected_record_relative_path = "selected_records/cluster_{width}.json"\n'
                f'selected_record_byte_size = 0\nselected_record_sha256 = "{"0" * 64}"',
                f'selected_record_relative_path = "selected_records/cluster_{width}.json"\n'
                f'selected_record_byte_size = {evidence["selected_record_size"]}\n'
                f'selected_record_sha256 = "{evidence["selected_record_sha256"]}"',
            )
            text = text.replace(
                'expected_generation_digest = "PENDING"', f'expected_generation_digest = "{evidence["generation_digest"]}"', 1
            )
        self.config_path.write_text(text)

        self.config = load_config_002c(self.config_path)

    def assign(self, *, membership_path: Path | None = None) -> dict:
        return r002c.stage_assign(
            config=self.config,
            csv_path=self.csv_path,
            membership_path=membership_path if membership_path is not None else self.membership_path,
            component_report_path=self.component_report_path,
            audit_json_path=self.audit_json_path,
            proteins_tsv_path=self.proteins_tsv_path,
            output_dir=self.output_dir,
        )

    def legacy_diagnostic(self, *, assign_record: dict) -> dict:
        return r002c.stage_legacy_diagnostic(
            config=self.config, csv_path=self.csv_path, output_dir=self.output_dir, assign_record=assign_record,
            exact_rc_edges_dir=self.exact_rc_edges_dir, cluster_evidence_root=self.cluster_evidence_root,
            decode_manifest_path=self.decode_manifest_path,
        )

    def exact_audit(self, *, width: int, assign_record: dict, decode_fasta_dir: Path | None = None) -> dict:
        return r002c.stage_exact_audit(
            width=width, config=self.config, output_dir=self.output_dir,
            decode_fasta_dir=decode_fasta_dir if decode_fasta_dir is not None else self.decode_fasta_dir,
            decode_manifest_path=self.decode_manifest_path, assign_record=assign_record,
        )

    def audit_probe(self, *, width: int, assign_record: dict, authorize: bool = True, mmseqs_bin: str | None = None) -> dict:
        return r002c.stage_audit_probe(
            width=width, config=self.config, output_dir=self.output_dir, decode_fasta_dir=self.decode_fasta_dir,
            decode_manifest_path=self.decode_manifest_path, assign_record=assign_record, authorize=authorize,
            mmseqs_bin=mmseqs_bin if mmseqs_bin is not None else self.mmseqs_bin,
        )

    def audit_search(
        self, *, width: int, query_partition: str, target_partition: str, assign_record: dict, authorize: bool = True,
        mmseqs_bin: str | None = None,
    ) -> dict:
        return r002c.stage_audit_search(
            width=width, query_partition=query_partition, target_partition=target_partition, config=self.config,
            output_dir=self.output_dir, decode_fasta_dir=self.decode_fasta_dir,
            decode_manifest_path=self.decode_manifest_path, assign_record=assign_record, authorize=authorize,
            mmseqs_bin=mmseqs_bin if mmseqs_bin is not None else self.mmseqs_bin,
        )


def _build_fixture(root: Path) -> _Fixture:
    return _Fixture(root, mmseqs_bin=_resolve_mmseqs_bin())


class AssignStageTests(unittest.TestCase):
    def test_dry_run_touches_nothing(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            result = r002c.stage_assign(
                config=fx.config, csv_path=Path("/does/not/exist.csv"), membership_path=Path("/does/not/exist.tsv.gz"),
                component_report_path=Path("/does/not/exist_report.json"), audit_json_path=Path("/does/not/exist_audit.json"),
                proteins_tsv_path=Path("/does/not/exist_proteins.tsv"), output_dir=fx.output_dir, dry_run=True,
            )
            self.assertTrue(result["dry_run"])
            self.assertFalse(fx.output_dir.exists())

    def test_assign_produces_an_accepted_record_and_membership_file(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            record = fx.assign()
            self.assertTrue(record["executed"])
            self.assertEqual(sum(record["partition_row_counts"].values()), _SAMPLE_COUNT)
            rows = splits_output.read_membership_gzip(Path(record["membership_path"]))
            self.assertEqual(len(rows), _SAMPLE_COUNT)
            accepted = restart.load_accepted(fx.output_dir, "assign")
            self.assertIsNotNone(accepted)

    def test_selected_record_never_inlines_the_large_sample_or_component_maps(self):
        # C2 (docs/reviews/002c1_partition_orchestration_correction_review.md):
        # the selection pointer must store only paths/hashes/counts/digests --
        # the 361,180-entry sample-to-component and 173,465-entry
        # component-to-partition maps live ONLY in the immutable generation's
        # own membership artifact.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            record = fx.assign()
            self.assertNotIn("sample_to_component", record)
            self.assertNotIn("component_to_partition", record)
            on_disk = json.loads(restart.selected_record_path(fx.output_dir, "assign").read_text())
            self.assertNotIn("sample_to_component", on_disk)
            self.assertNotIn("component_to_partition", on_disk)

    def test_changed_csv_invalidates_the_accepted_record(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            first_fp = fx.assign()["stage_fingerprint"]
            # Changing the CSV now makes it disagree with the config's frozen
            # hash -- assign must fail closed rather than silently ingest it.
            fx.csv_path.write_text(fx.csv_path.read_text() + "\n")
            with self.assertRaises(r002c.InputValidationError):
                fx.assign()

    def test_wrong_component_membership_hash_fails_closed_before_assignment(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            bad_membership = fx.root / "bad_membership.tsv.gz"
            splits_output.write_deterministic_component_membership_gzip([("row_0", _COMPONENT_IDS[0])], bad_membership)
            with self.assertRaises(Exception):
                fx.assign(membership_path=bad_membership)
            # No candidate generation is left behind, and no accepted record exists.
            self.assertIsNone(restart.load_accepted(fx.output_dir, "assign"))

    def test_wrong_component_report_hash_fails_closed_before_assignment(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            bad_report = fx.root / "bad_report.json"
            bad_report.write_text(json.dumps({"total_rows": 1}))
            with self.assertRaises(Exception):
                r002c.stage_assign(
                    config=fx.config, csv_path=fx.csv_path, membership_path=fx.membership_path,
                    component_report_path=bad_report, audit_json_path=fx.audit_json_path,
                    proteins_tsv_path=fx.proteins_tsv_path, output_dir=fx.output_dir,
                )
            self.assertIsNone(restart.load_accepted(fx.output_dir, "assign"))

    def test_wrong_audit_json_hash_fails_closed_before_assignment(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            bad_audit = fx.root / "bad_audit.json"
            bad_audit.write_text("{}")
            with self.assertRaises(r002c.InputValidationError):
                r002c.stage_assign(
                    config=fx.config, csv_path=fx.csv_path, membership_path=fx.membership_path,
                    component_report_path=fx.component_report_path, audit_json_path=bad_audit,
                    proteins_tsv_path=fx.proteins_tsv_path, output_dir=fx.output_dir,
                )
            self.assertIsNone(restart.load_accepted(fx.output_dir, "assign"))

    def test_wrong_proteins_tsv_hash_fails_closed_before_assignment(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            bad_proteins = fx.root / "bad_proteins.tsv"
            bad_proteins.write_text("protein_id\tprotein_name\n")
            with self.assertRaises(r002c.InputValidationError):
                r002c.stage_assign(
                    config=fx.config, csv_path=fx.csv_path, membership_path=fx.membership_path,
                    component_report_path=fx.component_report_path, audit_json_path=fx.audit_json_path,
                    proteins_tsv_path=bad_proteins, output_dir=fx.output_dir,
                )
            self.assertIsNone(restart.load_accepted(fx.output_dir, "assign"))

    def test_component_size_map_mismatch_against_report_fails_closed(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            bad_report = fx.root / "mismatched_report.json"
            mismatched = {
                "total_rows": _SAMPLE_COUNT,
                "component_count": _SAMPLE_COUNT,
                # Every declared size is wrong (2 instead of 1): the
                # membership-derived map can no longer match byte-for-byte.
                "component_sizes": {cid: 2 for cid in _COMPONENT_IDS},
                "giant_component_gate": {"single_component_gate_tripped": False, "top20_gate_tripped": False},
            }
            bad_report.write_text(json.dumps(mismatched))
            import hashlib as _hashlib

            text = fx.config_path.read_text()
            old_sha = _sha256_bytes(fx.component_report_path.read_bytes())
            new_sha = _sha256_bytes(bad_report.read_bytes())
            new_size = bad_report.stat().st_size
            old_size = fx.component_report_path.stat().st_size
            text = text.replace(f'report_sha256 = "{old_sha}"', f'report_sha256 = "{new_sha}"')
            text = text.replace(f"report_byte_size = {old_size}", f"report_byte_size = {new_size}")
            fx.config_path.write_text(text)
            fx.config = load_config_002c(fx.config_path)
            with self.assertRaises(Exception):
                r002c.stage_assign(
                    config=fx.config, csv_path=fx.csv_path, membership_path=fx.membership_path,
                    component_report_path=bad_report, audit_json_path=fx.audit_json_path,
                    proteins_tsv_path=fx.proteins_tsv_path, output_dir=fx.output_dir,
                )


class ExactAuditStageTests(unittest.TestCase):
    def test_exact_audit_passes_on_distinct_length_sequences(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            record = fx.exact_audit(width=500, assign_record=assign_record)
            self.assertTrue(record["passed"])
            self.assertEqual(record["violation_count"], 0)

    def test_width_outside_protected_widths_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            with self.assertRaises(r002c.StageValidationError):
                fx.exact_audit(width=999, assign_record=assign_record)

    def test_exact_audit_invalidated_by_a_changed_upstream_assignment(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            fp1 = r002c.exact_audit_fingerprint(
                config=fx.config, width=500, assign_stage_fingerprint=assign_record["stage_fingerprint"],
                assign_generation_digest=assign_record["generation_digest"], fasta_sha256="ignored-for-this-comparison",
                decode_generation_digest="ignored-for-this-comparison",
            )
            # A different (simulated) assign stage_fingerprint must produce a
            # different exact_audit fingerprint, so a rerun after a real
            # upstream change is never mistaken for still-current.
            fp2 = r002c.exact_audit_fingerprint(
                config=fx.config, width=500, assign_stage_fingerprint="a-different-assign-fingerprint",
                assign_generation_digest=assign_record["generation_digest"], fasta_sha256="ignored-for-this-comparison",
                decode_generation_digest="ignored-for-this-comparison",
            )
            self.assertNotEqual(fp1, fp2)

    def test_exact_audit_invalidated_by_a_forced_rebuild_of_assign(self):
        # C4: even a byte-identical forced rebuild of `assign` must get a
        # NEW generation_digest (salted with its own generation path), which
        # must invalidate a downstream exact_audit fingerprint bound to it.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            rebuilt = r002c.stage_assign(
                config=fx.config, csv_path=fx.csv_path, membership_path=fx.membership_path,
                component_report_path=fx.component_report_path, audit_json_path=fx.audit_json_path,
                proteins_tsv_path=fx.proteins_tsv_path, output_dir=fx.output_dir,
            )
            self.assertNotEqual(assign_record["generation_digest"], rebuilt["generation_digest"])
            fp1 = r002c.exact_audit_fingerprint(
                config=fx.config, width=500, assign_stage_fingerprint=assign_record["stage_fingerprint"],
                assign_generation_digest=assign_record["generation_digest"], fasta_sha256="x",
                decode_generation_digest="x",
            )
            fp2 = r002c.exact_audit_fingerprint(
                config=fx.config, width=500, assign_stage_fingerprint=rebuilt["stage_fingerprint"],
                assign_generation_digest=rebuilt["generation_digest"], fasta_sha256="x",
                decode_generation_digest="x",
            )
            self.assertNotEqual(fp1, fp2)

    def test_duplicate_fasta_header_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            bad_dir = fx.root / "dup_decode"
            bad_dir.mkdir()
            sequences = _SEQUENCES_BY_WIDTH[500]
            with (bad_dir / "sequence_partitions_width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
                # Duplicate the very first header.
                first_id = sorted(sequences)[0]
                handle.write(f">{first_id}\n{sequences[first_id]}\n")
            with self.assertRaises(r002c.FastaValidationError):
                fx.exact_audit(width=500, assign_record=assign_record, decode_fasta_dir=bad_dir)

    def test_wrong_width_sequence_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            bad_dir = fx.root / "wrong_width_decode"
            bad_dir.mkdir()
            # Reuse the 251-nt sequences under a width-500 filename.
            sequences = _SEQUENCES_BY_WIDTH[251]
            with (bad_dir / "sequence_partitions_width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            with self.assertRaises(r002c.FastaValidationError):
                fx.exact_audit(width=500, assign_record=assign_record, decode_fasta_dir=bad_dir)

    def test_missing_id_in_fasta_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            bad_dir = fx.root / "missing_id_decode"
            bad_dir.mkdir()
            sequences = dict(_SEQUENCES_BY_WIDTH[500])
            del sequences["row_0"]
            with (bad_dir / "sequence_partitions_width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            with self.assertRaises(r002c.FastaValidationError):
                fx.exact_audit(width=500, assign_record=assign_record, decode_fasta_dir=bad_dir)

    def test_non_acgt_alphabet_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            bad_dir = fx.root / "bad_alphabet_decode"
            bad_dir.mkdir()
            sequences = dict(_SEQUENCES_BY_WIDTH[500])
            first_id = sorted(sequences)[0]
            # Replace one nucleotide with an ambiguity code (N), keeping the
            # length exactly correct -- only the alphabet is wrong.
            sequences[first_id] = "N" + sequences[first_id][1:]
            with (bad_dir / "sequence_partitions_width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            with self.assertRaises(r002c.FastaValidationError):
                fx.exact_audit(width=500, assign_record=assign_record, decode_fasta_dir=bad_dir)

    def test_changed_fasta_content_produces_a_different_exact_audit_fingerprint(self):
        # F2 (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md):
        # a syntactically valid decode FASTA whose content no longer matches
        # the pinned Task 002B-2 decode-evidence manifest fails closed, even
        # though its own universe/width/alphabet are otherwise fine.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            record1 = fx.exact_audit(width=500, assign_record=assign_record)

            # Mutate one sequence's content (same ID, same width) so the
            # FASTA file's hash changes without touching anything else.
            mutated_dir = fx.root / "mutated_decode"
            mutated_dir.mkdir()
            sequences = dict(_SEQUENCES_BY_WIDTH[500])
            first_id = sorted(sequences)[0]
            seq = sequences[first_id]
            swapped = ("C" if seq[0] != "C" else "G") + seq[1:]
            sequences[first_id] = swapped
            with (mutated_dir / "sequence_partitions_width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            with self.assertRaises(r002c.DecodeManifestError):
                fx.exact_audit(width=500, assign_record=assign_record, decode_fasta_dir=mutated_dir)


class DecodeManifestBindingTests(unittest.TestCase):
    """F2: every stage that reads a decode FASTA verifies it against the
    pinned decode-evidence manifest -- a syntactically valid but
    non-accepted FASTA fails closed, distinctly from a structurally invalid
    one (covered by ``ExactAuditStageTests``).
    """

    def test_syntactically_valid_but_non_accepted_fasta_fails_closed(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            # A full replacement re-draw at the SAME width, using a
            # different seed: still exactly 20 rows, exact width, pure
            # A/C/G/T, and the identical accepted ID universe -- so every
            # structural/universe check in `_read_fasta_strict` passes, and
            # only the pinned decode-evidence hash comparison catches it.
            other_dir = fx.root / "other_valid_decode"
            other_dir.mkdir()
            sequences = {
                f"row_{i}": _pseudo_random_sequence(seed=9_000_000 + i, length=500) for i in range(_SAMPLE_COUNT)
            }
            with (other_dir / "sequence_partitions_width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            with self.assertRaises(r002c.DecodeManifestError):
                fx.exact_audit(width=500, assign_record=assign_record, decode_fasta_dir=other_dir)

    def test_decode_manifest_hash_mismatch_fails_closed(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            tampered_manifest = fx.root / "tampered_decode_manifest.json"
            data = json.loads(fx.decode_manifest_path.read_text())
            data["decode_generation_digest"] = "tampered"
            tampered_manifest.write_text(json.dumps(data))
            with self.assertRaises(r002c.DecodeManifestError):
                r002c.stage_exact_audit(
                    width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir,
                    decode_manifest_path=tampered_manifest, assign_record=assign_record,
                )


class DryRunAndAuthorizationTests(unittest.TestCase):
    def test_audit_probe_dry_run_never_opens_declared_inputs(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            result = r002c.stage_audit_probe(
                width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=Path("/does/not/exist"),
                decode_manifest_path=Path("/does/not/exist.json"), assign_record={}, authorize=False,
                mmseqs_bin="mmseqs-does-not-exist", dry_run=True,
            )
            self.assertTrue(result["dry_run"])
            self.assertFalse(fx.output_dir.exists())

    def test_audit_probe_without_authorization_raises_before_any_file_access(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            with self.assertRaises(r002c.AuthorizationError):
                r002c.stage_audit_probe(
                    width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=Path("/does/not/exist"),
                    decode_manifest_path=Path("/does/not/exist.json"), assign_record={}, authorize=False,
                    mmseqs_bin="mmseqs-does-not-exist", dry_run=False,
                )
            self.assertFalse(fx.output_dir.exists())

    def test_dry_run_is_checked_before_authorization(self):
        # Even without --authorize-mmseqs, --dry-run alone must return the
        # dry-run report rather than raising AuthorizationError.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            result = r002c.stage_audit_search(
                width=500, query_partition="train", target_partition="validation", config=fx.config,
                output_dir=fx.output_dir, decode_fasta_dir=Path("/does/not/exist"),
                decode_manifest_path=Path("/does/not/exist.json"), assign_record={},
                authorize=False, mmseqs_bin="mmseqs-does-not-exist", dry_run=True,
            )
            self.assertTrue(result["dry_run"])


class MemoryGateEnforcementTests(unittest.TestCase):
    """C5 (docs/reviews/002c1_partition_orchestration_correction_review.md):
    the configured memory gates are actually enforced, not dead config
    fields -- an unreachable installed-RAM/available-memory threshold must
    refuse BEFORE any subprocess launches.
    """

    def test_unreachable_min_installed_ram_refuses_before_any_subprocess(self):
        import dataclasses

        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            config = dataclasses.replace(
                fx.config, audit=dataclasses.replace(fx.config.audit, min_installed_ram_gib=1_000_000.0)
            )
            fx.config = config
            with self.assertRaises(r002c.guarded_exec.ResourceGateExceededError):
                fx.audit_probe(width=500, assign_record=assign_record)
            # F3: the per-launch gate now runs immediately before the FIRST
            # subprocess too, after the candidate generation directory
            # already exists (its query/target FASTAs must be written before
            # any subprocess can launch) -- the discarded candidate's own
            # generation subdirectory is removed, never merely a directory
            # that was never created.
            probe_dir = fx.output_dir / "audit_probe" / "500" / "generations"
            if probe_dir.exists():
                self.assertEqual(list(probe_dir.iterdir()), [])

    def test_unreachable_min_available_memory_before_launch_refuses(self):
        import dataclasses

        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            config = dataclasses.replace(
                fx.config,
                audit=dataclasses.replace(fx.config.audit, min_available_memory_gib_before_launch=1_000_000.0),
            )
            fx.config = config
            with self.assertRaises(r002c.guarded_exec.ResourceGateExceededError):
                fx.audit_probe(width=500, assign_record=assign_record)

    def test_low_memory_before_second_subprocess_discards_candidate_without_launching_it(self):
        # F3 (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md):
        # memory is rechecked immediately before EVERY individual MMseqs2
        # subprocess launch, not merely once before the whole four-command
        # attempt -- sufficient for the first command, insufficient for the
        # second, and the second must never launch.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()

            real_installed_check = r002c.guarded_exec.check_installed_ram_or_fail
            real_available_check = r002c.guarded_exec.check_available_memory_before_launch_or_fail
            call_count = {"n": 0}

            def _fail_on_second_call(**kwargs):
                call_count["n"] += 1
                if call_count["n"] == 2:
                    raise r002c.guarded_exec.ResourceGateExceededError("simulated low memory before the 2nd command")
                return 100.0

            # Keep this synthetic regression independent of the review host's
            # ability to expose physical RAM. Dedicated tests above retain the
            # real fail-closed installed/available-memory behavior.
            r002c.guarded_exec.check_installed_ram_or_fail = lambda **_kwargs: 16.0
            r002c.guarded_exec.check_available_memory_before_launch_or_fail = _fail_on_second_call
            try:
                with self.assertRaises(r002c.guarded_exec.ResourceGateExceededError):
                    fx.audit_probe(width=500, assign_record=assign_record)
            finally:
                r002c.guarded_exec.check_installed_ram_or_fail = real_installed_check
                r002c.guarded_exec.check_available_memory_before_launch_or_fail = real_available_check

            # Exactly 2 launch-time checks ran (createdb(query) succeeded,
            # createdb(target) refused) -- the search/createtsv commands
            # after it never launched, and the whole candidate generation was
            # discarded without touching any prior accepted evidence.
            self.assertEqual(call_count["n"], 2)
            probe_dir = fx.output_dir / "audit_probe" / "500" / "generations"
            if probe_dir.exists():
                self.assertEqual(list(probe_dir.iterdir()), [])


class DirectionAndWidthValidationTests(unittest.TestCase):
    def test_no_all_stage_exists(self):
        self.assertNotIn("all", r002c.STAGES)
        with self.assertRaises(SystemExit):
            r002c.build_parser().parse_args(["--stage", "all"])

    def test_width_rejected_outside_width_scoped_stages_via_cli(self):
        # main() must reject --width for "assign" BEFORE ever loading the
        # config or touching a declared input.
        with self.assertRaises(r002c.StageValidationError):
            r002c.main(["--stage", "assign", "--width", "500", "--config", "/does/not/exist.toml"])

    def test_width_required_for_width_scoped_stage_via_cli(self):
        with self.assertRaises(r002c.StageValidationError):
            r002c.main(["--stage", "exact_audit", "--config", "/does/not/exist.toml"])

    def test_direction_rejected_outside_direction_scoped_stages_via_cli(self):
        with self.assertRaises(r002c.StageValidationError):
            r002c.main([
                "--stage", "assign", "--query-partition", "train", "--target-partition", "validation",
                "--config", "/does/not/exist.toml",
            ])

    def test_direction_required_for_direction_scoped_stage_via_cli(self):
        # F1: audit_probe is width-scoped only now -- audit_search is the
        # sole remaining direction-scoped stage.
        with self.assertRaises(r002c.StageValidationError):
            r002c.main(["--stage", "audit_search", "--width", "500", "--config", "/does/not/exist.toml"])

    def test_direction_rejected_for_audit_probe_via_cli(self):
        # F1: --query-partition/--target-partition must be rejected for
        # audit_probe (it is width-scoped only, never direction-scoped).
        with self.assertRaises(r002c.StageValidationError):
            r002c.main([
                "--stage", "audit_probe", "--width", "500", "--query-partition", "train",
                "--target-partition", "validation", "--config", "/does/not/exist.toml",
            ])

    def test_mmseqs_stage_without_authorization_raises_before_config_load_via_cli(self):
        with self.assertRaises(r002c.AuthorizationError):
            r002c.main(["--stage", "audit_probe", "--width", "500", "--config", "/does/not/exist.toml"])

    def test_search_stage_without_authorization_raises_before_config_load_via_cli(self):
        with self.assertRaises(r002c.AuthorizationError):
            r002c.main([
                "--stage", "audit_search", "--width", "500", "--query-partition", "train",
                "--target-partition", "validation", "--config", "/does/not/exist.toml",
            ])

    def test_legacy_diagnostic_without_exact_rc_edges_dir_raises_via_cli(self):
        with self.assertRaises(r002c.StageValidationError):
            r002c.main(["--stage", "legacy_diagnostic", "--config", "/does/not/exist.toml"])

    def test_same_query_and_target_partition_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            with self.assertRaises(mmseqs_audit.InvalidDirectionError):
                r002c.stage_audit_search(
                    width=500, query_partition="train", target_partition="train", config=fx.config,
                    output_dir=fx.output_dir, decode_fasta_dir=Path("/tmp"),
                    decode_manifest_path=Path("/tmp/does-not-exist.json"), assign_record={}, authorize=True,
                    dry_run=False,
                )


class LegacyDiagnosticCompletenessTests(unittest.TestCase):
    def test_missing_cluster_membership_file_for_one_width_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            (fx.cluster_evidence_root / "memberships" / "cluster_101.membership.tsv").unlink()
            with self.assertRaises(r002c.InputValidationError):
                fx.legacy_diagnostic(assign_record=assign_record)

    def test_missing_exact_rc_edges_file_for_one_width_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            (fx.exact_rc_edges_dir / "exact_rc_edges_251.json").unlink()
            with self.assertRaises(r002c.InputValidationError):
                fx.legacy_diagnostic(assign_record=assign_record)

    def test_complete_evidence_produces_a_full_embedded_report(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            record = fx.legacy_diagnostic(assign_record=assign_record)
            self.assertIn("report", record)
            for width in _PROTECTED_WIDTHS:
                self.assertIn(str(width), record["report"]["cluster_boundary_by_width"])
                self.assertIn(str(width), record["report"]["exact_rc_by_width"])
                self.assertNotIn("directly_edge_matched_by_width", record["report"])


class LegacyEdgeProvenanceTests(unittest.TestCase):
    """F4 (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md)
    plus its Task 002C-2A correction: every legacy-diagnostic evidence file
    -- the three exact/RC edge files AND the three accepted cluster-
    membership TSVs/selected records -- is bound to explicit, pinned
    provenance with every endpoint reconciled against the closed canonical
    sample universe -- a bare file no longer qualifies merely because its
    own current hash is recorded.
    """

    def test_foreign_member_in_cluster_membership_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            membership_path = fx.cluster_evidence_root / "memberships" / "cluster_500.membership.tsv"
            lines = [f"row_{i}\trow_{i}\n" for i in range(_SAMPLE_COUNT)] + ["row_99999\trow_99999\n"]
            membership_path.write_text("".join(lines))
            self._repin_cluster(fx, 500, membership_path=membership_path)
            with self.assertRaises(r002c.InputValidationError):
                fx.legacy_diagnostic(assign_record=assign_record)

    def test_manually_unbound_cluster_membership_hash_is_rejected(self):
        # A bare file -- even one that would otherwise parse and reconcile
        # cleanly -- must not qualify merely because its OWN current hash is
        # recorded: it must match the config's PINNED expectation, which
        # this test deliberately leaves stale.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            membership_path = fx.cluster_evidence_root / "memberships" / "cluster_500.membership.tsv"
            membership_path.write_text("row_0\trow_0\n")  # content changed, config NOT re-pinned
            with self.assertRaises(r002c.InputValidationError):
                fx.legacy_diagnostic(assign_record=assign_record)

    def test_width_swapped_exact_rc_edges_is_rejected(self):
        # Width 251's accepted exact/RC edges content served under width
        # 500's slot: still a structurally valid, in-universe empty-or-real
        # list, but its hash does not match width 500's pinned expectation.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            width_251_content = (fx.exact_rc_edges_dir / "exact_rc_edges_251.json").read_bytes()
            (fx.exact_rc_edges_dir / "exact_rc_edges_500.json").write_bytes(width_251_content)
            with self.assertRaises(r002c.InputValidationError):
                fx.legacy_diagnostic(assign_record=assign_record)

    @staticmethod
    def _repin_cluster(fx, width: int, *, membership_path: Path) -> None:
        """Test-only helper: re-pins the config's cluster-membership hash/
        size expectation for ``width`` to whatever ``membership_path``
        currently contains, isolating the foreign-member check from the
        (already separately covered) pinned-hash check.
        """
        import dataclasses

        new_size = membership_path.stat().st_size
        new_sha = _sha256_bytes(membership_path.read_bytes())
        from rbpbench.splits.config_002c import LegacyClusterEvidenceConfig

        cluster_membership = dict(fx.config.legacy_edges.cluster_membership)
        cluster_membership[width] = dataclasses.replace(
            cluster_membership[width], membership_byte_size=new_size, membership_sha256=new_sha
        )
        fx.config = dataclasses.replace(
            fx.config,
            legacy_edges=LegacyClusterEvidenceConfig(
                return_manifest=fx.config.legacy_edges.return_manifest,
                return_inventory=fx.config.legacy_edges.return_inventory,
                cluster_membership=cluster_membership,
            ),
        )


class CurrentAssignmentValidatorTests(unittest.TestCase):
    """F4: a shared current-assignment validator re-hashes the accepted
    ``assign`` record's five frozen inputs before every downstream real
    stage/finalization -- editing the component report, component
    membership, dataset-audit JSON, or proteins table after ``assign``
    accepted must leave every downstream stage refusing, even though
    ``assign``'s OWN generation directory is still perfectly intact.
    """

    def test_component_membership_changed_after_assign_is_rejected_downstream(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            fx.membership_path.write_bytes(fx.membership_path.read_bytes() + b"\x00")
            with self.assertRaises(r002c.StaleAssignmentInputError):
                fx.exact_audit(width=500, assign_record=assign_record)

    def test_component_report_changed_after_assign_is_rejected_downstream(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            fx.component_report_path.write_text(fx.component_report_path.read_text() + " ")
            with self.assertRaises(r002c.StaleAssignmentInputError):
                fx.exact_audit(width=500, assign_record=assign_record)

    def test_audit_json_changed_after_assign_is_rejected_downstream(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            fx.audit_json_path.write_text(fx.audit_json_path.read_text() + " ")
            with self.assertRaises(r002c.StaleAssignmentInputError):
                fx.exact_audit(width=500, assign_record=assign_record)

    def test_proteins_tsv_changed_after_assign_is_rejected_downstream(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            fx.proteins_tsv_path.write_text(fx.proteins_tsv_path.read_text() + "\n")
            with self.assertRaises(r002c.StaleAssignmentInputError):
                fx.exact_audit(width=500, assign_record=assign_record)

    def test_stale_input_is_also_rejected_at_finalize(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            fx.legacy_diagnostic(assign_record=assign_record)
            for width in fx.config.protected_widths:
                fx.exact_audit(width=width, assign_record=assign_record)
            fx.proteins_tsv_path.write_text(fx.proteins_tsv_path.read_text() + "\n")
            with self.assertRaises(r002c.StaleAssignmentInputError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)


class FullPipelineEndToEndTests(unittest.TestCase):
    """The complete assign -> legacy_diagnostic -> exact_audit (x3 widths) ->
    audit_probe (x3 width-scoped, F1) -> audit_search (x18 directed) ->
    finalize chain, using the accepted local MMseqs2 binary and tiny
    synthetic fixtures throughout.

    NOTE: this exercises the real MMseqs2 binary 3 + 18 = 21 times (84
    subprocess launches). Per the reduced focused-test instructions
    (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md,
    "Focused evidence only"), this full directed pipeline is not rerun as
    part of routine focused verification -- see ``RealBinarySmokeTests``
    for the single tiny probe+search smoke that is.
    """

    def test_full_pipeline_promotes_to_finalize(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))

            assign_record = fx.assign()
            self.assertTrue(assign_record["minimum_count_report"]["passed"])

            legacy_record = fx.legacy_diagnostic(assign_record=assign_record)
            self.assertTrue(legacy_record["executed"])

            for width in fx.config.protected_widths:
                exact_record = fx.exact_audit(width=width, assign_record=assign_record)
                self.assertTrue(exact_record["passed"])

            probe_records = {}
            for width in fx.config.protected_widths:
                probe_record = fx.audit_probe(width=width, assign_record=assign_record)
                self.assertTrue(probe_record["executed"])
                probe_records[width] = probe_record

            for width in fx.config.protected_widths:
                for query_partition, target_partition in mmseqs_audit.ORDERED_PARTITION_PAIRS:
                    search_record = fx.audit_search(
                        width=width, query_partition=query_partition, target_partition=target_partition,
                        assign_record=assign_record,
                    )
                    self.assertTrue(search_record["passed"])
                    self.assertEqual(
                        search_record["upstream"]["probe_generation_digest"],
                        probe_records[width]["generation_digest"],
                    )

            finalize_record = r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)
            self.assertTrue(finalize_record["executed"])
            final_rows = splits_output.read_membership_gzip(Path(finalize_record["membership_path"]))
            self.assertEqual(len(final_rows), _SAMPLE_COUNT)
            # assign(2) + legacy(2) + 3 widths x 2 (exact_audit) + 3 probes x 2 (F1) + 18 searches x 2
            self.assertEqual(len(finalize_record["upstream"]), 2 + 2 + 3 * 2 + 3 * 2 + 18 * 2)


class RealBinarySmokeTests(unittest.TestCase):
    """A single tiny real-binary smoke covering one width probe and one
    directed search, in place of rerunning the full 3-probe/18-search
    directed pipeline for routine focused verification (docs/reviews/002c1_partition_orchestration_final_acceptance_correction.md,
    "Focused evidence only").
    """

    def test_one_probe_and_one_search_via_real_binary(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()

            probe_record = fx.audit_probe(width=500, assign_record=assign_record)
            self.assertTrue(probe_record["executed"])
            self.assertEqual(probe_record["stage"], "audit_probe")

            search_record = fx.audit_search(
                width=500, query_partition="train", target_partition="validation", assign_record=assign_record,
            )
            self.assertTrue(search_record["passed"])
            self.assertEqual(
                search_record["upstream"]["probe_generation_digest"], probe_record["generation_digest"]
            )


class FinalizeRefusalTests(unittest.TestCase):
    """NOTE: several of these tests exercise the real MMseqs2 binary across
    all 3 probes/18 searches. Per the reduced focused-test instructions,
    this class is not rerun as part of routine focused verification -- see
    ``RealBinarySmokeTests`` for the single tiny probe+search smoke that is.
    """

    def _assign_and_legacy(self, fx):
        assign_record = fx.assign()
        legacy_record = fx.legacy_diagnostic(assign_record=assign_record)
        return assign_record, legacy_record

    def _run_all_probes(self, fx, assign_record):
        for width in fx.config.protected_widths:
            fx.audit_probe(width=width, assign_record=assign_record)

    def _run_all_probes_and_searches(self, fx, assign_record, *, skip=None):
        self._run_all_probes(fx, assign_record)
        for width in fx.config.protected_widths:
            for query_partition, target_partition in mmseqs_audit.ORDERED_PARTITION_PAIRS:
                if skip is not None and (width, query_partition, target_partition) == skip:
                    continue
                fx.audit_search(width=width, query_partition=query_partition, target_partition=target_partition, assign_record=assign_record)

    def test_finalize_refuses_when_assign_is_missing(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            with self.assertRaises(restart.PriorStageNotAcceptedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)

    def test_finalize_refuses_when_legacy_diagnostic_is_missing(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            fx.assign()
            with self.assertRaises(restart.PriorStageNotAcceptedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)

    def test_finalize_refuses_when_an_exact_audit_width_is_missing(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record, _legacy = self._assign_and_legacy(fx)
            # Only run exact_audit for 2 of the 3 required widths.
            fx.exact_audit(width=500, assign_record=assign_record)
            fx.exact_audit(width=251, assign_record=assign_record)
            with self.assertRaises(restart.PriorStageNotAcceptedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)

    def test_finalize_refuses_when_a_probe_is_missing(self):
        # F1: finalize requires exactly the THREE width-scoped probes.
        # Running only 2 of the 3 (and skipping the third's dependent
        # searches too) already leaves finalize refusing on the missing
        # probe alone -- no real mmseqs run for the skipped width is needed.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record, _legacy = self._assign_and_legacy(fx)
            for width in fx.config.protected_widths:
                fx.exact_audit(width=width, assign_record=assign_record)
            fx.audit_probe(width=500, assign_record=assign_record)
            fx.audit_probe(width=251, assign_record=assign_record)
            # width 101's probe is deliberately never run/accepted.
            with self.assertRaises(restart.PriorStageNotAcceptedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)

    def test_finalize_refuses_when_only_one_direction_of_a_pair_is_present(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record, _legacy = self._assign_and_legacy(fx)
            for width in fx.config.protected_widths:
                fx.exact_audit(width=width, assign_record=assign_record)
            # Skip exactly ONE direction (validation->train at width 500) to
            # prove a one-direction-only pair still refuses.
            self._run_all_probes_and_searches(fx, assign_record, skip=(500, "validation", "train"))
            with self.assertRaises(restart.PriorStageNotAcceptedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)

    def test_finalize_refuses_when_an_audit_search_reports_a_violation(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record, _legacy = self._assign_and_legacy(fx)
            for width in fx.config.protected_widths:
                fx.exact_audit(width=width, assign_record=assign_record)
            self._run_all_probes_and_searches(fx, assign_record)
            # Tamper one accepted search record to simulate a discovered
            # cross-partition violation, and confirm finalize refuses on it.
            key = mmseqs_audit.selection_key("audit_search", 500, "train", "validation")
            record_path = restart.selected_record_path(fx.output_dir, key)
            record = json.loads(record_path.read_text())
            record["passed"] = False
            record["violation_count"] = 1
            record_path.write_text(json.dumps(record))
            with self.assertRaises(r002c.FinalizationRefusedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)

    def test_finalize_refuses_when_a_search_is_stale_against_its_probe_generation(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record, _legacy = self._assign_and_legacy(fx)
            for width in fx.config.protected_widths:
                fx.exact_audit(width=width, assign_record=assign_record)
            self._run_all_probes_and_searches(fx, assign_record)
            # Simulate a stale binding: the accepted search claims a probe
            # generation digest that no longer matches the currently
            # accepted (width-scoped, F1) probe.
            key = mmseqs_audit.selection_key("audit_search", 500, "train", "validation")
            record_path = restart.selected_record_path(fx.output_dir, key)
            record = json.loads(record_path.read_text())
            record["upstream"]["probe_generation_digest"] = "stale-digest-does-not-match"
            record_path.write_text(json.dumps(record))
            with self.assertRaises(r002c.FinalizationRefusedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)

    def test_finalize_refuses_when_assign_records_cached_summary_disagrees_with_independent_recompute(self):
        # C4: finalize must independently RECOMPUTE the summary from the
        # final membership plus a fresh CSV stream, never merely trust the
        # `assign` record's own cached `partition_row_counts`/
        # `minimum_count_report` fields.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record, _legacy = self._assign_and_legacy(fx)
            for width in fx.config.protected_widths:
                fx.exact_audit(width=width, assign_record=assign_record)
            self._run_all_probes_and_searches(fx, assign_record)

            assign_record_path = restart.selected_record_path(fx.output_dir, "assign")
            tampered = json.loads(assign_record_path.read_text())
            tampered["partition_row_counts"] = {
                p: c + 1000 for p, c in tampered["partition_row_counts"].items()
            }
            assign_record_path.write_text(json.dumps(tampered))
            with self.assertRaises(r002c.FinalizationRefusedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)


class SubprocessFailureDoesNotDamagePriorEvidenceTests(unittest.TestCase):
    def test_a_failed_audit_probe_leaves_no_accepted_record_and_discards_its_generation(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            with self.assertRaises(Exception):
                fx.audit_probe(width=500, assign_record=assign_record, mmseqs_bin="/definitely/not/a/real/mmseqs/binary")
            self.assertIsNone(restart.load_accepted(fx.output_dir, mmseqs_audit.probe_selection_key(500)))
            probe_dir = fx.output_dir / "audit_probe" / "500" / "generations"
            if probe_dir.exists():
                self.assertEqual(list(probe_dir.iterdir()), [])

    def test_failed_stage_never_damages_a_prior_accepted_assign_record(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            accepted_before = restart.load_accepted(fx.output_dir, "assign")
            self.assertIsNotNone(accepted_before)
            try:
                fx.audit_probe(width=500, assign_record=assign_record, mmseqs_bin="/definitely/not/a/real/mmseqs/binary")
            except Exception:
                pass
            accepted_after = restart.load_accepted(fx.output_dir, "assign")
            self.assertEqual(accepted_before, accepted_after)


if __name__ == "__main__":
    unittest.main()
