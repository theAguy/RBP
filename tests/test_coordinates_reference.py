"""Regression coverage for review item 2: the canonical-junction reference
lookup must use indexed random access (never a whole-file load) so it is
suitable for hg38/hg19-scale references, with a sequential index
preparation/checking workflow that records index commands and hashes.
"""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.reference import (
    IndexedFastaReader,
    build_fasta_index,
    load_fasta_sequences,
    prepare_reference_index,
)


def _wrap(sequence: str, width: int) -> str:
    return "\n".join(sequence[i : i + width] for i in range(0, len(sequence), width))


class IndexedFastaReaderTests(unittest.TestCase):
    def setUp(self):
        random.seed(20260916)
        self.seq_a = "".join(random.choice("ACGT") for _ in range(237))  # not a multiple of the line width
        self.seq_b = "".join(random.choice("ACGT") for _ in range(53))
        self.tmp = tempfile.TemporaryDirectory()
        self.fasta_path = Path(self.tmp.name) / "tiny_reference.fasta"
        self.fasta_path.write_text(f">chrA some description\n{_wrap(self.seq_a, 10)}\n>chrB\n{_wrap(self.seq_b, 10)}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_indexed_random_access_matches_whole_file_load(self):
        whole = load_fasta_sequences(self.fasta_path)
        self.assertEqual(whole["chrA"], self.seq_a)
        self.assertEqual(whole["chrB"], self.seq_b)

        entries = build_fasta_index(self.fasta_path)
        reader = IndexedFastaReader(self.fasta_path, entries)

        rng = random.Random(1)
        for chrom, sequence in (("chrA", self.seq_a), ("chrB", self.seq_b)):
            for _ in range(100):
                start = rng.randint(0, len(sequence) - 1)
                end = rng.randint(start + 1, len(sequence))
                self.assertEqual(reader.fetch(chrom, start, end), sequence[start:end])

    def test_span_crossing_multiple_lines(self):
        entries = build_fasta_index(self.fasta_path)
        reader = IndexedFastaReader(self.fasta_path, entries)
        # Spans a line boundary (line width is 10) and the final short line.
        self.assertEqual(reader.fetch("chrA", 8, 23), self.seq_a[8:23])
        self.assertEqual(reader.fetch("chrA", 0, len(self.seq_a)), self.seq_a)
        self.assertEqual(reader.fetch("chrB", 45, 53), self.seq_b[45:53])

    def test_out_of_range_and_unknown_contig_return_empty(self):
        entries = build_fasta_index(self.fasta_path)
        reader = IndexedFastaReader(self.fasta_path, entries)
        self.assertEqual(reader.fetch("chrA", 5, 5), "")
        self.assertEqual(reader.fetch("chrA", 0, len(self.seq_a) + 1), "")
        self.assertEqual(reader.fetch("chrZ", 0, 5), "")

    def test_never_loads_the_file_whole(self):
        # A whole-file read would call Path.open().read(); this asserts the
        # reader instead performs bounded seeks by checking that fetching a
        # small span reads far fewer bytes than the file's total size.
        import unittest.mock as mock

        entries = build_fasta_index(self.fasta_path)
        reader = IndexedFastaReader(self.fasta_path, entries)
        real_open = Path.open
        read_sizes = []

        def spying_open(self_path, *args, **kwargs):
            handle = real_open(self_path, *args, **kwargs)
            original_read = handle.read

            def spying_read(n=-1):
                if n and n > 0:
                    read_sizes.append(n)
                return original_read(n)

            handle.read = spying_read
            return handle

        with mock.patch.object(Path, "open", spying_open):
            reader.fetch("chrA", 10, 20)

        total_file_size = self.fasta_path.stat().st_size
        self.assertTrue(read_sizes)
        self.assertLess(max(read_sizes), total_file_size)


class PrepareReferenceIndexTests(unittest.TestCase):
    """Sequential index preparation/checking workflow: build once, reuse
    when the reference is unchanged, rebuild when it changes, and record
    index commands/hashes/sizes for provenance.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reference = Path(self.tmp.name) / "ref.fasta"
        self.reference.write_text(">chr1\n" + "ACGTACGTAC" * 5 + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_call_builds_index_and_records_provenance(self):
        entries, record = prepare_reference_index(self.reference)
        self.assertEqual(len(entries), 1)
        self.assertFalse(record["reused_existing_index"])
        self.assertIn("faidx", record["command"])
        self.assertEqual(len(record["reference_sha256"]), 64)
        self.assertEqual(len(record["index_sha256"]), 64)
        self.assertGreater(record["index_byte_size"], 0)
        self.assertEqual(record["num_contigs"], 1)
        self.assertTrue(Path(record["index_path"]).is_file())

    def test_second_call_reuses_the_cached_index_when_reference_is_unchanged(self):
        entries1, record1 = prepare_reference_index(self.reference)
        entries2, record2 = prepare_reference_index(self.reference)
        self.assertTrue(record2["reused_existing_index"])
        self.assertEqual(entries1, entries2)
        self.assertEqual(record1["reference_sha256"], record2["reference_sha256"])

    def test_changed_reference_invalidates_the_cached_index(self):
        prepare_reference_index(self.reference)
        # Same path, different content (and different length, to also
        # exercise a structurally different index).
        self.reference.write_text(">chr1\n" + "TTTTGGGGCCCCAAAA" * 3 + "\n>chr2\nACGT\n")
        entries, record = prepare_reference_index(self.reference)
        self.assertFalse(record["reused_existing_index"])
        self.assertEqual(record["num_contigs"], 2)


if __name__ == "__main__":
    unittest.main()
