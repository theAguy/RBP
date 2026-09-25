import csv
import random
import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.decode import encode_sequence
from rbpbench.splits.decode import (
    CENTER_WIDTHS,
    FULL_WIDTH,
    DecodeError,
    center_window,
    decode_row,
    iter_csv_one_hot_rows,
    iter_decode_rows,
    sample_id,
    stream_decode_to_fastas,
)


def _marker_sequence(width: int = FULL_WIDTH, seed: int = 1) -> str:
    """A deterministic, non-repeating synthetic nucleotide sequence (never
    the real dataset), so a crop's exact offset can be verified against an
    independently-computed slice rather than a trivially-repetitive string.
    """
    rng = random.Random(seed)
    return "".join(rng.choice("ACGT") for _ in range(width))


class SampleIdTests(unittest.TestCase):
    def test_canonical_row_ids(self):
        self.assertEqual(sample_id(0), "row_0")
        self.assertEqual(sample_id(41), "row_41")


class CenterWindowTests(unittest.TestCase):
    def test_full_width_is_identity(self):
        seq = _marker_sequence()
        self.assertEqual(center_window(seq, 500), seq)

    def test_251_crop_is_exact_deterministic_offset(self):
        seq = _marker_sequence()
        # start = floor((500 - 251) / 2) = 124
        expected = seq[124:375]
        self.assertEqual(center_window(seq, 251), expected)
        self.assertEqual(len(center_window(seq, 251)), 251)

    def test_101_crop_is_exact_deterministic_offset(self):
        seq = _marker_sequence()
        # start = floor((500 - 101) / 2) = 199
        expected = seq[199:300]
        self.assertEqual(center_window(seq, 101), expected)
        self.assertEqual(len(center_window(seq, 101)), 101)

    def test_crop_is_reproducible_across_calls(self):
        seq = _marker_sequence()
        self.assertEqual(center_window(seq, 251), center_window(seq, 251))
        self.assertEqual(center_window(seq, 101), center_window(seq, 101))

    def test_width_exceeding_sequence_rejected(self):
        with self.assertRaises(ValueError):
            center_window("ACGT", 500)

    def test_non_positive_width_rejected(self):
        with self.assertRaises(ValueError):
            center_window("ACGT" * 125, 0)


class DecodeRowTests(unittest.TestCase):
    def test_decode_row_produces_all_three_widths(self):
        seq = _marker_sequence()
        bits = encode_sequence(seq)
        decoded = decode_row(7, bits)
        self.assertEqual(decoded.row_index, 7)
        self.assertEqual(decoded.sample_id, "row_7")
        self.assertEqual(set(decoded.windows.keys()), set(CENTER_WIDTHS))
        self.assertEqual(decoded.windows[500], seq)
        self.assertEqual(decoded.windows[251], center_window(seq, 251))
        self.assertEqual(decoded.windows[101], center_window(seq, 101))

    def test_strict_decode_failure_wrong_length_fails_closed(self):
        with self.assertRaises(DecodeError) as ctx:
            decode_row(3, "1000")  # 4 bits -> 1 base, not 500
        self.assertEqual(ctx.exception.row_index, 3)
        self.assertEqual(ctx.exception.sample_id, "row_3")

    def test_strict_decode_failure_not_one_hot_fails_closed(self):
        bits = encode_sequence(_marker_sequence())
        corrupted = "11" + bits[2:]  # first group no longer exactly one-hot
        with self.assertRaises(DecodeError):
            decode_row(0, corrupted)

    def test_strict_decode_failure_non_binary_character_fails_closed(self):
        bits = encode_sequence(_marker_sequence())
        corrupted = "X" + bits[1:]
        with self.assertRaises(DecodeError):
            decode_row(0, corrupted)

    def test_strict_decode_never_repairs_silently(self):
        # A round-trip mismatch (impossible via decode_sequence's own
        # one-hot check alone, but decode_and_validate's extra round-trip
        # guard must still be exercised through decode_row): wrong length
        # entirely by one base.
        bits = encode_sequence(_marker_sequence())[:-4]
        with self.assertRaises(DecodeError):
            decode_row(0, bits)


