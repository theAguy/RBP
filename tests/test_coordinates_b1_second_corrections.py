"""Regression coverage for the Task 001B checkpoint B1 SECOND correction
round.

Every test here targets exactly one item from
``docs/reviews/001b_b1_correction_review.md`` (B1-C1 through B1-C6) and
demonstrably fails against commit ``11738d8`` (the reviewed, pre-second-
correction implementation). Fixtures are tiny and synthetic throughout; the
real CSV is never opened and no NCBI URL is ever requested (B1's
authorization boundary), consistent with the rest of the coordinate-runner
test suite.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.cleanup import CleanupRefused, execute_index_cleanup
from rbpbench.coordinates.config import load_config
from rbpbench.coordinates.diskbudget import DiskBudgetExceeded, check_pinned_volumes
from rbpbench.coordinates.download import parse_md5checksums
from rbpbench.coordinates.execution_sources import load_execution_sources
from rbpbench.coordinates.indexing import build_index_manifest, check_minimap2_mapping_stderr
from rbpbench.coordinates.manifest import manifest_content_sha256
from rbpbench.coordinates.runner import (
    _current_output_bytes,
    _run_tool_to_file,
    main,
    stage_align,
    stage_derive,
    stage_download,
    stage_index,
)
from rbpbench.data.audit import sha256_file

from test_coordinates_runner import (
    FIXTURE_CONFIG,
    FIXTURE_CSV,
    FIXTURE_EXECUTION_SOURCES,
    _FAKE_SEQKIT,
    _approved_host_context,
    _write_fake_executable,
    _write_reference_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_REPORT_HEADER = (
    "# Sequence-Name\tSequence-Role\tAssigned-Molecule\tAssigned-Molecule-Location/Type\t"
    "GenBank-Accn\tRelationship\tRefSeq-Accn\tAssembly-Unit\tSequence-Length\tUCSC-style-name\n"
)


def _cfg():
    return load_config(FIXTURE_CONFIG)


def _hg38_source_spec():
    spec = load_execution_sources(FIXTURE_EXECUTION_SOURCES)
    return spec.reference_sources["hg38"]


def _fixture_report(*, accession: str, length: int) -> str:
    return _REPORT_HEADER + f"1\tassembled-molecule\t1\tChromosome\t{accession}\t=\t{accession}\tPrimary Assembly\t{length}\t{accession}\n"


class C1ChecksumListingTests(unittest.TestCase):
    """B1-C1: the live md5checksums.txt listing must be fetched and cross-
    checked against both the frozen plan MD5 and the freshly downloaded
    file's own MD5, and the whole source set must be re-verified before a
    restart skip.
    """

    def _good_transport(self, *, fasta_body_gz: bytes, report_body: str, fasta_md5: str, report_md5: str, assembly: str):
        listing = f"{fasta_md5}  ./{assembly}_genomic.fna.gz\n{report_md5}  ./{assembly}_assembly_report.txt\n"

        def transport(url, dest_path):
            if "fna.gz" in url:
                dest_path.write_bytes(fasta_body_gz)
            elif "md5" in url:
                dest_path.write_text(listing)
            else:
                dest_path.write_text(report_body)

        return transport

    def test_live_checksum_listing_disagreeing_with_frozen_plan_value_is_a_hard_stop(self):
        spec = _hg38_source_spec()
        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = hashlib.md5(fasta_body_gz).hexdigest()
        report_md5 = hashlib.md5(report_body.encode()).hexdigest()
        adjusted = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )

        # The live listing entry for the FASTA disagrees with the frozen
        # plan MD5 (a live-list/plan-value mismatch) even though the
        # downloaded bytes themselves are internally consistent.
        wrong_live_md5 = "f" * 32
        listing = f"{wrong_live_md5}  ./{adjusted.assembly}_genomic.fna.gz\n{report_md5}  ./{adjusted.assembly}_assembly_report.txt\n"

        def transport(url, dest_path):
            if "fna.gz" in url:
                dest_path.write_bytes(fasta_body_gz)
            elif "md5" in url:
                dest_path.write_text(listing)
            else:
                dest_path.write_text(report_body)

        with tempfile.TemporaryDirectory() as tmp:
            sources_dir = Path(tmp) / "sources"
            record = stage_download(
                build="hg38",
                source_spec=adjusted,
                sources_dir=sources_dir,
                allow_mapping=True,
                host_role="approved_mac",
                dry_run=False,
                transport=transport,
            )
            self.assertFalse(record["executed"])
            self.assertIn("authoritative plan value", record["skip_reason"])
            # No accepted generation was left behind by the failed attempt.
            self.assertFalse(any((sources_dir / "generations").glob("*/*")) if (sources_dir / "generations").exists() else False)

    def test_missing_live_checksum_entry_is_refused(self):
        spec = _hg38_source_spec()
        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = hashlib.md5(fasta_body_gz).hexdigest()
        report_md5 = hashlib.md5(report_body.encode()).hexdigest()
        adjusted = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )

        def transport(url, dest_path):
            if "fna.gz" in url:
                dest_path.write_bytes(fasta_body_gz)
            elif "md5" in url:
                dest_path.write_text("")  # empty listing: no entries at all
            else:
                dest_path.write_text(report_body)

        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38",
                source_spec=adjusted,
                sources_dir=Path(tmp) / "sources",
                allow_mapping=True,
                host_role="approved_mac",
                dry_run=False,
                transport=transport,
            )
            self.assertFalse(record["executed"])
            self.assertIn("no entry for", record["skip_reason"])

    def test_successful_download_preserves_checksum_listing_hash_evidence(self):
        spec = _hg38_source_spec()
        fasta_body_gz = gzip.compress(b"tiny fixture fasta bytes")
        report_body = "tiny fixture report bytes"
        fasta_md5 = hashlib.md5(fasta_body_gz).hexdigest()
        report_md5 = hashlib.md5(report_body.encode()).hexdigest()
        adjusted = dataclasses.replace(
            spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
        )
        transport = self._good_transport(
            fasta_body_gz=fasta_body_gz, report_body=report_body, fasta_md5=fasta_md5, report_md5=report_md5,
            assembly=adjusted.assembly,
        )
        with tempfile.TemporaryDirectory() as tmp:
            record = stage_download(
                build="hg38",
                source_spec=adjusted,
                sources_dir=Path(tmp) / "sources",
                allow_mapping=True,
                host_role="approved_mac",
                dry_run=False,
                transport=transport,
            )
            self.assertTrue(record["executed"])
            self.assertIn("checksum_listing", record)
            self.assertTrue(Path(record["checksum_listing"]["dest_path"]).is_file())
            self.assertEqual(record["checksum_listing"]["sha256"], sha256_file(Path(record["checksum_listing"]["dest_path"])))

    def test_altered_accepted_source_forces_redownload_instead_of_silent_restart_skip(self):
        """B1-C1: a restart skip must revalidate the accepted source's
        current hashes, never trust the fingerprint/executed-boolean alone.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            sources_dir = tmp_path / "sources"
            derived_dir = tmp_path / "derived"

            spec = _hg38_source_spec()
            fasta_body_gz = gzip.compress(b">NC_TEST1.1\n" + b"ACGT" * 5 + b"\n")
            report_body = _fixture_report(accession="NC_TEST1.1", length=20)
            fasta_md5 = hashlib.md5(fasta_body_gz).hexdigest()
            report_md5 = hashlib.md5(report_body.encode()).hexdigest()
            adjusted = dataclasses.replace(
                spec, fasta_upstream_md5=fasta_md5, fasta_compressed_byte_size=len(fasta_body_gz), assembly_report_md5=report_md5
            )
            transport = self._good_transport(
                fasta_body_gz=fasta_body_gz, report_body=report_body, fasta_md5=fasta_md5, report_md5=report_md5,
                assembly=adjusted.assembly,
            )

            with mock.patch("rbpbench.coordinates.runner.urllib_transport", transport):
                with mock.patch(
                    "rbpbench.coordinates.runner.load_execution_sources",
                    return_value=dataclasses.replace(
                        load_execution_sources(FIXTURE_EXECUTION_SOURCES),
                        reference_sources={"hg38": adjusted, "hg19": adjusted},
                    ),
                ):
                    common = [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(output_dir),
                        "--sources-dir", str(sources_dir),
                        "--derived-dir", str(derived_dir),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                    ]
                    with _approved_host_context():
                        main([*common, "--stage", "download"])
                        first_record = json.loads((sources_dir / "TestAssembly38" / "download.json").read_text())
                        self.assertTrue(first_record["executed"])

                        # Tamper with the accepted FASTA bytes directly.
                        Path(first_record["fasta"]["dest_path"]).write_bytes(b"tampered content")

                        # Re-run with identical arguments (same restart
                        # fingerprint): must NOT silently skip.
                        main([*common, "--stage", "download"])

            second_record = json.loads((sources_dir / "TestAssembly38" / "download.json").read_text())
            self.assertTrue(second_record["executed"])
            # A fresh generation was produced (never merely trusting the
            # tampered prior one as "already completed").
            self.assertNotEqual(first_record["fasta"]["dest_path"], second_record["fasta"]["dest_path"])
            self.assertEqual(Path(second_record["fasta"]["dest_path"]).read_bytes(), fasta_body_gz)


