from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest

try:
    import torch
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("Task 004A-2 tests require PyTorch") from exc

from rbpbench.rescnn.data_004a2 import (
    CoverageSampler,
    ResCNN004A2DataError,
    SampleCandidate,
    audit_streams,
    build_cache_streams,
    canonical_content_sha256,
    decode_one_hot_bits,
    require_count_reconciliation,
)


def _fixture(*, malformed_development: bool = False):
    membership = ["sample_id\tcomponent_id\tpartition\n"]
    csv_rows = ["sequence,labels\n"]
    fasta = []
    bits = "1000" * 500
    for index in range(1027):
        if index < 513:
            partition = "train"
        elif index < 1026:
            partition = "validation"
        else:
            partition = "test"
        sample_id = f"row_{index}"
        membership.append(f"{sample_id}\tcomponent-{index}\t{partition}\n")
        if partition == "test":
            csv_rows.append("malformed-hidden-bits,malformed-hidden-labels\n")
            fasta.extend((f">{sample_id}\n", "N\n"))
            continue
        state = index % 3
        labels = ";".join(str(protein) for protein in range(1, 123)) if state == 0 else (
            ";".join(f"-{protein}" for protein in range(1, 123)) if state == 1 else ""
        )
        row_bits = "invalid" if malformed_development and index == 0 else bits
        csv_rows.append(f"{row_bits},{labels}\n")
        fasta.extend((f">{sample_id}\n", "A" * 500 + "\n"))
    return "".join(membership), "".join(csv_rows), "".join(fasta)


class StreamingBoundaryTests(unittest.TestCase):
    def test_malformed_test_fields_are_consumed_but_never_interpreted(self):
        membership, csv_rows, fasta = _fixture()
        audit = audit_streams(
            io.StringIO(membership), io.StringIO(csv_rows), io.StringIO(fasta),
            width=500, output_count=122, sample_size=513, seed=20261029,
            expected_partition_rows={"train": 513, "validation": 513, "test": 1},
            expected_component_count=1027,
        )
        self.assertEqual(audit.access, {
            "test_rows_seen": 1,
            "test_label_supplier_calls": 0,
            "test_csv_sequence_supplier_calls": 0,
            "test_fasta_sequence_interpretations": 0,
            "test_tensor_rows": 0,
            "test_prediction_rows": 0,
            "test_accessed": False,
        })
        self.assertEqual(len(audit.selected["train"]), 513)
        self.assertEqual(len(audit.selected["validation"]), 513)

        cache_result = build_cache_streams(
            io.StringIO(membership), io.StringIO(csv_rows), io.StringIO(fasta),
            selected=audit.selected, width=500, output_count=122,
        )
        require_count_reconciliation(audit.counts, cache_result.counts)
        self.assertEqual(cache_result.selected_content_sha256, audit.selected_content_sha256)
        self.assertEqual(cache_result.access["test_accessed"], False)
        self.assertEqual(cache_result.cache.base_codes.dtype, torch.uint8)
        self.assertEqual(cache_result.cache.targets.dtype, torch.uint8)
        self.assertEqual(cache_result.cache.masks.dtype, torch.uint8)
        self.assertEqual(tuple(cache_result.cache.base_codes.shape), (1026, 500))
        self.assertEqual(tuple(cache_result.cache.targets.shape), (1026, 122))
        self.assertNotIn("test", cache_result.cache.partitions)

    def test_same_malformed_sequence_in_development_fails(self):
        membership, csv_rows, fasta = _fixture(malformed_development=True)
        with self.assertRaisesRegex(ResCNN004A2DataError, "expected 2000"):
            audit_streams(
                io.StringIO(membership), io.StringIO(csv_rows), io.StringIO(fasta),
                width=500, output_count=122, sample_size=513, seed=20261029,
            )

    def test_lockstep_and_strict_one_hot_fail_closed(self):
        with self.assertRaises(ResCNN004A2DataError):
            decode_one_hot_bits("0000", width=1)
        with self.assertRaises(ResCNN004A2DataError):
            decode_one_hot_bits("1100", width=1)
        membership, csv_rows, fasta = _fixture()
        fasta = fasta.replace(">row_1", ">row_99", 1)
        with self.assertRaisesRegex(ResCNN004A2DataError, "lockstep ID mismatch"):
            audit_streams(
                io.StringIO(membership), io.StringIO(csv_rows), io.StringIO(fasta),
                width=500, output_count=122, sample_size=513, seed=20261029,
            )

    def test_sampler_is_bounded_deterministic_and_order_independent(self):
        def candidates():
            for index in range(600):
                labels = {1: index % 2, 2: (index + 1) % 2}
                content = canonical_content_sha256(
                    sample_id=f"row_{index}", component_id=f"c-{index}", partition="train",
                    base_codes=(0,), targets=(labels[1], labels[2]), masks=(1, 1),
                )
                yield SampleCandidate(f"row_{index}", f"c-{index}", "train", content), labels

        def run(rows):
            sampler = CoverageSampler(output_count=2, sample_size=17, seed=20261029)
            # Validation quotas must also be represented; mirror IDs into a disjoint canonical range.
            for candidate, labels in rows:
                sampler.observe(candidate, labels)
                mirror = SampleCandidate(
                    f"row_{candidate.row_index + 1000}", "v-" + candidate.component_id,
                    "validation", candidate.content_sha256,
                )
                sampler.observe(mirror, labels)
            return sampler.finalize()

        forward_rows = list(candidates())
        forward = run(forward_rows)
        reverse = run(reversed(forward_rows))
        self.assertEqual(forward, reverse)
        for partition in ("train", "validation"):
            self.assertEqual(len(forward[partition]), 17)
            self.assertEqual(len({row.sample_id for row in forward[partition]}), 17)

    def test_independent_count_matrix_not_whole_dataset_subtraction(self):
        membership, csv_rows, fasta = _fixture()
        audit = audit_streams(
            io.StringIO(membership), io.StringIO(csv_rows), io.StringIO(fasta),
            width=500, output_count=122, sample_size=513, seed=20261029,
        )
        cache = build_cache_streams(
            io.StringIO(membership), io.StringIO(csv_rows), io.StringIO(fasta),
            selected=audit.selected, width=500, output_count=122,
        )
        require_count_reconciliation(audit.counts, cache.counts)
        matrix = audit.counts.matrix()
        self.assertEqual(set(matrix), {"train", "validation"})
        self.assertNotIn("test", repr(matrix))


if __name__ == "__main__":
    unittest.main()