class IterDecodeRowsTests(unittest.TestCase):
    def test_streams_multiple_rows(self):
        rows = [(0, encode_sequence(_marker_sequence(seed=1))), (1, encode_sequence(_marker_sequence(seed=2)))]
        decoded = list(iter_decode_rows(rows))
        self.assertEqual([d.sample_id for d in decoded], ["row_0", "row_1"])

    def test_first_bad_row_aborts_the_stream(self):
        rows = [(0, encode_sequence(_marker_sequence())), (1, "bad"), (2, encode_sequence(_marker_sequence()))]

        def consume():
            return list(iter_decode_rows(rows))

        with self.assertRaises(DecodeError) as ctx:
            consume()
        self.assertEqual(ctx.exception.row_index, 1)


class IterCsvOneHotRowsTests(unittest.TestCase):
    def test_streams_rows_ignoring_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tiny.csv"
            with csv_path.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["sequence", "labels"])
                writer.writerow([encode_sequence(_marker_sequence()), "1;-2"])
                writer.writerow([encode_sequence(_marker_sequence()), ""])
            rows = list(iter_csv_one_hot_rows(csv_path))
            self.assertEqual([r[0] for r in rows], [0, 1])
            self.assertEqual(rows[0][1], encode_sequence(_marker_sequence()))


class StreamDecodeToFastasTests(unittest.TestCase):
    def _write_csv(self, csv_path: Path, sequences: list[str]) -> None:
        with csv_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sequence", "labels"])
            for seq in sequences:
                writer.writerow([encode_sequence(seq), ""])

    def test_writes_three_fastas_with_canonical_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "tiny.csv"
            seq_a = _marker_sequence(seed=1)
            seq_b = _marker_sequence(seed=2)
            self._write_csv(csv_path, [seq_a, seq_b])

            out_dir = tmp_path / "out"
            report = stream_decode_to_fastas(csv_path, out_dir)

            self.assertEqual(report.total_rows, 2)
            self.assertEqual(report.accepted_sample_ids, ("row_0", "row_1"))
            for width in CENTER_WIDTHS:
                path = report.output_paths[width]
                self.assertTrue(path.is_file())
                text = path.read_text()
                self.assertIn(">row_0\n", text)
                self.assertIn(">row_1\n", text)
                self.assertIn(center_window(seq_a, width), text)
                self.assertIn(center_window(seq_b, width), text)

    def test_strict_failure_promotes_nothing_and_leaves_prior_output_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"

            good_csv = tmp_path / "good.csv"
            self._write_csv(good_csv, [_marker_sequence()])
            first_report = stream_decode_to_fastas(good_csv, out_dir)
            accepted_bytes = {w: p.read_bytes() for w, p in first_report.output_paths.items()}

            bad_csv = tmp_path / "bad.csv"
            with bad_csv.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["sequence", "labels"])
                writer.writerow([encode_sequence(_marker_sequence()), ""])
                writer.writerow(["not-valid-bits", ""])

            with self.assertRaises(DecodeError):
                stream_decode_to_fastas(bad_csv, out_dir)

            # The prior accepted generation's files must be byte-identical
            # to before the failed re-run attempted to overwrite them.
            for width, path in first_report.output_paths.items():
                self.assertEqual(path.read_bytes(), accepted_bytes[width])
            # No stray .tmp files left behind.
            leftover_tmp = list(out_dir.glob("*.tmp"))
            self.assertEqual(leftover_tmp, [])

    def test_empty_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "empty.csv"
            with csv_path.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["sequence", "labels"])
            with self.assertRaises(DecodeError):
                stream_decode_to_fastas(csv_path, tmp_path / "out")


if __name__ == "__main__":
    unittest.main()
