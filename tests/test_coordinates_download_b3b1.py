"""Regression coverage for Task 001B checkpoint B3B-1's checksum-path
correction (``docs/reviews/001b_b3b1_stop_review.md`` /
``docs/handoffs/001b_b3b1_checksum_correction_claude_handoff.md``).

Root cause: the pre-correction ``parse_md5checksums_evidence()`` keyed
listing entries by basename alone. The real GRCh38.p14 ``md5checksums.txt``
listing legitimately repeats generic basenames (e.g. ``alt.scaf.fna.gz``)
under many different alt-locus subdirectories -- different files, different
full relative paths, legitimately different MD5s -- which the basename-keyed
parser mistook for 178 ``conflicting_duplicate`` violations, wrongly
stopping B3B-1. The correction keys listing identity by exact normalized
POSIX relative path instead, and derives each download target's exact
expected root-relative listing path from its frozen URL relative to the
frozen ``md5checksums_url``'s own directory.

Every transport here is a local injected fake (never a real NCBI URL), and
every fixture is tiny and synthetic, per this checkpoint's authorization
boundary. Test names below map to the handoff's "Mandatory regressions"
list, items 1-10.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.download import parse_md5checksums_evidence
from rbpbench.coordinates.execution_sources import load_execution_sources
from rbpbench.coordinates.runner import stage_download

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_EXECUTION_SOURCES = REPO_ROOT / "tests" / "fixtures" / "coordinates" / "tiny_execution_sources.toml"


def _hg38_spec():
    return load_execution_sources(FIXTURE_EXECUTION_SOURCES).reference_sources["hg38"]


def _ncbi_shaped_spec():
    """A real-NCBI-shaped spec: all three URLs share one directory, and the
    FASTA/assembly-report basenames are the long ``GCF_...`` form (never the
    short assembly label) -- the same shape as the real frozen
    ``configs/coordinate_execution_sources.toml`` entry.
    """
    base = "https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.40_GRCh38.p14"
    return dataclasses.replace(
        _hg38_spec(),
        assembly="GRCh38.p14",
        fasta_url=f"{base}/GCF_000001405.40_GRCh38.p14_genomic.fna.gz",
        assembly_report_url=f"{base}/GCF_000001405.40_GRCh38.p14_assembly_report.txt",
        md5checksums_url=f"{base}/md5checksums.txt",
    )


def _md5(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.md5(data).hexdigest()


class DistinctBasenamesDistinctPathsTests(unittest.TestCase):
    """Item 1: two different nested relative paths sharing a basename and
    having different MD5s must never be treated as a duplicate/conflict.
    """

    def test_same_basename_different_directory_are_distinct_valid_entries(self):
        text = (
            f"{_md5('A')}  ./assembly_structure/A/alt.scaf.fna.gz\n"
            f"{_md5('B')}  ./assembly_structure/B/alt.scaf.fna.gz\n"
        )
        result = parse_md5checksums_evidence(text)
        self.assertTrue(result.ok, result.violations)
        self.assertEqual(
            result.entries,
            {
                "assembly_structure/A/alt.scaf.fna.gz": _md5("A"),
                "assembly_structure/B/alt.scaf.fna.gz": _md5("B"),
            },
        )


class ExactPathDuplicateTests(unittest.TestCase):
    """Items 2-3: only the same exact normalized path repeating is a
    duplicate/conflicting-duplicate violation.
    """

    def test_same_exact_path_repeated_same_md5_is_a_duplicate_violation(self):
        text = f"{_md5('X')}  ./a/b.fna.gz\n{_md5('X')}  ./a/b.fna.gz\n"
        result = parse_md5checksums_evidence(text)
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "duplicate_path" for v in result.violations))
        self.assertEqual(result.entries["a/b.fna.gz"], _md5("X"))

    def test_same_exact_path_repeated_different_md5_is_conflicting_duplicate(self):
        text = f"{_md5('X')}  ./a/b.fna.gz\n{_md5('Y')}  ./a/b.fna.gz\n"
        result = parse_md5checksums_evidence(text)
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "conflicting_duplicate" for v in result.violations))
        # First entry retained, never silently overwritten.
        self.assertEqual(result.entries["a/b.fna.gz"], _md5("X"))

    def test_leading_dot_slash_and_bare_relative_path_normalize_to_the_same_identity(self):
        text = f"{_md5('X')}  ./a/b.fna.gz\n{_md5('Y')}  a/b.fna.gz\n"
        result = parse_md5checksums_evidence(text)
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "conflicting_duplicate" for v in result.violations))


class RealNcbiShapedGuardedDownloadTests(unittest.TestCase):
    """Item 4: a real-NCBI-shaped listing with many nested same-basename
    entries plus the two unique root targets: the guarded tiny download
    succeeds and selects the root targets.
    """

    def test_many_nested_same_basename_entries_do_not_block_the_root_targets(self):
        spec = _ncbi_shaped_spec()
        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = _md5(fasta_body_gz)
        report_md5 = _md5(report_body)
        adjusted = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )

        lines = [
            f"{fasta_md5}  ./{adjusted.fasta_remote_basename}",
            f"{report_md5}  ./{adjusted.assembly_report_remote_basename}",
        ]
        # 178-style repro: many alt-locus subdirectories, all sharing the
        # generic basename "alt.scaf.fna.gz", each with its own distinct MD5.
        for i in range(10):
            lines.append(f"{_md5(f'alt{i}')}  ./assembly_structure/ALT_{i}/alt.scaf.fna.gz")
        listing = "\n".join(lines) + "\n"

        calls: list[str] = []

        def transport(url, dest_path):
            calls.append(url)
            if "md5" in url:
                dest_path.write_text(listing)
            elif "genomic" in url:
                dest_path.write_bytes(fasta_body_gz)
            else:
                dest_path.write_text(report_body)

        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38", source_spec=adjusted, sources_dir=Path(tmp) / "sources", allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=transport,
            )
            self.assertTrue(record["executed"], record.get("skip_reason"))
            self.assertEqual(Path(record["fasta"]["dest_path"]).name, adjusted.fasta_remote_basename)
            self.assertEqual(Path(record["assembly_report"]["dest_path"]).name, adjusted.assembly_report_remote_basename)
            self.assertEqual(record["fasta"]["md5"], fasta_md5)
            self.assertEqual(record["assembly_report"]["md5"], report_md5)
            # Exactly three transport calls: listing, fasta, report -- no
            # per-alt-locus-entry request was ever made.
            self.assertEqual(len(calls), 3)


class MissingRootTargetTests(unittest.TestCase):
    """Item 5: a nested same-basename target with the required root target
    absent must be a hard missing-entry stop, with no large-file transport.
    """

    def test_nested_entry_sharing_the_target_basename_never_satisfies_a_missing_root_entry(self):
        spec = _ncbi_shaped_spec()
        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = _md5(fasta_body_gz)
        report_md5 = _md5(report_body)
        adjusted = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )

        # The FASTA root entry is ABSENT; only a nested entry sharing its
        # basename (and a plausible-looking but irrelevant MD5) is present.
        listing = (
            f"{fasta_md5}  ./assembly_structure/A/{adjusted.fasta_remote_basename}\n"
            f"{report_md5}  ./{adjusted.assembly_report_remote_basename}\n"
        )
        calls: list[str] = []

        def transport(url, dest_path):
            calls.append(url)
            if "md5" in url:
                dest_path.write_text(listing)
            elif "genomic" in url:
                dest_path.write_bytes(fasta_body_gz)
            else:
                dest_path.write_text(report_body)

        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38", source_spec=adjusted, sources_dir=Path(tmp) / "sources", allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=transport,
            )
            self.assertFalse(record["executed"])
            self.assertIn(f"no entry for exact path {adjusted.fasta_remote_basename!r}", record["skip_reason"])
            # Only the listing URL was ever requested.
            self.assertEqual(calls, [spec.md5checksums_url])


class ConflictingNestedEntryWithAgreeingRootTests(unittest.TestCase):
    """Item 6: a nested same-basename entry conflicting with the frozen MD5
    while the exact root target agrees: the root target is used and the
    download may proceed.
    """

    def test_nested_entry_with_wrong_md5_does_not_block_an_agreeing_root_entry(self):
        spec = _ncbi_shaped_spec()
        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = _md5(fasta_body_gz)
        report_md5 = _md5(report_body)
        adjusted = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )
        wrong_md5 = _md5("this is not the fasta's real md5")
        listing = (
            f"{fasta_md5}  ./{adjusted.fasta_remote_basename}\n"
            f"{wrong_md5}  ./assembly_structure/A/{adjusted.fasta_remote_basename}\n"
            f"{report_md5}  ./{adjusted.assembly_report_remote_basename}\n"
        )

        def transport(url, dest_path):
            if "md5" in url:
                dest_path.write_text(listing)
            elif "genomic" in url:
                dest_path.write_bytes(fasta_body_gz)
            else:
                dest_path.write_text(report_body)

        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38", source_spec=adjusted, sources_dir=Path(tmp) / "sources", allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=transport,
            )
            self.assertTrue(record["executed"], record.get("skip_reason"))
            self.assertEqual(record["fasta"]["md5"], fasta_md5)


class MalformedPathRejectionTests(unittest.TestCase):
    """Item 7: absolute, traversal, empty/malformed path and malformed-token
    rejection.
    """

    def test_absolute_path_is_rejected(self):
        result = parse_md5checksums_evidence(f"{_md5('x')}  /etc/passwd\n")
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "malformed_path" for v in result.violations))
        self.assertEqual(result.entries, {})

    def test_traversal_path_is_rejected(self):
        result = parse_md5checksums_evidence(f"{_md5('x')}  ../../etc/passwd\n")
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "malformed_path" for v in result.violations))

    def test_traversal_in_the_middle_of_the_path_is_rejected(self):
        result = parse_md5checksums_evidence(f"{_md5('x')}  ./assembly_structure/../../escape.fna.gz\n")
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "malformed_path" for v in result.violations))

    def test_empty_directory_only_path_is_rejected(self):
        result = parse_md5checksums_evidence(f"{_md5('x')}  ./\n")
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "malformed_path" for v in result.violations))

    def test_malformed_md5_token_is_rejected(self):
        result = parse_md5checksums_evidence("not-a-valid-md5-token  ./a.fna.gz\n")
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "malformed_token" for v in result.violations))
        self.assertNotIn("a.fna.gz", result.entries)

    def test_normalize_checksum_listing_path_directly(self):
        from rbpbench.coordinates.download import normalize_checksum_listing_path

        self.assertEqual(normalize_checksum_listing_path("./a/b.fna.gz"), ("a/b.fna.gz", None))
        self.assertEqual(normalize_checksum_listing_path("a/b.fna.gz"), ("a/b.fna.gz", None))
        normalized, reason = normalize_checksum_listing_path("/abs/path")
        self.assertIsNone(normalized)
        self.assertIn("absolute", reason)
        normalized, reason = normalize_checksum_listing_path("../x")
        self.assertIsNone(normalized)
        self.assertIn("traversal", reason)
        normalized, reason = normalize_checksum_listing_path("")
        self.assertIsNone(normalized)
        self.assertIn("empty", reason)
        normalized, reason = normalize_checksum_listing_path(".")
        self.assertIsNone(normalized)
        self.assertIn("basename", reason)


class InconsistentSourceUrlLayoutTests(unittest.TestCase):
    """Item 8: inconsistent source/checksum URL parent or authority
    rejection before any large-file transport.
    """

    def test_fasta_url_on_a_different_host_is_rejected_before_any_transport_call(self):
        spec = _ncbi_shaped_spec()
        adjusted = dataclasses.replace(
            spec, fasta_url="https://mirror.example.invalid/GCF_000001405.40_GRCh38.p14_genomic.fna.gz"
        )
        calls: list[str] = []

        def transport(url, dest_path):
            calls.append(url)
            dest_path.write_text("should never be called")

        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38", source_spec=adjusted, sources_dir=Path(tmp) / "sources", allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=transport,
            )
            self.assertFalse(record["executed"])
            self.assertIn("checksum-listing target path could not be derived", record["skip_reason"])
            self.assertEqual(calls, [])

    def test_fasta_url_in_a_different_directory_is_rejected_before_any_transport_call(self):
        spec = _ncbi_shaped_spec()
        adjusted = dataclasses.replace(
            spec,
            fasta_url=(
                "https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/"
                "GCF_000001405.40_GRCh38.p14/assembly_structure/GCF_000001405.40_GRCh38.p14_genomic.fna.gz"
            ),
        )
        calls: list[str] = []

        def transport(url, dest_path):
            calls.append(url)
            dest_path.write_text("should never be called")

        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38", source_spec=adjusted, sources_dir=Path(tmp) / "sources", allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=transport,
            )
            self.assertFalse(record["executed"])
            self.assertIn("checksum-listing target path could not be derived", record["skip_reason"])
            self.assertEqual(calls, [])


class PriorAcceptedGenerationPreservedTests(unittest.TestCase):
    """Item 9: failed parsing/path resolution must preserve a prior accepted
    generation and selection record.
    """

    def test_a_later_broken_listing_never_overwrites_a_prior_accepted_download_record(self):
        spec = _ncbi_shaped_spec()
        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = _md5(fasta_body_gz)
        report_md5 = _md5(report_body)
        adjusted = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )
        good_listing = (
            f"{fasta_md5}  ./{adjusted.fasta_remote_basename}\n{report_md5}  ./{adjusted.assembly_report_remote_basename}\n"
        )

        def good_transport(url, dest_path):
            if "md5" in url:
                dest_path.write_text(good_listing)
            elif "genomic" in url:
                dest_path.write_bytes(fasta_body_gz)
            else:
                dest_path.write_text(report_body)

        def broken_transport(url, dest_path):
            if "md5" in url:
                # Conflicting duplicate for the same exact root path: a
                # structurally broken listing.
                dest_path.write_text(good_listing + f"{'f' * 32}  ./{adjusted.fasta_remote_basename}\n")
            elif "genomic" in url:
                dest_path.write_bytes(fasta_body_gz)
            else:
                dest_path.write_text(report_body)

        with tempfile.TemporaryDirectory() as tmp:
            sources_dir = Path(tmp) / "sources"
            first = stage_download(
                build="hg38", source_spec=adjusted, sources_dir=sources_dir, allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=good_transport,
            )
            self.assertTrue(first["executed"], first.get("skip_reason"))
            download_json = sources_dir / "download.json"
            accepted_before = json.loads(download_json.read_text())

            with self.assertRaises(SystemExit):
                stage_download(
                    build="hg38", source_spec=adjusted, sources_dir=sources_dir, allow_mapping=True,
                    host_role="approved_mac", dry_run=False, transport=broken_transport,
                )

            accepted_after = json.loads(download_json.read_text())
            self.assertEqual(accepted_before, accepted_after)
            rejected_log = download_json.with_name(download_json.name + ".rejected_attempts.jsonl")
            self.assertTrue(rejected_log.is_file())


class AcceptedEvidenceRecordsTargetPathsTests(unittest.TestCase):
    """Item 10: accepted evidence records both exact target listing paths."""

    def test_accepted_record_and_planned_record_both_carry_exact_target_listing_paths(self):
        spec = _ncbi_shaped_spec()
        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = _md5(fasta_body_gz)
        report_md5 = _md5(report_body)
        adjusted = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )
        listing = (
            f"{fasta_md5}  ./{adjusted.fasta_remote_basename}\n{report_md5}  ./{adjusted.assembly_report_remote_basename}\n"
        )

        def transport(url, dest_path):
            if "md5" in url:
                dest_path.write_text(listing)
            elif "genomic" in url:
                dest_path.write_bytes(fasta_body_gz)
            else:
                dest_path.write_text(report_body)

        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38", source_spec=adjusted, sources_dir=Path(tmp) / "sources", allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=transport,
            )
            self.assertTrue(record["executed"], record.get("skip_reason"))
            expected = {
                "fasta": adjusted.fasta_remote_basename,
                "assembly_report": adjusted.assembly_report_remote_basename,
            }
            self.assertEqual(record["checksum_listing"]["target_listing_paths"], expected)
            self.assertEqual(record["planned"]["fasta_expected_listing_path"], adjusted.fasta_remote_basename)
            self.assertEqual(
                record["planned"]["assembly_report_expected_listing_path"], adjusted.assembly_report_remote_basename
            )


if __name__ == "__main__":
    unittest.main()
