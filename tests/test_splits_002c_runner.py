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
JSON, tiny dataset-audit/proteins-table stand-ins, and tiny per-width
similarity/exact-RC edge files. No real CSV, accepted Task 002B artifact,
or real MMseqs2 execution over real sequences is ever touched.
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
        self.similarity_edges_dir = root / "similarity_edges"
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
        self.config_path.write_text(text)

        self.decode_fasta_dir.mkdir(parents=True, exist_ok=True)
        for width in _PROTECTED_WIDTHS:
            fasta_path = self.decode_fasta_dir / f"width_{width}.fasta"
            sequences = _SEQUENCES_BY_WIDTH[width]
            with fasta_path.open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")

        self.similarity_edges_dir.mkdir(parents=True, exist_ok=True)
        for width in _PROTECTED_WIDTHS:
            (self.similarity_edges_dir / f"edges_{width}.json").write_text("[]")
            (self.similarity_edges_dir / f"exact_rc_edges_{width}.json").write_text("[]")

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
            similarity_edges_dir=self.similarity_edges_dir,
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
            record = r002c.stage_exact_audit(width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)
            self.assertTrue(record["passed"])
            self.assertEqual(record["violation_count"], 0)

    def test_width_outside_protected_widths_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            with self.assertRaises(r002c.StageValidationError):
                r002c.stage_exact_audit(width=999, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)

    def test_exact_audit_invalidated_by_a_changed_upstream_assignment(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            fp1 = r002c.exact_audit_fingerprint(
                config=fx.config, width=500, assign_stage_fingerprint=assign_record["stage_fingerprint"],
                assign_generation_digest=assign_record["generation_digest"], fasta_sha256="ignored-for-this-comparison",
            )
            # A different (simulated) assign stage_fingerprint must produce a
            # different exact_audit fingerprint, so a rerun after a real
            # upstream change is never mistaken for still-current.
            fp2 = r002c.exact_audit_fingerprint(
                config=fx.config, width=500, assign_stage_fingerprint="a-different-assign-fingerprint",
                assign_generation_digest=assign_record["generation_digest"], fasta_sha256="ignored-for-this-comparison",
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
            )
            fp2 = r002c.exact_audit_fingerprint(
                config=fx.config, width=500, assign_stage_fingerprint=rebuilt["stage_fingerprint"],
                assign_generation_digest=rebuilt["generation_digest"], fasta_sha256="x",
            )
            self.assertNotEqual(fp1, fp2)

    def test_duplicate_fasta_header_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            bad_dir = fx.root / "dup_decode"
            bad_dir.mkdir()
            sequences = _SEQUENCES_BY_WIDTH[500]
            with (bad_dir / "width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
                # Duplicate the very first header.
                first_id = sorted(sequences)[0]
                handle.write(f">{first_id}\n{sequences[first_id]}\n")
            with self.assertRaises(r002c.FastaValidationError):
                r002c.stage_exact_audit(width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=bad_dir, assign_record=assign_record)

    def test_wrong_width_sequence_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            bad_dir = fx.root / "wrong_width_decode"
            bad_dir.mkdir()
            # Reuse the 251-nt sequences under a "width_500" filename.
            sequences = _SEQUENCES_BY_WIDTH[251]
            with (bad_dir / "width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            with self.assertRaises(r002c.FastaValidationError):
                r002c.stage_exact_audit(width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=bad_dir, assign_record=assign_record)

    def test_missing_id_in_fasta_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            bad_dir = fx.root / "missing_id_decode"
            bad_dir.mkdir()
            sequences = dict(_SEQUENCES_BY_WIDTH[500])
            del sequences["row_0"]
            with (bad_dir / "width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            with self.assertRaises(r002c.FastaValidationError):
                r002c.stage_exact_audit(width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=bad_dir, assign_record=assign_record)

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
            with (bad_dir / "width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            with self.assertRaises(r002c.FastaValidationError):
                r002c.stage_exact_audit(width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=bad_dir, assign_record=assign_record)

    def test_changed_fasta_content_produces_a_different_exact_audit_fingerprint(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            record1 = r002c.stage_exact_audit(width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)

            # Mutate one sequence's content (same ID, same width) so the
            # FASTA file's hash changes without touching anything else.
            mutated_dir = fx.root / "mutated_decode"
            mutated_dir.mkdir()
            sequences = dict(_SEQUENCES_BY_WIDTH[500])
            first_id = sorted(sequences)[0]
            seq = sequences[first_id]
            swapped = ("C" if seq[0] != "C" else "G") + seq[1:]
            sequences[first_id] = swapped
            with (mutated_dir / "width_500.fasta").open("w") as handle:
                for sample_id in sorted(sequences):
                    handle.write(f">{sample_id}\n{sequences[sample_id]}\n")
            record2 = r002c.stage_exact_audit(width=500, config=fx.config, output_dir=fx.output_dir / "mutated_run", decode_fasta_dir=mutated_dir, assign_record=assign_record)
            self.assertNotEqual(record1["fasta_sha256"], record2["fasta_sha256"])
            self.assertNotEqual(record1["stage_fingerprint"], record2["stage_fingerprint"])


class DryRunAndAuthorizationTests(unittest.TestCase):
    def test_audit_probe_dry_run_never_opens_declared_inputs(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            result = r002c.stage_audit_probe(
                width=500, query_partition="train", target_partition="validation", config=fx.config,
                output_dir=fx.output_dir, decode_fasta_dir=Path("/does/not/exist"), assign_record={},
                authorize=False, mmseqs_bin="mmseqs-does-not-exist", dry_run=True,
            )
            self.assertTrue(result["dry_run"])
            self.assertFalse(fx.output_dir.exists())

    def test_audit_probe_without_authorization_raises_before_any_file_access(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            with self.assertRaises(r002c.AuthorizationError):
                r002c.stage_audit_probe(
                    width=500, query_partition="train", target_partition="validation", config=fx.config,
                    output_dir=fx.output_dir, decode_fasta_dir=Path("/does/not/exist"), assign_record={},
                    authorize=False, mmseqs_bin="mmseqs-does-not-exist", dry_run=False,
                )
            self.assertFalse(fx.output_dir.exists())

    def test_dry_run_is_checked_before_authorization(self):
        # Even without --authorize-mmseqs, --dry-run alone must return the
        # dry-run report rather than raising AuthorizationError.
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            result = r002c.stage_audit_search(
                width=500, query_partition="train", target_partition="validation", config=fx.config,
                output_dir=fx.output_dir, decode_fasta_dir=Path("/does/not/exist"), assign_record={},
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
            with self.assertRaises(r002c.guarded_exec.ResourceGateExceededError):
                r002c.stage_audit_probe(
                    width=500, query_partition="train", target_partition="validation", config=config,
                    output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record,
                    authorize=True, mmseqs_bin=fx.mmseqs_bin,
                )
            probe_dir = fx.output_dir / "audit_probe" / "500" / "train_to_validation" / "generations"
            self.assertFalse(probe_dir.exists())

    def test_unreachable_min_available_memory_before_launch_refuses(self):
        import dataclasses

        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            config = dataclasses.replace(
                fx.config,
                audit=dataclasses.replace(fx.config.audit, min_available_memory_gib_before_launch=1_000_000.0),
            )
            with self.assertRaises(r002c.guarded_exec.ResourceGateExceededError):
                r002c.stage_audit_probe(
                    width=500, query_partition="train", target_partition="validation", config=config,
                    output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record,
                    authorize=True, mmseqs_bin=fx.mmseqs_bin,
                )


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
        with self.assertRaises(r002c.StageValidationError):
            r002c.main(["--stage", "audit_probe", "--width", "500", "--config", "/does/not/exist.toml"])

    def test_mmseqs_stage_without_authorization_raises_before_config_load_via_cli(self):
        with self.assertRaises(r002c.AuthorizationError):
            r002c.main([
                "--stage", "audit_probe", "--width", "500", "--query-partition", "train",
                "--target-partition", "validation", "--config", "/does/not/exist.toml",
            ])

    def test_legacy_diagnostic_without_similarity_edges_dir_raises_via_cli(self):
        with self.assertRaises(r002c.StageValidationError):
            r002c.main(["--stage", "legacy_diagnostic", "--config", "/does/not/exist.toml"])

    def test_same_query_and_target_partition_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            with self.assertRaises(mmseqs_audit.InvalidDirectionError):
                r002c.stage_audit_probe(
                    width=500, query_partition="train", target_partition="train", config=fx.config,
                    output_dir=fx.output_dir, decode_fasta_dir=Path("/tmp"), assign_record={}, authorize=True,
                    dry_run=False,
                )


class LegacyDiagnosticCompletenessTests(unittest.TestCase):
    def test_missing_edges_file_for_one_width_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            (fx.similarity_edges_dir / "edges_101.json").unlink()
            with self.assertRaises(r002c.InputValidationError):
                fx.legacy_diagnostic(assign_record=assign_record)

    def test_missing_exact_rc_edges_file_for_one_width_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            (fx.similarity_edges_dir / "exact_rc_edges_251.json").unlink()
            with self.assertRaises(r002c.InputValidationError):
                fx.legacy_diagnostic(assign_record=assign_record)

    def test_complete_edges_produce_a_full_embedded_report(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            record = fx.legacy_diagnostic(assign_record=assign_record)
            self.assertIn("report", record)
            for width in _PROTECTED_WIDTHS:
                self.assertIn(str(width), record["report"]["directly_edge_matched_by_width"])
                self.assertIn(str(width), record["report"]["exact_rc_by_width"])


class FullPipelineEndToEndTests(unittest.TestCase):
    """The complete assign -> legacy_diagnostic -> exact_audit (x3 widths) ->
    audit_probe/audit_search (x18 directed) -> finalize chain, using the
    accepted local MMseqs2 binary and tiny synthetic fixtures throughout.
    """

    def test_full_pipeline_promotes_to_finalize(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))

            assign_record = fx.assign()
            self.assertTrue(assign_record["minimum_count_report"]["passed"])

            legacy_record = fx.legacy_diagnostic(assign_record=assign_record)
            self.assertTrue(legacy_record["executed"])

            for width in fx.config.protected_widths:
                exact_record = r002c.stage_exact_audit(width=width, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)
                self.assertTrue(exact_record["passed"])

            for width in fx.config.protected_widths:
                for query_partition, target_partition in mmseqs_audit.ORDERED_PARTITION_PAIRS:
                    probe_record = r002c.stage_audit_probe(
                        width=width, query_partition=query_partition, target_partition=target_partition,
                        config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir,
                        assign_record=assign_record, authorize=True, mmseqs_bin=fx.mmseqs_bin,
                    )
                    self.assertTrue(probe_record["executed"])
                    search_record = r002c.stage_audit_search(
                        width=width, query_partition=query_partition, target_partition=target_partition,
                        config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir,
                        assign_record=assign_record, authorize=True, mmseqs_bin=fx.mmseqs_bin,
                    )
                    self.assertTrue(search_record["passed"])
                    self.assertEqual(
                        search_record["upstream"]["probe_generation_digest"], probe_record["generation_digest"]
                    )

            finalize_record = r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)
            self.assertTrue(finalize_record["executed"])
            final_rows = splits_output.read_membership_gzip(Path(finalize_record["membership_path"]))
            self.assertEqual(len(final_rows), _SAMPLE_COUNT)
            # assign(2) + legacy(2) + 3 widths x 2 (exact_audit) + 18 probes x 2 + 18 searches x 2
            self.assertEqual(len(finalize_record["upstream"]), 2 + 2 + 3 * 2 + 18 * 2 + 18 * 2)


class FinalizeRefusalTests(unittest.TestCase):
    def _assign_and_legacy(self, fx):
        assign_record = fx.assign()
        legacy_record = fx.legacy_diagnostic(assign_record=assign_record)
        return assign_record, legacy_record

    def _run_all_probes_and_searches(self, fx, assign_record, *, skip=None):
        for width in fx.config.protected_widths:
            for query_partition, target_partition in mmseqs_audit.ORDERED_PARTITION_PAIRS:
                if skip is not None and (width, query_partition, target_partition) == skip:
                    continue
                r002c.stage_audit_probe(
                    width=width, query_partition=query_partition, target_partition=target_partition,
                    config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir,
                    assign_record=assign_record, authorize=True, mmseqs_bin=fx.mmseqs_bin,
                )
                r002c.stage_audit_search(
                    width=width, query_partition=query_partition, target_partition=target_partition,
                    config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir,
                    assign_record=assign_record, authorize=True, mmseqs_bin=fx.mmseqs_bin,
                )

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
            r002c.stage_exact_audit(width=500, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)
            r002c.stage_exact_audit(width=251, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)
            with self.assertRaises(restart.PriorStageNotAcceptedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)

    def test_finalize_refuses_when_a_probe_is_missing(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record, _legacy = self._assign_and_legacy(fx)
            for width in fx.config.protected_widths:
                r002c.stage_exact_audit(width=width, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)
            # Run every search, but skip exactly one probe (search still
            # requires its own probe internally, so run that pair's search
            # via a probe generated then discarded from the selected store).
            for width in fx.config.protected_widths:
                for query_partition, target_partition in mmseqs_audit.ORDERED_PARTITION_PAIRS:
                    r002c.stage_audit_probe(
                        width=width, query_partition=query_partition, target_partition=target_partition,
                        config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir,
                        assign_record=assign_record, authorize=True, mmseqs_bin=fx.mmseqs_bin,
                    )
                    r002c.stage_audit_search(
                        width=width, query_partition=query_partition, target_partition=target_partition,
                        config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir,
                        assign_record=assign_record, authorize=True, mmseqs_bin=fx.mmseqs_bin,
                    )
            # Now remove one accepted probe's selection record entirely.
            probe_key = mmseqs_audit.selection_key("audit_probe", 500, "train", "validation")
            restart.selected_record_path(fx.output_dir, probe_key).unlink()
            with self.assertRaises(restart.PriorStageNotAcceptedError):
                r002c.stage_finalize(config=fx.config, output_dir=fx.output_dir)

    def test_finalize_refuses_when_only_one_direction_of_a_pair_is_present(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record, _legacy = self._assign_and_legacy(fx)
            for width in fx.config.protected_widths:
                r002c.stage_exact_audit(width=width, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)
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
                r002c.stage_exact_audit(width=width, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)
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
                r002c.stage_exact_audit(width=width, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)
            self._run_all_probes_and_searches(fx, assign_record)
            # Simulate a stale binding: the accepted search claims a probe
            # generation digest that no longer matches the currently
            # accepted probe.
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
                r002c.stage_exact_audit(width=width, config=fx.config, output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record)
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
                r002c.stage_audit_probe(
                    width=500, query_partition="train", target_partition="validation", config=fx.config,
                    output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record,
                    authorize=True, mmseqs_bin="/definitely/not/a/real/mmseqs/binary",
                )
            self.assertIsNone(restart.load_accepted(fx.output_dir, mmseqs_audit.selection_key("audit_probe", 500, "train", "validation")))
            probe_dir = fx.output_dir / "audit_probe" / "500" / "train_to_validation" / "generations"
            if probe_dir.exists():
                self.assertEqual(list(probe_dir.iterdir()), [])

    def test_failed_stage_never_damages_a_prior_accepted_assign_record(self):
        with TemporaryDirectory() as tmp:
            fx = _build_fixture(Path(tmp))
            assign_record = fx.assign()
            accepted_before = restart.load_accepted(fx.output_dir, "assign")
            self.assertIsNotNone(accepted_before)
            try:
                r002c.stage_audit_probe(
                    width=500, query_partition="train", target_partition="validation", config=fx.config,
                    output_dir=fx.output_dir, decode_fasta_dir=fx.decode_fasta_dir, assign_record=assign_record,
                    authorize=True, mmseqs_bin="/definitely/not/a/real/mmseqs/binary",
                )
            except Exception:
                pass
            accepted_after = restart.load_accepted(fx.output_dir, "assign")
            self.assertEqual(accepted_before, accepted_after)


if __name__ == "__main__":
    unittest.main()