class C1DeriveRevalidationTests(unittest.TestCase):
    """B1-C1: derivation must re-hash the current source files against
    download.json's own recorded hashes immediately before deriving.
    """

    def test_derive_refuses_when_accepted_source_has_drifted_since_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_fasta = tmp_path / "source.fna"
            source_fasta.write_text(">NC_TEST1.1\nACGTACGT\n")
            report_path = tmp_path / "report.txt"
            report_path.write_text(_fixture_report(accession="NC_TEST1.1", length=8))

            download_record = {
                "executed": True,
                "fasta": {"dest_path": str(source_fasta), "sha256": sha256_file(source_fasta)},
                "assembly_report": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
                "checksum_listing": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
            }

            # Alter the source AFTER download.json's hash was recorded.
            source_fasta.write_text(">NC_TEST1.1\nTTTTTTTT\n")

            record = stage_derive(
                build="hg38",
                source_spec=_hg38_source_spec(),
                derived_dir=tmp_path / "derived",
                allow_mapping=True,
                host_role="approved_mac",
                download_record=download_record,
                dry_run=False,
            )
            self.assertFalse(record["executed"])
            self.assertIn("drifted", record["skip_reason"])

    def test_failure_between_derived_fasta_and_manifest_preserves_prior_generation(self):
        """B1-C2: a failure between writing the derived FASTA and
        building/persisting its manifest must never leave a new FASTA
        paired with a stale/missing manifest, and must preserve the
        previously accepted generation untouched.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_fasta = tmp_path / "source.fna"
            source_fasta.write_text(">NC_TEST1.1\nACGTACGT\n")
            report_path = tmp_path / "report.txt"
            report_path.write_text(_fixture_report(accession="NC_TEST1.1", length=8))
            download_record = {
                "executed": True,
                "fasta": {"dest_path": str(source_fasta), "sha256": sha256_file(source_fasta)},
                "assembly_report": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
                "checksum_listing": {"dest_path": str(report_path), "sha256": sha256_file(report_path)},
            }
            derived_dir = tmp_path / "derived"

            # First, a genuinely successful derivation.
            first = stage_derive(
                build="hg38",
                source_spec=_hg38_source_spec(),
                derived_dir=derived_dir,
                allow_mapping=True,
                host_role="approved_mac",
                download_record=download_record,
                dry_run=False,
            )
            self.assertTrue(first["executed"])
            original_fasta_bytes = Path(first["output_fasta"]).read_bytes()

            # Now force a failure AFTER the FASTA is derived but BEFORE the
            # manifest is built/persisted.
            with mock.patch("rbpbench.coordinates.runner.build_reference_manifest", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    stage_derive(
                        build="hg38",
                        source_spec=_hg38_source_spec(),
                        derived_dir=derived_dir,
                        allow_mapping=True,
                        host_role="approved_mac",
                        download_record=download_record,
                        dry_run=False,
                    )

            second_record = json.loads((derived_dir / "derive.json").read_text())
            self.assertEqual(second_record, first)
            self.assertEqual(Path(second_record["output_fasta"]).read_bytes(), original_fasta_bytes)
            # No incomplete new generation directory survives.
            remaining = [p for p in (derived_dir / "generations").iterdir() if p.is_dir()]
            self.assertEqual(remaining, [Path(first["output_fasta"]).parent])


_FAKE_BWA_INDEX = """#!/bin/bash
if [ "$#" -le 0 ]; then
  echo "Version: 0.7.19"
  exit 0
