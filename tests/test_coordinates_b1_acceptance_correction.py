"""Regression coverage for the Task 001B checkpoint B1 acceptance
correction (docs/reviews/001b_b1_final_correction_review.md).

Commits ``905f0bd``/``1138022`` made ``report_state.json`` the transactional
selection record for the per-build report artifact set, but three downstream
consumers -- ``stage_combined_report``, ``_write_provenance``, and cleanup --
still read the mutable, non-transactional fixed-path mirrors
(``report.json``/``report.md``/``mappings.tsv.gz``/``reference_index.json``)
instead. Every test here demonstrably fails against commit ``1138022`` for
the reason stated and targets exactly one bullet of that review's "Required
correction" list. Fixtures are tiny and synthetic throughout; the real CSV is
never opened and no NCBI URL is ever requested (B1's authorization
boundary), consistent with the rest of the coordinate-runner test suite.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.manifest import manifest_content_sha256
from rbpbench.coordinates.runner import (
    _load_accepted_report_state,
    _write_provenance,
    main,
    stage_combined_report,
    stage_report,
)
from rbpbench.coordinates.sampling import SampleAssignment, SamplingResult

from test_coordinates_runner import (
    FIXTURE_CONFIG,
    FIXTURE_CSV,
    FIXTURE_EXECUTION_SOURCES,
    _FAKE_BWA,
    _FAKE_MINIMAP2,
    _FAKE_SEQKIT,
    _approved_host_context,
    _write_fake_executable,
    _write_reference_manifest,
)


def _cfg():
    from rbpbench.coordinates.config import load_config

    return load_config(FIXTURE_CONFIG)


def _tiny_sample() -> SamplingResult:
    assignment = SampleAssignment(sample_id="row_0", row_index=0, stratum="representative", labels=(1, 0))
    return SamplingResult(
        assignments=(assignment,),
        representative_ids=frozenset({"row_0"}),
        quota_ids=frozenset(),
        filler_ids=frozenset(),
        unsatisfied_quotas=(),
    )


def _mapping_evaluated_report_kwargs(tmp_path: Path, build_dir: Path) -> dict:
    """A minimal, real mapping-evaluated ``stage_report`` fixture: empty but
    real SAM/BED files with matching align/exact_match records, so the
    accepted report_state.json genuinely has a mappings.tsv.gz and
    reconciliation actually passes (never merely "not_evaluated").
    """
    reference = tmp_path / "reference.fasta"
    reference.write_text(">chr1\n" + "A" * 20 + "\n")
    manifest = json.loads(
        _write_reference_manifest(tmp_path / "manifest.json", build="hg38", reference=reference).read_text()
    )
    bwa_sam = tmp_path / "align_bwa_mem.sam"
    mm2_sam = tmp_path / "align_minimap2_splice.sam"
    bed = tmp_path / "exact_match_hits.bed"
    bwa_sam.write_text("")
    mm2_sam.write_text("")
    bed.write_text("")
    align_record = {
        "executed": True,
        "reference_sha256": manifest["sha256"],
        "reference_manifest_content_sha256": manifest_content_sha256(manifest),
        "sam_paths": {"bwa_mem": str(bwa_sam), "minimap2_splice": str(mm2_sam)},
    }
    exact_match_record = {
        "executed": True,
        "reference_sha256": manifest["sha256"],
        "reference_manifest_content_sha256": manifest_content_sha256(manifest),
        "bed_path": str(bed),
    }
    return dict(
        cfg=_cfg(),
        build_output_dir=build_dir,
        expected_total=1,
        expected_representative=1,
        expected_controls=0,
        build="hg38",
        align_record=align_record,
        exact_match_record=exact_match_record,
        reference=reference,
        reference_manifest=manifest,
    )


class SelectedGenerationIndependentOfMirrorsTests(unittest.TestCase):
    """Required regression 1: a valid selected generation remains usable
    when every mirror is missing or corrupt.
    """

    def test_combined_report_succeeds_when_every_mirror_is_missing_or_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            build_dir = tmp_path / "hg38"
            sample = _tiny_sample()
            stage_report(sample, **_mapping_evaluated_report_kwargs(tmp_path, build_dir))

            # Every human-convenience mirror is now missing or corrupt; the
            # SELECTED report_state.json generation is untouched.
            (build_dir / "report.json").unlink()
            (build_dir / "report.md").write_text("not the accepted content")
            (build_dir / "mappings.tsv.gz").write_bytes(b"not even a valid gzip stream")

            combined = stage_combined_report(sample, cfg=_cfg(), output_dir=tmp_path, builds=("hg38",))
            self.assertIn("representative_stratum_gate", combined["per_build"]["hg38"])


class InterruptionBetweenMirrorWritesTests(unittest.TestCase):
    """Required regression 2: interruption immediately after the pointer
    commit and between each mirror write cannot make combined reporting or
    provenance consume stale evidence (cleanup's independent coverage lives
    in test_coordinates_b1_second_corrections.py/test_coordinates_b1_final_corrections.py).
    """

    def test_combined_report_and_provenance_survive_interruption_between_mirror_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            build_dir = tmp_path / "hg38"
            sample = _tiny_sample()
            kwargs = _mapping_evaluated_report_kwargs(tmp_path, build_dir)

            original_write_text = Path.write_text

            def flaky_write_text(self, *args, **kw):
                # Simulate a crash exactly after report_state.json (the
                # atomic pointer commit) and the report.json mirror write,
                # but before the report.md mirror write.
                if self.parent == build_dir and self.name == "report.md":
                    raise OSError("simulated interruption between mirror writes")
                return original_write_text(self, *args, **kw)

            with mock.patch.object(Path, "write_text", flaky_write_text):
                with self.assertRaises(OSError):
                    stage_report(sample, **kwargs)

            # report_state.json -- the authoritative pointer, committed
            # BEFORE any mirror -- is intact and hash-verifies cleanly.
            report_state, violations = _load_accepted_report_state(build_dir)
            self.assertEqual(violations, ())
            self.assertTrue(report_state["executed"])

            # A genuinely partially-refreshed mirror set: report.json exists
            # (written first), report.md does not (the simulated crash
            # point).
            self.assertTrue((build_dir / "report.json").is_file())
            self.assertFalse((build_dir / "report.md").is_file())

            # combined_report must still succeed, reading only the selected
            # generation.
            cfg = _cfg()
            combined = stage_combined_report(sample, cfg=cfg, output_dir=tmp_path, builds=("hg38",))
            self.assertIn("representative_stratum_gate", combined["per_build"]["hg38"])

            # provenance must attribute the SELECTED generation's exact
            # path/hash, never fall back to "whatever exists at the fixed
            # mirror path" (report.md's mirror does not exist at all).
            provenance = _write_provenance(
                cfg=cfg,
                output_dir=tmp_path,
                csv_path=FIXTURE_CSV,
                config_path=FIXTURE_CONFIG,
                dataset_audit_path=None,
                proteins_config_path=None,
                builds=("hg38",),
                index_records={},
                align_records={"hg38": kwargs["align_record"]},
                exact_match_records={"hg38": kwargs["exact_match_record"]},
                reference_manifests={"hg38": kwargs["reference_manifest"]},
                state={},
            )
            recorded_md = provenance["builds"]["hg38"]["generated_artifacts"]["report_md"]
            self.assertEqual(recorded_md["path"], report_state["report_md_path"])
            self.assertEqual(recorded_md["sha256"], report_state["report_md_sha256"])
            self.assertNotEqual(recorded_md["path"], str(build_dir / "report.md"))


class SelectedGenerationTamperingFailsClosedTests(unittest.TestCase):
    """Required regression 3: selected-generation tampering fails closed
    even when mirrors look valid (cleanup's counterpart lives in
    test_coordinates_b1_second_corrections.py/test_coordinates_b1_final_corrections.py).
    """

    def test_combined_report_refuses_a_tampered_selected_generation_even_with_valid_mirrors(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            build_dir = tmp_path / "hg38"
            sample = _tiny_sample()
            stage_report(sample, **_mapping_evaluated_report_kwargs(tmp_path, build_dir))
            report_state = json.loads((build_dir / "report_state.json").read_text())
            # The mirrors are left exactly as stage_report wrote them --
            # "look valid" is deliberate; only the SELECTED generation is
            # tampered.
            self.assertTrue((build_dir / "report.json").is_file())

            Path(report_state["report_json_path"]).write_text(
                json.dumps({"reconciliation": {"status": "passed"}, "tampered": True})
            )

            with self.assertRaises(SystemExit):
                stage_combined_report(sample, cfg=_cfg(), output_dir=tmp_path, builds=("hg38",))


class ForcedReportRebuildInvalidatesCombinedReportTests(unittest.TestCase):
    """Required regressions 4 and 5: a forced same-input report rebuild
    whose accepted evidence actually changed (a new generation_digest) must
    invalidate a prior combined-report completion, and provenance must
    record the exact selected-generation paths/hashes throughout.
    """

    def test_forced_report_rebuild_invalidates_combined_report_and_provenance_tracks_selected_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "out"
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _write_fake_executable(bin_dir, "bwa", _FAKE_BWA)
            _write_fake_executable(bin_dir, "minimap2", _FAKE_MINIMAP2)
            _write_fake_executable(bin_dir, "seqkit", _FAKE_SEQKIT)
            reference = tmp_path / "reference.fasta"
            reference.write_text(">chr1\n" + "A" * 20 + "\n")
            manifest = _write_reference_manifest(tmp_path / "hg38_manifest.json", build="hg38", reference=reference)

            base_common = [
                "--config", str(FIXTURE_CONFIG),
                "--csv", str(FIXTURE_CSV),
                "--execution-sources", str(FIXTURE_EXECUTION_SOURCES),
                "--output-dir", str(output_dir),
                "--build", "hg38",
            ]
            map_common = [
                *base_common,
                "--allow-mapping",
                "--host-role", "approved_mac",
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
            ]
            report_common = [
                *base_common,
                "--reference", f"hg38={reference}",
                "--reference-manifest", f"hg38={manifest}",
            ]
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
            with mock.patch.dict(os.environ, env), _approved_host_context():
                main([*base_common, "--stage", "sample"])
                main([*base_common, "--stage", "decode"])
                main([*base_common, "--stage", "controls"])
                main([*map_common, "--stage", "align"])
                main([*map_common, "--stage", "exact_match"])
                main([*report_common, "--stage", "report"])
                main([*report_common, "--stage", "combined_report"])

                original_report_state = json.loads((output_dir / "hg38" / "report_state.json").read_text())
                original_combined_text = (output_dir / "report.json").read_text()
                provenance = json.loads((output_dir / "provenance.json").read_text())
                recorded = provenance["builds"]["hg38"]["generated_artifacts"]

                # Required regression 5: provenance identifies the EXACT
                # selected report_state.json generation's paths/hashes, not
                # the fixed-path mirrors.
                mirror_report_json = str(output_dir / "hg38" / "report.json")
                self.assertEqual(recorded["report_json"]["path"], original_report_state["report_json_path"])
                self.assertEqual(recorded["report_json"]["sha256"], original_report_state["report_json_sha256"])
                self.assertEqual(recorded["report_md"]["path"], original_report_state["report_md_path"])
                self.assertEqual(recorded["mappings_tsv_gz"]["path"], original_report_state["mappings_tsv_gz_path"])
                self.assertNotEqual(recorded["report_json"]["path"], mirror_report_json)

                # Change the accepted primary-mode mapping evidence WITHOUT
                # touching align.json's own recorded fingerprint/hash (a
                # report-only forced re-run never re-validates align) -- the
                # first BWA record becomes unmapped. align's own SAM lives
                # inside its accepted generation directory (align.json
                # names the exact path), never at a fixed mirror.
                align_record = json.loads((output_dir / "hg38" / "align.json").read_text())
                bwa_sam_path = Path(align_record["sam_paths"]["bwa_mem"])
                lines = bwa_sam_path.read_text().splitlines()
                self.assertTrue(lines)
                fields = lines[0].split("\t")
                fields[2] = "*"  # RNAME -> unmapped
                lines[0] = "\t".join(fields)
                bwa_sam_path.write_text("\n".join(lines) + "\n")

                main([*report_common, "--stage", "report", "--force"])
                new_report_state = json.loads((output_dir / "hg38" / "report_state.json").read_text())
                # The report's accepted evidence genuinely changed: a new
                # generation_digest, distinct report content.
                self.assertNotEqual(new_report_state["generation_digest"], original_report_state["generation_digest"])
                self.assertNotEqual(new_report_state["report_json_sha256"], original_report_state["report_json_sha256"])

                # Required regression 4: combined_report, re-run WITHOUT
                # --force, must NOT silently skip over this new generation
                # -- the top-level combined report must reflect the new
                # data, never the stale one.
                main([*report_common, "--stage", "combined_report"])
                new_combined_text = (output_dir / "report.json").read_text()
                self.assertNotEqual(new_combined_text, original_combined_text)

                provenance2 = json.loads((output_dir / "provenance.json").read_text())
                recorded2 = provenance2["builds"]["hg38"]["generated_artifacts"]
                self.assertEqual(recorded2["report_json"]["path"], new_report_state["report_json_path"])
                self.assertEqual(recorded2["report_json"]["sha256"], new_report_state["report_json_sha256"])
                self.assertNotEqual(recorded2["report_json"]["sha256"], recorded["report_json"]["sha256"])


if __name__ == "__main__":
    unittest.main()
