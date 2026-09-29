import gzip
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rbpbench.splits import output as splits_output
from rbpbench.splits.ingestion import (
    ComponentIngestionError,
    LabelParseError,
    load_component_membership,
    parse_signed_labels,
    stream_component_label_aggregates,
    to_component_label_counts,
    verify_component_membership_file,
)

_HEX_A = "a" * 64
_HEX_B = "b" * 64
_HEX_C = "c" * 64


def _write_membership_gzip(path: Path, rows) -> None:
    splits_output.write_deterministic_component_membership_gzip(rows, path)


class VerifyMembershipFileTests(unittest.TestCase):
    def test_wrong_hash_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A)])
            with self.assertRaises(ComponentIngestionError):
                verify_component_membership_file(path, expected_sha256="0" * 64, expected_byte_size=path.stat().st_size)

    def test_wrong_byte_size_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A)])
            with self.assertRaises(ComponentIngestionError):
                verify_component_membership_file(path, expected_sha256=_sha(path), expected_byte_size=path.stat().st_size + 1)

    def test_correct_hash_and_size_are_accepted(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A)])
            import hashlib

            expected_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            actual = verify_component_membership_file(path, expected_sha256=expected_sha256, expected_byte_size=path.stat().st_size)
            self.assertEqual(actual, expected_sha256)

    def test_missing_file_is_rejected(self):
        with self.assertRaises(ComponentIngestionError):
            verify_component_membership_file(Path("/nonexistent/path.tsv.gz"), expected_sha256="0" * 64, expected_byte_size=1)


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class LoadComponentMembershipTests(unittest.TestCase):
    def test_exact_canonical_universe_is_accepted(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            rows = [("row_0", _HEX_A), ("row_1", _HEX_A), ("row_2", _HEX_B)]
            _write_membership_gzip(path, rows)
            universe = load_component_membership(path, expected_sample_count=3, expected_component_count=2)
            self.assertEqual(universe.sample_to_component["row_0"], _HEX_A)
            self.assertEqual(universe.component_sizes[_HEX_A], 2)
            self.assertEqual(universe.component_sizes[_HEX_B], 1)

    def test_missing_expected_id_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A)])  # row_1 missing
            with self.assertRaises(ComponentIngestionError) as ctx:
                load_component_membership(path, expected_sample_count=2, expected_component_count=1)
            self.assertIn("missing", str(ctx.exception))

    def test_foreign_id_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A), ("row_99", _HEX_A)])
            with self.assertRaises(ComponentIngestionError) as ctx:
                load_component_membership(path, expected_sample_count=1, expected_component_count=1)
            self.assertIn("foreign", str(ctx.exception))

    def test_duplicate_sample_id_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A), ("row_0", _HEX_B)])
            with self.assertRaises(ComponentIngestionError) as ctx:
                load_component_membership(path, expected_sample_count=1, expected_component_count=1)
            self.assertIn("duplicate", str(ctx.exception))

    def test_non_hex64_component_id_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", "not-a-hash")])
            with self.assertRaises(ComponentIngestionError) as ctx:
                load_component_membership(path, expected_sample_count=1, expected_component_count=1)
            self.assertIn("64-hex", str(ctx.exception))

    def test_uppercase_hex_component_id_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A.upper())])
            with self.assertRaises(ComponentIngestionError):
                load_component_membership(path, expected_sample_count=1, expected_component_count=1)

    def test_wrong_component_count_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A), ("row_1", _HEX_B)])
            with self.assertRaises(ComponentIngestionError) as ctx:
                load_component_membership(path, expected_sample_count=2, expected_component_count=1)
            self.assertIn("component count", str(ctx.exception))

    def test_component_size_map_mismatch_against_accepted_report_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A), ("row_1", _HEX_A)])
            with self.assertRaises(ComponentIngestionError) as ctx:
                load_component_membership(
                    path, expected_sample_count=2, expected_component_count=1,
                    expected_component_sizes={_HEX_A: 5},  # accepted report says size 5, actual is 2
                )
            self.assertIn("does not exactly match", str(ctx.exception))

    def test_fixture_hashes_can_never_satisfy_production_expectations(self):
        # A tiny fixture file will simply fail the production config's real
        # expected hash/size by construction -- no special-casing needed.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "membership.tsv.gz"
            _write_membership_gzip(path, [("row_0", _HEX_A)])
            with self.assertRaises(ComponentIngestionError):
                verify_component_membership_file(
                    path,
                    expected_sha256="6000c340056ba8204432e7f4c417fb811f8a3d1a5b1c091dea98461862c7b692",
                    expected_byte_size=14578797,
                )