fi
if [ "$1" == "index" ]; then
  prefix="$3"
  for suffix in .amb .ann .bwt .pac .sa; do
    printf 'fake bwa index bytes' > "${prefix}${suffix}"
  done
  exit 0
fi
exit 1
"""

_FAKE_MINIMAP2_INDEX = """#!/bin/bash
if [ "$#" -le 0 ]; then
  echo "2.31"
  exit 0
fi
for arg in "$@"; do
  if [ "$arg" == "--version" ]; then
    echo "2.31"
    exit 0
  fi
done
if [ "$1" == "-x" ]; then
  output="$6"
  printf 'fake mmi bytes' > "$output"
  echo "[M::mm_idx_stat] kmer size: 15; skip: 5; is_hpc: 0; #seq: 1" >&2
  exit 0
fi
exit 1
"""

_FAKE_MINIMAP2_INDEX_FAILS = """#!/bin/bash
if [ "$#" -le 0 ]; then
  echo "2.31"
  exit 0
fi
for arg in "$@"; do
  if [ "$arg" == "--version" ]; then
    echo "2.31"
    exit 0
  fi
done
exit 9
"""

# Combined fake tools that handle BOTH `bwa index`/`minimap2 -x ... -d ...`
# (creating real index files) AND `bwa mem`/`minimap2 -ax ...` (emitting
# fake SAM lines from the reads FASTA) — needed for tests that exercise the
# `index` stage followed by `align` in the same fixture.
_FAKE_BWA_FULL = """#!/bin/bash
if [ "$#" -le 0 ]; then
  echo "Version: 0.7.19"
  exit 0
