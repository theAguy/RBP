"""Regression coverage for Task 001B checkpoint B3A, item A1 (bind
downloads to the actual remote basenames).

Test names map to the executor handoff's "Minimum regression set"
(docs/handoffs/001b_b3a_claude_executor_handoff.md):
  - item 1 (real-NCBI-shaped GCF_... remote basename differing from assembly label)
  - item 2 (missing, malformed, duplicate, and conflicting checksum entries)
  - item 3 (checksum-first ordering and no large-file transport after listing failure)

Every transport here is a local injected fake (never a real NCBI URL), per
B3A's authorization boundary. Fixtures are tiny and synthetic throughout.
"""

from __future__ import annotations

import dataclasses
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


class RemoteBasenameTests(unittest.TestCase):
    """Item 1: real-NCBI-shaped GCF_... remote basename differs from the
    (shorter) assembly label -- the exact real-world mismatch A1 fixes.
    """

    def test_fasta_remote_basename_is_the_url_basename_not_the_assembly_label(self):
        spec = dataclasses.replace(
            _hg38_spec(),
            assembly="GRCh38.p14",
            fasta_url=(
                "https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.40_GRCh38.p14/"
                "GCF_000001405.40_GRCh38.p14_genomic.fna.gz"
            ),
            assembly_report_url=(
                "https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.40_GRCh38.p14/"
                "GCF_000001405.40_GRCh38.p14_assembly_report.txt"
            ),
        )
        self.assertNotEqual(spec.fasta_remote_basename, f"{spec.assembly}_genomic.fna.gz")
        self.assertEqual(spec.fasta_remote_basename, "GCF_000001405.40_GRCh38.p14_genomic.fna.gz")
        self.assertEqual(spec.assembly_report_remote_basename, "GCF_000001405.40_GRCh38.p14_assembly_report.txt")

    def test_stage_download_binds_local_destination_to_the_real_remote_basename(self):
        spec = dataclasses.replace(
            _hg38_spec(),
            assembly="GRCh38.p14",
            fasta_url="https://ftp.ncbi.nlm.nih.gov/x/GCF_000001405.40_GRCh38.p14_genomic.fna.gz",
            assembly_report_url="https://ftp.ncbi.nlm.nih.gov/x/GCF_000001405.40_GRCh38.p14_assembly_report.txt",
        )
        import gzip
        import hashlib

        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = hashlib.md5(fasta_body_gz).hexdigest()
        report_md5 = hashlib.md5(report_body.encode()).hexdigest()
        spec = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )
        listing = (
            f"{fasta_md5}  ./{spec.fasta_remote_basename}\n{report_md5}  ./{spec.assembly_report_remote_basename}\n"
        )

        def transport(url, dest_path):
            if "md5" in url:
                dest_path.write_text(listing)
            elif "genomic" in url:
                dest_path.write_bytes(fasta_body_gz)
            else:
                dest_path.write_text(report_body)

        with tempfile.TemporaryDirectory() as tmp:
            sources_dir = Path(tmp) / "sources"
            record = stage_download(
                build="hg38", source_spec=spec, sources_dir=sources_dir, allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=transport,
            )
            self.assertTrue(record["executed"], record.get("skip_reason"))
            self.assertEqual(Path(record["fasta"]["dest_path"]).name, "GCF_000001405.40_GRCh38.p14_genomic.fna.gz")
            self.assertEqual(
                Path(record["assembly_report"]["dest_path"]).name, "GCF_000001405.40_GRCh38.p14_assembly_report.txt"
            )
            # The real (pre-B3A) bug: never the shorter assembly-label name.
            self.assertNotEqual(Path(record["fasta"]["dest_path"]).name, f"{spec.assembly}_genomic.fna.gz")