class ParseSignedLabelsTests(unittest.TestCase):
    def test_empty_field_is_all_unknown(self):
        self.assertEqual(parse_signed_labels(""), {})

    def test_positive_and_negative_tokens(self):
        self.assertEqual(parse_signed_labels("+1;-2;+3"), {1: 1, 2: -1, 3: 1})

    def test_absent_protein_never_appears(self):
        result = parse_signed_labels("+1")
        self.assertNotIn(2, result)

    def test_zero_is_rejected(self):
        with self.assertRaises(LabelParseError):
            parse_signed_labels("+0")

    def test_out_of_range_high_is_rejected(self):
        with self.assertRaises(LabelParseError):
            parse_signed_labels("+123")

    def test_out_of_range_low_is_rejected_with_custom_bounds(self):
        with self.assertRaises(LabelParseError):
            parse_signed_labels("+1", protein_id_min=2, protein_id_max=122)

    def test_missing_sign_is_rejected(self):
        with self.assertRaises(LabelParseError):
            parse_signed_labels("5")

    def test_malformed_id_is_rejected(self):
        with self.assertRaises(LabelParseError):
            parse_signed_labels("+5a")

    def test_repeated_same_sign_is_rejected(self):
        with self.assertRaises(LabelParseError):
            parse_signed_labels("+1;+1")

    def test_contradictory_signs_are_rejected(self):
        with self.assertRaises(LabelParseError):
            parse_signed_labels("+1;-1")

    def test_empty_token_is_rejected(self):
        with self.assertRaises(LabelParseError):
            parse_signed_labels("+1;;+2")


class StreamComponentLabelAggregatesTests(unittest.TestCase):
    def test_aggregates_size_and_known_counts_without_dense_matrix(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tiny.csv"
            csv_path.write_text("sequence,labels\nAAAA,+1;-2\nCCCC,+1\nGGGG,\n")
            from rbpbench.splits.ingestion import ComponentUniverse

            universe = ComponentUniverse(
                sample_to_component={"row_0": _HEX_A, "row_1": _HEX_A, "row_2": _HEX_B},
                component_sizes={_HEX_A: 2, _HEX_B: 1},
            )
            aggregates = stream_component_label_aggregates(csv_path, universe)
            self.assertEqual(aggregates[_HEX_A].size, 2)
            self.assertEqual(aggregates[_HEX_A].label_counts[1], [2, 0])
            self.assertEqual(aggregates[_HEX_A].label_counts[2], [0, 1])
            self.assertEqual(aggregates[_HEX_B].size, 1)
            self.assertEqual(aggregates[_HEX_B].label_counts, {})

    def test_csv_row_absent_from_universe_is_rejected(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tiny.csv"
            csv_path.write_text("sequence,labels\nAAAA,+1\n")
            from rbpbench.splits.ingestion import ComponentUniverse

            universe = ComponentUniverse(sample_to_component={}, component_sizes={})
            with self.assertRaises(ComponentIngestionError):
                stream_component_label_aggregates(csv_path, universe)

    def test_universe_id_missing_from_csv_is_rejected(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tiny.csv"
            csv_path.write_text("sequence,labels\nAAAA,+1\n")
            from rbpbench.splits.ingestion import ComponentUniverse

            universe = ComponentUniverse(
                sample_to_component={"row_0": _HEX_A, "row_1": _HEX_A}, component_sizes={_HEX_A: 2}
            )
            with self.assertRaises(ComponentIngestionError) as ctx:
                stream_component_label_aggregates(csv_path, universe)
            self.assertIn("missing", str(ctx.exception))

    def test_aggregated_size_mismatch_against_universe_is_rejected(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tiny.csv"
            csv_path.write_text("sequence,labels\nAAAA,+1\n")
            from rbpbench.splits.ingestion import ComponentUniverse

            universe = ComponentUniverse(sample_to_component={"row_0": _HEX_A}, component_sizes={_HEX_A: 5})
            with self.assertRaises(ComponentIngestionError) as ctx:
                stream_component_label_aggregates(csv_path, universe)
            self.assertIn("aggregated size", str(ctx.exception))

    def test_to_component_label_counts_round_trips(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tiny.csv"
            csv_path.write_text("sequence,labels\nAAAA,+1\nCCCC,-1\n")
            from rbpbench.splits.ingestion import ComponentUniverse

            universe = ComponentUniverse(
                sample_to_component={"row_0": _HEX_A, "row_1": _HEX_A}, component_sizes={_HEX_A: 2}
            )
            aggregates = stream_component_label_aggregates(csv_path, universe)
            components = to_component_label_counts(aggregates)
            self.assertEqual(len(components), 1)
            self.assertEqual(components[0].component_id, _HEX_A)
            self.assertEqual(components[0].size, 2)
            self.assertEqual(components[0].label_counts[1], (1, 1))


if __name__ == "__main__":
    unittest.main()