fi
if [ "$1" == "index" ]; then
  prefix="$3"
  for suffix in .amb .ann .bwt .pac .sa; do
    printf 'fake bwa index bytes' > "${prefix}${suffix}"
  done
  exit 0
fi
reads="${@: -1}"
awk '
  /^>/ { if (name != "") print name "\\t0\\tchr1\\t1\\t60\\t" length(seq) "M\\t*\\t0\\t0\\t" seq "\\t*\\tNM:i:0\\tAS:i:" length(seq); name=substr($0,2); seq=""; next }
  { seq = seq $0 }
  END { if (name != "") print name "\\t0\\tchr1\\t1\\t60\\t" length(seq) "M\\t*\\t0\\t0\\t" seq "\\t*\\tNM:i:0\\tAS:i:" length(seq) }
' "$reads"
"""

_FAKE_MINIMAP2_FULL = """#!/bin/bash
if [ "$#" -le 0 ]; then
  echo "2.31"
  exit 0
fi
for arg in "$@"; do
  if [ "$arg" == "--version" ]; then
    echo "2.31"
    exit 0
  fi
done
if [ "$1" == "-x" ]; then
  output="$6"
  printf 'fake mmi bytes' > "$output"
  echo "[M::mm_idx_stat] kmer size: 15; skip: 5; is_hpc: 0; #seq: 1" >&2
  exit 0