class ChecksumListingParseTests(unittest.TestCase):
    """Item 2: missing, malformed, duplicate, and conflicting checksum entries."""

    def test_well_formed_listing_has_no_violations(self):
        text = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  ./a.fna.gz\nbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb  ./b.txt\n"
        result = parse_md5checksums_evidence(text)
        self.assertTrue(result.ok, result.violations)
        self.assertEqual(result.entries, {"a.fna.gz": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "b.txt": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"})

    def test_malformed_md5_token_is_a_violation(self):
        result = parse_md5checksums_evidence("not-a-valid-md5-token  ./a.fna.gz\n")
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "malformed_token" for v in result.violations))
        self.assertNotIn("a.fna.gz", result.entries)

    def test_malformed_line_shape_is_a_violation(self):
        result = parse_md5checksums_evidence("this-line-has-no-second-token\n")
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "malformed_path" for v in result.violations))

    def test_duplicate_basename_same_value_is_still_flagged(self):
        # B3A-A1: "do not silently let a later line overwrite an earlier
        # one" -- a repeated basename is a violation even when both lines
        # agree on the MD5 value.
        text = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  ./a.fna.gz\naaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  ./a.fna.gz\n"
        result = parse_md5checksums_evidence(text)
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "duplicate_basename" for v in result.violations))
        # The first (only) accepted value is retained, never silently overwritten.
        self.assertEqual(result.entries["a.fna.gz"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    def test_conflicting_duplicate_basename_is_flagged_distinctly(self):
        text = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  ./a.fna.gz\nbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb  ./a.fna.gz\n"
        result = parse_md5checksums_evidence(text)
        self.assertFalse(result.ok)
        self.assertTrue(any(v.kind == "conflicting_duplicate" for v in result.violations))
        self.assertEqual(result.entries["a.fna.gz"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")  # first entry retained

    def test_missing_entry_is_not_itself_a_parse_violation(self):
        # A basename simply absent from the listing is not a malformed line
        # -- that is stage_download's own "no entry for X" check, exercised
        # separately (C1ChecksumListingTests).
        result = parse_md5checksums_evidence("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  ./only_one.fna.gz\n")
        self.assertTrue(result.ok)


class ChecksumFirstOrderingTests(unittest.TestCase):
    """Item 3: checksum-first ordering and no large-file transport after
    listing failure.
    """

    def test_large_fasta_transport_is_never_called_when_listing_parse_fails(self):
        spec = _hg38_spec()
        calls: list[str] = []

        def transport(url, dest_path):
            calls.append(url)
            if "md5" in url:
                dest_path.write_text("garbage listing with no valid entries at all")
            else:
                dest_path.write_bytes(b"should never be requested")

        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38", source_spec=spec, sources_dir=Path(tmp) / "sources", allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=transport,
            )
            self.assertFalse(record["executed"])
            # Only the listing URL was ever requested -- the large FASTA URL
            # (and the assembly-report URL) were never touched.
            self.assertEqual(calls, [spec.md5checksums_url])

    def test_listing_is_fetched_before_any_large_file_transport_even_on_success(self):
        spec = _hg38_spec()
        import gzip
        import hashlib

        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = hashlib.md5(fasta_body_gz).hexdigest()
        report_md5 = hashlib.md5(report_body.encode()).hexdigest()
        adjusted = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )
        listing = f"{fasta_md5}  ./{adjusted.fasta_remote_basename}\n{report_md5}  ./{adjusted.assembly_report_remote_basename}\n"
        call_order: list[str] = []

        def transport(url, dest_path):
            call_order.append(url)
            if "md5" in url:
                dest_path.write_text(listing)
            elif "genomic" in url or "fna" in url:
                dest_path.write_bytes(fasta_body_gz)
            else:
                dest_path.write_text(report_body)

        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38", source_spec=adjusted, sources_dir=Path(tmp) / "sources", allow_mapping=True,
                host_role="approved_mac", dry_run=False, transport=transport,
            )
            self.assertTrue(record["executed"], record.get("skip_reason"))
            self.assertEqual(call_order[0], adjusted.md5checksums_url)


if __name__ == "__main__":
    unittest.main()