fi
reads="${@: -1}"
awk '
  /^>/ { if (name != "") print name "\\t0\\tchr1\\t1\\t60\\t" length(seq) "=\\t*\\t0\\t0\\t" seq "\\t*\\tAS:i:" length(seq); name=substr($0,2); seq=""; next }
  { seq = seq $0 }
  END { if (name != "") print name "\\t0\\tchr1\\t1\\t60\\t" length(seq) "=\\t*\\t0\\t0\\t" seq "\\t*\\tAS:i:" length(seq) }
' "$reads"
"""


class C2IndexTransactionalTests(unittest.TestCase):
    """B1-C2: index preparation must promote both index files AND their
    manifest as one immutable generation.
    """

    def test_failure_between_bwa_and_minimap2_preserves_prior_accepted_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA_INDEX)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2_INDEX)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 40 + "\n")
            manifest = json.loads(_write_reference_manifest(tmp_path / "manifest.json", build="hg38", reference=reference).read_text())
            index_dir = tmp_path / "indices" / "hg38"

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                first = stage_index(
                    _cfg(), build="hg38", index_dir=index_dir, allow_mapping=True, host_role="approved_mac",
                    threads=1, reference=reference, reference_manifest=manifest, dry_run=False,
                )
                self.assertTrue(first["executed"])
                original_bwt = Path(first["bwa_index_prefix"] + ".bwt").read_bytes()

                _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2_INDEX_FAILS)
                env2 = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
                with mock.patch.dict(os.environ, env2):
                    with self.assertRaises(Exception):
                        stage_index(
                            _cfg(), build="hg38", index_dir=index_dir, allow_mapping=True, host_role="approved_mac",
                            threads=1, reference=reference, reference_manifest=manifest, dry_run=False,
                        )

            second_record = json.loads((index_dir / "index.json").read_text())
            self.assertEqual(second_record, first)
            self.assertEqual(Path(second_record["bwa_index_prefix"] + ".bwt").read_bytes(), original_bwt)
            remaining = [p for p in (index_dir / "generations").iterdir() if p.is_dir()]
            self.assertEqual(remaining, [Path(first["bwa_index_prefix"]).parent])


class C3CombinedDiskBudgetTests(unittest.TestCase):
    """B1-C3: BWA/minimap2 (and SeqKit) must share ONE combined build-output
    allowance, never each independently granted its own full allowance.
    """

    def test_individually_sub_limit_writers_exceed_the_cap_in_combination(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            # Each fake tool alone writes 150 bytes: individually under a
            # 200-byte combined cap, but 300 bytes combined exceeds it.
            _write_fake_executable(
                bin_dir, "bwa",
                "#!/bin/bash\nif [ \"$#\" -le 0 ]; then echo 'Version: 0.7.19'; exit 0; fi\npython3 -c \"print('x'*150)\"\n",
            )
            _write_fake_executable(
                bin_dir, "minimap2",
                "#!/bin/bash\n"
                "if [ \"$#\" -le 0 ]; then echo '2.31'; exit 0; fi\n"
                "for arg in \"$@\"; do if [ \"$arg\" == \"--version\" ]; then echo '2.31'; exit 0; fi; done\n"
                "python3 -c \"print('y'*150)\"\n",
            )
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            reads = tmp_path / "reads.fasta"
            reads.write_text(">s1\nAAAA\n")
            manifest = json.loads(_write_reference_manifest(tmp_path / "manifest.json", build="hg38", reference=reference).read_text())

            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                with mock.patch("rbpbench.coordinates.runner.BUILD_OUTPUT_ALLOWANCE_GIB", 200 / (1024**3)):
                    with self.assertRaises(DiskBudgetExceeded):
                        stage_align(
                            _cfg(), build="hg38", build_output_dir=tmp_path / "out", allow_mapping=True,
                            host_role="approved_mac", threads=1, reference=reference, reference_manifest=manifest,
                            reads_fasta=reads, dry_run=False,
                        )
            # No accepted align record from the disqualified combined attempt.
            self.assertFalse((tmp_path / "out" / "align.json").exists())

    def test_current_output_bytes_sums_existing_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            a = tmp_path / "a.txt"
            a.write_bytes(b"12345")
            missing = tmp_path / "does_not_exist.txt"
            total = _current_output_bytes([str(a), missing, None])
            self.assertEqual(total, 5)

    def test_cross_volume_sources_and_derived_dirs_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sources_dir = tmp_path / "sources"
            derived_dir = tmp_path / "derived"
            fake_dev_map = {str(sources_dir): 11, str(derived_dir): 22, str(tmp_path): 1}

            def fake_volume_id(path):
                return fake_dev_map.get(str(Path(path)), 1)

            with mock.patch("rbpbench.coordinates.diskbudget.volume_id", side_effect=fake_volume_id):
                violations = check_pinned_volumes(
                    {"sources_dir": sources_dir, "derived_dir": derived_dir}, primary=tmp_path
                )
            self.assertEqual(len(violations), 2)


class C4CleanupPinningTests(unittest.TestCase):
    """B1-C4: cleanup must pin to the real configured repo root and the
    actual accepted reference, reject every symlinked ancestor component,
    verify report/provenance hashes, and preserve pre-deletion receipt
    evidence without recomputing deleted paths.
    """

    def test_ancestor_symlink_above_the_immediate_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            real_root = tmp_path / "real_repo"
            (real_root / "indices" / "hg38").mkdir(parents=True)
            (real_root / "indices" / "hg38" / "hg38.bwt").write_bytes(b"x")
            # Symlink an ancestor ABOVE the immediate "indices" parent.
            symlinked_repo_root = tmp_path / "symlinked_repo"
            symlinked_repo_root.symlink_to(real_root, target_is_directory=True)

            with self.assertRaises(CleanupRefused):
                execute_index_cleanup(
                    symlinked_repo_root / "indices" / "hg38",
                    index_manifest_present=True,
                    mapping_outputs_present=True,
                    reconciliation_passed=True,
                    repo_root=symlinked_repo_root,
                    build="hg38",
                )
            self.assertTrue((real_root / "indices" / "hg38" / "hg38.bwt").is_file())

    def test_arbitrary_indices_dir_not_matching_repo_root_is_refused(self):
        """The target must equal exactly repo-root/indices/<build> — an
        otherwise well-shaped 'indices/<build>' path rooted elsewhere is
        refused, never accepted merely because its own name/parent match.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_root = tmp_path / "repo"
            repo_root.mkdir()
            elsewhere_indices = tmp_path / "elsewhere" / "indices" / "hg38"
            elsewhere_indices.mkdir(parents=True)
            (elsewhere_indices / "hg38.bwt").write_bytes(b"x")

            with self.assertRaises(CleanupRefused):
                execute_index_cleanup(
                    elsewhere_indices,
                    index_manifest_present=True,
                    mapping_outputs_present=True,
                    reconciliation_passed=True,
                    repo_root=repo_root,
                    build="hg38",
                )
            self.assertTrue(elsewhere_indices.exists())

    def test_wrong_reference_uses_actual_derive_record_not_a_hardcoded_guess(self):
        """B1-C4: the actual accepted reference (as derive.json recorded it)
        must be used as the cleanup guard — never a hardcoded
        references/derived/<build>/reference.fna guess that could miss a
        nonstandard --derived-dir root and silently allow an unsafe cleanup.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            derived_dir = tmp_path / "custom_derived_root"
            index_dir = indices_dir / "hg38"

            from test_coordinates_runner_b1 import _write_realistic_cleanup_evidence

            _write_realistic_cleanup_evidence(
                output_dir=output_dir, index_dir=index_dir, build="hg38", reconciliation_status="passed"
            )
            # The actual accepted reference is INSIDE the index directory
            # itself (a pathological but real configuration mistake the
            # hardcoded-guess version would never have caught, since its
            # guess -- references/derived/hg38/reference.fna -- would never
            # match this nonstandard --derived-dir root).
            nested_reference = index_dir / "reference.fna"
            nested_reference.write_text(">chr1\nACGT\n")
            (derived_dir / "hg38").mkdir(parents=True)
            (derived_dir / "hg38" / "derive.json").write_text(
                json.dumps({"executed": True, "output_fasta": str(nested_reference)})
            )

            with self.assertRaises(SystemExit):
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(output_dir),
                        "--indices-dir", str(indices_dir),
                        "--derived-dir", str(derived_dir),
                        "--repo-root", str(tmp_path),
                        "--cleanup-index", "hg38",
                    ]
                )
            self.assertTrue(index_dir.exists())

    def test_altered_report_after_provenance_recorded_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            index_dir = indices_dir / "hg38"

            from test_coordinates_runner_b1 import _write_realistic_cleanup_evidence

            _write_realistic_cleanup_evidence(
                output_dir=output_dir, index_dir=index_dir, build="hg38", reconciliation_status="passed"
            )
            # The report still says "passed", but its bytes were altered
            # after provenance.json recorded its hash.
            (output_dir / "hg38" / "report.json").write_text(
                json.dumps({"reconciliation": {"status": "passed"}, "tampered": True})
            )

            with self.assertRaises(SystemExit):
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(output_dir),
                        "--indices-dir", str(indices_dir),
                        "--repo-root", str(tmp_path),
                        "--cleanup-index", "hg38",
                    ]
                )
            self.assertTrue(index_dir.exists())

    def test_completed_receipt_preserves_pre_deletion_hashes(self):
        """Reproduces the exact B1-C4 defect: the completed receipt must
        NEVER recompute (and thereby null out) hashes for paths that no
        longer exist after deletion.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"
            index_dir = indices_dir / "hg38"

            from test_coordinates_runner_b1 import _write_realistic_cleanup_evidence

            _write_realistic_cleanup_evidence(
                output_dir=output_dir, index_dir=index_dir, build="hg38", reconciliation_status="passed"
            )

            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(output_dir),
                    "--indices-dir", str(indices_dir),
                    "--repo-root", str(tmp_path),
                    "--cleanup-index", "hg38",
                ]
            )
            receipt = json.loads((output_dir / "hg38" / "cleanup_receipts" / "hg38_index_cleanup_receipt.json").read_text())
            self.assertTrue(receipt["completed"])
            self.assertTrue(receipt["files"])
            for entry in receipt["files"]:
                self.assertIsNotNone(entry["sha256"])
                self.assertIsNotNone(entry["byte_size"])


class C5CheckpointStageCrossingTests(unittest.TestCase):
    """B1-C5: an explicit --stage list must never name more than one
    build-scoped stage in a real --allow-mapping invocation.
    """

    def test_mixed_b3_b4_stage_list_is_rejected_before_data_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        # A nonexistent CSV: if the check ran late (after
                        # opening the CSV), this would instead fail with a
                        # file-not-found error.
                        "--csv", str(Path(tmp) / "does_not_exist.csv"),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(Path(tmp) / "out"),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                        "--stage", "download", "--stage", "derive", "--stage", "index",
                        "--stage", "align", "--stage", "exact_match", "--stage", "report",
                    ]
                )
            self.assertIn("exactly one build-scoped stage", str(ctx.exception))

    def test_single_build_scoped_stage_with_data_prep_stages_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Must not raise the checkpoint-crossing SystemExit (it may
            # still fail later for unrelated reasons, e.g. no reference).
            try:
                main(
                    [
                        "--config", str(FIXTURE_CONFIG),
                        "--csv", str(FIXTURE_CSV),
                        "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                        "--output-dir", str(Path(tmp) / "out"),
                        "--allow-mapping",
                        "--host-role", "approved_mac",
                        "--build", "hg38",
                        "--stage", "sample", "--stage", "decode", "--stage", "controls", "--stage", "align",
                    ]
                )
            except SystemExit as exc:
                self.assertNotIn("exactly one build-scoped stage", str(exc))

    def test_dry_run_multi_stage_plan_is_still_permitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            main(
                [
                    "--config", str(FIXTURE_CONFIG),
                    "--csv", str(FIXTURE_CSV),
                    "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                    "--output-dir", str(Path(tmp) / "out"),
                    "--allow-mapping",
                    "--host-role", "approved_mac",
                    "--build", "hg38",
                    "--dry-run",
                    "--stage", "sample", "--stage", "decode", "--stage", "controls",
                    "--stage", "align", "--stage", "exact_match", "--stage", "report",
                ]
            )  # must not raise


class C6RestartValidityAndWarningTests(unittest.TestCase):
    """B1-C6: current index-record/manifest/file evidence must be part of
    index/align restart validity, and the literal minimap2 multi-part
    warning text must be rejected regardless of stat-line count.
    """

    def test_check_minimap2_mapping_stderr_flags_the_literal_warning_text(self):
        violations = check_minimap2_mapping_stderr(
            "For a multi-part index, no @SQ lines will be outputted. "
            "Please use \"samtools dict\" to obtain @SQ lines.\n"
        )
        self.assertTrue(violations)
        self.assertTrue(any("multi-part index warning" in v for v in violations))

    def test_altered_index_file_is_not_silently_skipped_on_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA_FULL)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2_FULL)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 40 + "\n")
            manifest_path = tmp_path / "manifest.json"
            _write_reference_manifest(manifest_path, build="hg38", reference=reference)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--indices-dir", str(indices_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest_path}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample", "--stage", "decode", "--stage", "controls", "--stage", "index"])
                index_record = json.loads((indices_dir / "hg38" / "index.json").read_text())
                self.assertTrue(index_record["executed"])

                # Corrupt an actual index file on disk without touching
                # index.json/state.json at all.
                bwt_path = Path(index_record["bwa_index_prefix"] + ".bwt")
                bwt_path.write_bytes(bwt_path.read_bytes() + b"\x00corruption")

                # A non-forced re-run with identical arguments (matching
                # fingerprint) must NOT silently print "skip" and leave the
                # corrupted evidence unexamined.
                main([*common, "--stage", "index"])

            new_index_record = json.loads((indices_dir / "hg38" / "index.json").read_text())
            # The stage actually re-ran (a fresh generation was produced),
            # rather than being skipped as "already completed".
            self.assertNotEqual(new_index_record["bwa_index_prefix"], index_record["bwa_index_prefix"])
            self.assertTrue(new_index_record["executed"])

    def test_align_restart_skip_revalidates_the_currently_resolved_index_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA_FULL)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2_FULL)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 40 + "\n")
            manifest_path = tmp_path / "manifest.json"
            _write_reference_manifest(manifest_path, build="hg38", reference=reference)
            output_dir = tmp_path / "out"
            indices_dir = tmp_path / "indices"

            common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--indices-dir", str(indices_dir),
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest_path}",
                "--build", "hg38",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*common, "--stage", "sample", "--stage", "decode", "--stage", "controls", "--stage", "index"])
                main([*common, "--stage", "align"])
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                self.assertTrue(align_record["executed"])
                index_record = json.loads((indices_dir / "hg38" / "index.json").read_text())

                # Corrupt the index binding align depends on (its manifest's
                # own reference_sha256), without ever re-running the index
                # stage or changing align's declared inputs/flags.
                index_manifest_path = Path(index_record["index_manifest_path"])
                payload = json.loads(index_manifest_path.read_text())
                payload["reference_sha256"] = "0" * 64
                index_manifest_path.write_text(json.dumps(payload))

                # A non-forced re-run of align with identical arguments
                # (matching fingerprint) must re-verify the current index
                # binding and refuse to reuse it, never silently "skip".
                with self.assertRaises(SystemExit) as ctx:
                    main([*common, "--stage", "align"])
            self.assertIn("stale/foreign index", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
